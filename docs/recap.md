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

**Build `analyze.py` (Layer 2).** Pick a slice and analyze it:

1. **Recommended first slice: episodes 0–9** — control group, cheap, validates the prompt/JSON shape works.
2. After that: the **14 error episodes** — where the pain was.
3. Later: episodes around the **biggest time gaps** — to compare fresh-start vs. grinding-fatigue.

Per-episode output should be a small JSON:

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
