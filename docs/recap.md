# Session Transcript Analyzer — Recap & Guide

> Read this first if you're picking the project up in a new session. Covers
> what was decided, what's built, what's next, and what to actually look for
> when you eyeball the output.

---

## 1. What we're building

A **forensic diagnostic tool for coding-session transcripts.** Goal: take a
Claude Code session transcript and identify the interaction patterns that
produce bad code, rework, skipped verification, contradictions, and degraded
performance under fatigue/frustration/time pressure.

We are starting with a **proof-of-concept**, not a product. Read
`docs/original-prompt.md` for the full design spec.

---

## 2. Decisions locked in (don't re-litigate these)

| Decision | Choice |
|---|---|
| Transcript source | Claude Code JSONL (`~/.claude/projects/*.jsonl`) |
| Language | Python, stdlib only for the MVP |
| Analyzer model | Sonnet 4.6 for per-episode; Opus 4.7 reserved for cross-session pattern report later |
| Scope discipline | Tiny MVP first. No schemas, no taxonomy, no rolling state, no sentiment rubric. Those emerge from real output, not up-front design. |
| Hunger as a state signal | Dropped. Noise. |
| Timestamps | First-class. Every episode keeps timestamp + gap-from-previous. |
| Architecture | **Three layers:** (1) local parse — free, (2) trimmed LLM call per episode, (3) eventual cross-episode pattern report |
| Trim policy | Tool calls keep name + args; tool outputs get a structured stub (status, line/byte count). Error tails keep last ~20 lines. User prompts and assistant text are kept full. |
| Sub-agent traffic | Skipped (`isSidechain: true` filtered out) |
| Rolling state between episodes | **Not yet.** Episodes analyzed independently first. Add only if independent analysis is clearly missing things. |

---

## 3. What's built so far

### `parse.py` (done, committed, audited on real data)

Reads a Claude Code `.jsonl` file, groups records into **episodes** (one user
text turn + the assistant work that followed), and emits:

- `out/episodes.json` — structured, archival; full tool args preserved
- `out/episodes.md` — condensed, LLM-ready; this is what the analyzer will eat

Each episode carries:

- `timestamp` and `gap_seconds_from_prev`
- `user_text` (full, typos included)
- `assistant_text` (full)
- `tool_calls[]` with `name`, `input_summary`, `result_status` (ok/error/missing), `result_lines`, `result_bytes`, `result_tail`
- Structural signals: `has_tool_error`, `tool_count`, `user_tokens_est`, `assistant_tokens_est`, `raw_message_count`

No LLM is called. Everything is local and free.

### Audit results from one real session (Atlas, Apr 25 → May 11)

- 15,190 JSONL records → **307 episodes**
- 62 episodes flagged `has_tool_error` (~20%)
- Prompt capture: **verbatim**, including typos
- Tool input fidelity: solid — full paths, commands, flags preserved
- Time gaps: real and meaningful (largest: 1d 22h between episodes 120→121)
- **Known gap:** `grep` returning exit 1 (no matches) is currently flagged as a tool error. ~2 of 9 audited bash failures were this kind of noise. **Deferred fix** — the LLM analyzer can judge "grep found nothing" itself from `result_tail`. Don't add heuristics yet.
- **Known gap:** ~3 tool calls in one large episode showed `result_status: missing` (ordering artifact in JSONL). 0.16% rate. Deferred.

---

## 4. The architecture in one picture

```
┌────────────────────────────────────────────────────────────┐
│  Layer 1: parse.py  (LOCAL, FREE)                          │
│  ──────────────────────────────────                        │
│   .jsonl  →  episodes.json + episodes.md                   │
│   • split into episodes                                    │
│   • strip system-reminders, sidechain noise                │
│   • compute structural signals (gaps, errors, tool counts) │
│   • trim tool outputs to stubs                             │
└────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│  Layer 2: analyze.py  (LLM, Sonnet 4.6, ~$0.01–0.05/ep)    │
│  ─────────────────────────────────────────────────────     │
│   one trimmed episode  →  tiny JSON:                       │
│     { what_user_asked, what_model_did,                     │
│       did_model_verify, risk_flags[], notes }              │
│   No rolling state. No fixed taxonomy yet.                 │
└────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│  Layer 3: patterns.py  (LLM, Opus 4.7, single call)        │
│  ─────────────────────────────────────────────────         │
│   all per-episode analyses  →  pattern report:             │
│     • repeated risk_flags = real labels                    │
│     • time-of-day vs quality                               │
│     • gap-after-break vs quality                           │
│     • prompts that consistently produce bad code           │
│   Build only after Layer 2 output is trusted.              │
└────────────────────────────────────────────────────────────┘
```

**The point of Layer 1:** never send raw transcript to the LLM. A 50M-token
session compresses down to maybe 1–2M tokens of trimmed episodes. That keeps
analysis cheap (~$5 instead of ~$150).

---

## 5. What's next

**Layers 1, 2, and 3 are all built.** Verification pass 2 confirmed the
per-episode analyzer is calibrated: anti-bias is closed (12/12 verify=yes
records back evidence with tool tails, not prose), `did_model_verify` has
healthy distribution (~30/70 yes/no on baseline), and the new
`evidence_lifted_from_prose` flag fires when the model narrates results
without tool confirmation. See `docs/verify-analyze.md` for the protocol
and `docs/run-full.md` for the green-lit full-session run.

**Pending: the full 307-episode run + Layer 3 pattern report.**
- `python3 analyze.py --first 1000 --resume` (will analyze all unvisited
  episodes; ~$6 at current rates).
- `python3 patterns.py --tz <your IANA TZ>` to produce
  `out/patterns-report.md` — one Opus 4.7 call, ~$2-4.

Per-episode output (one JSON object per line in `out/analysis.jsonl`):

```json
{
  "episode_index": 0,
  "timestamp": "...",
  "what_user_asked": "...",
  "what_model_did": "...",
  "did_model_verify": "yes|no|unknown",
  "risk_flags": ["vague_requirements", "no_verification", ...],
  "notes": "..."
}
```

**Free-form `risk_flags`**, not a fixed taxonomy. Real patterns will emerge
from 10–20 analyzed episodes. That becomes the taxonomy in Layer 3.

After verification passes:
- If the analyzer is biased lenient → tune the system prompt (likely the
  ANTI-BIAS NOTE section).
- If the flags are noisy → trim the example list in the prompt to the
  3–5 names that actually showed up.
- If signal is clean → run on the rest of the 307 episodes (~$3–5) and
  start building Layer 3 (cross-episode pattern report on Opus 4.7).

---

## 6. How to run what exists

```bash
# Parse a session interactively (lists recent .jsonl files, you pick by number)
python3 parse.py

# Or pass an explicit path
python3 parse.py ~/.claude/projects/.../some-session.jsonl

# Outputs land in ./out/
#   out/episodes.json   (archival)
#   out/episodes.md     (read this — it's the LLM's eventual view)
```

No deps. Stdlib only.

---

## 7. What to look for — a viewing guide

This is the part nobody writes down. When you open `episodes.md`, you're not
just checking that parsing worked. You're starting to **read your own session
forensically.** Here's what to watch for.

### 7a. In `episodes.md` (what you have now)

**Prompt signals** (read your own `user_text`):
- **Vague verbs**: "fix it", "make it work", "clean this up" — no acceptance criteria. Expect bad output.
- **Compound asks**: "do X and also Y and while you're there Z" — these tend to produce half-finished work.
- **Frustration markers**: profanity, all-caps, "just", "please just", repeated negation ("don't again"), questioning competence. These usually correlate with rushed prompts and lower verification.
- **Time-pressure markers**: "quick", "real fast", "hurry", "I need this now".
- **Contradiction with earlier prompts**: did you say "keep it minimal" three episodes ago and now say "add a fallback for X"?

**Model signals** (read the `assistant_text`):
- **Verification claims without evidence**: "this should work", "this is now fixed" — without a test run or compiler output in the tool calls. That's a red flag.
- **Excessive hedging**: "let me try…", "this might work" — sometimes appropriate, sometimes a sign the model is guessing.
- **Long text + few tool calls** = explaining / planning episode.
- **Short text + many tool calls** = grinding / executing. Often where bugs slip in.
- **Read → Edit → Read same file → Edit same file**: rework cycle. The model is fixing what it just wrote.

**Tool patterns**:
- `Bash(npm test)` or `Bash(pytest)` followed by **no further edits** = verified and moved on. Good.
- Errors followed by `--no-verify`, `--force`, `git reset --hard` = bypassing safety. Bad.
- Long `Read` chains with no `Edit` = the model is lost, scanning for context.
- Same `Edit` to the same file 5+ times = thrashing.

**Time / gap patterns**:
- Cluster of episodes between 1am–5am with high tool-error rates = the "tired" pattern you wanted to detect.
- Long gaps (>30 min) inside a session = you walked away frustrated.
- Episode timestamps drift relative to gap-from-previous — was this episode fresh-after-break or hour-six-of-grinding?

### 7b. In `analyze.py` output (once built)

When the LLM returns its per-episode JSON, look for:

- **`did_model_verify: "no"` rate.** If it's >30%, the model is shipping unverified claims regularly. That's a systemic issue, not bad luck.
- **`risk_flags` repetition.** The same 3–5 flags will appear in 80%+ of episodes. Those are your real labels — note them down. The long tail of one-off flags is noise.
- **Alignment with your gut.** Read 5 analyses of episodes where *you* remember the pain. Does the analyzer's `notes` field match your memory? If yes, trust it for the boring episodes. If no, the prompt needs tuning.
- **Self-flattery bias.** LLMs grading LLMs tend to be lenient. If the analyzer almost never flags problems, it's broken or the prompt is too soft.

### 7c. In the eventual pattern report (Layer 3, later)

This is the payoff layer. What you're hoping to learn:

- **Time-of-day quality curve**: does 2am-you produce 3x the risk flags of 10am-you?
- **Fatigue threshold**: how many consecutive episodes before quality degrades?
- **Prompt-pattern → outcome map**: do prompts containing "just", "quick", or "real fast" correlate with more `no_verification` flags?
- **Architecture-decision drift**: where in the session did the model start ignoring an earlier constraint?
- **Your specific failure modes**: not LLM-general patterns. *Yours.* The point is to know your own bad habits with enough resolution to fix them.

If after 50 analyzed episodes you can't answer "what's *my* worst coding-session habit?" with one concrete sentence, the tool isn't done yet.

---

## 8. Things to actively resist building

(From the original prompt — these come later, if at all.)

- Dashboards
- Vector search
- Database layer
- Automated prompt-improver loop
- Real-time intervention
- IDE plugin
- Multi-model judge panel
- Elaborate UI

If you catch yourself sketching any of these, you're off track. Go back to
analyzing one more slice of real episodes.

---

## 9. Branch & repo

- Repo: `canfieldjuan/session-transcript-analyzer`
- Branch: `claude/session-transcript-analyzer-K8bUH`
- All work pushed here. New session: keep working on the same branch.

---

## 10. Roadmap notes (deferred, not built yet)

### 10a. Use the Message Batches API, not concurrent calls

When this graduates to a nightly cron job, switch `analyze.py` from
sequential one-call-at-a-time to the **Anthropic Message Batches API**.
Reasons, in order:

- **50% discount on input + output.** Cuts a $6 full-session run to $3,
  a $30 weekly batch (5 sessions × 307 episodes) to $15.
- **Cron doesn't need real-time.** Batches return within 24h; a nightly
  job that finishes by morning is fine.
- **Higher effective throughput.** A single batch can hold ~10K requests;
  no per-call rate-limit pressure, no client-side concurrency code, no
  retry orchestration.
- **Simpler than parallel calls.** Concurrent `asyncio` requests would
  hit rate limits fast, complicate `--resume`, and cost the same as
  sequential. Batches are strictly better when you don't need <1h
  latency.

What stays the same: the per-episode prompt, the JSON schema, the trim
policy. Only the call-site in `analyze.py` changes:

- One submission step that posts all unanalyzed episodes as a batch.
- One polling/wait step (or a separate "collect" command) that reads
  the batch results and appends to `out/analysis.jsonl`.
- `--resume` still works; just at batch granularity.

`patterns.py` is one big call (~$2-4) so batching saves only ~$1-2
there. Lower priority than analyze.py, but free to fold in once the
Batches plumbing exists.

### 10b. Cron-friendly entry point

For the nightly job to be hands-off, we need:

- **No interactive picker.** Auto-discover `~/.claude/projects/*.jsonl`
  files modified since the last run (mtime stamp on disk). Today,
  `parse.py` requires a number from stdin.
- **One command per session.** Something like
  `python3 cron_run.py --since "yesterday"` that finds new sessions,
  parses + submits a batch + collects + runs patterns, all without
  prompts.
- **Idempotent.** Re-running the same day must not re-submit work.
  `--resume` already handles this at the analyze layer; we'd extend it
  to the discovery layer.
- **Structured logs to a file**, not stdout interactive printing.
  `out/cron-YYYY-MM-DD.log` keeps the trail.

None of this is built. It's a deliberate next step once the MVP has
proven its value on a few hand-run sessions.

### 10c. Order of operations when we get there

1. Land Batches API in `analyze.py` (foreground command, manual run).
2. Land it in `patterns.py`.
3. Build the cron entry point that wraps both.
4. Add a basic `out/cron-status.json` so the next run knows where the
   last one stopped.

Resist building the cron entry point before steps 1-2 are solid. A cron
job that calls broken plumbing creates silent failures that pile up for
days before anyone notices.
