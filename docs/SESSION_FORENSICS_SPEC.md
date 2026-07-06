# Session Forensics System - Build Spec

## How to use this file
This is the step 1 contract, not a description of code to write blind.
Before writing code: read this whole spec, derive what a correct implementation
must touch and change, state what it must NOT touch, and write that plan down.
Build to that plan. Then reconstruct your own diff cold and check it against
this spec before calling anything done. The code is ground truth. This spec is
the standard the code is held to.

> CALIBRATION (2026-07-06): the strong keys in this spec are corpus-specific and
> must be DISCOVERED per corpus, not assumed. See "Forward-link: empirical
> calibration" below -- a corpus probe contradicted two of the three join keys
> this spec originally named. Run key-discovery against the real corpus before
> building any join.

## What we are actually building
A forensic audit of model behavior under coding and reviewing constraints, whose
output is preventative CI/CD measures. The system does not produce "findings."
It produces condition-to-behavior-to-prevention triples. Each triple names an
observable condition, the behavior that condition predicts, and the instrument
that can gate on that condition.

Generating question:
> What is the earliest observable condition that predicts a given failure, and
> what instrument can gate on that condition?

That is the only question whose answer is a preventative measure, because a
prevention needs a trigger to fire on.

## What we are NOT building (hard constraints)

1. NOT an intention detector.
   A transcript is behavior, not intention. The model's reasons are not in
   evidence. Any "why the model did X" answer a model gives is confabulation.
   Do not build any layer, field, or prompt that asks for or records the model's
   internal reason. Relocate every "why" to a "when": the observable condition
   present at the time (trigger, prior state, prompt shape, context contents,
   available-but-unused evidence, tool environment). WHAT is the behavior.
   WHEN is the condition, and WHEN is the only recoverable form of why.

2. NOT a failure-only sample.
   Sampling only failures produces coincidence patterns. Every candidate
   behavior must be measured against a base rate: how often the same behavior
   appears in non-failure sessions. A behavior earns durable-pattern status only
   if it is differentially present in failures. No contrast, no causal claim,
   no rule.

3. NOT organized around "evidence for done."
   The premature-done signature is ONE detector in layer 1, not the frame. Do
   not let it structure the system. It is a single row in the pattern library.

## The triple, and the three bars each must clear
A durable pattern is a (condition, behavior, prevention) triple. It is only
real when it clears all three:

- Proven: N independent confirmed instances, each citing the exact transcript
  span (session id, turn index, tool call) that shows it. No citation, not
  confirmed.
- Differentiated: measured against the base rate in clean sessions and shown to
  be differentially present in failures.
- Routable: collapses to a nameable condition an instrument can observe and
  gate on. If it cannot be named as a condition, it cannot become CI.

## Architecture

### Layer 1: mechanical detection
Cheap regex / heuristic scans surface candidate risk episodes. Examples:
no-verification, destructive commands, ignored bash errors, long grinds,
assumed-without-asking, premature-done, weak test assertions, no-test-added,
coverage drop. Layer 1 flags candidates only. It confirms nothing.

### Layer 2: adjudication (audit the auditor)
Layer 2 is model-run and therefore carries the same biases the system hunts
(confirm-bias, completion-bias, the pull to call a candidate confirmed because
confirming is cheap). It must run the same discipline demanded of a PR reviewer:

For each candidate:
1. Reconstruct the correct trajectory independently. Given only the transcript
   state up to that point, derive what the correct next action was. Do this
   without letting the flagged action tell you what should have happened.
2. Compare what the model actually did against that independent derivation.
3. Sort into confirmed, contradicted, or could-not-determine, with a transcript
   citation for every verdict. Do not report confirmed without a citation.

An adjudicator that eyeballs "was this bad" makes the whole system vibes
adjudicating vibes. The evidence standard is not optional here.

> Live proof this layer's bias is real, not theoretical: in the session that
> produced this spec, the step-3 reconstruction -- the step whose whole job is
> catching overclaims -- itself asserted a jsonl row it never read
> (`errors-and-loops.jsonl:cross_session:reconstruction-overclaim`). Layer 2's
> "I checked" must mean a cited read, especially in the check step.

### Layer 3: durable patterns
Confirmed sequences are grouped into reusable patterns only after they clear the
three bars above (proven, differentiated, routable). Layer 3 owns the base-rate
measurement. A pattern with no base rate is not promoted.

### The forward-link join (missing from the original three layers)
The most expensive failures are not visible in the session that causes them. A
weak test passes when written and fails weeks later. A symptom patch looks done
and reopens later. A missed edge case never shows in the transcript. Pure
in-session forensics is structurally blind to this class.

Build a forward link that joins:
- the session that wrote a test -> the later incident where that test failed to
  catch a regression
- the PR that patched a symptom -> the reopened issue
- the session that shipped a change -> a later revert or hotfix touching the
  same lines

This is a join across time. Without it, the entire latent-quality-risk class is
invisible.

### Forward-link: empirical calibration (corpus probe, 2026-07-06)
The three example join keys above are guesses at what the join might look like.
A probe against the real Atlas corpus contradicted two of the three. This is
the reconstruction discipline applied to the spec itself: check the keys against
the corpus, do not trust the examples.

Corpus: 416 session transcripts across 9 projects (487 MB). Atlas: 5,732
commits, 169 merge commits (near-total squash-merge), issues/PRs numbered to
~2000.

Strong-key hit counts in Atlas:

| key (spec example) | hits | verdict |
|---|---|---|
| `git revert` of a SHA | 0 | empty -- Atlas never git-reverts |
| reopened issue | 3 of 14,706 issue events | near-empty |
| **fix-forward PR** (regression/correction fix) | >= 46 with an earlier-#PR body reference (60 pulled, search capped) | THE Atlas join key |

Two of the three named keys were essentially absent. The real correction idiom
here is fix-forward: a later PR that repairs a flaw from earlier work
(`#2002 -> #2004`; `#1741 "Fix deflection PII scrub regression"`). The join
runs in two tiers of decreasing certainty:

- Tier 1 -- PR -> earlier flawed PR. Clean and dense: 46 of 60 fix-forward PRs
  cite the earlier PR in their body (`#2004 -> #1993/1994/2000/2002`). Git/GitHub
  only, NO transcript dependency. Build this first.
- Tier 2 -- earlier PR -> the session that made it. Partial: some PRs map to
  transcripts (`#1741` -> 2 sessions), some to none. This is where the
  later-proven flaw connects back to the in-session behavior/condition.

Ship Tier 1 first. It proves the class exists at scale before spending anything
on the hard session extraction -- prove the cheap dense half is real, give
Layer 3 something concrete to differentiate on, then pay for the partial
expensive half. Best-fit, not maximal.

#### Three durable constraints (each guards a trap that bites Layer 3)

1. STRONG KEYS ARE CORPUS-SPECIFIC -- DISCOVER, DO NOT ASSUME.
   Revert and reopen came up empty on Atlas; the real key was fix-forward. Every
   new corpus must re-run key discovery (count candidate keys against the corpus)
   before the join is built. A named key that is not measured is a guess.

2. TIER 1 DIFFERENTIATORS ARE RESTRICTED TO MERGE-TIME-OBSERVABLE FEATURES OF
   THE EARLIER PR.
   The dense clean PR->PR data gives only the EFFECT side: PR A was later
   repaired. It does NOT say what in A predicted that. If Layer 3 differentiates
   on features of A that are visible only in hindsight -- features that correlate
   with "got fixed" merely because both are downstream of the same latent flaw --
   the model POSTDICTS, not predicts. Restrict differentiating features to what
   was observable when A merged: A's diff shape, test delta, scope, review depth.
   Nothing that only became visible because the fix happened. The dense clean
   data is exactly what tempts you past this line.

3. TIER 2 LINKED-SUBSET IS BUILDING-BIASED; SESSION LINKAGE GATES ON
   TRANSCRIPT-COMPLETE.
   Partial coverage in Tier 2 is NOT random missingness. The sessions that link
   are the ones that shipped code; the sessions that do not link include the
   entire review and planning class (they ship nothing, so they cannot link by
   git ops). Therefore any Tier-2 pattern is a pattern about BUILDING and says
   nothing about review or planning failures -- and the seven-iteration problem
   is partly a reviewer failure, so reviewer-caused rework is invisible in this
   join BY CONSTRUCTION. Build Tier 2, but never let it stand in for the whole
   behavior space.
   Separately, session linkage can only run on FLUSHED transcripts. Computing
   before the flush systematically under-links the newest and often most-relevant
   sessions (observed: `/pull/2002` mapped to 0 transcripts because the active
   session was not flushed). Whatever runs the session->PR join must gate on
   transcript-complete. A pipeline sequencing rule, not a one-off; cheap to
   handle now, expensive to discover later when the freshest data looks emptiest.

## Routing table (behavior class -> prevention instrument)
Match the instrument to what it can observe. Routing a framing behavior to a CI
gate builds a gate blind to its own cause.

- Framing-triggered (caused by prompt wording or how a request was phrased)
  -> rule in AGENTS.md / CLAUDE.md
- Mechanical signature (destructive command, no test added, coverage drop)
  -> CI gate
- Semantic-only (symptom patch, weak assertion, insufficient check)
  -> review checklist / reviewer protocol
- Context or tool shape (nearby large artifact drives coupling, tool availability
  drives a bad call)
  -> environment change (isolation rules, tool scoping)

## The seven-iteration PR dissection
Do not treat all post-PR rework as builder failure. Separate two classes:

- Avoidable rework: the information needed to fix it correctly was present at
  round 1 and the builder did not use it. This is a source-trace miss. Real
  pattern, build-side prevention.
- Discovery: round N surfaced something not knowable at round 1. This is not a
  failure. Do not pathologize it.

Attribute each failure to the correct agent, because prevention differs:
- Builder source-trace miss -> build-side rule.
- Reviewer incompleteness (reviewer surfaced issue A this round when issue B was
  present and visible in round 1, forcing serial rework) -> exhaustive
  severity-sweep-every-category reviewer discipline so B comes up alongside A in
  round 1.

Serial single-issue review is a reviewer failure charged to the builder by
default. The system must catch and reassign it.

> Cross-reference to forward-link constraint 3: reviewer sessions ship nothing
> and will not appear in the Tier-2 session->PR join. The reviewer-incompleteness
> class this section cares about is exactly the class Tier 2 is blind to. Attribute
> reviewer failures from the review-thread record, not from the build-biased join.

## Evidence standard (applies at every layer that asserts)
- Every claim cites session id, turn index, and the tool call or line span that
  makes it true or false.
- Three buckets only: confirmed, contradicted, could-not-determine.
- could-not-determine includes any candidate pointing at transcript state that
  cannot be located or reconstructed.
- Nothing is confirmed without a citation.

## Output contract and state hygiene
Output is condition-behavior-prevention triples, each tagged by confidence:
- Reconstructed behavior (what the model observably did) is high-confidence and
  may be recorded as fact.
- Cause attribution and severity are model-derived and softer. Tag them as
  assessment, not settled fact. Do not let a soft judgment get cached as a
  premise the next phase plans against.

## Definition of done
- No layer asks for or stores model intention.
- Layer 3 promotes no pattern without a base-rate comparison.
- Every promoted triple has N cited instances and a named, observable condition.
- The forward-link join exists and is exercised on at least the weak-test and
  symptom-patch classes.
- Layer 2 runs independent reconstruction with citations, not eyeball
  adjudication.
- PR rework is split into avoidable vs discovery and attributed to an agent.
- Forward-link join keys were discovered against the corpus, not assumed
  (constraint 1); Tier-1 differentiators are merge-time-observable only
  (constraint 2); Tier-2 is labeled building-biased and gated on
  transcript-complete (constraint 3).
