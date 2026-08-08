from docket.hire.catalogue import SERVICES, get_service


def test_range_doctor_is_offered_and_describes_itself():
    svc = get_service("range-doctor")
    assert svc is not None
    assert svc.what_you_get and svc.typical_seconds > 0
    assert "wallet" in svc.input_schema


def test_unknown_service_returns_none():
    assert get_service("nope") is None


def test_every_service_states_a_price_and_an_asset():
    for svc in SERVICES.values():
        assert svc.price_display and svc.price_atomic and svc.asset


def test_no_service_promises_an_outcome():
    """Docket sells work performed, not results achieved.

    `advice`, `signal to trade` and `will` joined the list when a market-regime read
    entered the catalogue: a trading signal is the easiest thing here to describe as
    an instruction, and the description is the contract.
    """
    banned = (
        "guaranteed",
        "profit",
        "best",
        "safe",
        "will increase",
        "recommended",
        "advice",
        "signal to trade",
        "will",
    )
    for svc in SERVICES.values():
        blob = f"{svc.name} {svc.what_you_get}".lower()
        for word in banned:
            assert word not in blob, f"{svc.id} promises: {word}"
