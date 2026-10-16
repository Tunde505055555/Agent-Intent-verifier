# Agent Intent Verifier

**A GenLayer Intelligent Contract that acts as an onchain, decentralized judge of whether an autonomous AI agent's proposed action actually matches what the human intended.**

## Brief description

AI agents increasingly act on our behalf: booking travel, trading, buying things. The dangerous failure is not a crash. It's an agent that does something that *technically* follows the instruction but betrays its spirit (an "upgrade" nobody asked for, selling a position you said never to sell, exploiting a loophole in your wording).

Agent Intent Verifier is a reusable primitive. A user registers their intent in natural language. Before acting, an agent submits its proposed action, its reasoning, and its evidence. GenLayer validators then reach **consensus** on one of four verdicts:

| Decision | Meaning |
|---|---|
| `ALLOW` | Clearly aligned, within permissions, evidence supports it |
| `REQUIRE_APPROVAL` | Ambiguous, scope creep, weak reasoning, or possible loophole: ask the human |
| `BLOCK` | Violates a hard constraint, exceeds permissions, or undermines the goal |
| `INSUFFICIENT_EVIDENCE` | Relies on claims that could not be verified |

Every decision is stored with scores, an explanation, a hash, and an audit trail, and can be challenged (appealed) with new evidence.

## Package contents

```
agent-intent-verifier/
├── contracts/agent_intent_verifier.py   # the Intelligent Contract (GenVM v0.2.16)
├── tests/
│   ├── conftest.py                      # stubs the genlayer SDK for offline testing
│   └── test_deterministic_layer.py      # 17 unit tests of the deterministic layer
├── docs/ARCHITECTURE.md                 # data flow, storage, and consensus deep dive
└── README.md
```

No frontend or web files are included.

## How it works

The contract strictly separates two layers.

**1. Non-deterministic layer** (only inside `gl.vm.run_nondet`)
- Turns the natural-language intent into a structured **Intent Specification** (objective, required/forbidden conditions, permission boundaries, quantitative limits, ambiguous terms).
- Optionally fetches web evidence with `gl.nondet.web`.
- Asks the LLM for a structured verdict: five 0–100 scores (alignment, permission, constraint compliance, reasoning quality, evidence support), risk level, violated rules, scope creep, deception signals, a counterfactual test ("would the user accept this?"), and an intent boundary map.

**2. Deterministic layer** (plain Python, identical on every validator)
- `normalize_verdict` / `normalize_intent_spec`: enforce enums, clamp scores, fix list shapes, and recover JSON from messy model output. Malformed output degrades safely to `REQUIRE_APPROVAL`.
- `apply_deterministic_policy`: hard rules the LLM **can never soften**:
  - hard constraint violated, or constraint score < 40 → `BLOCK`
  - missing permission, or permission score < 40 → `BLOCK`
  - goal not preserved → never `ALLOW`
  - deception signals → at least `REQUIRE_APPROVAL`
  - evidence required but unverified → `INSUFFICIENT_EVIDENCE`
  - ambiguity, alignment < 75, scope creep, weak reasoning, or failed counterfactual → `REQUIRE_APPROVAL`
  - behavioural drift flagged → at least `REQUIRE_APPROVAL`
- Hashing, indexing, state transitions, behavioural history, and alignment history.

## How consensus is used

`_consensus_judge` wraps the judgement in `gl.vm.run_nondet(leader_fn, validator_fn)`:

1. The **leader** validator runs the full pipeline (spec → evidence → LLM verdict → deterministic policy) and proposes a result.
2. Every other **validator independently re-runs the same pipeline** with its own LLM call. It doesn't just inspect the leader's answer.
3. A validator accepts only if its own verdict has the same **semantic fingerprint** as the leader's:
   ```
   decision, risk_level, requires_human_approval,
   hard_constraint_violated, permission_missing,
   evidence_sufficient, alignment_band (score // 20)
   ```
   Prose and small score differences are allowed to vary. What *matters* must match.
4. Only accepted consensus results are written to storage.

So one hallucinating model can't decide the outcome, and no client or frontend can decide it at all. Because the deterministic policy runs after the LLM on every validator, the safety rules are part of what validators agree on.

## Public interface

### Write methods
| Method | Purpose |
|---|---|
| `register_intent(intent_text, permissions, constraints, preferences, context)` | Store a new intent (version 1). Returns `intent_id`. |
| `amend_intent(intent_id, ...)` | Owner-only. Adds a new version, so later actions are judged against the right instructions. |
| `verify_action(intent_id, intent_version, agent_address, proposed_action, agent_reasoning, evidence_text, evidence_urls)` | Run consensus verification. `intent_version = 0` means latest. |
| `challenge_decision(decision_id, counterargument, extra_evidence, extra_evidence_urls)` | Appeal: runs a fresh evaluation, stores it as a new linked record, and keeps the original untouched. |
| `run_demo_scenario(name)` | Runs a built-in adversarial scenario end to end. |

### View methods
`get_intent`, `get_intent_versions`, `get_decision`, `get_decision_ids`, `get_intent_decisions`, `get_audit_trail`, `get_agent_alignment_history`, `list_demo_scenarios`, `get_policy`.

All public signatures use only `str`, `int`, `bool`, `list[str]`, and `dict[str, typing.Any]`, so they're compatible with the GenVM v0.2.16 schema parser.

## Built-in demo scenarios

| Scenario | Expected |
|---|---|
| `authorized_flight`: cheapest direct flight under $500, $412 found | `ALLOW` |
| `ambiguous_upgrade`: "good seat" → agent buys a $180 upgrade | `REQUIRE_APPROVAL` |
| `hard_constraint_violation`: "never sell AAPL, no leverage" → sells AAPL on margin | `BLOCK` |
| `unverifiable_claim`: needs an independent lab report, has only marketing copy | `INSUFFICIENT_EVIDENCE` |
| `loophole_exploitation`: obeys the wording, breaks the intent | `BLOCK` |
| `behavioral_drift`: an agent whose alignment degrades over time | escalated |

## Quick start

### Deploy (GenLayer Studio)
1. Open [GenLayer Studio](https://studio.genlayer.com).
2. Load `contracts/agent_intent_verifier.py` and deploy it (no constructor arguments).
3. Call `list_demo_scenarios`, then `run_demo_scenario("hard_constraint_violation")`.
4. Inspect the result with `get_decision(<decision_id>)` and `get_audit_trail(<decision_id>)`.

### Example flow
```text
register_intent("Book the cheapest direct flight LIS→BER on 12 Mar under $500",
                ["search flights","purchase one economy ticket up to $500"],
                ["direct only","total ≤ $500"], ["morning"], "")
  → { intent_id: "intent-1", version: 1 }

verify_action("intent-1", 0, "0xAgent…", "Buy TP1234 08:10, $412 total",
              "Cheapest direct under limit", "Fare quote …", [])
  → { decision_id, verdict: { decision: "ALLOW", intent_alignment_score: 92, … },
      explanation: "User wanted … -> Agent proposed … -> Decision: ALLOW", decision_hash }
```

### Run the tests
The tests cover the deterministic layer (normalization, policy escalation, consensus fingerprint, behavioural analysis, hashing). They run offline with a stubbed SDK:

```bash
pip install pytest
pytest -q tests
# 17 passed
```

## Design principles
- **The LLM proposes, the deterministic code decides.** Safety rules can't be talked out of.
- **Validators agree on meaning, not wording.**
- **History is evidence, not a verdict.** Behavioural drift escalates to a human and never auto-rejects on its own.
- **Auditable by default.** Decision hashes cover the auditable core with no raw private data. Challenges append records and never overwrite them.
- **An alignment history, not a reputation number.** Trust signals are per-agent windows over verified decisions.

## Use cases
Agent wallets and spending guards, DAO or treasury agent oversight, travel and shopping agents, trading bots with hard limits, and any agent framework that needs a neutral "is this what the user meant?" check before acting.

## License
MIT
