"""Intent versioning, decision history, challenge/appeal, trust signal."""

import pytest

from tools.harness import genlayer_stub


def register(contract, **overrides):
    payload = {
        "intent_text": "Book me the cheapest direct flight from Lisbon to Berlin on 12 March under $500 total.",
        "permissions": ["search flights", "purchase one economy ticket up to $500"],
        "constraints": ["direct flights only", "total cost must not exceed $500"],
        "preferences": ["morning departure if possible"],
        "context": "Afternoon meeting in Berlin.",
    }
    payload.update(overrides)
    return contract.register_intent(**payload)


def verify(contract, intent_id, version=0, **overrides):
    payload = {
        "intent_id": intent_id,
        "intent_version": version,
        "agent_address": "0xAGENT",
        "proposed_action": "Purchase a direct Lisbon-Berlin economy ticket, 08:10, $412 total.",
        "agent_reasoning": "Cheapest direct option under the limit.",
        "evidence_text": "Fare quote total $412.00 incl. taxes.",
        "evidence_urls": [],
    }
    payload.update(overrides)
    return contract.verify_action(**payload)


def test_register_and_read_intent(contract):
    out = register(contract)
    assert out["intent_id"] == "intent-1"
    assert out["version"] == 1
    stored = contract.get_intent("intent-1", 0)
    assert stored["version"] == 1
    assert len(stored["intent_hash"]) == 64


def test_amend_creates_identifiable_versions(contract):
    register(contract)
    amended = contract.amend_intent(
        intent_id="intent-1",
        intent_text="Cheapest direct flight on 12 March under $650 total.",
        permissions=["purchase one economy ticket up to $650"],
        constraints=["direct flights only", "total cost must not exceed $650"],
        preferences=[],
        context="Budget raised.",
    )
    assert amended["version"] == 2
    versions = contract.get_intent_versions("intent-1")
    assert [v["version"] for v in versions] == [1, 2]
    assert versions[0]["intent_hash"] != versions[1]["intent_hash"]
    assert contract.get_intent("intent-1", 1)["intent_text"].endswith("under $500 total.")
    assert contract.get_intent("intent-1", 0)["version"] == 2


def test_action_is_judged_against_the_selected_version(contract):
    register(contract)
    contract.amend_intent(
        intent_id="intent-1",
        intent_text="Cheapest direct flight under $650 total.",
        permissions=["purchase up to $650"],
        constraints=["direct flights only"],
        preferences=[],
        context="",
    )
    record = verify(contract, "intent-1", version=1)
    assert record["intent_version"] == 1
    assert record["intent_hash"] == contract.get_intent("intent-1", 1)["intent_hash"]


def test_unknown_intent_and_version_are_rejected(contract):
    with pytest.raises(genlayer_stub.UserError):
        verify(contract, "intent-404")
    register(contract)
    with pytest.raises(genlayer_stub.UserError):
        verify(contract, "intent-1", version=7)


def test_empty_inputs_are_rejected(contract):
    with pytest.raises(genlayer_stub.UserError):
        register(contract, intent_text="")
    register(contract)
    with pytest.raises(genlayer_stub.UserError):
        verify(contract, "intent-1", proposed_action="")


def test_only_owner_may_amend(contract):
    register(contract)
    genlayer_stub.set_sender("0x" + "ff" * 20)
    try:
        with pytest.raises(genlayer_stub.UserError):
            contract.amend_intent(
                intent_id="intent-1",
                intent_text="Spend up to $5,000.",
                permissions=["spend up to $5,000"],
                constraints=[],
                preferences=[],
                context="",
            )
    finally:
        genlayer_stub.set_sender("0x" + "ab" * 20)


def test_decision_history_and_indexes(contract):
    register(contract)
    first = verify(contract, "intent-1")
    second = verify(contract, "intent-1")
    assert list(contract.decision_ids) == [first["decision_id"], second["decision_id"]]
    assert contract.get_intent_decisions("intent-1") == [
        first["decision_id"],
        second["decision_id"],
    ]
    assert contract.get_decision(first["decision_id"])["decision_hash"] == first["decision_hash"]
    with pytest.raises(genlayer_stub.UserError):
        contract.get_decision("dec-999")


def test_challenge_runs_fresh_evaluation_and_preserves_original(contract, model):
    register(
        contract,
        intent_text="Book the cheapest hotel near the conference under $200 per night.",
        permissions=["book one hotel room for three nights"],
        constraints=["under $200 per night", "walking distance to the venue"],
    )
    original = verify(
        contract,
        "intent-1",
        proposed_action="Book a $189 per night room with a mandatory $70 per night resort and city service fee.",
        agent_reasoning="The nightly rate is under $200.",
        evidence_text="resort and city service fee $70/night payable at property",
    )
    assert original["verdict"]["decision"] == "BLOCK"
    prompts_before = model.calls

    appeal = contract.challenge_decision(
        decision_id=original["decision_id"],
        counterargument="appeal-accepts: the property waived the mandatory fee in writing for this rate.",
        extra_evidence="Hotel confirmation: resort fee waived, all-in $189/night, 600 m from venue.",
        extra_evidence_urls=[],
    )

    assert model.calls > prompts_before, "a challenge must trigger a fresh evaluation"
    assert appeal["original_decision"] == "BLOCK"
    assert appeal["challenge_decision"] == "ALLOW"
    assert appeal["changed"] is True

    stored_original = contract.get_decision(original["decision_id"])
    assert stored_original["verdict"]["decision"] == "BLOCK", "original must be preserved"
    assert stored_original["challenges"] == [appeal["challenge_decision_id"]]

    trail = contract.get_audit_trail(original["decision_id"])
    assert trail["challenges"] == [
        {"decision_id": appeal["challenge_decision_id"], "decision": "ALLOW"}
    ]
    challenge_record = contract.get_decision(appeal["challenge_decision_id"])
    assert challenge_record["round"] == "challenge"
    assert challenge_record["parent_decision_id"] == original["decision_id"]


def test_challenge_requires_new_material(contract):
    register(contract)
    record = verify(contract, "intent-1")
    with pytest.raises(genlayer_stub.UserError):
        contract.challenge_decision(
            decision_id=record["decision_id"],
            counterargument="",
            extra_evidence="",
            extra_evidence_urls=[],
        )
    with pytest.raises(genlayer_stub.UserError):
        contract.challenge_decision(
            decision_id="dec-404",
            counterargument="please reconsider",
            extra_evidence="",
            extra_evidence_urls=[],
        )


def test_alignment_history_trust_signal(contract):
    register(contract)
    verify(contract, "intent-1")
    verify(contract, "intent-1")
    history = contract.get_agent_alignment_history("0xagent")
    assert history["verified_decisions"] == 2
    assert history["decision_counts"]["ALLOW"] == 2
    assert history["mean_alignment_score"] > 0
    assert "not a permanent global reputation score" in history["caveat"]


def test_history_is_supplied_to_later_evaluations(contract, runtime):
    register(contract)
    verify(contract, "intent-1")
    runtime.reset()
    verify(contract, "intent-1")
    verdict_prompts = [p for p in runtime.trace.prompts if "PREVIOUSLY VERIFIED ACTIONS" in p]
    assert verdict_prompts
    assert "intent_alignment_score" in verdict_prompts[0]


def test_policy_surface_is_published(contract, contract_module):
    policy = contract.get_policy()
    assert policy["decisions"] == list(contract_module.DECISIONS)
    assert policy["score_range"] == [0, 100]
    assert any("BLOCK" in rule for rule in policy["deterministic_escalations"])
    assert "run_nondet" in policy["consensus"]
