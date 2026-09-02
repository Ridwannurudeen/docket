"""The paired experiment protocol, registered before either arm runs.

V3 keeps two different hashes because its registration has two different moments. The
stage-one protocol hash covers every choice that can affect the result: the question,
claim, arms, selection and truth rules, rubric, evaluators, timing, failure policy and
the path where the cases will later be frozen. Stage two may add only the SHA-256 of that
referenced input file. The stage-one hash therefore stays stable while the composite
spec hash changes, and git can show whether the protocol really preceded the input lock.

The input digest is SHA-256 over the file's exact bytes, using the same bare lowercase
64-hex convention as the v2 datasets. Object identities use ``canonical_hash`` and keep
its ``0x`` prefix. These are deliberately different recipes: canonical JSON identifies
a protocol independent of formatting, while an input lock must detect even a changed
newline in the referenced artifact.

No file can prove its own history. A person can still rewrite a protocol and both hashes;
the persisted stage-one hash makes that rewrite visible against the earlier git commit.
``save`` additionally refuses an in-place stage-two transition that changes anything
except ``inputs_sha256``, and ``assert_runnable`` reopens the referenced file immediately
before a harness may run an arm.
"""

import hashlib
import hmac
import json
import math
import re
from base64 import b64decode
from binascii import Error as Base64Error
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ...hire.receipts import canonical_hash

ARMS = ("agent", "manual")
ARM_FIELDS = frozenset({"what_it_does", "who_runs_it", "what_is_recorded"})
# The result-affecting choices a runner must not be left to make. `arm_block_order` fixes
# whether the human or the service goes first across the whole family — running every manual
# case before any agent case is stronger than alternating, because the operator then never
# sees a service answer before finishing their own. `blinding_seed_recipe` and
# `blinding_parity` pin the exact bytes and the even/odd meaning, without which "reproducible
# A/B" is only reproducible by the code that happened to run. `normalisation_version` names
# the projection that strips arm tells, so a later change to it is visible as a different
# protocol rather than a silent re-scoring. `score_sheet_hash_recipe` and `sheets_per_seat`
# fix how a sheet is identified and that exactly one arrives per seat — no patches, no
# replacements after a disappointing sheet.
EXECUTION_FIELDS = frozenset(
    {
        "arm_block_order",
        "blinding_seed_recipe",
        "blinding_parity",
        "normalisation_version",
        "score_sheet_hash_recipe",
        "sheets_per_seat",
        "agent_endpoint",
        "agent_service_id",
        "agent_request_contract",
    }
)
# Only one order is honest here: a human who has seen the service's answer cannot un-see it.
MANUAL_FIRST = "all_manual_primaries_then_all_agent_primaries"
CASE_SELECTION_FIELDS = frozenset(
    {"rule", "chosen_by", "excluded", "population", "truth_source"}
)
CRITERION_FIELDS = frozenset(
    {
        "name",
        "score_3_means",
        "score_2_means",
        "score_1_means",
        "score_0_means",
    }
)
EVALUATOR_FIELDS = frozenset({"evaluator_id"})
SCORING_FIELDS = frozenset(
    {"randomisation", "disagreement", "selection_rule", "calibration"}
)
CORRECTION_FIELDS = frozenset(
    {"status", "supersedes_stage_one_protocol_hash", "reason"}
)
SUCCESSOR_FIELDS = frozenset(
    {
        "status",
        "prior_spec_id",
        "prior_stage_one_protocol_hash",
        "prior_spec_hash",
        "prior_ledger_ref",
        "reason",
    }
)
SPEED_FIELDS = frozenset(
    {
        "formula",
        "material_if",
        "minimum_median_seconds_saved",
        "maximum_median_agent_to_manual_ratio",
        "requires_complete_pairs",
    }
)
TIMING_TEXT_FIELDS = frozenset(
    {"clock", "start_event", "stop_event", "interruptions", "operator_control"}
)
STAGE_TWO_FIELDS = frozenset({"inputs_sha256"})
SHA256 = re.compile(r"[0-9a-f]{64}")
OBJECT_HASH = re.compile(r"0x[0-9a-f]{64}")
ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")
REPO_ROOT = Path(__file__).resolve().parents[3]
RANGE_POSITION_MANAGER = "0x46a15b0b27311cedf172ab29e4f4766fbe7f4364"
RANGE_MASTER_CHEF = "0x556b9306565093c855aea9ae92a594704c2cd59e"

# Positions the experiment party controls. The Range population enumerates every live v3
# position on chain, so without this the sampler could draw Docket's own demonstration LP
# into Docket's own evidence. Registering the list is not enough on its own: a registration
# that omitted a known controlled position would still lock, so the constants below are the
# floor the registration must cover, and the registration is the hash-bound part that cannot
# drift afterwards. Neither layer survives both attacks alone.
RANGE_CONTROLLED_WALLETS = frozenset({"0xe55816904796341bf8535e25f6c8b647927fc946"})
RANGE_CONTROLLED_TOKEN_IDS = frozenset({7141050})
RANGE_CONFLICT_REASON = "experiment_party_controlled"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
YIELD_SOURCE_URLS = {
    "pools": "https://explorer.pancakeswap.com/api/cached/pools/v3/bsc/list/top",
    "token_list": "https://tokens.pancakeswap.finance/pancakeswap-extended.json",
}
RANGE_CAPTURE_NOT_BEFORE = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)
YIELD_CAPTURE_NOT_BEFORE = datetime(2026, 8, 26, 12, tzinfo=timezone.utc)
YIELD_CAPTURE_ATTEMPTS = tuple(
    YIELD_CAPTURE_NOT_BEFORE + timedelta(minutes=offset) for offset in range(3)
)
YIELD_ASSISTED_CAPTURE_ATTEMPTS = tuple(
    datetime(2026, 9, 3, 12, tzinfo=timezone.utc) + timedelta(minutes=offset)
    for offset in range(3)
)
YIELD_PRIOR_STAGE_ONE_PROTOCOL_HASH = (
    "0x10d0fb31ea70c4bb31581952b99b6776d5f25d2c51bdf9543d47d07781266d3c"
)
YIELD_PRIOR_SPEC_HASH = (
    "0xad391e9aa3b039ee5e43397d488deb25893253d3376b08ff544c5651566395d9"
)
YIELD_PRIOR_LEDGER_REF = "docket/advantage/v3/runs/v3-02-yield-router.jsonl"
YIELD_SUCCESSOR_REASON = (
    "The v3-02 official ledger remains published with manual primary "
    "v3-02-yield-router::yield-01-916f992d::manual::primary failed as "
    "invoke_error after 11219000000 ns. This is a distinct successor with new future "
    "source captures and a disclosed Codex-assisted baseline; it does not replace, "
    "retry or relabel that failed primary."
)
RANGE_PRIOR_STAGE_ONE_PROTOCOL_HASH = (
    "0x2a83c1a331d579e5cef461d52c539711b4fa2bba6dd397aaad1bf38b6b47f9ab"
)
RANGE_PRIOR_SPEC_HASH = (
    "0x2a15b50e88b164ff57a7256aa9e35bdfb539cb02549e9c1374641fef92b4a43a"
)
RANGE_PRIOR_LEDGER_REF = "docket/advantage/v3/runs/v3-05-range-doctor.jsonl"
RANGE_SUCCESSOR_REASON = (
    "The v3-05 official ledger remains separate and unchanged. As recorded there, "
    "manual primary "
    "v3-05-range-doctor::range-passing_gate_in_range-5223058::manual::primary "
    "terminated as interrupted with no recorded elapsed time, which fires v3-05's "
    "any_pair_is_incomplete check and leaves refuted as its only terminal state. That "
    "ledger is operator-held evidence outside the tracked tree at this registration: a "
    "reader who cannot see it should treat this motivation as unverified and judge this "
    "family on its own registered protocol instead. This is a distinct successor with a "
    "new archive-pinned frame, a new future pool-truth capture and a paid agent arm; it "
    "does not replace, retry or relabel that primary, and it does not relabel v3-05's "
    "published state."
)
# Cases whose frozen reveal the operator has already seen. Token 5223058 was revealed in
# full during the interrupted v3-05 slot on 2026-08-30; the other two are v3-05's remaining
# registered cases, published in its committed input envelope. Excluding all three costs the
# successor nothing and removes the only positions an operator could answer from memory.
# Equality, not a floor, for the same reason as RANGE_CONTROLLED_TOKEN_IDS: a list free to
# grow could delete an honest third party's position from the draw on an unfalsifiable claim.
RANGE_PRIOR_EXPOSURE_TOKEN_IDS = frozenset({1056809, 1653348, 5223058})
RANGE_PRIOR_EXPOSURE_REASON = "operator_saw_this_case_in_the_predecessor"
RANGE_PRIOR_EXPOSURE_SPEC_ID = "v3-05-range-doctor"
# Who each arm actually is. v3-06 registers that its baseline is not a human; this family
# registers the opposite for its manual arm and, for the agent arm, that the hire is settled
# rather than served from the free allowance. Both are claims a reader would otherwise have
# to take on trust, and both change what the comparison means.
RANGE_SUCCESSOR_ARM_IDENTITIES = {
    "agent": {
        "arm": "agent",
        "authorization": "canary_authorized_x402_exact",
        "display_name": "Deployed Range Doctor, settled hire",
        "free_tier": False,
        "human": False,
        "independent": False,
        "kind": "settled_public_hire",
    },
    "manual": {
        "arm": "manual",
        "display_name": "Human operator",
        "human": True,
        "independent": False,
        "kind": "human_operator",
        "operator": "owner",
    },
}
# A distinct successor answers a published predecessor rather than correcting an unlocked
# registration, so it carries successor_provenance instead of protocol_correction.
DISTINCT_SUCCESSOR_SPEC_IDS = frozenset(
    {"v3-06-yield-router-assisted", "v3-07-range-doctor"}
)
WARDEN_AUTHORABLE_CLASSES = frozenset(
    {
        "DRAIN_ADDRESS",
        "ENCODING_TRICK",
        "HIDDEN_UNICODE",
        "MALICIOUS_LINK",
        "PROMPT_INJECTION",
        "ROLE_OVERRIDE",
        "SECRET_EXFIL",
        "TOOL_HIJACK",
        "WEB3_INJECTION",
    }
)
WARDEN_BLOCKED_CLASSES = frozenset({"DRAIN_ADDRESS", "SECRET_EXFIL"})

# Three is the smallest number that can show a spread rather than a pair of points. It is a
# floor, not a target: each registered family below plans five or twelve.
MIN_CASES = 3
MIN_EVALUATORS = 2
MIN_CRITERIA = 2


def is_warden_family(spec: "PairedSpec") -> bool:
    """Whether a registered family uses the Warden security protocol."""
    return spec.category == "security"


def is_range_family(spec: "PairedSpec") -> bool:
    """Whether a registered family uses the Range Doctor service protocol."""
    return spec.execution_protocol.get("agent_service_id") == "range-doctor"


def is_range_successor_family(spec: "PairedSpec") -> bool:
    """Whether a Range family draws its cases from an enumerable archive-pinned frame."""
    return is_range_family(spec) and "frame_definition" in spec.case_selection


def is_yield_family(spec: "PairedSpec") -> bool:
    """Whether a registered family uses the Yield Router service protocol."""
    return spec.execution_protocol.get("agent_service_id") == "yield-router"


def _warden_policy_enabled(spec: "PairedSpec") -> bool:
    return spec.case_selection.get("labelling_policy") is not None


def _warden_expected_verdict(labels) -> str:
    labels = set(labels)
    if not labels:
        return "ALLOW"
    if labels & WARDEN_BLOCKED_CLASSES:
        return "BLOCK"
    return "SANITIZE"


def _validate_warden_policy(spec: "PairedSpec") -> None:
    policy = spec.case_selection.get("labelling_policy")
    if policy is None:
        return
    required = {
        "version",
        "all_applicable",
        "mechanism_and_action_classes_may_cooccur",
        "decoded_normalized_operative_content",
        "mere_mentions_are_labels",
        "evidence_span_per_label",
        "blocked_classes",
        "verdict_composition",
        "class_boundaries",
    }
    _required_fields(policy, required, "Warden labelling policy")
    if policy["version"] != "warden.all-applicable.v1":
        raise ValueError("spec: Warden labelling policy version is invalid")
    if any(
        policy[name] is not expected
        for name, expected in (
            ("all_applicable", True),
            ("mechanism_and_action_classes_may_cooccur", True),
            ("decoded_normalized_operative_content", True),
            ("mere_mentions_are_labels", False),
            ("evidence_span_per_label", True),
        )
    ):
        raise ValueError("spec: Warden labelling policy is not all-applicable")
    if set(policy["blocked_classes"]) != WARDEN_BLOCKED_CLASSES:
        raise ValueError(
            "spec: Warden blocked classes do not match the composition rule"
        )
    boundaries = policy["class_boundaries"]
    if (
        not isinstance(boundaries, dict)
        or set(boundaries) != WARDEN_AUTHORABLE_CLASSES
        or not all(
            isinstance(value, str) and value.strip() for value in boundaries.values()
        )
    ):
        raise ValueError("spec: Warden class boundaries are incomplete")
    if (
        not isinstance(policy["verdict_composition"], str)
        or not policy["verdict_composition"].strip()
    ):
        raise ValueError("spec: Warden verdict composition is blank")

    provenance = spec.pilot_provenance
    if not isinstance(provenance, dict):
        raise ValueError("spec: pilot-informed Warden policy needs pilot provenance")
    _required_fields(
        provenance,
        {
            "status",
            "prior_spec_id",
            "prior_stage_one_protocol_hash",
            "class_rule_authored_after_pilot",
            "original_registration_passed",
            "prompt_omission_fixed_at",
            "trial",
            "evidence",
        },
        "Warden pilot provenance",
    )
    if (
        provenance["status"] != "pilot_informed"
        or provenance["class_rule_authored_after_pilot"] is not True
        or provenance["original_registration_passed"] is not False
        or OBJECT_HASH.fullmatch(provenance["prior_stage_one_protocol_hash"]) is None
    ):
        raise ValueError("spec: Warden pilot provenance is invalid")
    trial = provenance["trial"]
    _required_fields(
        trial,
        {
            "hostile_decisions",
            "class_counts",
            "class_micro_f1",
            "qualification_floor",
            "qualified",
        },
        "Warden pilot trial",
    )
    counts = trial["class_counts"]
    decision = trial["hostile_decisions"]
    _required_fields(counts, {"tp", "fp", "fn"}, "Warden pilot class counts")
    _required_fields(decision, {"correct", "total"}, "Warden pilot decisions")
    denominator = 2 * counts["tp"] + counts["fp"] + counts["fn"]
    expected_f1 = 2 * counts["tp"] / denominator if denominator else 1.0
    if (
        decision != {"correct": 8, "total": 8}
        or counts != {"tp": 4, "fp": 3, "fn": 0}
        or not math.isclose(trial["class_micro_f1"], expected_f1)
        or trial["qualification_floor"] != 0.8
        or trial["qualified"] is not False
    ):
        raise ValueError("spec: Warden pilot figures are internally inconsistent")


def _blank_fields(body: dict, required: frozenset[str]) -> set[str]:
    return {name for name in required if not str(body.get(name, "")).strip()}


@dataclass(frozen=True)
class PairedSpec:
    """One registered agent-versus-human experiment, fixed at construction."""

    spec_id: str
    question: str
    category: str
    claim: str
    falsifier: str
    arms: dict
    case_selection: dict
    quality_rubric: dict
    scoring: dict
    speed_threshold: dict
    timing: dict
    measures: dict
    # Everything the runner would otherwise decide for itself. Each of these changes the
    # result, so each is registered before the inputs are locked rather than settled in code
    # once the outputs are visible: which arm block runs first, the exact bytes that derive
    # the A/B assignment, the projection that strips arm tells, and how a score sheet is
    # identified. A choice made in the runner is a choice made after registration.
    execution_protocol: dict
    n_planned: int
    stopping_rule: str
    registration_provenance: str
    protocol_correction: dict | None
    inputs_ref: str
    # Empty through stage one. ``lock_inputs`` is the only API that fills it from a file.
    inputs_sha256: str = ""
    pilot_provenance: dict | None = None
    successor_provenance: dict | None = None
    failure_policy: str = field(
        default=(
            "Every scheduled primary attempt is published. A technical failure, timeout, "
            "empty or malformed response scores zero, remains in every applicable "
            "denominator, and is never replaced by a scored retry."
        )
    )
    _registered_stage_one_protocol_hash: str = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self):
        # Frozen stops rebinding, not writes through a reference the caller kept. What was
        # validated must be the same object graph the hashes later identify.
        for name in (
            "arms",
            "case_selection",
            "quality_rubric",
            "scoring",
            "speed_threshold",
            "timing",
            "measures",
            "execution_protocol",
        ):
            object.__setattr__(self, name, deepcopy(getattr(self, name)))
        object.__setattr__(
            self, "protocol_correction", deepcopy(self.protocol_correction)
        )
        object.__setattr__(self, "pilot_provenance", deepcopy(self.pilot_provenance))
        object.__setattr__(
            self, "successor_provenance", deepcopy(self.successor_provenance)
        )

        for name in (
            "spec_id",
            "question",
            "category",
            "claim",
            "falsifier",
            "stopping_rule",
            "failure_policy",
            "registration_provenance",
            "inputs_ref",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(
                    f"spec: {name} is empty — it has to be fixed before the outputs exist"
                )

        ref = Path(self.inputs_ref)
        if ref.is_absolute() or ".." in ref.parts:
            raise ValueError(
                f"spec: inputs_ref {self.inputs_ref!r} is not a repository-relative path"
            )
        if self.inputs_sha256 and SHA256.fullmatch(self.inputs_sha256) is None:
            raise ValueError(
                "spec: inputs_sha256 must be empty at stage one or the bare lowercase "
                "64-hex SHA-256 of the referenced file's exact bytes"
            )

        if tuple(sorted(self.arms)) != tuple(sorted(ARMS)):
            raise ValueError(
                f"spec: arms are {sorted(self.arms)} — this report compares exactly "
                f"{sorted(ARMS)}"
            )
        for arm, body in self.arms.items():
            unsaid = _blank_fields(body, ARM_FIELDS)
            if unsaid:
                raise ValueError(
                    f"spec: the {arm} arm leaves {sorted(unsaid)} missing or blank"
                )

        if self.n_planned < MIN_CASES:
            raise ValueError(
                f"spec: n_planned is {self.n_planned}, fewer than {MIN_CASES}"
            )
        unsaid = _blank_fields(self.case_selection, CASE_SELECTION_FIELDS)
        if unsaid:
            raise ValueError(
                f"spec: case_selection leaves {sorted(unsaid)} missing or blank"
            )

        criteria = self.quality_rubric.get("criteria") or []
        if len(criteria) < MIN_CRITERIA:
            raise ValueError(
                f"spec: the rubric has {len(criteria)} criteria, fewer than {MIN_CRITERIA}"
            )
        names = []
        for criterion in criteria:
            unsaid = _blank_fields(criterion, CRITERION_FIELDS)
            if unsaid:
                raise ValueError(
                    f"spec: rubric criterion {criterion.get('name', '<unnamed>')!r} leaves "
                    f"{sorted(unsaid)} missing or blank"
                )
            names.append(criterion["name"])
        if len(set(names)) != len(names):
            raise ValueError("spec: rubric criterion names are not distinct")
        if not str(self.quality_rubric.get("scale", "")).strip():
            raise ValueError(
                "spec: the rubric names no scale, so its scores have no units"
            )

        evaluators = int(self.scoring.get("evaluators", 0))
        roster = self.scoring.get("evaluator_roster") or []
        if evaluators < MIN_EVALUATORS:
            raise ValueError(
                f"spec: {evaluators} evaluator(s) is fewer than {MIN_EVALUATORS}"
            )
        if len(roster) != evaluators:
            raise ValueError(
                f"spec: evaluator_roster has {len(roster)} seat ids for {evaluators} "
                "registered model seats"
            )
        evaluator_ids = []
        for evaluator in roster:
            unsaid = _blank_fields(evaluator, EVALUATOR_FIELDS)
            if unsaid:
                raise ValueError(
                    f"spec: evaluator {evaluator.get('evaluator_id', '<unnamed>')!r} leaves "
                    f"{sorted(unsaid)} missing or blank"
                )
            evaluator_ids.append(evaluator["evaluator_id"])
        if len(set(evaluator_ids)) != len(evaluator_ids):
            raise ValueError("spec: evaluator seat ids are not distinct")
        if self.scoring.get("blinded") is not True:
            raise ValueError("spec: scoring is not blinded")
        unsaid = _blank_fields(self.scoring, SCORING_FIELDS)
        if unsaid:
            raise ValueError(f"spec: scoring leaves {sorted(unsaid)} missing or blank")

        unsaid = _blank_fields(self.execution_protocol, EXECUTION_FIELDS)
        if unsaid:
            raise ValueError(
                f"spec: execution_protocol leaves {sorted(unsaid)} missing or blank — "
                "a result-affecting choice left out here is one the runner makes after "
                "registration, which is the objection this whole file answers"
            )
        if self.execution_protocol["arm_block_order"] != MANUAL_FIRST:
            raise ValueError(
                "spec: arm_block_order must be "
                f"{MANUAL_FIRST!r} — an operator who has seen the service's answer for any "
                "case cannot produce an independent manual arm for the ones that follow"
            )
        if self.execution_protocol["blinding_parity"] not in ("even_a_is_agent",):
            raise ValueError(
                "spec: blinding_parity must state which way an even digest maps, or the "
                "runner picks the polarity and 'reproducible' means only 'by that code'"
            )
        if int(self.execution_protocol["sheets_per_seat"]) != 1:
            raise ValueError(
                "spec: exactly one score sheet per seat — a second sheet is a replacement "
                "for one whose result was unwelcome"
            )
        expected_path = f"/hire/{self.execution_protocol['agent_service_id']}"
        if not self.execution_protocol["agent_endpoint"].endswith(expected_path):
            raise ValueError(
                "spec: agent_endpoint must end in the registered service hire path"
            )

        unsaid = _blank_fields(self.speed_threshold, SPEED_FIELDS)
        if unsaid:
            raise ValueError(
                f"spec: speed_threshold leaves {sorted(unsaid)} missing or blank"
            )
        seconds = self.speed_threshold["minimum_median_seconds_saved"]
        ratio = self.speed_threshold["maximum_median_agent_to_manual_ratio"]
        if (
            not isinstance(seconds, (int, float))
            or isinstance(seconds, bool)
            or seconds <= 0
        ):
            raise ValueError("spec: minimum median seconds saved must be positive")
        if (
            not isinstance(ratio, (int, float))
            or isinstance(ratio, bool)
            or not 0 < ratio < 1
        ):
            raise ValueError(
                "spec: maximum median agent/manual ratio must be between 0 and 1"
            )
        if self.speed_threshold["requires_complete_pairs"] is not True:
            raise ValueError("spec: fast failures cannot satisfy the speed threshold")

        unsaid = _blank_fields(self.timing, TIMING_TEXT_FIELDS)
        if unsaid:
            raise ValueError(f"spec: timing leaves {sorted(unsaid)} missing or blank")
        timeout = self.timing.get("timeout_seconds")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("spec: timing.timeout_seconds must be a positive integer")

        for measure in ("time", "cost"):
            if not str(self.measures.get(measure, "")).strip():
                raise ValueError(f"spec: measures.{measure} is blank")

        if (
            self.spec_id in DISTINCT_SUCCESSOR_SPEC_IDS
            and self.protocol_correction is not None
        ):
            raise ValueError(
                "spec: a distinct successor cannot be a protocol correction"
            )
        if (
            self.spec_id not in DISTINCT_SUCCESSOR_SPEC_IDS
            and self.protocol_correction is None
        ):
            raise ValueError("spec: protocol_correction is required for this family")
        if self.protocol_correction is not None:
            unsaid = _blank_fields(self.protocol_correction, CORRECTION_FIELDS)
            if unsaid:
                raise ValueError(
                    "spec: protocol_correction leaves "
                    f"{sorted(unsaid)} missing or blank"
                )
            if self.protocol_correction["status"] != "corrected_before_input_lock":
                raise ValueError(
                    "spec: protocol correction must be labelled "
                    "corrected_before_input_lock"
                )
            if (
                OBJECT_HASH.fullmatch(
                    self.protocol_correction["supersedes_stage_one_protocol_hash"]
                )
                is None
            ):
                raise ValueError(
                    "spec: protocol correction must name the superseded hash"
                )
        if is_warden_family(self):
            _validate_warden_policy(self)
        if is_range_successor_family(self):
            _validate_range_successor_registration(self)
        if self.spec_id == "v3-06-yield-router-assisted":
            _validate_yield_successor_registration(self)

        # The nested dicts remain ordinary JSON-shaped objects for deterministic saving.
        # Cache what construction validated so a later write through ``spec.scoring`` or
        # ``spec.quality_rubric`` cannot silently become a new registered protocol in memory.
        object.__setattr__(
            self,
            "_registered_stage_one_protocol_hash",
            canonical_hash(self._stage_one_body()),
        )

    @property
    def runnable(self) -> bool:
        """Whether this record claims a stage-two input lock exists."""
        return bool(self.inputs_sha256)

    @property
    def stage_one_protocol_hash(self) -> str:
        """Stable identity of every registered field except the later input digest."""
        return self._registered_stage_one_protocol_hash

    @property
    def spec_hash(self) -> str:
        """Composite identity; changes when the exact input bytes are locked."""
        return canonical_hash(self._body())

    def _stage_one_body(self) -> dict:
        body = {
            "spec_id": self.spec_id,
            "question": self.question,
            "category": self.category,
            "claim": self.claim,
            "falsifier": self.falsifier,
            "arms": dict(self.arms),
            "case_selection": dict(self.case_selection),
            "quality_rubric": dict(self.quality_rubric),
            "scoring": dict(self.scoring),
            "speed_threshold": dict(self.speed_threshold),
            "timing": dict(self.timing),
            "measures": dict(self.measures),
            "execution_protocol": dict(self.execution_protocol),
            "n_planned": self.n_planned,
            "stopping_rule": self.stopping_rule,
            "failure_policy": self.failure_policy,
            "registration_provenance": self.registration_provenance,
            "protocol_correction": (
                dict(self.protocol_correction)
                if self.protocol_correction is not None
                else None
            ),
            "inputs_ref": self.inputs_ref,
        }
        if self.pilot_provenance is not None:
            body["pilot_provenance"] = dict(self.pilot_provenance)
        if self.successor_provenance is not None:
            body["successor_provenance"] = dict(self.successor_provenance)
        return body

    def _body(self) -> dict:
        return self._stage_one_body() | {"inputs_sha256": self.inputs_sha256}

    def as_record(self) -> dict:
        self._assert_protocol_unchanged()
        return self._body() | {
            "stage_one_protocol_hash": self.stage_one_protocol_hash,
            "spec_hash": self.spec_hash,
        }

    def _assert_protocol_unchanged(self) -> None:
        actual = canonical_hash(self._stage_one_body())
        if not hmac.compare_digest(actual, self.stage_one_protocol_hash):
            raise ValueError(
                f"spec {self.spec_id!r} protocol was mutated after construction: the "
                f"registered stage-one hash is {self.stage_one_protocol_hash} and its "
                f"current fields give {actual}"
            )


def _inputs_path(spec: PairedSpec, repo_root: Path) -> Path:
    root = Path(repo_root).resolve()
    try:
        path = (root / spec.inputs_ref).resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(
            f"spec {spec.spec_id!r} references missing inputs {spec.inputs_ref!r}"
        ) from exc
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"spec {spec.spec_id!r} inputs_ref escapes the repository root"
        ) from exc
    if not path.is_file():
        raise ValueError(
            f"spec {spec.spec_id!r} inputs_ref {spec.inputs_ref!r} is not a file"
        )
    return path


def _required_fields(body: dict, required: set[str], context: str) -> None:
    missing = required - body.keys()
    if missing:
        raise ValueError(f"spec: {context} is missing {sorted(missing)}")


def _validate_locked_source(source: dict, repo_root: Path, context: str) -> bytes:
    _required_fields(source, {"ref", "sha256"}, context)
    if not isinstance(source["ref"], str) or not source["ref"].strip():
        raise ValueError(f"spec: {context} ref must be a nonblank string")
    ref = Path(source["ref"])
    if ref.is_absolute() or ".." in ref.parts:
        raise ValueError(f"spec: {context} ref is not repository-relative")
    if (
        not isinstance(source["sha256"], str)
        or SHA256.fullmatch(source["sha256"]) is None
    ):
        raise ValueError(f"spec: {context} digest is invalid")
    root = Path(repo_root).resolve()
    try:
        path = (root / ref).resolve(strict=True)
        path.relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(
            f"spec: {context} ref is missing or escapes the repository"
        ) from exc
    if not path.is_file():
        raise ValueError(f"spec: {context} ref is not a file")
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual, source["sha256"]):
        raise ValueError(f"spec: {context} source does not match its digest")
    return raw


def _locked_json(source: dict, repo_root: Path, context: str):
    raw = _validate_locked_source(source, repo_root, context)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"spec: {context} is not valid UTF-8 JSON") from exc


def _range_conflict_exclusion(spec: PairedSpec) -> tuple[set[str], set[int]]:
    """The registered conflict lists, checked against the ones this build knows about.

    The registration is what a reader can verify: it is inside the stage-one protocol hash,
    so it cannot be edited once a sample has been drawn against it. The constants are what
    stops a registration from being written that quietly leaves out a position we hold.
    """
    exclusion = spec.case_selection.get("conflict_exclusion")
    if not isinstance(exclusion, dict) or set(exclusion) != {
        "wallets",
        "token_ids",
        "excluded_reason",
    }:
        raise ValueError(
            "spec: Range case_selection needs a conflict_exclusion with exactly "
            "wallets, token_ids and excluded_reason"
        )
    if exclusion["excluded_reason"] != RANGE_CONFLICT_REASON:
        raise ValueError(
            f"spec: Range conflict exclusions must be recorded as {RANGE_CONFLICT_REASON!r}"
        )
    wallets = exclusion["wallets"]
    token_ids = exclusion["token_ids"]
    if (
        not isinstance(wallets, list)
        or not wallets
        or not all(
            isinstance(wallet, str)
            and wallet == wallet.lower()
            and ADDRESS.fullmatch(wallet)
            for wallet in wallets
        )
        or len(set(wallets)) != len(wallets)
    ):
        raise ValueError(
            "spec: Range conflict wallets must be distinct lowercase 20-byte addresses"
        )
    if (
        not isinstance(token_ids, list)
        or not all(
            isinstance(token_id, int)
            and not isinstance(token_id, bool)
            and token_id >= 0
            for token_id in token_ids
        )
        or len(set(token_ids)) != len(token_ids)
    ):
        raise ValueError(
            "spec: Range conflict token ids must be distinct non-negative integers"
        )
    if (
        set(wallets) != RANGE_CONTROLLED_WALLETS
        or set(token_ids) != RANGE_CONTROLLED_TOKEN_IDS
    ):
        # Equality, not a floor. A floor stops the list being written short, but leaves it
        # free to be padded — and padding an honest third party's wallet into it deletes
        # their positions from the draw deterministically, on a claim ("we control this")
        # that nobody outside can disprove. Requiring equality means growing the list takes
        # a code change and a re-registration together, both visible in git.
        raise ValueError(
            "spec: Range conflict exclusion does not match the positions this build knows "
            "the experiment party controls"
        )
    return set(wallets), set(token_ids)


def _range_successor_frame(spec: PairedSpec) -> dict:
    frame = spec.case_selection.get("frame_definition")
    if not isinstance(frame, dict):
        raise ValueError("spec: Range successor needs a frame_definition object")
    _required_fields(
        frame,
        {
            "version",
            "chain_id",
            "position_manager",
            "rpc_failure_policy",
            "master_chef",
            "observation_block",
            "observation_block_hash",
            "observation_time",
            "sample_size",
            "source_methods",
            "index_derivation",
            "collision_handling",
            "strata",
            "selection_rule",
            "pool_truth_capture_attempts",
            "pool_truth_sources",
            "complete_required",
        },
        "Range successor frame definition",
    )
    source_methods = [
        "eth_blockNumber",
        "eth_getBlockByNumber",
        "totalSupply",
        "tokenByIndex",
        "ownerOf",
        "userPositionInfos_if_farm_held",
        "positions_if_conflict_free",
        "getPool_and_slot0_per_unique_live_pool",
    ]
    if (
        frame["version"] != "range.enumerable-1024.v1"
        or frame["chain_id"] != 56
        or str(frame["position_manager"]).lower() != RANGE_POSITION_MANAGER
        or str(frame["master_chef"]).lower() != RANGE_MASTER_CHEF
        or not isinstance(frame["observation_block"], int)
        or isinstance(frame["observation_block"], bool)
        or frame["observation_block"] <= 0
        or not isinstance(frame["observation_block_hash"], str)
        or re.fullmatch(r"0x[0-9a-f]{64}", frame["observation_block_hash"]) is None
        or frame["sample_size"] != 1024
        or frame["source_methods"] != source_methods
        or frame["pool_truth_sources"] != YIELD_SOURCE_URLS
        or frame["rpc_failure_policy"]
        != (
            "Each registered JSON-RPC call is made once against DOCKET_ARCHIVE_RPC. "
            "Any transport, JSON-RPC, ABI, pinned-header or completeness failure aborts "
            "the frame without substituting an endpoint or retrying a sampled call."
        )
        or frame["complete_required"] is not True
    ):
        raise ValueError("spec: Range successor frame definition is invalid")
    _utc_timestamp(frame["observation_time"], "Range successor observation time")
    derivation = frame["index_derivation"]
    if not isinstance(derivation, dict) or derivation != {
        "counter_start": 0,
        "digest": "SHA-256",
        "integer_encoding": "unsigned_big_endian",
        "modulus": "totalSupply_at_observation_block",
        "preimage": (
            "UTF8(stage_one_protocol_hash || '|56|' || lowercase(position_manager) "
            "|| '|' || decimal(observation_block) || '|' || decimal(counter))"
        ),
    }:
        raise ValueError("spec: Range successor index derivation is invalid")
    strata = frame["strata"]
    expected_strata = [
        "passing_gate_in_range",
        "passing_gate_out_of_range",
        "nonzero_liquidity_failed_gate",
    ]
    if (
        not isinstance(strata, list)
        or [row.get("name") for row in strata if isinstance(row, dict)]
        != expected_strata
        or any(
            set(row) != {"name", "definition"}
            or not isinstance(row["definition"], str)
            or not row["definition"].strip()
            for row in strata
        )
        or frame["collision_handling"]
        != (
            "If index modulo totalSupply was already emitted, increment counter and "
            "hash again. sample_ordinal advances only after a new index is emitted."
        )
        or frame["selection_rule"]
        != {
            "digest": "SHA-256",
            "order": "ascending_digest",
            "preimage": (
                "UTF8(stage_one_protocol_hash || '|56|' || lowercase(position_manager) "
                "|| '|' || decimal(token_id) || '|' || stratum_name)"
            ),
            "take": "one_per_stratum",
        }
    ):
        raise ValueError("spec: Range successor strata or selection rule are invalid")
    attempts = frame["pool_truth_capture_attempts"]
    if not isinstance(attempts, list) or len(attempts) != 3:
        raise ValueError("spec: Range successor needs exactly three pool captures")
    parsed_attempts = [
        _utc_timestamp(value, "Range successor pool capture") for value in attempts
    ]
    if parsed_attempts != sorted(set(parsed_attempts)):
        raise ValueError("spec: Range successor pool captures are not increasing")
    return frame


def _range_prior_exposure(spec: PairedSpec) -> set[int]:
    """The cases this operator has already seen revealed, checked against the constants."""
    exposure = spec.case_selection.get("prior_exposure_exclusion")
    if not isinstance(exposure, dict) or set(exposure) != {
        "token_ids",
        "excluded_reason",
        "prior_spec_id",
        "disclosure",
    }:
        raise ValueError(
            "spec: Range distinct successor needs a prior_exposure_exclusion with "
            "exactly token_ids, excluded_reason, prior_spec_id and disclosure"
        )
    token_ids = exposure["token_ids"]
    if (
        not isinstance(token_ids, list)
        or not all(
            isinstance(token_id, int)
            and not isinstance(token_id, bool)
            and token_id >= 0
            for token_id in token_ids
        )
        or token_ids != sorted(set(token_ids))
        or set(token_ids) != RANGE_PRIOR_EXPOSURE_TOKEN_IDS
    ):
        raise ValueError(
            "spec: Range prior-exposure token ids do not match the cases this build "
            "knows the operator has already seen revealed"
        )
    if (
        exposure["excluded_reason"] != RANGE_PRIOR_EXPOSURE_REASON
        or exposure["prior_spec_id"] != RANGE_PRIOR_EXPOSURE_SPEC_ID
        or not str(exposure["disclosure"]).strip()
    ):
        raise ValueError("spec: Range prior-exposure exclusion is not disclosed")
    return set(token_ids)


def _validate_range_distinct_successor(spec: PairedSpec) -> None:
    """A Range family that answers a published predecessor rather than correcting a draft."""
    if spec.pilot_provenance is not None or spec.protocol_correction is not None:
        raise ValueError(
            "spec: a Range distinct successor carries successor provenance alone"
        )
    if spec.inputs_ref != "docket/advantage/v3/inputs/range-v7-positions.json":
        raise ValueError("spec: Range distinct successor inputs_ref is invalid")
    frame = _range_successor_frame(spec)
    observed = _utc_timestamp(
        frame["observation_time"], "Range successor observation time"
    )
    captures = [
        _utc_timestamp(value, "Range successor pool capture")
        for value in frame["pool_truth_capture_attempts"]
    ]
    if captures[0] <= observed:
        # The whole point of the successor is register, then capture in the future. A pool
        # truth registered at or before the pinned block would be an artifact that already
        # existed when the protocol was fixed.
        raise ValueError(
            "spec: Range distinct successor pool truth must be captured after the pinned "
            "observation block"
        )
    _range_prior_exposure(spec)
    lowered = spec.claim.lower()
    if "human operator" not in lowered or "settled" not in lowered:
        raise ValueError(
            "spec: a Range distinct successor claim must say the manual arm is a human "
            "operator and that the agent arm was settled"
        )
    identities = spec.execution_protocol.get("arm_identities")
    if identities != RANGE_SUCCESSOR_ARM_IDENTITIES:
        raise ValueError("spec: Range distinct successor arm identities are invalid")
    provenance = spec.successor_provenance
    if not isinstance(provenance, dict) or set(provenance) != SUCCESSOR_FIELDS:
        raise ValueError("spec: Range distinct successor provenance is incomplete")
    if provenance != {
        "status": "distinct_successor_after_terminal_incomplete_pair",
        "prior_spec_id": RANGE_PRIOR_EXPOSURE_SPEC_ID,
        "prior_stage_one_protocol_hash": RANGE_PRIOR_STAGE_ONE_PROTOCOL_HASH,
        "prior_spec_hash": RANGE_PRIOR_SPEC_HASH,
        "prior_ledger_ref": RANGE_PRIOR_LEDGER_REF,
        "reason": RANGE_SUCCESSOR_REASON,
    }:
        raise ValueError("spec: Range distinct successor provenance is invalid")


def _validate_range_successor_registration(spec: PairedSpec) -> None:
    _range_conflict_exclusion(spec)
    _range_successor_frame(spec)
    if spec.successor_provenance is not None:
        _validate_range_distinct_successor(spec)
        return
    provenance = spec.pilot_provenance
    if not isinstance(provenance, dict):
        raise ValueError("spec: Range successor needs pilot provenance")
    _required_fields(
        provenance,
        {
            "status",
            "prior_spec_id",
            "prior_stage_one_protocol_hash",
            "original_registration_passed",
            "dry_run_preregistered_nothing",
            "new_frame_read_before_registration",
            "feasibility_probe_preceded_registration",
            "evidence",
        },
        "Range successor pilot provenance",
    )
    if (
        provenance["status"] != "pilot_informed"
        or provenance["prior_spec_id"] != "v3-01-range-doctor"
        or provenance["original_registration_passed"] is not False
        or provenance["dry_run_preregistered_nothing"] is not True
        or provenance["new_frame_read_before_registration"] is not False
        or provenance["feasibility_probe_preceded_registration"] is not True
        or OBJECT_HASH.fullmatch(provenance["prior_stage_one_protocol_hash"]) is None
        or spec.protocol_correction["supersedes_stage_one_protocol_hash"]
        != provenance["prior_stage_one_protocol_hash"]
    ):
        raise ValueError("spec: Range successor pilot provenance is invalid")
    evidence = provenance["evidence"]
    if not isinstance(evidence, dict) or set(evidence) != {
        "range_replacement_dry_run",
        "live_feasibility",
    }:
        raise ValueError("spec: Range successor provenance evidence is incomplete")
    for source in evidence.values():
        if (
            not isinstance(source, dict)
            or set(source) != {"ref", "sha256"}
            or not isinstance(source["ref"], str)
            or not source["ref"].strip()
            or SHA256.fullmatch(str(source["sha256"])) is None
        ):
            raise ValueError("spec: Range successor provenance evidence is invalid")


def range_sample_indices(spec: PairedSpec, total_supply: int) -> list[dict]:
    """Derive the registered distinct enumerable indices, including collisions."""
    frame = _range_successor_frame(spec)
    if (
        not isinstance(total_supply, int)
        or isinstance(total_supply, bool)
        or total_supply < frame["sample_size"]
    ):
        raise ValueError("spec: Range totalSupply cannot fill the registered sample")
    rows = []
    seen = set()
    counter = frame["index_derivation"]["counter_start"]
    while len(rows) < frame["sample_size"]:
        preimage = (
            f"{spec.stage_one_protocol_hash}|56|{RANGE_POSITION_MANAGER}|"
            f"{frame['observation_block']}|{counter}"
        ).encode("utf-8")
        index = int.from_bytes(hashlib.sha256(preimage).digest(), "big") % total_supply
        if index not in seen:
            rows.append(
                {
                    "sample_ordinal": len(rows),
                    "derivation_counter": counter,
                    "index": index,
                }
            )
            seen.add(index)
        counter += 1
    return rows


def _range_source_frame(sources: list[dict], repo_root: Path, conflict: tuple):
    conflict_wallets, conflict_token_ids = conflict
    if not isinstance(sources, list) or len(sources) != 3:
        raise ValueError("spec: Range manifest needs exactly three typed source refs")
    if not all(isinstance(source, dict) for source in sources):
        raise ValueError("spec: every Range manifest source ref must be an object")
    by_kind = {source.get("kind"): source for source in sources}
    if set(by_kind) != {"transfer_logs", "position_enumeration", "pool_truth"}:
        raise ValueError(
            "spec: Range manifest sources must be transfer_logs, position_enumeration and pool_truth"
        )

    transfer = _locked_json(
        by_kind["transfer_logs"], repo_root, "Range transfer-log source"
    )
    if not isinstance(transfer, dict):
        raise ValueError("spec: Range transfer-log source must be an object")
    _required_fields(
        transfer,
        {
            "from_block",
            "to_block",
            "selected_block",
            "predecessor_block",
            "latest_finalized_block",
            "contracts",
            "complete",
            "logs",
        },
        "Range transfer-log source",
    )
    selected_block = transfer["selected_block"]
    predecessor_block = transfer["predecessor_block"]
    if (
        transfer["from_block"] != 0
        or not isinstance(transfer["to_block"], int)
        or isinstance(transfer["to_block"], bool)
        or transfer["to_block"] <= 0
        or transfer["complete"] is not True
        or not isinstance(transfer["contracts"], list)
        or {str(contract).lower() for contract in transfer["contracts"]}
        != {RANGE_POSITION_MANAGER, RANGE_MASTER_CHEF}
        or not isinstance(transfer["logs"], list)
    ):
        raise ValueError("spec: Range transfer-log frame is incomplete or misbounded")
    if not isinstance(selected_block, dict) or not isinstance(predecessor_block, dict):
        raise ValueError("spec: Range block-boundary evidence must be objects")
    _required_fields(selected_block, {"number", "timestamp"}, "Range selected block")
    _required_fields(
        predecessor_block, {"number", "timestamp"}, "Range predecessor block"
    )
    if (
        not isinstance(selected_block["number"], int)
        or isinstance(selected_block["number"], bool)
        or not isinstance(predecessor_block["number"], int)
        or isinstance(predecessor_block["number"], bool)
        or selected_block["number"] != transfer["to_block"]
        or predecessor_block["number"] != transfer["to_block"] - 1
        or not isinstance(transfer["latest_finalized_block"], int)
        or isinstance(transfer["latest_finalized_block"], bool)
        or transfer["latest_finalized_block"] < transfer["to_block"]
        or not isinstance(selected_block["timestamp"], str)
        or not isinstance(predecessor_block["timestamp"], str)
        or _utc_timestamp(selected_block["timestamp"], "Range selected block timestamp")
        < RANGE_CAPTURE_NOT_BEFORE
        or _utc_timestamp(
            predecessor_block["timestamp"], "Range predecessor block timestamp"
        )
        >= RANGE_CAPTURE_NOT_BEFORE
    ):
        raise ValueError("spec: Range block-boundary/finality evidence is invalid")
    candidate_wallets = set()
    log_identities = set()
    for row in transfer["logs"]:
        if not isinstance(row, dict):
            raise ValueError("spec: every Range transfer log must be an object")
        _required_fields(
            row,
            {"contract", "block_number", "transaction_hash", "log_index", "topics"},
            "Range transfer log",
        )
        if (
            not isinstance(row["contract"], str)
            or row["contract"].lower()
            not in {RANGE_POSITION_MANAGER, RANGE_MASTER_CHEF}
            or not isinstance(row["block_number"], int)
            or isinstance(row["block_number"], bool)
            or not 0 <= row["block_number"] <= transfer["to_block"]
            or not isinstance(row["transaction_hash"], str)
            or re.fullmatch(r"0x[0-9a-fA-F]{64}", row["transaction_hash"]) is None
            or not isinstance(row["log_index"], int)
            or isinstance(row["log_index"], bool)
            or row["log_index"] < 0
            or not isinstance(row["topics"], list)
            or len(row["topics"]) != 4
            or str(row["topics"][0]).lower() != TRANSFER_TOPIC
            or not all(
                isinstance(topic, str)
                and re.fullmatch(r"0x[0-9a-fA-F]{64}", topic) is not None
                for topic in row["topics"][1:]
            )
            or not all(
                re.fullmatch(r"0x0{24}[0-9a-fA-F]{40}", row["topics"][index])
                is not None
                for index in (1, 2)
            )
        ):
            raise ValueError("spec: Range transfer log is malformed or out of bounds")
        log_identity = (row["transaction_hash"].lower(), row["log_index"])
        if log_identity in log_identities:
            raise ValueError("spec: Range transfer log identity is duplicated")
        log_identities.add(log_identity)
        recipient = "0x" + row["topics"][2][-40:].lower()
        if recipient != "0x" + "0" * 40:
            candidate_wallets.add(recipient)
    if not candidate_wallets:
        raise ValueError("spec: Range transfer-log frame has no candidate wallets")

    enumeration = _locked_json(
        by_kind["position_enumeration"],
        repo_root,
        "Range position-enumeration source",
    )
    if not isinstance(enumeration, dict):
        raise ValueError("spec: Range position enumeration must be an object")
    _required_fields(
        enumeration,
        {"observation_block", "observation_time", "complete", "wallet_scans"},
        "Range position-enumeration source",
    )
    if (
        enumeration["observation_block"] != transfer["to_block"]
        or enumeration["complete"] is not True
        or not isinstance(enumeration["observation_time"], str)
        or not enumeration["observation_time"].strip()
        or not isinstance(enumeration["wallet_scans"], list)
    ):
        raise ValueError("spec: Range position enumeration is incomplete or misbounded")
    if _utc_timestamp(
        enumeration["observation_time"], "Range observation_time"
    ) != _utc_timestamp(selected_block["timestamp"], "Range selected block timestamp"):
        raise ValueError("spec: Range observation time must be the selected block time")
    scans = {}
    for scan in enumeration["wallet_scans"]:
        if not isinstance(scan, dict):
            raise ValueError("spec: every Range wallet scan must be an object")
        _required_fields(
            scan,
            {
                "wallet",
                "positions_held",
                "positions_examined",
                "closed_skipped",
                "scan_complete",
                "positions",
            },
            "Range wallet scan",
        )
        wallet = scan["wallet"]
        if (
            not isinstance(wallet, str)
            or ADDRESS.fullmatch(wallet) is None
            or scan["scan_complete"] is not True
            or not isinstance(scan["positions"], list)
            or wallet.lower() in scans
        ):
            raise ValueError("spec: Range wallet scan is invalid or duplicated")
        for name in ("positions_held", "positions_examined", "closed_skipped"):
            if (
                not isinstance(scan[name], int)
                or isinstance(scan[name], bool)
                or scan[name] < 0
            ):
                raise ValueError("spec: Range wallet coverage counts are invalid")
        if scan["positions_held"] != scan["positions_examined"] or scan[
            "positions_examined"
        ] != len(scan["positions"]):
            raise ValueError(
                "spec: Range complete scan counts contradict its positions"
            )
        scans[wallet.lower()] = scan
    if set(scans) != candidate_wallets:
        raise ValueError("spec: Range wallet scans do not cover the transfer-log frame")

    pool_truth = _locked_json(
        by_kind["pool_truth"], repo_root, "Range pool-truth source"
    )
    if not isinstance(pool_truth, dict) or not isinstance(
        pool_truth.get("source_snapshots"), dict
    ):
        raise ValueError("spec: Range pool truth needs source_snapshots")
    snapshots = pool_truth["source_snapshots"]
    if set(snapshots) != {"pools", "token_list"}:
        raise ValueError("spec: Range pool truth needs pools and token_list snapshots")
    source_bodies = {
        name: _validate_source_snapshot(
            snapshot, name, attempts=(RANGE_CAPTURE_NOT_BEFORE,)
        )
        for name, snapshot in snapshots.items()
        if isinstance(snapshot, dict)
    }
    if set(source_bodies) != {"pools", "token_list"}:
        raise ValueError("spec: Range pool source snapshots must be objects")
    if (
        snapshots["pools"]["attempt_ordinal"]
        != snapshots["token_list"]["attempt_ordinal"]
    ):
        raise ValueError("spec: Range pool snapshots must use one capture attempt")
    if snapshots["pools"]["attempt_ordinal"] != 1:
        raise ValueError("spec: Range pool truth must use the registered capture")
    if _utc_timestamp(
        selected_block["timestamp"], "Range selected block timestamp"
    ) > _utc_timestamp(snapshots["pools"]["observed_at"], "Range pools observed_at"):
        raise ValueError("spec: Range pool truth predates the selected block")
    if _utc_timestamp(
        snapshots["pools"]["observed_at"], "Range pools observed_at"
    ) > _utc_timestamp(
        snapshots["token_list"]["observed_at"], "Range token_list observed_at"
    ):
        raise ValueError("spec: Range pool snapshots were not captured in order")
    pools_body = source_bodies["pools"]
    pool_rows = (
        pools_body
        if isinstance(pools_body, list)
        else pools_body.get("rows")
        if isinstance(pools_body, dict)
        else None
    )
    token_body = source_bodies["token_list"]
    if (
        not isinstance(pool_rows, list)
        or not isinstance(token_body, dict)
        or not isinstance(token_body.get("tokens"), list)
    ):
        raise ValueError("spec: Range pool truth source shapes are invalid")
    allowlist = _token_allowlist(token_body, "Range token-list source")
    pools_by_id = {}
    for row in pool_rows:
        if not isinstance(row, dict):
            raise ValueError("spec: every Range pool source row must be an object")
        pool_id = str(row.get("id") or "").lower()
        if ADDRESS.fullmatch(pool_id) is None or pool_id in pools_by_id:
            raise ValueError("spec: Range pool source ids are invalid or duplicated")
        pools_by_id[pool_id] = row

    positions = {}
    conflicted = {}
    for wallet, scan in scans.items():
        rows = scan["positions"]
        closed_count = 0
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(
                    "spec: every Range enumerated position must be an object"
                )
            _required_fields(
                row,
                {
                    "position_manager",
                    "token_id",
                    "pool_id",
                    "liquidity",
                    "current_tick",
                    "tick_lower",
                    "tick_upper",
                },
                "Range enumerated position",
            )
            if (
                not isinstance(row["position_manager"], str)
                or row["position_manager"].lower() != RANGE_POSITION_MANAGER
                or not isinstance(row["token_id"], int)
                or isinstance(row["token_id"], bool)
                or row["token_id"] < 0
                or not isinstance(row["liquidity"], int)
                or isinstance(row["liquidity"], bool)
                or row["liquidity"] < 0
                or not all(
                    isinstance(row[name], int) and not isinstance(row[name], bool)
                    for name in ("current_tick", "tick_lower", "tick_upper")
                )
            ):
                raise ValueError("spec: Range enumerated position values are invalid")
            if row["tick_lower"] >= row["tick_upper"]:
                raise ValueError("spec: Range tick bounds are not ordered")
            beneficiary = row.get("staking_beneficiary")
            if wallet == RANGE_MASTER_CHEF:
                if (
                    not isinstance(beneficiary, str)
                    or ADDRESS.fullmatch(beneficiary) is None
                ):
                    raise ValueError(
                        "spec: every farm-held Range position needs a 20-byte "
                        "staking_beneficiary, or the conflict check cannot be applied to it"
                    )
            elif beneficiary is not None:
                raise ValueError(
                    "spec: only farm-held Range positions may name a staking_beneficiary"
                )
            if (
                row["token_id"] in conflict_token_ids
                or wallet in conflict_wallets
                or (
                    wallet == RANGE_MASTER_CHEF
                    and beneficiary.lower() in conflict_wallets
                )
            ):
                # Recorded before liquidity, range, pool-gate or stratum classification, so
                # nothing about this position's outcome can influence whether it is dropped.
                conflict_identity = (RANGE_POSITION_MANAGER, row["token_id"])
                if conflict_identity in conflicted or conflict_identity in positions:
                    # One token id, two holders. On chain `ownerOf` is unique, so this can
                    # only come from a fabricated enumeration — and left unchecked it lets
                    # a token be declared excluded under the controlled wallet while a
                    # second copy of it stays in the drawable frame under an honest one.
                    raise ValueError(
                        "spec: Range enumeration repeats a position identity across "
                        "holders, so one copy could be excluded while another is drawn"
                    )
                conflicted[conflict_identity] = {
                    "position_manager": row["position_manager"],
                    "wallet": wallet,
                    "token_id": row["token_id"],
                    "excluded_reason": RANGE_CONFLICT_REASON,
                }
                # The scanner counted a closed position in its own closed_skipped, so the
                # reconciliation below still has to see it. Counting is not classifying.
                if row["liquidity"] <= 0:
                    closed_count += 1
                continue
            if row["liquidity"] <= 0:
                closed_count += 1
                continue
            if row["current_tick"] < row["tick_lower"]:
                status = "below_range"
            elif row["current_tick"] >= row["tick_upper"]:
                status = "above_range"
            else:
                status = "in_range"
            pool_id = str(row["pool_id"]).lower()
            pool_row = pools_by_id.get(pool_id)
            if ADDRESS.fullmatch(pool_id) is None or pool_row is None:
                raise ValueError(
                    "spec: every Range position needs a frozen 20-byte pool source row"
                )
            failed_gate = _yield_first_failed_gate(pool_row, allowlist)
            gate_passes = failed_gate is None
            fee_usd_24h = (
                None
                if pool_row.get("feeUSD24h") is None
                else _yield_number(pool_row, "feeUSD24h")
            )
            protocol_fee_usd_24h = (
                None
                if pool_row.get("protocolFeeUSD24h") is None
                else _yield_number(pool_row, "protocolFeeUSD24h")
            )
            tvl_usd = _yield_number(pool_row, "tvlUSD")
            identity = (RANGE_POSITION_MANAGER, row["token_id"])
            if identity in positions or identity in conflicted:
                raise ValueError("spec: Range enumeration repeats a position identity")
            positions[identity] = {
                "position_manager": row["position_manager"],
                "wallet": wallet,
                "token_id": row["token_id"],
                "range_status": status,
                "liquidity": row["liquidity"],
                "pool_gate_passes": gate_passes,
                "_current_tick": row["current_tick"],
                "_tick_lower": row["tick_lower"],
                "_tick_upper": row["tick_upper"],
                "_positions_held": scan["positions_held"],
                "_positions_examined": scan["positions_examined"],
                "_closed_skipped": scan["closed_skipped"],
                "_scan_complete": scan["scan_complete"],
                "_first_failed_gate": failed_gate,
                "_fee_usd_24h": fee_usd_24h,
                "_protocol_fee_usd_24h": protocol_fee_usd_24h,
                "_tvl_usd": tvl_usd,
            }
        if closed_count != scan["closed_skipped"]:
            raise ValueError("spec: Range closed_skipped does not match zero liquidity")
    return (
        candidate_wallets,
        positions,
        conflicted,
        enumeration["observation_block"],
        enumeration["observation_time"],
    )


def _validate_range_inputs(
    spec: PairedSpec, body: dict, cases: list[dict], repo_root: Path
) -> None:
    manifest = body.get("selection_manifest")
    if not isinstance(manifest, dict):
        raise ValueError("spec: Range inputs need a selection_manifest object")
    _required_fields(
        manifest,
        {
            "candidate_wallets",
            "eligible_positions",
            "conflict_exclusions",
            "source_refs",
        },
        "Range selection_manifest",
    )
    candidate_wallets = manifest["candidate_wallets"]
    eligible_positions = manifest["eligible_positions"]
    manifest_sources = manifest["source_refs"]
    conflict = _range_conflict_exclusion(spec)
    if not isinstance(candidate_wallets, list) or not candidate_wallets:
        raise ValueError("spec: Range candidate_wallets must be a nonempty array")
    if not all(
        isinstance(wallet, str) and ADDRESS.fullmatch(wallet)
        for wallet in candidate_wallets
    ) or len({wallet.lower() for wallet in candidate_wallets}) != len(
        candidate_wallets
    ):
        raise ValueError("spec: Range candidate wallets must be distinct addresses")
    candidate_wallets = {wallet.lower() for wallet in candidate_wallets}
    (
        source_wallets,
        source_positions,
        source_conflicted,
        source_observation_block,
        source_observation_time,
    ) = _range_source_frame(manifest_sources, repo_root, conflict)
    if candidate_wallets != source_wallets:
        raise ValueError("spec: Range candidate manifest differs from transfer logs")
    if not isinstance(eligible_positions, list) or len(eligible_positions) < 5:
        raise ValueError("spec: Range selection manifest needs at least five positions")
    position_frame = {}
    for index, position in enumerate(eligible_positions):
        if not isinstance(position, dict):
            raise ValueError("spec: every Range eligible position must be an object")
        _required_fields(
            position,
            {
                "position_manager",
                "wallet",
                "token_id",
                "range_status",
                "liquidity",
                "pool_gate_passes",
            },
            f"Range eligible position {index + 1}",
        )
        manager = position["position_manager"]
        wallet = position["wallet"]
        token_id = position["token_id"]
        if not isinstance(manager, str) or manager.lower() != RANGE_POSITION_MANAGER:
            raise ValueError(
                "spec: Range manifest has an unregistered position manager"
            )
        if (
            not isinstance(wallet, str)
            or ADDRESS.fullmatch(wallet) is None
            or wallet.lower() not in candidate_wallets
        ):
            raise ValueError(
                "spec: Range position wallet is outside the candidate frame"
            )
        if not isinstance(token_id, int) or isinstance(token_id, bool) or token_id < 0:
            raise ValueError("spec: Range manifest token_id must be non-negative")
        if not isinstance(position["range_status"], str) or position[
            "range_status"
        ] not in {"in_range", "above_range", "below_range"}:
            raise ValueError("spec: Range manifest has an invalid range_status")
        if (
            not isinstance(position["liquidity"], int)
            or isinstance(position["liquidity"], bool)
            or position["liquidity"] <= 0
        ):
            raise ValueError("spec: Range manifest positions need positive liquidity")
        if not isinstance(position["pool_gate_passes"], bool):
            raise ValueError("spec: Range manifest pool gate must be boolean")
        identity = (manager.lower(), token_id)
        if identity in position_frame:
            raise ValueError(
                "spec: Range manifest position identities are not distinct"
            )
        position_frame[identity] = position
    declared_conflicts = manifest["conflict_exclusions"]
    if not isinstance(declared_conflicts, list):
        raise ValueError("spec: Range conflict_exclusions must be an array")
    declared = {}
    for index, record in enumerate(declared_conflicts):
        if not isinstance(record, dict):
            raise ValueError("spec: every Range conflict exclusion must be an object")
        _required_fields(
            record,
            {"position_manager", "wallet", "token_id", "excluded_reason"},
            f"Range conflict exclusion {index + 1}",
        )
        manager = record["position_manager"]
        if not isinstance(manager, str) or manager.lower() != RANGE_POSITION_MANAGER:
            raise ValueError(
                "spec: Range conflict exclusion names an unregistered position manager"
            )
        if not isinstance(record["token_id"], int) or isinstance(
            record["token_id"], bool
        ):
            raise ValueError(
                "spec: Range conflict exclusion token_id must be an integer"
            )
        identity = (RANGE_POSITION_MANAGER, record["token_id"])
        if identity in declared:
            raise ValueError(
                "spec: Range conflict exclusions repeat a position identity"
            )
        declared[identity] = record
    # Both directions. An omitted conflict is self-dealing; an invented one deletes an
    # honest position and shifts which token wins the lowest-hash draw, which is the same
    # attack pointed the other way.
    if set(declared) != set(source_conflicted):
        raise ValueError(
            "spec: Range conflict exclusions differ from the ones derived from the sources"
        )
    for identity, record in declared.items():
        derived = source_conflicted[identity]
        if (
            record["wallet"].lower() != derived["wallet"].lower()
            or record["excluded_reason"] != RANGE_CONFLICT_REASON
        ):
            raise ValueError(
                "spec: Range conflict exclusion contradicts the parsed sources"
            )
    if set(position_frame) != set(source_positions):
        raise ValueError(
            "spec: Range eligible manifest differs from archive enumeration"
        )
    conflict_wallets, conflict_token_ids = conflict
    for identity, position in position_frame.items():
        if (
            identity[1] in conflict_token_ids
            or position["wallet"].lower() in conflict_wallets
        ):
            raise ValueError(
                "spec: a Range eligible position is experiment-party controlled"
            )
    for identity, position in position_frame.items():
        source_position = source_positions[identity]
        if (
            position["wallet"].lower() != source_position["wallet"].lower()
            or position["range_status"] != source_position["range_status"]
            or position["liquidity"] != source_position["liquidity"]
            or position["pool_gate_passes"] is not source_position["pool_gate_passes"]
        ):
            raise ValueError("spec: Range eligible manifest contradicts parsed sources")

    required = {
        "case_id",
        "selection_stratum",
        "chain_id",
        "position_manager",
        "wallet",
        "token_id",
        "observation_block",
        "observation_time",
        "declared_position_value_usd",
        "estimated_recenter_cost_usd",
        "decision_horizon_days",
        "source_refs",
        "truth",
    }
    identities = set()
    observation_blocks = set()
    observation_times = set()
    for index, case in enumerate(cases):
        _required_fields(case, required, f"Range case {index + 1}")
        if case["chain_id"] != 56:
            raise ValueError("spec: every Range case must use chain_id 56")
        if str(case["position_manager"]).lower() != RANGE_POSITION_MANAGER:
            raise ValueError(
                "spec: every Range case must use the registered position manager"
            )
        if (
            not isinstance(case["wallet"], str)
            or ADDRESS.fullmatch(case["wallet"]) is None
        ):
            raise ValueError("spec: every Range wallet must be a 20-byte address")
        if (
            not isinstance(case["token_id"], int)
            or isinstance(case["token_id"], bool)
            or case["token_id"] < 0
        ):
            raise ValueError(
                "spec: every Range token_id must be a non-negative integer"
            )
        if (
            not isinstance(case["observation_block"], int)
            or isinstance(case["observation_block"], bool)
            or case["observation_block"] <= 0
        ):
            raise ValueError("spec: every Range observation_block must be positive")
        if (
            not isinstance(case["observation_time"], str)
            or not case["observation_time"].strip()
        ):
            raise ValueError("spec: every Range observation_time must be nonblank")
        observation_blocks.add(case["observation_block"])
        observation_times.add(case["observation_time"])
        if case["declared_position_value_usd"] != 10000:
            raise ValueError(
                "spec: every Range case must use the registered $10,000 value"
            )
        if case["estimated_recenter_cost_usd"] != 25:
            raise ValueError("spec: every Range case must use the registered $25 cost")
        if case["decision_horizon_days"] != 30:
            raise ValueError(
                "spec: every Range case must use the registered 30-day horizon"
            )
        if not isinstance(case["source_refs"], list) or not case["source_refs"]:
            raise ValueError("spec: every Range case must carry frozen source refs")
        if case["source_refs"] != manifest_sources:
            raise ValueError(
                "spec: every Range case must reference the typed manifest sources"
            )
        identity = (case["position_manager"].lower(), case["token_id"])
        if identity in identities:
            raise ValueError("spec: Range position identities are not distinct")
        identities.add(identity)
        if identity not in position_frame:
            raise ValueError(
                "spec: a selected Range case is outside the complete manifest"
            )

        truth = case["truth"]
        if not isinstance(truth, dict):
            raise ValueError("spec: every Range case must carry an object truth record")
        _required_fields(
            truth,
            {
                "range_status",
                "liquidity",
                "pool_gate_passes",
                "first_failed_gate",
                "current_tick",
                "tick_lower",
                "tick_upper",
                "fee_usd_24h",
                "protocol_fee_usd_24h",
                "tvl_usd",
                "gross_apr",
                "net_apr",
                "annual_gross_usd",
                "annual_net_usd",
                "annual_overstatement_usd",
                "cost_only_break_even_days",
                "positions_held",
                "positions_examined",
                "closed_skipped",
                "scan_complete",
            },
            f"Range case {index + 1} truth",
        )
        status = truth["range_status"]
        if not isinstance(status, str) or status not in {
            "in_range",
            "above_range",
            "below_range",
        }:
            raise ValueError("spec: Range truth has an invalid range_status")
        if (
            not isinstance(truth["liquidity"], int)
            or isinstance(truth["liquidity"], bool)
            or truth["liquidity"] <= 0
        ):
            raise ValueError(
                "spec: every Range case must have positive integer liquidity"
            )
        if not isinstance(truth["pool_gate_passes"], bool):
            raise ValueError("spec: every Range pool_gate_passes value must be boolean")
        stratum = case["selection_stratum"]
        if (
            not isinstance(stratum, int)
            or isinstance(stratum, bool)
            or stratum
            not in {
                1,
                2,
                3,
                4,
                5,
            }
        ):
            raise ValueError("spec: Range selection_stratum must be 1 through 5")
        if stratum == 1 and (status != "in_range" or not truth["pool_gate_passes"]):
            raise ValueError(
                "spec: Range stratum 1 must be in-range with a passing gate"
            )
        if stratum == 2 and (status != "above_range" or not truth["pool_gate_passes"]):
            raise ValueError(
                "spec: Range stratum 2 must be above-range with a passing gate"
            )
        if stratum == 3 and (status != "below_range" or not truth["pool_gate_passes"]):
            raise ValueError(
                "spec: Range stratum 3 must be below-range with a passing gate"
            )
        if stratum == 4 and (truth["liquidity"] <= 0 or truth["pool_gate_passes"]):
            raise ValueError(
                "spec: Range stratum 4 must have liquidity and fail the gate"
            )
        if truth["pool_gate_passes"] and truth["first_failed_gate"] is not None:
            raise ValueError("spec: a passing Range gate cannot name a failed gate")
        if (
            not truth["pool_gate_passes"]
            and not str(truth["first_failed_gate"] or "").strip()
        ):
            raise ValueError(
                "spec: a failed Range gate must name its first failed gate"
            )
        for tick in ("current_tick", "tick_lower", "tick_upper"):
            if not isinstance(truth[tick], int) or isinstance(truth[tick], bool):
                raise ValueError(f"spec: Range truth {tick} must be an integer")
        if (
            status == "in_range"
            and not truth["tick_lower"] <= truth["current_tick"] < truth["tick_upper"]
        ):
            raise ValueError("spec: Range in-range truth contradicts its ticks")
        if status == "above_range" and not truth["current_tick"] >= truth["tick_upper"]:
            raise ValueError("spec: Range above-range truth contradicts its ticks")
        if status == "below_range" and not truth["current_tick"] < truth["tick_lower"]:
            raise ValueError("spec: Range below-range truth contradicts its ticks")
        for count in ("positions_held", "positions_examined", "closed_skipped"):
            if (
                not isinstance(truth[count], int)
                or isinstance(truth[count], bool)
                or truth[count] < 0
            ):
                raise ValueError(
                    f"spec: Range truth {count} must be a non-negative integer"
                )
        if (
            truth["positions_examined"] > truth["positions_held"]
            or truth["closed_skipped"] > truth["positions_examined"]
        ):
            raise ValueError("spec: Range coverage counts are inconsistent")
        if truth["scan_complete"] is not True:
            raise ValueError("spec: Range input lock requires a complete wallet scan")
        framed = position_frame[identity]
        sourced = source_positions[identity]
        if (
            framed["wallet"].lower() != case["wallet"].lower()
            or framed["range_status"] != status
            or framed["liquidity"] != truth["liquidity"]
            or framed["pool_gate_passes"] is not truth["pool_gate_passes"]
        ):
            raise ValueError("spec: a Range case does not match its selection manifest")
        if (
            truth["first_failed_gate"] != sourced["_first_failed_gate"]
            or truth["current_tick"] != sourced["_current_tick"]
            or truth["tick_lower"] != sourced["_tick_lower"]
            or truth["tick_upper"] != sourced["_tick_upper"]
            or truth["positions_held"] != sourced["_positions_held"]
            or truth["positions_examined"] != sourced["_positions_examined"]
            or truth["closed_skipped"] != sourced["_closed_skipped"]
            or truth["scan_complete"] is not sourced["_scan_complete"]
            or truth["fee_usd_24h"] != sourced["_fee_usd_24h"]
            or truth["protocol_fee_usd_24h"] != sourced["_protocol_fee_usd_24h"]
            or truth["tvl_usd"] != sourced["_tvl_usd"]
        ):
            raise ValueError("spec: Range case pool truth contradicts parsed sources")
        rate_fields = (
            "gross_apr",
            "net_apr",
            "annual_gross_usd",
            "annual_net_usd",
            "annual_overstatement_usd",
            "cost_only_break_even_days",
        )
        if truth["pool_gate_passes"]:
            raw_fields = ("fee_usd_24h", "protocol_fee_usd_24h", "tvl_usd")
            if any(
                not isinstance(truth[name], (int, float))
                or isinstance(truth[name], bool)
                or not math.isfinite(truth[name])
                for name in raw_fields
            ):
                raise ValueError("spec: a passing Range case needs finite pool truth")
            if truth["tvl_usd"] <= 0:
                raise ValueError("spec: a passing Range case needs positive tvl_usd")
            gross_apr = truth["fee_usd_24h"] * 365 / truth["tvl_usd"]
            net_apr = (
                (truth["fee_usd_24h"] - truth["protocol_fee_usd_24h"])
                * 365
                / truth["tvl_usd"]
            )
            expected_rates = {
                "gross_apr": gross_apr,
                "net_apr": net_apr,
                "annual_gross_usd": 10000 * gross_apr,
                "annual_net_usd": 10000 * net_apr,
                "annual_overstatement_usd": 10000 * (gross_apr - net_apr),
                "cost_only_break_even_days": (
                    25 / (10000 * net_apr / 365) if net_apr > 0 else None
                ),
            }
            for name, expected in expected_rates.items():
                actual = truth[name]
                if expected is None:
                    if actual is not None:
                        raise ValueError(f"spec: Range truth has incorrect {name}")
                elif (
                    not isinstance(actual, (int, float))
                    or isinstance(actual, bool)
                    or not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
                ):
                    raise ValueError(f"spec: Range truth has incorrect {name}")
        elif any(truth[name] is not None for name in rate_fields):
            raise ValueError("spec: a failed Range gate cannot carry rate-based truth")
    if {case["selection_stratum"] for case in cases} != {1, 2, 3, 4, 5}:
        raise ValueError(
            "spec: Range inputs must contain each registered stratum exactly once"
        )
    if len(observation_blocks) != 1 or len(observation_times) != 1:
        raise ValueError(
            "spec: all Range cases must use one observation block and time"
        )
    if observation_blocks != {source_observation_block} or observation_times != {
        source_observation_time
    }:
        raise ValueError(
            "spec: Range cases do not use the parsed observation block/time"
        )
    remaining = dict(position_frame)
    selected_by_stratum = {case["selection_stratum"]: case for case in cases}
    filters = {
        1: lambda row: row["range_status"] == "in_range" and row["pool_gate_passes"],
        2: lambda row: row["range_status"] == "above_range" and row["pool_gate_passes"],
        3: lambda row: row["range_status"] == "below_range" and row["pool_gate_passes"],
        4: lambda row: not row["pool_gate_passes"],
        5: lambda row: True,
    }
    for stratum in range(1, 6):
        candidates = [
            identity for identity, row in remaining.items() if filters[stratum](row)
        ]
        if not candidates:
            raise ValueError(f"spec: Range selection stratum {stratum} is empty")
        expected_identity = min(
            candidates,
            key=lambda identity: hashlib.sha256(
                f"{spec.stage_one_protocol_hash}56{identity[0]}{identity[1]}".encode()
            ).hexdigest(),
        )
        case = selected_by_stratum[stratum]
        actual_identity = (case["position_manager"].lower(), case["token_id"])
        if actual_identity != expected_identity:
            raise ValueError(
                f"spec: Range case for stratum {stratum} is not the lowest hash"
            )
        del remaining[expected_identity]


def _range_successor_source_frame(
    spec: PairedSpec, sources: list[dict], repo_root: Path
) -> tuple[set[str], list[dict], list[dict], dict]:
    frame_definition = _range_successor_frame(spec)
    conflict_wallets, conflict_token_ids = _range_conflict_exclusion(spec)
    if not isinstance(sources, list) or len(sources) != 2:
        raise ValueError("spec: Range successor needs exactly two typed source refs")
    if not all(isinstance(source, dict) for source in sources):
        raise ValueError("spec: every Range successor source ref must be an object")
    by_kind = {source.get("kind"): source for source in sources}
    if set(by_kind) != {"enumerable_position_frame", "pool_truth"}:
        raise ValueError(
            "spec: Range successor sources must be enumerable_position_frame and pool_truth"
        )

    frame = _locked_json(
        by_kind["enumerable_position_frame"],
        repo_root,
        "Range successor enumerable frame",
    )
    if not isinstance(frame, dict):
        raise ValueError("spec: Range successor enumerable frame must be an object")
    _required_fields(
        frame,
        {
            "chain_id",
            "position_manager",
            "observation_block",
            "observation_block_hash",
            "observation_time",
            "total_supply",
            "sample_size",
            "complete",
            "rows",
            "rpc_call_accounting",
        },
        "Range successor enumerable frame",
    )
    if (
        frame["chain_id"] != 56
        or str(frame["position_manager"]).lower() != RANGE_POSITION_MANAGER
        or frame["observation_block"] != frame_definition["observation_block"]
        or frame["observation_block_hash"] != frame_definition["observation_block_hash"]
        or frame["observation_time"] != frame_definition["observation_time"]
        or frame["sample_size"] != frame_definition["sample_size"]
        or frame["complete"] is not True
        or not isinstance(frame["rows"], list)
        or len(frame["rows"]) != frame_definition["sample_size"]
    ):
        raise ValueError(
            "spec: Range successor enumerable frame is incomplete or changed"
        )
    expected_indices = range_sample_indices(spec, frame["total_supply"])
    base_fields = {
        "sample_ordinal",
        "derivation_counter",
        "index",
        "token_id",
        "owner",
        "staking_beneficiary",
    }
    position_fields = {
        "liquidity",
        "token0",
        "token1",
        "fee",
        "tick_lower",
        "tick_upper",
    }
    live_fields = {"pool_id", "current_tick"}
    token_ids = set()
    candidate_wallets = set()
    conflicted = []
    positions = []
    farm_calls = 0
    for row, derived_index in zip(frame["rows"], expected_indices, strict=True):
        if not isinstance(row, dict) or not base_fields <= set(row):
            raise ValueError(
                "spec: every Range successor frame row needs identity fields"
            )
        if any(row[name] != derived_index[name] for name in derived_index):
            raise ValueError(
                "spec: Range successor frame indices were not derived as registered"
            )
        token_id = row["token_id"]
        owner = row["owner"]
        beneficiary = row["staking_beneficiary"]
        if (
            not isinstance(token_id, int)
            or isinstance(token_id, bool)
            or token_id < 0
            or token_id in token_ids
            or not isinstance(owner, str)
            or ADDRESS.fullmatch(owner) is None
        ):
            raise ValueError(
                "spec: Range successor frame identity is invalid or repeated"
            )
        token_ids.add(token_id)
        owner = owner.lower()
        if owner == RANGE_MASTER_CHEF:
            farm_calls += 1
            if (
                not isinstance(beneficiary, str)
                or ADDRESS.fullmatch(beneficiary) is None
            ):
                raise ValueError(
                    "spec: every farm-held Range successor row needs a beneficiary"
                )
            wallet = beneficiary.lower()
        else:
            if beneficiary is not None:
                raise ValueError(
                    "spec: only farm-held Range successor rows may name a beneficiary"
                )
            wallet = owner
        candidate_wallets.add(wallet)
        is_conflict = (
            token_id in conflict_token_ids
            or owner in conflict_wallets
            or wallet in conflict_wallets
        )
        if is_conflict:
            if set(row) != base_fields:
                raise ValueError(
                    "spec: Range successor conflict was not recorded before outcome fields"
                )
            conflicted.append(
                {
                    "position_manager": RANGE_POSITION_MANAGER,
                    "wallet": wallet,
                    "token_id": token_id,
                    "excluded_reason": RANGE_CONFLICT_REASON,
                }
            )
            continue
        if frozenset(row) not in {
            frozenset(base_fields | position_fields),
            frozenset(base_fields | position_fields | live_fields),
        }:
            raise ValueError(
                "spec: Range successor position row has unregistered fields"
            )
        if (
            not isinstance(row["liquidity"], int)
            or isinstance(row["liquidity"], bool)
            or row["liquidity"] < 0
            or not all(
                isinstance(row[name], int) and not isinstance(row[name], bool)
                for name in ("fee", "tick_lower", "tick_upper")
            )
            or row["tick_lower"] >= row["tick_upper"]
            or any(
                not isinstance(row[name], str) or ADDRESS.fullmatch(row[name]) is None
                for name in ("token0", "token1")
            )
        ):
            raise ValueError("spec: Range successor position values are invalid")
        if row["liquidity"] == 0:
            if set(row) != base_fields | position_fields:
                raise ValueError(
                    "spec: closed Range successor rows cannot name pool outcomes"
                )
            continue
        if (
            set(row) != base_fields | position_fields | live_fields
            or not isinstance(row["pool_id"], str)
            or ADDRESS.fullmatch(row["pool_id"]) is None
            or not isinstance(row["current_tick"], int)
            or isinstance(row["current_tick"], bool)
        ):
            raise ValueError("spec: live Range successor rows need pool and tick truth")
        status = (
            "below_range"
            if row["current_tick"] < row["tick_lower"]
            else "above_range"
            if row["current_tick"] >= row["tick_upper"]
            else "in_range"
        )
        positions.append(
            {
                "position_manager": RANGE_POSITION_MANAGER,
                "wallet": wallet,
                "token_id": token_id,
                "range_status": status,
                "liquidity": row["liquidity"],
                "current_tick": row["current_tick"],
                "tick_lower": row["tick_lower"],
                "tick_upper": row["tick_upper"],
                "token0": row["token0"].lower(),
                "token1": row["token1"].lower(),
                "fee": row["fee"],
                "pool_id": row["pool_id"].lower(),
            }
        )

    pool_truth = _locked_json(
        by_kind["pool_truth"], repo_root, "Range successor pool truth"
    )
    if not isinstance(pool_truth, dict) or set(pool_truth) != {
        "capture_log",
        "source_snapshots",
    }:
        raise ValueError(
            "spec: Range successor pool truth needs capture_log and source_snapshots"
        )
    snapshots = pool_truth["source_snapshots"]
    if not isinstance(snapshots, dict) or set(snapshots) != {"pools", "token_list"}:
        raise ValueError("spec: Range successor pool truth needs pools and token_list")
    attempts = tuple(
        _utc_timestamp(value, "Range successor pool capture")
        for value in frame_definition["pool_truth_capture_attempts"]
    )
    source_bodies = {
        name: _validate_source_snapshot(snapshot, name, attempts=attempts)
        for name, snapshot in snapshots.items()
        if isinstance(snapshot, dict)
    }
    if set(source_bodies) != {"pools", "token_list"}:
        raise ValueError("spec: Range successor pool snapshots must be objects")
    if (
        snapshots["pools"]["attempt_ordinal"]
        != snapshots["token_list"]["attempt_ordinal"]
    ):
        raise ValueError(
            "spec: Range successor pool snapshots need one capture attempt"
        )
    chosen_ordinal = snapshots["pools"]["attempt_ordinal"]
    capture_log = pool_truth["capture_log"]
    if not isinstance(capture_log, list) or len(capture_log) != chosen_ordinal:
        raise ValueError(
            "spec: Range successor capture log must reach its chosen attempt"
        )
    for ordinal, attempt in enumerate(capture_log, start=1):
        if not isinstance(attempt, dict) or set(attempt) != {
            "attempt_ordinal",
            "scheduled_at",
            "pools_status",
            "token_list_status",
        }:
            raise ValueError("spec: Range successor capture log entry is invalid")
        if (
            attempt["attempt_ordinal"] != ordinal
            or attempt["scheduled_at"]
            != frame_definition["pool_truth_capture_attempts"][ordinal - 1]
            or not all(
                isinstance(attempt[name], int)
                and not isinstance(attempt[name], bool)
                and attempt[name] >= 0
                for name in ("pools_status", "token_list_status")
            )
        ):
            raise ValueError(
                "spec: Range successor capture log is out of order or malformed"
            )
        succeeded = (
            attempt["pools_status"] == 200 and attempt["token_list_status"] == 200
        )
        if succeeded != (ordinal == chosen_ordinal):
            raise ValueError(
                "spec: Range successor pool truth is not the first successful capture"
            )
    pools_body = source_bodies["pools"]
    pool_rows = (
        pools_body
        if isinstance(pools_body, list)
        else pools_body.get("rows")
        if isinstance(pools_body, dict)
        else None
    )
    token_body = source_bodies["token_list"]
    if (
        not isinstance(pool_rows, list)
        or not isinstance(token_body, dict)
        or not isinstance(token_body.get("tokens"), list)
    ):
        raise ValueError("spec: Range successor pool source shapes are invalid")
    allowlist = _token_allowlist(token_body, "Range successor token-list source")
    pools_by_id = {}
    for pool in pool_rows:
        if not isinstance(pool, dict):
            raise ValueError("spec: every Range successor pool row must be an object")
        pool_id = str(pool.get("id") or "").lower()
        if ADDRESS.fullmatch(pool_id) is None or pool_id in pools_by_id:
            raise ValueError("spec: Range successor pool ids are invalid or duplicated")
        pools_by_id[pool_id] = pool
    for position in positions:
        pool = pools_by_id.get(position["pool_id"])
        if pool is not None:
            try:
                pool_token0 = pool["token0"]["id"].lower()
                pool_token1 = pool["token1"]["id"].lower()
            except (AttributeError, KeyError, TypeError) as exc:
                raise ValueError(
                    "spec: Range successor pool row has invalid token identities"
                ) from exc
            if (
                pool_token0 != position["token0"]
                or pool_token1 != position["token1"]
                or _yield_number(pool, "feeTier") != position["fee"]
            ):
                raise ValueError(
                    "spec: Range successor position does not match its frozen pool row"
                )
        failed_gate = (
            "pool_not_in_frozen_truth"
            if pool is None
            else _yield_first_failed_gate(pool, allowlist)
        )
        position["pool_gate_passes"] = failed_gate is None
        position["first_failed_gate"] = failed_gate
        for target, source in (
            ("fee_usd_24h", "feeUSD24h"),
            ("protocol_fee_usd_24h", "protocolFeeUSD24h"),
            ("tvl_usd", "tvlUSD"),
        ):
            position[target] = (
                None
                if pool is None or pool.get(source) is None
                else _yield_number(pool, source)
            )
        if failed_gate is None:
            gross_apr = position["fee_usd_24h"] * 365 / position["tvl_usd"]
            net_apr = (
                (position["fee_usd_24h"] - position["protocol_fee_usd_24h"])
                * 365
                / position["tvl_usd"]
            )
            position.update(
                {
                    "gross_apr": gross_apr,
                    "net_apr": net_apr,
                    "annual_gross_usd": 10000 * gross_apr,
                    "annual_net_usd": 10000 * net_apr,
                    "annual_overstatement_usd": 10000 * (gross_apr - net_apr),
                    "cost_only_break_even_days": (
                        25 / (10000 * net_apr / 365) if net_apr > 0 else None
                    ),
                }
            )
        else:
            position.update(
                {
                    "gross_apr": None,
                    "net_apr": None,
                    "annual_gross_usd": None,
                    "annual_net_usd": None,
                    "annual_overstatement_usd": None,
                    "cost_only_break_even_days": None,
                }
            )

    accounting = frame["rpc_call_accounting"]
    unique_live_pools = len({position["pool_id"] for position in positions})
    expected_accounting = {
        "eth_blockNumber": 1,
        "eth_getBlockByNumber": 1,
        "totalSupply": 1,
        "tokenByIndex": frame_definition["sample_size"],
        "ownerOf": frame_definition["sample_size"],
        "userPositionInfos": farm_calls,
        "positions": frame_definition["sample_size"] - len(conflicted),
        "getPool": unique_live_pools,
        "slot0": unique_live_pools,
        "eth_getLogs": 0,
    }
    expected_accounting["total"] = sum(expected_accounting.values())
    if accounting != expected_accounting:
        raise ValueError("spec: Range successor RPC call accounting is inconsistent")
    return candidate_wallets, positions, conflicted, frame


def _range_successor_stratum(position: dict) -> str | None:
    if not position["pool_gate_passes"]:
        return "nonzero_liquidity_failed_gate"
    if position["range_status"] == "in_range":
        return "passing_gate_in_range"
    return "passing_gate_out_of_range"


def range_selected_positions(spec: PairedSpec, positions: list[dict]) -> list[dict]:
    """Select the registered lowest-hash position from each successor stratum."""
    strata = [row["name"] for row in _range_successor_frame(spec)["strata"]]
    # A family that registers prior exposure removes those token ids from selection only.
    # They stay in the published eligible manifest, so the exclusion is visible rather than
    # silently shrinking the population it was drawn from.
    exposed = (
        _range_prior_exposure(spec)
        if spec.case_selection.get("prior_exposure_exclusion") is not None
        else set()
    )
    selected = []
    for stratum in strata:
        candidates = [
            row
            for row in positions
            if _range_successor_stratum(row) == stratum
            and row["token_id"] not in exposed
        ]
        if not candidates:
            raise ValueError(f"spec: Range successor stratum {stratum!r} is empty")
        selected.append(
            min(
                candidates,
                key=lambda row: hashlib.sha256(
                    (
                        f"{spec.stage_one_protocol_hash}|56|{RANGE_POSITION_MANAGER}|"
                        f"{row['token_id']}|{stratum}"
                    ).encode("utf-8")
                ).hexdigest(),
            )
        )
    return selected


def _range_successor_public_position(position: dict) -> dict:
    return {
        name: position[name]
        for name in (
            "position_manager",
            "wallet",
            "token_id",
            "range_status",
            "liquidity",
            "pool_gate_passes",
            "first_failed_gate",
        )
    }


def _range_successor_truth(position: dict) -> dict:
    truth = {
        name: position[name]
        for name in (
            "range_status",
            "liquidity",
            "pool_gate_passes",
            "first_failed_gate",
            "current_tick",
            "tick_lower",
            "tick_upper",
            "fee_usd_24h",
            "protocol_fee_usd_24h",
            "tvl_usd",
            "gross_apr",
            "net_apr",
            "annual_gross_usd",
            "annual_net_usd",
            "annual_overstatement_usd",
            "cost_only_break_even_days",
        )
    }
    truth.update(
        {
            "frame_sample_size": 1024,
            "frame_unique_indices": 1024,
            "frame_complete": True,
        }
    )
    return truth


def _validate_range_successor_inputs(
    spec: PairedSpec, body: dict, cases: list[dict], repo_root: Path
) -> None:
    manifest = body.get("selection_manifest")
    if not isinstance(manifest, dict):
        raise ValueError("spec: Range successor inputs need a selection_manifest")
    _required_fields(
        manifest,
        {
            "candidate_wallets",
            "eligible_positions",
            "conflict_exclusions",
            "source_refs",
        },
        "Range successor selection manifest",
    )
    source_refs = manifest["source_refs"]
    source_wallets, source_positions, source_conflicts, frame = (
        _range_successor_source_frame(spec, source_refs, repo_root)
    )
    candidate_wallets = manifest["candidate_wallets"]
    if not isinstance(candidate_wallets, list) or candidate_wallets != sorted(
        source_wallets
    ):
        raise ValueError(
            "spec: Range successor candidate wallets differ from the frame"
        )
    eligible = manifest["eligible_positions"]
    expected_eligible = [
        _range_successor_public_position(position) for position in source_positions
    ]
    if eligible != expected_eligible:
        raise ValueError(
            "spec: Range successor eligible positions differ from the frame"
        )
    if manifest["conflict_exclusions"] != source_conflicts:
        raise ValueError("spec: Range successor conflicts differ from the frame")
    selected = range_selected_positions(spec, source_positions)
    if len(cases) != len(selected):
        raise ValueError("spec: Range successor cases do not fill every stratum")
    required = {
        "case_id",
        "selection_stratum",
        "chain_id",
        "position_manager",
        "wallet",
        "token_id",
        "observation_block",
        "observation_time",
        "declared_position_value_usd",
        "estimated_recenter_cost_usd",
        "decision_horizon_days",
        "source_refs",
        "truth",
    }
    for case, position in zip(cases, selected, strict=True):
        _required_fields(case, required, "Range successor case")
        stratum = _range_successor_stratum(position)
        if (
            set(case) != required
            or case["case_id"] != f"range-{stratum}-{position['token_id']}"
            or case["selection_stratum"] != stratum
            or case["chain_id"] != 56
            or str(case["position_manager"]).lower() != RANGE_POSITION_MANAGER
            or str(case["wallet"]).lower() != position["wallet"]
            or case["token_id"] != position["token_id"]
            or case["observation_block"] != frame["observation_block"]
            or case["observation_time"] != frame["observation_time"]
            or case["declared_position_value_usd"] != 10000
            or case["estimated_recenter_cost_usd"] != 25
            or case["decision_horizon_days"] != 30
            or case["source_refs"] != source_refs
            or case["truth"] != _range_successor_truth(position)
        ):
            raise ValueError("spec: Range successor case contradicts its frozen frame")


def _decode_embedded_bytes(digest, encoded, context: str) -> bytes:
    if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
        raise ValueError(f"spec: {context} digest is invalid")
    try:
        raw = b64decode(encoded, validate=True)
    except (Base64Error, ValueError, TypeError) as exc:
        raise ValueError(f"spec: {context} body is not valid base64") from exc
    actual = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual, digest):
        raise ValueError(f"spec: {context} body does not match its digest")
    return raw


def _valid_labels(values) -> bool:
    return (
        isinstance(values, list)
        and all(isinstance(label, str) and label.strip() for label in values)
        and len(values) == len(set(values))
    )


def _calibration_number(value, context: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise ValueError(f"spec: {context} must be a finite number")
    return float(value)


def _computed_calibration_truth(spec: PairedSpec | str, inputs: dict) -> dict | None:
    spec_id = spec.spec_id if isinstance(spec, PairedSpec) else spec
    range_family = (
        is_range_family(spec)
        if isinstance(spec, PairedSpec)
        else spec_id
        in {"v3-01-range-doctor", "v3-05-range-doctor", "v3-07-range-doctor"}
    )
    if range_family:
        if not isinstance(inputs, dict):
            raise ValueError("spec: Range calibration input must be an object")
        _required_fields(
            inputs,
            {
                "current_tick",
                "tick_lower",
                "tick_upper",
                "fee_usd_24h",
                "protocol_fee_usd_24h",
                "tvl_usd",
                "declared_position_value_usd",
                "estimated_recenter_cost_usd",
            },
            "Range calibration input",
        )
        ticks = (inputs["current_tick"], inputs["tick_lower"], inputs["tick_upper"])
        if not all(
            isinstance(value, int) and not isinstance(value, bool) for value in ticks
        ):
            raise ValueError("spec: Range calibration ticks must be integers")
        current_tick, tick_lower, tick_upper = ticks
        if tick_lower >= tick_upper:
            raise ValueError("spec: Range calibration tick bounds are not ordered")
        fee = _calibration_number(inputs["fee_usd_24h"], "Range calibration fee")
        protocol_fee = _calibration_number(
            inputs["protocol_fee_usd_24h"], "Range calibration protocol fee"
        )
        tvl = _calibration_number(inputs["tvl_usd"], "Range calibration TVL")
        value = _calibration_number(
            inputs["declared_position_value_usd"], "Range calibration position value"
        )
        cost = _calibration_number(
            inputs["estimated_recenter_cost_usd"], "Range calibration recenter cost"
        )
        if tvl <= 0 or value <= 0 or cost < 0:
            raise ValueError(
                "spec: Range calibration economic inputs are out of bounds"
            )
        status = (
            "below_range"
            if current_tick < tick_lower
            else "above_range"
            if current_tick >= tick_upper
            else "in_range"
        )
        gross_apr = fee * 365 / tvl
        net_apr = (fee - protocol_fee) * 365 / tvl
        return {
            "range_status": status,
            "gross_apr": gross_apr,
            "net_apr": net_apr,
            "annual_gross_usd": value * gross_apr,
            "annual_net_usd": value * net_apr,
            "annual_overstatement_usd": value * (gross_apr - net_apr),
            "cost_only_break_even_days": (
                cost / (value * net_apr / 365) if net_apr > 0 else None
            ),
        }
    if (
        is_yield_family(spec)
        if isinstance(spec, PairedSpec)
        else spec_id in {"v3-02-yield-router", "v3-06-yield-router-assisted"}
    ):
        if not isinstance(inputs, dict):
            raise ValueError("spec: Yield calibration input must be an object")
        _required_fields(
            inputs,
            {
                "allowlist",
                "current_pool",
                "destination_pool",
                "position_value_usd",
                "switching_cost_usd",
                "decision_horizon_days",
            },
            "Yield calibration input",
        )
        allowlist_values = inputs["allowlist"]
        if (
            not isinstance(allowlist_values, list)
            or not allowlist_values
            or not all(
                isinstance(address, str) and ADDRESS.fullmatch(address)
                for address in allowlist_values
            )
        ):
            raise ValueError("spec: Yield calibration allowlist is invalid")
        allowlist = {address.lower() for address in allowlist_values}
        current_pool = inputs["current_pool"]
        destination_pool = inputs["destination_pool"]
        if not isinstance(current_pool, dict) or not isinstance(destination_pool, dict):
            raise ValueError("spec: Yield calibration pools must be objects")
        current_gate = _yield_first_failed_gate(current_pool, allowlist)
        destination_gate = _yield_first_failed_gate(destination_pool, allowlist)
        value = _calibration_number(
            inputs["position_value_usd"], "Yield calibration position value"
        )
        cost = _calibration_number(
            inputs["switching_cost_usd"], "Yield calibration switching cost"
        )
        horizon = inputs["decision_horizon_days"]
        if (
            value <= 0
            or cost < 0
            or not isinstance(horizon, int)
            or isinstance(horizon, bool)
            or horizon <= 0
        ):
            raise ValueError("spec: Yield calibration scenario is out of bounds")
        current_net = (
            (
                _yield_number(current_pool, "feeUSD24h")
                - _yield_number(current_pool, "protocolFeeUSD24h")
            )
            * 365
            / _yield_number(current_pool, "tvlUSD")
            if current_gate is None
            else None
        )
        destination_net = (
            (
                _yield_number(destination_pool, "feeUSD24h")
                - _yield_number(destination_pool, "protocolFeeUSD24h")
            )
            * 365
            / _yield_number(destination_pool, "tvlUSD")
            if destination_gate is None
            else None
        )
        extra_per_day = (
            value * (destination_net - current_net) / 365
            if current_net is not None and destination_net is not None
            else None
        )
        days = (
            cost / extra_per_day
            if extra_per_day is not None and extra_per_day > 0
            else None
        )
        decision = (
            None
            if current_gate is not None or destination_gate is not None
            else "MOVE"
            if days is not None and days <= horizon
            else "STAY"
        )
        return {
            "current_first_failed_gate": current_gate,
            "destination_first_failed_gate": destination_gate,
            "current_net_apr": current_net,
            "destination_net_apr": destination_net,
            "extra_usd_per_day": extra_per_day,
            "days_to_recover": days,
            "decision": decision,
        }
    return None


def _calibration_truth_matches(actual, expected) -> bool:
    if not isinstance(actual, dict) or set(actual) != set(expected):
        return False
    for name, expected_value in expected.items():
        actual_value = actual[name]
        if isinstance(expected_value, float):
            if (
                not isinstance(actual_value, (int, float))
                or isinstance(actual_value, bool)
                or not math.isclose(
                    actual_value, expected_value, rel_tol=1e-12, abs_tol=1e-12
                )
            ):
                return False
        elif actual_value != expected_value:
            return False
    return True


def _validate_evaluator_calibration(
    spec: PairedSpec, body: dict, held_out_cases: list[dict], repo_root: Path
) -> None:
    vendor_classes = (
        _warden_vendor_classes(body, repo_root) if is_warden_family(spec) else set()
    )
    shared = body.get("calibration_set")
    if not isinstance(shared, dict):
        raise ValueError("spec: input envelope needs one shared calibration_set")
    _required_fields(
        shared,
        {"sha256", "body_base64"},
        "shared evaluator calibration set",
    )
    shared_raw = _decode_embedded_bytes(
        shared["sha256"], shared["body_base64"], "shared evaluator calibration set"
    )
    try:
        shared_body = json.loads(shared_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("spec: shared calibration set is not UTF-8 JSON") from exc
    if not isinstance(shared_body, dict):
        raise ValueError("spec: shared calibration set must be an object")
    _required_fields(shared_body, {"spec_id", "cases"}, "shared calibration set")
    if shared_body["spec_id"] != spec.spec_id:
        raise ValueError("spec: shared calibration set names a different family")
    if is_warden_family(spec) and (
        not _valid_labels(shared_body.get("class_vocabulary"))
        or set(shared_body["class_vocabulary"]) != vendor_classes
    ):
        raise ValueError(
            "spec: Warden calibration vocabulary differs from the frozen vendor snapshot"
        )
    shared_cases = shared_body["cases"]
    if not isinstance(shared_cases, list) or len(shared_cases) != 8:
        raise ValueError(
            "spec: shared calibration set must contain exactly eight cases"
        )
    shared_by_id = {}
    for case in shared_cases:
        if not isinstance(case, dict):
            raise ValueError("spec: every shared calibration case must be an object")
        fields = {"case_id", "input"}
        fields |= (
            {"expected_hostile", "expected_classes"}
            if is_warden_family(spec)
            else {"expected"}
        )
        _required_fields(case, fields, "shared calibration case")
        case_id = case["case_id"]
        if (
            not isinstance(case_id, str)
            or not case_id.strip()
            or case_id in shared_by_id
            or case["input"] in (None, "", [], {})
        ):
            raise ValueError("spec: shared calibration case is invalid or duplicated")
        if is_warden_family(spec) and (
            not isinstance(case["expected_hostile"], bool)
            or not _valid_labels(case["expected_classes"])
            or (case["expected_hostile"] and not case["expected_classes"])
            or (not case["expected_hostile"] and case["expected_classes"])
            or not isinstance(case["input"], dict)
            or set(case["input"]) != {"payload"}
            or not isinstance(case["input"]["payload"], str)
            or not case["input"]["payload"].strip()
        ):
            raise ValueError("spec: shared Warden calibration truth is invalid")
        if (
            is_warden_family(spec)
            and not set(case["expected_classes"]) <= vendor_classes
        ):
            raise ValueError(
                "spec: the shared Warden calibration key names a class the vendor never "
                "published; every calibration class must be a published vendor class"
            )
        if _warden_policy_enabled(spec):
            _required_fields(
                case,
                {"expected_verdict", "evidence_spans"},
                "pilot-informed Warden calibration case",
            )
            if case["expected_verdict"] != _warden_expected_verdict(
                case["expected_classes"]
            ):
                raise ValueError(
                    "spec: Warden calibration verdict violates the composition rule"
                )
            spans = case["evidence_spans"]
            if not isinstance(spans, list) or {
                span.get("label") for span in spans if isinstance(span, dict)
            } != set(case["expected_classes"]):
                raise ValueError(
                    "spec: every Warden calibration label needs an evidence span"
                )
            payload_bytes = case["input"]["payload"].encode("utf-8")
            for span in spans:
                _required_fields(
                    span,
                    {"label", "start", "end", "basis"},
                    "pilot-informed Warden calibration evidence",
                )
                if (
                    not isinstance(span["start"], int)
                    or isinstance(span["start"], bool)
                    or not isinstance(span["end"], int)
                    or isinstance(span["end"], bool)
                    or not 0 <= span["start"] < span["end"] <= len(payload_bytes)
                    or span["basis"] not in {"surface", "unicode_normalized", "decoded"}
                ):
                    raise ValueError("spec: Warden calibration evidence is invalid")
                try:
                    evidence = payload_bytes[span["start"] : span["end"]].decode(
                        "utf-8"
                    )
                except UnicodeDecodeError as exc:
                    raise ValueError(
                        "spec: Warden calibration evidence splits a UTF-8 character"
                    ) from exc
                if not evidence.strip() or (
                    span["basis"] != "surface"
                    and not (
                        isinstance(span.get("derived_text"), str)
                        and span["derived_text"].strip()
                    )
                ):
                    raise ValueError("spec: Warden calibration evidence is blank")
        computed = _computed_calibration_truth(spec, case["input"])
        if computed is not None and not _calibration_truth_matches(
            case["expected"], computed
        ):
            raise ValueError(
                "spec: shared calibration answer key contradicts its family formulas"
            )
        shared_by_id[case_id] = case
    if is_range_family(spec) and {
        case["expected"]["range_status"] for case in shared_cases
    } != {"in_range", "above_range", "below_range"}:
        raise ValueError("spec: Range calibration must cover all three range states")
    if is_yield_family(spec) and (
        None
        not in {case["expected"]["current_first_failed_gate"] for case in shared_cases}
        or len({case["expected"]["current_first_failed_gate"] for case in shared_cases})
        < 3
    ):
        raise ValueError(
            "spec: Yield calibration must cover eligibility and exclusions"
        )
    if is_warden_family(spec) and {
        case["expected_hostile"] for case in shared_cases
    } != {True, False}:
        raise ValueError("spec: Warden calibration must cover hostile and benign truth")
    if is_warden_family(spec) and {
        case["input"]["payload"] for case in shared_cases
    } & {
        case.get("text")
        for case in held_out_cases
        if isinstance(case, dict) and isinstance(case.get("text"), str)
    }:
        raise ValueError("spec: Warden calibration payloads overlap the held-out set")

    calibration = body.get("evaluator_calibration")
    roster = spec.scoring["evaluator_roster"]
    if not isinstance(calibration, list) or len(calibration) != len(roster):
        raise ValueError(
            "spec: input envelope needs one evaluator_calibration record per seat"
        )
    expected_ids = [row["evaluator_id"] for row in roster]
    if [
        row.get("evaluator_id") for row in calibration if isinstance(row, dict)
    ] != expected_ids:
        raise ValueError("spec: evaluator calibration seats do not match the roster")
    for row in calibration:
        _required_fields(
            row,
            {
                "evaluator_id",
                "model_build",
                "session_id",
                "rubric_anchor_hash",
                "calibration_results",
            },
            f"evaluator calibration {row['evaluator_id']}",
        )
        if not all(
            isinstance(row[name], str) and row[name].strip()
            for name in ("model_build", "session_id")
        ):
            raise ValueError(
                f"spec: evaluator {row['evaluator_id']!r} has no model/session record"
            )
        if row["rubric_anchor_hash"] != canonical_hash(spec.quality_rubric["criteria"]):
            raise ValueError(
                "spec: evaluator did not identify the frozen rubric anchors"
            )
        results = row["calibration_results"]
        if not isinstance(results, list) or len(results) != 8:
            raise ValueError(
                "spec: evaluator calibration artifact must contain exactly eight results"
            )
        result_ids = []
        for result in results:
            if not isinstance(result, dict):
                raise ValueError(
                    "spec: every evaluator calibration result must be an object"
                )
            _required_fields(
                result, {"case_id", "input"}, "evaluator calibration result"
            )
            if (
                not isinstance(result["case_id"], str)
                or not result["case_id"].strip()
                or result["input"] in (None, "", [], {})
            ):
                raise ValueError("spec: evaluator calibration result is invalid")
            result_ids.append(result["case_id"])
        if set(result_ids) != set(shared_by_id) or len(set(result_ids)) != 8:
            raise ValueError(
                "spec: evaluator calibration results do not cover the shared cases"
            )
        if is_warden_family(spec):
            decisions = 0
            verdicts = 0
            true_positive = false_positive = false_negative = 0
            for result in results:
                _required_fields(
                    result,
                    {
                        "expected_hostile",
                        "predicted_hostile",
                        "expected_classes",
                        "predicted_classes",
                    },
                    "Warden evaluator calibration result",
                )
                if _warden_policy_enabled(spec):
                    _required_fields(
                        result,
                        {"expected_verdict", "predicted_verdict"},
                        "pilot-informed Warden evaluator calibration result",
                    )
                if not isinstance(result["expected_hostile"], bool) or not isinstance(
                    result["predicted_hostile"], bool
                ):
                    raise ValueError(
                        "spec: Warden calibration decisions must be booleans"
                    )
                shared_case = shared_by_id[result["case_id"]]
                if (
                    result["input"] != shared_case["input"]
                    or result["expected_hostile"] is not shared_case["expected_hostile"]
                    or result["expected_classes"] != shared_case["expected_classes"]
                    or (
                        _warden_policy_enabled(spec)
                        and result["expected_verdict"]
                        != shared_case["expected_verdict"]
                    )
                ):
                    raise ValueError(
                        "spec: Warden evaluator result contradicts the shared answer key"
                    )
                expected_classes = result["expected_classes"]
                predicted_classes = result["predicted_classes"]
                if not _valid_labels(expected_classes) or not _valid_labels(
                    predicted_classes
                ):
                    raise ValueError("spec: Warden calibration classes are invalid")
                if not set(expected_classes) | set(predicted_classes) <= vendor_classes:
                    raise ValueError(
                        "spec: a Warden calibration seat answered outside the frozen "
                        "vocabulary; every calibration class must be a published vendor "
                        "class"
                    )
                decisions += result["expected_hostile"] == result["predicted_hostile"]
                if _warden_policy_enabled(spec):
                    if result["predicted_verdict"] not in {
                        "ALLOW",
                        "SANITIZE",
                        "BLOCK",
                    }:
                        raise ValueError(
                            "spec: Warden calibration predicted_verdict is invalid"
                        )
                    verdicts += (
                        result["expected_verdict"] == result["predicted_verdict"]
                    )
                expected_set = set(expected_classes)
                predicted_set = set(predicted_classes)
                true_positive += len(expected_set & predicted_set)
                false_positive += len(predicted_set - expected_set)
                false_negative += len(expected_set - predicted_set)
            denominator = 2 * true_positive + false_positive + false_negative
            micro_f1 = 2 * true_positive / denominator if denominator else 1.0
            if (
                decisions < 7
                or micro_f1 < 0.80
                or (_warden_policy_enabled(spec) and verdicts < 7)
            ):
                raise ValueError("spec: Warden evaluator class micro-F1 is below 0.80")
        else:
            for result in results:
                _required_fields(
                    result,
                    {"expected", "submitted"},
                    "Pancake evaluator calibration result",
                )
                shared_case = shared_by_id[result["case_id"]]
                if (
                    result["input"] != shared_case["input"]
                    or result["expected"] != shared_case["expected"]
                ):
                    raise ValueError(
                        "spec: evaluator result contradicts the shared answer key"
                    )
            if sum(result["expected"] == result["submitted"] for result in results) < 7:
                raise ValueError(
                    "spec: evaluator did not pass at least seven of eight cases"
                )
    if len({row["session_id"] for row in calibration}) != len(roster):
        raise ValueError(
            "spec: every evaluator seat needs its own distinct session; one session id "
            "reported twice is one run counted twice"
        )


def _validate_source_snapshot(
    snapshot: dict,
    name: str,
    *,
    attempts: tuple[datetime, ...] = YIELD_CAPTURE_ATTEMPTS,
):
    _required_fields(
        snapshot,
        {"url", "observed_at", "attempt_ordinal", "sha256", "body_base64"},
        f"Yield {name} source snapshot",
    )
    if not all(
        isinstance(snapshot[field], str) and snapshot[field].strip()
        for field in ("url", "observed_at")
    ):
        raise ValueError(
            f"spec: Yield {name} source URL and observation time are required"
        )
    if snapshot["url"] != YIELD_SOURCE_URLS[name]:
        raise ValueError(f"spec: Yield {name} source URL is not the registered URL")
    observed_at = _utc_timestamp(snapshot["observed_at"], f"Yield {name} observed_at")
    attempt = snapshot["attempt_ordinal"]
    if (
        not isinstance(attempt, int)
        or isinstance(attempt, bool)
        or not 1 <= attempt <= len(attempts)
    ):
        raise ValueError(f"spec: Yield {name} capture attempt is invalid")
    attempt_start = attempts[attempt - 1]
    if not attempt_start <= observed_at < attempt_start + timedelta(minutes=1):
        raise ValueError(
            f"spec: Yield {name} snapshot is outside its registered capture attempt"
        )
    raw = _decode_embedded_bytes(
        snapshot["sha256"], snapshot["body_base64"], f"Yield {name} source"
    )
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"spec: Yield {name} source body is not valid UTF-8 JSON"
        ) from exc


def _utc_timestamp(value: str, context: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"spec: {context} is not an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"spec: {context} must be UTC")
    return parsed


def yield_capture_attempts(spec: PairedSpec) -> tuple[datetime, ...]:
    """Return the capture schedule registered inside a Yield family protocol."""
    if not is_yield_family(spec) and spec.spec_id != (
        "v3-02-yield-router-REHEARSAL-NOT-REGISTERED"
    ):
        raise ValueError("spec: capture attempts requested for a non-Yield family")
    if spec.spec_id in {
        "v3-02-yield-router",
        "v3-02-yield-router-REHEARSAL-NOT-REGISTERED",
    }:
        return YIELD_CAPTURE_ATTEMPTS
    values = spec.case_selection.get("source_capture_attempts")
    if not isinstance(values, list) or len(values) != 3:
        raise ValueError("spec: Yield successor needs exactly three source captures")
    attempts = tuple(_utc_timestamp(value, "Yield source capture") for value in values)
    if attempts != tuple(sorted(set(attempts))):
        raise ValueError("spec: Yield source captures are not strictly increasing")
    return attempts


def _yield_readiness_output(fixture: dict) -> dict:
    required = {"fixture_id", "current_pool_id", "scenario", "source_snapshots"}
    if not isinstance(fixture, dict) or set(fixture) != required:
        raise ValueError("spec: Yield baseline readiness fixture is not self-contained")
    if fixture["fixture_id"] != "readiness-synthetic":
        raise ValueError("spec: Yield readiness fixture id is invalid")
    serialized = json.dumps(fixture, sort_keys=True)
    if any(
        value in serialized
        for value in (
            "02-yield-cases.json",
            "06-yield-assisted-cases.json",
            "yield-01-916f992d",
        )
    ):
        raise ValueError("spec: Yield readiness fixture references official inputs")
    snapshots = fixture["source_snapshots"]
    if not isinstance(snapshots, dict) or set(snapshots) != {"pools", "token_list"}:
        raise ValueError("spec: Yield readiness needs two synthetic snapshots")
    bodies = {}
    for name, snapshot in snapshots.items():
        if not isinstance(snapshot, dict) or set(snapshot) != {
            "url",
            "observed_at",
            "sha256",
            "body",
        }:
            raise ValueError("spec: Yield readiness snapshot is invalid")
        if snapshot["url"] != f"synthetic://yield-readiness/{name}":
            raise ValueError("spec: Yield readiness source is not synthetic")
        _utc_timestamp(snapshot["observed_at"], "Yield readiness observed_at")
        raw = json.dumps(
            snapshot["body"], sort_keys=True, separators=(",", ":")
        ).encode()
        if hashlib.sha256(raw).hexdigest() != snapshot["sha256"]:
            raise ValueError("spec: Yield readiness snapshot digest is incorrect")
        bodies[name] = snapshot["body"]
    pools = bodies["pools"]
    tokens = bodies["token_list"]
    if (
        not isinstance(pools, list)
        or len(pools) != 3
        or not isinstance(tokens, dict)
        or not isinstance(tokens.get("tokens"), list)
    ):
        raise ValueError("spec: Yield readiness source shapes are invalid")
    allowlist = _token_allowlist(tokens, "Yield readiness token-list")
    included = []
    excluded = []
    rows = {}
    for row in pools:
        if not isinstance(row, dict):
            raise ValueError("spec: Yield readiness pool must be an object")
        pool_id = str(row.get("id") or "").lower()
        if ADDRESS.fullmatch(pool_id) is None or pool_id in rows:
            raise ValueError("spec: Yield readiness pool ids are invalid")
        rows[pool_id] = row
        failed = _yield_first_failed_gate(row, allowlist)
        if failed is None:
            included.append(pool_id)
        else:
            excluded.append(
                {
                    "pool_id": pool_id,
                    "first_failed_gate": failed,
                    "reason": failed,
                }
            )
    if len(included) != 2 or len(excluded) != 1:
        raise ValueError("spec: Yield readiness fixture must exercise one exclusion")
    current_pool = fixture["current_pool_id"]
    if current_pool not in included:
        raise ValueError("spec: Yield readiness current pool is not eligible")
    scenario = fixture["scenario"]
    expected_scenario = {
        "position_size_usd": 10000,
        "switching_cost_usd": 25,
        "horizon_days": 30,
    }
    if scenario != expected_scenario:
        raise ValueError("spec: Yield readiness scenario is invalid")
    rates = {
        pool_id: (
            _yield_number(rows[pool_id], "feeUSD24h")
            - _yield_number(rows[pool_id], "protocolFeeUSD24h")
        )
        * 365
        / _yield_number(rows[pool_id], "tvlUSD")
        for pool_id in included
    }
    destination = min(included, key=lambda pool_id: (-rates[pool_id], pool_id))
    current_rate = rates[current_pool]
    destination_rate = rates[destination]
    extra = 10000 * (destination_rate - current_rate) / 365
    days = 25 / extra if extra > 0 else None
    move = days is not None and days <= 30
    formula = "(feeUSD24h-protocolFeeUSD24h)*365/tvlUSD"

    def rate_record(pool_id: str) -> dict:
        row = rows[pool_id]
        return {
            "pool_id": pool_id,
            "feeUSD24h": row["feeUSD24h"],
            "protocolFeeUSD24h": row["protocolFeeUSD24h"],
            "tvlUSD": row["tvlUSD"],
            "net_apr": rates[pool_id],
            "formula": formula,
            "observation_window": "24h",
        }

    return {
        "sources": {
            name: {
                key: snapshots[name][key] for key in ("url", "observed_at", "sha256")
            }
            for name in ("pools", "token_list")
        },
        "universe": {
            "considered": len(pools),
            "included_count": len(included),
            "excluded_count": len(excluded),
            "included_pool_ids": included,
            "excluded": excluded,
        },
        "rates": {
            "current": rate_record(current_pool),
            "candidates": [rate_record(pool_id) for pool_id in included],
        },
        "scenario": {
            **scenario,
            "current_net_apr": current_rate,
            "destination_net_apr": destination_rate,
            "extra_usd_per_day": extra,
            "days_to_recover": days,
            "formula": (
                "extra_usd_per_day=10000*(destination_net_apr-current_net_apr)/365; "
                "days_to_recover=25/extra_usd_per_day"
            ),
            "cost_scope": (
                "Caller-supplied estimate covering gas on all legs, swap fee and "
                "impact, and uncollected fees"
            ),
        },
        "decision": {
            "move_or_stay": "MOVE" if move else "STAY",
            "destination_pool_id": destination if move else None,
            "rule": (
                "Highest eligible net APR; lowercase pool-address ascending tie-break; "
                "MOVE only for a positive delta recovered within 30 days"
            ),
        },
        "limitations": [
            "The annualised 24-hour rate is an observation, not a forecast.",
            "A pool-wide rate is not a concentrated-position return.",
            "Destination impermanent loss is not modelled.",
            "The switching cost is caller-supplied.",
            "The comparison is bounded to this exact synthetic readiness fixture.",
        ],
    }


def _validate_yield_successor_registration(spec: PairedSpec) -> None:
    if not is_yield_family(spec):
        raise ValueError("spec: Yield assisted successor must use Yield Router")
    if spec.protocol_correction is not None:
        raise ValueError("spec: a distinct successor cannot be a protocol correction")
    if spec.inputs_ref != "docket/advantage/v3/inputs/06-yield-assisted-cases.json":
        raise ValueError("spec: Yield assisted successor inputs_ref is invalid")
    if yield_capture_attempts(spec) != YIELD_ASSISTED_CAPTURE_ATTEMPTS:
        raise ValueError("spec: Yield assisted capture schedule is invalid")
    if spec.claim != (
        "Within the exact frozen eligible top-pools response and common "
        "$10,000/$25/30-day scenario, the deployed Yield Router's median rubric "
        "total is no lower than the Codex-assisted baseline's, every deployed Yield "
        "Router universe exactly matches the truth manifest, and the deployed Yield "
        "Router is materially faster under the registered complete-pair "
        "30-second/0.50 threshold."
    ) or any(word in spec.claim.lower().split() for word in ("human", "manual")):
        raise ValueError("spec: Yield assisted successor claim is not explicit")
    if {arm: spec.arms[arm].get("display_name") for arm in ARMS} != {
        "agent": "Deployed Yield Router",
        "manual": "Codex-assisted baseline",
    }:
        raise ValueError("spec: Yield assisted arm display names are invalid")
    expected_identity = {
        "arm": "manual",
        "kind": "codex_assisted",
        "operator": "Codex",
        "display_name": "Codex-assisted baseline",
        "human_or_independent": False,
    }
    if spec.execution_protocol.get("baseline_identity") != expected_identity:
        raise ValueError("spec: Yield assisted baseline identity is invalid")
    readiness = spec.execution_protocol.get("baseline_readiness")
    if not isinstance(readiness, dict) or set(readiness) != {
        "required_before_primary",
        "scored",
        "fixture",
        "expected_output",
    }:
        raise ValueError("spec: Yield assisted baseline readiness is incomplete")
    if (
        readiness["required_before_primary"] is not True
        or readiness["scored"] is not False
    ):
        raise ValueError("spec: Yield assisted readiness flags are invalid")
    if readiness["expected_output"] != _yield_readiness_output(readiness["fixture"]):
        raise ValueError("spec: Yield assisted readiness answer is not canonical")
    provenance = spec.successor_provenance
    if not isinstance(provenance, dict) or set(provenance) != SUCCESSOR_FIELDS:
        raise ValueError("spec: Yield assisted successor provenance is incomplete")
    expected_provenance = {
        "status": "distinct_successor_after_failed_primary",
        "prior_spec_id": "v3-02-yield-router",
        "prior_stage_one_protocol_hash": YIELD_PRIOR_STAGE_ONE_PROTOCOL_HASH,
        "prior_spec_hash": YIELD_PRIOR_SPEC_HASH,
        "prior_ledger_ref": YIELD_PRIOR_LEDGER_REF,
        "reason": YIELD_SUCCESSOR_REASON,
    }
    if provenance != expected_provenance:
        raise ValueError("spec: Yield assisted successor provenance is invalid")


def _yield_number(row: dict, field: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"spec: Yield source row has invalid {field}") from exc
    if not math.isfinite(value):
        raise ValueError(f"spec: Yield source row has non-finite {field}")
    return value


def _token_allowlist(token_body: dict, context: str) -> set[str]:
    allowlist = set()
    for token in token_body["tokens"]:
        if not isinstance(token, dict):
            raise ValueError(f"spec: every {context} token must be an object")
        if token.get("chainId") != 56:
            continue
        address = token.get("address")
        if not isinstance(address, str) or ADDRESS.fullmatch(address) is None:
            raise ValueError(f"spec: every BSC {context} token needs a 20-byte address")
        allowlist.add(address.lower())
    return allowlist


def _yield_first_failed_gate(row: dict, allowlist: set[str]) -> str | None:
    addresses = {}
    for side in ("token0", "token1"):
        token = row.get(side)
        address = str(token.get("id") if isinstance(token, dict) else "").lower()
        if ADDRESS.fullmatch(address) is None:
            raise ValueError(f"spec: Yield source row has invalid {side} id")
        addresses[side] = address
    for side in ("token0", "token1"):
        if addresses[side] not in allowlist:
            return f"{side}_allowlist"
    tvl = _yield_number(row, "tvlUSD")
    if tvl < 10000:
        return "tvl_floor"
    if _yield_number(row, "volumeUSD24h") / tvl > 50:
        return "turnover_ceiling"
    if row.get("feeUSD24h") is None:
        return "feeUSD24h_non_null"
    if row.get("protocolFeeUSD24h") is None:
        return "protocolFeeUSD24h_non_null"
    return None


def _validate_yield_inputs(
    spec: PairedSpec, body: dict, cases: list[dict], _repo_root: Path
) -> None:
    snapshots = body.get("source_snapshots")
    if not isinstance(snapshots, dict) or set(snapshots) != {"pools", "token_list"}:
        raise ValueError(
            "spec: Yield inputs need exactly pools and token_list snapshots"
        )
    attempts = yield_capture_attempts(spec)
    source_bodies = {}
    for name, snapshot in snapshots.items():
        if not isinstance(snapshot, dict):
            raise ValueError(f"spec: Yield {name} source snapshot must be an object")
        source_bodies[name] = _validate_source_snapshot(
            snapshot, name, attempts=attempts
        )
    if (
        snapshots["pools"]["attempt_ordinal"]
        != snapshots["token_list"]["attempt_ordinal"]
    ):
        raise ValueError("spec: Yield snapshots must use one capture attempt")
    chosen_attempt = snapshots["pools"]["attempt_ordinal"]
    capture_log = body.get("capture_log")
    if not isinstance(capture_log, list) or len(capture_log) != chosen_attempt:
        raise ValueError("spec: Yield inputs need every scheduled capture attempt")
    for index, attempt in enumerate(capture_log, start=1):
        if not isinstance(attempt, dict):
            raise ValueError("spec: every Yield capture attempt must be an object")
        _required_fields(
            attempt,
            {"attempt_ordinal", "scheduled_at", "pools_status", "token_list_status"},
            "Yield capture attempt",
        )
        expected_time = attempts[index - 1].isoformat().replace("+00:00", "Z")
        if (
            attempt["attempt_ordinal"] != index
            or attempt["scheduled_at"] != expected_time
            or not isinstance(attempt["pools_status"], int)
            or isinstance(attempt["pools_status"], bool)
            or not isinstance(attempt["token_list_status"], int)
            or isinstance(attempt["token_list_status"], bool)
        ):
            raise ValueError("spec: Yield capture attempt contradicts the schedule")
        both_succeeded = (
            attempt["pools_status"] == 200 and attempt["token_list_status"] == 200
        )
        if both_succeeded != (index == chosen_attempt):
            raise ValueError("spec: Yield did not freeze its first complete capture")
    if _utc_timestamp(
        snapshots["pools"]["observed_at"], "Yield pools observed_at"
    ) > _utc_timestamp(
        snapshots["token_list"]["observed_at"], "Yield token_list observed_at"
    ):
        raise ValueError("spec: Yield snapshots were not captured in registered order")

    pools_body = source_bodies["pools"]
    if isinstance(pools_body, list):
        pool_rows = pools_body
    elif isinstance(pools_body, dict) and isinstance(pools_body.get("rows"), list):
        pool_rows = pools_body["rows"]
    else:
        raise ValueError("spec: Yield pools snapshot is not a list or rows envelope")
    if not all(isinstance(row, dict) for row in pool_rows):
        raise ValueError("spec: every Yield source pool row must be an object")
    token_body = source_bodies["token_list"]
    if not isinstance(token_body, dict) or not isinstance(
        token_body.get("tokens"), list
    ):
        raise ValueError("spec: Yield token_list snapshot has no tokens array")
    allowlist = _token_allowlist(token_body, "Yield token-list source")

    manifest = body.get("truth_manifest")
    if not isinstance(manifest, dict):
        raise ValueError("spec: Yield inputs need a truth_manifest object")
    _required_fields(
        manifest,
        {"raw_pool_ids", "included_pool_ids", "excluded"},
        "Yield truth_manifest",
    )
    raw_ids = manifest["raw_pool_ids"]
    included = manifest["included_pool_ids"]
    excluded = manifest["excluded"]
    if not all(isinstance(values, list) for values in (raw_ids, included, excluded)):
        raise ValueError("spec: Yield manifest partitions must be arrays")
    if not all(
        isinstance(pool_id, str) and ADDRESS.fullmatch(pool_id)
        for pool_id in raw_ids + included
    ):
        raise ValueError("spec: Yield manifest pool ids must be 20-byte addresses")
    excluded_ids = []
    for row in excluded:
        if not isinstance(row, dict):
            raise ValueError("spec: every Yield exclusion must be an object")
        _required_fields(
            row,
            {"pool_id", "first_failed_gate", "reason"},
            "Yield exclusion",
        )
        if (
            not isinstance(row["pool_id"], str)
            or ADDRESS.fullmatch(row["pool_id"]) is None
        ):
            raise ValueError("spec: Yield excluded pool ids must be 20-byte addresses")
        if row["reason"] != row["first_failed_gate"]:
            raise ValueError(
                "spec: Yield exclusion reason must be its registered gate label"
            )
        excluded_ids.append(row["pool_id"])
    if len(raw_ids) != len(set(raw_ids)) or len(included) != len(set(included)):
        raise ValueError("spec: Yield manifest pool ids are not distinct")
    if len(excluded_ids) != len(set(excluded_ids)):
        raise ValueError("spec: a Yield pool is excluded more than once")
    if set(included) & set(excluded_ids) or set(raw_ids) != set(included) | set(
        excluded_ids
    ):
        raise ValueError(
            "spec: Yield manifest does not partition every raw pool exactly once"
        )
    if len(included) < spec.n_planned:
        raise ValueError("spec: Yield inputs have fewer than five eligible pools")

    source_ids = [str(row.get("id") or "").lower() for row in pool_rows]
    if any(ADDRESS.fullmatch(pool_id) is None for pool_id in source_ids):
        raise ValueError("spec: every Yield source pool needs a 20-byte id")
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("spec: Yield source pool ids are not distinct")
    expected_included = []
    expected_excluded = []
    rows_by_id = {}
    for pool_id, row in zip(source_ids, pool_rows, strict=True):
        rows_by_id[pool_id] = row
        failed_gate = _yield_first_failed_gate(row, allowlist)
        if failed_gate is None:
            expected_included.append(pool_id)
        else:
            expected_excluded.append(
                {
                    "pool_id": pool_id,
                    "first_failed_gate": failed_gate,
                    "reason": failed_gate,
                }
            )
    if raw_ids != source_ids:
        raise ValueError(
            "spec: Yield raw_pool_ids do not preserve every source row in order"
        )
    if included != expected_included or excluded != expected_excluded:
        raise ValueError(
            "spec: Yield truth manifest does not match the registered gate"
        )

    selected = sorted(
        included,
        key=lambda pool_id: hashlib.sha256(
            f"{spec.stage_one_protocol_hash}{str(pool_id).lower()}".encode()
        ).hexdigest(),
    )[: spec.n_planned]
    case_pool_ids = []
    for index, case in enumerate(cases):
        _required_fields(
            case,
            {
                "case_id",
                "pool_id",
                "position_value_usd",
                "switching_cost_usd",
                "decision_horizon_days",
                "truth",
            },
            f"Yield case {index + 1}",
        )
        if case["position_value_usd"] != 10000 or case["switching_cost_usd"] != 25:
            raise ValueError("spec: Yield cases must use the registered value and cost")
        if case["decision_horizon_days"] != 30:
            raise ValueError("spec: Yield cases must use the registered 30-day horizon")
        if not isinstance(case["truth"], dict):
            raise ValueError("spec: every Yield case needs an object truth record")
        if (
            not isinstance(case["pool_id"], str)
            or ADDRESS.fullmatch(case["pool_id"]) is None
        ):
            raise ValueError("spec: every Yield case pool_id must be a 20-byte address")
        case_pool_ids.append(case["pool_id"])
    if case_pool_ids != selected:
        raise ValueError("spec: Yield cases are not the registered hash-ordered sample")

    net_rates = {
        pool_id: (
            _yield_number(rows_by_id[pool_id], "feeUSD24h")
            - _yield_number(rows_by_id[pool_id], "protocolFeeUSD24h")
        )
        * 365
        / _yield_number(rows_by_id[pool_id], "tvlUSD")
        for pool_id in included
    }
    best_pool = min(included, key=lambda pool_id: (-net_rates[pool_id], pool_id))
    for case in cases:
        truth = case["truth"]
        _required_fields(
            truth,
            {
                "current_net_apr",
                "destination_pool_id",
                "destination_net_apr",
                "extra_usd_per_day",
                "days_to_recover",
                "decision",
            },
            f"Yield case {case['case_id']} truth",
        )
        current_rate = net_rates[case["pool_id"]]
        best_rate = net_rates[best_pool]
        extra_per_day = 10000 * (best_rate - current_rate) / 365
        days_to_recover = 25 / extra_per_day if extra_per_day > 0 else None
        destination = best_pool if extra_per_day > 0 else None
        decision = (
            "MOVE" if days_to_recover is not None and days_to_recover <= 30 else "STAY"
        )
        expected = {
            "current_net_apr": current_rate,
            "destination_pool_id": destination,
            "destination_net_apr": best_rate if destination else None,
            "extra_usd_per_day": extra_per_day,
            "days_to_recover": days_to_recover,
            "decision": decision,
        }
        for name, value in expected.items():
            actual = truth[name]
            if isinstance(value, float):
                if (
                    not isinstance(actual, (int, float))
                    or isinstance(actual, bool)
                    or not math.isclose(actual, value, rel_tol=1e-12, abs_tol=1e-12)
                ):
                    raise ValueError(f"spec: Yield case truth has incorrect {name}")
            elif actual != value:
                raise ValueError(f"spec: Yield case truth has incorrect {name}")


def _warden_vendor_classes(body: dict, repo_root: Path) -> set[str]:
    """The vendor's own published class list, read from the frozen snapshot.

    Both the calibration answer key and the held-out labels are scored against this
    vocabulary, so it is parsed once here rather than twice with two chances to disagree.
    """
    snapshot = body.get("vendor_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("spec: Warden inputs need a vendor_snapshot object")
    vendor_raw = _validate_locked_source(snapshot, repo_root, "Warden vendor_snapshot")
    try:
        vendor_body = json.loads(vendor_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "spec: Warden vendor snapshot is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(vendor_body, dict) or not isinstance(
        vendor_body.get("classes"), list
    ):
        raise ValueError("spec: Warden vendor snapshot needs a classes array")
    vendor_class_list = vendor_body["classes"]
    if (
        not vendor_class_list
        or not all(
            isinstance(label, str) and label.strip() for label in vendor_class_list
        )
        or len(vendor_class_list) != len(set(vendor_class_list))
    ):
        raise ValueError(
            "spec: Warden vendor classes must be distinct nonblank strings"
        )
    return set(vendor_class_list)


def _validate_warden_inputs(
    spec: PairedSpec, body: dict, cases: list[dict], repo_root: Path
) -> None:
    vendor_classes = _warden_vendor_classes(body, repo_root)

    hostile_count = 0
    benign_count = 0
    critical_hostile_count = 0
    hostile_classes = set()
    payload_ids = set()
    for index, case in enumerate(cases):
        _required_fields(
            case,
            {
                "case_id",
                "payload_id",
                "text",
                "expected_verdict",
                "labels",
                "evidence_spans",
                "hostile",
                "critical",
                "survival_predicates",
            },
            f"Warden case {index + 1}",
        )
        if not isinstance(case["payload_id"], str) or not case["payload_id"].strip():
            raise ValueError("spec: every Warden payload_id must be a nonblank string")
        if case["payload_id"] in payload_ids:
            raise ValueError("spec: Warden payload ids are not distinct")
        payload_ids.add(case["payload_id"])
        if not isinstance(case["text"], str) or not case["text"].strip():
            raise ValueError("spec: every Warden payload text must be nonblank")
        if not isinstance(case["expected_verdict"], str) or case[
            "expected_verdict"
        ] not in {"ALLOW", "SANITIZE", "BLOCK"}:
            raise ValueError("spec: Warden expected_verdict is invalid")
        if not isinstance(case["labels"], list) or not isinstance(
            case["evidence_spans"], list
        ):
            raise ValueError("spec: Warden labels and evidence_spans must be arrays")
        if (
            not all(
                isinstance(label, str) and label.strip() for label in case["labels"]
            )
            or len(case["labels"]) != len(set(case["labels"]))
            or not set(case["labels"]) <= vendor_classes
        ):
            raise ValueError(
                "spec: Warden labels must be distinct registered vendor classes"
            )
        if not isinstance(case["hostile"], bool) or not isinstance(
            case["critical"], bool
        ):
            raise ValueError("spec: Warden hostile and critical flags must be booleans")
        if case["hostile"]:
            if not case["labels"] or case["expected_verdict"] == "ALLOW":
                raise ValueError(
                    "spec: hostile Warden cases need labels and a protective verdict"
                )
            hostile_count += 1
            hostile_classes.update(case["labels"])
        else:
            if case["labels"] or case["expected_verdict"] != "ALLOW":
                raise ValueError(
                    "spec: benign Warden cases must be unlabelled ALLOW truth"
                )
            benign_count += 1
        if _warden_policy_enabled(spec) and case[
            "expected_verdict"
        ] != _warden_expected_verdict(case["labels"]):
            raise ValueError("spec: Warden verdict violates the composition rule")

        evidence_texts = {}
        payload_bytes = case["text"].encode("utf-8")
        text_size = len(payload_bytes)
        for span in case["evidence_spans"]:
            if not isinstance(span, dict):
                raise ValueError("spec: every Warden evidence span must be an object")
            _required_fields(span, {"label", "start", "end"}, "Warden evidence span")
            if _warden_policy_enabled(spec):
                _required_fields(span, {"basis"}, "pilot-informed Warden evidence span")
                if span["basis"] not in {
                    "surface",
                    "unicode_normalized",
                    "decoded",
                }:
                    raise ValueError("spec: Warden evidence basis is invalid")
                if span["basis"] != "surface" and not (
                    isinstance(span.get("derived_text"), str)
                    and span["derived_text"].strip()
                ):
                    raise ValueError(
                        "spec: derived Warden evidence needs its decoded or normalized text"
                    )
            if span["label"] not in case["labels"]:
                raise ValueError(
                    "spec: Warden evidence span names an unregistered case label"
                )
            if (
                not isinstance(span["start"], int)
                or isinstance(span["start"], bool)
                or not isinstance(span["end"], int)
                or isinstance(span["end"], bool)
                or not 0 <= span["start"] < span["end"] <= text_size
            ):
                raise ValueError("spec: Warden evidence byte offsets are invalid")
            key = (span["label"], span["start"], span["end"])
            if key in evidence_texts:
                raise ValueError("spec: Warden evidence spans are duplicated")
            try:
                evidence_texts[key] = payload_bytes[span["start"] : span["end"]].decode(
                    "utf-8"
                )
            except UnicodeDecodeError as exc:
                raise ValueError(
                    "spec: Warden evidence offsets split a UTF-8 character"
                ) from exc
        evidence_keys = set(evidence_texts)
        if case["hostile"] and {key[0] for key in evidence_keys} != set(case["labels"]):
            raise ValueError("spec: every Warden hostile label needs an evidence span")
        if not case["hostile"] and evidence_keys:
            raise ValueError("spec: a benign Warden case cannot carry hostile evidence")

        predicates = case["survival_predicates"]
        if not isinstance(predicates, list):
            raise ValueError("spec: Warden survival_predicates must be an array")
        if case["critical"]:
            if not case["hostile"] or not predicates:
                raise ValueError(
                    "spec: every critical Warden case must be hostile and have predicates"
                )
            critical_hostile_count += 1
        for predicate in predicates:
            if not isinstance(predicate, dict):
                raise ValueError(
                    "spec: every Warden survival predicate must be an object"
                )
            _required_fields(
                predicate,
                {"kind", "pattern", "label", "evidence_start", "evidence_end"},
                "Warden survival predicate",
            )
            if (
                not isinstance(predicate["kind"], str)
                or predicate["kind"] not in {"literal", "regex"}
                or not isinstance(predicate["pattern"], str)
                or not predicate["pattern"]
            ):
                raise ValueError("spec: Warden survival predicate is invalid")
            if (
                not isinstance(predicate["label"], str)
                or not isinstance(predicate["evidence_start"], int)
                or isinstance(predicate["evidence_start"], bool)
                or not isinstance(predicate["evidence_end"], int)
                or isinstance(predicate["evidence_end"], bool)
            ):
                raise ValueError("spec: Warden survival predicate evidence is invalid")
            predicate_key = (
                predicate["label"],
                predicate["evidence_start"],
                predicate["evidence_end"],
            )
            if predicate_key not in evidence_keys:
                raise ValueError(
                    "spec: Warden survival predicate is not tied to evidence"
                )
            if predicate["kind"] == "regex":
                try:
                    matched = re.fullmatch(
                        predicate["pattern"], evidence_texts[predicate_key]
                    )
                except re.error as exc:
                    raise ValueError(
                        "spec: Warden survival predicate regex is invalid"
                    ) from exc
            else:
                matched = predicate["pattern"] == evidence_texts[predicate_key]
            if not matched:
                raise ValueError(
                    "spec: Warden survival predicate does not match its source evidence"
                )
        if (
            case["critical"] or (_warden_policy_enabled(spec) and case["hostile"])
        ) and {
            (row["label"], row["evidence_start"], row["evidence_end"])
            for row in predicates
        } != evidence_keys:
            raise ValueError(
                "spec: every critical Warden vector needs a survival predicate"
            )

    if hostile_count < 4 or benign_count < 4:
        raise ValueError(
            "spec: Warden inputs need at least four hostile and four benign cases"
        )
    if len(hostile_classes) < 4:
        raise ValueError(
            "spec: Warden inputs need at least four hostile vendor classes"
        )
    if _warden_policy_enabled(spec) and hostile_classes != vendor_classes:
        raise ValueError(
            "spec: pilot-informed Warden inputs must cover every vendor class"
        )
    if critical_hostile_count < 2:
        raise ValueError("spec: Warden inputs need at least two critical hostile cases")


INPUT_VALIDATORS = {
    "v3-01-range-doctor": _validate_range_inputs,
    "v3-02-yield-router": _validate_yield_inputs,
    "v3-03-warden-security": _validate_warden_inputs,
    "v3-04-warden-security": _validate_warden_inputs,
    "v3-05-range-doctor": _validate_range_successor_inputs,
    "v3-06-yield-router-assisted": _validate_yield_inputs,
    "v3-07-range-doctor": _validate_range_successor_inputs,
}


def _validate_inputs(spec: PairedSpec, raw: bytes, repo_root: Path) -> None:
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"spec {spec.spec_id!r} inputs are not valid UTF-8 JSON"
        ) from exc
    if not isinstance(body, dict):
        raise ValueError(f"spec {spec.spec_id!r} inputs must be a JSON object")
    _required_fields(
        body, {"spec_id", "stage_one_protocol_hash", "cases"}, "input envelope"
    )
    if body["spec_id"] != spec.spec_id:
        raise ValueError(f"spec {spec.spec_id!r} inputs name a different spec_id")
    if body["stage_one_protocol_hash"] != spec.stage_one_protocol_hash:
        raise ValueError(
            f"spec {spec.spec_id!r} inputs name a different stage-one protocol"
        )
    cases = body["cases"]
    if not isinstance(cases, list) or len(cases) != spec.n_planned:
        raise ValueError(
            f"spec {spec.spec_id!r} inputs must contain exactly {spec.n_planned} cases"
        )
    case_ids = []
    for case in cases:
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("case_id"), str)
            or not case["case_id"].strip()
        ):
            raise ValueError(
                f"spec {spec.spec_id!r} every case needs a nonblank case_id"
            )
        case_ids.append(case["case_id"])
    if len(set(case_ids)) != len(case_ids):
        raise ValueError(f"spec {spec.spec_id!r} case ids are not distinct")

    _validate_evaluator_calibration(spec, body, cases, repo_root)

    validator = (
        INPUT_VALIDATORS.get(spec.spec_id, _validate_warden_inputs)
        if is_warden_family(spec)
        else INPUT_VALIDATORS.get(spec.spec_id)
    )
    if validator is None:
        raise ValueError(f"spec {spec.spec_id!r} has no registered input validator")
    validator(spec, body, cases, repo_root)


def assert_runnable(spec: PairedSpec, *, repo_root: Path = REPO_ROOT) -> None:
    """Refuse a run unless the referenced file exists and its exact bytes still match."""
    spec._assert_protocol_unchanged()
    if not spec.runnable:
        raise ValueError(
            f"spec {spec.spec_id!r} has no locked inputs — {spec.inputs_ref!r} must be "
            "frozen in a later commit before either arm runs"
        )
    raw = _inputs_path(spec, repo_root).read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual, spec.inputs_sha256):
        raise ValueError(
            f"spec {spec.spec_id!r} inputs digest mismatch: the registration says "
            f"{spec.inputs_sha256} but {spec.inputs_ref!r} now hashes to {actual}"
        )
    _validate_inputs(spec, raw, repo_root)


def lock_inputs(spec: PairedSpec, *, repo_root: Path = REPO_ROOT) -> PairedSpec:
    """Return stage two by reading the referenced file; callers never supply its digest."""
    spec._assert_protocol_unchanged()
    if spec.runnable:
        raise ValueError(f"spec {spec.spec_id!r} already has locked inputs")
    raw = _inputs_path(spec, repo_root).read_bytes()
    _validate_inputs(spec, raw, repo_root)
    return replace(spec, inputs_sha256=hashlib.sha256(raw).hexdigest())


def save(spec: PairedSpec, path, *, repo_root: Path = REPO_ROOT) -> None:
    """Write deterministically and enforce the only permitted stage-two field delta."""
    path = Path(path)
    spec._assert_protocol_unchanged()
    if spec.runnable and not path.exists():
        raise ValueError(
            "spec: stage two must update its saved stage-one record; a locked spec "
            "cannot appear at a new path without that history"
        )

    if path.exists():
        previous = load(path, repo_root=repo_root)
        if previous.runnable:
            if previous != spec:
                raise ValueError(
                    f"spec {spec.spec_id!r} is already input-locked and cannot be edited"
                )
        elif spec.runnable:
            changed = {
                name
                for name in previous._body()
                if previous._body()[name] != spec._body()[name]
            }
            if changed != STAGE_TWO_FIELDS:
                raise ValueError(
                    "spec: stage two may change only inputs_sha256; changed "
                    f"{sorted(changed)}"
                )

    if spec.runnable:
        assert_runnable(spec, repo_root=repo_root)

    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(spec.as_record(), sort_keys=True, indent=2, ensure_ascii=False)
    path.write_text(blob + "\n", encoding="utf-8", newline="\n")


def load(path, *, repo_root: Path = REPO_ROOT) -> PairedSpec:
    """Rebuild a spec and verify both its stable protocol identity and composite digest."""
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    stored_protocol = record.pop("stage_one_protocol_hash", None)
    stored_spec = record.pop("spec_hash", None)
    if stored_protocol is None or stored_spec is None:
        raise ValueError("spec: saved records must carry both registered hashes")
    if any(
        not isinstance(digest, str) or OBJECT_HASH.fullmatch(digest) is None
        for digest in (stored_protocol, stored_spec)
    ):
        raise ValueError(
            "spec: registered object hashes must be 0x-prefixed SHA-256 values"
        )

    spec = PairedSpec(**record)
    if not hmac.compare_digest(stored_protocol, spec.stage_one_protocol_hash):
        raise ValueError(
            f"spec {spec.spec_id!r} does not hash to its stage-one protocol digest: the "
            f"file says {stored_protocol} and its protocol fields give "
            f"{spec.stage_one_protocol_hash}"
        )
    if not hmac.compare_digest(stored_spec, spec.spec_hash):
        raise ValueError(
            f"spec {spec.spec_id!r} does not hash to the composite digest it carries: the "
            f"file says {stored_spec} and its contents give {spec.spec_hash}"
        )
    if spec.runnable:
        assert_runnable(spec, repo_root=repo_root)
    return spec
