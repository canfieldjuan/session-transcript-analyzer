#!/usr/bin/env python3
"""
forward_link.py -- the forward-link join, Tier 1 (PR -> PR fix-forward).

Cross-time forensics. In-session forensics (parse/detect/analyze/patterns) is
structurally blind to failures whose evidence only appears LATER: a weak test
that passes when written and fails weeks later, a symptom patch that reopens, a
change that ships and is later fixed forward. This module joins an earlier PR
(A) that looked done to the later fix-forward PR (B) that repaired a flaw in it.

Tier 1 is git/GitHub-only -- no transcripts (that is Tier 2). See
docs/SESSION_FORENSICS_SPEC.md.

CONSTRAINT 1 (spec): strong keys are corpus-specific -- discover, do not assume.
A corpus probe found revert/reopened-issue near-empty on Atlas and fix-forward
the real key; key_discovery() measures the counts and records them.

CONSTRAINT 2 (spec): the earlier PR's features are restricted to what was
observable AT A's MERGE TIME (diff shape, test delta, scope, review depth).
Nothing derived from B or from after A merged -- hindsight postdicts, it does
not predict. merge_time_features() enforces this with a fail-closed allowlist
and a <= mergedAt filter on reviews/comments.

Usage:
  python3 forward_link.py [--repo owner/name] [--out-dir out-atlas-fwd]
                          [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
from pathlib import Path

REPO_DEFAULT = "canfieldjuan/ATLAS"

# fix-forward search terms -- documented constant; recall depends on it.
FIX_FORWARD_TERMS = "regression OR self-correction OR revert OR hotfix OR corrects"

# reopened-issue count comes from the SPEC calibration probe: re-paginating the
# ~14.7k issue-events every run is wasteful and the value is stable. revert and
# fix-forward are measured live. This keeps constraint 1 honest (counts recorded)
# without the per-run cost. Documented in the findings doc.
CALIBRATION_REOPENED_ISSUES = 3
CALIBRATION_REOPENED_EVENTS_SCANNED = 14706

# The ONLY feature keys a record may carry for the earlier PR (constraint 2).
MERGE_TIME_FEATURE_KEYS = (
    "additions", "deletions", "changed_files",   # diff shape
    "test_files_changed", "test_lines_changed",  # test delta
    "scope_files", "scope_top_dirs",             # scope
    "review_count", "review_comment_count", "hours_to_merge",  # review depth
)


# --- subprocess boundary (the one reusable idiom, from analyze.py) ---------

def _run(args: list[str], timeout: int = 180) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f"{' '.join(args[:3])} exit {proc.returncode}: "
            f"{(proc.stderr or proc.stdout)[-200:]}"
        )
    return proc.stdout


def _gh_json(args: list[str], timeout: int = 180):
    return json.loads(_run(args, timeout) or "null")


# --- pure helpers (unit-testable, NO network) ------------------------------

# 3+ digits: Atlas PR/issue numbers are 3-4 digit (min observed #118); the floor
# also drops low-number prose noise ("#1", "step #2"). A stray match still passes
# the A<B + resolves-to-merged-PR gates, so it becomes CND, never a fabricated link.
_PR_REF_RE = re.compile(r"#(\d{3,})")


def parse_earlier_refs(body: str, self_number: int) -> list[int]:
    """Earlier-PR references in a fix-forward body: #N where N < self_number.
    The squash-merge self-reference (#self_number) is dropped by the N<self test."""
    refs = {int(m.group(1)) for m in _PR_REF_RE.finditer(body or "")}
    return sorted(n for n in refs if n < int(self_number))


_TEST_RE = re.compile(
    r"(^|/)(tests?|specs?|__tests__)(/|_|\.|$)|\.test\.|\.spec\.", re.I
)


def _is_test_path(path: str) -> bool:
    return bool(_TEST_RE.search(path or ""))


def _ts(s):
    if not s:
        return None
    dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def merge_time_features(a_view: dict) -> dict:
    """A's MERGE-TIME-observable features ONLY (constraint 2).

    Reviews/comments are filtered to <= mergedAt so post-merge (hindsight)
    activity cannot leak in; an item with an unknown timestamp is DROPPED (it
    could be post-merge -- fail closed toward hindsight exclusion). The return is
    guarded to MERGE_TIME_FEATURE_KEYS and FAILS CLOSED with `raise` (not
    `assert` -- assert is stripped by `python -O`).
    """
    merged = _ts(a_view.get("mergedAt"))
    created = _ts(a_view.get("createdAt"))
    files = a_view.get("files") or []
    tests = [f for f in files if _is_test_path(f.get("path", ""))]

    def _at_or_before_merge(items, tskey):
        if merged is None:
            return items  # unmerged A: no merge boundary; caller marks it CND
        keep = []
        for it in items:
            t = _ts(it.get(tskey))
            if t is not None and t <= merged:  # drop unknown ts: fail closed
                keep.append(it)
        return keep

    reviews = _at_or_before_merge(a_view.get("reviews") or [], "submittedAt")
    comments = _at_or_before_merge(a_view.get("comments") or [], "createdAt")
    hours = (
        round((merged - created).total_seconds() / 3600, 1)
        if (merged and created) else None
    )

    feats = {
        "additions": a_view.get("additions"),
        "deletions": a_view.get("deletions"),
        "changed_files": a_view.get("changedFiles"),
        "test_files_changed": len(tests),
        "test_lines_changed": sum(
            (f.get("additions", 0) + f.get("deletions", 0)) for f in tests
        ),
        "scope_files": len(files),
        "scope_top_dirs": len(
            {(f["path"].split("/")[0] if "/" in f["path"] else "<root>")
             for f in files if f.get("path")}
        ),
        "review_count": len(reviews),
        "review_comment_count": len(comments),
        "hours_to_merge": hours,
    }

    extra = set(feats) - set(MERGE_TIME_FEATURE_KEYS)
    missing = set(MERGE_TIME_FEATURE_KEYS) - set(feats)
    if extra or missing:  # fail-closed: no hindsight key in, no required key out
        raise ValueError(
            f"CONSTRAINT 2 violation: feature keys drifted "
            f"(extra={sorted(extra)}, missing={sorted(missing)})"
        )
    return feats


def build_pairs(fix_forward_prs: list[dict]) -> list[dict]:
    """Join each fix-forward PR B to earlier referenced PR(s) A (A < B).
    A B with no earlier reference yields NO pair -- no fabricated link."""
    pairs = []
    for b in fix_forward_prs:
        bn = b.get("number")
        for a in parse_earlier_refs(b.get("body", ""), bn):
            pairs.append({
                "earlier_pr": a,
                "fix_forward_pr": bn,
                "fix_forward_title": b.get("title", ""),
                "evidence_span": f"#{a} referenced in PR #{bn} body",
            })
    return pairs


# --- gh/git wrappers (net-new; read-only queries against Atlas) -------------

def gh_head_sha(repo: str) -> str:
    return _run(["gh", "api", f"repos/{repo}/commits/main", "--jq", ".sha"]).strip()


def key_discovery(repo: str) -> dict:
    """Constraint 1: measure candidate join keys; do not assume. fix-forward and
    revert are measured live; reopened-issue is from the calibration probe."""
    ff = _gh_json(["gh", "pr", "list", "--repo", repo, "--state", "all",
                   "--search", FIX_FORWARD_TERMS, "--limit", "300",
                   "--json", "number"])
    fix_forward = len(ff or [])
    revert_source = "live gh search commits"
    try:
        rv = _gh_json(["gh", "search", "commits", "--repo", repo,
                       "This reverts commit", "--limit", "100", "--json", "sha"])
        reverts = len(rv or [])
    except Exception:
        reverts = None  # a measured FAILURE, not a measured zero -- do not conflate
        revert_source = "probe failed (not measured)"
    counts = {
        "fix_forward_prs": fix_forward,
        "git_reverts": reverts,
        "git_reverts_source": revert_source,
        "reopened_issues": CALIBRATION_REOPENED_ISSUES,
        "reopened_events_scanned": CALIBRATION_REOPENED_EVENTS_SCANNED,
        "reopened_source": "spec calibration probe (not re-paginated per run)",
    }
    counts["dominant_key"] = max(
        (("fix_forward", fix_forward), ("revert", reverts or 0),
         ("reopened_issue", CALIBRATION_REOPENED_ISSUES)),
        key=lambda kv: kv[1],
    )[0]
    return counts


def fetch_fix_forward_prs(repo: str, limit: int) -> list[dict]:
    return _gh_json(["gh", "pr", "list", "--repo", repo, "--state", "all",
                     "--search", FIX_FORWARD_TERMS, "--limit", str(limit),
                     "--json", "number,title,body"]) or []


def fetch_pr_view(repo: str, n: int):
    """A's merge-time view. Returns None when n is not a PR (e.g. an issue ref)."""
    try:
        return _gh_json(["gh", "pr", "view", str(n), "--repo", repo, "--json",
                         "number,additions,deletions,changedFiles,files,"
                         "reviews,comments,createdAt,mergedAt,state"])
    except RuntimeError:
        return None


# --- record assembly + writers ---------------------------------------------

def assemble_record(pair: dict, corpus: dict, a_view) -> dict:
    """Build one forward-link record. confirmed iff A resolves to a MERGED PR and
    its merge-time features extract; else could_not_determine (never fabricated)."""
    rec = {
        "dataset": corpus["dataset"],
        "corpus": corpus["pin"],
        "forward_link_key": "fix_forward",
        "earlier_pr": pair["earlier_pr"],
        "fix_forward_pr": pair["fix_forward_pr"],
        "evidence": [{
            "kind": "github",
            "quote_or_summary": pair["evidence_span"],
            "location": f"PR #{pair['fix_forward_pr']} body",
        }],
    }
    if a_view is None:
        rec.update(classification="could_not_determine", tags=[],
                   note=f"#{pair['earlier_pr']} did not resolve to a PR (likely an issue)")
        return rec
    if not a_view.get("mergedAt"):
        rec.update(classification="could_not_determine", tags=[],
                   earlier_pr_state=a_view.get("state"),
                   note=f"#{pair['earlier_pr']} is not merged (did not 'look done')")
        return rec
    rec["earlier_pr_merge_time_features"] = merge_time_features(a_view)
    rec["classification"] = "confirmed"
    rec["tags"] = ["REPEATED_FIX_LOOP", "CONTRACT_DRIFT"]
    return rec


def write_jsonl(path: Path, records: list[dict]) -> None:
    """Crash-safe append (parse/analyze pattern)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:  # fresh file per run; corpus pin makes it reproducible
        for r in records:
            f.write(json.dumps(r, ensure_ascii=True) + "\n")
            f.flush()


def render_findings_doc(corpus: dict, keys: dict, records: list[dict]) -> str:
    confirmed = [r for r in records if r["classification"] == "confirmed"]
    cnd = [r for r in records if r["classification"] == "could_not_determine"]
    pin = corpus["pin"]
    lines = [
        "# Forward-Link Findings -- Tier 1 (PR -> PR fix-forward)",
        "",
        "Status: positive-class collection for later differentiation. Not a durable",
        "pattern yet -- see the bar-2 guard below.",
        "",
        "Source artifact, local only:",
        f"- `{corpus['dataset']}/forward-links.jsonl`",
        "",
        "Corpus pin:",
        f"- repo: `{pin['repo']}`",
        f"- query date: `{pin['query_date']}`",
        f"- Atlas `main` HEAD sha: `{pin['atlas_head_sha']}`",
        f"- PR-number range covered: `{pin['pr_range'][0]}`..`{pin['pr_range'][1]}`",
        "",
        "The `out-*/` artifact is gitignored (may hold sensitive material). This doc",
        "carries the durable findings + the corpus pin needed to re-check it.",
        "",
        "## Key discovery (constraint 1 -- discover, do not assume)",
        "",
        "| candidate key | count | source |",
        "|---|---:|---|",
        f"| fix-forward PRs | {keys['fix_forward_prs']} | live `gh pr list --search` |",
        f"| git reverts | {keys['git_reverts'] if keys['git_reverts'] is not None else 'not measured'} "
        f"| {keys['git_reverts_source']} |",
        f"| reopened issues | {keys['reopened_issues']} of "
        f"{keys['reopened_events_scanned']} events | {keys['reopened_source']} |",
        "",
        f"Dominant key: **{keys['dominant_key']}**. Revert/reopen are near-empty on",
        "this corpus; fix-forward is the join key.",
        "",
        "## Result",
        "",
        f"- pairs: {len(records)}",
        f"- confirmed (earlier PR merged + merge-time features): {len(confirmed)}",
        f"- could_not_determine (ref was an issue, or earlier PR unmerged): {len(cnd)}",
        "",
        "## Earlier-PR merge-time-observable features (constraint 2)",
        "",
        "Each confirmed record carries ONLY these features of the earlier PR, all",
        "observable at its merge time; nothing derived from the fix-forward PR or from",
        "after the earlier PR merged (reviews/comments are filtered to <= mergedAt):",
        "",
        "`" + "`, `".join(MERGE_TIME_FEATURE_KEYS) + "`",
        "",
        "## Confirmed pairs (earlier PR -> fix-forward PR)",
        "",
        "| earlier PR | fix-forward PR | adds/dels | files | tests | reviews | hrs-to-merge |",
        "|---:|---:|---|---:|---:|---:|---:|",
    ]
    for r in confirmed:
        f = r["earlier_pr_merge_time_features"]
        lines.append(
            f"| #{r['earlier_pr']} | #{r['fix_forward_pr']} | "
            f"{f['additions']}/{f['deletions']} | {f['scope_files']} | "
            f"{f['test_files_changed']} | {f['review_count']} | {f['hours_to_merge']} |"
        )
    lines += [
        "",
        "## Bar-2 guard (do not skip)",
        "",
        "This is the POSITIVE CLASS ONLY. It is a failure-only sample until a control",
        "of non-fix-forward PRs is measured with the identical feature extractor. Do",
        "NOT promote any pattern from this table alone -- differentiation against a base",
        "rate is the Layer-3 next slice. A feature that is merely present here may be",
        "just as present in PRs that were never fixed forward.",
        "",
        "## Deferred",
        "- Control sample + base-rate differentiation (Layer 3).",
        "- Tier 2 (session -> PR), gated on transcript-complete; building-biased.",
        "- The near-empty revert / reopened-issue keys (cheap add-ons).",
    ]
    return "\n".join(lines) + "\n"


# --- main ------------------------------------------------------------------

def _print_dry_run(repo: str, out_dir: str, limit: int) -> None:
    print("DRY RUN -- forward_link.py Tier 1 (no execution)")
    print(f"  repo (read-only): {repo}")
    print(f"  out-dir: {out_dir}/forward-links.jsonl (gitignored)")
    print("  gh commands that WOULD run:")
    print(f"    gh api repos/{repo}/commits/main --jq .sha")
    print(f"    gh pr list --repo {repo} --state all --search "
          f"'{FIX_FORWARD_TERMS}' --limit 300 --json number   (key discovery)")
    print(f"    gh search commits --repo {repo} 'This reverts commit' --limit 100   (key discovery)")
    print(f"    gh pr list --repo {repo} --state all --search "
          f"'{FIX_FORWARD_TERMS}' --limit {limit} --json number,title,body")
    print(f"    gh pr view <earlier#> --repo {repo} --json number,additions,"
          "deletions,changedFiles,files,reviews,comments,createdAt,mergedAt,state")
    print("  then: build pairs, extract merge-time features (constraint 2), "
          "write jsonl + docs/forward-link-findings.md")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--out-dir", default="out-atlas-fwd")
    ap.add_argument("--limit", type=int, default=200,
                    help="max fix-forward PRs to pull")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        _print_dry_run(args.repo, args.out_dir, args.limit)
        return

    query_date = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    keys = key_discovery(args.repo)
    ffs = fetch_fix_forward_prs(args.repo, args.limit)
    pairs = build_pairs(ffs)

    nums = [p["earlier_pr"] for p in pairs] + [p["fix_forward_pr"] for p in pairs]
    corpus = {
        "dataset": args.out_dir,
        "pin": {
            "repo": args.repo,
            "query_date": query_date,
            "atlas_head_sha": gh_head_sha(args.repo),
            "pr_range": [min(nums), max(nums)] if nums else [None, None],
        },
    }

    view_cache: dict[int, object] = {}
    records = []
    for pair in pairs:
        a = pair["earlier_pr"]
        if a not in view_cache:
            view_cache[a] = fetch_pr_view(args.repo, a)
        records.append(assemble_record(pair, corpus, view_cache[a]))

    out_dir = Path(args.out_dir)
    write_jsonl(out_dir / "forward-links.jsonl", records)
    Path("docs/forward-link-findings.md").write_text(
        render_findings_doc(corpus, keys, records), encoding="utf-8"
    )

    confirmed = sum(1 for r in records if r["classification"] == "confirmed")
    print(f"forward-link Tier 1: {len(pairs)} pairs "
          f"({confirmed} confirmed, {len(records) - confirmed} could_not_determine)")
    print(f"  key discovery: {keys}")
    print(f"  wrote {out_dir}/forward-links.jsonl (gitignored) + "
          "docs/forward-link-findings.md")


if __name__ == "__main__":
    main()
