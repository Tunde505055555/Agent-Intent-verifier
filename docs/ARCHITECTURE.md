# Architecture

## Verification pipeline
```text
verify_action / challenge_decision
        │
        ▼
_run_verification ──► _consensus_judge ──► gl.vm.run_nondet(leader_fn, validator_fn)
                                              │
              ┌───────────────────────────────┴───────────────────────────────┐
              │ _judge(request)  (runs on leader AND on each validator)        │
              │   1. _derive_intent_spec   LLM → normalize_intent_spec         │
              │   2. _fetch_evidence       gl.nondet.web (optional, ≤4 URLs)   │
              │   3. LLM verdict           → normalize_verdict                 │
              │   4. apply_deterministic_policy  (hard escalation rules)       │
              └───────────────────────────────┬───────────────────────────────┘
                                              │
                validator_fn: verdicts_agree(leader, mine) via verdict_fingerprint
                                              │
        ▼ (accepted only)
behavioral_analysis (deterministic) → build_explanation → decision_record_hash
        │
        ▼
storage: decisions, intent_decisions index, agent history
```

## Deterministic vs non-deterministic boundary
| Step | Layer |
|---|---|
| Intent → structured spec | non-deterministic (LLM) |
| Web evidence fetch | non-deterministic (`gl.nondet.web`) |
| Alignment / deception / drift judgement | non-deterministic (LLM) |
| Enum, score and shape validation | deterministic |
| Escalation policy | deterministic |
| Fingerprint comparison | deterministic |
| Behavioural flags, alignment history | deterministic |
| Hashing, IDs, storage | deterministic |

## Consensus fingerprint
Two verdicts agree when these fields are equal:
`decision`, `risk_level`, `requires_human_approval`, `hard_constraint_violated`,
`permission_missing`, `evidence_sufficient`, `intent_alignment_score // 20`.

Why coarse: LLMs never produce byte-identical prose, so exact-match consensus would never be reached. Bucketing scores into bands of 20 tolerates normal variance while still rejecting a leader whose judgement is materially different.

## Storage
- `TreeMap[str, str]` tables holding canonical JSON: intent versions, decisions, per-intent decision indexes, per-agent records.
- `u256` counters for intent and decision IDs.
- Intents are versioned and owner-gated (`amend_intent` checks `gl.message.sender_address`).
- Challenges create new records linked by `parent_decision_id`. Originals keep a `challenges` list and are never rewritten in substance.

## Failure modes handled
- Model returns prose or fenced JSON → `parse_model_json` recovers it, or returns `{}`.
- Unknown decision or risk enum → safe default (`REQUIRE_APPROVAL`, `MEDIUM`).
- Out-of-range or non-numeric scores → clamped to 0..100.
- Unreachable evidence URL → evidence marked unverified, which leads to `INSUFFICIENT_EVIDENCE` if it was relied on.
- Leader returns an error → `validator_fn` rejects it.
