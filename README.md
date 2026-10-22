# Agent Intent Verifier

A GenLayer **Intelligent Contract** that acts as an onchain, decentralized
intent judge for autonomous agents. It turns a human's natural-language
instruction into a structured Intent Specification, then decides whether an
agent's proposed action is genuinely faithful to that intent — not merely
technically permitted.

Contract-only repository: no frontend, no server, no wallet UI. The contract
alone holds the logic, and validator consensus alone decides.

```text
contracts/agent_intent_verifier.py   the Intelligent Contract (single file)
tools/lint_contract.py               genvm-style lint + v0.2.16 schema check
tools/harness/                       offline runtime stub, loader, schema parser
tests/                               50 tests: schema, policy, 6 scenarios, lifecycle
examples/scenarios.json              ready-to-send calldata for every method
docs/DESIGN.md                       architecture, policy table, result shape
docs/SCHEMA_PARSER.md                how the v0.2.16 schema parser fails, and why
```

## Verify locally

```bash
python3 tools/lint_contract.py            # PASS, no findings
python3 tools/lint_contract.py --print-schema
python3 -m pytest tests -q                # 50 passed
```

## Deploy on GenLayer Studio

1. Open Studio, **Contracts → new file**, paste
   `contracts/agent_intent_verifier.py`. Keep the first line
   `# { "Depends": "py-genlayer:test" }` exactly as-is.
2. **Deploy** — the constructor takes no arguments.
3. Call `get_policy()` to confirm the deployment: it returns the decision enum,
   score range and the deterministic escalation rules.
4. Call `run_demo_scenario("authorized_flight")` … through
   `run_demo_scenario("behavioral_drift")` for the six built-in cases, then read
   `get_decision_ids()` and `get_audit_trail(<id>)`.

## What it does

**Stage 1 — Intent Specification.** Natural language becomes: primary
objective, required conditions, forbidden conditions, permission boundaries,
quantitative limits, preferences, ambiguous terms, critical assumptions.

**Stage 2 — Action verification.** Fourteen checks: intent alignment,
permission, constraints, hidden consequences, ambiguity, reasoning
verification, evidence verification, goal preservation, scope creep, conflict
detection, deception/loophole exploitation, counterfactual intent test, intent
boundary map, behavioural consistency against verified history.

**Result.** `ALLOW` / `REQUIRE_APPROVAL` / `BLOCK` / `INSUFFICIENT_EVIDENCE`
plus five 0–100 scores, risk level, violated rules, ambiguities, hidden
consequences, evidence used, scope creep, conflicts, deception signals, intent
boundary buckets, counterfactual answer, behavioural flags, derived
`requires_human_approval`, a plain-language explanation and the validator
consensus record.

## Why it is hard to game

* All subjective judgement happens inside `gl.vm.run_nondet`; the leader and
  every validator derive the specification and judge the action
  **independently**, and the write only lands when their semantic fingerprints
  (decision, risk, hard flags, score band) agree. One hallucinating model
  cannot set the outcome.
* A deterministic policy layer re-checks every verdict and can only make it
  stricter: a violated hard constraint or missing permission forces `BLOCK`,
  unverified required evidence forces `INSUFFICIENT_EVIDENCE`, ambiguity or
  deception forces `REQUIRE_APPROVAL`.
* Decision enum, score ranges, required fields and state transitions are pure
  deterministic Python — no floats, no clock, no randomness.
* The caller supplies only text. It cannot pass a decision, a score, or a
  bypass flag.

## Governance surface

* **Challenge / appeal** — `challenge_decision` re-runs the full evaluation with
  a counterargument and new evidence, stores a linked new record, and never
  mutates the original.
* **Intent versioning** — `amend_intent` appends an independently hashed
  version; every decision records the exact version and hash it was judged
  against.
* **Audit trail** — hash-chained decision records with timestamps; agent
  reasoning is stored as a hash, never as raw text.
* **Trust signal** — `get_agent_alignment_history` returns an alignment history
  with an explicit caveat, not a permanent reputation score. Behavioural change
  is treated as evidence for review, never as automatic rejection.

See `docs/DESIGN.md` for the full architecture and `docs/SCHEMA_PARSER.md` for
the schema constraints every public signature respects.
