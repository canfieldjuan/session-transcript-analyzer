# Verifying analyze.py

The local session runs this. The cloud session built it. Goal: confirm the
analyzer produces useful, evidence-bound output before we trust it on bigger
slices.

---

## 0a. Changes since the first verification pass

If this is your second (or later) pass, here's what's new:

- **Prefill removed** — this Sonnet variant doesn't support assistant-message
  prefill. The model now returns a bare JSON object; `extract_first_json`
  locates it.
- **Anti-bias hardened** — explicit rule: a commit hash, test count, or
  success claim in the assistant's prose does NOT count as verification.
  Only `tail:` content from tool results counts. New flag
  `evidence_lifted_from_prose` captures this failure mode.
- **`long_grind` threshold dropped to 15** (from 20) — matches what the
  analyzer was already firing in practice.
- **`max_tokens` bumped to 800** — guards against the ep-169 cutoff case.
- **Incomplete responses are now skipped, not written** — no more degenerate
  records with only `episode_index` + `timestamp`.
- **`parse.py` keeps a success tail for every tool result** (last ~3 lines,
  200B max) so the analyzer can see commit hashes, pytest summaries, "File
  updated" — the evidence that distinguishes verification from prose.
- **`parse.py` widened diagnostic-key truncation** (`command`, `file_path`,
  `path`) from 80 to 300 chars so long bash invocations aren't hidden.

These two `parse.py` changes alter the rendered episode shape, so **you
must re-run `parse.py` for the new rendering to apply.** Recommended flow:

```bash
rm out/episodes.json out/episodes.md out/analysis.jsonl
python3 parse.py
python3 analyze.py --first 10
python3 analyze.py --errors-only --first 14 --resume
```

---

## 0. Setup (one-time)

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # your key
```

Confirm `out/episodes.json` exists (run `python3 parse.py` first if not).

---

## 1. Dry-run — read the prompt before spending tokens

```bash
python3 analyze.py --first 1 --dry-run
```

This prints the system prompt and the rendered first episode without calling
the API.

**Verify:**
- [ ] System prompt is intact, includes the SCHEMA, ZERO-TRUST RULES, and
      ANTI-BIAS NOTE sections.
- [ ] The rendered episode contains the user's prompt verbatim (typos OK).
- [ ] Tool calls show `name(input_summary) -> status [N lines, M B]`.
- [ ] Error tails appear under `tail:` when present.
- [ ] No `<system-reminder>` blocks leaked through.

If any of those fail, stop and report back — it's a parse/render bug, not an
API issue.

---

## 2. Live run — 10 episodes, baseline

```bash
python3 analyze.py --first 10
```

Watch the per-episode lines stream by. Each line:

```
  [3/10] ep 2: verify=no flags=[vague_requirements,no_verification]
```

**Verify during the run:**
- [ ] No API errors.
- [ ] Every episode line completes with `verify=` and `flags=` populated.
- [ ] Cost looks reasonable (it'll print final total at the end).

Then read:

```bash
cat out/analysis-summary.md
```

**Verify in the summary:**
- [ ] Episodes analyzed = 10 (or however many succeeded).
- [ ] `did_model_verify` distribution looks defensible — if it's 10/10 "yes"
      with no errors anywhere, the analyzer is being too lenient. If it's
      10/10 "no" the prompt may be too strict. Real sessions usually mix.
- [ ] Top risk_flags has 3–7 recurring names. Not 30 one-off labels (means
      the analyzer is inventing) and not 1 dominant label (means it's lazy).
- [ ] Cost is under $1.

---

## 3. Spot-check three records

```bash
# View any specific record
python3 -c "
import json
for line in open('out/analysis.jsonl'):
    rec = json.loads(line)
    if rec['episode_index'] in (0, 4, 9):
        print(json.dumps(rec, indent=2))
        print()
"
```

For each spot-checked record, **cross-reference with `out/episodes.md`**:

- [ ] `what_user_asked` actually matches what you typed in that episode.
- [ ] `what_model_did` is accurate — not flattering, not exaggerating.
- [ ] If `did_model_verify == "yes"`, find the verifying evidence **in a
      tool result tail**, not in the assistant's prose. A successful
      `Bash(pytest) ... tail: 5 passed`, an `Edit ... tail: File updated`,
      a commit hash that appears in a `Bash(git commit) tail:` — those
      count. A commit hash that only appears in the assistant's text reply
      does NOT count.
- [ ] Each `risk_flag` has supporting evidence in `notes` or in the rendered
      episode. Flags without textual evidence = analyzer hallucination.

**Anti-bias spot-check (the ep-4 class of failure).** For every record
where `verify=yes`, run this:

1. Open `out/episodes.md` and locate the same episode.
2. Find the specific claim the analyzer used to justify `yes` in `notes`
   (e.g. "tool output confirmed commit hash fe6458ff").
3. Confirm that string (`fe6458ff` in this example) appears in a `tail:`
   block of a tool result. If it only appears in the `**Assistant (text):**`
   section — the analyzer credited assistant prose as tool output. That's
   the systemic bias and means the prompt is still leaking.

If 2+ records fail this check, the ANTI-BIAS NOTE needs another pass.

---

## 4. The pain pass — analyze error episodes

```bash
python3 analyze.py --errors-only --first 14 --resume
```

`--resume` skips anything already in `analysis.jsonl`. `--errors-only` picks
only episodes where `has_tool_error=True` (you have 62, this run takes the
first 14 of them).

**Verify:**
- [ ] These episodes' analyses have **higher rates** of `no_verification`,
      `bash_error_ignored`, or `bypassed_safety` than the baseline run. If
      not, the analyzer isn't seeing the difference between calm episodes
      and error episodes — that's a prompt failure.
- [ ] At least one episode flags `read_edit_thrash` if you've actually seen
      the model re-edit the same file 3+ times. Cross-check the episode's
      tool list in `episodes.md`.

---

## 5. Report back — what to tell the cloud session

A short note covering:

1. **Did anything crash?** If yes: command + stderr.
2. **`did_model_verify` distribution** across both runs.
3. **Top 5 risk_flags** by frequency.
4. **One episode where the analyzer was clearly wrong** (wrong verify,
   unsupported flag, or hallucinated `what_model_did`). Paste the JSON
   record and a quick note on what's wrong.
5. **One episode where the analyzer was clearly right** — ideally an error
   episode where it called out something you'd already noticed yourself.
6. **Total cost.**

That tells us whether to tune the prompt, expand the slice, or move on to
Layer 3 (cross-episode pattern report).
