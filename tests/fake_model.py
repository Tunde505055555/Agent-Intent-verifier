"""
Deterministic stand-in for the validator LLM.

It answers the two prompt templates the contract issues (intent specification
and verdict) using keyed rules, so contract behaviour — especially the
deterministic escalation policy and consensus logic — can be tested without a
node or a live model. Real judgements come from validators onchain; this only
pins down how the contract *handles* model output.
"""

from __future__ import annotations

import json
import typing


def _spec(objective: str, **kwargs) -> dict[str, typing.Any]:
    spec: dict[str, typing.Any] = {
        "primary_objective": objective,
        "required_conditions": [],
        "forbidden_conditions": [],
        "permission_boundaries": [],
        "quantitative_limits": {},
        "preferences": [],
        "ambiguous_terms": [],
        "critical_assumptions": [],
    }
    spec.update(kwargs)
    return spec


BASE_VERDICT: dict[str, typing.Any] = {
    "decision": "ALLOW",
    "intent_alignment_score": 92,
    "permission_score": 96,
    "constraint_compliance_score": 95,
    "reasoning_quality_score": 88,
    "evidence_support_score": 90,
    "risk_level": "LOW",
    "violated_rules": [],
    "ambiguities": [],
    "hidden_consequences": [],
    "evidence_used": [],
    "scope_creep": [],
    "conflicts": [],
    "deception_signals": [],
    "hard_constraint_violated": False,
    "permission_missing": False,
    "evidence_required": False,
    "evidence_sufficient": True,
    "goal_preserved": True,
    "reasoning_supports_action": True,
    "counterfactual_user_would_accept": "YES",
    "counterfactual_note": "the action matches what the user asked for",
    "intent_boundary": {
        "clearly_authorized": [],
        "reasonable_interpretation": [],
        "ambiguous": [],
        "clearly_unauthorized": [],
    },
    "reason": "action is aligned with the stated objective",
}


def verdict(**overrides) -> dict[str, typing.Any]:
    out = json.loads(json.dumps(BASE_VERDICT))
    out.update(overrides)
    return out


VERDICT_RULES: list[tuple[str, dict[str, typing.Any]]] = [
    (
        "appeal-accepts",
        verdict(
            decision="ALLOW",
            intent_alignment_score=90,
            reason="new evidence shows the mandatory fee is waived for this rate",
        ),
    ),
    (
        "premium economy upgrade",
        verdict(
            decision="ALLOW",
            intent_alignment_score=68,
            ambiguities=["'good seat' does not clearly authorize a paid upgrade"],
            hidden_consequences=["$180 unplanned charge"],
            counterfactual_user_would_accept="UNCLEAR",
            intent_boundary={
                "clearly_authorized": ["select a free seat"],
                "reasonable_interpretation": ["choose an aisle/window seat"],
                "ambiguous": ["paid premium economy upgrade"],
                "clearly_unauthorized": ["business class purchase"],
            },
            reason="comfort was preferred but paid upgrades were never authorized",
        ),
    ),
    (
        "AAPL",
        verdict(
            decision="BLOCK",
            intent_alignment_score=22,
            permission_score=18,
            constraint_compliance_score=5,
            risk_level="CRITICAL",
            violated_rules=["never sell AAPL", "no leverage / margin borrowing"],
            hard_constraint_violated=True,
            permission_missing=True,
            goal_preserved=False,
            counterfactual_user_would_accept="NO",
            reason="the action breaks two explicit hard constraints",
        ),
    ),
    (
        "supplement",
        verdict(
            decision="INSUFFICIENT_EVIDENCE",
            intent_alignment_score=55,
            evidence_support_score=15,
            evidence_required=True,
            evidence_sufficient=False,
            evidence_used=["vendor marketing claim only"],
            ambiguities=["no independent lab report retrieved"],
            risk_level="HIGH",
            reason="purchase is conditional on lab certification that could not be verified",
        ),
    ),
    (
        "resort and city service fee",
        verdict(
            decision="ALLOW",
            intent_alignment_score=35,
            constraint_compliance_score=20,
            risk_level="HIGH",
            violated_rules=["effective nightly cost $259 exceeds $200", "not walking distance"],
            deception_signals=[
                "mandatory fee excluded from the quoted nightly rate",
                "'conference adjacent' claim contradicts 4.5 km distance",
            ],
            hard_constraint_violated=True,
            goal_preserved=False,
            counterfactual_user_would_accept="NO",
            reason="technically compliant nightly rate hides a mandatory fee",
        ),
    ),
    (
        "impression campaign",
        verdict(
            decision="ALLOW",
            intent_alignment_score=79,
            reasoning_quality_score=52,
            reason="spend stays under the cap and budget shifting is authorized",
        ),
    ),
]


class FakeModel:
    def __init__(self) -> None:
        self.calls = 0
        self.flip_after: int | None = None

    # -- prompt entrypoint --------------------------------------------------

    def __call__(self, prompt: str) -> dict[str, typing.Any]:
        self.calls += 1
        if "Intent Specification" in prompt and "primary_objective" in prompt:
            if "convert a human instruction" in prompt:
                return self._spec_for(prompt)
        return self._verdict_for(prompt)

    def render(self, url: str) -> str:
        if "invalid" in url:
            raise RuntimeError("dns failure")
        return f"page text for {url}"

    # -- internals ----------------------------------------------------------

    def _spec_for(self, prompt: str) -> dict[str, typing.Any]:
        if "AAPL" in prompt:
            return _spec(
                "rebalance the portfolio into index funds without touching AAPL",
                forbidden_conditions=["sell AAPL", "use leverage", "borrow on margin"],
                permission_boundaries=["buy orders", "sell non-AAPL holdings"],
            )
        if "good seat" in prompt:
            return _spec(
                "obtain a comfortable seat on an existing booking",
                ambiguous_terms=["good seat"],
                critical_assumptions=["no unexpected spending"],
            )
        if "lab report" in prompt:
            return _spec(
                "buy the supplement only if certified free of banned substances",
                required_conditions=["independent lab certification"],
            )
        if "hotel" in prompt:
            return _spec(
                "book the cheapest compliant hotel near the conference",
                quantitative_limits={"max_nightly_total": "200 USD"},
                forbidden_conditions=["exceed $200 per night all-in"],
            )
        if "ad budget" in prompt:
            return _spec(
                "maximise qualified signups under a $5,000 monthly cap",
                quantitative_limits={"monthly_spend": "5000 USD"},
            )
        return _spec(
            "book the cheapest direct flight within the stated budget",
            quantitative_limits={"max_total": "500 USD"},
            required_conditions=["direct flight", "12 March"],
        )

    def _verdict_for(self, prompt: str) -> dict[str, typing.Any]:
        for marker, payload in VERDICT_RULES:
            if marker in prompt:
                out = json.loads(json.dumps(payload))
                break
        else:
            out = verdict()
        if self.flip_after is not None and self.calls > self.flip_after:
            out["decision"] = "BLOCK"
            out["hard_constraint_violated"] = True
            out["intent_alignment_score"] = 5
        return out
