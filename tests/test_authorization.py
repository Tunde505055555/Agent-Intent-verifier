"""Enforceable authorization over agent-history writes and challenges.

Rule: only the authenticated agent itself, the intent owner, or a delegate
explicitly granted by the agent may append records to that agent's history;
the same parties may file a challenge. Untrusted callers can never influence
later verdicts by writing into another agent's history.
"""

import pytest

from tools.harness import genlayer_stub

OWNER = "0x" + "ab" * 20
AGENT = "0x" + "cd" * 20
OTHER = "0x" + "ee" * 20


@pytest.fixture(autouse=True)
def _reset_sender():
    yield
    genlayer_stub.set_sender("0x" + "ab" * 20)


def register(contract, sender=OWNER):
    genlayer_stub.set_sender(sender)
    return contract.register_intent(
        intent_text="Book me the cheapest direct flight from Lisbon to Berlin under $500 total.",
        permissions=["search flights", "purchase one economy ticket up to $500"],
        constraints=["direct flights only", "total cost must not exceed $500"],
        preferences=["morning departure if possible"],
        context="Afternoon meeting in Berlin.",
    )


def verify(contract, sender, agent=AGENT):
    genlayer_stub.set_sender(sender)
    return contract.verify_action(
        intent_id="intent-1",
        intent_version=0,
        agent_address=agent,
        proposed_action="Purchase a direct Lisbon-Berlin economy ticket, 08:10, $412 total.",
        agent_reasoning="Cheapest direct option under the limit.",
        evidence_text="Fare quote total $412.00 incl. taxes.",
        evidence_urls=[],
    )


def test_unauthorized_caller_cannot_write_agent_history(contract):
    register(contract)
    with pytest.raises(genlayer_stub.UserError):
        verify(contract, OTHER)
    assert list(contract.decision_ids) == [], "no record may be written"


def test_intent_owner_is_authorized_to_submit(contract):
    register(contract)
    record = verify(contract, OWNER, agent=AGENT)
    assert record["authority"] == "intent_owner"
    assert record["agent"] == AGENT


def test_agent_can_submit_for_itself(contract):
    register(contract, sender=AGENT)
    record = verify(contract, AGENT, agent=AGENT)
    assert record["authority"] == "agent"


def test_delegation_grants_then_revokes_access(contract):
    register(contract)
    with pytest.raises(genlayer_stub.UserError):
        verify(contract, OTHER)

    genlayer_stub.set_sender(AGENT)
    contract.grant_agent_authority(agent_address=AGENT, delegate=OTHER)
    assert contract.get_agent_delegates(AGENT) == [OTHER]

    record = verify(contract, OTHER)
    assert record["authority"] == "delegated"

    genlayer_stub.set_sender(AGENT)
    contract.revoke_agent_authority(agent_address=AGENT, delegate=OTHER)
    assert contract.get_agent_delegates(AGENT) == []
    with pytest.raises(genlayer_stub.UserError):
        verify(contract, OTHER)


def test_only_the_agent_itself_grants_or_revokes(contract):
    register(contract)
    with pytest.raises(genlayer_stub.UserError):
        genlayer_stub.set_sender(OTHER) or contract.grant_agent_authority(
            agent_address=AGENT, delegate=OTHER
        )
    with pytest.raises(genlayer_stub.UserError):
        genlayer_stub.set_sender(OWNER) or contract.grant_agent_authority(
            agent_address=AGENT, delegate=OWNER
        )
    genlayer_stub.set_sender(AGENT)
    contract.grant_agent_authority(agent_address=AGENT, delegate=OWNER)
    with pytest.raises(genlayer_stub.UserError):
        genlayer_stub.set_sender(OTHER) or contract.revoke_agent_authority(
            agent_address=AGENT, delegate=OWNER
        )


def test_agent_cannot_delegate_to_itself(contract):
    genlayer_stub.set_sender(AGENT)
    with pytest.raises(genlayer_stub.UserError):
        contract.grant_agent_authority(agent_address=AGENT, delegate=AGENT)


def test_unauthorized_caller_cannot_challenge(contract):
    register(contract)
    record = verify(contract, OWNER)
    with pytest.raises(genlayer_stub.UserError):
        genlayer_stub.set_sender(OTHER) or contract.challenge_decision(
            decision_id=record["decision_id"],
            counterargument="please reconsider",
            extra_evidence="",
            extra_evidence_urls=[],
        )
    assert contract.get_decision(record["decision_id"]).get("challenges", []) == []


def test_authorized_parties_can_challenge(contract):
    register(contract, sender=AGENT)
    record = verify(contract, AGENT)
    # the judged agent's delegate may challenge
    genlayer_stub.set_sender(AGENT)
    contract.grant_agent_authority(agent_address=AGENT, delegate=OWNER)
    appeal = genlayer_stub.set_sender(OWNER) or contract.challenge_decision(
        decision_id=record["decision_id"],
        counterargument="appeal-accepts: fare was refunded in full.",
        extra_evidence="Refund confirmation email.",
        extra_evidence_urls=[],
    )
    assert appeal["challenge_authority"] == "delegated"
    # the intent owner may also challenge
    second = verify(contract, AGENT)
    appeal2 = genlayer_stub.set_sender(AGENT) or contract.challenge_decision(
        decision_id=second["decision_id"],
        counterargument="appeal-accepts: alternative direct fare exists.",
        extra_evidence="",
        extra_evidence_urls=[],
    )
    assert appeal2["challenge_authority"] == "agent"


def test_authorization_view_reflects_current_state(contract):
    register(contract)
    genlayer_stub.set_sender(OTHER)
    denied = contract.get_authorization("intent-1", 0, AGENT)
    assert denied["authorized"] is False and denied["authority"] == ""
    genlayer_stub.set_sender(OWNER)
    owner_call = contract.get_authorization("intent-1", 0, AGENT)
    assert owner_call["authorized"] is True
    assert owner_call["authority"] == "intent_owner"

    genlayer_stub.set_sender(AGENT)
    contract.grant_agent_authority(agent_address=AGENT, delegate=OTHER)
    genlayer_stub.set_sender(OTHER)
    granted = contract.get_authorization("intent-1", 0, AGENT)
    assert granted["authorized"] is True
    assert granted["authority"] == "delegated"
    assert granted["delegates"] == [OTHER]


def test_demo_scenarios_stay_out_of_user_histories(contract):
    result = contract.run_demo_scenario("authorized_flight")
    assert result["record"]["authority"] == "demo"
    assert result["record"]["agent"].startswith("demo-agent-")
    history = contract.get_agent_alignment_history(AGENT)
    assert history["verified_decisions"] == 0
