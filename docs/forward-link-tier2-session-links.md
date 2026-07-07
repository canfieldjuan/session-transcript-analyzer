# Forward-Link Findings -- Tier 2 (session -> PR)

Status: partial session linkage for Tier-1 fix-forward records. This is
building-biased evidence, not a promoted pattern or CI gate.

Source artifacts, local only:
- `out-atlas-fwd/session-pr-links.jsonl`
- `out-atlas-cur/source.snapshot.jsonl`

Input pins:
- Tier-1 jsonl sha256: `e575745044824f726f2e4f6169b579aef2cccbd183d80f89917972a07592389d`
- transcript sha256: `d031b790ddcf11dc4ab403361561151d31718ef312c9007d2c0d85b5d7682094`
- transcript records: `11765`
- transcript episodes: `346`
- terminal marker: `pr-link`

## Method

A Tier-1 earlier PR is linked only when the pinned raw snapshot contains
strong build evidence: a `gh pr create` command for `canfieldjuan/ATLAS`
and full tool output containing the created PR number. Plain mentions,
`gh pr view`, review comments, merge commands, and `pr-link` metadata are
ignored because they do not prove this session built the PR.

The run fails closed if `episodes.json` no longer matches the raw snapshot
by sha256, record count, snapshot filename, or terminal snapshot marker.

## Result

- Tier-1 confirmed records considered: 141
- confirmed session links: 2
- could_not_determine: 139
- unique PRs created in this transcript: 7
- linked earlier PRs: #1994, #2002

## Confirmed Links

| earlier PR | fix-forward PR | episode | evidence |
|---:|---:|---:|---|
| #1994 | #2004 | 298 | `source.snapshot.jsonl:line 10439 gh pr create -> #1994` |
| #2002 | #2004 | 307 | `source.snapshot.jsonl:line 10825 gh pr create -> #2002` |

## Caveats

- This is **building-biased** by construction. Review-only and planning-only
  sessions usually do not create PRs, so they remain invisible here.
- `could_not_determine` does not mean no session exists. It means this pinned
  transcript lacks strong PR-create evidence for that earlier PR.
- Do not promote prevention triples from this file alone. The linked episode
  still needs Layer-2 reconstruction with cited transcript spans.

## Deferred
- Multi-session Atlas transcript index.
- Weak/touched PR diagnostics.
- Layer-2 adjudication of linked episodes.
