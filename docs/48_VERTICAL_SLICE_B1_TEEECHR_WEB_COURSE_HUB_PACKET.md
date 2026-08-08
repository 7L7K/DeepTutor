# Vertical Slice B1 — TEEECHR Web Course Hub Packet

Status: Phase 0 baseline ledger accepted; B1 UI start gate accepted with Chat deferred
Date: 2026-08-07
Branch: `feature/teeechr-web-course-hub-slice-b1`
Base: `ffa8233763ad621c170575f27f41d7fdec623691`

## Scope

B1 is the authenticated TEEECHR web Course Hub slice:

- Classes-first authenticated Home;
- stable owner-private Course Hub;
- persistent Course title and term identity;
- truthful null states;
- only destinations that already work;
- no fabricated Progress, recommendations, or timeline intelligence.

BlueWay remains the academic-life and Course-entry product. TEEECHR web owns
the Course learning workspace. The old BlueWay-hosted Course workspace plan is
superseded; see
[`47_BLUEWAY_TEEECHR_PRODUCT_BOUNDARY_CORRECTION.md`](47_BLUEWAY_TEEECHR_PRODUCT_BOUNDARY_CORRECTION.md).

The following are explicitly outside B1: BlueWay launch/SSO, syllabus parsing,
Course timeline intelligence, Study Sessions, recommendation engine, Progress
redesign, hosted deployment, production configuration, frozen migration SQL,
and release certification.

## Protected checkout and setup

- Worktree: `/Users/home/Desktop/2k26/teeech/DeepTutor-web-course-hub-b1`
- Branch: `feature/teeechr-web-course-hub-slice-b1`
- Base/initial HEAD: `ffa8233763ad621c170575f27f41d7fdec623691`
- Node: `/opt/homebrew/opt/node@22/bin/node` — v22.23.2
- npm: 10.9.8
- Python: `/Users/home/.codex/runtimes/teeechr-b1-python311/bin/python` — 3.11.15
- pytest: 8.4.2
- Web dependencies: installed with `npm ci --legacy-peer-deps`; lockfile unchanged
- Backend development dependencies: installed in the external Python environment
- Original per-test ledger logs: `/tmp/teeechr-b1-baseline-ledger-20260807/`

No BlueWay checkout, Slice A branch, historical-migration worktree, hosted
environment, production secret, or frozen migration SQL was modified.

## Untouched baseline

The first complete backend baseline, after only external environment setup,
was:

```text
3845 passed, 16 failed, 8 skipped, 10 warnings
```

The 16 failures were each rerun individually twice with `pytest -vv --tb=short`.
All 32 individual runs reproduced exit code 1. None was order-dependent. The
exact command used for the aggregate baseline was:

```text
/Users/home/.codex/runtimes/teeechr-b1-python311/bin/python -m pytest -q tests
```

## Accepted Phase 0A failure ledger

`Yes` in a surface column means the failure blocked claiming that B1 surface
until the maintenance boundary was repaired or the failure was deliberately
deferred. `No` means there is no direct B1 contract dependency. For the Course
schema rows, all Course-backed surfaces are marked `Yes` because they cannot
claim owner-private Course behavior against an unverified schema bootstrap.

| # | Exact test node | Classification | Phase 0C disposition | Classes Home | Course Overview | Materials | Practice | Review | Chat |
|---:|---|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | `tests/agents/chat/test_agent_loop.py::test_loaded_deferred_tool_is_authorized_on_next_round_only` | `TEST_ISOLATION` | Deferred; test loader bypasses the production provider-view setup and leaves live schemas unset. No agent redesign in B1. | No | No | No | No | No | Yes |
| 2 | `tests/agents/chat/test_cli_app_wiring.py::test_an_unrelated_tool_is_not_handed_a_sandbox` | `STALE_TEST_EXPECTATION` | Deferred; current security contract rejects unattached RAG instead of returning augmented kwargs. | No | No | No | No | No | Yes |
| 3 | `tests/agents/chat/test_context_budget.py::test_forced_finish_still_reports_the_tools_the_turn_carried` | `TEST_ISOLATION` | Deferred; fake registry/context does not satisfy the current provider view and attached-KB contract. | No | No | No | No | No | Yes |
| 4 | `tests/courses/migrations/test_baseline_adoption.py::test_exact_legacy_profiles_adopt_without_rewriting_domain_rows[course_only]` | `STALE_TEST_EXPECTATION` | Fixed in maintenance diff: authoritative ledger is 0–13, not 0–11. | Yes | Yes | Yes | Yes | Yes | Yes |
| 5 | `tests/courses/migrations/test_baseline_adoption.py::test_exact_legacy_profiles_adopt_without_rewriting_domain_rows[full]` | `STALE_TEST_EXPECTATION` | Fixed: expected 0–13; digest ignores only the nullable `external_term_id` columns introduced by migration 12. Existing values remain unchanged. | Yes | Yes | Yes | Yes | Yes | Yes |
| 6 | `tests/courses/migrations/test_runner.py::test_receipt_uses_exact_artifact_bytes_and_tamper_blocks_before_writes` | `STALE_TEST_EXPECTATION` | Fixed: expected authoritative ledger through 13. Frozen SQL unchanged. | Yes | Yes | Yes | Yes | Yes | Yes |
| 7 | `tests/courses/migrations/test_runner.py::test_concurrent_startup_applies_once_and_other_wrapper_observes_receipt` | `STALE_TEST_EXPECTATION` | Fixed: concurrent receipt expectation now includes 12–13. | Yes | Yes | Yes | Yes | Yes | Yes |
| 8 | `tests/courses/migrations/test_runner.py::test_spawned_processes_first_start_apply_once_and_converge_on_one_receipt` | `STALE_TEST_EXPECTATION` | Fixed: spawned-process receipt expectation now includes 12–13. | Yes | Yes | Yes | Yes | Yes | Yes |
| 9 | `tests/courses/practice/test_attempt_contract.py::test_migration_0002_replay_tamper_and_rollback_are_transactional` | `STALE_TEST_EXPECTATION` | Fixed: expected ledger through 13. | Yes | Yes | Yes | Yes | Yes | Yes |
| 10 | `tests/courses/practice/test_attempt_contract.py::test_upgrade_from_exact_p4_02b_state_applies_generation_migrations_and_preserves_rows` | `STALE_TEST_EXPECTATION` | Fixed: expected migration sequence through 13. | Yes | Yes | Yes | Yes | Yes | Yes |
| 11 | `tests/courses/practice/test_flashcard_contract.py::test_upgrade_from_exact_p4_05_receipts_applies_flashcards_then_generation` | `STALE_TEST_EXPECTATION` | Fixed: expected migration sequence and ledger through 13. | Yes | Yes | Yes | Yes | Yes | Yes |
| 12 | `tests/services/codex_auth/test_credential_location.py::test_relocation_ignores_a_symlinked_legacy_directory` | `TEST_ISOLATION` | Fixed in test fixture ordering. The private-tree symlink guard remains fail-closed. | Yes | Yes | Yes | Yes | Yes | Yes |
| 13 | `tests/services/codex_auth/test_credential_location.py::test_relocation_refuses_a_symlinked_private_parent` | `TEST_ISOLATION` | Fixed in test fixture ordering. The private-parent symlink invariant remains fail-closed. | Yes | Yes | Yes | Yes | Yes | Yes |
| 14 | `tests/services/config/test_runtime_settings.py::test_startup_ensure_creates_missing_runtime_jsons_with_defaults` | `TEST_ISOLATION` | Fixed by redirecting the deployment-owned model catalog to the test temp path; no user-local config is committed. | Yes | Yes | Yes | Yes | Yes | Yes |
| 15 | `tests/services/session/test_turn_event_flush.py::test_flush_mirrors_whole_batch_in_one_file_write` | `TEST_ISOLATION` | Fixed by modeling the SQLite-derived `user/workspace/chat/chat` mirror path. Persisted DB and JSONL events were verified. | No | No | No | No | No | Yes |
| 16 | `tests/services/session/test_turn_event_flush.py::test_flush_is_idempotent_per_execution` | `TEST_ISOLATION` | Fixed by the same path-contract fixture correction; idempotent DB and JSONL persistence was verified. | No | No | No | No | No | Yes |

### Classification notes

- Migration versions 12 and 13 are authoritative checked-in migrations. The
  tests were stale; `deeptutor/courses/migrations/sql/*.sql` was not edited.
- The credential failures were caused by introducing hostile symlinks before
  the test resolved the owner directory. The runtime correctly rejects a
  symlink anywhere in a private workspace.
- Runtime settings already call the model-catalog bootstrap. The test still
  assumed the pre-admin-owned path resolver; it now supplies an isolated
  deployment-owned temp catalog.
- Session event rows were not lost. The DB-backed mirror intentionally derives
  its private workspace from the SQLite location. The corrected fixture proves
  the exact path and one-open/idempotent behavior.
- The three Chat rows remain open. They are the only intentionally deferred
  baseline failures and keep Chat hidden or explicitly incomplete in B1.

## Maintenance verification

After the narrow test repairs, the focused maintenance set passed:

```text
4 passed
```

The complete backend rerun then passed every repaired contract and left only
the three documented Chat failures:

```text
3858 passed, 3 failed, 8 skipped, 10 warnings
```

No new failure was introduced by the maintenance diff. The three remaining
failures are accepted as deferred Chat authorization/fixture debt and do not
authorize claiming Chat as complete.

## Phase 0B web baseline

All unchanged web checks passed under the explicit Node 22 runtime:

| Command | Result |
|---|---|
| `npm run test:node` | exit 0; 416 tests, 416 passed, 0 failed |
| `npm run lint` | exit 0; 0 errors, 185 existing warnings |
| `npx tsc --noEmit` | exit 0 |
| `npm run build` | exit 0; Next 16.2.3, static pages 60/60 |

Warnings were existing lint/Browserslist warnings; no web source or lockfile
change was made to obtain the green result.

## B1 start gate

The UI start gate requires all of the following to be green or accepted as
explicitly deferred:

- Course ownership and isolation;
- Course list/read API;
- Course/term identity;
- private-workspace credential boundary;
- web tests;
- lint;
- TypeScript/typecheck;
- production build.

The three unrelated/deferred Chat authorization fixtures do not block the
Course Hub surfaces, but they do block claiming Chat as complete. The full
backend rerun is complete with only those three failures. Course title and
owner identity are persisted by the current Course aggregate; term-qualified
identity is available from the existing BlueWay map contract where present and
is explicitly null for standalone Courses until a term is linked. The B1 UI
must render that null state rather than infer a term.

## Phase 1 boundary record

BlueWay owns academic-life context and Course entry. TEEECHR web owns Classes
Home, Course Overview, Materials, Practice, Review, and conditionally Chat;
Progress and Study Sessions are later surfaces. The superseded BlueWay-hosted
Course workspace plan is recorded in
`docs/47_BLUEWAY_TEEECHR_PRODUCT_BOUNDARY_CORRECTION.md`.

## Phase 2 audit contract

Before UI implementation, publish exact current references for:

- framework and route tree;
- authenticated landing route;
- Course list API/components;
- Course detail API/components;
- Course Chat;
- Practice and Attempts;
- Flashcards;
- Course Sources;
- General Study;
- current navigation;
- tests and fixtures.

Each item must be classified `REUSE`, `EXTEND`, `WRAP`, `REPLACE`, or `PARK`.
The audit must name real files, routes, schemas, APIs, and tests; it must not
describe a hypothetical app.

## Phase 2 current web audit (pre-implementation snapshot)

Audit basis: the clean base checkout plus the read-only source inventory on
2026-08-07. No product files were changed while this audit was prepared. The
Phase 3 section below records the implementation that followed this audit.

### Framework and route tree

The web client is a Next.js App Router application (Next 16.2.3) under
`web/app`, with route groups for auth, workspace, utility, and admin surfaces.
The relevant current tree is:

```text
web/app/
├── (auth)/login/page.tsx
├── (auth)/register/page.tsx
├── (workspace)/page.tsx                         # root -> /home redirect
├── (workspace)/home/[[...sessionId]]/page.tsx   # chat and optional session
├── (workspace)/practice/page.tsx
├── (workspace)/flashcards/page.tsx
├── (utility)/knowledge/page.tsx
├── (utility)/space/learning/page.tsx            # Mastery Path / Course learning
├── (utility)/space/page.tsx
├── (utility)/space/chat-history/page.tsx
└── (admin)/admin/users/page.tsx
```

`web/app/(workspace)/layout.tsx` composes `CapabilityAccessProvider`,
`UnifiedChatProvider`, `AppShell`, `WorkspaceSidebar`, and `CapabilityGate`.
`web/components/layout/AppShell.tsx` owns the responsive shell and drawer.
`web/components/sidebar/WorkspaceSidebar.tsx` currently owns chat-history
navigation and account links; it does not yet provide a Classes-first Course
navigation section.

Classification: `REUSE` the route-group and shell structure; `EXTEND` the
workspace context/provider boundary; `REPLACE` only the `/home` landing
decision so `/home` can become Classes Home while an explicit session route
continues to host Chat. The existing optional catch-all must not be allowed to
silently make Chat the authenticated landing page.

### Authenticated landing route

`web/app/(workspace)/page.tsx` redirects `/` to `/home`, preserving
`?session=...`, `capability`, and repeated `tool` parameters. The actual
`/home` implementation is currently the optional-catch-all chat page at
`web/app/(workspace)/home/[[...sessionId]]/page.tsx`. Auth is enforced through
the workspace `CapabilityGate` and the runtime auth transport in
`web/lib/auth.ts` (`/api/v1/auth/status`, login, register, logout).

Classification: `REPLACE` the no-session `/home` landing view with Classes
Home; `REUSE` the auth status and existing session leaf behavior. The B1 route
split must preserve direct `/home/<sessionId>` reopening for Chat.

### Course list/read API and current consumer

Frontend transport and state:

- `web/lib/course-api.ts` — `listCourses()` calls `GET /api/v1/courses`;
  `createCourse()` calls `POST /api/v1/courses`; `getCourseCapabilities()`
  reads the same authenticated response; source, learning, and lifecycle
  transports are also defined here.
- `web/context/CourseContext.tsx` — resolves authenticated identity, loads the
  owner-scoped list, validates the per-user local selection key, rejects stale
  selections, and exposes create/archive/restore/select operations.
- `web/lib/course-selection.ts` — identity-namespaced selection persistence and
  session/course binding rules.
- `web/components/courses/CourseBar.tsx` — current compact course selector and
  create/general-study actions, reused by Chat, Practice, Flashcards, and
  Course Learning.

Backend authority:

- `deeptutor/api/routers/courses.py` — authenticated `POST /api/v1/courses`,
  `GET /api/v1/courses`, `POST /api/v1/courses/general-study`,
  `GET /api/v1/courses/{course_id}`, title update, archive, and restore;
  practice, flashcard, learning, learner-action, and source routes are all
  nested under the same owner-checked router.
- `deeptutor/courses/service.py` — current-scope service construction and
  owner-private route boundary.
- `deeptutor/courses/repository.py` — per-user SQLite Course aggregate,
  owner-filtered list/read/write queries, revision and write-epoch authority.
- `deeptutor/courses/models.py` — Course persistence remains `id`,
  `owner_user_id`, `title`, `workspace_kind`, `state`, `revision`,
  `write_epoch`, `managed_kb_ref`, timestamps, and `archived_at`; the B1
  response model now also carries an optional `term` projection.
- `deeptutor/courses/migrations/sql/0012_blueway_term_qualified_maps.sql` —
  provider map/record term qualification; it does not currently add a
  learner-facing persistent `term` field to `courses`.

Classification: `REUSE` the API, repository, owner filter, revision, and
selection context; `EXTEND` the Course identity contract with an explicit
term projection from the existing qualified map. Do not infer term from title,
BlueWay text, or a fabricated client field.

Current backend contract tests include:
`tests/courses/test_api.py`, `tests/courses/test_repository.py`,
`tests/courses/test_learner_actions.py`, `tests/courses/test_turn_contract.py`,
`tests/multi_user/test_resource_isolation.py`, and
`tests/api/test_course_sessions_api.py`. Frontend transport and identity tests
include `web/tests/course-api.test.ts`,
`web/tests/course-actions.test.ts`, `web/tests/course-selection.test.ts`, and
`web/tests/unified-ws-course-identity.test.ts`.

### Course detail / Overview

There is no current dedicated Course detail route or Course Overview component.
The closest current detail reads are `getCourse()` in
`web/lib/course-api.ts`, active-course presentation in
`web/components/courses/CourseBar.tsx`, and the Course-aware portions of
`web/components/practice/PracticeWorkspace.tsx`,
`web/components/flashcards/FlashcardsWorkspace.tsx`, and
`web/app/(utility)/space/learning/page.tsx`.

Classification: `REPLACE` for the missing route/component with a thin
owner-private Course Overview; `REUSE` the existing read API and `Course`
identity; `WRAP` existing working destinations rather than duplicating their
state machines. Until the term field exists, the term card must be a truthful
null state rather than a guessed value.

### Course Chat

Course Chat is not a separate route today. It is the existing
`web/app/(workspace)/home/[[...sessionId]]/page.tsx` Chat implementation with
`CourseContext`, `CourseBar`, `courseIdForChatSession`,
`resolveSessionCourseView`, and `web/lib/unified-ws.ts` carrying `course_id`.
The backend contract is in `deeptutor/api/routers/chat.py`,
`deeptutor/services/session/turn_runtime.py`, and the Course turn tests.

Classification: `WRAP` the existing session leaf and Course identity seam;
`PARK` a new standalone Chat route until the three deferred authorization
fixtures are repaired. Chat must not be presented as complete in B1.

### Practice and Attempts

`web/app/(workspace)/practice/page.tsx` renders
`web/components/practice/PracticeWorkspace.tsx`. It already uses
`useCourses()`, `web/lib/practice-api.ts`, `listCourseSources()`, revision and
write-epoch checks, practice generation plans, Attempts, autosave, submit,
grade, results, and remediation-to-Flashcards handoff.

The backend contract is nested in `deeptutor/api/routers/courses.py` and
implemented by `deeptutor/courses/practice_repository.py`,
`deeptutor/courses/attempt_repository.py`, and corresponding services. Tests
are in `tests/courses/practice/test_api.py`,
`tests/courses/practice/test_attempt_contract.py`,
`tests/courses/practice/test_generation_api.py`, and the broader practice
contract suites.

Classification: `REUSE` the route, component, API, and Attempt state machine;
`EXTEND` only the Course Hub links and null-state entry point. Do not rebuild
Practice inside B1.

### Flashcards / Review

`web/app/(workspace)/flashcards/page.tsx` renders
`web/components/flashcards/FlashcardsWorkspace.tsx`, using
`web/lib/flashcards-api.ts`, the Course context, source receipts, generation
briefs, deck lifecycle, due-card review, and review persistence. The backend
routes are the `/{course_id}/flashcards` family in
`deeptutor/api/routers/courses.py`; contracts live under
`deeptutor/courses/flashcard_*` and `tests/courses/practice/test_flashcard_contract.py`.

Classification: `REUSE` the existing Flashcards/Review destination and
identity; `EXTEND` the Hub link and empty state. Review is the working
Flashcards review surface, not a new Progress redesign.

### Course Sources / Materials

Course sources are already represented by `CourseSource` in
`web/lib/course-api.ts`, with list, upload, archive, progress, and source detail
transport. `PracticeWorkspace` consumes `listCourseSources()` for source
selection. The backend source routes are
`GET/POST /api/v1/courses/{course_id}/sources` and source detail/progress/archive
routes in `deeptutor/api/routers/courses.py`; persistence and ingestion live in
`deeptutor/courses/repository.py` and `deeptutor/courses/ingestion.py`.

The general `/knowledge` route (`web/app/(utility)/knowledge/page.tsx`,
`web/components/knowledge/KnowledgePage.tsx`, and
`web/lib/knowledge-api.ts`) manages general knowledge bases, not the private
Course source list. It must not be relabeled as Course Materials without an
explicit ownership bridge.

Classification: `WRAP` existing Course source API/repository; `EXTEND` a Course
Materials view in the Course Overview; `PARK` general Knowledge as a separate
utility surface.

### General Study

`web/app/(utility)/space/learning/page.tsx` branches on `activeCourse`: it
renders the existing general Mastery Path when there is no selected Course and
the Course learning path when there is one. The Course API exposes
`/api/v1/courses/{course_id}/learning` plus init/reset; the general learning
transport is `web/lib/learning-api.ts`.

Classification: `REUSE` the existing destination when explicitly opened;
`WRAP` it from Course actions only where a real Course learning contract
exists; `PARK` any new Progress redesign and recommendations from B1.

### Current navigation

`web/components/sidebar/WorkspaceSidebar.tsx` currently exposes new Chat,
session history, profile/admin, and logout through
`web/components/sidebar/SidebarShell.tsx`. It does not expose Classes Home,
Course Overview, Materials, Practice, Review, or a Course-scoped Chat section.
The current `CourseBar` is an in-content selector, not primary navigation.

Classification: `EXTEND` the sidebar with a Classes-first entry and real
Course destinations after the route split; `WRAP` existing session history and
account links; `PARK` Chat as a complete primary destination until its auth
baseline is green.

### Tests, fixtures, and proof level

- Backend ownership/list/read: `tests/courses/test_api.py`,
  `tests/courses/test_repository.py`, `tests/multi_user/test_resource_isolation.py`.
- Course session binding: `tests/api/test_course_sessions_api.py`,
  `tests/courses/test_turn_contract.py`,
  `tests/integrations/blueway/test_phase3a_transcript_chat_runtime.py`.
- Web Course transport/identity: `web/tests/course-api.test.ts`,
  `web/tests/course-actions.test.ts`, `web/tests/course-selection.test.ts`,
  `web/tests/unified-ws-course-identity.test.ts`.
- Existing authenticated/browser-facing web scenarios:
  `web/tests/e2e/phase4-authenticated.spec.ts` and
  `web/tests/e2e/phase5-flashcards-ux.spec.ts`.
- Node web baseline: 416/416 tests passed.

These are source/test references. They are not hosted, physical-device,
TestFlight, or release proof.

## Commit separation

Maintenance commits must remain separate from B1 product work. The expected
maintenance scope is:

- migration expectation updates;
- credential/runtime/session test-isolation repairs;
- this accepted ledger and boundary documentation.

The later B1 product commit must contain only Classes Home/Course Hub behavior
and its tests. No BlueWay changes, migration SQL, hosted configuration, or
production secrets belong in either commit.

## Phase 3 B1 implementation

The audited route split is implemented only in this B1 checkout:

| Surface | Route | Implementation | Classification/result |
|---|---|---|---|
| Classes Home | `/classes` and no-session `/` redirect | `web/app/(workspace)/classes/page.tsx`, `web/components/courses/ClassesHome.tsx`, `web/app/(workspace)/page.tsx` | `REPLACE` the no-session Chat landing with an owner-scoped Classes list; direct `/home/<sessionId>` remains Chat |
| Course Overview | `/classes/[courseId]` | `web/app/(workspace)/classes/[courseId]/page.tsx`, `web/components/courses/CourseOverview.tsx`, `web/lib/course-api.ts:getCourse` | `WRAP` the existing owner-checked detail API and link only to real B1 destinations |
| Materials | `/classes/[courseId]/materials` | `web/app/(workspace)/classes/[courseId]/materials/page.tsx`, `web/components/courses/CourseMaterials.tsx` | `WRAP` `listCourseSources`, `attachCourseSource`, and `archiveCourseSource`; processing/ready/failed/archived states are shown truthfully |
| Practice | `/practice` | existing `web/components/practice/PracticeWorkspace.tsx` | `REUSE`; Course Overview selects the Course before navigation |
| Review | `/flashcards` | existing `web/components/flashcards/FlashcardsWorkspace.tsx` | `REUSE`; no new Progress surface is claimed |
| Chat | `/home` and `/home/[sessionId]` | existing `web/app/(workspace)/home/[[...sessionId]]/page.tsx` | `PARK` as complete; Course Overview displays an explicit unavailable state while the three Chat authorization fixtures remain red |

Navigation is Classes-first in
`web/components/sidebar/SidebarShell.tsx`; Chat remains a distinct nav item
that opens a fresh `/home` session. General Study remains the existing
`/space/learning` destination and is linked as a separate non-Course utility.

### B1 identity and privacy contract

`deeptutor/courses/repository.py` now projects `Course.term` from
`blueway_course_maps.external_term_id` only when exactly one non-null term is
associated with the Course. Legacy databases without migration 0012 return a
null projection, and conflicting mappings also return null. The repository
never derives term from a title. `tests/courses/test_repository.py` covers the
no-map, one-map, and conflicting-map states; `web/tests/course-api.test.ts`
covers the nullable owner-scoped detail response.

### Post-implementation validation

The Node22 web validation after the B1 route work is:

| Command | Result |
|---|---|
| `npm run test:node` | exit 0; 417 tests, 417 passed, 0 failed |
| `npm run lint` | exit 0; 0 errors, 229 warnings (the prior 185 plus literal-text warnings in the new UI) |
| `npx tsc --noEmit` | exit 0 |
| `npm run build` | exit 0; Next 16.2.3, new `/classes`, `/classes/[courseId]`, and `/classes/[courseId]/materials` routes generated |

The backend compatibility validation for the new Course projection passed the
repository and legacy-upgrade focused set: `26 passed`. The final full backend
rerun after the UI and term projection work is `3859 passed, 3 failed, 8
skipped, 10 warnings`. The three failures are the deferred Chat nodes listed
above; no Course or B1 route failure was added.

## Remaining proof boundaries

Not claimed by this packet:

- hosted Supabase Edge;
- hosted TEEECHR runtime;
- physical iPhone;
- TestFlight;
- production secrets or key rotation;
- VoiceOver or Dynamic Type certification;
- migration-zero bootstrap on a fresh deployment;
- release, rollback, monitoring, and recovery readiness.
