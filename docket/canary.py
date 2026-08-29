"""Run and durably record the public Range Doctor service canary."""

import base64
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Mapping

import httpx
from eth_account import Account

from .advantage.v3 import report as v3_report
from .hire.catalogue import HIRE_PRICE_ATOMIC, HIRE_PRICE_DISPLAY, USDT_TOKEN
from .hire.receipts import canonical_hash, is_human_readable_result
from .hire.x402 import (
    ASSET_TRANSFER_METHOD,
    B402_FACILITATOR,
    B402_NETWORK,
    B402_RELAYER,
    EIP712_DOMAINS,
    MAX_TIMEOUT_SECONDS,
    NETWORK,
    SCHEME,
    X402_VERSION,
    build_signed_payment,
)
from .store import Store

END_AT = datetime(2026, 9, 24, tzinfo=timezone.utc)
LEG_NAMES = (
    "fresh_browser_surface",
    "snapshot_age_surface",
    "free_verified_example",
    "controlled_live_lp",
    "exact_0_50_settlement",
    "complete_human_result",
    "proof_binding",
    "rejected_replay",
)
_STATUS_PASSED = "passed"
_STATUS_FAILED = "failed"
_STATUS_NOT_YET = "not_yet_exercised"
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")
_SERVICE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_DECISION_STATUSES = {
    "in_range",
    "out_of_range_below",
    "out_of_range_above",
}


@dataclass(frozen=True)
class CanaryOutcome:
    verdict: str
    run_id: int | None
    checks: list[dict]


@dataclass(frozen=True)
class CanaryConfig:
    database: str
    base_url: str
    service_id: str
    end_at: datetime
    wallet: str | None
    token_id: int | None
    position_value_usd: float | None
    recenter_cost_usd: float | None
    lp_error: str | None
    private_key_file: str | None
    token_file: str | None
    facilitator_kind: str | None
    facilitator_url: str | None
    payment_token: str | None
    relayer_contract: str | None
    paid_error: str | None

    @property
    def live_lp_configured(self) -> bool:
        return (
            self.lp_error is None
            and self.wallet is not None
            and self.token_id is not None
            and self.position_value_usd is not None
            and self.recenter_cost_usd is not None
        )

    @property
    def paid_material_configured(self) -> bool:
        return (
            self.paid_error is None
            and self.private_key_file is not None
            and self.token_file is not None
            and self.facilitator_kind is not None
            and self.facilitator_url is not None
            and self.payment_token is not None
            and self.relayer_contract is not None
        )


class _ScriptSources(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []
        self.main_depth = 0
        self.heading_depth = 0
        self.main_text_present = False
        self.main_heading_present = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "script":
            source = dict(attrs).get("src")
            if source:
                self.sources.append(source)
        if tag == "main":
            self.main_depth += 1
        elif self.main_depth and tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.main_depth and tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading_depth = max(0, self.heading_depth - 1)
        elif tag == "main":
            self.main_depth = max(0, self.main_depth - 1)
            if not self.main_depth:
                self.heading_depth = 0

    def handle_data(self, data: str) -> None:
        if not self.main_depth or not data.strip():
            return
        self.main_text_present = True
        if self.heading_depth:
            self.main_heading_present = True


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _text(environment: Mapping[str, str], name: str) -> str | None:
    value = environment.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _finite_number(value: str, *, allow_zero: bool) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError("must be a finite number") from exc
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        boundary = "zero or greater" if allow_zero else "greater than zero"
        raise ValueError(f"must be finite and {boundary}")
    return number


def _configuration(environment: Mapping[str, str]) -> CanaryConfig:
    database = _text(environment, "DOCKET_DB")
    base_url = _text(environment, "DOCKET_CANARY_BASE_URL")
    if database is None:
        raise ValueError("DOCKET_DB is required")
    if base_url is None:
        raise ValueError("DOCKET_CANARY_BASE_URL is required")

    url = httpx.URL(base_url)
    if url.scheme != "https" or not url.host or url.userinfo:
        raise ValueError("DOCKET_CANARY_BASE_URL must be a public HTTPS origin")
    if url.path not in ("", "/") or url.query or url.fragment:
        raise ValueError(
            "DOCKET_CANARY_BASE_URL must not include a path, query, or fragment"
        )
    base_url = str(url).rstrip("/")

    end_value = _text(environment, "DOCKET_CANARY_END_AT")
    end_at = END_AT if end_value is None else _parse_timestamp(end_value)
    if end_at != END_AT:
        raise ValueError("DOCKET_CANARY_END_AT must be 2026-09-24T00:00:00Z")
    service_id = _text(environment, "DOCKET_CANARY_SERVICE_ID") or "range-doctor"
    if _SERVICE_ID.fullmatch(service_id) is None:
        raise ValueError("DOCKET_CANARY_SERVICE_ID must be a lowercase service slug")

    lp_names = {
        "wallet": "DOCKET_CANARY_WALLET",
        "token_id": "DOCKET_CANARY_TOKEN_ID",
        "position_value": "DOCKET_CANARY_POSITION_VALUE_USD",
        "recenter_cost": "DOCKET_CANARY_RECENTER_COST_USD",
    }
    lp_values = {name: _text(environment, key) for name, key in lp_names.items()}
    wallet = None
    token_id = None
    position_value = None
    recenter_cost = None
    lp_error = None
    if any(value is not None for value in lp_values.values()):
        missing = [name for name, value in lp_values.items() if value is None]
        if missing:
            lp_error = f"controlled LP configuration is missing {', '.join(missing)}"
        else:
            try:
                wallet = str(lp_values["wallet"])
                if _ADDRESS.fullmatch(wallet) is None:
                    raise ValueError("wallet must be a 20-byte 0x address")
                try:
                    token_id = int(str(lp_values["token_id"]))
                except ValueError as exc:
                    raise ValueError("token_id must be a positive integer") from exc
                if token_id <= 0:
                    raise ValueError("token_id must be positive")
                position_value = _finite_number(
                    str(lp_values["position_value"]), allow_zero=False
                )
                recenter_cost = _finite_number(
                    str(lp_values["recenter_cost"]), allow_zero=True
                )
            except ValueError as exc:
                lp_error = str(exc)

    private_key_file = _text(environment, "DOCKET_CANARY_PRIVATE_KEY_FILE")
    token_file = _text(environment, "DOCKET_CANARY_TOKEN_FILE")
    facilitator_kind = _text(environment, "DOCKET_FACILITATOR_KIND")
    facilitator_url = _text(environment, "DOCKET_FACILITATOR_URL")
    payment_token = _text(environment, "DOCKET_PAYMENT_TOKEN")
    relayer_contract = _text(environment, "DOCKET_B402_RELAYER_CONTRACT")
    paid_error = None
    if private_key_file is not None:
        if token_file is None:
            paid_error = "a payment key requires the private canary token file"
        else:
            public_settings = {
                "DOCKET_FACILITATOR_KIND": facilitator_kind,
                "DOCKET_FACILITATOR_URL": facilitator_url,
                "DOCKET_PAYMENT_TOKEN": payment_token,
                "DOCKET_B402_RELAYER_CONTRACT": relayer_contract,
            }
            missing = [name for name, value in public_settings.items() if value is None]
            if missing:
                paid_error = f"a payment key requires {', '.join(missing)}"
            elif facilitator_kind != B402_FACILITATOR:
                paid_error = f"DOCKET_FACILITATOR_KIND must be {B402_FACILITATOR}"
            elif str(payment_token).lower() != USDT_TOKEN.lower():
                paid_error = f"DOCKET_PAYMENT_TOKEN must be {USDT_TOKEN}"
            elif str(relayer_contract).lower() != B402_RELAYER.lower():
                paid_error = f"DOCKET_B402_RELAYER_CONTRACT must be {B402_RELAYER}"
            else:
                payment_token = USDT_TOKEN
                relayer_contract = B402_RELAYER
                try:
                    parsed_facilitator = httpx.URL(str(facilitator_url))
                except httpx.InvalidURL:
                    parsed_facilitator = None
                if (
                    parsed_facilitator is None
                    or parsed_facilitator.scheme != "https"
                    or not parsed_facilitator.host
                    or parsed_facilitator.userinfo
                    or parsed_facilitator.query
                    or parsed_facilitator.fragment
                ):
                    paid_error = "DOCKET_FACILITATOR_URL must be an HTTPS endpoint without credentials, query, or fragment"

    return CanaryConfig(
        database=database,
        base_url=base_url,
        service_id=service_id,
        end_at=end_at,
        wallet=wallet,
        token_id=token_id,
        position_value_usd=position_value,
        recenter_cost_usd=recenter_cost,
        lp_error=lp_error,
        private_key_file=private_key_file,
        token_file=token_file,
        facilitator_kind=facilitator_kind,
        facilitator_url=facilitator_url,
        payment_token=payment_token,
        relayer_contract=relayer_contract,
        paid_error=paid_error,
    )


def _check(
    leg: str,
    status: str,
    *,
    checked: list[str],
    observed: dict,
    evidence: dict,
) -> dict:
    return {
        "leg": leg,
        "checked": checked,
        "status": status,
        "observed": observed,
        "evidence": evidence,
    }


def _response_error(response: httpx.Response) -> dict:
    evidence = {
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type", "").split(";", 1)[0],
    }
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        code = body["error"].get("code")
        if isinstance(code, str) and code:
            evidence["error_code"] = code
    return evidence


def _transport_error(exc: httpx.HTTPError) -> dict:
    return {"error_type": type(exc).__name__}


def _sha256(content: bytes) -> str:
    return "0x" + hashlib.sha256(content).hexdigest()


def _safe_scalar(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def _same_origin(left: httpx.URL, right: httpx.URL) -> bool:
    return (
        left.scheme.lower(),
        left.host.lower() if left.host else None,
        left.port,
    ) == (
        right.scheme.lower(),
        right.host.lower() if right.host else None,
        right.port,
    )


def _fresh_browser_check(client: httpx.Client, base_url: str) -> dict:
    checked = [
        "a new HTTP client started without cookies",
        "the public root returned HTML over HTTPS",
        "every script referenced by that HTML was fetched from the same origin",
    ]
    observed = {
        "new_session": True,
        "initial_cookie_count": len(client.cookies),
        "javascript_rendered": False,
    }
    evidence = {
        "base_url": base_url,
        "outside_vantage_claimed": False,
    }
    try:
        response = client.get("/", headers={"accept": "text/html"})
    except httpx.HTTPError as exc:
        evidence.update(_transport_error(exc))
        return _check(
            LEG_NAMES[0],
            _STATUS_FAILED,
            checked=checked,
            observed=observed,
            evidence=evidence,
        )
    evidence.update(
        {
            "html_status_code": response.status_code,
            "html_content_type": response.headers.get("content-type", "").split(";", 1)[
                0
            ],
            "html_sha256": _sha256(response.content),
            "html_url": str(response.url),
        }
    )
    if (
        response.status_code != 200
        or "text/html" not in response.headers.get("content-type", "").lower()
    ):
        return _check(
            LEG_NAMES[0],
            _STATUS_FAILED,
            checked=checked,
            observed=observed,
            evidence=evidence,
        )

    parser = _ScriptSources()
    parser.feed(response.text)
    observed["referenced_script_count"] = len(parser.sources)
    if not parser.sources:
        evidence["delivery_mode"] = "server_rendered_html"
        observed["fetched_script_count"] = 0
        observed["main_text_present"] = parser.main_text_present
        observed["main_heading_present"] = parser.main_heading_present
        if not parser.main_text_present or not parser.main_heading_present:
            evidence["failure"] = "server_rendered_surface_incomplete"
            return _check(
                LEG_NAMES[0],
                _STATUS_FAILED,
                checked=checked,
                observed=observed,
                evidence=evidence,
            )
        return _check(
            LEG_NAMES[0],
            _STATUS_PASSED,
            checked=checked,
            observed=observed,
            evidence=evidence,
        )

    script_evidence = []
    for source in parser.sources:
        script_url = response.url.join(source)
        if not _same_origin(response.url, script_url):
            script_evidence.append({"url": str(script_url), "same_origin": False})
            evidence["scripts"] = script_evidence
            return _check(
                LEG_NAMES[0],
                _STATUS_FAILED,
                checked=checked,
                observed=observed,
                evidence=evidence,
            )
        try:
            script = client.get(script_url, headers={"accept": "text/javascript"})
        except httpx.HTTPError as exc:
            script_evidence.append(
                {
                    "url": str(script_url),
                    "same_origin": True,
                    **_transport_error(exc),
                }
            )
            evidence["scripts"] = script_evidence
            return _check(
                LEG_NAMES[0],
                _STATUS_FAILED,
                checked=checked,
                observed=observed,
                evidence=evidence,
            )
        content_type = script.headers.get("content-type", "").split(";", 1)[0]
        script_evidence.append(
            {
                "url": str(script.url),
                "same_origin": True,
                "status_code": script.status_code,
                "content_type": content_type,
                "sha256": _sha256(script.content),
            }
        )
        if (
            script.status_code != 200
            or "javascript" not in content_type.lower()
            or not script.content
        ):
            evidence["scripts"] = script_evidence
            return _check(
                LEG_NAMES[0],
                _STATUS_FAILED,
                checked=checked,
                observed=observed,
                evidence=evidence,
            )
    evidence["scripts"] = script_evidence
    observed["fetched_script_count"] = len(script_evidence)
    return _check(
        LEG_NAMES[0],
        _STATUS_PASSED,
        checked=checked,
        observed=observed,
        evidence=evidence,
    )


def _snapshot_age_check(client: httpx.Client, base_url: str) -> dict:
    checked = [
        "GET /stats described the snapshot bound to the serving process",
        "coverage.snapshot_age_seconds was a surfaced nonnegative integer",
    ]
    observed = {}
    evidence = {"url": f"{base_url}/stats"}
    try:
        response = client.get("/stats", headers={"accept": "application/json"})
    except httpx.HTTPError as exc:
        evidence.update(_transport_error(exc))
        return _check(
            LEG_NAMES[1],
            _STATUS_FAILED,
            checked=checked,
            observed=observed,
            evidence=evidence,
        )
    if response.status_code != 200:
        evidence.update(_response_error(response))
        return _check(
            LEG_NAMES[1],
            _STATUS_FAILED,
            checked=checked,
            observed=observed,
            evidence=evidence,
        )
    try:
        body = response.json()
    except ValueError:
        body = None
    coverage = body.get("coverage") if isinstance(body, dict) else None
    if not isinstance(coverage, dict):
        evidence["failure"] = "coverage_not_present"
        return _check(
            LEG_NAMES[1],
            _STATUS_FAILED,
            checked=checked,
            observed=observed,
            evidence=evidence,
        )
    age = coverage.get("snapshot_age_seconds")
    observed.update(
        {
            "snapshot_id": _safe_scalar(coverage.get("snapshot_id")),
            "captured_at": _safe_scalar(coverage.get("captured_at")),
            "snapshot_age_seconds": _safe_scalar(age),
        }
    )
    if not isinstance(age, int) or isinstance(age, bool) or age < 0:
        evidence["failure"] = "snapshot_age_not_nonnegative_integer"
        return _check(
            LEG_NAMES[1],
            _STATUS_FAILED,
            checked=checked,
            observed=observed,
            evidence=evidence,
        )
    evidence["status_code"] = response.status_code
    return _check(
        LEG_NAMES[1],
        _STATUS_PASSED,
        checked=checked,
        observed=observed,
        evidence=evidence,
    )


def _verified_example_check(client: httpx.Client, base_url: str) -> dict:
    checked = [
        "GET /advantage/v2.json returned the v2 public corpus",
        "the corpus included a summary and at least one spec/run/falsifier record",
    ]
    observed = {}
    evidence = {"url": f"{base_url}/advantage/v2.json"}
    try:
        response = client.get(
            "/advantage/v2.json", headers={"accept": "application/json"}
        )
    except httpx.HTTPError as exc:
        evidence.update(_transport_error(exc))
        return _check(
            LEG_NAMES[2],
            _STATUS_FAILED,
            checked=checked,
            observed=observed,
            evidence=evidence,
        )
    if response.status_code != 200:
        evidence.update(_response_error(response))
        return _check(
            LEG_NAMES[2],
            _STATUS_FAILED,
            checked=checked,
            observed=observed,
            evidence=evidence,
        )
    try:
        body = response.json()
    except ValueError:
        body = None
    experiments = body.get("experiments") if isinstance(body, dict) else None
    valid_experiments = (
        isinstance(experiments, list)
        and bool(experiments)
        and all(
            isinstance(experiment, dict)
            and all(
                isinstance(experiment.get(field), dict)
                for field in ("spec", "run", "falsifier_result")
            )
            for experiment in experiments
        )
    )
    valid = (
        isinstance(body, dict)
        and body.get("version") == "v2"
        and isinstance(body.get("summary"), dict)
        and valid_experiments
    )
    observed.update(
        {
            "version": _safe_scalar(body.get("version"))
            if isinstance(body, dict)
            else None,
            "experiment_count": len(experiments)
            if isinstance(experiments, list)
            else 0,
        }
    )
    evidence["status_code"] = response.status_code
    if not valid:
        evidence["failure"] = "v2_corpus_shape_incomplete"
    return _check(
        LEG_NAMES[2],
        _STATUS_PASSED if valid else _STATUS_FAILED,
        checked=checked,
        observed=observed,
        evidence=evidence,
    )


def _is_number(value: object, *, allow_zero: bool = True) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and (float(value) >= 0 if allow_zero else float(value) > 0)
    )


def _decision_grade(result: object, payload: dict) -> tuple[list[str], dict]:
    failures = []
    observed = {
        "target_found": False,
        "qualifying_position_count": 0,
        "decision_present": False,
        "measured_value_present": False,
    }
    if not isinstance(result, dict):
        return ["result_not_object"], observed

    if result.get("target_found") is not True:
        failures.append("target_not_found")
    observed["target_found"] = result.get("target_found") is True
    if result.get("target_token_id") != payload["token_id"]:
        failures.append("target_token_id_mismatch")
    decision = result.get("decision")
    if not isinstance(decision, str) or not decision.strip():
        failures.append("decision_missing")
    else:
        observed["decision_present"] = True
    coverage = result.get("coverage")
    if not isinstance(coverage, str) or not coverage.strip():
        failures.append("coverage_missing")
    limitation = result.get("primary_limitation")
    if not isinstance(limitation, str) or not limitation.strip():
        failures.append("primary_limitation_missing")
    if result.get("positions_examined") != 1:
        failures.append("positions_examined_not_one")

    positions = result.get("positions")
    if not isinstance(positions, list) or len(positions) != 1:
        failures.append("qualifying_position_count_not_one")
        return failures, observed
    position = positions[0]
    diagnosis = position.get("diagnosis") if isinstance(position, dict) else None
    if not isinstance(diagnosis, dict):
        failures.append("diagnosis_missing")
        return failures, observed
    status = diagnosis.get("status")
    if status not in _DECISION_STATUSES:
        failures.append("position_closed_or_unknown")
    else:
        observed["qualifying_position_count"] = 1
        observed["position_status"] = status
    position_decision = diagnosis.get("decision")
    if not isinstance(position_decision, str) or not position_decision.strip():
        failures.append("position_decision_missing")

    facts = diagnosis.get("verifiable_facts")
    if not isinstance(facts, dict):
        failures.append("verifiable_facts_missing")
    else:
        if facts.get("position_id") != payload["token_id"]:
            failures.append("fact_position_id_mismatch")
        for field in ("current_tick", "lower_tick", "upper_tick"):
            if not isinstance(facts.get(field), int) or isinstance(
                facts.get(field), bool
            ):
                failures.append(f"{field}_missing")
        block = facts.get("bsc_block")
        if not isinstance(block, int) or isinstance(block, bool) or block <= 0:
            failures.append("bsc_block_missing")
        observed_at = facts.get("observation_time")
        try:
            _parse_timestamp(observed_at)
        except (AttributeError, TypeError, ValueError):
            failures.append("observation_time_missing")
        observed.update(
            {
                "position_id": _safe_scalar(facts.get("position_id")),
                "current_tick": _safe_scalar(facts.get("current_tick")),
                "lower_tick": _safe_scalar(facts.get("lower_tick")),
                "upper_tick": _safe_scalar(facts.get("upper_tick")),
                "bsc_block": _safe_scalar(block),
                "observation_time": _safe_scalar(observed_at),
            }
        )

    economics = diagnosis.get("economic_consequence")
    if not isinstance(economics, dict):
        failures.append("economic_consequence_missing")
    else:
        if economics.get("unavailable_reason") is not None:
            failures.append("economic_consequence_unavailable")
        if (
            economics.get("declared_position_value_usd")
            != payload["declared_position_value_usd"]
        ):
            failures.append("position_value_mismatch")
        for field in (
            "gross_apr",
            "net_apr",
            "annual_gross_usd",
            "annual_net_usd",
            "annual_overstatement_usd",
            "pool_rate_at_declared_value_usd",
        ):
            if not _is_number(economics.get(field)):
                failures.append(f"{field}_missing")

    conditional = diagnosis.get("conditional_actions")
    if not isinstance(conditional, dict):
        failures.append("conditional_actions_missing")
    else:
        actions = conditional.get("actions")
        if (
            not isinstance(actions, list)
            or not actions
            or not all(
                isinstance(action, dict)
                and isinstance(action.get("kind"), str)
                and bool(action["kind"].strip())
                and isinstance(action.get("text"), str)
                and bool(action["text"].strip())
                for action in actions or []
            )
        ):
            failures.append("conditional_actions_incomplete")
        if (
            conditional.get("estimated_recenter_cost_usd")
            != payload["estimated_recenter_cost_usd"]
        ):
            failures.append("recenter_cost_mismatch")
        if conditional.get("unavailable_reason") is not None:
            failures.append("conditional_actions_unavailable")

    measured = result.get("measured_value")
    if not isinstance(measured, dict):
        failures.append("measured_value_missing")
    else:
        benchmark_available = (
            _is_number(measured.get("paired_manual_seconds"))
            and isinstance(measured.get("quality_result"), dict)
            and bool(measured["quality_result"])
            and isinstance(measured.get("report_url"), str)
            and bool(measured["report_url"].strip())
            and measured.get("benchmark_unavailable_reason") is None
        )
        benchmark_state = measured.get("benchmark_state")
        unavailable_reason = measured.get("benchmark_unavailable_reason")
        benchmark_explicitly_unavailable = (
            measured.get("paired_manual_seconds") is None
            and measured.get("quality_result") is None
            and measured.get("report_url") is None
            and benchmark_state in v3_report.STATES
            and isinstance(unavailable_reason, str)
            and bool(unavailable_reason.strip())
        )
        measured_ok = _is_number(measured.get("this_run_seconds")) and (
            benchmark_available or benchmark_explicitly_unavailable
        )
        if not measured_ok:
            failures.append("measured_value_incomplete")
        observed["measured_value_present"] = measured_ok
        observed["paired_benchmark_available"] = benchmark_available
    return failures, observed


def _controlled_lp_check(
    client: httpx.Client, config: CanaryConfig
) -> tuple[dict, dict | None, dict | None]:
    checked = [
        "the configured wallet and exact position were read through the free path",
        "exactly one active known position returned a human decision and on-chain facts",
        "economics, conditional actions, coverage, limitation, and measured value were present",
    ]
    if config.lp_error is not None:
        return (
            _check(
                LEG_NAMES[3],
                _STATUS_FAILED,
                checked=checked,
                observed={"configured": False},
                evidence={"configuration_error": config.lp_error},
            ),
            None,
            None,
        )
    if not config.live_lp_configured:
        return (
            _check(
                LEG_NAMES[3],
                _STATUS_NOT_YET,
                checked=checked,
                observed={"configured": False},
                evidence={"reason": "controlled_live_lp_absent"},
            ),
            None,
            None,
        )

    payload = {
        "wallet": config.wallet,
        "token_id": config.token_id,
        "declared_position_value_usd": config.position_value_usd,
        "estimated_recenter_cost_usd": config.recenter_cost_usd,
    }
    evidence = {"url": f"{config.base_url}/hire/{config.service_id}", "paid": False}
    try:
        response = client.post(f"/hire/{config.service_id}", json=payload)
    except httpx.HTTPError as exc:
        evidence.update(_transport_error(exc))
        return (
            _check(
                LEG_NAMES[3],
                _STATUS_FAILED,
                checked=checked,
                observed={"configured": True},
                evidence=evidence,
            ),
            payload,
            None,
        )
    if response.status_code != 200:
        evidence.update(_response_error(response))
        return (
            _check(
                LEG_NAMES[3],
                _STATUS_FAILED,
                checked=checked,
                observed={"configured": True},
                evidence=evidence,
            ),
            payload,
            None,
        )
    try:
        body = response.json()
    except ValueError:
        body = None
    result = body.get("result") if isinstance(body, dict) else None
    failures, observed = _decision_grade(result, payload)
    observed.update(
        {
            "configured": True,
            "wallet": config.wallet,
            "token_id": config.token_id,
            "declared_position_value_usd": config.position_value_usd,
            "estimated_recenter_cost_usd": config.recenter_cost_usd,
        }
    )
    evidence["status_code"] = response.status_code
    if failures:
        evidence["failed_requirements"] = failures
    return (
        _check(
            LEG_NAMES[3],
            _STATUS_FAILED if failures else _STATUS_PASSED,
            checked=checked,
            observed=observed,
            evidence=evidence,
        ),
        payload,
        result if isinstance(result, dict) else None,
    )


def _not_yet_paid_checks(reason: str) -> list[dict]:
    descriptions = (
        f"an exact {HIRE_PRICE_DISPLAY} authorization settled",
        "the paid response contained a complete human result",
        "the receipt bound payment, input, and output evidence",
        "the identical settled request was rejected as a replay",
    )
    return [
        _check(
            leg,
            _STATUS_NOT_YET,
            checked=[description],
            observed={"exercised": False},
            evidence={"reason": reason},
        )
        for leg, description in zip(LEG_NAMES[4:], descriptions, strict=True)
    ]


def _paid_material(config: CanaryConfig) -> tuple[object, str]:
    if config.private_key_file is None or config.token_file is None:
        raise ValueError("paid canary material is absent")
    private_key = Path(config.private_key_file).read_text(encoding="utf-8").strip()
    token = Path(config.token_file).read_text(encoding="utf-8").strip()
    if not private_key or not token:
        raise ValueError("paid canary files must be nonempty")
    return Account.from_key(private_key), token


def _challenge_offer(
    body: object, expected_url: str, config: CanaryConfig
) -> tuple[dict | None, dict]:
    observed = {"exact_offer_present": False}
    if not isinstance(body, dict):
        return None, observed
    resource = body.get("resource")
    offers = body.get("accepts")
    error = body.get("error")
    if (
        body.get("x402Version") != X402_VERSION
        or not isinstance(resource, dict)
        or resource.get("url") != expected_url
        or not isinstance(error, dict)
        or error.get("code") != "payment_invalid"
        or not isinstance(offers, list)
        or len(offers) != 1
        or not isinstance(offers[0], dict)
    ):
        return None, observed
    offer = offers[0]
    extra = offer.get("extra")
    domain = EIP712_DOMAINS.get(str(config.payment_token).lower())
    expected_extra = (
        {
            "assetTransferMethod": ASSET_TRANSFER_METHOD,
            **domain,
            "relayerContract": config.relayer_contract,
        }
        if domain is not None
        else None
    )
    valid = (
        offer.get("scheme") == SCHEME
        and offer.get("network") == NETWORK
        and offer.get("amount") == str(HIRE_PRICE_ATOMIC)
        and str(offer.get("asset", "")).lower() == str(config.payment_token).lower()
        and isinstance(offer.get("payTo"), str)
        and _ADDRESS.fullmatch(offer["payTo"]) is not None
        and offer.get("maxTimeoutSeconds") == MAX_TIMEOUT_SECONDS
        and extra == expected_extra
    )
    observed.update(
        {
            "exact_offer_present": valid,
            "amount_atomic": _safe_scalar(offer.get("amount")),
            "asset": _safe_scalar(offer.get("asset")),
            "recipient": _safe_scalar(offer.get("payTo")),
            "network": _safe_scalar(offer.get("network")),
            "relayer_contract": _safe_scalar(extra.get("relayerContract"))
            if isinstance(extra, dict)
            else None,
            "verifying_contract": _safe_scalar(extra.get("verifyingContract"))
            if isinstance(extra, dict)
            else None,
        }
    )
    return (offer if valid else None), observed


def _encoded_payment(envelope: dict) -> str:
    raw = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _settlement_check(
    receipt: object, account: object, offer: dict, authorization: dict
) -> tuple[dict, bool]:
    checked = [
        "the paid request returned a settled payment",
        f"the settlement named exactly {HIRE_PRICE_ATOMIC} atomic units of USDT and the challenged recipient",
    ]
    payment = receipt.get("payment") if isinstance(receipt, dict) else None
    valid = isinstance(payment, dict) and (
        payment.get("status") == "settled"
        and payment.get("amount") == str(HIRE_PRICE_ATOMIC)
        and str(payment.get("asset", "")).lower() == USDT_TOKEN.lower()
        and str(payment.get("recipient", "")).lower() == offer["payTo"].lower()
        and str(payment.get("payer", "")).lower() == account.address.lower()
        and payment.get("nonce") == authorization["nonce"].lower()
    )
    observed = {
        "exercised": True,
        "settled": bool(
            isinstance(payment, dict) and payment.get("status") == "settled"
        ),
        "amount_atomic": _safe_scalar(payment.get("amount"))
        if isinstance(payment, dict)
        else None,
        "asset": _safe_scalar(payment.get("asset"))
        if isinstance(payment, dict)
        else None,
        "recipient": _safe_scalar(payment.get("recipient"))
        if isinstance(payment, dict)
        else None,
    }
    evidence = {
        "payment_id": _safe_scalar(payment.get("payment_id"))
        if isinstance(payment, dict)
        else None,
        "transaction_id": _safe_scalar(payment.get("transaction_id"))
        if isinstance(payment, dict)
        else None,
        "network": _safe_scalar(payment.get("network"))
        if isinstance(payment, dict)
        else None,
    }
    return (
        _check(
            LEG_NAMES[4],
            _STATUS_PASSED if valid else _STATUS_FAILED,
            checked=checked,
            observed=observed,
            evidence=evidence,
        ),
        valid,
    )


def _complete_result_check(result: object, payload: dict) -> tuple[dict, bool]:
    failures, observed = _decision_grade(result, payload)
    readable = is_human_readable_result(result)
    if not readable:
        failures.append("human_readable_result_missing")
    observed.update({"exercised": True, "human_readable": readable})
    valid = not failures
    return (
        _check(
            LEG_NAMES[5],
            _STATUS_PASSED if valid else _STATUS_FAILED,
            checked=[
                "the paid output was human-readable",
                "the paid output independently met every decision-grade preflight requirement",
            ],
            observed=observed,
            evidence={"failed_requirements": failures},
        ),
        valid,
    )


def _proof_check(
    receipt: object,
    result: object,
    payload: dict,
    authorization: dict,
    service_id: str,
) -> tuple[dict, bool]:
    checked = [
        "the receipt service and canonical input/output hashes matched this request and result",
        "delivery time and settled payment id, nonce, transaction, and network were present",
    ]
    failures = []
    if not isinstance(receipt, dict):
        failures.append("receipt_missing")
        receipt = {}
    payment = receipt.get("payment")
    if not isinstance(payment, dict):
        failures.append("payment_proof_missing")
        payment = {}
    expected_input = canonical_hash(payload)
    expected_output = canonical_hash(result)
    if receipt.get("service") != service_id:
        failures.append("service_mismatch")
    if receipt.get("input_hash") != expected_input:
        failures.append("input_hash_mismatch")
    if receipt.get("output_hash") != expected_output:
        failures.append("output_hash_mismatch")
    delivered_at = receipt.get("delivered_at")
    try:
        _parse_timestamp(delivered_at)
    except (AttributeError, TypeError, ValueError):
        failures.append("delivery_time_missing")
    if not isinstance(payment.get("payment_id"), str) or not payment["payment_id"]:
        failures.append("payment_id_missing")
    if payment.get("nonce") != authorization["nonce"].lower():
        failures.append("nonce_mismatch")
    if (
        not isinstance(payment.get("transaction_id"), str)
        or not payment["transaction_id"]
    ):
        failures.append("transaction_id_missing")
    if payment.get("network") != B402_NETWORK:
        failures.append("network_mismatch")
    valid = not failures
    return (
        _check(
            LEG_NAMES[6],
            _STATUS_PASSED if valid else _STATUS_FAILED,
            checked=checked,
            observed={
                "exercised": True,
                "service": _safe_scalar(receipt.get("service")),
                "delivered_at": _safe_scalar(delivered_at),
                "input_hash_matches": receipt.get("input_hash") == expected_input,
                "output_hash_matches": receipt.get("output_hash") == expected_output,
            },
            evidence={
                "payment_id": _safe_scalar(payment.get("payment_id")),
                "transaction_id": _safe_scalar(payment.get("transaction_id")),
                "network": _safe_scalar(payment.get("network")),
                "failed_requirements": failures,
            },
        ),
        valid,
    )


def _paid_checks(
    client: httpx.Client,
    config: CanaryConfig,
    payload: dict,
    now: datetime,
) -> list[dict]:
    if config.paid_error is not None:
        checks = _not_yet_paid_checks("paid_canary_configuration_invalid")
        checks[0] = _check(
            LEG_NAMES[4],
            _STATUS_FAILED,
            checked=["both owner-controlled canary files were configured together"],
            observed={"exercised": False},
            evidence={"configuration_error": config.paid_error},
        )
        return checks
    if not config.paid_material_configured:
        return _not_yet_paid_checks("owner_payment_material_absent")
    try:
        account, token = _paid_material(config)
    except (OSError, ValueError) as exc:
        checks = _not_yet_paid_checks("paid_canary_material_unusable")
        checks[0] = _check(
            LEG_NAMES[4],
            _STATUS_FAILED,
            checked=["owner-controlled canary files were readable and valid"],
            observed={"exercised": False},
            evidence={"error_type": type(exc).__name__},
        )
        return checks

    route = f"/hire/{config.service_id}"
    expected_url = f"{config.base_url}{route}"
    try:
        challenge_response = client.post(
            route,
            json=payload,
            headers={"X-PAYMENT": "invalid", "X-Docket-Canary": token},
        )
    except httpx.HTTPError as exc:
        checks = _not_yet_paid_checks("exact_challenge_unavailable")
        checks[0] = _check(
            LEG_NAMES[4],
            _STATUS_FAILED,
            checked=["an invalid payment obtained the exact private canary challenge"],
            observed={"exercised": True},
            evidence=_transport_error(exc),
        )
        return checks
    try:
        challenge = challenge_response.json()
    except ValueError:
        challenge = None
    offer, challenge_observed = _challenge_offer(challenge, expected_url, config)
    if challenge_response.status_code != 402 or offer is None:
        checks = _not_yet_paid_checks("exact_challenge_invalid")
        checks[0] = _check(
            LEG_NAMES[4],
            _STATUS_FAILED,
            checked=["an invalid payment obtained the exact private canary challenge"],
            observed={"exercised": True, **challenge_observed},
            evidence=_response_error(challenge_response),
        )
        return checks

    envelope = build_signed_payment(
        account,
        offer,
        challenge["resource"],
        now=int(now.timestamp()),
    )
    payment_header = _encoded_payment(envelope)
    headers = {"X-PAYMENT": payment_header, "X-Docket-Canary": token}
    try:
        response = client.post(route, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        checks = _not_yet_paid_checks("settled_request_unavailable")
        checks[0] = _check(
            LEG_NAMES[4],
            _STATUS_FAILED,
            checked=["one freshly signed exact authorization was submitted once"],
            observed={"exercised": True, **challenge_observed},
            evidence=_transport_error(exc),
        )
        return checks
    if response.status_code != 200:
        checks = _not_yet_paid_checks("settled_result_not_returned")
        checks[0] = _check(
            LEG_NAMES[4],
            _STATUS_FAILED,
            checked=["one freshly signed exact authorization was submitted once"],
            observed={"exercised": True, **challenge_observed},
            evidence=_response_error(response),
        )
        return checks
    try:
        body = response.json()
    except ValueError:
        body = None
    result = body.get("result") if isinstance(body, dict) else None
    receipt = body.get("receipt") if isinstance(body, dict) else None
    authorization = envelope["payload"]["authorization"]
    settlement, settlement_valid = _settlement_check(
        receipt, account, offer, authorization
    )
    complete, complete_valid = _complete_result_check(result, payload)
    proof, proof_valid = _proof_check(
        receipt, result, payload, authorization, config.service_id
    )
    if not (settlement_valid and complete_valid and proof_valid):
        replay = _not_yet_paid_checks("paid_result_or_proof_failed")[-1]
        return [settlement, complete, proof, replay]

    try:
        replay_response = client.post(route, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        replay = _check(
            LEG_NAMES[7],
            _STATUS_FAILED,
            checked=["the identical settled signed request was rejected as a replay"],
            observed={"exercised": True},
            evidence=_transport_error(exc),
        )
        return [settlement, complete, proof, replay]
    replay_error = _response_error(replay_response)
    replay_valid = (
        replay_response.status_code == 409
        and replay_error.get("error_code") == "authorization_replay"
    )
    replay = _check(
        LEG_NAMES[7],
        _STATUS_PASSED if replay_valid else _STATUS_FAILED,
        checked=["the identical settled signed request was rejected as a replay"],
        observed={"exercised": True, "identical_request_rejected": replay_valid},
        evidence=replay_error,
    )
    return [settlement, complete, proof, replay]


def _verdict(checks: list[dict]) -> str:
    if any(check["status"] == _STATUS_FAILED for check in checks):
        return _STATUS_FAILED
    if all(check["status"] == _STATUS_PASSED for check in checks):
        return _STATUS_PASSED
    return _STATUS_NOT_YET


def _finish_runner_failure(
    history: Store,
    run_id: int,
    checks: list[dict],
    exc: Exception,
) -> CanaryOutcome:
    if len(checks) < len(LEG_NAMES):
        failed_leg = LEG_NAMES[len(checks)]
        checks.append(
            _check(
                failed_leg,
                _STATUS_FAILED,
                checked=[
                    "the canary runner completed this leg without an internal error"
                ],
                observed={"completed": False},
                evidence={"error_type": type(exc).__name__},
            )
        )
    while len(checks) < len(LEG_NAMES):
        checks.append(
            _check(
                LEG_NAMES[len(checks)],
                _STATUS_NOT_YET,
                checked=["the canary runner reached this leg"],
                observed={"exercised": False},
                evidence={"reason": "runner_terminated_before_leg"},
            )
        )
    history.finish_canary_run(
        run_id,
        verdict=_STATUS_FAILED,
        checks=checks,
        finished_at=_utc_now().isoformat(),
    )
    return CanaryOutcome(_STATUS_FAILED, run_id, checks)


def _record_configuration_failure(
    environment: Mapping[str, str], checked_at: datetime, exc: Exception
) -> CanaryOutcome:
    database = _text(environment, "DOCKET_DB")
    if database is None:
        raise exc
    service_id = _text(environment, "DOCKET_CANARY_SERVICE_ID") or "range-doctor"
    if _SERVICE_ID.fullmatch(service_id) is None:
        service_id = "range-doctor"
    raw_target = _text(environment, "DOCKET_CANARY_BASE_URL")
    target_url = "configuration-invalid"
    if raw_target is not None:
        try:
            candidate = httpx.URL(raw_target)
        except httpx.InvalidURL:
            candidate = None
        if (
            candidate is not None
            and candidate.scheme == "https"
            and candidate.host
            and not candidate.userinfo
        ):
            target_url = str(candidate)

    history = Store(database)
    run_id = history.begin_canary_run(
        service_id, target_url, started_at=checked_at.isoformat()
    )
    checks = [
        _check(
            LEG_NAMES[0],
            _STATUS_FAILED,
            checked=["configuration permitted a fresh public HTTPS session"],
            observed={"exercised": False},
            evidence={
                "reason": "configuration_invalid",
                "error_type": type(exc).__name__,
            },
        )
    ]
    for leg in LEG_NAMES[1:]:
        checks.append(
            _check(
                leg,
                _STATUS_NOT_YET,
                checked=["valid configuration allowed the runner to reach this leg"],
                observed={"exercised": False},
                evidence={"reason": "configuration_invalid"},
            )
        )
    history.finish_canary_run(
        run_id,
        verdict=_STATUS_FAILED,
        checks=checks,
        finished_at=_utc_now().isoformat(),
    )
    return CanaryOutcome(_STATUS_FAILED, run_id, checks)


def run_from_environment(
    environment: Mapping[str, str] | None = None,
    *,
    now: datetime | None = None,
    transport: httpx.BaseTransport | None = None,
    store: Store | None = None,
) -> CanaryOutcome:
    environment = os.environ if environment is None else environment
    checked_at = _utc_now() if now is None else now.astimezone(timezone.utc)
    # The eligibility boundary is fixed, so no malformed or extended environment value
    # can make the runner touch history or the network after the judging window.
    if checked_at >= END_AT:
        return CanaryOutcome("window_ended", None, [])

    try:
        config = _configuration(environment)
    except Exception as exc:
        return _record_configuration_failure(environment, checked_at, exc)
    history = Store(config.database) if store is None else store
    run_id = history.begin_canary_run(
        config.service_id, config.base_url, started_at=checked_at.isoformat()
    )
    checks = []
    try:
        # One new client makes the browser-surface claim bounded to this run and avoids
        # inheriting cookies, proxy credentials, or authorization from another process.
        with httpx.Client(
            base_url=config.base_url,
            transport=transport,
            timeout=45.0,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "Docket service canary/1"},
        ) as client:
            checks.extend(
                (
                    _fresh_browser_check(client, config.base_url),
                    _snapshot_age_check(client, config.base_url),
                    _verified_example_check(client, config.base_url),
                )
            )
            controlled, payload, _ = _controlled_lp_check(client, config)
            checks.append(controlled)
            if controlled["status"] == _STATUS_PASSED and payload is not None:
                checks.extend(_paid_checks(client, config, payload, checked_at))
            else:
                reason = (
                    "controlled_live_lp_absent"
                    if controlled["status"] == _STATUS_NOT_YET
                    else "decision_grade_free_preflight_failed"
                )
                checks.extend(_not_yet_paid_checks(reason))
    except Exception as exc:
        return _finish_runner_failure(history, run_id, checks, exc)

    verdict = _verdict(checks)
    history.finish_canary_run(
        run_id,
        verdict=verdict,
        checks=checks,
        finished_at=_utc_now().isoformat(),
    )
    return CanaryOutcome(verdict, run_id, checks)


def main(
    environment: Mapping[str, str] | None = None,
    *,
    now: datetime | None = None,
    transport: httpx.BaseTransport | None = None,
    store: Store | None = None,
) -> int:
    outcome = run_from_environment(
        environment, now=now, transport=transport, store=store
    )
    if outcome.verdict == "window_ended":
        print("Docket canary: monitoring window ended")
        return 0
    print(f"Docket canary: {outcome.verdict}")
    if outcome.verdict == _STATUS_PASSED:
        return 0
    if outcome.verdict == _STATUS_FAILED:
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
