# TEEECHR v1.5.2 Phase 3A and Phase 4 — Close BlueWay, Restore Learning Workflows

Status: **Phase 3A remains open.** The original roadmap below remains the Phase 4
planning authority, but its pre-closeout branch/commit statements are superseded by
the 2026-07-27 receipt below.

### 2026-07-27 Phase 3A closeout-repair receipt

- TEEECHR authority is
  `/Users/home/Desktop/2k26/teeech/DeepTutor-v1.5.2-baseline` on
  `feature/teeechr-v152-phase3a-closeout`. The reviewed source/test repair tip is
  `624f4a6a` (three local commits); this documentation receipt follows it. The
  branch is not pushed or a Phase 3A completion claim.
- Canonical BlueWay authority is `/Users/home/Developer/BlueWay-local`, `main` at
  `1752e5f`, one local commit ahead of `origin/main`. Its user-owned dirty worktree
  is preserved and read-only for this lane. The isolated Phase 3A proof worktree is
  `/Users/home/Desktop/2k26/teeech/BlueWay-phase3a-transcript-proof` on
  `feature/teeechr-phase3a-transcript-proof` at `1752e5f`; this receipt makes no
  claim about its current cleanliness.
- The historical-fork safety branch remains preserved. Upstream v1.5.5 integration
  remains deferred; no push, merge, deployment, hosted mutation, or paid/provider
  call is authorized by this closeout lane.
- Local source/validation receipt: backend `2861 passed, 6 skipped, 9 warnings`;
  focused repaired suite `119 passed`; web node suite `168 passed`; `tsc` passed;
  Next production build emitted `52` routes; lint reported `0` errors and `101`
  warnings; i18n parity passed (audit findings informational); Ruff and
  `git diff --check` passed; independent review found no P0-P2 issue.
- The repair set adds per-round tool-schema authority with atomic rejection of an
  unauthorized tool batch; Course mastery suppresses build/assess and requires a
  private, real `ask_user` reply receipt; no-speech transcript omission; a
  production-shaped, provider-free import-to-Course-Chat passive-content proof; and
  auth-setting test isolation.
- Still open: a current non-empty real BlueWay export/sync into the exact private
  `CourseSource` with citation receipt, two-account browser isolation, disposable
  revoke/reconnect, and confirmed fixture cleanup. These gates prevent Phase 3A
  completion.

Last updated: 2026-07-27

## 1. Goal and non-goals

### Goal

Finish the current v1.5.2-based private Course and BlueWay foundation, then
restore the useful historical Practice, quiz, Flashcards, progress, remediation,
and learner-action workflows as general college-course features.

The authenticated TEEECHR user remains the ownership root. Every learning
artifact must resolve through one private Course and retain exact source
provenance. BlueWay supplies read-only academic context through explicit
external mappings; it does not become TEEECHR storage or identity authority.

### Non-goals

- Do not integrate upstream DeepTutor v1.5.5 in this plan.
- Do not merge or rebase the historical TEEECHR fork into the current branch.
- Do not delete, rewrite, or force-update the historical fork `main`.
- Do not restore tester-cookie ownership, tester-prefixed Knowledge Bases,
  NCE-only domain assumptions, the historical question coordinator, compatibility
  stubs, or incomplete frontend deletions.
- Do not make BlueWay mandatory for Course, Practice, quiz, Flashcards, mastery,
  or remediation.
- Do not migrate historical learner attempts or decks in the first implementation
  slice. Historical data import requires a separate dry-run migration contract.
- Do not add sharing, multi-server coordination, BlueWay write-back, raw-audio
  import, hard deletion, production deployment, or production data migration.
- Do not run paid provider calls, mutate hosted data, deploy, or publish a release
  without a separate action-time approval.

## 2. Preservation and branch contract

Three histories remain distinct:

| History | Current authority | Purpose | Rule |
| --- | --- | --- | --- |
| Historical product fork | `/Users/home/Desktop/2k26/teeech/DeepTutor`, `safety/teeechr-pre-v152-20260720` at `3c2d5a47` | Behavioral and UX reference for Practice, quizzes, Flashcards, access onboarding, and learner actions | Preserve; inspect and selectively reimplement behavior; never merge wholesale |
| Current Course/BlueWay product | `/Users/home/Desktop/2k26/teeech/DeepTutor-v1.5.2-baseline`, `feature/teeechr-v152-phase3a-closeout`; reviewed source/test tip `624f4a6a`, followed by this documentation receipt | Active implementation authority for Phase 3A; Phase 4 remains planned | Validate and close only the listed open gates; do not treat the local branch as a published completion |
| Moving upstream | `HKUDS/DeepTutor` `main`, observed at v1.5.5 commit `47d05809` on 2026-07-27 | Future compatibility source | Monitor only; no integration in this plan |

Before Phase 4 implementation, preserve the historical fork `main` with an
explicit archival branch or tag. Do not move any `main` pointer while implementing
or validating Phase 3A or Phase 4.

## 3. Contract stub

### Inputs

- One authenticated TEEECHR user.
- One active private Course.
- Zero or more ready CourseSources, including uploads or BlueWay imports.
- Explicit learning objectives/modules when available.
- A learner action: Chat, create Practice, begin/resume quiz, create/review
  Flashcards, inspect progress, or review weak topics.

### Outputs

- Source-grounded Practice sets and quiz questions.
- Durable, resumable, graded quiz attempts.
- Durable manual or source-grounded Flashcard decks and review events.
- Course-scoped mastery, error, review-queue, and remediation state.
- Resolvable citations from generated learning assets back to immutable
  CourseSource revisions and fingerprints.

### Success

One authenticated learner can:

1. create two private Courses;
2. attach or sync distinct material into each Course;
3. use grounded Chat;
4. create, complete, reload, and review a quiz;
5. create and study a persistent Flashcard deck;
6. inspect weak objectives and launch remediation;
7. restart TEEECHR without losing state; and
8. receive `404` for every foreign Course, assessment, attempt, deck, card,
   review, progress, or source identifier.

## 4. Locked product decisions

- Practice is the learner workspace; a Quiz is one graded activity inside it.
- Phase 4 restores behavior, not the historical implementation architecture.
- Quiz grading is authoritative evidence for quantitative mastery.
- Flashcard ratings schedule future review but do not directly claim mastery.
- Manual Practice and Flashcard creation works without a model assignment.
- Generated Practice and Flashcards require server-resolved Course sources and
  explicit provider authority.
- Course titles, source names, topics, and external BlueWay titles are never
  ownership keys.
- Existing Course archive/restore rules apply to learning artifacts.
- No permanent deletion endpoint is added.
- Historical attempt/deck migration is deferred to a separate dry-run plan.

## 5. Data and ownership contract

All records live inside the authenticated owner's private Course database or a
strict personal path derived from that owner. API callers never supply
`owner_user_id`.

### PracticeSet

```text
PracticeSet
  id: prc_<opaque UUID>
  owner_user_id
  course_id
  title
  mode: manual | generated
  state: draft | ready | archived
  source_snapshot_json
  objective_ids_json
  generation_receipt_json?
  revision
  write_epoch
  created_at
  updated_at
  archived_at?
```

`source_snapshot_json` contains only server-resolved source IDs, revisions, and
fingerprints. Display names and prompt text are not authority.

### PracticeQuestion

```text
PracticeQuestion
  id: qst_<opaque UUID>
  practice_set_id
  question_type
  prompt
  answer_contract_json
  explanation
  objective_ids_json
  citation_json
  ordinal
  revision
  created_at
```

Questions become immutable when their PracticeSet becomes ready. Corrected or
regenerated sets create successors; they do not rewrite completed attempts.

### QuizAttempt and QuizAttemptItem

```text
QuizAttempt
  id: att_<opaque UUID>
  owner_user_id
  course_id
  practice_set_id
  state: in_progress | submitted | graded | abandoned | archived
  practice_set_revision
  source_snapshot_json
  score_json?
  revision
  started_at
  submitted_at?
  graded_at?
  updated_at
```

```text
QuizAttemptItem
  id: ati_<opaque UUID>
  attempt_id
  question_id
  response_json?
  grading_json?
  error_type?
  objective_ids_json
  citation_json
  revision
  answered_at?
  graded_at?
```

An attempt binds permanently to one Course, PracticeSet revision, question set,
and source snapshot. It cannot be moved to another Course or silently upgraded
to a newer generated set.

### FlashcardDeck, Flashcard, and FlashcardReview

```text
FlashcardDeck
  id: dck_<opaque UUID>
  owner_user_id
  course_id
  title
  mode: manual | generated
  state: draft | ready | archived
  source_snapshot_json
  generation_receipt_json?
  revision
  write_epoch
  created_at
  updated_at
  archived_at?
```

```text
Flashcard
  id: crd_<opaque UUID>
  deck_id
  prompt
  answer
  objective_ids_json
  citation_json
  ordinal
  revision
  created_at
  updated_at
```

```text
FlashcardReview
  id: rvw_<opaque UUID>
  owner_user_id
  course_id
  deck_id
  card_id
  rating: again | hard | good | easy
  deck_revision
  reviewed_at
  next_review_at
```

Ready generated cards are immutable. Manual cards use optimistic revisions.
Review events are append-only and cannot be reassigned.

### Learning and mastery linkage

The existing deterministic Course learning identity remains
`lp_<course_id>`. Phase 4 reuses:

- `deeptutor.learning.models.QuizAttempt`
- `deeptutor.learning.models.ErrorRecord`
- `deeptutor.learning.models.ReviewTask`
- `deeptutor.learning.models.LearningProgress`
- `deeptutor.learning.service.LearningService.grade_and_record`
- `deeptutor.learning.mastery.compute_mastery`
- `deeptutor.learning.scheduler.ReviewScheduler`

The new assessment repository owns durable product attempts. After a valid
graded item commit, an idempotent mastery adapter records the corresponding
learning attempt under `lp_<course_id>`. Replaying the same graded item must not
double-count mastery.

## 6. Source and generation contract

### Manual mode

Manual Practice sets, questions, decks, and cards require no provider call.
They may optionally reference active Course sources selected through
server-resolved IDs.

### Generated mode

Generated assets:

1. resolve the authenticated user and active Course;
2. resolve only active ready CourseSources owned by that Course;
3. capture source IDs, revisions, and fingerprints;
4. build bounded retrieval context server-side;
5. treat retrieved text as untrusted learning content, never instructions;
6. request structured output under explicit item/text/time limits;
7. validate every question/card and citation;
8. stage the complete asset;
9. revalidate user, Course state, source revisions, and write epoch; and
10. publish atomically or leave a terminal safe failure.

No client-supplied KB name, source title, filename, BlueWay title, transcript
instruction, URL, tool name, or prompt fragment can grant retrieval or tool
authority.

### Source lifecycle

- Archiving a source prevents new generation from using it.
- Existing attempts and reviews retain the frozen source receipt.
- A generated asset whose source is later archived remains historical but is
  visibly marked as based on unavailable material.
- Regeneration from current material creates a successor PracticeSet or deck.
- Transcript tombstones remove the source from active generation and retrieval
  while preserving archived provenance.

## 7. Historical behavior alignment matrix

| Concern | Historical reference | Current foundation | Phase 4 intent | Acceptance check |
| --- | --- | --- | --- | --- |
| Practice workspace | `web/components/practice/PracticeWorkspace.tsx:PracticeWorkspace` | Course picker and Course-aware Chat in `web/context/CourseContext.tsx` | Rebuild Practice as a Course route with saved sets and attempts | Two same-titled Courses never share sets or attempts |
| Attempt APIs | `deeptutor/api/routers/practice.py:create_attempt`, `save_attempt_results`, `get_progress` | `CourseRepository`, `CourseService`, authenticated Course APIs | Add owner-derived Course assessment APIs | Foreign attempt IDs return the same `404` as missing IDs |
| Quiz persistence | Historical Practice SQLite behavior | `courses.db`, optimistic revisions, Course write epochs | Store immutable question sets and resumable attempts in the personal Course DB | In-progress and graded attempts survive restart |
| Flashcards | `deeptutor/api/routers/flashcards.py:generate_flashcard_deck`, `review_flashcard`, `complete_flashcard_pass` | CourseSource provenance and deterministic ingestion | Add Course-owned decks, cards, review events, and missed-card loops | Deck/reviews survive reload and remain Course-isolated |
| Flashcard service | `deeptutor/services/flashcards/service.py:FlashcardService` | No persistent Course Flashcard product yet | Reuse scheduling behavior only after contract review; do not port tester ownership | Ratings produce deterministic next-review state without changing mastery directly |
| Mastery | Historical domain progress | `LearningService.grade_and_record`, `LearningProgress`, `ReviewTask` | Map graded items to Course objectives under `lp_<course_id>` | Replay does not double-count; weak objectives match committed attempts |
| Learner actions | Historical `ChatMessages.tsx` action chips | Current Course Chat and unified WebSocket | Restore `Quiz me`, `Explain simpler`, `Flashcards`, and `Review weak topics` with Course identity | Each action reaches the expected owned Course workflow |
| Grounding | Historical Knowledge/topic starter distinction | Server-derived Course source authority | Manual assets may be ungrounded and labeled; generated grounded assets require citations | Every grounded question/card has resolvable source lineage |
| Access code | `deeptutor/api/routers/access.py:claim_access`, `AccessManager` | v1.5.2 authenticated users and role checks | Defer optional invitation/onboarding; never use access cookie as ownership | Claim results in a normal authenticated account before resource access |
| NCE behavior | Historical domain normalization and prompts | General Course objectives/modules | Keep NCE only as an optional template | Biology and Calculus use the same ownership and persistence contracts |

## 7A. Phase 4 code-seam decisions

The 2026-07-27 read-only current/historical implementation audit adds these
constraints before P4-01 may begin. They refine the task breakdown; they do not
authorize Phase 4 implementation while Phase 3A remains open.

### Course database evolution

- `courses.db` currently has no schema-version ledger. Its existing
  `CREATE TABLE IF NOT EXISTS` statements and one ad hoc column repair are not
  sufficient provenance for six assessment/Flashcard tables.
- P4-01 must first add a transactional, idempotent Course-schema migration
  ledger. Existing databases may adopt the baseline only after the runner verifies
  the expected Course/source tables, columns, indexes, ownership fields, and
  foreign-key behavior. Partial or unknown shapes fail closed rather than being
  silently relabeled.
- Each migration records an immutable version/name/checksum receipt and runs under
  the repository write lock with foreign keys enabled. Fresh-database replay and
  upgrade replay from the Phase 3A schema must converge to the same effective
  definitions.
- Assessment tables live in the same per-user `courses.db`. They must reuse the
  same connection and write-lock authority as `CourseRepository`; do not create a
  second per-file repository with an independent lock or a caller-supplied owner.

### Repository, API, and derived learning evidence

- Put assessment operations behind a bounded `CourseAssessmentRepository` /
  `CourseAssessmentService` seam composed from the authenticated Course repository.
  API callers never provide `owner_user_id`, filesystem paths, KB names, or display
  titles as authority.
- Add a dedicated Course Practice/Flashcard router surface that reuses the existing
  non-enumerating `404`, optimistic `409`, archive fence, and
  `course_operation_lock` behavior. Do not overload source-ingestion operations or
  generic `/api/v1/learning` deletion routes.
- The new assessment tables are authoritative for Practice sets, immutable
  questions, attempts/items, decks/cards, and reviews. `LearningProgress` under
  `lp_<course_id>` receives only idempotent derived grading/mastery/error/review
  evidence; it is not a second product-attempt store.
- `LearningService.grade_and_record`, deterministic grading, mastery computation,
  and the review scheduler are reusable. The adapter idempotency key is the
  immutable assessment attempt-item identity. Flashcard ratings never call the
  mastery adapter directly.

### Frontend and historical behavior boundary

- Add a Course-owned Practice workspace and Flashcard workflow using
  `CourseContext`, `course-api.ts`, and the active immutable user/Course identity.
  Do not turn the existing Book quiz/Flashcard blocks or generic Learning page into
  the persistence authority.
- Preserve the historical user behaviors: create/resume/review quiz attempts,
  wrong-answer remediation, source-trust badges, persistent Flashcard study,
  missed-card loops, and learner action chips.
- Reimplement rather than port the historical storage and authority: tester-cookie
  ownership, tester-prefixed IDs/KB names, destructive result replacement/reset,
  repeat-submit semantics, client/model grading authority, NCE-only prompts,
  uncited topic generation, and model-written coaching state are rejected.
- The first implementation slice remains manual Practice and manual Flashcards.
  Provider-backed generation, model session analysis, historical-data import, and
  upstream reconciliation stay behind their separate gates.

## 8. Phase 3A task breakdown

### P3A-01 — Reconcile Phase 3 truth

- **Scope:** Phase 3 plan, migration handoff, changelog, Future Due, current
  BlueWay proof references.
- **Inputs / outputs:** one evidence matrix classifying each old unchecked item
  as `proved`, `partially proved`, `open`, or `deferred`.
- **Acceptance criteria:**
  - stale task-level boxes no longer contradict the later proof ledger;
  - the receipt records the current BlueWay and TEEECHR authorities rather than
    historical branch-publication snapshots;
  - upstream integration is explicitly out of scope;
  - no runtime or deployment claim exceeds its evidence.
- **Doc alignment:** `docs/TEEECHR_V152_PHASE3_BLUEWAY_INTEGRATION_PLAN.md`.
- **Risk / unknown:** July 22 receipts predate the final BlueWay consolidation.
  Resolve by checking current Git identities and current proof documents.

### P3A-02 — Revalidate the exact TEEECHR branch

- **Scope:** tests and builds only; no feature edits.
- **Inputs / outputs:** exact command receipt for the current branch.
- **Acceptance criteria:**
  - full Python suite passes or every unrelated failure is classified;
  - changed Python files pass Ruff;
  - web tests, TypeScript, and production build pass;
  - repository diff, tracked, untracked, and ignored states are reviewed;
  - no paid provider call occurs.
- **Doc alignment:** Phase 3 verification plan.
- **Risk / unknown:** dependency or upstream service drift since 2026-07-22.

**2026-07-27 receipt:** local backend, focused repair, web, TypeScript, build,
lint, i18n, Ruff, and diff checks passed as recorded above. This completes neither
the real transcript/citation gate nor browser/revoke/fixture gates.

### P3A-03 — Prove a real transcript reaches private Course Knowledge

- **Scope:** one approved BlueWay beta account, one completed transcript, one
  private TEEECHR profile and Course.
- **Inputs / outputs:** bounded export/sync receipt, resulting CourseSource,
  source fingerprint, and one citation lookup.
- **Acceptance criteria:**
  - zero-segment/no-speech transcripts are omitted without failing the snapshot;
  - one non-empty completed transcript maps to the exact Course;
  - raw audio, provider IDs, paths, and excluded metadata do not cross the boundary;
  - the source survives restart and is searchable only by its owner/Course;
  - no transcript text is copied into logs or proof documents.
- **Doc alignment:** Phase 3 transcript contract and BlueWay academic export fixture.
- **Risk / unknown:** the currently connected account may not own an eligible
  non-empty transcript. Use a disposable approved witness if necessary.

### P3A-04 — Prove transcript prompt text remains passive

- **Scope:** deterministic local Course Chat/RAG runtime; no external tools or paid calls.
- **Inputs / outputs:** malicious-looking transcript fixture and turn/tool event receipt.
- **Acceptance criteria:**
  - transcript instructions cannot mount or invoke tools;
  - retrieval stays within the exact Course source set;
  - foreign KB/source/session IDs return non-enumerating denial;
  - logs contain no transcript content;
  - the response may discuss the text but cannot treat it as authority.
- **Doc alignment:** `deeptutor/services/session/turn_runtime.py` and
  `deeptutor/multi_user/knowledge_access.py`.
- **Residual boundary:** the provider-free production-shaped import-to-Chat proof
  below closes the local tool/passive-content contract. It does not prove the
  separate current real BlueWay transfer and citation gate in P3A-03.

**2026-07-27 repair proof:** production-shaped provider-free import-to-Course-Chat
coverage satisfies this local passive-content/tool-authority gate: malicious-looking
imported text remains passive and cannot obtain tool authority. It is not the
required current real BlueWay transcript-to-CourseSource/citation receipt in P3A-03.

### P3A-05 — Complete current two-user browser isolation

- **Scope:** two disposable TEEECHR users and two separate BlueWay accounts.
- **Inputs / outputs:** browser/API receipt with two same-titled Courses.
- **Acceptance criteria:**
  - each account sees only its own connection, Courses, sources, and progress;
  - logout/login and A-to-B account changes clear stale state;
  - crossed Course/source/session/sync identifiers return `404`;
  - no user needs access to another user's credential or opaque external IDs.
- **Doc alignment:** Phase 3 P3-11 and Course ownership tests.
- **Risk / unknown:** existing hosted two-owner proof used API/runtime surfaces;
  this task closes the current browser flow.

### P3A-06 — Prove disposable disconnect/reconnect and retire fixtures

- **Scope:** disposable proof accounts only; the active beta client and primary
  user connection are not cleanup targets.
- **Inputs / outputs:** revoke/reconnect receipt and reviewed fixture inventory.
- **Acceptance criteria:**
  - disconnect blocks refresh/export immediately;
  - imported Course material remains according to retention copy;
  - reconnect restores the same Course mapping for the same BlueWay subject;
  - only confirmed disposable accounts/grants are disabled or removed;
  - destructive cleanup requires separate approval.
- **Doc alignment:** `BlueWayService.disconnect` and Phase 3 rollback rules.
- **Risk / unknown:** cleanup authority must distinguish active beta users from fixtures.

### P3A-07 — Final Phase 3 closeout

- **Scope:** exact diffs, tests, docs, evidence, branches, and handoff.
- **Inputs / outputs:** closeout receipt and promotion recommendation.
- **Acceptance criteria:**
  - repository closeout backcheck passes;
  - no P0-P2 security/data-lifecycle finding remains;
  - exact unproved surfaces are parked;
  - Phase 3 is labeled source-complete or runtime-complete only to the proven boundary;
  - no merge to `main` or upstream occurs without separate approval.
- **Doc alignment:** `section-closeout-backcheck`.
- **Risk / unknown:** a final proof may reveal a small must-fix source defect.

## 9. Phase 4 task breakdown

### P4-01 — Assessment and Flashcard schema contract

- **Scope:** Course models/repository migrations and model-only tests.
- **Inputs / outputs:** the opaque IDs and tables in Section 5.
- **Acceptance criteria:**
  - foreign keys, checks, indexes, WAL, and optimistic revisions pass;
  - two users and same-titled Courses cannot collide;
  - no hard-delete path exists;
  - schema upgrade is restart-safe and idempotent.
- **Doc alignment:** `CourseRepository._initialize`.
- **Risk / unknown:** keep the schema small enough to avoid duplicating all
  `LearningProgress` state.

### P4-02 — Practice set and attempt repository

- **Scope:** repository/service methods only.
- **Inputs / outputs:** create/list/read/archive sets; start/save/submit/grade attempts.
- **Acceptance criteria:**
  - attempt membership never changes after creation;
  - stale writes return `409`;
  - unknown and foreign IDs return the same `404`;
  - submitted/graded attempts are immutable;
  - restart preserves in-progress answers and graded history.
- **Doc alignment:** historical `practice.py` behavior and current Course repository.
- **Risk / unknown:** autosave must not overwrite newer answers from another tab.

### P4-03 — Deterministic grading and mastery adapter

- **Scope:** grading adapter, idempotency receipt, learning-service integration.
- **Inputs / outputs:** graded items and Course mastery updates.
- **Acceptance criteria:**
  - deterministic question types use deterministic grading;
  - model-assisted grading is explicit, bounded, and separately labeled;
  - each graded attempt item affects mastery at most once;
  - incorrect answers create error/review evidence;
  - Flashcard reviews do not directly change mastery.
- **Doc alignment:** `LearningService.grade_and_record`.
- **Risk / unknown:** qualitative questions require a separate judgment contract.

### P4-04 — Manual Practice API and minimal UI

- **Scope:** Course-owned APIs and `/practice` Course workspace.
- **Inputs / outputs:** manual set creation, attempt runner, autosave, submit,
  results, resume, and history.
- **Acceptance criteria:**
  - works without a configured model;
  - active Course is visible on every page;
  - browser state is user- and Course-namespaced;
  - archive/identity changes make in-flight editors read-only or fail closed;
  - no broad redesign of Chat, Settings, or Course navigation.
- **Doc alignment:** historical `PracticeWorkspace`.
- **Risk / unknown:** retain the useful UX without carrying historical component debt.

### P4-05 — Grounded Practice generation

- **Scope:** bounded generator, validator, background operation, progress API.
- **Inputs / outputs:** immutable generated PracticeSet with citations.
- **Acceptance criteria:**
  - only server-resolved active sources enter retrieval;
  - item/text/context/time limits are enforced;
  - malformed or incomplete generation never becomes ready;
  - archive, logout, revision, or source changes fence the final commit;
  - deterministic fake provider covers automated tests;
  - real provider proof requires separate approval.
- **Doc alignment:** Course source ingestion fences and historical Practice outcomes.
- **Risk / unknown:** question quality requires a later labeled evaluation set;
  contract correctness comes first.

### P4-06 — Flashcard repository and manual workflow

- **Scope:** decks, cards, review events, scheduling policy, API, minimal UI.
- **Inputs / outputs:** persistent manual decks and review sessions.
- **Acceptance criteria:**
  - deck/card/review ownership and Course binding pass;
  - rating produces deterministic next-review state;
  - missed-card loop and completion summary survive reload;
  - archive blocks new reviews while retaining history;
  - manual cards work without a model.
- **Doc alignment:** historical `FlashcardService` and `FlashcardsWorkspace`.
- **Risk / unknown:** port scheduling behavior only after reviewing its time and
  persistence assumptions.

### P4-07 — Grounded Flashcard generation

- **Scope:** generated deck operation and provenance.
- **Inputs / outputs:** immutable ready deck with source citations.
- **Acceptance criteria:**
  - same source snapshot/idempotency key creates no duplicate;
  - changed sources create a successor deck;
  - ungrounded topic starters are explicitly labeled and require user intent;
  - generated cards cannot widen Course/tool authority;
  - failed generation retains a safe terminal receipt.
- **Doc alignment:** historical source-trust badge behavior and current Course sources.
- **Risk / unknown:** do not present generated cards as source-grounded without citations.

### P4-08 — Learner actions and remediation loop

- **Scope:** Chat action chips, Course navigation, weak-objective launch payloads.
- **Inputs / outputs:** `Quiz me`, `Explain simpler`, `Flashcards`, and
  `Review weak topics`.
- **Acceptance criteria:**
  - every action carries an exact Course ID;
  - Practice/Flashcard generation uses the current server-resolved source set;
  - weak-topic Practice derives from committed mastery/errors;
  - action replay cannot cross identity or Course changes.
- **Doc alignment:** historical `ChatMessages.tsx` actions and current Course Chat.
- **Risk / unknown:** avoid encoding large prompts in client navigation state.

### P4-09 — Beta-scale and adversarial proof

- **Scope:** automated ownership, concurrency, persistence, browser, and provider-neutral tests.
- **Inputs / outputs:** exact test/evidence matrix.
- **Acceptance criteria:**
  - 50 profiles remain isolated;
  - at least ten concurrent non-provider assessment/review operations pass;
  - stale revisions, duplicate submissions, replay, archive, logout, and restart pass;
  - malicious sources cannot grant tool/Knowledge authority;
  - two authenticated users complete distinct Course learning loops;
  - no paid provider call occurs during automated validation.
- **Doc alignment:** Phase 2/3 adversarial test patterns.
- **Risk / unknown:** browser and API proof do not imply physical-device or production proof.

### P4-10 — Phase 4 closeout

- **Scope:** tests, diffs, changelog, plan ledger, Future Due, and handoff.
- **Inputs / outputs:** reviewed commits and closeout receipt.
- **Acceptance criteria:**
  - full affected Python/web suites and production build pass;
  - repository closeout backcheck passes;
  - no tracked DB, credential, transcript, generated output, or personal data exists;
  - historical data migration and upstream integration remain separately parked;
  - commit/push/merge decisions are explicit.
- **Doc alignment:** repository `AGENTS.md`.
- **Risk / unknown:** do not turn closeout into upstream integration.

## 10. API surface proposal

The final names may change during contract review, but the smallest expected
surface is:

```text
POST  /api/v1/courses/{course_id}/practice
GET   /api/v1/courses/{course_id}/practice
GET   /api/v1/courses/{course_id}/practice/{practice_set_id}
POST  /api/v1/courses/{course_id}/practice/{practice_set_id}/archive

POST  /api/v1/courses/{course_id}/practice/{practice_set_id}/attempts
GET   /api/v1/courses/{course_id}/practice/{practice_set_id}/attempts
GET   /api/v1/courses/{course_id}/practice/{practice_set_id}/attempts/{attempt_id}
PATCH /api/v1/courses/{course_id}/practice/{practice_set_id}/attempts/{attempt_id}
POST  /api/v1/courses/{course_id}/practice/{practice_set_id}/attempts/{attempt_id}/submit

POST  /api/v1/courses/{course_id}/flashcards
GET   /api/v1/courses/{course_id}/flashcards
GET   /api/v1/courses/{course_id}/flashcards/{deck_id}
PATCH /api/v1/courses/{course_id}/flashcards/{deck_id}
POST  /api/v1/courses/{course_id}/flashcards/{deck_id}/archive
POST  /api/v1/courses/{course_id}/flashcards/{deck_id}/reviews
```

Generated set/deck creation uses explicit operation IDs and progress status
behind these Course-owned resources. No endpoint accepts an owner ID, KB name,
external BlueWay title, or client-selected filesystem path.

## 11. Verification plan

### Contract tests

- Owner and parent Course are derived server-side.
- Foreign and missing resources are non-enumerating.
- Revisions, immutable states, idempotency, archive, and restart behavior pass.
- Every grounded question/card citation resolves to the frozen source snapshot.
- Mastery updates exactly once per graded item.
- Flashcard review scheduling is deterministic.

### Golden local scenarios

1. Biology and Calculus have identical source filenames but isolated Practice sets.
2. Alice and Bob have Courses named “Biology”; crossed IDs return `404`.
3. A five-question manual quiz survives browser and server restart.
4. A generated quiz fails midway and publishes no partial ready set.
5. A changed source creates a successor while an older attempt remains reviewable.
6. A manual Flashcard deck completes an Again/Hard/Good/Easy review loop.
7. A malicious transcript cannot invoke tools or select another Knowledge source.
8. A BlueWay transcript creates grounded cards without importing raw audio or provider metadata.
9. Archiving a Course blocks new attempts/reviews but retains history.
10. Logout followed by another login exposes no prior Course learning cache.

### Proof surfaces kept separate

- Source and schema.
- Unit/contract tests.
- Full Python and web regression.
- Authenticated browser runtime.
- BlueWay backend/data sync.
- Real provider generation.
- Deployment and hosting.
- Physical-device behavior.
- Historical data migration.
- Future upstream integration.

## 12. Risks and decisions

### Open product decisions

1. Historical data: functionality-only first, or also import old attempts/decks?
   Recommendation: functionality first; separate dry-run importer later.
2. Ungrounded generation: allow explicit topic-starter quizzes/cards?
   Recommendation: allow only with a visible “Not grounded in your Course sources”
   label and never use them for high-confidence mastery.
3. Qualitative grading: model judgment or self-assessment?
   Recommendation: deterministic grading for V1; add explicitly labeled model
   judgment later.
4. Flashcard scheduling: exact historical algorithm or a smaller new policy?
   Recommendation: inspect historical behavior, then adopt a documented,
   deterministic policy rather than copying storage code.
5. Archived source behavior: keep old assets visible?
   Recommendation: keep historical attempts/decks visible with an unavailable-source
   badge; block new generation until an active source is selected.

### Engineering risks

- Duplicating learning/mastery state across assessment and learning storage.
- Treating display text as identity during historical behavior porting.
- Letting generated source text influence tools or routing.
- Partial generation represented as a complete learning asset.
- Double-counting mastery during retry or duplicate submission.
- Browser cache leakage during identity or Course switches.
- Importing historical data before its ownership can be proved.
- Letting moving upstream work destabilize the bounded v1.5.2 product lane.

## 13. Exit criteria

### Phase 3A

- The Phase 3 plan and proof ledger no longer contradict each other.
- Current TEEECHR branch validation passes.
- One real non-empty transcript reaches the correct private Course Knowledge.
- Provider-free production-shaped Course Chat proof shows imported transcript-like
  text remains passive and cannot obtain tool authority; P3A-03 still requires the
  separate current real transcript/CourseSource/citation receipt.
- Current two-user browser isolation and disposable disconnect/reconnect pass.
- Fixture cleanup is reviewed separately from active beta authority.
- Final closeout records all remaining unproved surfaces.

### Phase 4

- Practice/Quiz and Flashcards are Course-owned, persistent, restart-safe, and archived rather than hard-deleted.
- Manual learning workflows operate without paid providers.
- Generated assets are bounded, source-grounded, cited, and fail closed.
- Graded quiz items update mastery idempotently.
- Flashcard reviews schedule review without falsely asserting mastery.
- Learner actions open the correct owned Course workflow.
- Two-user, two-Course, fifty-profile, concurrency, restart, and prompt-injection tests pass.
- Historical data migration and upstream integration remain explicitly deferred.

## 14. Recommended execution order

```text
P3A truth reconciliation
  -> exact TEEECHR revalidation
    -> real transcript ingest
      -> transcript prompt-injection proof
        -> two-user browser + disposable revoke/reconnect
          -> Phase 3 closeout
            -> Phase 4 schema
              -> manual Practice/Quiz
                -> grading/mastery adapter
                  -> grounded Practice generation
                    -> manual Flashcards
                      -> grounded Flashcard generation
                        -> learner actions/remediation
                          -> beta-scale proof and closeout
```

Upstream integration begins only through a separately approved future plan.
