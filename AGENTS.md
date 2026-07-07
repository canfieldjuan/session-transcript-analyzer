# AGENTS.md -- working rules for this repo

Rules a fresh session (human or model) must honor when changing this forensics tool.
The repo is `session-transcript-analyzer`; Atlas (and any analyzed repo) is a **read-only**
data source, queried via `gh` -- never modified.

## Forensics slices ship via branch + PR
Non-trivial changes go on a `claude/pr-<slice>` branch and open a PR ready for review
(fetch before push; never force-push). Do NOT commit non-trivial work straight to `main`.
Trivial fixes (typo, one-liner) may go direct, but when in doubt, branch.

## Contract first, reconstruct cold before "done"
Every non-trivial slice ships a `plans/PR-<Slice>.md` doc, contract-first:
1. **Root cause, not symptom** -- what is actually wrong and why.
2. **What a correct fix must touch and change.**
3. **What must NOT change** -- the modules and behaviors to leave alone.

Build to that contract (nothing unimplemented, nothing outside it). Before calling it done,
**reconstruct your own diff cold**: read it as if you did not write it, check every change
traces to the contract, everything the contract required appears, and nothing outside scope
moved -- cite `file:line`, lead with gaps, do not declare done while a gap stands.

## Evidence + honesty
- Three buckets only: **confirmed / contradicted / could_not_determine**; nothing confirmed
  without a citation.
- A **null result is a valid outcome** -- do not manufacture a pattern to fill an artifact.
- Reconstructed behavior is fact; cause/severity are soft assessments -- tag them, don't cache
  them as premises.

## Mechanics
- Run a **code-review agent** on new logic before merge; address findings.
- **No new deps** beyond `requirements.txt` (`anthropic`) -- prefer stdlib + the `gh` CLI.
- **Provenance:** stamp artifacts with their dataset + corpus pin (sha / query date / range).
- **Persistence (three tiers):** raw derived artifacts stay local under `out-*/` (gitignored,
  may hold sensitive material); a committed `docs/*.md` companion carries the durable findings
  + the pin; findings are mirrored to the tracking issue.
- Guards and proofs **fail closed** (`raise`, not `assert` -- `python -O` strips asserts).

## Layers (see docs/SESSION_FORENSICS_SPEC.md)
`parse.py` (extract) -> `detect.py` (mechanical candidates) -> `analyze.py` (adjudication) ->
`patterns.py` (durable patterns). `forward_link*.py` is the cross-time join alongside them.
Reuse a layer's extractor rather than forking it -- identical extraction across compared sets
is load-bearing.
