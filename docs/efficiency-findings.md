# Efficiency Findings -- Errors & Correction Loops (a faster-coder checklist)

Status: persisted findings for prevention. Not a guardrail proposal yet.

Source artifact, local only:
- `out-atlas-cur/errors-and-loops.jsonl`

Dataset:
- `out-atlas-cur`, 346 episodes
- `episodes.json` sha256: `fe42c4686453b87af30fdd059ebcd8e6997415c12f411a63d09f4501bf313725`
- plus 3 cross-session meta-errors from the mining session itself (flagged `cross_session`)

## The one habit with the highest ROI

**Spend the ~10 seconds to hit the source of truth before you assert or act** --
read the parser, compute the hash, run `git diff --numstat`, fetch the ref, grep for
what already exists. It is cheaper than one correction round, every time. Every pattern
below is a variant of skipping that step.

## The seven avoidable-rework patterns (ranked by rework cost)

Count provenance: the pre-scan distillation named six; the seventh (pattern 7, review
under-call) was surfaced by the residual finder angle (F) -- which is why the mine converged
at seven, not six.

1. **Verify the proxy, not the source of truth.** (dominant -- 4/6 of the last mine + H-x12
   + the hash mislabel this session + ep18/ep92). A green gate, a coherent idea, a file's
   existence, or a `print` stood in for the actual check.
   *Fix:* read the consuming code / compute the value / check the target -- not its proxy.

2. **Hard-coded volatile values drift.** diff-count 200/18, line numbers :14/:11, the
   `d031b790` hash typed this session, churn counts.
   *Fix:* never type a value a command derives; cite the source (`numstat`, `sha256`, the plan table).

3. **Iterate by prose without pinning the ref.** the CLAUDE.md draft loop (5 rounds), the
   audit-doc cascade (6 rounds).
   *Fix:* a **round-2 stop rule** -- pin the base SHA + reconstruct the consumers after round 1,
   not round 5.

4. **Act before syncing state.** push-before-pull -> rejected (this session); ep92 LGTM on the
   wrong dev's PR; ep141 forgot work that already existed.
   *Fix:* fetch / read current state (and confirm the target) before acting.

5. **Setup != verified-working.** the polling triggers (ep274) were configured, never proven to fire.
   *Fix:* prove the mechanism engages, not just that it is configured.

6. **Proofs that can't fail.** the C1 "proof" printed + exited 0; then `assert` stripped by `-O`.
   *Fix:* fail-closed -- `raise` / exit non-zero on drift.

7. **Under-call / rubber-stamp in review.** ep95, ep115, ep206 -- the second reviewer (Codex/agent)
   caught a real finding I disputed or missed.
   *Fix:* run the boundary / second-side probe and reconcile against the other reviewer BEFORE the verdict.

## Counter-moves that already work (do more of these)

- **Verify-before-publish** (ep216): verifying caught a false MAJOR *before* I posted it. Zero cost.
- **Probe-before-claim** (ep178): a probe surfaced the issue before it shipped.

These are the positive form of pattern 1 -- the source-of-truth check, run early, costs seconds and
prevents the whole loop.

## The reflexive proof (it is live, not historical)

Four of these fired in the act of mining this very session: the hash mislabel (#1/#2),
push-before-pull (#4), the ep307 mis-seed (#1), and -- caught in review -- the step-3
reconstruction asserting a jsonl row (ep178) it never read (#1, a summary-overclaim inside
the overclaim-catcher). The patterns are not in the past tense.

## How we decide a mine is "done" (saturation protocol)

Not "one search angle is swept" -- that is the proxy trap (pattern 1) applied to the mining itself.
A mine is dry only when:

- **Convergence, not coverage:** >= 2 consecutive *independent* finder angles surface zero new.
  Angles used here: operator-contradiction turns, completion-claim adjacency, self-correction
  acknowledgments, tool-error recovery, edit-thrash, residual pass.
- **Pattern-level vs instance-level:** the actionable unit is the *pattern*. This mine reached
  pattern-level convergence at 7 (angles D/E added 0 new, angle F added instances + 1 pattern then
  no more). Instance-level is NOT saturated -- ~17 self-correction episodes outside the records
  remain; they are instances of the 7 classes, not new classes.
- **Name the residual:** every net has a blind spot. This one cannot catch silently self-caught
  errors, soft-signal contradictions, or non-acknowledgment semantic misses. Silence != zero.
- **Reproducibility caveat:** the convergence verdict here is artifact-recorded from a one-off
  angle scan over the pinned `episodes.json`, not a committed rerunnable proof. Re-derive it by
  re-running the six angle scans over the pinned dataset; until a scan script is persisted, treat
  the recorded verdict as evidence, not independent proof.

## Preservation notes

Three-tier persistence: raw `.jsonl` local (gitignored `out-*/`), this doc committed, same content
on GitHub issue #1. Re-check the local `errors-and-loops.jsonl` against the pinned `episodes.json`
sha256 above.
