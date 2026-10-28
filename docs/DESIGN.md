# Agent Intent Verifier — design

An onchain decentralized judge that decides whether an autonomous agent's
proposed action is faithful to a human's *intent*, not merely whether the
transaction is technically valid.

## Execution split

```text
                        verify_action(...)          <- transaction
                                |
          +---------------------+---------------------+
          |  DETERMINISTIC (identical on all nodes)   |
          |  - input validation, empty checks         |
          |  - intent version resolution              |
          |  - history digest assembly                |
          +---------------------+---------------------+
                                |
                    gl.vm.run_nondet(leader, validator)
                                |
      +-------------------------+--------------------------+
      | NON-DETERMINISTIC block (runs on leader AND on      |
      | every validator, independently)                     |
      |  1. intent text  -> Intent Specification (LLM)      |
      |  2. evidence URLs -> gl.nondet.web.render           |
      |  3. structured judgement of the action (LLM, JSON)  |
      |  4. deterministic normalization + escalation policy |
      +-------------------------+--------------------------+
                                 |
                  validator compares SEMANTIC FINGERPRINT
                  (decision, risk, hard flags, score band)
                                 |
                     agreement -> state write; disagreement -> no write

Scores are quantized to their band representative (10/30/50/70/90) inside the
non-deterministic block, before fingerprinting and storage. Validators agree
on the band, so only the band value is ever persisted: every later consumer
(behavioural drift, alignment history, audit) sees exactly the value the
validators agreed on, never a leader-only exact score.
```

The frontend, the caller, and any single model can never set the outcome: the
verdict enum is produced inside consensus and then re-checked by deterministic
policy code before storage.

## Intent Specification

Stage 1 converts natural language into a strict structure, validated by
`normalize_intent_spec`:

`primary_objective`, `required_conditions`, `forbidden_conditions`,
`permission_boundaries`, `quantitative_limits`, `preferences`,
`ambiguous_terms`, `critical_assumptions`.

## Checks performed on the action

Intent alignment · permission · constraints · hidden consequences · ambiguity ·
reasoning verification · evidence verification · goal preservation · scope creep ·
conflict detection · deception / loophole exploitation · counterfactual intent
test · intent boundary map · behavioural consistency.

### Counterfactual intent test

"If the user clearly understood that the agent would perform this exact action
and its consequences, would the user reasonably consider it consistent with
their original instruction?" — answered `YES` / `NO` / `UNCLEAR` and used as a
**signal**: anything other than `YES` prevents a bare `ALLOW`, it never
manufactures a `BLOCK` on its own.

### Intent boundary map

Every judgement returns four buckets — `clearly_authorized`,
`reasonable_interpretation`, `ambiguous`, `clearly_unauthorized` — e.g. for
"buy the cheapest flight under $500": buying a $412 direct fare is clearly
authorized; a $480 fare with one stop may be a reasonable interpretation;
adding a $60 seat upgrade is ambiguous; a $700 business fare is clearly
unauthorized.

## Deterministic escalation policy

The model proposes; this table decides. It can only make the outcome stricter:

| Condition | Effect |
| --- | --- |
| hard constraint violated, or constraint score < 40 | `BLOCK` |
| permission missing, or permission score < 40 | `BLOCK` |
| underlying objective undermined | never `ALLOW` |
| deception / loophole signals present | at least `REQUIRE_APPROVAL` |
| evidence required but unverified | `INSUFFICIENT_EVIDENCE` |
| ambiguity, alignment < 75, scope creep, weak reasoning, failed counterfactual | `REQUIRE_APPROVAL` |
| behavioural drift flags against verified history | at least `REQUIRE_APPROVAL` |

`requires_human_approval` is derived, never model-provided.

## Result shape

```json
{
  "decision": "ALLOW | REQUIRE_APPROVAL | BLOCK | INSUFFICIENT_EVIDENCE",
  "intent_alignment_score": 0,
  "permission_score": 0,
  "constraint_compliance_score": 0,
  "reasoning_quality_score": 0,
  "evidence_support_score": 0,
  "risk_level": "LOW | MEDIUM | HIGH | CRITICAL",
  "violated_rules": [], "ambiguities": [], "hidden_consequences": [],
  "evidence_used": [], "scope_creep": [], "conflicts": [], "deception_signals": [],
  "intent_boundary": {"clearly_authorized": [], "reasonable_interpretation": [],
                      "ambiguous": [], "clearly_unauthorized": []},
  "counterfactual_user_would_accept": "YES | NO | UNCLEAR",
  "behavioral_consistency": {"flags": [], "history_size": 0},
  "requires_human_approval": false,
  "policy_escalations": [],
  "explanation": "User wanted -> Agent proposed -> Evidence -> Conflict -> Decision",
  "validator_consensus": {"result": "AGREED", "fingerprint": {}},
  "reason": ""
}
```

## Auditability and privacy

Stored per decision: intent id + version + intent hash, the derived intent
specification, action text and its hash, a **hash** of the agent's reasoning,
evidence URLs, the verdict, timestamp (`gl.message_raw['datetime']`), round
(`initial` / `challenge` / `demo`), parent decision, submitter, and a
`decision_hash` over the auditable core. Raw reasoning bodies and free-form
private payloads are never persisted.

## Authorization for history writes

Writes to an agent's behavioural history are bound to the caller:

| `verify_action` / `challenge_decision` caller | Basis |
| --- | --- |
| The agent itself (transaction sender = `agent_address`) | `agent` |
| The owner of the intent being judged | `intent_owner` |
| A delegate the agent explicitly granted via `grant_agent_authority` | `delegated` |

Any other caller is rejected, so no untrusted party can append records that
later influence this agent's verdicts through behavioural drift or the
alignment history. Only the agent itself may grant or revoke delegate
authority. The authorization basis is stored on every decision record
(`authority`), included in the `decision_hash`, and published through
`get_authorization` / `get_policy`. Built-in demo scenarios only ever write
to synthetic `demo-agent-*` identities.

## Challenge / appeal

`challenge_decision` re-runs the whole non-deterministic evaluation with the
counterargument and new evidence injected, stores it as a **new** record, links
it to the parent, and leaves the original decision byte-for-byte intact. Only
the intent owner, the judged agent, or a delegate granted by that agent may
file a challenge. Both original and challenge are visible through
`get_audit_trail`.

## Intent versioning

`register_intent` creates version 1; `amend_intent` appends an
independently hashed version. `verify_action(intent_id, intent_version, ...)`
judges against the exact version (`0` = latest), so a decision can always be
replayed against the instructions that were in force.

## Trust signal

`get_agent_alignment_history` returns decision counts, mean alignment, a recent
window, the last decisions and accumulated behavioural flags — an *alignment
history* with an explicit caveat, deliberately not one permanent reputation
number. Behavioural change is evidence, never an automatic rejection.
