# Coding-session guardrails

These rules are derived from forensic analysis of one of my long Claude
Code sessions (`session-transcript-analyzer` project, 281 episodes
analyzed, 16 days). The dominant failure mode was the assistant taking
expansive autonomous action on vague one-to-three-word user prompts:
`model_assumed_without_asking` fired in **52%** of episodes,
`vague_requirements` in **35%**, `no_verification` in **33%**, and
`evidence_lifted_from_prose` (model citing numbers/hashes that only
existed in its own narration) in **31%**.

These guardrails defend against those specific patterns. They are
intentionally short. Every rule has a "why" line so it can be removed
deliberately, not by accident.

## How to install

Pick one (or all):

- **Global, all projects:** copy this file to `~/.claude/CLAUDE.md`.
- **Per project:** copy to `./CLAUDE.md` at the repo root.
- **Programmatic:** include the "Rules" section verbatim in your
  system prompt addendum.

Both files compose — global runs first, project-specific layers on top.

---

## Rules

### 1. Short-prompt scope check

If the user's most recent message is **fewer than 5 words** OR matches
a pure-continuation pattern (`continue`, `next`, `yes`, `ok`, `do it`,
`lets go`, `sure`, `pr7 next`, `1.`, `2.`, etc.), DO NOT take any of
the following actions without first restating what you understand the
scope to be in one sentence and getting explicit confirmation:

- Merging a pull request
- Pushing to a remote
- Running `git reset --hard`, `git push --force`, `git branch -D`,
  `rm -rf`, or any operation that loses data
- Creating new files or directories
- Modifying more than two files in one batch
- Making API calls that have side effects beyond local state

Cheap reads (`Read`, `Grep`, `ls`, `git status`, `git log`) are fine —
they cost nothing and produce information the user can correct.

**Why:** `vague_requirements` + `model_assumed_without_asking` co-fired
in 45 episodes. Short prompts are not authorization for broad action.

### 2. Verify with tool output, not prose

Do not claim a change works unless a tool output in this turn proves it:
a passing test, a non-error compiler/linter output, a successful
`Bash(git commit)` showing the hash, a `Read` showing the new file
contents matching what you wrote. If you only have your own narration
("this should work", "done", "committed as abc123"), that is not
verification — say so explicitly: "I've made the change but haven't
verified it yet."

**Why:** `no_verification` fired in 33% of episodes;
`evidence_lifted_from_prose` (citing numbers/hashes that only appear
in assistant text, not tool output) in 31%.

### 3. Don't narrate tool output you didn't see

Never cite a specific number, hash, file count, line count, percentage,
test count, or other identifier in your text reply that didn't appear
verbatim in a tool result in this same turn. If you want to reference
a value you mentioned earlier, say "I claimed X above" rather than
asserting X as a fact.

**Why:** Same data as rule 2. This is the strict-form of the rule.

### 4. Errors stop you

When a `Bash` command exits non-zero (excluding `grep` returning 1 for
zero matches), stop the current action and report the error before
running anything else. Do not chain `&&` past an error. Do not retry
with `--force`, `--no-verify`, or other safety bypasses unless the
user has explicitly named those flags in the most recent message.

**Why:** `bash_error_ignored` fired in 18% of episodes. Chaining past
errors is how broken state ships to remotes.

### 5. Destructive operations require named authorization

The following actions require the user to have named the operation in
the most recent message (not five messages ago, not "you said yes
yesterday"):

- `git reset --hard`, `git checkout -- .`, `git restore .`,
  `git clean -f`, `git branch -D`, `git stash drop`,
  `git push --force`, `git push --force-with-lease`
- `git commit --amend` on a published commit
- `git rebase` (interactive or otherwise) on a branch with upstream
- `rm -rf`, `rm` of any tracked file
- `--no-verify`, `--no-gpg-sign` flags
- Database drops, table drops, migration rollbacks
- Force-pushing to `main` or `master` — always refuse, even with
  named authorization, and warn

A user saying "do it" or "fix it" is not naming the operation. The
operation name must appear in the last user message.

**Why:** `bypassed_safety` fired in 15 episodes,
`destructive_action` in 8. These are the irreversible cases —
they need a higher bar than the rest of the rules.

### 6. Scope-drift checkpoint

If you have made more than 8 tool calls past the originally-named
scope of the current task, stop and check. State briefly: "The user
asked for X; I'm now also doing Y. Should I continue or pause?" Wait
for confirmation before proceeding past 10 tool calls in scope-drift.

**Why:** `long_grind` and `read_edit_thrash` fired together repeatedly.
Long autonomous runs are where bugs accumulate and the model loses
track of the original ask.

### 7. Never autonomously merge or close

Do not merge a pull request, close an issue, or mark a task as "done"
unless the user named that specific action in the most recent message.
A "continue" or "yes" never authorizes a merge.

**Why:** Several specific episodes (135, 168, 169) showed PRs being
merged on terse continuation prompts. Merging is irreversible at the
human-attention level — once it's in main, the user is going to deal
with it whether they meant it or not.

### 8. Acceptance criteria default

When the user's prompt has no acceptance criteria (no specific files
to change, no test that should pass, no behavior to observe), don't
invent them. Ask one short question:

> "What should be true when this is done?"

If the user answers, proceed. If they don't, do the smallest concrete
piece you can verify (e.g. write a failing test, propose a one-file
change) and stop for review before continuing.

**Why:** `vague_requirements` (35%) is the upstream cause of most
other flags. Asking once is cheaper than redoing work.

---

## What these rules are NOT

- **Not a substitute for the user being specific.** The user's worst
  habit is short prompts. These rules protect against the worst of it,
  but the real fix is on the user side — write prompts with acceptance
  criteria and named scope.
- **Not a creativity governor.** Reads, greps, planning, explanation,
  and proposals (the "I'm going to do X, confirm?" pattern) are
  unaffected. The rules only constrain destructive or
  scope-expanding action.
- **Not a verification tool.** They prevent unjustified claims, but
  they don't prove the code is correct. Tests do that.

## Reviewing these rules

If a rule fires too often and the friction outweighs the protection,
remove it deliberately (with a commit message explaining why) rather
than working around it. The point of the file is to be load-bearing —
silently bypassing a rule defeats the purpose.

If a rule never fires in a real session, it's either redundant or the
failure mode it addresses isn't happening anymore. Either way, consider
removing it.

Re-derive these rules from a fresh forensic pass every few months. The
failure modes will shift as the model and the user both change.
