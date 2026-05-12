#!/usr/bin/env python3
"""
parse.py — Extract episodes from a Claude Code JSONL session transcript.

An "episode" is one user text turn plus the assistant work that followed
(text + tool calls + tool results) up until the next user text turn.

Outputs:
  out/episodes.json  — structured, archival (full tool input args kept)
  out/episodes.md    — condensed, LLM-ready (one block per episode)

No LLM calls. All local. Free.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def est_tokens(s: str) -> int:
    return max(1, len(s) // 4)


# ---------- session discovery ----------

def find_recent_sessions(limit: int = 20) -> list[Path]:
    if not CLAUDE_PROJECTS_DIR.exists():
        return []
    files: list[tuple[float, Path]] = []
    for p in CLAUDE_PROJECTS_DIR.rglob("*.jsonl"):
        try:
            files.append((p.stat().st_mtime, p))
        except OSError:
            continue
    files.sort(reverse=True)
    return [p for _, p in files[:limit]]


def pick_session(sessions: list[Path]) -> Path:
    if not sessions:
        print(f"No .jsonl sessions found in {CLAUDE_PROJECTS_DIR}", file=sys.stderr)
        sys.exit(1)
    print(f"\nRecent sessions in {CLAUDE_PROJECTS_DIR}:\n")
    for i, p in enumerate(sessions, 1):
        mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        size_kb = p.stat().st_size // 1024
        print(f"  [{i:2d}] {mtime}  {size_kb:>7d} KB  {p.parent.name}/{p.stem[:8]}")
    print()
    choice = input(f"Pick session [1-{len(sessions)}] (default 1): ").strip() or "1"
    try:
        return sessions[int(choice) - 1]
    except (ValueError, IndexError):
        print(f"Invalid choice: {choice}", file=sys.stderr)
        sys.exit(1)


# ---------- JSONL reading ----------

def read_jsonl(path: Path) -> Iterable[dict]:
    with path.open() as f:
        for line_no, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"  warn: skipping malformed line {line_no}: {e}", file=sys.stderr)


# ---------- content extraction ----------

SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)


def is_pure_tool_result(content: Any) -> bool:
    if not isinstance(content, list) or not content:
        return False
    return all(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def extract_user_text(content: Any) -> str:
    """Human-typed text only. Strips <system-reminder> blocks (harness noise)."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif isinstance(b, str):
                parts.append(b)
        text = "\n".join(parts)
    else:
        return ""
    return SYSTEM_REMINDER_RE.sub("", text).strip()


def extract_assistant_blocks(content: Any) -> tuple[str, list[dict]]:
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        return "", []
    text_parts: list[str] = []
    tool_uses: list[dict] = []
    for b in content:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text":
            text_parts.append(b.get("text", ""))
        elif t == "tool_use":
            tool_uses.append({
                "id": b.get("id"),
                "name": b.get("name"),
                "input": b.get("input", {}),
            })
    return "\n".join(text_parts).strip(), tool_uses


def _tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(b.get("text", ""))
                elif b.get("type") == "tool_result":
                    parts.append(_tool_result_text(b.get("content")))
        return "\n".join(parts)
    return ""


def extract_tool_results(content: Any) -> list[dict]:
    out = []
    if not isinstance(content, list):
        return out
    for b in content:
        if isinstance(b, dict) and b.get("type") == "tool_result":
            out.append({
                "tool_use_id": b.get("tool_use_id"),
                "is_error": bool(b.get("is_error", False)),
                "content": _tool_result_text(b.get("content")),
            })
    return out


# ---------- episode model ----------

@dataclass
class ToolCall:
    name: str
    input_summary: str
    raw_input: dict
    result_status: str       # ok | error | missing
    result_lines: int
    result_bytes: int
    result_tail: str         # last ~20 lines if error, else ""


@dataclass
class Episode:
    index: int
    timestamp: str | None
    gap_seconds_from_prev: int | None
    user_text: str
    assistant_text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    has_tool_error: bool = False
    tool_count: int = 0
    user_tokens_est: int = 0
    assistant_tokens_est: int = 0
    raw_message_count: int = 0


def _short(v: Any, n: int = 80) -> str:
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


# Diagnostic keys: keep more characters because truncating these (especially
# `command`) hides the literal action and forces the analyzer to guess.
_LONG_KEYS = {"command", "file_path", "path"}
_LONG_LIMIT = 300


def summarize_tool_input(inp: dict) -> str:
    if not isinstance(inp, dict) or not inp:
        return ""
    priority = ["file_path", "path", "command", "pattern", "url", "query"]
    bits, seen = [], set()
    for k in priority:
        if k in inp:
            limit = _LONG_LIMIT if k in _LONG_KEYS else 80
            bits.append(f"{k}={_short(inp[k], limit)}")
            seen.add(k)
    for k, v in inp.items():
        if k not in seen:
            limit = _LONG_LIMIT if k in _LONG_KEYS else 80
            bits.append(f"{k}={_short(v, limit)}")
    return ", ".join(bits)


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


# ---------- episode assembly ----------

def build_episodes(records: list[dict]) -> list[Episode]:
    """
    Walk records in order. An episode starts at a user message containing
    human text. Tool-result-only user messages and assistant messages get
    attached to the current episode.
    """
    episodes: list[Episode] = []
    cur: Episode | None = None
    tool_index: dict[str, ToolCall] = {}

    def attach_tool_results(content: Any) -> bool:
        if cur is None:
            return False
        attached = False
        for tr in extract_tool_results(content):
            tc = tool_index.get(tr["tool_use_id"])
            if tc is None:
                continue
            txt = tr["content"] or ""
            tc.result_bytes = len(txt)
            tc.result_lines = txt.count("\n") + (1 if txt else 0)
            if tr["is_error"]:
                tc.result_status = "error"
                # Keep a generous tail for errors (~20 lines, capped at 800B).
                tc.result_tail = "\n".join(txt.splitlines()[-20:])[-800:]
            else:
                tc.result_status = "ok"
                # Keep a brief success tail (last ~3 lines, capped at 200B).
                # This is what lets the analyzer verify e.g. commit hashes,
                # pytest summaries, "File created" messages -- evidence that
                # the prose-only narration is NOT a substitute for.
                tc.result_tail = "\n".join(txt.splitlines()[-3:])[-200:]
            attached = True
        return attached

    for rec in records:
        # Skip sub-agent / sidechain traffic for MVP — focus on the main thread.
        if rec.get("isSidechain"):
            continue

        msg = rec.get("message") or {}
        role = msg.get("role") or rec.get("type")
        content = msg.get("content")
        ts = rec.get("timestamp")

        if role == "user":
            if is_pure_tool_result(content):
                if attach_tool_results(content) and cur is not None:
                    cur.raw_message_count += 1
                continue

            user_text = extract_user_text(content)
            if not user_text:
                # Empty after stripping reminders — noise.
                continue

            # New episode.
            if cur is not None:
                episodes.append(cur)
            tool_index = {}
            cur = Episode(
                index=len(episodes),
                timestamp=ts,
                gap_seconds_from_prev=None,
                user_text=user_text,
                assistant_text="",
                raw_message_count=1,
            )

        elif role == "assistant":
            if cur is None:
                continue
            text, tool_uses = extract_assistant_blocks(content)
            if text:
                cur.assistant_text = (cur.assistant_text + "\n" + text).strip() if cur.assistant_text else text
            for tu in tool_uses:
                tc = ToolCall(
                    name=tu["name"] or "?",
                    input_summary=summarize_tool_input(tu["input"] if isinstance(tu["input"], dict) else {}),
                    raw_input=tu["input"] if isinstance(tu["input"], dict) else {},
                    result_status="missing",
                    result_lines=0,
                    result_bytes=0,
                    result_tail="",
                )
                cur.tool_calls.append(tc)
                if tu["id"]:
                    tool_index[tu["id"]] = tc
            cur.raw_message_count += 1

        # system / summary / unknown — skip.

    if cur is not None:
        episodes.append(cur)

    # Post-pass: derived signals + gaps.
    prev_dt: datetime | None = None
    for ep in episodes:
        ep.tool_count = len(ep.tool_calls)
        ep.has_tool_error = any(tc.result_status == "error" for tc in ep.tool_calls)
        ep.user_tokens_est = est_tokens(ep.user_text)
        ep.assistant_tokens_est = est_tokens(ep.assistant_text)
        dt = parse_ts(ep.timestamp)
        if dt and prev_dt:
            ep.gap_seconds_from_prev = int((dt - prev_dt).total_seconds())
        if dt:
            prev_dt = dt
    return episodes


# ---------- rendering ----------

def _blockquote(s: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in s.splitlines())


def _fmt_gap(seconds: int | None) -> str:
    if seconds is None:
        return "first"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h{(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d{(seconds % 86400) // 3600}h"


def render_md(episodes: list[Episode], session_path: Path) -> str:
    lines: list[str] = [
        "# Session episodes",
        "",
        f"Source: `{session_path}`",
        f"Episodes: {len(episodes)}",
        "",
        "---",
        "",
    ]
    for ep in episodes:
        ts = ep.timestamp or "unknown"
        lines += [
            f"## Episode {ep.index} — {ts} (gap: {_fmt_gap(ep.gap_seconds_from_prev)})",
            "",
            f"*tokens_est: user={ep.user_tokens_est}, assistant={ep.assistant_tokens_est} | "
            f"tools={ep.tool_count}, tool_error={ep.has_tool_error}*",
            "",
            "**User:**",
            "",
            _blockquote(ep.user_text),
            "",
        ]
        if ep.assistant_text:
            lines += [
                "**Assistant (text):**",
                "",
                _blockquote(ep.assistant_text),
                "",
            ]
        if ep.tool_calls:
            lines.append("**Tools:**")
            for tc in ep.tool_calls:
                status = {"ok": "ok", "error": "ERROR", "missing": "no-result"}[tc.result_status]
                lines.append(
                    f"- `{tc.name}({tc.input_summary})` → {status} "
                    f"[{tc.result_lines} lines, {tc.result_bytes} B]"
                )
                if tc.result_tail:
                    lines.append("  ```")
                    for tl in tc.result_tail.splitlines():
                        lines.append(f"  {tl}")
                    lines.append("  ```")
            lines.append("")
        lines += ["---", ""]
    return "\n".join(lines)


SOURCE_FORMAT = "claude_code_jsonl"


def to_json(episodes: list[Episode], session_path: Path) -> str:
    payload = {
        "source_format": SOURCE_FORMAT,
        "source": str(session_path),
        "episode_count": len(episodes),
        "episodes": [
            {**asdict(ep), "tool_calls": [asdict(tc) for tc in ep.tool_calls]}
            for ep in episodes
        ],
    }
    return json.dumps(payload, indent=2, default=str)


# ---------- main ----------

def main() -> None:
    ap = argparse.ArgumentParser(description="Extract episodes from a Claude Code JSONL session.")
    ap.add_argument("session", nargs="?", help="Path to .jsonl session. If omitted, picks interactively.")
    ap.add_argument("-o", "--out-dir", default="out", help="Output directory (default: out/)")
    args = ap.parse_args()

    if args.session:
        session_path = Path(args.session).expanduser()
        if not session_path.exists():
            print(f"Not found: {session_path}", file=sys.stderr)
            sys.exit(1)
    else:
        session_path = pick_session(find_recent_sessions())

    print(f"\nParsing {session_path} …")
    records = list(read_jsonl(session_path))
    print(f"  {len(records)} records")

    episodes = build_episodes(records)
    print(f"  {len(episodes)} episodes")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "episodes.json"
    md_path = out_dir / "episodes.md"
    json_path.write_text(to_json(episodes, session_path))
    md_path.write_text(render_md(episodes, session_path))

    total = sum(ep.user_tokens_est + ep.assistant_tokens_est for ep in episodes)
    err_count = sum(1 for ep in episodes if ep.has_tool_error)
    print()
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print()
    print(f"  total est. tokens (trimmed view): {total:,}")
    print(f"  episodes with tool error:         {err_count}")


if __name__ == "__main__":
    main()
