# TEEECHR Next Advanced Learner Feature Decision

Date: 2026-08-01
Status: selected for planning; implementation not started
Selection: Course Progress and Adaptive Remediation

## Decision

The next advanced learner feature should be a learner-facing Course Progress
and Adaptive Remediation experience.

This is the smallest feature that closes the current product loop:

```text
Course sources and Chat
        -> Practice evidence
        -> Flashcard review evidence
        -> Course learning/mastery state
        -> clear next recommendation
        -> learner-approved remediation activity
```

The backend already derives bounded weak objectives from committed error,
due-review, and encountered-low-mastery evidence. It also exposes learner-safe
progress/next-step views and can prepare remediation Flashcards. What is missing
is one coherent learner experience that explains the evidence, recommends a
next action, and lets the learner confirm it.

## Learner outcome

On a Course progress screen, the learner can answer:

- What have I practiced?
- What am I understanding?
- What needs attention?
- Why is TEEECHR recommending this next step?
- Should I review cards, take a short quiz, or continue learning?

The initial version uses plain readiness bands and evidence counts rather than
calendar promises or false precision. It does not display internal objective
IDs, raw algorithm scores, or labels such as `provider_failed`.

## Proposed first slice

### 1. Course overview

Show only server-derived, owner-scoped evidence:

- objectives encountered versus not yet encountered;
- current strengths;
- needs-attention objectives with a plain reason such as “recent mistake,”
  “review needed,” or “still developing”;
- recent Practice and Flashcard activity; and
- the next recommended action.

### 2. Explainable recommendation

Every recommendation includes:

- the evidence category, not private answer text;
- the Course and source/provenance boundary;
- the proposed activity type and size; and
- an editable review step before any provider call or new saved activity.

### 3. Learner-confirmed remediation

Offer bounded actions:

- Review existing Flashcards;
- Create a short remediation Flashcard deck;
- Take a short Practice quiz; or
- Continue the next learning objective.

Nothing is generated merely because a sync, transcript, grade, or page view
occurred. Generation remains explicit and uses the existing provider, budget,
source snapshot, revision, and review gates.

### 4. Persistence and isolation

- Progress is derived from persisted Course evidence and `lp_<course_id>`.
- General Study never changes Course mastery.
- Recommendations are owner- and Course-scoped and revalidated before action.
- Archived Courses are read-only and cannot start remediation work.
- Identity changes clear cached progress and recommendation state.

## Acceptance criteria

- Two users with identical Course/objective titles see only their own evidence.
- The same user can switch Courses without stale strengths or recommendations.
- A recommendation is deterministic for the same frozen evidence snapshot.
- Untouched objectives are not mislabeled as weak.
- A weak-objective reason is traceable to committed evidence without exposing
  raw answers or private source text.
- The learner can edit or decline the proposed activity before generation.
- Provider-off mode still shows progress and can route to existing/manual work.
- Provider failure changes no mastery and publishes no activity.
- Completion of a target-native Practice attempt updates progress once, even
  across retry/restart.
- General Study activity remains excluded from Course mastery.
- Archived Course progress remains viewable while new actions are blocked.
- Authenticated browser proof covers two users, two Courses, restart, and
  logout/login cache isolation.

## Alternatives considered

### Typed-answer semantic grading

Useful, but not first. It introduces a new grading-authority problem: model
judgments, partial credit, rubric versioning, appeals, uncertain provider
outcomes, and mastery effects. The current exact grading remains honest and
reliable. Typed-answer grading should follow with a separate evidence contract.

### Spoken answers

Deferred. It adds microphone permissions, transcription, accessibility,
privacy, latency, and provider-cost surfaces before the basic progress loop is
visible.

### Adaptive deck generation

Partially included only as a learner-confirmed remediation action. A fully
autonomous adaptive generator is deferred because automatic generation would
weaken the explicit-review and spend contracts.

### Notifications and detailed scheduling

Deferred. The learner explicitly disliked date-heavy review presentation, and
notification delivery adds platform and preference complexity. The first
progress experience should use readiness and evidence, not “tomorrow” claims.

### Shared or instructor-assigned decks

Deferred. Private learner ownership is the locked beta model. Sharing needs a
new membership, role, revocation, and copied-versus-shared-data contract.

### Cross-Course decks and BlueWay write-back

Deferred. Both widen authority beyond the private Course boundary. BlueWay
remains read-only, and cross-Course aggregation needs explicit provenance and
mastery semantics.

## Non-goals for the first slice

- no autonomous background generation;
- no provider-based grading;
- no spoken answers;
- no push notifications or calendar scheduling;
- no instructor/shared workspace;
- no BlueWay write-back;
- no cross-Course mastery score;
- no multi-server coordination; and
- no historical-data promotion into live mastery.

## Next planning action

Write the Phase 7 Course Progress and Adaptive Remediation contract around the
existing `learner_actions`, learning policy, grading evidence, Practice plan,
and Flashcard remediation primitives. Begin with provider-free read models and
authenticated browser states; add generation only through the existing review
and budget gates.
