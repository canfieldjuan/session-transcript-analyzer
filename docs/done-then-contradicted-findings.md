# Done-Then-Contradicted Findings (Premature-Closure Mine)

Status: persisted findings for later prevention design. Not a guardrail proposal yet.

Source artifact, local only:
- `out-atlas-cur/done-then-contradicted.jsonl`

Dataset:
- `out-atlas-cur`
- 346 episodes
- `episodes.json` sha256: `fe42c4686453b87af30fdd059ebcd8e6997415c12f411a63d09f4501bf313725`
- `source.snapshot.jsonl` sha256: `d031b790ddcf11dc4ab403361561151d31718ef312c9007d2c0d85b5d7682094`

The ignored `out-atlas-cur/` artifacts are not committed (derived session outputs,
may contain transcript-sensitive material). This file preserves the durable findings
and the provenance needed to re-check the local artifact later.

## What this mine hunts

Not the word "done." The **premature-closure condition**: what made the model think it
had enough evidence when it did not. `confirmed` requires a completion claim + a later
operator/reviewer contradiction + an observable cost.

## Result

6 records:

| Classification | Count | Windows |
|---|---:|---|
| confirmed | 5 | 272-274, 308-309, 311-317, 317-318, 320-327 |
| contradicted | 1 | 276-279 (#1961 red = a legitimate CI re-fire) |

Missing-step tags (confirmed):

| tag | count |
|---|---:|
| `patch_completion_not_verification` | 2 |
| `missing_source_trace` | 2 |
| `missing_fail_closed_proof` | 1 |
| `summary_overclaim` | 1 |
| `no_round2_stop_rule` | 1 |

Cost split: `both` 2, `waste` 3, `none` 1.

## Headline finding

Every confirmed closure rested on the **cheaper proxy** instead of the source of truth:

- CI-green / mergeState-CLEAN treated as done (#2002) -> the doc **content** (the math, the scope) was unverified; no gate checks it.
- trigger configured treated as polling-works (ep274) -> the mechanism was never verified to **fire**.
- audit reads CLAUDE.md treated as gate-safe (MCP) -> the audit **parse contract** was unread.
- script reproduced once treated as proven (C1) -> the proof could not **fail**.
- number typed into the PR body treated as summary-correct -> it was not derived from `git diff --numstat`.

Unifying condition: a proxy (a green gate / a config action / a file-read / one reproduction /
a typed number) was substituted for the source-of-truth check.

## Confirmed sequences

### Polling set-up treated as working (window 272-274)
claim: polling is set up and running. used: the setup ACTION (created the triggers).
missing: verification the triggers actually FIRE. contradiction: operator ep274
("im pretty sure your not polling anything"); self-admission same episode.
repair: prove it empirically, then drove the watching live. rounds 1. cost waste.
tags: `patch_completion_not_verification`.

### #2002/#2004 -- H-x12 bad math (window 308-309)
claim: merged #2002 "all gates green, CLEAN, 0 threads". used: CI gate status + mergeState.
missing: the doc math (dateless ratio is `12T/365`, not a flat "12x too low") and scope; no
gate checks doc content. contradiction: operator ep309. repair: changed hypothesis (#2004,
traced `faq_deflection_report.py:3226-3234`). rounds 2. cost both.
tags: `patch_completion_not_verification`, `missing_source_trace`.

### C1 proof not fail-closed (window 311-317)
claim: "proven". used: one reproduction of the numbers. missing: a proof must be
fail-closed (script printed + exit 0; later `assert` guards stripped by `python -O`).
contradiction: operator ep311 -> ep316 -> ep317. repair: patched the symptom twice (seal,
then assert) before addressing the class (round 3: `raise SystemExit`). rounds 3. cost both.
tags: `missing_fail_closed_proof`, `no_round2_stop_rule`.

### PR-body diff drift (window 317-318)
claim: "pushed clean" with a typed "200 ins / 18 del". used: a hand-written split.
missing: the actual `git diff --numstat` (204/14 = 218). contradiction: operator ep318.
repair: removed all hard-coded counts from the PR body -> point to the plan table. rounds 1.
cost waste. tags: `summary_overclaim`.

### MCP table vs audit parse contract (window 320-327)
claim: "gate-safe / table stays, no audit change". used: verified the audits READ CLAUDE.md.
missing: the audit PARSE CONTRACT (`### <Name> MCP Server (N tools)` headings + backticked
tool names + `ATLAS_MCP_*_PORT=`/`--sse` lines; a markdown table satisfies none). contradiction:
operator ep323 -> ep327. repair: read the three parsers directly, keep the audited sections.
rounds 3. cost waste (potential: would have broken the MCP audits if shipped).
tags: `missing_source_trace`.

## Non-confirmed

### ep276 "1961 is red" -- contradicted
A legitimate CI re-fire (live-reconciliation flips on a new push / Codex re-review), not a
false "done." I acknowledged it immediately and engaged the reconcile loop; merged only on
verified-green when directed (ep279). No premature closure -> not forced into a confirmed.

## Preservation notes

Three-tier persistence, same as passes 1-2: the raw `.jsonl` stays local (gitignored under
`out-*/`), this doc is committed, and the same content is posted to GitHub issue #1. Re-check
the local `done-then-contradicted.jsonl` against the pinned `episodes.json` sha256 above.
