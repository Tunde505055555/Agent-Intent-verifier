"""Unit tests for the deterministic layer: enums, score ranges, required
fields, escalation policy, hashing, trust maths. These must be identical on
every validator, so they are pure functions with no LLM involvement."""

import json

import pytest


@pytest.fixture()
def m(contract_module):
    return contract_module


def test_quantize_score_snaps_to_band_representative(m):
    assert m.quantize_score(0) == 10
    assert m.quantize_score(19) == 10
    assert m.quantize_score(20) == 30
    assert m.quantize_score(87) == 90
    assert m.quantize_score(99) == 90
    assert m.quantize_score(100) == 90  # 100 shares the top band
    # two materially different scores in the same band persist identically
    assert m.quantize_score(21) == m.quantize_score(39)


def test_clamp_score_handles_garbage(m):
    assert m.clamp_score(101) == 100
    assert m.clamp_score(-5) == 0
    assert m.clamp_score("87") == 87
    assert m.clamp_score("high") == 0
    assert m.clamp_score(None) == 0
    assert m.clamp_score(True) == 0


def test_parse_model_json_recovers_from_fences_and_prose(m):
    raw = "Sure!\n```json\n{\"decision\": \"ALLOW\"}\n```\nHope that helps"
    assert m.parse_model_json(raw) == {"decision": "ALLOW"}
    assert m.parse_model_json("not json at all") == {}


def test_normalize_verdict_enforces_enums_and_fields(m):
    out = m.normalize_verdict({"decision": "allow it", "risk_level": "spicy"})
    assert out["decision"] == "REQUIRE_APPROVAL"  # unknown enum degrades safely
    assert out["risk_level"] == "MEDIUM"
    for field in m.VERDICT_SCORE_FIELDS:
        assert 0 <= out[field] <= 100
    for field in m.VERDICT_LIST_FIELDS:
        assert isinstance(out[field], list)
    assert set(out["intent_boundary"]) == set(m.BOUNDARY_BUCKETS)


def test_normalize_intent_spec_shape(m):
    spec = m.normalize_intent_spec({"primary_objective": "", "required_conditions": "x"})
    assert spec["primary_objective"] == "UNDETERMINED"
    assert spec["required_conditions"] == ["x"]
    assert isinstance(spec["quantitative_limits"], dict)


def test_hard_constraint_forces_block_even_if_model_says_allow(m):
    verdict = m.normalize_verdict({"decision": "ALLOW", "hard_constraint_violated": True})
    out = m.apply_deterministic_policy(verdict)
    assert out["decision"] == "BLOCK"
    assert out["risk_level"] != "LOW"
    assert "hard constraint violated" in out["policy_escalations"]


def test_missing_permission_forces_block(m):
    out = m.apply_deterministic_policy(
        m.normalize_verdict({"decision": "ALLOW", "permission_missing": True})
    )
    assert out["decision"] == "BLOCK"


def test_unverified_evidence_forces_insufficient(m):
    out = m.apply_deterministic_policy(
        m.normalize_verdict(
            {
                "decision": "ALLOW",
                "evidence_required": True,
                "evidence_sufficient": False,
                "intent_alignment_score": 90,
                "permission_score": 90,
                "constraint_compliance_score": 90,
                "goal_preserved": True,
                "reasoning_supports_action": True,
                "counterfactual_user_would_accept": "YES",
            }
        )
    )
    assert out["decision"] == "INSUFFICIENT_EVIDENCE"
    assert out["requires_human_approval"] is True


def test_ambiguity_downgrades_allow_to_approval(m):
    out = m.apply_deterministic_policy(
        m.normalize_verdict(
            {
                "decision": "ALLOW",
                "intent_alignment_score": 90,
                "permission_score": 90,
                "constraint_compliance_score": 90,
                "goal_preserved": True,
                "reasoning_supports_action": True,
                "counterfactual_user_would_accept": "YES",
                "ambiguities": ["'good seat' is undefined"],
            }
        )
    )
    assert out["decision"] == "REQUIRE_APPROVAL"


def test_deception_signals_never_allow(m):
    out = m.apply_deterministic_policy(
        m.normalize_verdict(
            {
                "decision": "ALLOW",
                "intent_alignment_score": 95,
                "permission_score": 95,
                "constraint_compliance_score": 95,
                "goal_preserved": True,
                "reasoning_supports_action": True,
                "counterfactual_user_would_accept": "YES",
                "deception_signals": ["hidden fee"],
            }
        )
    )
    assert out["decision"] == "REQUIRE_APPROVAL"


def test_failed_counterfactual_requires_approval(m):
    out = m.apply_deterministic_policy(
        m.normalize_verdict(
            {
                "decision": "ALLOW",
                "intent_alignment_score": 95,
                "permission_score": 95,
                "constraint_compliance_score": 95,
                "goal_preserved": True,
                "reasoning_supports_action": True,
                "counterfactual_user_would_accept": "UNCLEAR",
            }
        )
    )
    assert out["decision"] == "REQUIRE_APPROVAL"


def test_fingerprint_tolerates_wording_but_not_substance(m):
    a = m.apply_deterministic_policy(
        m.normalize_verdict({"decision": "BLOCK", "intent_alignment_score": 21})
    )
    b = m.apply_deterministic_policy(
        m.normalize_verdict(
            {"decision": "BLOCK", "intent_alignment_score": 25, "reason": "different words"}
        )
    )
    c = m.apply_deterministic_policy(
        m.normalize_verdict({"decision": "ALLOW", "intent_alignment_score": 95})
    )
    assert m.verdicts_agree(a, b)
    assert not m.verdicts_agree(a, c)


def test_behavioral_analysis_flags_drift_without_auto_reject(m):
    history = [
        {"decision": "ALLOW", "intent_alignment_score": 92},
        {"decision": "REQUIRE_APPROVAL", "intent_alignment_score": 71},
        {"decision": "REQUIRE_APPROVAL", "intent_alignment_score": 58},
    ]
    verdict = m.normalize_verdict({"decision": "ALLOW", "intent_alignment_score": 79})
    analysis = m.behavioral_analysis(history, verdict)
    assert "repeated boundary testing" in analysis["flags"]
    assert "goal drift" in analysis["flags"]
    assert "additional evidence" in analysis["note"]


def test_alignment_history_is_not_a_single_reputation_number(m):
    history = m.alignment_history(
        [
            {"decision": "ALLOW", "intent_alignment_score": 90},
            {"decision": "BLOCK", "intent_alignment_score": 20},
        ]
    )
    assert history["verified_decisions"] == 2
    assert history["decision_counts"]["BLOCK"] == 1
    assert "caveat" in history


def test_decision_hash_is_stable_and_content_bound(m):
    record = {
        "intent_id": "intent-1",
        "intent_version": 1,
        "intent_spec_hash": "a" * 64,
        "action_hash": "b" * 64,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "round": "initial",
        "verdict": m.apply_deterministic_policy(m.normalize_verdict({"decision": "ALLOW"})),
    }
    first = m.decision_record_hash(record)
    assert first == m.decision_record_hash(json.loads(json.dumps(record)))
    record["action_hash"] = "c" * 64
    assert m.decision_record_hash(record) != first


def test_explanation_follows_required_narrative(m):
    spec = m.normalize_intent_spec({"primary_objective": "book a cheap direct flight"})
    verdict = m.apply_deterministic_policy(m.normalize_verdict({"decision": "ALLOW"}))
    text = m.build_explanation(spec, "buy the $412 ticket", verdict)
    for marker in ("User wanted:", "Agent proposed:", "Evidence/context:", "Decision:"):
        assert marker in text
