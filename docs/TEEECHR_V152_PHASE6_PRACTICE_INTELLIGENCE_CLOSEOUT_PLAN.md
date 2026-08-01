# TEEECHR v1.5.2 Phase 6 Closeout — Practice Intelligence and Product Parity

Status: **implemented, qualified, and locally closed for the current beta**

Date: 2026-07-30

Canonical implementation checkout:
`/Users/home/Desktop/2k26/teeech/DeepTutor-v1.5.2-baseline`

Implementation branch/base:
`feature/teeechr-v152-phase5-course-study-intelligence` from accepted Phase 5
head `3243c0d5`. Phase 6 implementation commits are `c0e7f5a7` (backend,
database, and contract tests) and `73ef9ed3` (learner UI and browser proof).

Historical behavior reference:
`/Users/home/Desktop/2k26/teeech/DeepTutor`, historical `main` at
`e991e79f`, especially learner-product commit `949f5a8e`

## 1. Goal and non-goals

### Goal

Close the remaining learner-facing gaps between the preserved historical
TEEECHR Practice/Quiz product and the private Course-owned v1.5.2
implementation. The primary outcome is a student-facing generated-quiz flow
that reuses the existing Course generation, attempt, grading, mastery, and
remediation authorities without restoring the historical tester-cookie,
NCE-only, or question-coordinator architecture.

This document also reconciles the original migration roadmap. The original
Phase 6 was not absent: its Chat, Knowledge, learner-action, remediation, and
mastery requirements were substantially implemented during the reordered
Phase 4 and Phase 5 work.

### Non-goals

- No direct merge or module copy from historical `main`.
- No tester cookie, access code, title, filename, Knowledge Base name, or NCE
  domain becomes ownership authority.
- No automatic quiz or Flashcard generation after BlueWay sync.
- No BlueWay write-back.
- No historical learner-data mutation or import.
- No upstream DeepTutor v1.5.5 reconciliation.
- No sharing, instructor assignment, spoken answers, notifications, or
  multi-server coordination.
- No push, merge, deployment, or production release from this plan.

## 2. Contract stub

### Inputs

- Current authenticated user and private Course.
- Owned ready Course sources with immutable source revisions and fingerprints.
- Optional current Course Chat assistant message or weak-objective handoff.
- Learner-selected quiz focus, question count, difficulty, and timing mode.
- Existing Course Practice generation, attempt, grading, mastery, and
  remediation services.

### Outputs

- An editable quiz plan shown before provider work.
- A durable generated Practice operation bound to the authenticated owner,
  Course, source receipts, Course write epoch, and idempotency key.
- A ready immutable Practice revision with cited questions.
- A resumable quiz attempt with autosaved answers, deterministic grading,
  objective-level evidence, and remediation.
- A learner-facing result that explains score and weak objectives without
  exposing internal provider or database terminology.

### Success

1. A learner can choose a Course, request a quiz, review its plan, generate it,
   answer, reload or restart, submit, grade, and enter remediation.
2. `Quiz me` from Course Chat opens the same editable plan rather than creating
   a parallel quiz system.
3. Foreign Course, source, operation, Practice set, attempt, evidence, and
   learning identifiers remain non-enumerating `404`.
4. Provider failure never creates a ready quiz, changes mastery, or destroys an
   existing attempt.
5. Only proven graded events affect Course mastery.

## 3. Roadmap reconciliation

The original roadmap in
`/Users/home/Desktop/2k26/teeech/TEEECHR_V152_MIGRATION_MASTER_HANDOFF.md`
defined:

- Phase 4: Practice reimplementation.
- Phase 5: Flashcards reimplementation.
- Phase 6: Chat, Knowledge, and mastery integration.
- Phase 7: historical data migration.
- Phase 8: BlueWay bridge.
- Phase 9: staging and production.

Execution was deliberately reordered:

- BlueWay moved forward into implemented Phase 3/3A.
- Course-owned Practice, grading, mastery, Flashcards, and learner actions were
  built together during the implemented Phase 4.
- Provider-safe Flashcard intelligence and the learner Flashcard experience
  were completed during Phase 5.
- The original Phase 6 requirements were therefore absorbed across Phase 4 and
  Phase 5 rather than executed as a separate branch.

This plan uses **Phase 6 Closeout** to make that history explicit and finish the
remaining generated-Practice and learner-product gaps.

## 4. Historical-to-current alignment matrix

| Concern | Historical reference | Current authority | Classification | Acceptance check |
| --- | --- | --- | --- | --- |
| Private learner ownership | Historical tester identity and tester-prefixed Knowledge names | `deeptutor/services/auth.py`, `deeptutor/services/path_service.py`, `courses/repository.py` | Superseded | Foreign identifiers remain `404`; admin role grants no private-data access |
| Practice library | `949f5a8e:web/components/practice/PracticeWorkspace.tsx` | Current `PracticeWorkspace.tsx` | Reimplemented with Study/Create/Activity journeys | Sets survive reload/restart and archive/restore |
| Persistent quiz attempts | `949f5a8e:api/routers/practice.py` | `attempt_repository.py`, `attempt_service.py`, `courses.py` | Reimplemented | Start/resume/autosave/submit history survives restart |
| Deterministic grading | Historical quiz-submission agent | `grading_repository.py`, `grading_service.py` | Reimplemented and hardened | Replay is idempotent; forged evidence changes no mastery |
| Practice progress | Historical `/practice/progress` domain summary | Course objectives, mastery, errors, review queue | Redesigned, presentation partial | Results explain weak objectives and link to Course learning |
| Grounded quiz generation | Historical topic/KB generation | `generation_service.py`, `generation_repository.py`, `generation_provider.py` | Reimplemented with a durable review-first plan | Editable plan starts one cited operation and opens the quiz |
| Generated-quiz UI | Historical dedicated generation controls | Current `PracticeWorkspace.tsx` Study/Create/Activity journey | Reimplemented | Learner completes generation-to-grade without API tooling |
| Chat `Quiz me` | Historical Chat quiz action | `ChatMessages.tsx`, `courses.py:run_course_learner_action` | Reimplemented through the same durable plan | Chat opens the same editable quiz plan with exact context |
| Explain/Flashcards/weak review actions | Historical quick replies | Current learner actions and Phase 5 proposals | Reimplemented | All actions use owned Course/session authority |
| Timed/untimed quiz | Historical soft timer/exam controls | Persisted `QuizAttempt.timing_mode` and advisory UI timer | Reimplemented as untimed or advisory only | Timer survives reload and never auto-submits |
| PDF/exam mimic | Historical Practice source option | No current product contract | Deferred decision | Separate privacy, prompt-injection, similarity, and citation contract |
| Progressive first question | Historical starter/background batches | Current complete immutable revision | Superseded by default | Measure latency before adding safe staged delivery |
| Large exam batching | Historical generation experiments | Current bounded generation limits | Deferred | Load, cost, latency, and retention limits pass |
| Manual Flashcards | Historical deck/review APIs | Current Flashcard repository/workspace | Reimplemented | Create, study, review, archive/restore survive restart |
| Generated Flashcards | Historical topic/KB generation | Phase 5 Course and General Study generation | Reimplemented and superseded | Explicit plan, bounded call, atomic publication, citations |
| Missed-only Flashcards | Historical `review_mode=missed_only` | Current remediation and schedule | Partially superseded | Decide whether a visible shortcut adds value |
| Topic suggestions | Historical `/topic-suggestions` | Editable focus and smart conversation context | Superseded | Learner can edit the focus; unrelated context is excluded |
| Tester access codes | Historical `16888d3d` | Upstream authenticated accounts | Intentionally not ported as identity | Any future code grants eligibility, never data authority |
| TEEECHR-focused navigation | Historical learner shell | Current DeepTutor sidebar | Partial | Separate primary/advanced navigation plan is approved |
| Historical attempts/decks | Historical local databases | No reviewed importer | Deferred to original Phase 7 | Zero-write dry run classifies every record |

## 5. Locked decisions

- Authentication is the owner root; `course_id` is the learning boundary.
- Generated quizzes require a Course.
- Course generation includes relevant ready Course material by default.
- Source selection becomes visible when multiple ready sources exist.
- The learner reviews an editable quiz plan before any paid provider call.
- BlueWay material is ordinary owned Course material after verified import.
- BlueWay sync never automatically generates assessments.
- Generated questions require exact source citations.
- Grading is deterministic and server-side. The model does not decide mastery.
- General Study reviews do not affect Course mastery.
- Archive/restore remains the learner-visible deletion lifecycle.
- Manual Practice remains available when generation is disabled.

## 6. Decisions applied

### D6-01 — Timed assessment scope: implemented

- `untimed` and `practice timer` modes only.
- The timer shows elapsed time and survives reload.
- Expiry never silently submits or discards work.
- Strict proctored/exam enforcement remains out of scope.

### D6-02 — PDF/exam-mimic scope: deferred

“Make this look like
my professor’s exam” adds structure-extraction, imitation-quality, and
prompt-injection concerns that deserve a separate contract.

### D6-03 — Missed-answer remediation: implemented narrowly

Graded Practice attempts with misses expose `Review misses as Flashcards`.
The server resolves the owned attempt, immutable graded evidence, Course, and
source authority before preparing the existing editable Flashcard brief. A
separate historical scheduling filter named “missed only” remains unnecessary.

### D6-04 — Product shell: deferred

Plan branding and primary navigation as a separate
frontend slice after generated Practice works. Hiding upstream tools is an
information-architecture decision, not Practice cleanup.

### D6-05 — Draft plan retention

Draft plans are retained in the private Course database and remain editable
until confirmed or superseded by future policy. Phase 6 does not run a silent
expiry or deletion job. The `expired` state is reserved for a later explicit
retention contract and is not assigned by the current runtime.

### D6-06 — Provider configuration

Practice and Flashcard generation deliberately share the existing
deployment-owned study-generation credential, GPT-5 Mini binding, disabled-by-
default paid-use gate, per-owner concurrency fence, and persistent budget
ledger. Phase 6 adds no second key store or learner-controlled provider. A
separate Practice model/budget is future work if product-quality evidence
requires it.

## 7. Task breakdown

### P6-00 — Freeze parity and proof authority

- **Scope:** docs and read-only inventories.
- **Inputs:** historical `e991e79f`/`949f5a8e`, current `3243c0d5`, original
  roadmap, Phase 4 and Phase 5 closeouts.
- **Outputs:** this matrix and classified historical behaviors.
- **Acceptance:** every historical learner feature is classified; unrelated
  dirty/untracked paths remain untouched.
- **Doc alignment:** historical `TEEECHR_V152_PHASE1_CHANGE_MAP.md`.
- **Risk:** treating history as runtime authority. Verify current symbols/tests.

### P6-01 — Generated-quiz planning contract

- **Scope:** Practice request models, current generation API, client types, and
  contract tests.
- **Inputs:** Course, focus, count, difficulty, timing mode, optional sources,
  and optional Chat origin.
- **Outputs:** non-mutating plan/coverage response and confirmed generation
  request.
- **Acceptance:** preview makes zero provider calls; confirmation is
  idempotent; foreign sources return `404`; manual Practice remains available.
- **Doc alignment:** `generation_models.py` and
  `courses.py:create_generated_practice`.
- **Risk:** adding a second source-authority path. Reuse the current resolver.

### P6-02 — Practice creation journey

- **Scope:** `PracticeWorkspace.tsx` and narrow Practice client/types.
- **Inputs:** P6-01 plan and capability state.
- **Outputs:** Study/Create/Activity layout, manual/generated choice, editable
  plan modal, honest operation state, and automatic transition into the quiz.
- **Acceptance:** no raw provider code appears by default; failure preserves
  existing sets; a ready operation opens the quiz; accessibility passes.
- **Doc alignment:** Phase 5 Flashcard learner-shell patterns.
- **Risk:** recreating a dense control wall. Use progressive disclosure.

### P6-03 — Course Chat to quiz

- **Scope:** Course learner action proposal, Chat transition state, and Practice
  plan hydration.
- **Inputs:** exact owned assistant message, session binding, source snapshot,
  and learner request.
- **Outputs:** editable quiz plan opened from `Quiz me`.
- **Acceptance:** button click makes no provider call; stale, foreign,
  regenerated, or course-mismatched messages fail safely.
- **Doc alignment:** `courses.py:run_course_learner_action` and
  `ChatMessages.tsx`.
- **Risk:** trusting assistant prose as facts. Chat supplies intent; Course
  sources supply factual authority.

### P6-04 — Quiz attempt and result experience

- **Scope:** current attempt UI and result presentation; no grading rewrite.
- **Inputs:** immutable ready revision and existing attempt APIs.
- **Outputs:** focused question flow, autosave, review-before-submit, results,
  weak objectives, explanations, and history.
- **Acceptance:** reload resumes exactly; unknown attempt IDs never create
  replacements; submit/grade replay is idempotent; citations remain visible.
- **Doc alignment:** `attempt_repository.py`, `grading_repository.py`,
  `mastery_adapter.py`.
- **Risk:** browser state diverges from SQLite. Server state stays authoritative.

### P6-05 — Remediation and mastery closeout

- **Scope:** Practice results, Learning Space, weak-topic action, and Flashcard
  successor brief.
- **Inputs:** proven graded items with resolved Course objective IDs.
- **Outputs:** retry weak objectives, explain weak topic, or make remediation
  Flashcards.
- **Acceptance:** forged/unresolved objectives change no mastery; replay creates
  no duplicate evidence; General Study remains outside Course mastery.
- **Doc alignment:** `grading_service.py`, `mastery_adapter.py`, learner actions.
- **Risk:** overstating mastery from one attempt. Present evidence honestly.

### P6-06 — Optional bounded timer

- **Scope:** only if D6-01 is approved.
- **Inputs:** attempt start time and persisted elapsed-time receipt.
- **Outputs:** untimed or advisory practice-timer mode.
- **Acceptance:** reload cannot reset time; expiry does not silently submit;
  accessibility does not depend on rapid announcements.
- **Doc alignment:** `QuizAttempt` and attempt persistence.
- **Risk:** confusing a study timer with proctoring.

### P6-07 — Product-shell decision packet

- **Scope:** read-only navigation/branding inventory and implementation plan.
- **Inputs:** current sidebar, Course selector, historical learner shell, and
  college-companion goal.
- **Outputs:** primary/advanced navigation, naming boundary, route impact, and
  desktop/mobile wireframes.
- **Acceptance:** no route is deleted by assumption; learner tools are easy to
  find; deep links remain valid.
- **Doc alignment:** current `SidebarShell.tsx` and historical change map.
- **Risk:** mixing rebranding with learning correctness.

### P6-08 — Qualification and closeout

- **Scope:** affected tests, authenticated browser campaign, docs, changelog,
  and independent review.
- **Outputs:** exact-commit evidence matrix and parked-item list.
- **Acceptance:** Section 8 passes and the repository closeout backcheck runs.
- **Doc alignment:** Phase 4 and Phase 5 closeout receipts.
- **Risk:** calling local proof a production release.

## 8. Verification plan

### Contract and ownership

- Same-titled Courses and quizzes for Alice and Bob do not collide.
- Foreign Course/source/operation/Practice/attempt/evidence IDs return `404`.
- Two admins retain separate private Course workspaces.
- Disabled/deleted accounts lose authority on the next operation.
- Archived Course or changed write epoch blocks generation and remediation.
- Unknown attempt IDs never create replacement attempts.

### Generation

- Plan preview makes zero provider calls and publishes no quiz.
- Confirmation is exact-key idempotent.
- Provider unavailable, timeout, malformed output, missing citations, source
  replacement, archive, and revocation never publish a ready revision.
- Manual Practice works while provider use is disabled.
- Only ready owned sources appear in the plan.

### Attempts, grading, and mastery

- Answers survive browser and backend restart.
- Stale writes conflict instead of overwriting newer data.
- Submit and grade replay are idempotent.
- Only the immutable submitted snapshot is graded.
- Objective evidence is complete, bounded, and replay-safe.
- General Study and unresolved objectives cannot change Course mastery.

### Browser journeys

1. Course → Create → Generate → Review plan → Confirm → Start → reload →
   resume → submit → grade → remediate.
2. Course Chat → `Quiz me` → edit plan → confirm → complete quiz.
3. Provider disabled → manual Practice still works.
4. Alice/Bob same-title isolation.
5. Backend restart for private Practice/Flashcard identity and persistence.
6. Advisory timer reload/resume without a second attempt.

### Proof surfaces kept separate

- Source/diff review.
- Backend tests.
- Frontend tests/typecheck/build.
- Authenticated browser runtime.
- Bounded paid-provider proof.
- Historical migration dry run.
- Upstream reconciliation.
- Staging/deployment/release.

## 9. Risks and unknowns

- Provider safety tests do not prove pedagogical quality across subjects.
- Current atomic ready revisions may trade latency for consistency; measure
  time-to-first-useful-question before adding staged generation.
- The advisory timer is not proctoring and never auto-submits.
- PDF/exam mimic is excluded pending a separate contract.
- The current app still exposes upstream tools and DeepTutor branding.
- Functionality parity does not migrate historical learner records.
- Current work remains based on v1.5.2 while upstream was observed at v1.5.5.

## 10. Exit criteria

Phase 6 Closeout is complete only when:

1. Generated quizzes work from Course and Course Chat.
2. Attempts, grading, mastery, citations, and remediation survive restart and
   ownership attacks.
3. The timer, PDF/exam-mimic, missed-answer remediation, draft retention,
   provider-binding, and product-shell boundaries above are reflected in code
   or explicitly deferred.
4. Every historical feature remains classified.
5. Documentation and changelog match the final tree.
6. Tracked, untracked, staged, and unstaged state are reviewed.
7. Closeout and independent security/usability reviews have no must-fix issue.
8. Paid proof, push, merge, deployment, import, and upstream integration remain
   separately authorized.

## 11. Recommended execution order

```text
P6-00 parity authority
  -> user decisions D6-01 through D6-04
  -> P6-01 generated-quiz plan contract
  -> P6-02 Practice creation journey
  -> P6-03 Course Chat transition
  -> P6-04 attempt/result experience
  -> P6-05 remediation/mastery closeout
  -> optional P6-06 bounded timer
  -> separately reviewed P6-07 product shell
  -> P6-08 qualification and closeout
```

## 12. Local qualification receipt

The implementation and qualification tree was reviewed against accepted Phase 5
head `3243c0d5`. The reviewed implementation commits are `c0e7f5a7` and
`73ef9ed3`; no push, merge, deployment, historical import, BlueWay mutation, or
upstream integration is part of this receipt.

### Implemented

- Owner-bound, revisioned, retained Practice generation plans with separate
  creation and confirmation idempotency.
- Exact ready-source receipts, optimistic Course/write-epoch fences, immutable
  plan authority, SQL-level confirmation bindings, and cancellation fencing.
- Explicit confirmation before provider admission; plan review performs no
  provider work.
- Guarded GPT-5 Mini Practice adapter using the existing encrypted
  study-generation credential, per-owner concurrency, and persistent budget
  ledger. Missing evidence, malformed output, timeouts, and uncertain
  accounting fail closed.
- Study/Create/Activity Practice UI, Course Chat `Quiz me` handoff, editable
  review dialog, automatic launch, reload-safe attempt resume, advisory timer,
  deterministic grading, Course source labels, and missed-answer Flashcard
  remediation.
- Historical completed generation operations are not replayed on later Practice
  visits; only active queued/running work is restored automatically.

### Validation

- Full Course backend suite: `322 passed`, `6 warnings`.
- Focused migration/generation replay and adversarial SQL suite: `42 passed`.
- Frontend Node contract suite: `210 passed`.
- TypeScript: passed.
- Focused ESLint: `0 errors`, `85 warnings`; warnings are the existing literal
  localization debt plus an existing image warning, not correctness failures.
- Next production build: passed, `54` routes.
- Authenticated deterministic browser campaign: `10` journeys passed, including
  exact one confirmation, no legacy direct-generation call, generated quiz
  launch, advisory timer, reload resume without a second attempt, grading,
  Course source labels, multiple/no-source selection behavior, mobile focused
  quiz-taking, and Course Chat handoff.
- Ruff, shell syntax, migration replay, and diff integrity: passed.
- Three independent read-only Luna reviews covered database integrity,
  provider/security, and learner UI. Their must-fix SQL authority and stale
  operation replay findings were repaired and regression-tested.
- No paid provider call was made during Phase 6 qualification.

### Bounded paid-provider follow-up — 2026-07-31

- The user authorized a total Practice investigation ceiling of 300,000
  microusd ($0.30). Each attempt retained a separate 10,000-microusd ($0.01)
  admission cap. All requests used the same owned ready source for one private
  Course, `store=false`, no tools, no SDK retries, three questions, and one
  explicit confirmation.
- Attempt A terminated `failed/provider_failed` without settleable usage. Its
  6,278-microusd reservation remains `uncertain`; no quiz was published.
- A content-free diagnostic boundary was added and tested before the second
  request. Attempt B proved an HTTP 400 `invalid_request` at the provider
  boundary. Its 6,277-microusd reservation remains `uncertain`; no quiz was
  published. Raw provider messages and learner material were not logged.
- OpenAI's Structured Outputs contract confirmed that arrays support
  `minItems` and `maxItems`, but not the Practice schema's `uniqueItems`
  keyword. The keyword was removed while TEEECHR's existing normalization
  retained duplicate-objective rejection. Focused provider, generation, and
  governance tests passed before another request was admitted.
- Repaired attempt C completed and atomically published three grounded
  questions. Its ledger row settled with 922 input tokens, 509 output tokens,
  and an actual cost of 1,249 microusd ($0.001249), against a 6,273-microusd
  reservation. A real local API journey then started the quiz, autosaved all
  three responses, submitted, deterministically graded, and returned three
  result questions. Raw Course and operation identifiers remain only in the
  governed private runtime stores, not in this repository receipt.
- An authenticated Chrome journey then opened that exact paid-generated quiz
  through the normal learner UI, started one new attempt, saved an answer,
  reloaded the page, and recovered the same attempt and answer without creating
  a replacement. It completed the remaining answers, submitted, graded, showed
  the three Course-source labels, persisted the 67% result in attempt history,
  and opened the missed-answer Flashcard review handoff. The 67% result also
  re-proved the locked deterministic exact-answer contract: two exact answers
  passed, while a semantically similar but non-exact third answer remained a
  miss. Semantic or model-based grading is not part of Phase 6.
- In the same browser session, provider-disabled Create showed the manual
  fallback and made no provider request. Activity presented the retained failed
  operation with learner-safe copy and no raw provider error. A later beta-
  quality follow-up removed unpublished failed generated shells from the normal
  Study library while retaining their private Activity recovery history. A
  recovered failed shell with a ready revision remains visible.
- Total Practice accounting exposure from this follow-up is 13,804 microusd
  ($0.013804): 12,555 microusd retained conservatively as two uncertain
  reservations plus 1,249 microusd settled usage. The shared provider and paid
  usage policy were disabled after every attempt and are disabled at closeout.
- Post-repair validation passed the focused provider suite (`11 passed`) and
  the complete Practice suite (`192 passed`, one existing warning), plus Ruff,
  diff integrity, and the independent read-only closeout review.

### Practice/Quiz beta-quality follow-up — 2026-07-31

- Course changes now clear the prior Course's sets, sources, attempts, and
  operations immediately and show an exact-Course loading state until the new
  owner-scoped data is complete. A stable load epoch prevents the view-epoch
  change performed by successful loading from leaving the page permanently
  busy.
- The Study library prioritizes ready quizzes, separates archived quizzes, and
  keeps failed unpublished generation shells in Activity rather than presenting
  them as normal learner work. Failed and cancelled operations expose safe
  review/retry and manual actions.
- Starting a quiz now enters a focused, one-question surface with numbered
  navigation, previous/next controls, answer autofocus, explicit saved-state
  requirements, guarded Submit, abandonment confirmation, and responsive
  390x844 behavior. Results lead with `correct out of total`, explain misses,
  preserve Course source labels, and offer retry or missed-answer Flashcards
  only when appropriate.
- The answer persistence boundary now rejects malformed, extra-field, non-text,
  and overlong exact-answer payloads before they can be written. Current
  `exact-v1` behavior is explicitly proven as Unicode NFC, trim, and case-fold
  equivalence; extra wording, punctuation changes, and simple-number formatting
  remain intentionally unequal.
- Fairer variants are parked for a new `exact-v2` schema/evidence contract.
  Changing `exact-v1` grading in place would make already-persisted immutable
  grading evidence non-reproducible.
- Provider-free closeout passed `216` Practice/Course backend tests, `52`
  focused grading/persistence tests, `210` frontend Node tests, TypeScript, and
  `10` authenticated browser journeys. No paid provider call was made in this
  follow-up.
- Current-tree production builds compiled and typechecked; Turbopack generated
  all 54 routes. The later stabilization audit isolated the non-terminating
  worker behavior to unsupported Node.js 26. The same build completed and
  exited successfully under Node.js 24.14.0, and a prebuild guard now rejects
  unsupported Node majors. This remains local build proof, not browser,
  deployment, or release authority.

### Deliberately separate or unproved

- Browser-level cancel during a live queued/running worker and browser failure
  presentation are not claimed; cancellation, late-result discard, and
  provider failures are covered at repository/service/API contract level.
- Browser UI proof of the paid generation *confirmation and in-flight operation*
  is not claimed. The repaired provider request and publication were proved
  through the authenticated local API, and the resulting real quiz was then
  proved through the authenticated Chrome learner lifecycle. The existing
  provider-free browser suite remains a separate repeatable surface.
- Staging, deployed, and release-artifact builds remain unproved. The current
  tree now has a clean local production-build exit under an evidenced supported
  Node runtime, but that does not establish any hosted or packaged artifact.
- Historical learner-data migration, upstream reconciliation, staging,
  production, multi-server coordination, product-shell redesign, strict exam
  mode, and PDF/exam mimic remain parked.

### 2026-08-01 - Luna qualification and runtime-policy transition

- Phase 6 learner acceptance remains closed through `315510e1`.
- Reviewed commit `a113ebed` promotes Practice generation to
  `gpt-5.6-luna` with medium reasoning through the central typed registry.
  Mini remains dormant emergency rollback and is not selected by an active
  feature.
- The frozen Course and General Study Practice cases passed Luna-medium live
  qualification, human review, requested/actual-model validation, pricing
  receipts, and the zero-retry/capped-call contract. The exact committed slice
  passed 196 impacted tests plus Ruff, diff, credential, and local-path checks.
- The local active usage policy was backed up and moved to pricing authority
  `openai-gpt-5.6-luna-2026-08-01` only after confirming zero reserved
  operations. Eleven settled and five uncertain historical Mini reservations
  remain immutable. Fresh no-call provider resolution reports Practice
  available.
- The current backend and frontend restarted successfully from `a113ebed`.
  Authenticated post-restart Practice Create exposed the AI quiz-planning form,
  including the server-derived `Using BlueWay verified course bundle` status,
  and did not show the disabled-provider fallback. The check stopped before
  confirmation, so it made no provider call.
- The non-terminating production-build boundary was isolated to the machine's
  unsupported Node.js 26 runtime. Under Node.js 24.14.0 the full current-tree
  Next build compiled, typechecked, generated all 54 routes with 17 workers,
  finalized, and exited successfully. The web package now accepts only the
  evidenced Node 22/24 lines, rejects unsupported majors before building, and
  selects Node 22 LTS through `.nvmrc`. No deployment or release authority is
  claimed.
