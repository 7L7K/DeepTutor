# TEEECHR v1.5.2 Phase 3A and Phase 4 — Close BlueWay, Restore Learning Workflows

Status: **Phase 3A accepted; Phase 4 locally complete for the provider-free single-host engineering boundary.**
The real two-owner Apple/device flow, hosted fixture retirement, publication,
deployment, and release certification remain parked. They do not block Phase 4,
and Phase 4 must not imply that those distinct surfaces passed.

### 2026-07-28 Phase 3A engineering closeout

- The primary real BlueWay connection was recovered under persistent
  single-host credential authority and completed one bounded sync without
  replacing retained Course/source/mapping/record identities.
- A provider-free hermetic command now proves authenticated Alice/Bob route
  isolation, real local BlueWay HTTP transport, private SQLite persistence,
  encrypted credential re-instantiation, revocation, same-subject reconnect,
  and non-duplicating Course mapping reuse.
- A replay-index bootstrap race found by the harness was repaired and
  adversarially tested so initialization never removes a correct live replay
  guard.
- Final focused results are hermetic `5 passed`, affected legacy/schema
  `27 passed`, Ruff/shell/diff checks pass, and no P0-P2 independent-review
  finding remains.
- The user accepted this as the Phase 3A engineering boundary. Native Apple,
  current device/browser, hosted cleanup, merge, push, deployment, and release
  claims remain separate.

### 2026-07-27 Phase 3A closeout-repair receipt

- TEEECHR authority is
  `/Users/home/Desktop/2k26/teeech/DeepTutor-v1.5.2-baseline` on
  `feature/teeechr-v152-phase3a-closeout`. The exact validated source/test repair
  tip is `850e7316` (five local commits). This documentation-only superseding
  receipt at `bd6c117e` follows that validated tip; the immutable command/SHA
  receipt is Linear project comment
  `ffa56940-2ec2-4b56-9e8d-47fdf0b8436d`. The branch is not pushed or a Phase
  3A completion claim.
- Canonical BlueWay authority is `/Users/home/Developer/BlueWay-local`, `main` at
  `1203983c`, two local commits ahead of `origin/main` as observed on
  2026-07-28. Its user-owned dirty worktree is preserved and read-only for this
  lane. The isolated Phase 3A proof worktree is
  `/Users/home/Desktop/2k26/teeech/BlueWay-phase3a-transcript-proof` on
  `feature/teeechr-phase3a-transcript-proof` at `1752e5f`; this receipt makes no
  claim about its current cleanliness.
- The historical-fork safety branch remains preserved. Upstream v1.5.5 integration
  remains deferred; no push, merge, deployment, hosted mutation, or paid/provider
  call is authorized by this closeout lane.
- Exact-`850e7316` local source/validation receipt: backend
  `2862 passed, 6 skipped, 9 warnings`; web node suite `168 passed`; `tsc`
  passed; Next production build emitted `52` routes; lint reported `0` errors
  and `101` warnings; i18n parity passed (audit findings informational); Ruff,
  `git diff --check`, the bounded changed-range secret scan, and clean-worktree
  verification passed. The first independent closeout review found only stale
  receipt text after the fifth commit; this section supersedes that text.
- The repair set adds per-round tool-schema authority with atomic rejection of an
  unauthorized tool batch; Course mastery suppresses build/assess and requires a
  private, real `ask_user` reply receipt; no-speech transcript omission; a
  production-shaped, provider-free import-to-Course-Chat passive-content proof; and
  auth-setting test isolation.
- The content-free receipt in
  `docs/TEEECHR_V152_PHASE3A_REAL_TRANSCRIPT_RECEIPT.md` closes the real
  transcript/CourseSource/restart/citation gate without another sync or paid
  call.
- At the time of this 2026-07-27 receipt, persistent credential-loss recovery,
  two-account browser isolation, disposable revoke/reconnect, and confirmed
  fixture cleanup remained open. The 2026-07-28 engineering acceptance above
  supersedes that status while preserving the native/hosted release gates.

Last updated: 2026-07-28

## Canonical authority

This file is the canonical engineering decision and phase-order authority for
Phase 4. The root migration handoff is an operator overview and
`FUTURE_DUE.md` is the deferred-work ledger; neither may redefine the schema,
invariants, or implementation order recorded here.

Accepted Phase 4 starting point:
`af5eab79ec7b918242b228de67af358944323fd9`.

Active local implementation branch:
`feature/teeechr-v152-phase4-learning`.

### Phase 4 implementation goal

Deliver a private, Course-owned college learning loop on the accepted Phase 3A
foundation: establish one restart-safe and checksum-backed `courses.db` schema
authority; implement immutable Practice revisions, resumable attempts,
deterministic grading with idempotent mastery evidence, manual and grounded
Practice, persistent manual and grounded Flashcards, and Course-scoped learner
actions/remediation; then qualify ownership, archive, revision, replay,
concurrency, restart, browser identity isolation, prompt-injection resistance,
and 50-profile beta behavior without paid providers, hosted mutation, BlueWay
source changes, deployment, push, merge, hard deletion, historical-data import,
or upstream integration.

Completion means P4-01 through P4-10 pass their slice-local and integrated
acceptance criteria, affected regressions and production build pass, the
repository closeout backcheck finds no unresolved P0-P2 issue, and exact
unproved release surfaces remain documented.

The P4-01 subordinate artifacts are:

- `docs/TEEECHR_V152_PHASE4_DATABASE_CONTRACT.md`
- `docs/contracts/teeechr_phase3a_courses_schema_manifest.json`
- `docs/TEEECHR_V152_PHASE4_P4_01_TEST_SPEC.md`
- `docs/TEEECHR_V152_PHASE4_P4_01_COMMIT_MAP.md`

They provide executable detail for this plan but do not override it. P4-01 was
implemented on the local Phase 4 branch by `1cc75f2f`. P4-02A was implemented
by `6bdb5179`, P4-02B by `d613b8ad`, P4-03 by `96e073ee`, P4-04 by
`5cf02793`, P4-05 by `20a604be`, and P4-06 by `c55d2dc0`; P4-07 is the
local implementation commit `712769b3`, P4-08 by `0b88ca61`, and P4-09 by
`b4e68369`. P4-10 closeout is the next active slice.

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
| Current Course/BlueWay product | `/Users/home/Desktop/2k26/teeech/DeepTutor-v1.5.2-baseline`, `feature/teeechr-v152-phase4-learning`, based exactly on accepted Phase 3A commit `af5eab79` | Active Phase 4 implementation authority; Phase 3A engineering is accepted | Keep commits local; no push, merge, or deployment without separate approval |
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

### PracticeSet, PracticeSetRevision, and PracticeQuestion

```text
PracticeSet
  id: prc_<opaque UUID>
  owner_user_id
  course_id
  title
  mode: manual | generated
  state: draft | archived
  current_revision_id?
  write_epoch
  created_at
  updated_at
  archived_at?
```

```text
PracticeSetRevision
  id: prv_<opaque UUID>
  practice_set_id
  revision_number
  state: draft | ready | superseded
  source_snapshot_json
  objective_ids_json
  generation_receipt_json?
  created_at
  ready_at?
```

```text
PracticeQuestion
  id: qst_<opaque UUID>
  practice_set_revision_id
  question_type
  prompt
  answer_contract_json
  explanation
  objective_ids_json
  citation_json
  ordinal
  created_at
```

`PracticeSetRevision` is the sole historical authority for immutable question
content, objectives, citations, and source provenance. Its
`source_snapshot_json` contains only server-resolved source IDs, revisions, and
fingerprints. Questions become immutable when their revision becomes ready.
Corrected or regenerated content creates a successor revision; it does not
rewrite completed attempts. Display names and prompt text are never authority.

### QuizAttempt, QuizAttemptItem, and QuizAttemptAnswer

```text
QuizAttempt
  id: att_<opaque UUID>
  owner_user_id
  course_id
  practice_set_id
  practice_set_revision_id
  state: in_progress | submitted | graded | abandoned | archived
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
  display_ordinal
  option_order_json?
  randomized_values_json?
  grading_json?
  error_type?
  graded_at?
```

```text
QuizAttemptAnswer
  attempt_item_id
  response_json?
  revision
  answered_at?
```

An attempt references exactly one immutable `PracticeSetRevision`; it does not
duplicate full question text, citations, objectives, or source snapshots.
Attempt items persist presentation-specific facts such as question order,
option order, and randomized values. Answers use compare-and-swap revisions.
Submission freezes answers, and grading results become immutable.

An attempt cannot be moved to another Course or silently upgraded to a newer
revision. Archive-only retention keeps its referenced revision reviewable.

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
constraints before P4-01 may begin. They refine the task breakdown and now form
the Phase 4 implementation entry contract.

### Course database evolution

- `courses.db` currently has no schema-version ledger. Its existing
  `CREATE TABLE IF NOT EXISTS` statements and ad hoc Course/BlueWay repairs are
  not sufficient provenance. `CourseRepository` and `BlueWayRepository`
  currently form two independent schema authorities; P4-01 must replace both
  with one migration runner before adding learning tables.
- P4-01 is internally split into P4-01A migration kernel, P4-01B Phase 3A
  baseline adoption, and P4-01C bootstrap unification. It adds no Practice,
  attempt, grading, Flashcard, or review table.
- Existing databases may adopt the baseline only after the runner structurally
  verifies a known ledger-free profile. The current manifest recognizes exact
  Course-only and Course-plus-BlueWay profiles because BlueWay initialization
  was optional. Partial or unknown shapes fail closed with a useful difference.
- Each migration records an immutable version/name/checksum receipt derived
  from exact checked-in SQL bytes and runs under the per-database repository
  write lock with verified foreign keys. Fresh creation and adoption must
  converge to the same effective definitions.
- The current lock is per `CourseRepository` instance. P4-01A replaces it with
  a canonical resolved-path lock registry; `BEGIN IMMEDIATE` remains the SQLite
  writer-exclusion authority and the Python lock is not a multi-process claim.
- Future tables are introduced just in time: Practice revisions/questions in
  P4-02A, attempts/answers in P4-02B, grading evidence in P4-03, and
  Flashcards/reviews in P4-06.
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
- `PracticeSetRevision` owns immutable historical question/source/citation
  content. Attempts reference one revision and persist only presentation order,
  randomized values, learner answers, submission, and grading; they do not copy
  complete question snapshots.

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

### Executable invariants and slice-local proof

Each safety principle must map to a database constraint, transactional
repository predicate, service behavior, or test. At minimum:

- Course membership is enforced by foreign keys and Course-rooted queries.
- Attempt revision membership is immutable.
- Ready questions reject updates.
- Autosave uses compare-and-swap answer revisions.
- Submission freezes answers.
- A unique grading-evidence receipt prevents duplicate mastery effects.
- Course archive/write epoch is rechecked in the write transaction.
- Missing and foreign resources use the same service-level `404`.
- Flashcard reviews have no direct mastery adapter.
- Stored migration checksums block rewritten artifacts.

Basic isolation, concurrency, restart, replay, archive, and browser behavior are
proved in the slice that introduces them. P4-09 retains integrated 50-profile,
extended-concurrency, and full learning-loop qualification; it is not the first
place fundamental invariants are tested.

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

**2026-07-27 source/test receipt:** local backend, focused repair, web,
TypeScript, build, lint, i18n, Ruff, and diff checks passed as recorded above.
That receipt did not itself close the live proof gates; P3A-03 is now closed by
the separate 2026-07-28 real-transfer receipt, while browser, recovery,
revoke/reconnect, and fixture gates remain open.

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
- **Historical pre-proof condition:** an eligible non-empty transcript had to
  exist under the approved owner. The 2026-07-28 receipt below proves that
  condition for the recorded transfer without another sync.

**2026-07-28 real-transfer receipt:** this gate is now proved by the content-free
receipt in `docs/TEEECHR_V152_PHASE3A_REAL_TRANSCRIPT_RECEIPT.md`. The exact
owner-bound hosted aggregate has `9` completed transcripts: `7` with non-empty
segments and `2` valid no-speech completions. The completed TEEECHR sync retained
those `7` searchable transcripts in `5` hash-matching ready Course bundles.
After process restart, an exact transcript CourseSource emitted one
`blueway-course-bundle.json` citation for its owning profile and none for a
foreign profile. No raw identity, per-user, Course, source,
Knowledge-reference, bundle-content, transcript-content, or bearer fingerprint
entered the tracked receipt. The published evidence-artifact and verifier
SHA-256 values are reproducibility checksums only.

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
  below closes the local tool/passive-content contract. It does not replace the
  separately documented real-transfer receipt that closes P3A-03.

**2026-07-27 repair proof:** production-shaped provider-free import-to-Course-Chat
coverage satisfies this local passive-content/tool-authority gate: malicious-looking
imported text remains passive and cannot obtain tool authority. It is not the
authority for the separate real transfer receipt in P3A-03.

### P3A-04A — Repair persistent credential and recovery authority

- **Scope:** TEEECHR secret loading, encrypted credential preflight, recovery
  lifecycle, and provider-free tests; hosted secret rotation remains a later
  separately approved action.
- **Inputs / outputs:** persistent owner-controlled AES and pairing secrets,
  envelope key identity, safe recovery state/API, and recovery proof.
- **Acceptance criteria:**
  - a normal server restart preserves credential decryptability;
  - integration startup fails closed into `credential_recovery_required` when
    an active credential is unreadable, while non-integration TEEECHR
    functionality remains available;
  - status distinguishes an active, decryptable connection from
    `credential_recovery_required`;
  - Disconnect preflight-decrypts the credential before entering
    `revocation_pending`, then preserves local-first generation fencing before
    any network revoke;
  - recovery preserves Courses, sources, records, mappings, mastery, and sync
    history while quarantining the unreadable envelope;
  - an owner-approved replacement pairing atomically replaces the remote grant
    and reuses Course identity only by owner and opaque external identity;
  - no secret is committed, logged, returned to the browser, or silently
    regenerated.
- **Risk / unknown:** the two existing envelopes were encrypted with an
  ephemeral process-only key and are cryptographically unrecoverable. Do not
  attempt current local disconnect or a new-key sync.

**Historical 2026-07-27 source status:** the single-host persistent authority, fail-closed
`credential_recovery_required` state, same-subject recovery exchange, generation
fences, credential quarantine, recovery API, Settings UI, and provider-free
adversarial tests are implemented on the Phase 3A closeout branch. This is source
and deterministic-test proof only. The primary grant remains untouched; hosted
pairing-secret rotation, persistent-authority runtime bootstrap/restart,
same-account live recovery, and the post-recovery bounded sync still require
their separate operational gates. The 2026-07-28 live recovery receipt and
engineering acceptance above supersede this historical operational status.

### P3A-05 — Parked release certification: current two-user browser isolation

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

If only one disposable BlueWay account is available, record a partial proof
only: two disposable TEEECHR profiles may prove same-title local Course
isolation, non-enumerating foreign Course/source/session/sync `404`s, and
Alice-to-Bob logout/cache clearing; one account may prove one real BlueWay
consent/status/sync. It does not prove a second BlueWay account's consent,
export/sync, or independently mapped imported Course, and therefore does not
satisfy this gate.

### P3A-06 — Parked release certification: disposable reconnect and fixtures

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

Status: **completed for the accepted engineering boundary.** The parked
release-certification gates above remain explicitly unproved.

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

### P4-01A — Migration kernel

- **Scope:** immutable migration discovery, ledger, exact-byte checksums,
  transactions, per-database locking, foreign-key verification, and diagnostics.
- **Inputs / outputs:** migration runner only; no learning table.
- **Acceptance criteria:**
  - duplicate versions/names and unknown receipts fail closed;
  - tampering, failed SQL, failed postconditions, and foreign-key violations
    roll back the active migration and receipt;
  - concurrent startup results in one writer and one completed-state observer;
  - every normal repository connection enables and verifies foreign keys.
- **Doc alignment:** `docs/TEEECHR_V152_PHASE4_DATABASE_CONTRACT.md`.
- **Risk / unknown:** connection-level foreign-key policy must not exist only in
  the migration runner.

### P4-01B — Phase 3A baseline adoption

- **Scope:** checked-in `0000_phase3a_baseline.sql`, structural manifest
  comparator, known-profile adoption, and preservation tests.
- **Inputs / outputs:** one canonical Phase 3A schema and one baseline receipt.
- **Acceptance criteria:**
  - empty, exact Course-only, and exact Course-plus-BlueWay states converge;
  - partial, unknown, and managed-name-collision states fail before mutation;
  - Course, source, mapping, record, sync, and replay-guard identities and values
    remain unchanged;
  - diagnostics identify exact structural differences.
- **Doc alignment:**
  `docs/contracts/teeechr_phase3a_courses_schema_manifest.json`.
- **Risk / unknown:** any additional historical shape requires explicit
  source-backed fixture authority; it is never guessed.

### P4-01C — Single bootstrap authority

- **Scope:** route fresh database creation through migrations and remove or
  reduce Course/BlueWay DDL bootstraps to migration-runner calls.
- **Inputs / outputs:** exactly one managed-schema creation/evolution path.
- **Acceptance criteria:**
  - repeated startup is a no-op;
  - restart and concurrent repository wrappers are safe;
  - existing Course and BlueWay repository behavior remains green;
  - no independent ad hoc repair path remains.
- **Doc alignment:** `CourseRepository._initialize`,
  `BlueWayRepository._initialize`, and the P4-01 commit map.
- **Risk / unknown:** conversion must preserve the repaired live BlueWay replay
  guard continuously.

### P4-02A — Practice authoring persistence

Status: **completed for the local engineering boundary by `6bdb5179`.**

- **Scope:** introduce PracticeSet, PracticeSetRevision, and PracticeQuestion
  migration plus Course-rooted repository/service methods.
- **Inputs / outputs:** create/list/read/archive sets; draft, ready, successor
  revision, questions, objectives, citations, and source receipt.
- **Acceptance criteria:**
  - ready revisions and questions are immutable;
  - corrections create successors;
  - foreign/missing identifiers return the same `404`;
  - two users and same-titled Courses remain isolated;
  - archive and restart preserve history.
- **Doc alignment:** Section 5 and historical Practice behavior.
- **Risk / unknown:** do not freeze generation-only fields into the manual
  authoring contract unnecessarily.
- **Implementation receipt:**
  - migration `0001_practice_authoring.sql` is governed by the P4-01
    exact-byte ledger and both packaged wheels;
  - P4-02A exposes manual authoring only; generated provenance remains reserved
    for the server-owned P4-05 operation;
  - database triggers and indexes enforce active Course/Practice parents,
    draft-only creation, nonempty publication, one ready revision, immutable
    ready history, forward-only current revision, archive-only retention, and
    no direct-SQL question insertion beneath ready or archived parents;
  - every multi-step write uses the shared resolved-path lock and
    `BEGIN IMMEDIATE`, requires the exact Course write epoch, and resolves
    source receipts from ready Course sources on the server;
  - focused Practice/migration/Course/BlueWay proof passed `74` tests; the
    broader Course plus BlueWay bootstrap/credential-recovery proof passed
    `136` tests with `6` existing warnings; Ruff and diff hygiene passed;
  - independent Terra review replayed the direct-SQL and stale-epoch attacks
    and returned PASS with no P0/P1 finding.

### P4-02B — Attempt persistence

Status: **completed for the local engineering boundary by `d613b8ad`.**

- **Scope:** introduce QuizAttempt, QuizAttemptItem, and QuizAttemptAnswer
  migration plus start/resume/autosave/abandon/submit behavior.
- **Inputs / outputs:** exact revision binding, presentation order, randomized
  values, compare-and-swap answers, and submission freeze.
- **Acceptance criteria:**
  - attempt membership never changes after creation;
  - concurrent stale autosaves are rejected;
  - submission freezes answers and double submit is idempotent;
  - unknown and foreign IDs return the same `404`;
  - restart preserves in-progress and submitted history.
- **Doc alignment:** historical `practice.py` behavior and current Course repository.
- **Risk / unknown:** autosave must not overwrite newer answers from another tab.
- **Implementation receipt:**
  - migration `0002_quiz_attempts.sql` is checksum-ledgered and packaged in
    both wheels; a prior exact P4-02A database applies only `0002`, preserves
    every Course/Practice row, creates empty attempt tables, and then replays
    as a no-op;
  - start authority requires the current ready Practice revision and derives
    all question membership and order server-side; one in-progress attempt is
    permitted per owner and Practice set;
  - successor publication and Course/Practice archive atomically archive
    in-progress attempts, preserve their immutable revision history, and never
    revive them on restore;
  - answers use exact-revision CAS writes and durable idempotency receipts that
    replay the original response, revision, and timestamp even after later
    autosaves; submission and abandonment are idempotent terminal operations;
  - schema triggers enforce immutable bindings/presentation, monotonic answer
    and attempt revisions, chronological timestamps, applied-answer receipt
    consistency, no deletes, uniform owned-parent relationships, and reserve
    grading fields for P4-03;
  - focused Practice/migration/BlueWay proof passed `69` tests; the broader
    Course plus BlueWay bootstrap/credential-recovery proof passed `153` tests
    with `6` existing warnings; Ruff and diff hygiene passed;
  - independent Terra review replayed timestamp, CAS, receipt-forgery,
    uniform-404, successor, archive, and concurrency attacks and returned PASS
    with no P0-P2 finding.

### P4-03 — Deterministic grading and mastery adapter

- **Scope:** grading-evidence migration, adapter, idempotency receipt, and
  learning-service integration.
- **Inputs / outputs:** graded items and Course mastery updates.
- **Acceptance criteria:**
  - deterministic question types use deterministic grading;
  - model-assisted grading is explicit, bounded, and separately labeled;
  - each graded attempt item affects mastery at most once;
  - double submission and repeated worker retry cannot duplicate grading or
    mastery evidence;
  - incorrect answers create error/review evidence;
  - Flashcard reviews do not directly change mastery.
- **Doc alignment:** `LearningService.grade_and_record`.
- **Risk / unknown:** qualitative questions require a separate judgment contract.

#### P4-03 implementation receipt — 2026-07-28

- implementation commit: `96e073ee`;
- SQLite atomically seals deterministic exact-answer item results, immutable
  per-objective evidence, and aggregate attempt score before any Learning JSON
  projection;
- evidence binds the frozen answer contract, canonical response object,
  question objective, captured module/type mapping, result, and error class;
- digest-checked pending evidence acts as a recoverable outbox, and the
  Learning receipt prevents duplicate mastery, error, or review effects after
  interruption, retry, or parent archive;
- zero-objective and unresolved-objective evidence is retained as immutable
  `unmapped` history without inventing mastery ownership;
- Course learning reset rejects authoritative SQLite grading history even when
  projection has not yet completed;
- Course/Practice archive and Practice successor replacement terminalize both
  in-progress and submitted ungraded attempts without deletion;
- SQLite validators reject forged wrong-answer grades, unrelated objectives,
  incomplete item evidence, and inconsistent aggregate scores;
- the exact staged snapshot passed Ruff, `git diff --check`, `47` focused
  grading/migration tests, and `462` impacted Course, BlueWay, and Learning
  tests; independent Terra review found no P0-P2 issue;
- the accepted runtime remains one application process. Multi-process Learning
  JSON delivery and cryptographic authenticity against an actor who can rewrite
  both SQLite and Learning JSON remain explicitly outside this phase.

### P4-04 — Manual Practice API and minimal UI

- **Scope:** Course-owned APIs and `/practice` Course workspace.
- **Inputs / outputs:** manual set creation, attempt runner, autosave, submit,
  results, resume, and history.
- **Acceptance criteria:**
  - works without a configured model;
  - active Course is visible on every page;
  - browser state is user- and Course-namespaced;
  - refresh, back navigation, and server restart preserve the correct attempt;
  - two authenticated browser identities cannot observe each other's state;
  - archive/identity changes make in-flight editors read-only or fail closed;
  - no broad redesign of Chat, Settings, or Course navigation.
- **Doc alignment:** historical `PracticeWorkspace`.
- **Risk / unknown:** retain the useful UX without carrying historical component debt.

#### P4-04 implementation receipt — 2026-07-28

- implementation commit: `5cf02793`;
- the authenticated Course API now exposes private manual Practice authoring,
  archive/restore, immutable ready revisions, resumable attempts, CAS and
  idempotent answer saves, submit/abandon, deterministic grading, and results;
- draft authoring responses include the answer contract, while ready learner
  responses omit it until the owned attempt is durably graded; results resolve
  the attempt's frozen revision rather than a newer current revision;
- `/practice` always displays the active Course, clears identity-, Course-, and
  view-scoped state on replacement, fences delayed set and attempt responses,
  requires explicit durable answer saves before submit, and persists no answer
  or quiz snapshot in browser storage;
- same-title Alice/Bob tests and foreign Course, set, revision, attempt, and item
  identifiers prove uniform private `404` behavior; archive, stale CAS,
  idempotency, answer-authority, historical-revision, and grading retries are
  covered;
- the exact slice passed Ruff, `78` focused backend tests, `235` impacted
  Course and BlueWay tests, TypeScript, ESLint, `175` web node tests, a Next
  production build including `/practice`, secret/diff checks, and independent
  Terra review with no P0-P2 finding;
- live browser interaction, refresh/back-navigation behavior, and two real
  authenticated browser sessions remain explicitly unproved here and are
  retained for the integrated P4-09 browser campaign.

### P4-05 — Grounded Practice generation

Status: **completed for the local engineering boundary by `20a604be`.**

- **Scope:** bounded generator, validator, background operation, progress API.
- **Inputs / outputs:** immutable generated PracticeSetRevision with citations.
- **Acceptance criteria:**
  - only server-resolved active sources enter retrieval;
  - item/text/context/time limits are enforced;
  - malformed or incomplete generation never becomes ready;
  - account disable/revocation, Course or Practice write-epoch changes,
    generated-draft replacement, archive, or source receipt changes fence the
    final commit;
  - browser logout or identity change immediately fences browser progress and
    result application, but does not revoke the account or silently cancel an
    already accepted server-owned operation; display-title-only Course
    revisions are likewise non-authoritative;
  - deterministic fake provider covers automated tests;
  - real provider proof requires separate approval.
- **Doc alignment:** Course source ingestion fences and historical Practice outcomes.
- **Risk / unknown:** question quality requires a later labeled evaluation set;
  contract correctness comes first.

#### P4-05 implementation receipt — 2026-07-28

- migration `0004_practice_generation.sql` adds retained, immutable generation
  operations with exact owner, Course, Practice revision, idempotency,
  source-snapshot, revision, and write-epoch bindings;
- generated questions and ready publication are database-fenced behind the
  matching running operation and its receipt; manual repository calls cannot
  mutate generated drafts;
- background work rebuilds the personal repository from the persisted owner,
  revalidates account and Course authority before final commit, reconciles
  orphaned operations after restart, and terminates provider work through a
  bounded server-owned deadline;
- the production provider seam fails closed as unavailable. Automated proof
  uses only the explicitly enabled deterministic local provider; no paid or
  real provider call was made;
- deterministic Course indexes carry the exact CourseSource content fingerprint,
  and generation accepts only server-resolved text whose fingerprint matches
  the frozen source receipt. Source text remains passive input and cannot
  select tools, Knowledge, owners, paths, or providers;
- malformed, partial, over-limit, uncited, stale-source, revoked-owner, archived,
  or write-epoch-stale results terminate safely and never publish a ready
  revision;
- ready question responses omit both answer contracts and answer-adjacent
  explanations until durable grading reveals them;
- exact local proof passed Ruff and diff/secret checks, `52` focused migration,
  API, generation, grading, and BlueWay-bootstrap tests, `255` impacted Course
  and BlueWay tests, TypeScript, ESLint, `175` web node tests, and a Next
  production build with `53` pages;
- independent Terra review returned `PASS_WITH_PARKED_FOLLOWUPS` with no P0-P2
  finding. Real-provider quality/cost, authenticated browser runtime, and a
  hostile writer with direct access to the private SQLite file remain outside
  this slice's proven boundary.

### P4-06 — Flashcard repository and manual workflow

Status: **completed for the local engineering boundary by `c55d2dc0`.**

- **Scope:** introduce deck/card/review migration with repository, scheduling
  policy, API, and minimal UI.
- **Inputs / outputs:** persistent manual decks and review sessions.
- **Acceptance criteria:**
  - deck/card/review ownership and Course binding pass;
  - rating produces deterministic next-review state;
  - missed-card loop and completion summary survive reload;
  - scheduling and review history survive restart;
  - archive blocks new reviews while retaining history;
  - manual cards work without a model.
- **Doc alignment:** historical `FlashcardService` and `FlashcardsWorkspace`.
- **Risk / unknown:** port scheduling behavior only after reviewing its time and
  persistence assumptions.

#### P4-06 implementation receipt — 2026-07-28

- migration `0005_flashcards.sql` adds private Course-owned decks, cards,
  append-only review events, and durable per-card schedules to the one
  checksum-backed `courses.db` migration stream (`0000..0005`);
- manual decks retain draft/ready/archive lifecycle, optimistic deck/card
  revisions, draft-safe restore, and archive-only history. Archived Courses,
  decks, and cards block new review work without deleting prior events;
- review idempotency binds the exact owner, Course, Course write epoch, deck,
  card, rating, and deck/card revisions. A persisted two-thread same-key race
  proves one review row, one schedule increment, and the same returned receipt;
- the documented deterministic UTC scheduling policy is Again `60` seconds,
  Hard at least `6` hours and `1.2x`, Good at least `1` day and `2x`, and Easy
  at least `4` days and `3x`, with every interval capped at `180` days.
  Flashcard ratings schedule review only and never mutate mastery;
- the authenticated Course API exposes manual deck/card lifecycle and due
  review operations without accepting owners, paths, Knowledge names,
  providers, or client clock authority;
- the `/flashcards` workspace uses the active private Course, keeps only
  transient review state, requeues Again cards inside the current pass, clears
  state on identity/Course changes, and becomes read-only when the Course is
  archived;
- exact proof passed Ruff and diff/secret checks, `98` initial Practice tests
  plus the persisted concurrency regression, `23` migration tests, `265`
  impacted Course and BlueWay tests, TypeScript, ESLint with no errors, `179`
  web node tests, and a Next production build with `54` pages including
  `/flashcards`;
- independent Terra review initially found two P2 closeout gaps (archived-Course
  UI fencing and a missing same-key concurrency regression). Both were fixed
  and re-reviewed; the final verdict was `PASS_WITH_PARKED_FOLLOWUPS` with no
  P0-P2 finding. Authenticated browser interaction and beta-scale qualification
  remain P4-09 proof surfaces.

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

P4-07 implementation receipt:

- migration `0006_flashcard_generation.sql` adds one retained, owner/Course-bound
  operation ledger and generated-deck successor identity without a second schema
  authority;
- a generated request freezes exact source revision/fingerprint receipts,
  objective IDs, item/context bounds, Course write epoch, deck write epoch,
  idempotency key, and request fingerprint before local work begins;
- final publication revalidates the current account, active Course/write epoch,
  draft generated deck, exact source revisions/fingerprints, bounded provider
  output, and every citation, then atomically inserts immutable cards, initial
  review schedules, the ready deck transition, and the completed operation;
- generated cards and ready state cannot be inserted through the manual
  Flashcard APIs or direct SQLite without the bound running operation; terminal
  completed/failed operations are immutable and no generation record has a
  delete path;
- explicit manual deck creation is the user-intent-only ungrounded starter path
  and is visibly labeled `Manual deck — not source-grounded`; the generated
  endpoint rejects empty source sets and the UI labels its result
  `Grounded in the cited Course sources`;
- the runtime provider is unavailable by default. The only automated execution
  provider is the explicit deterministic local fake, which treats indexed
  Course text as inert input, accepts no client prompt/provider/KB/tool
  authority, and makes no paid call;
- exact proof passed `43` focused generation/migration/Flashcard tests, `272`
  canonical Course and BlueWay tests (excluding three preserved unrelated
  duplicate `* 2.py` files), Ruff, staged/unstaged diff and high-confidence
  secret checks, TypeScript, ESLint, `181` web node tests, and a Next production
  build with `54` pages;
- independent Terra review found three P2 closeout gaps: terminal timestamp-only
  mutation, missing adversarial API parity/bypass checks, and ambiguous
  ungrounded-starter labeling. All three were fixed and re-reviewed; the final
  verdict was `PASS_WITH_PARKED_FOLLOWUPS` with no P0-P2 finding;
- real provider generation and an authenticated browser interaction remain
  unproved and are not implied by the local deterministic/API/build evidence.

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

**2026-07-28 local implementation receipt:** P4-08 is source- and
deterministic-test complete on local commit `0b88ca61`.

- the four Chat chips appear only for the latest completed, persisted assistant
  message in an active Course session;
- every action requires the exact authenticated Course, persisted session,
  selected assistant message, current Course revision, and write epoch;
- the browser request contains no prompt, source/objective selection,
  Knowledge-base name, provider/model, tool, path, or owner authority;
- the server resolves only current ready non-superseded Course sources and
  derives weak objectives from committed active errors, due reviews, and
  encountered low-mastery objectives;
- Practice and Flashcard actions reuse the existing fenced grounded-generation
  operations. Atomic live-operation registration prevents an idempotent replay
  from scheduling a second worker or orphaning the original;
- Explain simpler returns a fixed, side-effect-free server plan bound to the
  selected assistant message. The server does not send a chat turn, and an
  exact replay returns the same plan;
- delayed browser results are fenced by immutable user identity, Course,
  session, assistant message, and request epoch;
- Course-learning reads retain progress state while redacting pending prompt,
  expected answer, options, learner answers, learner attribution, AI
  confirmation, Feynman text, failure notes, and grading receipts;
- final validation passed `33` focused learner-action and generation tests,
  Ruff, staged/unstaged diff checks, `184` web node tests, TypeScript, targeted
  ESLint with no errors, and a Next production build with `54` pages;
- independent Terra review initially found duplicate-worker replay, missing
  browser identity fencing, and optional message provenance. All were fixed
  and re-reviewed; the final verdict had no remaining P0-P2 finding.

Authenticated browser interaction remains part of P4-09 and is not implied by
the API, unit, type, lint, or build proof above.

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

**2026-07-28 local implementation receipt:** P4-09 is provider-free,
integration-, and authenticated-browser complete on local commit `b4e68369`.

- fifty saved profiles receive separate personal Course databases and distinct
  opaque Course, Practice, Flashcard, and learning artifacts; foreign and
  missing Course resources retain identical `404` behavior;
- a separate normal bcrypt/JWT proof verifies immutable user-ID ownership,
  immediate role demotion on an already-issued token, and next-request denial
  after account disablement;
- ten independent assessment, review, and learning-reset operations run
  concurrently without a provider;
- Alice and Bob complete distinct graded-Practice and Flashcard-review loops
  for same-titled private Courses, with direct foreign Course, Practice, and
  Flashcard identifiers denied;
- stale revision, autosave/review replay, archive terminalization, restore,
  durable receipt history, and repository-wrapper reopen behavior pass;
- the real Practice and Flashcard generation workers run through deterministic
  local resolver/provider seams. Malicious source material remains inert text,
  while typed worker authority and persisted citations contain only the
  authenticated Course and immutable owned source receipts;
- the browser runner refuses occupied ports, creates a disposable auth/runtime
  root, and leaves no credential, cookie, report, or test-result residue in the
  repository;
- the two-part Playwright campaign creates same-titled Alice/Bob Courses,
  Alice's five-question manual quiz, and distinct learning plans; it then kills
  and waits for the backend process, starts a fresh application against the
  same durable root, and proves quiz/learning persistence, foreign-ID `404`,
  logout/cache isolation, and correct identity-scoped Course restoration;
- Course list/mutation responses are fenced by immutable identity and request
  epoch. A delayed archive of Course A checks the current runtime selection,
  so it cannot clear a newer same-user selection of Course B;
- final focused validation passed `32` backend learner-action/generation/beta
  tests, `185` web node tests, TypeScript, targeted ESLint, Ruff, diff checks,
  both authenticated Playwright halves, and a Next production build with `54`
  pages;
- independent Terra review initially found a false process-restart claim,
  synthetic-auth overclaim, same-identity archive race, and worker-boundary
  prompt-injection proof gap. All were corrected and re-reviewed with no
  remaining P0-P2 finding.

This proof is local and disposable. It does not imply a physical-device,
hosted, deployed, paid-provider, or production release result.

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

**2026-07-28 local closeout receipt:** P4-10 passes with parked release
follow-ups. The exact tested implementation head is `d16980c9`; the final
documentation commit follows this receipt.

- P4-01 through P4-09 are represented by reviewed local implementation,
  test, and receipt commits based on accepted Phase 3A commit `af5eab79`;
- the final affected Python campaign passed `399` Course, BlueWay, and
  multi-user tests with `8` warnings;
- the web campaign passed `185` node tests and TypeScript; full ESLint
  completed with `0` errors and `138` existing warnings; the production build
  emitted `54` pages;
- `scripts/test-phase4-browser` passed both authenticated halves: disposable
  Alice/Bob setup and verification after actual backend process death and
  restart;
- the first broad Python run found one macOS ACL race when an active SQLite
  `-shm` sidecar disappeared and was recreated between permission repair
  operations. Commit `d16980c9` adds a bounded sidecar-only retry that
  revalidates OS ownership, regular-file shape, symlink/hard-link constraints,
  mode `0600`, and ACL removal while persistent and non-sidecar errors remain
  fail-closed;
- focused ACL proof covers disappearance, recreation from `0644` to repaired
  `0600`, exact retry exhaustion, broken symlink, and hard-link substitution;
  the previously failing hermetic BlueWay lifecycle passed five consecutive
  reruns before the final `399`-test campaign passed;
- high-confidence secret scanning of the Phase 4 range found no key, JWT, or
  private-key pattern; no tracked database, WAL/SHM file, credential envelope,
  transcript payload, browser report, generated test result, or personal
  runtime data was added;
- the three unrelated untracked duplicate `* 2.py` files remain preserved and
  excluded from every Phase 4 commit;
- the repository section-closeout backcheck passes with
  `PASS_WITH_PARKED_FOLLOWUPS`; independent Sol review reports no unresolved
  P0-P2 issue inside the provider-free scope;
- no push, merge, deployment, hosted mutation, BlueWay source edit, paid
  provider call, hard deletion, historical learner-data import, or upstream
  integration occurred.

Parked release gates are explicit: complete pre-provider account/Course/target/
source revalidation before any real or paid generation call; current native
two-real-owner Apple/device certification; hosted fixture retirement;
production deployment/release; historical learner-data migration; and future
upstream reconciliation.

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

### Resolved Phase 4 product decisions

1. Historical data: functionality first. A separate report-only importer is
   parked in `FUTURE_DUE.md`.
2. Ungrounded starters: manual Practice and Flashcards are allowed only with
   visible not-source-grounded labeling; generated endpoints require owned
   ready sources.
3. Grading: exact deterministic grading is the Phase 4 authority. Model
   judgment remains a future explicitly labeled mode.
4. Flashcard scheduling: the implementation uses a documented deterministic
   Again/Hard/Good/Easy policy with a 180-day cap rather than copying historical
   storage.
5. Archived sources/assets: historical attempts and decks remain reviewable;
   archived parents block new work and no hard-delete path exists.
6. Accepted-commit durability: publish a checkpoint branch before Phase 4?
   The branch remains local. Push, merge, and deployment each require separate
   explicit approval after review of the final commit range.

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
  text remains passive and cannot obtain tool authority.
- Persistent credential authority and owner-approved recovery pass before any
  new-key sync or disconnect/reconnect attempt.
- Hermetic two-owner isolation and disposable disconnect/reconnect pass.
- Current native two-real-owner browser/device proof and fixture cleanup remain
  parked release-certification gates.
- Final engineering closeout records all remaining unproved surfaces.

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
        -> persistent credential authority + recovery
          -> hermetic two-owner + revoke/reconnect
            -> Phase 3 engineering closeout
              -> P4-01A migration kernel
                -> P4-01B Phase 3A baseline adoption
                  -> P4-01C single bootstrap authority
                    -> P4-02A Practice revisions/questions
                      -> P4-02B attempts/answers
                        -> P4-03 grading/mastery adapter
                          -> P4-04 manual Practice UI
                            -> P4-05 grounded Practice generation
                              -> P4-06 manual Flashcards
                                -> P4-07 grounded Flashcards
                                  -> P4-08 learner actions/remediation
                                    -> P4-09/P4-10 proof and closeout

Parallel release-certification lane:
  real second Apple owner -> current browser/device isolation
    -> disposable hosted revoke/reconnect -> reviewed fixture retirement
```

Upstream integration begins only through a separately approved future plan.
