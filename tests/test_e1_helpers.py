from experiments.e1_instant_settlement import (
    STATUS,
    _abort_note,
    _decode_error,
    canonical_manifest_hash,
)


def test_canonical_manifest_hash_is_stable_and_key_ordered():
    a = canonical_manifest_hash({"b": 1, "a": {"y": 2, "x": 1}})
    b = canonical_manifest_hash({"a": {"x": 1, "y": 2}, "b": 1})
    assert a == b
    assert a.startswith("0x") and len(a) == 66


def test_status_enum_order():
    assert STATUS[0] == "OPEN" and STATUS[3] == "COMPLETED"


def test_decode_error_names_the_kernel_custom_error():
    # the selector the testnet kernel returns for createJob(..., hook=0x0)
    assert _decode_error("ContractCustomError('0x55c45de1', '0x55c45de1')") == "HookRequired()"
    assert _decode_error("plain timeout, no revert data") is None


def test_decode_error_resolves_the_router_fund_gate():
    # 0x32d53d69 is a router error, not a kernel one — it only names once the union
    # selector table spans EvaluatorRouter/OptimisticPolicy alongside the kernel (Task 2b)
    assert _decode_error("ContractCustomError('0x32d53d69', '0x32d53d69')") == "PolicyNotSet()"
    # and the router's evaluator invariant, which is E1-revised's actual answer
    assert _decode_error("execution reverted 0xec43ea50") == "RouterNotEvaluator()"


def test_abort_note_flags_a_run_that_stopped_before_complete():
    # the likely outcome today: the hook rejects fund(), so complete() is never attempted
    note = _abort_note(["fund_evaluator_gas", "create_job", "set_budget", "approve", "fund"])
    assert "does NOT answer E1" in note and "ABORTED AT fund" in note
    assert "ABORTED AT setup" in _abort_note([])


def test_abort_note_is_silent_once_complete_was_attempted():
    # a revert *on* complete() is a real E1 answer, so `notes` must not disown it
    assert _abort_note(["create_job", "set_budget", "approve", "fund", "submit", "complete"]) == ""
