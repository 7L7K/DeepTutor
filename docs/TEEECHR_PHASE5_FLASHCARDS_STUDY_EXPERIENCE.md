# TEEECHR Phase 5 Flashcards Study Experience

Status: approved for implementation

Authority:
`/Users/home/Desktop/2k26/teeech/DeepTutor-v1.5.2-baseline`

Implementation branch:
`feature/teeechr-v152-phase5-course-study-intelligence`

Starting HEAD:
`262a778d5a95b616397f4428b71e0554aff08f53`

Parent contract:
`docs/TEEECHR_PHASE5_COURSE_STUDY_INTELLIGENCE.md`

## Goal

Turn the existing secure Course Flashcards foundation into a study-first
learner experience. A learner should understand the active Course, cards ready
to study, the next useful action, and how to create more cards within five
seconds.

The normal experience must hide provider machinery, raw identifiers, scheduling
dates, and technical operation history while preserving the existing ownership,
grounding, confirmation, budget, publication, restart, and archive contracts.

## Locked product decisions

- Study is the default Flashcards view.
- The page has three learner views: Study, Create, and Activity.
- Manual Flashcards remain available without a provider.
- Provider-off mode does not show a wall of disabled generation controls.
- A normal grounded request asks one essential question: what should these
  cards help the learner understand?
- TEEECHR chooses deterministic safe defaults before exposing optional
  customization.
- Every paid provider call still requires visible learner confirmation.
- Every generated candidate still requires learner review before publication.
- Chat and Practice prepare proposals but cannot call a paid provider or
  publish.
- Generated factual cards remain immutable after publication.
- The study session offers Got it and Study again. The existing scheduler keeps
  exact intervals and timestamps internally.
- Exact next-review dates do not appear in the normal learner interface.
- Technical failure codes remain in server logs or administrator diagnostics,
  not primary learner copy.
- Course ownership remains private and role-independent.
- Archive and restore remain the only deletion lifecycle.

## Non-goals

- Typed or spoken answer grading.
- Automatic paid generation.
- Automatic generation from every BlueWay transcript.
- Editing a generated factual card in place.
- Detailed calendar or scheduling controls.
- Cross-Course or shared decks.
- Instructor-assigned decks.
- BlueWay write-back.
- Web-assisted generation.
- Multi-server budget coordination.
- Upstream DeepTutor reconciliation.
- Push, merge, deployment, or production release.

## Current state

The Phase 5 backend and persistence boundary already supports:

- private Course-owned manual and generated decks;
- ready Course source resolution;
- server-normalized generation briefs;
- explicit provider confirmation;
- bounded GPT-5 Mini provider use;
- durable queued, running, awaiting-review, completed, failed, and cancelled
  operations;
- cited candidate review;
- include, exclude, reorder, and immutable publication;
- review scheduling and restart persistence;
- Chat and Practice proposal preparation;
- provider-free deterministic validation;
- owner and Course isolation.

The current Flashcards page combines Study, Create, operation history,
candidate review, errors, and manual editing in one long workspace. It exposes
raw objective IDs, raw operation states, raw failure codes, and disabled
provider controls. This project reorganizes the learner surface without
weakening the existing contracts.

An uncommitted scroll repair already makes the Flashcards workspace vertically
scrollable and adds a browser regression. That repair must be preserved and
included in the reviewed implementation slice. Three unrelated duplicate
untracked Python files are outside this project and must remain untouched.

## Information architecture

The canonical route remains `/flashcards`.

Presentation may use:

```text
/flashcards?view=study
/flashcards?view=create
/flashcards?view=activity
```

Query state controls presentation only. It never grants Course, source, deck,
operation, candidate, provider, or review authority.

### Study

The default view contains:

- a cards-ready summary;
- one primary Start studying action;
- active decks ordered by ready count and recency;
- caught-up, empty, and archived-only states;
- archived decks behind a disclosure.

### Create

The learner first chooses:

- Generate from Course materials; or
- Create manually.

The grounded flow initially shows:

- suggested deck name;
- study focus;
- selected Course materials;
- suggested card count.

Customization reveals:

- difficulty;
- answer length;
- card types;
- hints;
- named learning objectives.

Raw objective IDs are never learner-facing.

### Activity

Activity contains:

- active generation;
- candidate drafts ready for learner review;
- recoverable failures;
- collapsed previous activity.

Technical operation history does not appear in Study or inside the normal
creation form.

## Learner state contract

### No Course

Explain that Flashcards belong to a Course and offer Choose a Course or Create a
Course.

### Empty Course

Offer Generate from Course and Create manually. If no ready sources exist,
explain that grounded generation requires Course material while manual creation
works immediately.

### Cards ready

Show the number of cards ready and one Start studying action. When one deck has
ready cards, begin it directly.

### Caught up

Show You are caught up with Done or Create more cards. Do not show a future
date.

### Provider unavailable

Show a short unavailable notice and Create manually. Do not render disabled
advanced generation controls.

### Request editing

Ask what the cards should help the learner understand. Auto-select current ready
Course sources and deterministic defaults. Customization remains optional.

### Confirmation

Summarize the requested count, focus, selected Course materials, and provider
disclosure. Confirming is the only action that may schedule paid work.

### Generating

Explain that TEEECHR is creating cards and that the learner may leave the page.
Update automatically. Manual refresh is only a disconnected fallback.

### Candidate review

Present one candidate at a time with question, answer, Keep, Remove, and an
optional source disclosure. A summary supports final ordering and publication.
The publish action includes the exact selected count.

### Generation failure

Return the learner to the preserved request and show:

```text
We could not create these cards.
Your request is still here.
```

Offer Try again only when the server says a new attempt is safe. Otherwise offer
Change request. Raw error codes are not displayed.

### Active study

Before reveal:

- question;
- Show answer;
- optional Give me a hint;
- subtle cards-left count.

After reveal:

- answer;
- Got it;
- Study again;
- optional source disclosure.

Got it maps to the existing successful scheduler rating. Study again maps to the
existing repeat rating. No scheduler schema change is implied.

### Study complete

Show the cards reviewed and Done or Keep studying. Do not show an exact next
review date.

### Archived deck

Hide it from the active deck list. Show it only under Archived decks with
Restore. No hard-delete action exists.

## Chat and Practice handoffs

### Course Chat

```text
Course conversation
  -> Make this into flashcards
  -> server prepares a non-paid proposal
  -> open Create with Prepared from Course Chat
  -> learner reviews the prefilled request
  -> learner explicitly confirms provider use
```

### Practice remediation

```text
graded Practice attempt
  -> Create review cards
  -> server proposes missed or weak objectives
  -> open Create with Prepared from your Practice results
  -> learner reviews the prefilled request
  -> learner explicitly confirms provider use
```

Proposal origin is context, not ownership or source authority. Logout, identity
change, Course mismatch, or stale proposal state must clear or reject the
handoff safely.

## Learner-facing copy map

| Current copy | Replacement |
| --- | --- |
| Grounded generation | Generate from Course materials |
| Review grounded deck request | Review request |
| Review successor request | Create updated version |
| Objective IDs | Learning objectives |
| BlueWay verified course bundle | Imported BlueWay Course material |
| Confirm and generate candidates | Generate cards |
| Publish selected cards | Publish selected cards with the exact count |
| queued | Waiting to start |
| running | Creating cards |
| awaiting_review | Ready for your review |
| provider_failed | Learner-safe recovery copy selected by failure category |

## Presentation types

Suggested client presentation types:

```ts
type FlashcardsView = "study" | "create" | "activity";

type FlashcardCreateMode =
  | "choose"
  | "grounded"
  | "manual";

type GroundedCreateStage =
  | "editing"
  | "confirming"
  | "generating"
  | "reviewing";
```

Suggested component seams:

- `FlashcardsPageShell`
- `FlashcardsViewNavigation`
- `FlashcardsStudyDashboard`
- `FlashcardDeckList`
- `CreateDeckChooser`
- `GroundedDeckComposer`
- `GenerationConfirmation`
- `GenerationProgress`
- `CandidateReviewFlow`
- `FlashcardStudySession`
- `GenerationActivity`
- `LearnerGenerationNotice`
- `ProposalOriginBanner`

Component extraction must be incremental. Do not rewrite repositories, API
routers, or provider services merely to obtain cleaner frontend component
boundaries.

## Security and authority invariants

- The authenticated server resolves the immutable owner and current Course.
- Browser state never grants ownership, source, Knowledge Base, provider,
  filesystem, or publication authority.
- Foreign and missing Course, source, deck, operation, candidate, session,
  message, Practice attempt, and review identifiers retain the same safe
  not-found response.
- Ready Course sources remain the only factual authority for generated cards.
- Chat text and Practice results may supply focus but not factual authority.
- A prepared brief is invalidated by account, Course, write-epoch, source, or
  revision drift.
- No automatic paid retry follows an uncertain provider response.
- Failed and cancelled operations publish zero active cards.
- Publication remains atomic, revision-checked, and idempotent.
- Generated cards remain immutable.
- Exact provider errors, prompts, excerpts, credentials, and sensitive receipts
  stay out of learner copy.

## Implementation milestones

### P0-01 Information architecture

- [x] Add Study, Create, and Activity views.
- [x] Make Study the default.
- [x] Remove the redundant active-Course badge.
- [x] Move operations out of the creation form.
- [x] Preserve Course switching and identity cache clearing.

### P0-02 Study dashboard

- [x] Add cards-ready summary and Start studying.
- [x] Add empty, caught-up, and archived-only states.
- [x] Simplify active deck rows.
- [x] Hide exact next-review dates.

### P0-03 Creation chooser

- [x] Add Generate from Course and Create manually choices.
- [x] Collapse provider-off mode to one notice and manual action.
- [x] Show essential grounded fields first.
- [x] Put advanced generation settings behind Customize.
- [x] Remove raw objective IDs; apply prepared Course objectives automatically
      until the Course API exposes authoritative learner-facing objective names.

### P0-04 Candidate review

- [x] Present candidates in a focused review flow.
- [x] Support Keep, Remove, reversible inclusion, and final ordering.
- [x] Keep citations available through a source disclosure.
- [x] Publish the exact selected count.
- [x] Return the ready deck to Study.

### P0-05 Study session

- [x] Replace four scheduler choices with Got it and Study again.
- [x] Add optional hint and source disclosure without increasing authority.
- [x] Show cards left instead of scheduler dates.
- [x] Add simple completion actions.

### P0-06 Activity and recovery

- [x] Translate operation states into learner copy.
- [x] Preserve failed request input.
- [x] Show retry only when safe. The current operation contract exposes no
      explicit safe-retry authority, so the learner receives Change request
      instead of an inferred retry.
- [x] Keep completed history collapsed.
- [x] Update active operations automatically.
- [x] Remove raw technical codes from learner DOM.

### P0-07 Chat and Practice handoffs

- [x] Open Create with an origin banner and prefilled safe brief.
- [x] Preserve visible provider confirmation.
- [x] Reject Course or identity mismatch.
- [x] Clear proposals on logout or identity change.

### P0-08 Qualification and closeout

- [x] Add a dedicated Phase 5 Flashcards UX browser specification.
- [x] Cover learner operation states with pure deterministic presentation tests
      and the core manual/generated journeys with the deterministic local
      provider.
- [x] Reprove two-user ownership and cache isolation.
- [x] Reprove restart persistence.
- [x] Test desktop, narrow-height, and 390-pixel-wide viewport behavior.
- [x] Run TypeScript, focused tests, diff check, secret scan, and closeout
      backcheck.
- [x] Review all tracked and untracked state.
- [x] Update this document with final evidence and remaining unproved surfaces.

## Test and proof plan

Automated proof must cover:

- no Course;
- empty Course;
- no ready sources;
- provider disabled;
- provider enabled through a deterministic local adapter;
- manual creation;
- request confirmation;
- queued and running generation;
- candidate review;
- immutable publication;
- cards ready;
- no cards ready;
- active review;
- study completion;
- safe failure recovery;
- retry allowed and prohibited;
- archive and restore;
- Chat proposal;
- Practice proposal;
- Course switching;
- logout and second-user isolation;
- backend restart;
- desktop and narrow viewport scrolling.

Use real authentication, HTTP routes, SQLite persistence, Course ownership, and
backend restarts. Mock only paid external provider behavior. Automated tests
must not make paid calls.

A real paid-provider UI smoke remains separately approval-gated and must not be
used to imply deployment or production readiness.

## Stop conditions

Stop and request a separate decision before:

- adding or changing database schemas;
- changing provider, budget, credential, auth, or Course ownership contracts;
- enabling automatic or globally available paid generation;
- adding typed or spoken answer evaluation;
- merging, pushing, deploying, or releasing;
- touching BlueWay source or hosted data.

## Parking lot

- Typed answer evaluation after the two-choice review flow is stable.
- Spoken answers after microphone, transcription, privacy, and cost contracts
  exist.
- Adaptive generation settings after real learner evidence exists.
- Detailed scheduling only if beta learners request it.
- Manual successors for generated cards with explicit provenance.
- Notifications after TEEECHR has a durable notification surface.
- Shared decks after a separate access-control design.
- BlueWay write-back outside the current read-only integration.

## Progress ledger

### 2026-07-30 - implementation start

- Approved the study-first direction.
- Locked Study, Create, and Activity as the learner information architecture.
- Replaced the proposed four-button scheduler UI with Got it and Study again.
- Removed exact future review dates from the normal learner contract.
- Replaced learner-visible technical failure codes with safe recovery behavior.
- Preserved the existing provider, ownership, immutable publication, archive,
  and deterministic-test boundaries.
- Added this authoritative implementation plan.

### 2026-07-30 - P0 learner experience integrated

- Added Study, Create, and Activity as presentation-only views; Study is the
  safe default and view state does not grant authority.
- Preserved the Course/auth hydration fence so an immediate learner click
  cannot race the initial owner-scoped load and get reset.
- Collapsed provider-off creation to a learner-safe notice and manual path.
- Moved advanced grounded options behind Customize and removed raw objective
  IDs from the learner surface. Prepared objective bindings remain internal
  because the current Course API does not expose authoritative display names.
- Moved generation operations and candidate review to Activity, added
  learner-safe state/failure presentation, automatic active-operation refresh,
  exact-count publication, and collapsed previous activity.
- Integrated the two-choice study session with optional hint/source disclosure,
  cards-left progress, and completion copy with no scheduler dates.
- Added pure presentation and study-session tests plus a dedicated authenticated
  Phase 5 learner-shell browser specification.
- Split auth identity resolution from synchronous identity/Course invalidation.
  The page now renders a loading-safe state unless the visible Course matches
  the current owner-scoped request fence. A delayed Course A to Course B browser
  test proves the older response cannot replace the current Course.
- Made the Course-derived deck name deterministic and optional to edit, leaving
  study focus as the one required normal-generation question.
- Changed candidate review to one candidate at a time with Previous/Next,
  card-specific accessible Keep/Remove controls, a selected-order disclosure,
  and exact-count publication.

Proof at this milestone:

- `npx tsc --noEmit` passed.
- All 204 frontend node tests passed.
- The authenticated six-flow browser campaign passed after updating it to the
  new Study/Create/Activity journey.
- The campaign covered two private users, backend restart, manual provider-free
  creation and study, deterministic grounded staging, learner review, exact
  publication, post-restart study, a delayed Course-switch race, and a
  390-pixel-wide learner surface.

Remaining proof boundaries:

- No new paid-provider call was made for this UX lane.
- No deployment, production runtime, physical-device, push, or merge claim is
  included.
- The Study summary is authoritative for the selected deck. A Course-wide
  aggregate would require a future bounded server summary response; the client
  deliberately does not issue one request per deck.

### 2026-07-30 - closeout backcheck

Verdict: `PASS_WITH_PARKED_FOLLOWUPS`

Final evidence:

- `npm run test:node`: 204 passed.
- `npx tsc --noEmit`: passed.
- Focused ESLint: passed with no errors or warnings.
- Focused backend Course/Flashcard campaign: 62 passed.
- `./scripts/test-phase4-browser`: all six authenticated flows passed across
  backend restarts.
- `git diff --check`: passed.
- Tracked-diff secret scan: no secret-like values found.
- Independent Terra review: no remaining P0-P2 findings.

Parked P3:

- Remove the unreachable legacy generation-operation JSX retained behind a
  constant-false guard during a later bounded component cleanup. It is not
  rendered, bundled as an active learner path, or reachable through browser
  state.
- Add a Course-wide cards-ready aggregate only with a bounded server response;
  do not replace it with one browser request per deck.

Current proof before the redesign:

- Phase 5 provider and persistence boundary is implemented on the feature
  branch.
- A bounded real GPT-5 Mini generation and publication proof exists separately.
- Provider gates are disabled after proof.
- The Flashcards scroll repair passed the authenticated five-flow browser
  campaign but remains uncommitted.

## Implementation goal

Implement and close the P0 milestones in this document on the current Phase 5
feature branch. Preserve all locked authority contracts, update this progress
ledger after each completed milestone, validate with deterministic provider-free
tests plus authenticated browser and restart proof, and stop before push, merge,
deployment, provider-policy changes, schema changes, or BlueWay mutation.
