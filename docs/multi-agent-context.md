# Managing AI-agent context across multiple sessions

Originally written as a forum reply to the question "how are you all
solving context loss when switching between agents (Codex terminal,
Claude Code, etc)?" Saved here so it can be linked and updated as the
patterns evolve.

---

**TL;DR — durable artifacts > volatile state.** Don't try to preserve
"context" as a thing. Preserve the *decisions, contracts, and
playbooks* the next agent needs to act. Anything in chat history dies;
anything in git or a markdown file survives.

## Background

This writeup is based on a multi-agent forensic-analysis project
(cloud Claude Code session + a local Claude Code session, ~16 days,
human as relay between them). The system below is what actually worked
in production for that project — not what sounds good in theory.

## The layered system

**1. Git commits as the decision log.** Every commit body is
deliberately overlong by typical standards — not "fix bug" but the why,
what was rejected, the trade-off. When a new agent does `git log`,
they reconstruct the reasoning trail back to commit 1. This is the
single biggest carrier and the cheapest. If you do nothing else, do
this.

**2. A small `docs/` folder, treated as load-bearing.**
- One handoff doc (we called it `docs/recap.md`) capturing: decisions
  locked in (so agents don't re-litigate), architecture, what's built,
  what's deliberately NOT being built.
- One playbook **per anticipated next-agent task** — forward-looking
  instructions written *before* the next agent exists.
- The original prompt or spec, verbatim, never edited.

**3. Stable JSON contracts between scripts.** Parser → analyzer →
reporter all talk through documented JSON shapes, not shared Python
objects. Agents can modify one script without breaking the others.
**Decoupling code = decoupling agents.**

**4. Tool affordances at the runtime level.** Every script has
`--resume`, crash-safe incremental writes, `--dry-run`. When an agent
picks up partial work, they don't restart — they continue. Context
preservation at the *execution* level, not just the documentation
level. Underrated.

**5. The honest gap: the human relays session output.** Actual data
products (gitignored `out/` files, analysis JSON) don't transfer via
git. The human pastes findings between sessions. Fine for low-cadence
handoffs; would break at scale.

## Direct answers to common questions

### Source of truth — repo markdown, Confluence/Notion, or MCP/shared memory?

Repo markdown. Strongly.

- Version-controls alongside the code that depends on it.
- Every agent already has git access — Confluence/Notion adds an
  external dependency that breaks when the wiki is down or the API
  key expires.
- Diffs are reviewable. If an agent edits CLAUDE.md, you see the
  change in the same PR as the code that motivated it.
- "Shared memory layers" drift silently from the code they describe.
  Markdown next to the code rots more slowly because it's right there.

Confluence/Notion makes sense for org-wide docs not tied to one repo.
Not for the moment-to-moment context an agent needs.

### MCP for AI coding context — does it work in practice?

MCP is great for *actions* (git ops, PR management, calendar, search).
Not as primary context storage.

- Adds a network hop on every read; a markdown file is one filesystem
  read.
- MCP servers can disconnect mid-session (this happened to us — tools
  became unavailable for several minutes). Files don't.
- The thing you most want — version history alongside the code — you
  already get from git for free.

Use MCP for the things agents *do*. Use markdown for the things they
*read*.

### Separating human docs from AI docs?

We didn't. Same docs served both. The trick is writing them so they're:

- Imperative and unambiguous (so an AI can follow mechanically)
- Structured with clear sections (so a human can skim)
- Honest about uncertainty ("we don't know X yet"; "this is deferred")

If you find yourself writing two versions of the same doc, that's a
smell — the human version will go hand-wavy, the AI version will go
terse, and they'll diverge. Write one good version.

The one exception: **per-task playbooks**. These are AI-task-shaped —
explicit dry-run steps, error-handling, report-back templates. Humans
can read them, but they're optimized for an agent to follow
mechanically.

## Templates

### `docs/recap.md` — the handoff / orientation doc

```markdown
## 1. What we're building (1 paragraph)
## 2. Decisions locked in (don't re-litigate)   ← table format works well
## 3. What's built so far (file by file, 1-3 sentences each)
## 4. Architecture (ASCII diagram or short outline)
## 5. What's next (with link to the playbook)
## 6. How to run what exists (copy-paste commands)
## 7. What to look for (qualitative viewing guide)
## 8. Things to actively resist building (anti-scope list)
## 9. Branch / repo / install
## 10. Stable interfaces (JSON contracts — load-bearing)
## 11. Roadmap (deferred features, with "do not build until X" gates)
```

The load-bearing sections: §2 (next agent doesn't redesign the stack),
§8 (doesn't over-build), §10 (contracts don't drift).

### `CLAUDE.md` — rules the agent reads at session start

```markdown
## Principles
[3-5 sentences about how this codebase wants to be worked on]

## Don't
[Specific actions to refuse, each with WHY]

## Verify before claiming done
[Specific commands; e.g. "run `pytest tests/` after any change to src/"]

## When in doubt
[Usually: "ask before acting"]
```

Keep this under 100 lines. Long rule files get ignored.

### `docs/handoff-<task>.md` — per-task playbook, written *before* the task is assigned

```markdown
## 0. Prereqs
## 1. Dry-run / sanity check (read before spending real resources)
## 2. The real run (commands, expected runtime, expected cost)
## 3. Spot-check protocol
## 4. Failure modes and what to do
   - If X happens: do Y
   - If Z happens: stop and report
## 5. Report back (structured template the next agent fills in)
   1. <specific question 1>
   2. <specific question 2>
   ...
```

**§5 is the magic.** By specifying what the next agent must report
back, you constrain the shape of their reply so the *following* agent
can act on it quickly. We had agents respond in exactly the structure
we asked for.

## The one pattern worth stealing: "predictive handoff"

The single most valuable move was **writing the next agent's playbook
before that agent existed.** When I knew there'd be a local
verification session next, I wrote the verification playbook *in the
current session*. The local session opened the repo, ran
`cat docs/verify-analyze.md`, and had a complete script. Zero
ambiguity, zero orientation overhead.

When finishing a session, **pre-stage the next session's instructions
before stopping.** Costs 10 minutes, saves an hour.

## What didn't work / what I'd change

- Output data (analysis files, reports) sat in gitignored `out/`.
  Cross-session, the human had to paste outputs manually. Should have
  committed them as artifacts or used a separate `outputs/` branch.
- The recap doc got internally inconsistent twice (section numbering
  drifted as new sections landed). A doc-structure linter would have
  caught it. Or just fewer top-level sections.
- Never tried Notion / Confluence — can't compare from experience.

## Related files in this repo

- `docs/recap.md` — the actual handoff doc this project ran on (sections
  1-11 as above).
- `docs/verify-analyze.md`, `docs/run-full.md` — the per-task playbooks.
- `docs/coding-session-guardrails.md` — the eventual CLAUDE.md-style
  ruleset this project produced as its main deliverable.
- `parse.py`, `analyze.py`, `patterns.py` — the three scripts. Stable
  JSON contracts between them are documented in `docs/recap.md` §10.

Read those if you want to see the system applied end-to-end, not just
the templates.
