# TEEECHR v1.5.2 Practice and Quiz Quality Checklist

Status: **closed for the current single-host beta with explicit parked items**

Priority: **Practice/Quizzes first; Flashcards support quiz remediation**

Scope: private Course learning on the single-host TEEECHR beta

Last reviewed: 2026-07-31

This document is the working finish line for the learner-facing Practice
experience. Each item is crossed off only when the implementation, the relevant
test, and the required user-facing proof agree. A passing unit test does not by
itself prove that the browser journey works, and a browser screenshot does not
prove ownership or persistence.

## Status and evidence rules

- `[ ]` open; `[x]` completed with evidence recorded beside the item; `[!]`
  blocked or failed and requires a decision or repair.
- Every completed item should record at least one of: test command, test name,
  browser journey, API proof, database/provenance proof, or human review.
- Keep provider, browser, backend/database, security, and release claims
  separate.
- Do not mark a provider-paid item complete when only a fake provider was used.
- Do not mark a deployment or phone item complete from local browser evidence.

## Product hierarchy

The beta learning loop is intentionally ordered as:

```text
Course → Practice/Quiz → Results → Missed concepts → optional Flashcards
                         ↑
                   Course Chat
                         ↑
                    BlueWay sources
```

- Practice/Quizzes are the primary assessment and learning surface.
- Flashcards are an optional recovery tool for missed concepts.
- Course Chat prepares, explains, and can hand off to a reviewed quiz plan.
- BlueWay supplies owned Course material; it does not silently generate quizzes.

## A. Quiz creation and review

### A1. Course and source context

- [x] Switching Courses shows a clear loading state instead of a misleading
  empty Practice library. Evidence: authenticated browser Course-load delay
  assertion; `PracticeWorkspace.tsx` exact-Course load epoch.
- [x] Old Course sets, sources, attempts, and operations disappear before the
  new Course data is displayed. Evidence: stale-scope Node tests and the
  authenticated delayed Course-switch browser journey.
- [x] The selected Course, source list, and generated quiz all resolve through
  the authenticated owner and Course parent. Evidence: full Practice ownership
  suite (`216 passed`) and authenticated Alice/Bob browser restart journey.
- [x] A Course with one ready source uses that source automatically. Evidence:
  Phase 6 generation browser journey.
- [x] A Course with multiple ready sources exposes source selection clearly.
  Evidence: `phase6 source choices distinguish multiple materials...`.
- [x] A Course with no ready source explains that generation cannot proceed and
  offers the manual Practice path. Evidence: the same authenticated browser
  journey verifies the blocked review action and visible manual fallback.
- [x] Generated questions retain Course-source labels in results. Evidence:
  authenticated Chrome journey on 2026-07-31; `PracticeWorkspace.tsx` result
  citations.

### A2. Request planning

- [x] Opening the quiz plan performs no provider call. Evidence: Practice
  generation contract and browser/provider-free tests.
- [x] The review surface clearly shows Course, focus, source material, count,
  difficulty, timing, destination, and whether AI work will occur.
  Evidence: authenticated modal journey checks Course, destination, focus,
  count, material count, difficulty, timing, and the explicit AI confirmation.
- [x] The learner can edit the plan before confirmation without losing context.
  Evidence: Phase 6 browser plan-edit assertion and revisioned-plan tests.
- [x] Closing or cancelling the review leaves no provider operation or partial
  quiz. Evidence: provider-call counter in the modal browser journey and
  non-mutating preview contract tests.
- [x] Repeated confirmation with the same idempotency key does not create a
  duplicate quiz or duplicate paid request. Evidence: generation API,
  repository, SQL replay, and budget-ledger tests.
- [x] Double-clicking or rapidly pressing confirmation is safe. Evidence: the
  UI disables confirmation while busy and server confirmation remains
  exact-key idempotent.
- [x] A stale source, archived Course, revoked account, or changed write epoch
  blocks confirmation without publishing a ready quiz. Evidence: generation
  service/API and adversarial Course tests in the `216 passed` suite.
- [x] The learner can understand the difference between manual and AI-created
  Practice without seeing provider or database terminology. Evidence:
  authenticated provider-off and no-source browser journeys.

### A3. Generation lifecycle

- [x] Provider-disabled Create shows a manual fallback and makes no provider
  request. Evidence: authenticated Chrome journey on 2026-07-31.
- [x] Provider failures do not publish a ready quiz or overwrite an existing
  ready quiz. Evidence: generation repository/service/API tests.
- [x] Failed operations use learner-safe copy in Activity and do not expose raw
  provider errors. Evidence: authenticated Chrome Activity journey on
  2026-07-31.
- [x] Queued, running, completed, failed, and cancelled states each have a
  clear next action. Evidence: Activity renders retained operation history;
  failed/cancelled operations offer review/retry and manual paths.
- [x] Refreshing or restarting during queued/running work produces a truthful
  status and does not replay completed work. Evidence: startup reconciliation,
  operation-list, and completed-operation replay regression tests.
- [!] Browser-level cancellation during live queued/running work is not proven.
  Decision: keep the server/API cancellation and late-result-discard proof as
  authority; park a live slow-provider browser capture because it adds no beta
  data-integrity authority and would require a specially controlled worker.
- [x] A real GPT-5 Mini provider operation was bounded, settled, and published
  three grounded questions under the approved cost ceiling. Evidence: private
  ledger/runtime receipt; no provider gate remained enabled at closeout.
- [!] The paid provider confirmation-and-in-flight journey is not proven through
  the browser. Decision: the bounded real-provider API proof and the resulting
  authenticated browser quiz lifecycle remain separate; do not spend again
  solely to capture a transient UI state.

### A4. Practice library

- [x] Ready quizzes are visually primary. Evidence: ready-first library sorting
  and authenticated browser journey.
- [x] In-progress attempts are easy to resume. Evidence: the primary action is
  “Start or resume quiz”; reload restores the same attempt.
- [x] Archived quizzes are separated from active quizzes. Evidence: archived
  items render under a collapsed `Archived quizzes` section.
- [x] Manually created drafts remain understandable and editable. Evidence:
  provider-free manual Practice browser journey.
- [x] Failed provider-created draft shells do not clutter the normal Study list,
  or are clearly labelled as historical failed attempts with an obvious action.
  Evidence: `practiceLibrarySets` filters unpublished failed shells; Activity
  retains their recovery history; Node regression tests cover recovered shells.
- [x] A user can tell whether a listed item is ready to take, still being built,
  unfinished, failed, or archived. Evidence: Study library state labels,
  separate archive section, and Activity lifecycle presentation.

## B. Quiz-taking experience

### B1. Start and navigation

- [x] A ready quiz can start an attempt from the normal Practice UI. Evidence:
  authenticated Chrome journey on 2026-07-31.
- [x] The quiz becomes a focused assessment surface after Start; creation and
  archive controls should not compete with answering questions.
- [x] Question progress is visible and understandable.
- [x] Questions can be navigated by clear numbering or Next/Back controls.
- [x] The learner does not see unrelated questions or internal revision details
  while answering.
- [x] Keyboard navigation and focus order are usable.
- [x] Narrow screens do not hide the answer field or Submit action.
  Evidence for the five items above: authenticated two-question browser journey
  at 390x844 verifies focused controls, numbered navigation, autofocus, Enter
  save/advance, answer-field bounds, and visible Submit.

### B2. Answers and persistence

- [x] Answers autosave through the server-owned attempt. Evidence: browser
  journey and attempt repository tests.
- [x] Reload resumes the same in-progress attempt and restores a saved answer.
  Evidence: authenticated Chrome journey on 2026-07-31.
- [x] Unsaved changes are visibly distinguishable from saved answers. Evidence:
  numbered navigation exposes answered/unanswered state and Submit explains
  unsaved work.
- [x] Submit is blocked while required answers are unsaved or missing. Evidence:
  browser journey and component state contract.
- [x] A network failure during save preserves the local text and explains how to
  retry.
  Evidence: answer text remains component-owned until a successful save; the
  shared alert surfaces the API failure without advancing.
- [x] Abandoning with unsaved work requires an understandable confirmation.
  Evidence: inline “Leave this attempt” confirmation and persistence tests.
- [x] Unknown or foreign attempt identifiers do not create replacement attempts.
  Evidence: ownership/attempt contract tests.

### B3. Submit, grade, and history

- [x] Submission transitions the attempt to submitted without losing answers.
  Evidence: authenticated Chrome journey on 2026-07-31.
- [x] Grading is server-authoritative and idempotent. Evidence: grading
  repository/API tests and browser result proof.
- [x] Results persist in attempt history and can be reopened. Evidence:
  authenticated Chrome journey on 2026-07-31.
- [x] Repeated Grade clicks never duplicate evidence or alter the score.
  Evidence: grading replay/idempotency and mastery-evidence tests.
- [x] Starting a new attempt is explicit and does not mutate a previous graded
  attempt.
- [x] Attempt history clearly distinguishes in-progress, submitted, graded,
  abandoned, and archived/revision states.
  Evidence: attempt history uses persisted server state and score; historical
  revisions are read-only.
- [x] Perfect results clearly say there are no missed concepts to remediate.
  Evidence: provider-free browser journey verifies `2 correct out of 2`, the
  perfect-result message, and absence of missed-answer remediation.

## C. Grading quality and learner trust

- [x] The current deterministic exact-answer contract is documented and tested.
  Evidence: grading repository and contract tests.
- [!] Multiple accepted deterministic answer variants are deferred to a new
  `exact-v2` evidence contract. Changing `exact-v1` in place would make prior
  immutable grading evidence non-reproducible.
- [!] Punctuation and simple-number equivalence are deferred with `exact-v2`.
  Current `exact-v1` intentionally applies Unicode NFC, surrounding-whitespace
  trim, and case folding only; it rejects extra wording, punctuation changes,
  and `1,000` versus `1000`.
- [x] Explain the expected answer after a miss without exposing hidden answer
  contracts before grading.
- [x] Add a short pre-quiz explanation that answers are checked deterministically
  and that capitalization and surrounding spaces do not matter.
- [x] Do not introduce model-assisted grading until accuracy, cost, privacy,
  latency, and appeal/review behavior have a separate approved contract.
- [x] Add tests for current-contract equivalents, extra wording, empty answers,
  very long answers, malformed answer payloads, and Unicode normalization.
  Evidence: `test_grading_contract.py` and `test_attempt_contract.py`; malformed
  and overlong payloads now fail before persistence.

## D. Results, citations, and remediation

- [x] Each generated result question shows its owned Course source label.
  Evidence: authenticated Chrome journey on 2026-07-31.
- [x] Results lead with “correct out of total” and a useful explanation, not
  only a percentage.
- [x] Missed questions visibly explain what needs review.
- [x] A missed graded attempt opens the existing Flashcard remediation brief.
  Evidence: authenticated Chrome journey on 2026-07-31.
- [x] Remediation names the missed concepts and destination before any provider
  call.
- [x] Remediation never changes the original quiz score or silently changes
  Course mastery.
- [x] A perfect quiz does not offer a missed-question deck.
- [x] Repeating remediation does not create duplicate cards without explicit
  learner confirmation.
  Evidence for Results/remediation: authenticated result journeys, remediation
  proposal/idempotency tests, and immutable grading/mastery tests.

## E. Course Chat handoff

- [x] “Quiz me” appears only for suitable owned assistant responses.
- [x] Chat opens the same editable Practice plan used by the Practice page.
- [x] The plan shows a concise explanation of which recent conversation context
  was selected.
- [x] Unrelated earlier messages are excluded.
- [x] A stale, foreign, regenerated, deleted, or Course-mismatched message fails
  safely before provider work.
- [x] A course-less conversation remains conversation-drafted and is not falsely
  labelled Course-grounded.
- [x] Chat-to-quiz confirmation remains idempotent and owner-bound.
  Evidence: Course Chat authenticated browser journey plus learner-action,
  message-binding, stale-scope, and General Chat provenance contract tests.

## F. Archive, restore, and identity safety

- [x] Archiving a ready quiz removes it from the active list or labels it clearly.
- [x] Restoring returns the same quiz identity and history.
- [x] Archived quizzes remain readable but reject new writes.
- [x] No permanent-delete path is reachable from the UI.
- [x] User A cannot list, read, attempt, grade, or remediate User B’s quiz,
  source, operation, evidence, or attempt by changing an identifier.
- [x] Logout clears cached Course and Practice state.
- [x] Logging in as another user cannot display the previous user’s active Course
  or quiz history.
- [x] Administrator role does not grant access to another person’s private
  Course workspace.
  Evidence: Course/Practice ownership and archive contract tests plus the
  authenticated Alice/Bob restart and cache-isolation browser journey.

## G. Error recovery and accessibility

- [x] Network failure during generation provides a retry or manual fallback.
- [x] Server restart during an attempt preserves the durable state.
- [x] Server restart during generation reconciles the operation honestly.
- [x] Provider timeout, malformed output, missing evidence, and quota denial each
  produce safe learner copy and no partial ready quiz.
- [x] Dialog focus is trapped, labelled, and restored when the dialog closes.
- [x] All controls have unique accessible names in the covered Practice journey.
- [x] Disabled controls explain what prerequisite is missing.
- [!] Keyboard interaction is browser-proven for quiz answering and modal focus,
  but a formal screen-reader pass across Create, Study, Results, and remediation
  remains a release-accessibility task.
- [x] Desktop and mobile-width browser layouts remain usable; the 390x844 proof
  verifies that the answer field and Submit stay within the viewport.
  Evidence: generation/reconciliation/provider contract tests, modal browser
  assertions, provider-off/manual fallback, and responsive browser proof.

## H. Cost, security, and release boundaries

- [x] Provider use is disabled by default at closeout. Evidence: runtime
  capability state and provider-off browser journey.
- [x] Paid investigation remained under the approved `$0.30` ceiling. Evidence:
  private usage ledger receipt.
- [x] Every paid request has one explicit confirmation, one owner-bound
  operation, a budget reservation, and a durable outcome.
- [x] No automatic paid retry occurs after an uncertain provider outcome.
- [x] Provider logs contain only bounded, content-free diagnostics.
- [x] Secrets, raw provider prompts, Course excerpts, and learner answers are
  absent from normal logs and repository artifacts.
- [x] No deployment, TestFlight, multi-server, BlueWay write-back, or upstream
  reconciliation claim is made from this local checklist.
  Evidence: provider governance/security tests, bounded 2026-07-31 ledger
  receipt, secret/diff review, and disabled shared-provider/paid-use gates.

## I. Flashcards: intentionally secondary

These items support the quiz loop but do not block the primary quiz experience:

- [x] Missed-answer Flashcards use a clear editable brief.
- [x] The user can review the destination, source context, and card count before
  generation.
- [x] Flashcard creation does not happen automatically after every quiz or
  BlueWay sync.
- [x] Flashcard review does not silently alter Course quiz mastery.
- [!] Advanced Flashcard scheduling, spoken answers, adaptive decks, sharing,
  notifications, and cross-Course decks remain parked unless separately
  approved. Decision: these are future product slices and do not block the
  accepted beta Practice loop.

## Completion receipt

Repository:
`/Users/home/Desktop/2k26/teeech/DeepTutor-v1.5.2-baseline`

Branch: `feature/teeechr-v152-phase5-course-study-intelligence`

Accepted Phase 5 base: `3243c0d5`

Phase 6 implementation base before this quality pass: `8fb153f8`

Tested head: the reviewed local quality-checklist commit recorded in the final
closeout; no remote, merge, or deployment claim is implied.

### Proof surfaces

- Backend/database: `.venv/bin/python -m pytest tests/courses/practice
  tests/courses/test_phase4_beta.py tests/courses/test_course_learner_actions.py
  -q` → `216 passed`, one existing warning.
- Focused grading/persistence: `.venv/bin/python -m pytest
  tests/courses/practice/test_attempt_contract.py
  tests/courses/practice/test_grading_contract.py -q` → `52 passed`.
- Frontend contracts: `cd web && npm run test:node` → `210 passed`.
- TypeScript: `cd web && npx tsc --noEmit` → passed.
- Production artifact: both the default Turbopack build and a Webpack
  discriminator compiled and typechecked this tree; Turbopack also generated
  all 54 routes. Neither local process terminated cleanly after its final build
  phase, so this receipt does not claim a clean current-tree production-build
  exit. The authenticated runtime proof remains separate.
- Focused ESLint: `0 errors`; literal-localization warnings remain separately
  tracked and do not change the English-only beta behavior.
- Authenticated browser: `./scripts/test-phase4-browser` → `10` journeys passed
  across disposable Alice/Bob accounts, actual backend restarts, provider-off
  manual Practice, focused/mobile quiz taking, Flashcard regressions, Course
  and General Chat handoffs, exact-one confirmation, generated quiz reload,
  citations, multiple sources, and no-source manual fallback.
- Provider ledger: the separately approved GPT-5 Mini investigation published
  three grounded questions for 1,249 microusd actual usage; two earlier safe
  failures remain conservatively reserved, for 13,804 microusd total exposure.
  Both provider gates were disabled afterward. This quality pass made no paid
  call.

This receipt is ready for a reviewed local commit only. Push, merge, deployment,
TestFlight, production release, historical migration, and upstream
reconciliation each require separate approval.

### Explicitly parked `[!]` items

- Live browser capture of cancellation during a deliberately slow provider job.
- Paid browser capture of confirmation and the transient in-flight state.
- Versioned `exact-v2` accepted variants, punctuation, and number equivalence.
- Formal screen-reader certification beyond the current keyboard/focus proof.
- Clean production-build process exit; the current source compiled and
  typechecked, but local Next.js worker shutdown did not complete.
- Advanced secondary Flashcard features listed in Section I.

The failed-shell library cleanup, Course-switch stale-state prevention,
mobile/keyboard quiz flow, and current-build two-user isolation are complete in
this receipt.
