# Failure Sequence Findings, Passes 1-2

Status: persisted findings for later prevention design. This is not a
guardrail proposal yet.

Source artifacts, local only:
- `out-atlas-cur/failure-sequences.jsonl`
- `out-atlas-cur/failure-sequences-summary.md`

Dataset:
- `out-atlas-cur`
- 346 episodes
- `episodes.json` sha256: `fe42c4686453b87af30fdd059ebcd8e6997415c12f411a63d09f4501bf313725`
- `source.snapshot.jsonl` sha256: `d031b790ddcf11dc4ab403361561151d31718ef312c9007d2c0d85b5d7682094`

The ignored `out-atlas-cur/` artifacts are not committed because they are
derived session outputs and may contain transcript-sensitive material. This
file preserves the durable findings and the provenance needed to re-check the
local artifacts later.

## Result

Nine records were mined:

| Classification | Count | Episodes |
|---|---:|---|
| confirmed | 4 | 309, 311, 318, 323 |
| could_not_determine | 2 | 26, 272 |
| contradicted | 3 | 2, 19, 181 |

Cost split:

| Cost type | Count | Meaning |
|---|---:|---|
| both | 2 | Waste plus shipped or real quality impact |
| waste | 2 | Review/draft churn without shipped defect |
| none | 5 | Hypothesis not proven as a failure sequence |

Confirmed tags:

| Tag | Count |
|---|---:|
| `REPEATED_FIX_LOOP` | 2 |
| `CONTRACT_DRIFT` | 2 |
| `TEST_THEATER` | 1 |
| `SUMMARY_DRIFT` | 1 |
| `MISSING_SOURCE_TRACE` | 1 |

## Headline Finding

The strongest confirmed pattern is not "the model worked too long" or "the
model assumed too much." The confirmed pattern is:

```text
model acts or claims completion
-> before tracing the actual source-of-truth contract
-> operator/reviewer contradicts the claim
-> model repairs
```

The source of truth that was missed varied by arc:
- the real ratio/math basis;
- the parser contract, not merely the parser path;
- whether a proof can fail closed;
- the actual diff, not a hard-coded PR-body summary.

## Seed Quality

Externally contradicted arcs were far higher yield than raw mechanical flags:

| Seed type | Confirmed sequences |
|---|---:|
| operator/reviewer contradiction anchored | 4/4 |
| mechanical-only seeds | 0/5 |

Implication: use mechanical flags for candidate generation only. Do not
headline raw counts as failures until a causal sequence is proven.

## Confirmed Sequences

### Episode 309: H-x12 Bad Math

Tags: `REPEATED_FIX_LOOP`, `CONTRACT_DRIFT`

Sequence:

```text
self-correction PR claimed a dateless week was about 12x low
-> actual code ratio is 12T/365
-> operator contradicted the math and scope
-> follow-up PR corrected the merged doc
```

Cost: both. A bad math claim shipped in a merged doc and required another
review round.

### Episodes 311, 316, 317: C1 Proof Not Fail-Closed

Tags: `TEST_THEATER`, `REPEATED_FIX_LOOP`

Sequence:

```text
model called C1 "proven"
-> proof artifact printed results and exited 0
-> then used bare assert guards
-> operator/reviewer noted assert disappears under python -O
-> proof was finally converted to explicit raise SystemExit guards
```

Cost: both. The "proof" claim required multiple rounds before it became a
durable proof.

### Episode 318: PR Body Diff Drift

Tags: `SUMMARY_DRIFT`

Sequence:

```text
model hard-coded diff counts in PR body
-> later diff changed
-> operator found PR body count did not match actual diff
-> PR body was changed to reference the plan table instead
```

Cost: waste. Description-only drift, no product defect.

### Episode 323: MCP Table vs Audit Parser Contract

Tags: `MISSING_SOURCE_TRACE`, `CONTRACT_DRIFT`

Sequence:

```text
model proposed keeping a compact MCP table and moving runbooks
-> checked that audits read CLAUDE.md
-> missed the parse contract those audits require
-> operator contradicted the audit-safe claim
-> draft changed to keep audited headings, tool names, port lines, and launch lines
```

Cost: waste. Caught in draft; no shipped defect. Potential quality risk: if
shipped, the change would have broken the MCP doc audits or produced false
confidence.

## Non-Confirmed Seeds

Mechanical-only seeds were deliberately not forced into findings:

- ep2 and ep19: contradicted. Long review arcs were healthy review depth, not
  waste.
- ep181: contradicted. Compaction resume re-fetched current head/diff before
  acting, so stale-state reaction did not hold.
- ep26: could not determine. Red PR was inherited; no in-window proof that the
  model caused the loop.
- ep272: could not determine for Class-2/Class-3 sequence. It remains a
  confirmed Class-1 near-miss (`bypassed_safety_or_destructive`) because
  `git push --force-with-lease` happened, but no downstream waste or quality
  loss was proven.

## Working Hypotheses For Next Mine

The next useful target is the "done-then-contradicted" loop:

```text
model says done/fixed/clean/proven/resolved
-> later operator/reviewer contradicts the same arc
-> inspect what evidence the model treated as sufficient
-> identify the missing step
```

Candidate missing-step tags:
- `missing_source_trace`
- `missing_negative_case`
- `missing_fail_closed_proof`
- `missing_surface_inventory`
- `stale_state_check`
- `check_appeasement`
- `patch_completion_not_verification`
- `summary_overclaim`
- `no_round2_stop_rule`

The question for prevention is not whether the model intended to overclaim.
The useful question is: what closure condition made the model believe "done"
before the source of truth had been checked?

## Preservation Notes

Use this document and `docs/failure-tag-taxonomy.md` when deciding whether to
codify preventative measures. Do not turn a single record into a durable rule.
Codify only after the same sequence recurs or has severe enough potential harm
to justify a process guard.
