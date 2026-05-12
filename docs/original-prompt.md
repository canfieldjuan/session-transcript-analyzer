# Original Design Prompt

> Saved verbatim from the initiating conversation, with two edits per user direction:
> 1. "Hunger" removed as a state signal — treated as noise.
> 2. Timestamp extraction added as a first-class concern (degradation over time-of-day).
>
> Scope note from user: this project may be more complex than it looks. Start with the **absolute minimum** first — do not over-build.

---

You are helping me design a local coding-session transcript analyzer.

## Goal
Build a forensic diagnostic tool for coding-session transcripts.

The system should identify interaction patterns that lead to:
- bad code
- weak architecture
- rework
- contradictions
- skipped verification
- bad coding practices
- prompt failures
- model response failures
- degraded performance when I am frustrated, rushed, tired, stressed, or confused

Do not write production code yet.

We are starting with a proof-of-concept using 10 to 20 prompt-response episodes from one frustrating coding session.

## Core principle
Use zero-trust reasoning.
Do not infer beyond evidence.
Use `unknown` when evidence is missing.
Do not claim code correctness unless supported by tests, compiler output, runtime output, user correction, or explicit later verification.

## Separate analysis into

### 1. User-side analysis
- prompts and inputs
- explicit requirements
- implicit requirements
- architecture decisions
- constraints
- conflicts inside the prompt
- conflicts with earlier known decisions
- missing prerequisites
- things I should have done first
- prompt patterns likely to cause bad code
- sentiment and state signals

### 2. Model-side analysis
- how the model interpreted the request
- assumptions the model made
- questions the model asked
- questions the model should have asked but did not
- architectural changes proposed
- code/design actions proposed
- constraints ignored or missed
- bad-practice risks
- verification gaps
- whether the response likely increased or reduced risk

## Sentiment scoring
Use a 0–5 scale with qualitative anchors.
Every score must include:
- score
- label
- evidence
- confidence
- why_not_higher
- why_not_lower

Do not use generic sentiment libraries.
Sentiment must be coding-context aware.

## Timestamps (added)
- Extract message timestamps when present in the transcript.
- Preserve them on every event/episode so we can correlate quality with time-of-day, session-elapsed-time, and consecutive-hours-coding.
- If a timestamp is missing, record `timestamp: unknown` rather than guessing.

## Rolling context
Episode extraction must receive a `rolling_state_before` object containing:
- current task goal
- active architecture decisions
- active constraints
- unresolved requirements
- known user preferences
- open TODOs
- prior contradictions
- known model failure patterns

Episode extraction must output:
1. `episode_analysis`
2. `rolling_state_updates`

Do not rely on hidden memory.

## Before code
1. Define event schema.
2. Define episode schema.
3. Define episode-analysis schema.
4. Define rolling-state schema.
5. Define fixed label taxonomy.
6. Define anchored sentiment rubric.
7. Run a taxonomy collision test.
8. Create synthetic test episodes.
9. Create expected JSON outputs for synthetic episodes.
10. Define manual validation checklist.
11. Define first pattern-report format.
12. Give first implementation steps.

## Taxonomy collision test
For each major label group:
- user prompt risks
- architecture risks
- model response risks
- workflow mistakes
- sentiment/state signals

Create at least 3 ambiguous events that could plausibly fit multiple labels.
For each:
- list possible labels
- choose primary label
- choose secondary labels
- explain rejected labels
- refine definitions if needed

## Do not build yet
- dashboards
- vector search
- database layer
- automated prompt improver loop
- real-time intervention system
- IDE plugin
- full transcript ingestion
- multi-model judge panel
- elaborate UI

## Deliverables
1. Proposed file/folder structure
2. Event schema
3. Episode schema
4. Rolling-state schema
5. Episode-analysis schema
6. Fixed label taxonomy
7. Anchored sentiment rubric
8. Taxonomy collision test
9. Synthetic test episodes
10. Expected JSON output for synthetic episodes
11. Extractor prompt
12. Pattern-report prompt
13. Manual validation checklist
14. First 5 implementation steps

Be blunt about complexity and failure modes.
Prioritize small, testable steps.
