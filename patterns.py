#!/usr/bin/env python3
"""
patterns.py — Layer 3 of the session-transcript-analyzer.

Reads out/analysis.jsonl (from analyze.py) plus out/episodes.json (for
timestamps and gap_seconds_from_prev), pre-aggregates locally, then asks
Opus 4.7 to write one cross-episode pattern report.

Output: out/patterns-report.md

Pre-aggregation strategy (same principle as Layer 1):
  - Risk-flag frequencies and co-occurrence: counted locally.
  - Hour-of-day breakdown: computed locally in the user's timezone.
  - Gap-bucket breakdown: computed locally from episodes.json.
  - Verify distribution: counted locally.
The LLM receives the aggregates plus all per-episode analyses (compact JSON
lines), and is asked to interpret -- not to count.

Cost: ~$2-4 for ~300 records. One Opus call.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # type: ignore
except ImportError:
    ZoneInfo = None  # type: ignore
    ZoneInfoNotFoundError = Exception  # type: ignore

try:
    from anthropic import Anthropic  # type: ignore
except ImportError:
    Anthropic = None  # type: ignore


MODEL = "claude-opus-4-7"
MAX_OUTPUT_TOKENS = 6000


SYSTEM_PROMPT = """You are a forensic pattern analyst.

You receive (1) pre-computed aggregate statistics and (2) all per-episode
analyses from a coding-session forensic pass. Your job is to write ONE
structured pattern report that the human user (the person doing the coding)
will read to understand their own habits.

OUTPUT FORMAT: Markdown only. Use the exact sections below, in order. Do
not add other sections. Do not fabricate signal -- if the evidence does not
support a claim, say "no signal" or "insufficient data".

# Pattern report

## Headline finding
ONE sentence: the single most important pattern in this dataset. This goes
at the top because if the user only reads one thing, this is it.

## The user's worst recurring habit
ONE concrete sentence with evidence. What is the one thing this person
keeps doing that produces bad outcomes? Reference specific risk flags and
episode counts. Do NOT flatter. If the user has many bad habits, pick the
costliest -- the one that, if fixed, would prevent the most rework.

## The model's worst recurring behavior
ONE concrete sentence with evidence. What is the one thing the assistant
keeps doing that produces bad outcomes? Common candidates: not asking
clarifying questions, claiming verification without tool evidence, bypassing
safety checks. Reference specific risk flags and episode counts.

## Top risk-flag co-occurrence pairs
The 3-5 most informative pairs of flags that fire together, ranked by
diagnostic value (not just raw count). For each:
- `flag_a` + `flag_b`: <N> episodes (e.g. eps 12, 45, 91). <one sentence
  interpreting what this pair means about the user's workflow>.

## Time-of-day correlation
Use the hour-of-day table provided in the aggregates. Identify whether
late-hour episodes (in the user's local time) have meaningfully higher
rates of negative flags compared to daytime episodes. If no significant
correlation exists, say so explicitly. Do not invent a curve. Cite
specific hours and the per-hour flag rates.

## Session-resumption correlation
Compare episodes that follow a long gap (> 4 hours = "fresh start") vs
episodes with short gaps ("grinding"). Are flag rates different? Cite
the gap-bucket aggregates. If insufficient samples in any bucket, say so.

## Intent vs execution divergence
Are there episodes where the user gave a short or ambiguous prompt and the
model took expansive autonomous action? Cite specific episodes. This is
the "took the wheel" failure mode -- it may be invisible in per-episode
analysis because the tools all succeeded, but it is visible here when you
see vague_requirements co-occurring with verify=yes and high tool_count.

## What the user should change first
ONE actionable sentence: the single behavior change most likely to improve
session quality based on the data. Be specific. "Be more careful" is NOT
acceptable. "Stop using 'just' and 'real fast' in prompts; reserve them
for genuinely one-line tasks" IS acceptable.

## What the user should NOT conclude
Important. List 1-3 plausible-sounding interpretations that the data does
NOT support. This protects against the user over-reading the report.
Example: "The data shows verification rate is lowest at 2-4am, but the
sample size at those hours is N=3, so do not conclude this is a robust
pattern."

ZERO-TRUST RULES
- Every claim must reference the aggregated data or specific episode indices.
- Distinguish "X correlates with Y in this dataset" from "X causes Y".
- Do not infer mood, fatigue, or physical state.
- If the dataset is too small for a claim, say so out loud.
- Do not flatter the user. Do not flatter the model. The point of the
  report is to make both the user and the assistant visibly worse, so the
  user can fix what is fixable on their side and adjust their reliance
  on the assistant accordingly."""


# ---------- aggregation ----------

def _hour_in_tz(ts: str, tz) -> int | None:
    if not ts or ts == "unknown":
        return None
    try:
        s = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
        dt = datetime.fromisoformat(s)
        if tz is not None:
            dt = dt.astimezone(tz)
        else:
            dt = dt.astimezone()  # system local TZ
        return dt.hour
    except (ValueError, TypeError):
        return None


def _gap_bucket(gap_seconds: int | None) -> str:
    if gap_seconds is None:
        return "first_episode"
    if gap_seconds < 300:
        return "lt_5m"
    if gap_seconds < 1800:
        return "5m_to_30m"
    if gap_seconds < 14400:
        return "30m_to_4h"
    return "gt_4h"


def aggregate(
    records: list[dict],
    episodes_by_idx: dict[int, dict],
    tz,
) -> dict:
    n = len(records)

    flag_counter: Counter[str] = Counter()
    flag_to_eps: dict[str, list[int]] = defaultdict(list)
    for r in records:
        for f in r.get("risk_flags") or []:
            flag_counter[f] += 1
            flag_to_eps[f].append(r["episode_index"])

    co_counter: Counter[tuple[str, str]] = Counter()
    co_to_eps: dict[tuple[str, str], list[int]] = defaultdict(list)
    for r in records:
        flags = sorted(set(r.get("risk_flags") or []))
        for i, a in enumerate(flags):
            for b in flags[i + 1 :]:
                co_counter[(a, b)] += 1
                co_to_eps[(a, b)].append(r["episode_index"])

    verify_counter: Counter[str] = Counter(
        r.get("did_model_verify", "unknown") for r in records
    )

    # Hour-of-day: count, no_verification, flag totals
    by_hour: dict[int, dict] = {
        h: {"count": 0, "verify_no": 0, "flags": Counter()} for h in range(24)
    }
    for r in records:
        h = _hour_in_tz(r.get("timestamp", ""), tz)
        if h is None:
            continue
        by_hour[h]["count"] += 1
        if r.get("did_model_verify") == "no":
            by_hour[h]["verify_no"] += 1
        for f in r.get("risk_flags") or []:
            by_hour[h]["flags"][f] += 1

    # Gap buckets
    by_gap: dict[str, dict] = {
        b: {"count": 0, "verify_no": 0, "flags": Counter()}
        for b in ("first_episode", "lt_5m", "5m_to_30m", "30m_to_4h", "gt_4h")
    }
    for r in records:
        ep = episodes_by_idx.get(r["episode_index"])
        gap = ep.get("gap_seconds_from_prev") if ep else None
        bucket = _gap_bucket(gap)
        by_gap[bucket]["count"] += 1
        if r.get("did_model_verify") == "no":
            by_gap[bucket]["verify_no"] += 1
        for f in r.get("risk_flags") or []:
            by_gap[bucket]["flags"][f] += 1

    return {
        "n": n,
        "verify_counter": verify_counter,
        "flag_counter": flag_counter,
        "flag_to_eps": flag_to_eps,
        "co_counter": co_counter,
        "co_to_eps": co_to_eps,
        "by_hour": by_hour,
        "by_gap": by_gap,
    }


# ---------- rendering for the LLM ----------

def _fmt_eps_list(eps: list[int], limit: int = 10) -> str:
    if not eps:
        return ""
    if len(eps) <= limit:
        return ", ".join(str(e) for e in eps)
    return ", ".join(str(e) for e in eps[:limit]) + f", … (+{len(eps) - limit} more)"


def render_aggregates(agg: dict, tz_label: str) -> str:
    n = agg["n"]
    lines = []
    lines.append(f"# Aggregates (pre-computed, do not re-count)")
    lines.append("")
    lines.append(f"total_episodes_analyzed: {n}")
    lines.append(f"timezone_for_hour_of_day: {tz_label}")
    lines.append("")
    lines.append("## verify distribution")
    for label in ("yes", "no", "unknown"):
        c = agg["verify_counter"].get(label, 0)
        pct = (c / n * 100) if n else 0
        lines.append(f"- {label}: {c} ({pct:.0f}%)")
    lines.append("")
    lines.append("## risk_flag frequencies")
    for flag, c in agg["flag_counter"].most_common():
        pct = (c / n * 100) if n else 0
        eps = _fmt_eps_list(agg["flag_to_eps"][flag])
        lines.append(f"- `{flag}`: {c} ({pct:.0f}%) — eps [{eps}]")
    lines.append("")
    lines.append("## flag co-occurrence (top 15 by count)")
    for (a, b), c in agg["co_counter"].most_common(15):
        eps = _fmt_eps_list(agg["co_to_eps"][(a, b)])
        lines.append(f"- `{a}` + `{b}`: {c} — eps [{eps}]")
    lines.append("")
    lines.append("## hour-of-day breakdown")
    lines.append("hour | count | verify_no | top flags")
    lines.append("---- | ----- | --------- | ---------")
    for h in range(24):
        b = agg["by_hour"][h]
        if b["count"] == 0:
            continue
        top = ", ".join(f"{f}({c})" for f, c in b["flags"].most_common(3))
        lines.append(f"{h:02d}   | {b['count']:>5} | {b['verify_no']:>9} | {top}")
    lines.append("")
    lines.append("## gap-bucket breakdown (time from previous episode)")
    lines.append("bucket           | count | verify_no | top flags")
    lines.append("---------------- | ----- | --------- | ---------")
    for bucket in ("first_episode", "lt_5m", "5m_to_30m", "30m_to_4h", "gt_4h"):
        b = agg["by_gap"][bucket]
        top = ", ".join(f"{f}({c})" for f, c in b["flags"].most_common(3))
        lines.append(f"{bucket:<16} | {b['count']:>5} | {b['verify_no']:>9} | {top}")
    lines.append("")
    return "\n".join(lines)


def render_records(records: list[dict]) -> str:
    """Compact one-line-per-record dump of all analyses."""
    lines = ["# Per-episode analyses (compact)"]
    for r in records:
        compact = {
            "i": r.get("episode_index"),
            "ts": r.get("timestamp"),
            "verify": r.get("did_model_verify"),
            "flags": r.get("risk_flags") or [],
            "ask": r.get("what_user_asked"),
            "did": r.get("what_model_did"),
            "notes": r.get("notes"),
        }
        lines.append(json.dumps(compact, ensure_ascii=False))
    return "\n".join(lines)


# ---------- main ----------

def _require_anthropic():
    if Anthropic is None:
        print(
            "Missing dependency. Run: pip install -r requirements.txt",
            file=sys.stderr,
        )
        sys.exit(1)


def _resolve_tz(name: str | None):
    if not name or name == "local":
        return None
    if ZoneInfo is None:
        print(f"zoneinfo not available; falling back to local time", file=sys.stderr)
        return None
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        print(f"Unknown timezone: {name!r}. Falling back to local.", file=sys.stderr)
        return None


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Cross-episode pattern report with Opus 4.7."
    )
    ap.add_argument(
        "--analyses", default="out/analysis.jsonl",
        help="Path to analysis.jsonl (default: out/analysis.jsonl)",
    )
    ap.add_argument(
        "--episodes", default="out/episodes.json",
        help="Path to episodes.json for timestamps + gaps (default: out/episodes.json)",
    )
    ap.add_argument(
        "--out-dir", default="out", help="Output directory (default: out/)",
    )
    ap.add_argument(
        "--tz", default="local",
        help='Timezone for hour-of-day buckets, IANA name (e.g. "America/Los_Angeles"). Default: system local.',
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Print the assembled prompt (system + user) and exit. No API call.",
    )
    args = ap.parse_args()

    analyses_path = Path(args.analyses)
    episodes_path = Path(args.episodes)
    if not analyses_path.exists():
        print(f"Not found: {analyses_path}. Run analyze.py first.", file=sys.stderr)
        sys.exit(1)
    if not episodes_path.exists():
        print(f"Not found: {episodes_path}. Run parse.py first.", file=sys.stderr)
        sys.exit(1)

    records: list[dict] = []
    for line in analyses_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not records:
        print("No analysis records found.", file=sys.stderr)
        sys.exit(1)

    episodes_data = json.loads(episodes_path.read_text())
    episodes_by_idx = {ep["index"]: ep for ep in episodes_data["episodes"]}

    tz = _resolve_tz(args.tz)
    tz_label = args.tz if args.tz != "local" else "system local"

    print(f"Loaded {len(records)} analysis records")
    print(f"Loaded {len(episodes_by_idx)} episodes for structural context")
    print(f"Timezone for hour-of-day: {tz_label}")

    agg = aggregate(records, episodes_by_idx, tz)
    aggregates_md = render_aggregates(agg, tz_label)
    records_md = render_records(records)
    user_msg = aggregates_md + "\n\n" + records_md

    if args.dry_run:
        print("\n----- SYSTEM PROMPT -----\n")
        print(SYSTEM_PROMPT)
        print("\n----- USER MESSAGE (aggregates + records) -----\n")
        print(user_msg)
        print("\n----- (dry run, no API call) -----")
        return

    _require_anthropic()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set. export it and re-run.", file=sys.stderr)
        sys.exit(1)
    client = Anthropic()

    print(f"\nCalling {MODEL} for pattern report …")
    msg = client.messages.create(
        model=MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    report = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "patterns-report.md"
    report_path.write_text(report)

    in_cost = msg.usage.input_tokens * 15 / 1_000_000
    out_cost = msg.usage.output_tokens * 75 / 1_000_000
    print(f"\nWrote {report_path}")
    print(
        f"  input_tokens:  {msg.usage.input_tokens:,}  (${in_cost:.4f})"
    )
    print(
        f"  output_tokens: {msg.usage.output_tokens:,}  (${out_cost:.4f})"
    )
    print(f"  total cost:    ${in_cost + out_cost:.4f}")


if __name__ == "__main__":
    main()
