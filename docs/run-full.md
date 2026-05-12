# Full-session run (Layers 2 + 3)

Green-lit after pass-2 verification. The per-episode analyzer is calibrated;
this doc covers the full 307-episode run and the cross-episode pattern
report.

---

## 0. Pull latest

```bash
git pull
```

Changes since pass 2:
- `analyze.py`: removed the silent no-op `cache_control` block (system
  prompt is below Sonnet's 1024-token cache threshold so it was free
  drift, not free savings). Token-usage fields in summary trimmed
  accordingly.
- New `patterns.py` — Layer 3, cross-episode pattern report on Opus 4.7.
- New `docs/run-full.md` — this file.
- `docs/recap.md` section 5 updated.

No parsing or rendering changes since pass 2, so **you do not need to
re-run `parse.py` or wipe `out/analysis.jsonl`.** The 23 records from
pass 2 are still valid and `--resume` will pick up where you left off.

---

## 1. Analyze all remaining episodes

```bash
python3 analyze.py --first 1000 --resume
```

`--first 1000` is a generous upper bound; combined with `--resume`, the
tool will analyze every not-yet-analyzed episode and stop. For the Atlas
session (307 episodes, 23 already done) that's ~284 fresh API calls.

**Expected cost:** ~$5.50 (extrapolating from $0.020/episode in pass 2).

**Expected runtime:** ~15-25 minutes wall-clock, sequential. The progress
log shows one line per episode as it completes.

**What can go wrong:**
- API rate limits → SDK retries automatically; if it gives up on one
  episode, that one is logged FAILED and skipped, the rest continues.
- Network blip → same as above.
- Crash → analysis.jsonl is flushed per-line, so re-running with
  `--resume` picks up exactly where it stopped.

After it finishes:

```bash
cat out/analysis-summary.md
wc -l out/analysis.jsonl   # should be ~280-300 (depending on skips)
```

---

## 2. Sanity-check the full run

Before spending Opus tokens on Layer 3, glance at the summary:

- [ ] `did_model_verify` distribution: no degenerate (e.g. 99% yes) shape.
- [ ] Top risk_flags: 3-6 names dominate. Long tail is noise but should
      not exceed ~30% of total flag firings.
- [ ] No more than ~5% of selected episodes ended up as SKIPPED (missing
      required fields). If higher, the model is choking on something —
      report back.

If anything looks degenerate, stop and report before running Layer 3.

---

## 3. Pattern report (Layer 3)

```bash
python3 patterns.py --tz America/Los_Angeles   # or your IANA TZ
```

If you skip `--tz`, it uses system local time. The TZ matters for the
"time-of-day correlation" section — if your transcripts span machines in
different timezones, pick the TZ where you actually do the coding.

Dry-run first if you want to eyeball the assembled prompt before spending
Opus tokens:

```bash
python3 patterns.py --tz America/Los_Angeles --dry-run | less
```

**Expected cost:** $2-4 for ~300 records (Opus 4.7 list prices).

**Expected runtime:** 30-90 seconds for one Opus call.

Output: `out/patterns-report.md`.

---

## 4. Read the report

The report has 9 sections, in this order:

1. **Headline finding** — if you only read one line, this is it.
2. **The user's worst recurring habit** — *your* costliest pattern.
3. **The model's worst recurring behavior** — what the assistant does wrong.
4. **Top risk-flag co-occurrence pairs** — which problems travel together.
5. **Time-of-day correlation** — does 2am-you write worse prompts?
6. **Session-resumption correlation** — fresh-after-break vs grinding.
7. **Intent vs execution divergence** — the ep-169 "took the wheel" pattern.
8. **What the user should change first** — one actionable change.
9. **What the user should NOT conclude** — anti-overreading guardrails.

The prompt explicitly instructs Opus to NOT flatter and to call out
insufficient-data cases. If the report reads like cheerful coaching, the
prompt failed; report back.

---

## 5. Report back

Short summary:
1. Final episode count analyzed (and skipped, if any).
2. `did_model_verify` distribution.
3. Top 5 risk_flags.
4. **Quote the headline finding verbatim.**
5. **Quote "the user's worst recurring habit" verbatim.**
6. Total cost across Layer 2 + Layer 3.
7. Any section in the report that felt wrong, generic, or hallucinated.

That tells us whether the system is producing the diagnostic insight it
was designed for — or whether the prompts need another tuning pass before
running this on other sessions.

---

## What this whole project was for

Per `docs/recap.md` §7c: if at the end you can't answer "what's *my* worst
coding-session habit?" with one concrete sentence, the tool isn't done yet.
The headline + "user's worst habit" sections in the pattern report are
literally that sentence. If they land, the MVP is complete.
