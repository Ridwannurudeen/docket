import json
from pathlib import Path

ABI_DIR = Path(__file__).resolve().parents[1] / "abis"


def _fn_names(abi: list) -> set[str]:
    return {e["name"] for e in abi if e.get("type") == "function"}


def test_commerce_abi_has_e1_functions():
    abi = json.loads((ABI_DIR / "AgenticCommerce.json").read_text())
    if isinstance(abi, dict):  # some repos wrap as {"abi": [...]}
        abi = abi["abi"]
    names = _fn_names(abi)
    for required in {
        "createJob",
        "setBudget",
        "fund",
        "submit",
        "complete",
        "jobs",
        "jobCounter",
        "claimRefund",
    }:
        assert required in names, f"missing {required}"


def test_erc20_abi_has_approve_and_balance():
    abi = json.loads((ABI_DIR / "ERC20.json").read_text())
    if isinstance(abi, dict):
        abi = abi["abi"]
    names = _fn_names(abi)
    assert {"approve", "balanceOf"} <= names


def _load(name: str) -> list:
    abi = json.loads((ABI_DIR / name).read_text())
    return abi["abi"] if isinstance(abi, dict) else abi


def _sig(entry: dict) -> str:
    def kind(item):
        if item["type"].startswith("tuple"):
            inner = ",".join(kind(comp) for comp in item["components"])
            return f"({inner}){item['type'][len('tuple') :]}"
        return item["type"]

    return (
        entry["name"] + "(" + ",".join(kind(i) for i in entry.get("inputs", [])) + ")"
    )


def test_escrow_abi_fragments_match_the_vendored_artifacts():
    """The escrow modules carry hand-written ABI fragments, because `abis/` is a repo
    directory and does not exist on the deployed box. Hand-written means it can drift,
    and a fragment whose types drift encodes a different selector — a call the contract
    silently does not recognise. Compare every fragment against the real artifact."""
    from docket.escrow import chain, flow

    vendored = {
        "AgenticCommerce.json": [flow.COMMERCE_ABI, chain.COMMERCE_ABI],
        "EvaluatorRouter.json": [flow.ROUTER_ABI, chain.ROUTER_ABI],
        "OptimisticPolicy.json": [chain.POLICY_ABI],
        "ERC20.json": [flow.ERC20_ABI],
    }
    checked = 0
    for artifact, fragment_sets in vendored.items():
        truth = {
            e["name"]: _sig(e) for e in _load(artifact) if e.get("type") == "function"
        }
        for fragment in fragment_sets:
            for entry in fragment:
                name = entry["name"]
                assert name in truth, f"{name} is not in {artifact}"
                assert _sig(entry) == truth[name], (
                    f"{artifact}:{name} fragment signature {_sig(entry)} "
                    f"drifted from {truth[name]}"
                )
                checked += 1
    assert checked >= 8


def test_every_router_error_signature_the_explainer_knows_is_real():
    """The explainer matches reverts by selector, computed from these strings. A typo
    would not fail loudly — it would just never match, and every revert would degrade to
    'the call reverted', which is precisely the unhelpful output it exists to prevent."""
    from docket.escrow.settle import ROUTER_ERROR_SIGNATURES

    truth = {
        e["name"] + "(" + ",".join(i["type"] for i in e.get("inputs", [])) + ")"
        for e in _load("EvaluatorRouter.json")
        if e.get("type") == "error"
    }
    for sig in ROUTER_ERROR_SIGNATURES:
        assert sig in truth, f"{sig} is not an error on EvaluatorRouter"


def test_the_job_struct_field_order_is_the_one_the_reader_assumes():
    """`status` is field 7 and the last field is a bytes32 deliverable. Reading `[-1]`
    as status finds nothing and reports every job as unsubmitted, which is exactly the
    bug that cost E1c a run."""
    from docket.escrow.chain import JOB_FIELDS

    get_job = next(
        e for e in _load("AgenticCommerce.json") if e.get("name") == "getJob"
    )
    assert tuple(c["name"] for c in get_job["outputs"][0]["components"]) == JOB_FIELDS
    assert JOB_FIELDS[7] == "status"
    assert JOB_FIELDS[-1] == "deliverable"
