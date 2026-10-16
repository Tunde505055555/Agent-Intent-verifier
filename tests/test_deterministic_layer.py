"""Unit tests for the deterministic (validator-identical) layer of the contract."""
import agent_intent_verifier as aiv


def good_verdict(**over):
    base = {
        "decision": "ALLOW", "risk_level": "LOW",
        "intent_alignment_score": 92, "permission_score": 95,
        "constraint_compliance_score": 96, "reasoning_quality_score": 88,
        "evidence_support_score": 90, "goal_preserved": True,
        "reasoning_supports_action": True, "evidence_sufficient": True,
        "counterfactual_user_would_accept": "YES",
    }
    base.update(over)
    return aiv.apply_deterministic_policy(aiv.normalize_verdict(base))


# --- normalisation -------------------------------------------------------

def test_clamp_score_bounds_and_garbage():
    assert aiv.clamp_score(150) == 100
    assert aiv.clamp_score(-3) == 0
    assert aiv.clamp_score("72.6") == 73
    assert aiv.clamp_score("abc") == 0
    assert aiv.clamp_score(True) == 0


def test_parse_model_json_recovers_fenced_output():
    raw = 'Sure!\n```json\n{"decision": "BLOCK"}\n```'
    assert aiv.parse_model_json(raw) == {"decision": "BLOCK"}
    assert aiv.parse_model_json("no json here") == {}


def test_unknown_decision_degrades_to_approval():
    v = aiv.normalize_verdict({"decision": "YOLO", "risk_level": "EXTREME"})
    assert v["decision"] == aiv.DECISION_APPROVAL
    assert v["risk_level"] == "MEDIUM"
    assert v["counterfactual_user_would_accept"] == "UNCLEAR"


def test_intent_spec_shape():
    spec = aiv.normalize_intent_spec({"required_conditions": "direct", "quantitative_limits": {"max": 500}})
    assert spec["primary_objective"] == "UNDETERMINED"
    assert spec["required_conditions"] == ["direct"]
    assert spec["quantitative_limits"] == {"max": "500"}
    for f in aiv.SPEC_LIST_FIELDS:
        assert isinstance(spec[f], list)


# --- deterministic policy (LLM can never soften these) -------------------

def test_clean_verdict_is_allowed():
    v = good_verdict()
    assert v["decision"] == aiv.DECISION_ALLOW
    assert v["requires_human_approval"] is False


def test_hard_constraint_forces_block_even_if_model_says_allow():
    v = good_verdict(hard_constraint_violated=True)
    assert v["decision"] == aiv.DECISION_BLOCK
    assert v["risk_level"] == "HIGH"  # LOW is escalated


def test_missing_permission_blocks():
    assert good_verdict(permission_score=20)["decision"] == aiv.DECISION_BLOCK


def test_goal_not_preserved_never_allowed():
    assert good_verdict(goal_preserved=False)["decision"] == aiv.DECISION_BLOCK


def test_deception_requires_approval():
    v = good_verdict(deception_signals=["exploits literal wording"])
    assert v["decision"] == aiv.DECISION_APPROVAL


def test_unverified_evidence_is_insufficient():
    v = good_verdict(evidence_required=True, evidence_sufficient=False)
    assert v["decision"] == aiv.DECISION_INSUFFICIENT
    assert v["requires_human_approval"] is True


def test_ambiguity_and_scope_creep_escalate():
    assert good_verdict(ambiguities=["'good seat'"])["decision"] == aiv.DECISION_APPROVAL
    assert good_verdict(scope_creep=["buys upgrade"])["decision"] == aiv.DECISION_APPROVAL
    assert good_verdict(counterfactual_user_would_accept="NO")["decision"] == aiv.DECISION_APPROVAL


# --- consensus fingerprint ----------------------------------------------

def test_fingerprint_ignores_prose_but_not_decision():
    a = good_verdict(reason="cheap direct flight")
    b = good_verdict(reason="totally different wording", intent_alignment_score=95)
    assert aiv.verdicts_agree(a, b)  # same 80-99 band, same decision
    c = good_verdict(hard_constraint_violated=True)
    assert not aiv.verdicts_agree(a, c)


def test_fingerprint_band_boundary():
    a = good_verdict(intent_alignment_score=79, ambiguities=["x"])
    b = good_verdict(intent_alignment_score=80, ambiguities=["x"])
    assert not aiv.verdicts_agree(a, b)


# --- history / audit -----------------------------------------------------

def test_behavioral_analysis_flags_drift():
    prev = [{"decision": "ALLOW", "intent_alignment_score": s} for s in (95, 85, 70)]
    out = aiv.behavioral_analysis(prev, good_verdict(intent_alignment_score=40))
    assert "goal drift" in out["flags"]
    assert "sudden behavioral change" in out["flags"]


def test_alignment_history_counts():
    recs = [{"decision": "ALLOW", "intent_alignment_score": 90},
            {"decision": "BLOCK", "intent_alignment_score": 10}]
    h = aiv.alignment_history(recs)
    assert h["verified_decisions"] == 2
    assert h["decision_counts"]["BLOCK"] == 1
    assert h["mean_alignment_score"] == 50


def test_decision_hash_is_deterministic():
    v = good_verdict()
    rec = {"intent_id": "intent-1", "intent_version": 1, "intent_spec_hash": "a",
           "action_hash": "b", "verdict": v, "timestamp": "t", "round": 0}
    assert aiv.decision_record_hash(rec) == aiv.decision_record_hash(dict(rec))
    assert len(aiv.decision_record_hash(rec)) == 64


def test_demo_scenarios_cover_every_decision():
    expected = {s["expected"] for s in aiv.DEMO_SCENARIOS.values()}
    assert set(aiv.DECISIONS) <= expected | {aiv.DECISION_APPROVAL}
    assert len(aiv.DEMO_SCENARIOS) >= 6
