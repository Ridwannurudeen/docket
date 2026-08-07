from experiments.e1_instant_settlement import STATUS, _decode_error, canonical_manifest_hash


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
