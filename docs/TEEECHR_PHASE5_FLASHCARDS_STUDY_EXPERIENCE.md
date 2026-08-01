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

The same Flashcards product must also support private course-less learning.
General Chat may prepare a reviewable conversation-draft deck in the learner's
private system-managed General Study workspace. Conversation context is never
misrepresented as source-grounded Course knowledge.

The normal experience must hide provider machinery, raw identifiers, scheduling
dates, and technical operation history while preserving the existing ownership,
grounding, confirmation, budget, publication, restart, and archive contracts.

## Contract stub

Inputs:

- an authenticated learner;
- either one active academic Course with ready material or one owned completed
  Chat message path;
- an editable learning focus, destination, count from 1 through 48, and optional
  generation preferences.

Outputs:

- a provider-free review summary;
- one explicitly confirmed bounded provider operation from a centered modal;
- private server-validated candidates;
- an immutable ready deck containing all validated candidates;
- durable source or conversation provenance.

Success requires Course and General Study journeys to preserve owner isolation,
make zero automatic paid calls, reject stale authority before provider use and
publication, survive restart, and never label conversation-only cards as
source-grounded.

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
- Every generated candidate still requires server-side schema, quality,
  relevance, provenance, ownership, revision, and publication validation.
- The normal learner journey automatically publishes all validated candidates
  and opens the first study card; candidate machinery is not learner-facing.
- Chat and Practice prepare proposals but cannot call a paid provider or
  publish.
- General Study is created lazily, is private and system-managed, and cannot be
  archived, renamed, mapped to BlueWay, or used for Course mastery.
- General Chat may prepare conversation-draft cards without an attached source.
  The server selects a bounded relevant message path, freezes its message IDs
  and fingerprint, derives a no-spend learning brief from the paired question
  plus the assistant explanation's structure, and labels the result
  `Based on this conversation`.
- A General Chat proposal defaults to General Study. The learner may explicitly
  choose an active Course, but changing the destination never converts
  conversation provenance into grounded provenance.
- General Chat supports both a visible Make flashcards action and natural
  requests such as `turn this into ten flashcards`; both open the same editable
  review flow.
- Generated card count supports 1 through 48, defaults to 8, permits a blank
  value while editing, and offers 5, 10, and 20 as shortcuts.
- Grounded Course generation selects all current ready material by default.
  One material is implicit; multiple materials are changed through an optional
  disclosure and grounded generation never proceeds with zero materials.
- Imported BlueWay data is Course material, not a generation permission.
  BlueWay sync never generates cards automatically.
- Pressing `Create N cards with AI` inside the centered `Ready to create` modal
  is the visible paid-action confirmation. Coverage checks and opening the
  modal make zero paid calls. There is no automatic paid retry.
- Exact duplicate candidates are removed. A candidate that does not pass the
  server's deterministic and provider-output checks cannot be published.
- Rejected unpublished candidates may disappear. Published cards and decks use
  archive and restore only; no hard-delete path exists.
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
- Cross-Course, shared, or instructor-assigned decks.
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
- durable queued, running, awaiting-finalization, completed, failed, and
  cancelled operations;
- cited candidate validation;
- atomic immutable publication;
- review scheduling and restart persistence;
- Chat and Practice proposal preparation;
- provider-free deterministic validation;
- owner and Course isolation.

The original Flashcards page combined Study, Create, operation history,
candidate review, errors, and manual editing in one long workspace. The current
learner surface separates those concerns, keeps raw operation details out of
the normal flow, and preserves Activity as a recovery surface.

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

- resumable generation and finalization recovery when the learner returns after
  a reload or restart;
- recoverable failures from earlier requests;
- collapsed previous activity.

The normal create journey is `edit -> coverage check -> centered confirmation
modal -> generation -> automatic validated publication -> first study card`.
Activity is the recovery/history surface, not a required detour. Technical
operation history does not appear in Study or inside the normal creation form.

## Learner state contract

### General Study

General Study is the default private destination for General Chat proposals and
course-less manual decks. It reuses the private Course aggregate internally but
is presented as a Study space, not an academic Course. It has no BlueWay
mapping, Course learning path, or mastery effect.

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
Card count may be blank during editing. Validate it only on blur or continue,
then require an integer from 1 through 48.

### Confirmation

Before confirmation, run a provider-free relevance check against the selected
Course materials. If those materials do not cover the learner's topic, explain
what to change and make zero provider calls. Otherwise summarize the requested
count, focus, selected Course materials, destination, provenance basis, and
provider disclosure in a centered modal over the creation form. The learner may
return to change the request or confirm there. Confirming is the only action
that may schedule paid work.

### Generating

Explain that TEEECHR is creating cards and that the learner may leave the page.
Update automatically. Manual refresh is only a disconnected fallback.

### Automatic finalization

When the operation produces candidates, the client submits every candidate that
passed server validation through the existing atomic publication endpoint.
Publication rechecks owner, Course, write epoch, source or conversation
authority, candidate revision, and immutable provenance. On success, the client
loads the ready deck and opens its first due card without showing candidate
operations, Save cards, or Start studying. If finalization fails, no partial
deck becomes active and Activity remains the recovery surface.

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
handoff safely. A confirmation cannot promote itself to Chat or Practice
authority: the server re-resolves the owned message or graded attempt and
requires its sources, objectives, brief, limits, and options to match the
canonical proposal exactly. Successor generation is workspace-only.

### General Chat

```text
General conversation
  -> Make flashcards button or natural-language request
  -> server resolves the owned active message path
  -> server selects a bounded relevant context window
  -> open the editable review summary
  -> default destination to General Study
  -> learner may explicitly choose an active Course
  -> learner confirms Create N cards with AI in the modal
  -> candidates remain Based on this conversation
  -> validated candidates publish atomically
  -> the first study card opens
```

The context selector begins at the requested assistant message, walks only its
owned branch ancestry, includes directly relevant surrounding messages, removes
system/tool/credential surfaces, rejects zero-overlap neighboring turns, and
applies a strict size bound. Before any provider call, the deterministic planner
uses the paired learner request plus meaningful numbered explanation headings
to derive a proposed title, coverage topics, and learning focus. Misspelled
learner topic words may be corrected only against words already present in the
selected assistant response. The review summary shows the proposed title,
coverage, focus, destination, count, and exact selected-message count.

The immutable conversation receipt records session ID, selected message IDs,
the terminal assistant message ID, canonical content fingerprint, safe title
and topic summary, and the authenticated session-storage scope needed to reload
the exact reviewed conversation. It does not copy conversation text into Course
sources or manufacture Course citations.

## Doc alignment matrix

| Concern | Current authority | Approved intent | Acceptance check |
| --- | --- | --- | --- |
| Personal workspace | `deeptutor/courses/models.py:Course` and `repository.py:CourseRepository` | Add an explicit academic-Course versus General-Study kind; never infer it from title | Two users receive different lazy General Study IDs and cannot read each other's workspace |
| Chat branch authority | `deeptutor/services/session/sqlite_store.py:get_messages_for_context` | Resolve the owned branch ending at the selected assistant message | Sibling branches, foreign sessions, wrong roles, and stale messages are rejected |
| Grounded provenance | `flashcard_generation_models.py:FlashcardSourceReceipt` | Preserve required source receipts and citations | Source revision or fingerprint drift blocks publication |
| Conversation provenance | `flashcard_generation_models.py:FlashcardGenerationOrigin` | Add an immutable conversation receipt without source authority | Cards persist `Based on this conversation` and carry no fabricated source citation |
| Provider admission | `flashcard_generation_provider.py:OpenAIFlashcardGenerationProvider.generate` | One bounded call only after modal confirmation | Coverage check and opening the modal make zero calls; no automatic retry; one active operation |
| Publication | `flashcard_generation_repository.py:publish_candidates` | Automatically submit all validated candidates through the existing atomic publication contract | Failure or stale authority publishes zero cards |
| Lifecycle | `flashcard_repository.py` and migration triggers | Keep archive/restore; no delete | No deck/card/workspace hard-delete route is reachable |
| Mastery | `deeptutor/learning` Course path | General Study and conversation drafts do not mutate Course mastery | Review scheduling persists while mastery files remain unchanged |

## Learner-facing copy map

| Current copy | Replacement |
| --- | --- |
| Grounded generation | Generate from Course materials |
| Review grounded deck request | Check Course coverage |
| Review successor request | Create updated version |
| Objective IDs | Learning objectives |
| BlueWay verified course bundle | Imported BlueWay Course material |
| Confirm and generate candidates | Create the exact card count with AI |
| Publish selected cards | Save the exact selected count |
| queued | Waiting to start |
| running | Creating cards |
| awaiting_review | Finishing your cards |
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
  | "publishing";
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
- `AutomaticGenerationFinalizer`
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
- Course Chat text and Practice results may supply focus but not factual
  authority.
- General Chat context may support explicitly conversation-drafted cards but
  never grants Course source authority, citations, objectives, or mastery.
- General Study is an explicit immutable workspace kind. Its title is display
  data and never authority.
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

### P0-04 Automatic finalization

- [x] Keep provider candidates behind server validation.
- [x] Publish every validated candidate atomically.
- [x] Preserve citations and provenance on the immutable published cards.
- [x] Open the ready deck directly on its first study card.
- [x] Keep generation progress inside Create and use Activity only for recovery
      after navigation, reload, restart, or a finalization failure.

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

### P1-01 General Study aggregate

- [x] Add an explicit workspace-kind schema and model contract.
- [x] Lazily create exactly one private General Study workspace per owner.
- [x] Exclude it from BlueWay mapping, Course archive/restore, and Course
      mastery endpoints.
- [x] Preserve the existing deck, card, review, ownership, and scheduling
      repositories.

### P1-02 Conversation context authority

- [x] Resolve only the authenticated owner's persisted session and active
      branch ending at the selected assistant message.
- [x] Select a bounded relevant context window and persist only its immutable
      receipt/fingerprint as generation authority.
- [x] Keep conversation-draft and source-grounded provider/output contracts
      explicit and separate.
- [x] Reject foreign, deleted, wrong-role, sibling-branch, oversized, incoherent,
      or changed context before provider use or publication.

### P1-03 Unified review and generation

- [x] Show proposed title, focus, destination, count, and provenance basis
      before the paid action.
- [x] Support General Study default plus explicit active-Course destination.
- [x] Support counts 1 through 48 with blank-safe editing and 5/10/20 shortcuts.
- [x] Deduplicate candidates without hiding meaningful alternate questions.
- [x] Preserve explicit Create N cards confirmation and automatic atomic
      publication of server-validated candidates.

### P1-04 Course creation simplification

- [x] Auto-use the only ready Course material without a checkbox.
- [x] Auto-select all ready material and reveal Change materials only when more
      than one exists.
- [x] Prevent zero selected material in grounded mode.
- [x] Keep BlueWay origin in provenance rather than presenting it as a
      generation permission.

### P1-05 Chat entry points

- [x] Show Make flashcards on eligible Course and General Chat answers.
- [x] Recognize natural requests without silently scheduling work.
- [x] Route both entry points through the same server-owned proposal and review
      contract.
- [x] Clear stale proposals on identity, session, branch, or destination
      changes.

### P1-06 Qualification

- [x] Fresh and upgrade migration replay.
- [x] Two-user General Study isolation and lazy singleton proof.
- [x] Grounded versus conversation-draft provenance tests.
- [x] Context branch, size, relevance, and stale-message adversarial tests.
- [x] Counts 1, 5, 8, 20, and 48 plus blank/invalid UI proof.
- [x] Failure, cancellation, archive/restore, restart, and zero-partial-deck
      proof.
- [x] Authenticated browser journeys for Course, General Chat, destination
      change, review, publication, and study.
- [x] No automatic paid-provider test; retain a separately approved bounded
      smoke only.

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
- automatic validated publication;
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

- adding any schema beyond the approved explicit workspace-kind and
  conversation-provenance contract;
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
- All 205 frontend node tests passed.
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

- `npm run test:node`: 205 passed.
- `npx tsc --noEmit`: passed.
- Focused ESLint: passed with no errors or warnings.
- Focused backend Course/Flashcard campaign: 168 passed.
- `./scripts/test-phase4-browser`: all six authenticated flows passed across
  backend restarts.
- `git diff --check`: passed.
- Tracked-diff secret scan: no secret-like values found.
- Independent Terra review: no remaining P0-P2 findings.
- API authority regressions prove an exact owned Chat proposal can be
  revalidated while forged Chat and Practice focus changes return `422` before
  an operation, worker, provider reservation, or paid call exists.

Parked P3:

- Remove the unreachable legacy generation-operation JSX retained behind a
  constant-false guard during a later bounded component cleanup. It is not
  rendered, bundled as an active learner path, or reachable through browser
  state.
- Add a Course-wide cards-ready aggregate only with a bounded server response;
  do not replace it with one browser request per deck.

### 2026-07-30 - source relevance and continuous-create repair

- Added a provider-free Course-material relevance preflight. Unsupported topics
  are stopped before provider admission, preserve the request, and direct the
  learner to change the topic, select different material, or create manually.
- Split imported BlueWay Course bundles into individual records for Flashcard
  retrieval and rank them by learner focus with learner-content records ahead
  of capture metadata. An unrelated early record can no longer monopolize the
  bounded context window. Every accepted BlueWay export dataset has an explicit
  priority: source text, notes, transcripts, syllabus facts, and assignments
  lead; Course/profile/schedule context follows; links and capture metadata are
  last.
- Strengthened the GPT-5 Mini generation contract so each card directly serves
  the requested focus, tests one standalone idea, answers its own question,
  avoids source/recording trivia, and retains exact receipt-bound citations.
- Added output validation that rejects cards whose question, answer, and hint
  do not match the learner's focus. Citation text alone cannot make an
  irrelevant card pass. This lexical topic fence applies to direct workspace
  requests. Chat and Practice proposals instead validate exact citations,
  Course authority, objective scope, standalone quality, and source-trivia
  rules without requiring internal workflow words to appear in cards.
- The relevance fence is deliberately a bounded lexical safety heuristic, not
  a complete semantic-quality claim. It handles short scientific terms,
  Unicode, longer common inflections, and symbolic C++/C# names while rejecting
  short shared-prefix collisions; the server validation boundary remains the
  final publication quality gate. Chat and Practice wrapper briefs use their already owned
  source/objective scope for availability rather than treating system-written
  workflow copy as the learner's topic. Their confirmation payloads cannot
  choose that relaxed contract: the server re-derives and exactly compares the
  bound proposal before any operation or provider reservation exists.
- Changed the normal flow to remain on Create:
  `edit -> check coverage -> confirm -> generating -> review -> save -> study`.
  Activity remains available for restart-safe recovery and prior history.
- Ready Course material is selected when the Course loads and the final selected
  source cannot be silently unchecked. The form gives the deck name and
  learning topic visible labels, exposes source selection as a first-class
  step, and translates the internal BlueWay bundle name to `Imported BlueWay
  Course material`.
- No schema, migration, Course ownership, BlueWay source, hosted data, provider
  policy, or budget contract changed.

### 2026-07-30 - General Study and conversation-draft expansion approved

- Approved lazy private General Study as an explicit system-managed workspace,
  not a title convention or special deck.
- Approved smart bounded General Chat context with immutable message receipts,
  editable pre-generation review, General Study default destination, and an
  optional explicit active-Course destination.
- Approved a strict distinction between source-grounded and
  conversation-drafted cards.
- Approved 1-through-48 generated counts, blank-safe editing, and 5/10/20
  shortcuts.
- Approved automatic current Course-material selection, with material
  customization shown only when multiple ready sources exist.
- Approved both the visible Chat action and natural-language request entry
  points.
- Preserved explicit paid-action confirmation, no automatic BlueWay generation,
  no automatic retry, no Course mastery mutation from General Study, and
  archive/restore-only lifecycle.

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

### 2026-07-30 - General Study and conversation-draft implementation closeout

Implemented:

- Added one lazy, private, system-managed General Study workspace per immutable
  owner. It cannot receive Course sources, managed Knowledge, Practice, learning,
  or mastery writes.
- Added General Chat Flashcard proposals from a bounded relevant conversation
  branch. The proposal freezes exact message IDs, a digest, and a plain summary;
  execution reloads those exact messages and stops before provider use if they
  changed.
- Upgraded the no-spend conversation planner to remove unrelated zero-overlap
  turns and derive a proposed title, learning focus, and coverage list from the
  learner's question and the selected explanation's headings. The immutable
  receipt also records whether the authenticated General Chat lived in the
  personal or legacy administrator session namespace so execution reloads the
  reviewed authority rather than guessing a database. An administrator-scope
  operation revalidates the account's current role under the identity lock
  before context resolution, provider admission, and candidate commit; demotion
  fails the operation as an authority change without invoking the provider.
- Added an editable no-spend review screen showing the proposed deck, focus,
  destination, count, and conversation or Course-material provenance.
- Kept conversation-drafted provenance when the learner explicitly saves the
  deck to an academic Course. Moving the deck never converts it to
  Course-grounded knowledge or permits Course mastery mutation.
- Added 1-through-48 blank-safe counts with 5, 10, and 20 shortcuts.
- Made one ready Course source automatic and hid its selector; multiple ready
  sources remain selected by default behind `Change materials`.
- Added the General Chat `Make flashcards` action and bounded natural-language
  intent parsing. Both routes prepare the same server-owned proposal.
- Kept paid generation behind a separate explicit confirmation, with no
  automatic retry and no generation triggered by BlueWay synchronization.
- Preserved archive/restore-only lifecycle for General Study decks and verified
  review history survives restoration.

Closeout proof:

- Focused conversation-authority and Flashcard lifecycle campaign: 17 passed.
- Broader impacted Course, Practice, Flashcard, API, repository, and learner
  action campaign: 215 passed.
- Migration replay campaign: 23 passed.
- Web TypeScript passed; Node contract suite: 207 passed.
- Authenticated deterministic browser campaign passed all seven flows,
  including two-user restart isolation, provider-free manual work, grounded
  source selection, immutable candidate publication, and the complete General
  Chat preview-to-study journey.
- The authority-change adversarial test proves changed reviewed messages fail
  with `authority_changed` before the provider is called.

### 2026-07-30 - single-confirmation direct-study amendment

Approved and implemented:

- Replaced the inline `Ready to create` block with a centered, keyboard-aware
  modal over the creation form.
- Kept the modal as the single explicit paid-action confirmation and preserved
  an immediate Change request path.
- Removed candidate review, Save cards, and Start studying from the normal
  generated-card journey.
- Automatically submits all server-validated candidates through the existing
  atomic publication endpoint exactly once.
- Opens the immutable ready deck directly on its first study card.
- Keeps operation and candidate data available in Activity only for
  restart-safe recovery or a finalization failure.
- Preserved schema, relevance, provenance, owner, current-role, Course,
  write-epoch, source or conversation fingerprint, candidate-revision, and
  immutable-publication checks.

The updated normal journey is:

```text
edit request
  -> provider-free coverage check
  -> centered Ready to create modal
  -> one explicit Create N cards with AI confirmation
  -> bounded generation
  -> server validation
  -> automatic atomic publication
  -> first study card
```

Proof for this amendment:

- TypeScript and focused ESLint passed.
- All 208 frontend Node contract tests passed.
- The seven-flow hermetic authenticated browser campaign passed.
- The Course and General Chat journeys each proved one generation request, one
  automatic publication request, no learner candidate-review screen, and an
  immediately active first study card.
- The automatically published Course deck remained ready and studyable after a
  backend process restart.
- `git diff --check` and the added-line secret scan passed.

Proof boundaries:

- The browser and automated campaigns use deterministic local providers; they
  do not claim a new paid GPT-5 Mini call or model-quality proof.
- No push, merge, deployment, production migration, BlueWay mutation, or
  release claim is included.

### 2026-07-30 - focused numbered-study amendment

Approved and implemented:

- Starting a study session replaces deck management with one centered
  notecard.
- `Start studying`, archive controls, the deck list, archived decks, and
  neighboring card prompts are unavailable until the learner exits or finishes
  the session.
- Navigation exposes only numbered positions. Selecting a number changes the
  active unfinished card without revealing its question in advance.
- Ratings remain durable server-owned scheduler writes. Arbitrary navigation
  does not skip unfinished cards when the session advances.

### 2026-07-30 - beta learner-experience acceptance

Decision:

- The user accepted the current Phase 5 Flashcards learner experience as good
  enough for the current beta.
- Phase 5 product behavior is frozen at the current Study, Create, Activity,
  Course-grounded, General Study, General Chat, automatic publication, and
  focused numbered-study contracts.
- Additional Flashcard capabilities belong in `FUTURE_DUE.md`; they are not
  required to close the Phase 5 learner experience.

Boundary:

- This acceptance is a product/human-review gate. By itself it does not claim
  that the work is pushed, merged, deployed, reconciled with newer upstream
  DeepTutor, or production released.

### 2026-08-01 - Luna qualification and runtime-policy transition

- The accepted learner experience remains anchored at `3243c0d5`.
- Reviewed commit `a113ebed` promotes Flashcards generation to
  `gpt-5.6-luna` with medium reasoning through the central typed registry.
  Mini remains defined only as emergency rollback and is not selected by an
  active feature.
- The Luna-medium Course and conversation Flashcard artifacts passed frozen
  qualification and human review. The complete commit snapshot passed 196
  impacted tests, Ruff, diff, credential, and local-path checks.
- The local paid-use ledger retained all historical Mini receipts and changed
  only its active pricing authority to `openai-gpt-5.6-luna-2026-08-01` after
  confirming that no operation was reserved. Fresh no-call resolution reports
  Flashcard generation available.
- A controlled current-HEAD backend/frontend restart succeeded. The
  authenticated post-restart Flashcards Create surface exposed `Generate from
  Course materials` and `Create manually`, with no disabled-provider warning.
  The check stopped before confirmation, so it made no provider call.
- The non-terminating production-build boundary was isolated to the machine's
  unsupported Node.js 26 runtime. The same current tree completed a full Next
  production build under Node.js 24.14.0, generated all 54 routes, and exited
  successfully. The web package now rejects unsupported Node majors before a
  build, accepts only the evidenced Node 22/24 lines, and selects Node 22 LTS in
  `.nvmrc`. This is local build proof only; no deployment or release authority
  is claimed.
