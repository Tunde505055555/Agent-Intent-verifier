"""End-to-end demonstration scenarios executed through the contract itself."""

import pytest

from tools.harness import genlayer_stub

EXPECTED = {
    "authorized_flight": "ALLOW",
    "ambiguous_upgrade": "REQUIRE_APPROVAL",
    "hard_constraint_violation": "BLOCK",
    "unverifiable_claim": "INSUFFICIENT_EVIDENCE",
    "loophole_exploitation": "BLOCK",
    "behavioral_drift": "REQUIRE_APPROVAL",
}


@pytest.mark.parametrize("name,expected", sorted(EXPECTED.items()))
def test_demo_scenarios(contract, name, expected):
    result = contract.run_demo_scenario(name)
    assert result["decision"] == expected, result["record"]["verdict"]["reason"]
    assert result["expected_decision"] == expected
    assert result["matches_expectation"] is True


def test_scenario_catalogue_matches_tests(contract):
    listed = {entry["name"]: entry["expected_decision"] for entry in contract.list_demo_scenarios()}
    assert listed == EXPECTED


def test_allow_scenario_record_is_complete(contract, contract_module):
    record = contract.run_demo_scenario("authorized_flight")["record"]
    verdict = record["verdict"]
    assert verdict["decision"] == "ALLOW"
    assert verdict["requires_human_approval"] is False
    assert 0 <= verdict["intent_alignment_score"] <= 100
    assert verdict["risk_level"] in contract_module.RISK_LEVELS
    assert verdict["validator_consensus"]["result"] == "AGREED"
    assert len(record["decision_hash"]) == 64
    assert record["intent_spec"]["primary_objective"]
    assert "User wanted:" in verdict["explanation"]
    # no raw private payloads are stored: only hashes of reasoning
    assert "agent_reasoning" not in record
    assert len(record["reasoning_hash"]) == 64


def test_persisted_scores_are_exactly_what_validators_agreed_on(contract, contract_module):
    """Consensus agrees on the score band, so every persisted score must be
    the band representative — never a leader-only exact value."""
    for name in EXPECTED:
        verdict = contract.run_demo_scenario(name)["record"]["verdict"]
        for field in contract_module.VERDICT_SCORE_FIELDS:
            stored = verdict[field]
            assert stored == contract_module.quantize_score(stored)
            assert stored % contract_module.SCORE_BAND_WIDTH == contract_module.SCORE_BAND_WIDTH // 2
        assert (
            verdict["validator_consensus"]["fingerprint"]["alignment_band"]
            == verdict["intent_alignment_score"] // contract_module.SCORE_BAND_WIDTH
        )


def test_loophole_case_reports_deception_and_hidden_cost(contract):
    verdict = contract.run_demo_scenario("loophole_exploitation")["record"]["verdict"]
    assert verdict["decision"] == "BLOCK"
    assert verdict["deception_signals"]
    assert verdict["risk_level"] in ("HIGH", "CRITICAL")


def test_drift_case_is_flagged_not_silently_allowed(contract):
    verdict = contract.run_demo_scenario("behavioral_drift")["record"]["verdict"]
    assert verdict["behavioral_consistency"]["flags"]
    assert verdict["decision"] == "REQUIRE_APPROVAL"
    assert "behavioral drift flagged against verified history" in verdict["policy_escalations"]


def test_insufficient_evidence_case_attempts_web_retrieval(contract, runtime):
    verdict = contract.run_demo_scenario("unverifiable_claim")["record"]["verdict"]
    assert verdict["decision"] == "INSUFFICIENT_EVIDENCE"
    assert runtime.trace.urls, "the contract must try to fetch the cited evidence"
    assert verdict["requires_human_approval"] is True


def test_ambiguous_case_draws_the_intent_boundary(contract):
    verdict = contract.run_demo_scenario("ambiguous_upgrade")["record"]["verdict"]
    boundary = verdict["intent_boundary"]
    assert boundary["clearly_authorized"]
    assert boundary["ambiguous"]
    assert boundary["clearly_unauthorized"]
    assert verdict["ambiguities"]


def test_leader_and_validators_both_evaluate(contract, runtime):
    contract.run_demo_scenario("authorized_flight")
    assert runtime.trace.leader_runs == 1
    assert runtime.trace.validator_runs == runtime.validator_count
    assert all(runtime.trace.agreements)


def test_validator_disagreement_blocks_the_write(contract, model):
    """A hallucinating leader cannot push a verdict through consensus."""
    model.flip_after = 2  # leader answers normally, validators diverge
    with pytest.raises(genlayer_stub.ConsensusFailure):
        contract.run_demo_scenario("authorized_flight")
    assert list(contract.decision_ids) == []
