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
