from docket.signals import name_family, signals_for


def _agent(**over) -> dict:
    base = {
        "agent_id": "56:0xreg:1",
        "token_id": "1",
        "name": "Some Agent",
        "description": "does a thing",
        "owner_address": "0xowner",
        "supported_protocols": [],
        "x402_supported": False,
        "total_feedbacks": 0,
        "total_score": 0.0,
    }
    base.update(over)
    return base


def test_placeholder_name_is_detected():
    assert signals_for(_agent(name="Agent #254413"))["placeholder_name"] is True
    assert signals_for(_agent(name="SOLVENT"))["placeholder_name"] is False


def test_callable_requires_a2a_or_mcp():
    assert signals_for(_agent(supported_protocols=["A2A"]))["callable"] is True
    assert signals_for(_agent(supported_protocols=["MCP"]))["callable"] is True
    assert signals_for(_agent(supported_protocols=["Web"]))["callable"] is False
    assert signals_for(_agent(supported_protocols=[]))["callable"] is False


def test_has_feedback_is_strictly_positive():
    assert signals_for(_agent(total_feedbacks=1))["has_feedback"] is True
    assert signals_for(_agent(total_feedbacks=0))["has_feedback"] is False


def test_describes_itself_requires_real_description():
    assert signals_for(_agent(description=None))["describes_itself"] is False
    assert signals_for(_agent(description="   "))["describes_itself"] is False
    assert signals_for(_agent(description="A yield agent."))["describes_itself"] is True


def test_name_family_collapses_bulk_mint_families():
    # Verified pattern: one family is ~46% of the chain under near-identical names.
    assert name_family(_agent(name="Ave.ai Trading Agent")) == "ave.ai"
    assert name_family(_agent(name="Ave.ai Research Agent")) == "ave.ai"
    assert name_family(_agent(name="Purr-Fect 1234")) == "purr-fect"
    assert name_family(_agent(name="SOLVENT")) == "solvent"


def test_name_family_falls_back_to_owner_for_placeholder_names():
    assert name_family(_agent(name="Agent #999", owner_address="0xABC")) == "owner:0xabc"


def test_name_family_groups_two_unrelated_owners_under_one_key():
    """The reason the label had to change. Grouping is the first token of a name anyone can
    type, so two addresses that never met share a key — which is what "publisher" denied."""
    mine = _agent(name="SOLVENT Trading", owner_address="0xaaa")
    theirs = _agent(name="SOLVENT Imposter", owner_address="0xbbb")
    assert name_family(mine) == name_family(theirs) == "solvent"
    assert mine["owner_address"] != theirs["owner_address"]


def test_name_family_disclaims_provenance_where_a_reader_will_see_it():
    """The docstring is the label's fine print: it ships in the source an evaluator reads."""
    doc = name_family.__doc__.lower()
    assert "not" in doc and "provenance" in doc
    assert "first token" in doc


def test_signals_expose_no_publisher_key_at_all():
    assert "publisher" not in signals_for(_agent())
    assert signals_for(_agent(name="Ave.ai Trading Agent"))["name_family"] == "ave.ai"


def test_signals_never_assert_safety():
    # Guard against a future contributor adding a "trusted"/"safe" verdict field.
    keys = set(signals_for(_agent()))
    assert not (keys & {"safe", "trusted", "verified_by_docket", "recommended"})
