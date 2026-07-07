# PR: Tier 2 Session-to-PR Link

## Why this slice exists
Tier 1 proved the fix-forward PR->PR class exists, and Layer 3 found no
merge-time feature strong enough to gate on. The next spec step is Tier 2:
connect earlier flawed PRs back to transcript evidence when the local session
actually created that PR.

Root cause: Tier 1 records only the effect side (`earlier_pr -> fix_forward_pr`).
Without a session link, the forensics pipeline cannot inspect the observable
condition present when the earlier PR was built. A correct Tier-2 slice must
link only from transcript source-of-truth evidence, and must not pretend review
or mention-only PR activity means "this session built the PR."

## What a correct fix must touch and change
1. Add a Tier-2 script that reads:
   - `out-atlas-fwd/forward-links.jsonl` as the Tier-1 source;
   - `out-atlas-cur/episodes.json` plus its pinned `source.snapshot.jsonl` as
     the transcript source.
2. Fail closed unless the parsed episode artifact matches the raw snapshot:
   sha256, record count, snapshot filename, and a terminal raw snapshot marker.
3. Extract strong PR-create actions from raw tool results, not assistant prose:
   `gh pr create` command + GitHub PR URL / echoed PR number in the full tool
   output.
4. Link Tier-1 confirmed `earlier_pr` records to the episode that created that
   earlier PR, if present. Otherwise record `could_not_determine`.
5. Write a gitignored local JSONL artifact and a committed findings doc with:
   counts, input pins, linked examples, and the building-biased caveat.

## What must NOT change
- Do not change `forward_link.py`, `forward_link_differentiate.py`, or their
  generated findings.
- Do not mutate Atlas or query/write Atlas beyond optional read-only evidence
  already present in the local snapshot.
- Do not infer links from `gh pr view`, PR comments, review posts, plain `#N`
  mentions, or `pr-link` metadata. Those are mention/touch signals, not build
  evidence.
- Do not promote any prevention triple or CI gate from Tier 2; this slice only
  produces the partial building-biased join.

## Verification
- `python -m pytest test_forward_link_tier2.py -q` -> 7 passed.
- `python3 test_forward_link_tier2.py` -> 7/7 passed.
- `python3 forward_link_tier2.py --dry-run` prints the fail-closed pin and
  strong-evidence plan, no execution.
- `python3 forward_link_tier2.py` against the pinned `out-atlas-*` inputs ->
  2/141 Tier-1 records linked; 7 PR-create actions found in the transcript.
- Generated local raw artifact: `out-atlas-fwd/session-pr-links.jsonl`
  (gitignored). Generated committed doc:
  `docs/forward-link-tier2-session-links.md`.

## Deferred
- Weak/touched PR evidence classification (`viewed`, `reviewed`, `merged`) as a
  separate diagnostic table, if useful.
- Multi-session corpus indexing across every Atlas transcript. This slice uses
  the pinned current-session artifact only.
- Pattern attribution from linked sessions. Tier 2 supplies evidence candidates;
  Layer 2/3 still have to adjudicate behavior with citations.
