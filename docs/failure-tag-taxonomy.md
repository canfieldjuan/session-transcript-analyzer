# Failure Tag Taxonomy

Status: discovery taxonomy, not a fix plan.

Use these tags after raw transcript/tool evidence is available. They are
adjudication labels for recurring Claude failure modes, not first-pass detector
verdicts and not automatic guardrails.

## Pipeline Placement

1. Raw transcript / PR evidence
   Source of truth: episode text, tool output, git/GitHub state, diff, tests.

2. Class-1 mechanical flags
   Cheap candidate generation, such as `no_verification`,
   `bash_error_ignored`, `bypassed_safety_or_destructive`, and
   `model_assumed_without_asking`.

3. Class-2 / Class-3 adjudication tags
   Apply the tags below only after comparing the episode or PR to evidence.

4. Pattern report / durable rule
   Convert a tag into a guardrail only after repeated, verified occurrences.

## Canonical Tags

### CONTRACT_DRIFT

Producer, consumer, docs, tests, or PR claims disagree about shape, fields,
basis, behavior, or source of truth.

Evidence to look for:
- docs say one shape, parser expects another;
- backend emits fields the frontend does not accept;
- generated file is stale against the producer contract;
- PR body or plan claims differ from the actual diff.

### SCOPE_EXPANSION

The agent changes files or surfaces beyond the declared fix without first
updating scope and proving necessity.

Evidence to look for:
- file list grows during a repair pass;
- a narrow check failure turns into unrelated doc/code churn;
- added surfaces are not named in the plan/body.

### STALE_STATE_REACTION

The agent acts on old PR, CI, review, git, or branch state instead of fetching
current state first.

Evidence to look for:
- comments on green/red/merged/reviewed/clean status using an old SHA;
- ignores a newer push;
- reviews or merges against a non-current head.

### TEST_THEATER

Tests exist but do not prove the claimed behavior.

Evidence to look for:
- snapshots preserve current output without a mutation/negative case;
- tests assert mock calls instead of observable behavior;
- happy-path-only coverage for a guard or checker;
- tests are not enrolled in CI;
- test could not fail for the defect it claims to cover.

### HAPPY_PATH_PATCH

The agent patches the obvious passing or cited case without proving negative,
boundary, or adversarial cases.

Evidence to look for:
- only the reviewer-provided input is covered;
- no empty/malformed/duplicate/missing-field case;
- fix handles the visible example but leaves the class unproven.

### OVERBROAD_REFACTOR

The agent rewrites architecture or shared abstractions when a narrower correct
fix would solve the issue.

Evidence to look for:
- broad shared-helper extraction during a narrow bug fix;
- multiple unrelated callers migrated to satisfy one failing case;
- large structural diff where source-of-truth tracing would have been enough.

### MISSING_SOURCE_TRACE

A claim, fix, or test is not traced back to the actual source of truth: parser,
producer, schema, allowlist, generated file, route, database, or GitHub state.

Evidence to look for:
- claim cites memory/docs while code is the real consumer;
- test mirrors generated output by hand;
- fix is made before reading the parser/gate/producer.

### CHECK_APPEASEMENT

The agent changes code/docs to satisfy a check or review wording without
understanding or fixing the underlying cause.

Evidence to look for:
- change matches the error string but not the defect;
- review comment is patched literally with no root-cause proof;
- adjacent failure appears immediately after the claimed fix.

### ASYNC_ORDER_VIOLATION

The agent does steps in an impossible or wrong async order.

Evidence to look for:
- asks for check results before pushing;
- comments on CI before a fresh check/webhook result exists;
- fixes before the latest verdict exists;
- talks merge-readiness before verifying current head and review state.

### UNRELATED_CLEANUP

Drive-by formatting, cleanup, doc polish, renames, or refactors not required
for the stated failure.

Evidence to look for:
- harmless-but-noisy file churn;
- unrelated prose cleanup in a blocker repair;
- metadata changes not tied to the fix.

### REPEATED_FIX_LOOP

The same failure class recurs after claimed fixes; the agent keeps patching
instead of re-deriving root cause.

Evidence to look for:
- same finding reappears after "fixed";
- fix creates a new adjacent contradiction;
- three or more correction rounds on the same narrow issue.

### SUMMARY_DRIFT

Final answer, PR body, plan, or handoff claims more than the diff or evidence
supports.

Evidence to look for:
- says "gate-safe" before the gate ran;
- says "repo-real" for an unmerged draft or memory-only rule;
- overstates fixed scope, test coverage, or current GitHub state.

### INCOMPLETE_SURFACE_UPDATE

One output or consumer surface is updated while another required surface is
missed.

Evidence to look for:
- report updated but PDF/email/API/UI unchanged;
- backend changed but generated frontend contract not updated;
- producer changed but snapshot/example/docs/parser still use old shape.

## Collision Rules

- Use `CONTRACT_DRIFT` when two artifacts disagree.
- Use `INCOMPLETE_SURFACE_UPDATE` when the issue is missed propagation.
- Use `SCOPE_EXPANSION` for extra breadth.
- Use `OVERBROAD_REFACTOR` only when the extra breadth is structural or
  architectural.
- Use `UNRELATED_CLEANUP` for harmless-but-noisy drive-bys.
- Use `CHECK_APPEASEMENT` when the agent is chasing a check/review symptom.
- Use `MISSING_SOURCE_TRACE` when the agent never tied the claim to ground
  truth.

## Current Use

Use this taxonomy to label confirmed transcript/PR failures. Do not treat a tag
as confirmed without cited evidence from transcript text, tool output, git,
GitHub, or code.

## Event Sequence Model

The tags are less important than the sequence of events that led to waste or a
quality failure. Every confirmed finding should capture the chain, not just the
label.

Use this shape:

```text
Trigger -> model decision -> missed source/evidence -> action taken ->
failure signal -> repair behavior -> outcome
```

### Waste Sequence

Use when the main harm is time, churn, repeated review rounds, or unnecessary
work.

Common chain:

```text
Ambiguous/stale/narrow trigger
-> model acts before source trace or latest verdict
-> check/review contradicts the action
-> model patches the visible symptom
-> another adjacent contradiction appears
-> scope expands or same approach repeats
-> extra review rounds / wasted commands / noisy docs / operator intervention
```

Typical tags:
- `STALE_STATE_REACTION`
- `ASYNC_ORDER_VIOLATION`
- `CHECK_APPEASEMENT`
- `REPEATED_FIX_LOOP`
- `SCOPE_EXPANSION`
- `UNRELATED_CLEANUP`

### Quality-Failure Sequence

Use when the main harm is wrong behavior, false confidence, missed output
surface, or a PR that should not have merged.

Common chain:

```text
Narrow fix request or PR claim
-> model reads diff/claim but not source-of-truth consumer
-> implementation or review covers the happy path
-> secondary surface / negative case / contract edge is missed
-> tests pass but do not prove the real invariant
-> shipped output, docs, or PR summary overstates correctness
```

Typical tags:
- `MISSING_SOURCE_TRACE`
- `HAPPY_PATH_PATCH`
- `TEST_THEATER`
- `CONTRACT_DRIFT`
- `INCOMPLETE_SURFACE_UPDATE`
- `SUMMARY_DRIFT`

### Sequence Evidence Required

For each confirmed sequence, record:

- starting trigger: user prompt, PR review, CI failure, or merge state;
- first wrong irreversible or costly move;
- source of truth that should have been read first;
- evidence that exposed the failure;
- whether repair changed hypothesis or repeated the same approach;
- final cost: extra rounds, extra files, wrong output, stale claim, or missed
  blocker.

Do not mark a sequence confirmed just because one tag appears. A sequence needs
at least two linked events and an observable cost.
