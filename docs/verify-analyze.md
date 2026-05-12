# Verifying analyze.py

The local session runs this. The cloud session built it. Goal: confirm the
analyzer produces useful, evidence-bound output before we trust it on bigger
slices.

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
- [ ] If `did_model_verify == "yes"`, find the verifying tool call in the
      episode. A successful `Bash(pytest)` or `Bash(npm test)` or similar.
      No verification tool call = the analyzer is wrong, should be "no".
- [ ] Each `risk_flag` has supporting evidence in `notes` or in the rendered
      episode. Flags without textual evidence = analyzer hallucination.

If you find 2+ unsupported flags or wrong-direction verify calls, the prompt
needs tuning — note which episodes and report back.

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
