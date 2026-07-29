# TEEECHR v1.5.2 Phase 4 Database Contract

Status: **implemented through migration `0007`; Phase 4 hardening qualification in progress**

Canonical parent:
`docs/TEEECHR_V152_PHASE3A_PHASE4_LEARNING_WORKFLOWS_PLAN.md`

Accepted starting commit: `af5eab79ec7b918242b228de67af358944323fd9`

## Authority chain

1. The authenticated account determines the immutable `owner_user_id`.
2. `PersonalPathService` resolves that owner's private `courses.db`.
3. `CourseRepository` owns the database connection policy and resolves one
   process-local lock from a canonical database-path lock registry.
4. The Phase 4 migration runner is the only authority allowed to create or
   evolve managed tables, indexes, triggers, or checks.
5. Course, BlueWay, Practice, attempt, grading-evidence, Flashcard, and review
   repositories consume the migrated schema; they do not run independent DDL.

API callers never supply an owner ID, database path, Knowledge Base name,
display title, or external BlueWay title as authority.

## Current root cause

At the accepted Phase 3A commit, `CourseRepository._initialize` creates Course
and source objects while `BlueWayRepository._initialize` independently creates
integration objects and performs ad hoc repairs. In addition,
`CourseRepository._write_lock` is allocated per repository instance rather than
per resolved database path. This is safe only as a bounded legacy state. P4-01
must converge both DDL paths into one migration authority and introduce a
canonical path-keyed lock registry before adding learning tables.

Two legitimate ledger-free legacy profiles are currently known:

- `phase3a_course_only`: Course and CourseSource objects exist; the user has
  never initialized the optional BlueWay repository.
- `phase3a_course_plus_blueway`: the canonical Course objects and the current
  BlueWay connection, mapping, record, sync-run, and replay-guard objects exist.

The machine-readable manifest is
`docs/contracts/teeechr_phase3a_courses_schema_manifest.json`. Any additional
historical profile must be added from reviewed source/history evidence with a
dedicated fixture and test. The runner must never infer a repair for an unknown
shape.

## Migration artifact contract

Checked-in SQL under the eventual Course migration package is immutable after
release. The first artifact is:

```text
0000_phase3a_baseline.sql
```

The ledger is deliberately minimal:

```sql
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    checksum_sha256 TEXT NOT NULL,
    applied_at_utc TEXT NOT NULL
);
```

`checksum_sha256` is the lowercase SHA-256 digest of the exact checked-in SQL
bytes. It is not derived from dynamically generated SQL, normalized SQL, Python
source, or an in-memory callable.

One migration receipt is inserted only after its SQL and postconditions pass in
the same transaction. Recorded version, name, or checksum disagreement blocks
startup.

## Startup algorithm

1. Resolve the authenticated user's `courses.db` through server authority.
2. Resolve and acquire the canonical path-keyed repository write lock.
3. Open the database with a bounded busy timeout.
4. Enable `PRAGMA foreign_keys = ON`.
5. Read `PRAGMA foreign_keys` and fail unless it returns `1`.
6. Classify the database:
   - empty;
   - ledger-free exact `phase3a_course_only`;
   - ledger-free exact `phase3a_course_plus_blueway`;
   - ledger-bearing;
   - unknown or partial.
7. For an empty database, apply `0000_phase3a_baseline.sql`.
8. For exact `phase3a_course_only`, apply the idempotent baseline inside
   `BEGIN IMMEDIATE` to add only the missing empty BlueWay objects, then verify
   convergence.
9. For exact `phase3a_course_plus_blueway`, create the ledger and adopt the
   baseline without rewriting domain rows.
10. For a ledger-bearing database, validate every receipt against the checked-in
    artifact set.
11. For an unknown or partial database, fail closed before any write and return
    the structural difference.
12. Apply each pending migration separately:
    - `BEGIN IMMEDIATE`;
    - execute exact artifact bytes;
    - verify declared postconditions;
    - run `PRAGMA foreign_key_check`;
    - insert the immutable receipt;
    - `COMMIT`.
13. Roll back the active migration on any failure. Previously committed valid
    migrations remain intact.
14. Release the lock.

Every normal repository connection—not only the migration connection—must enable
and verify foreign-key enforcement. `BEGIN IMMEDIATE` is still required for
SQLite writer exclusion, including callers outside the current process; the
Python lock is not treated as a cross-process guarantee.

## Schema comparison

Raw `sqlite_master.sql` text is not the primary equality mechanism. The
comparator uses normalized structural facts:

- managed tables and columns;
- declared type, nullability, default, and primary-key position;
- foreign-key source/target and update/delete actions;
- named indexes, uniqueness, indexed columns, sort direction, and partial
  predicate;
- unique constraints represented by SQLite auto-index metadata;
- explicitly modeled checks and required triggers.

The comparator returns a bounded diagnostic such as:

```text
course_sources:
  missing column: idempotency_key
blueway_sync_runs:
  index mismatch: blueway_snapshot_replay
```

SQLite internal objects are ignored. Explicitly listed unmanaged objects may be
preserved. Unknown objects using TEEECHR-managed names or colliding with managed
tables/indexes cause a fail-closed result.

## History authority

Ready learning content has one historical authority:

```text
PracticeSet
└── PracticeSetRevision (immutable once ready)
    └── PracticeQuestion (immutable content and citations)

QuizAttempt
├── references one PracticeSetRevision
├── QuizAttemptItem (question identity and presentation order)
└── QuizAttemptAnswer (learner state and optimistic revision)
```

Attempts do not duplicate full immutable question text or source snapshots.
They persist only presentation-specific state such as question order, option
order, randomized values, answers, submission, and grading. Archive-only
retention guarantees the referenced revision remains reviewable.

## Just-in-time migration sequence

- P4-01: migration infrastructure and Phase 3A baseline only.
- P4-02A: PracticeSet, PracticeSetRevision, and PracticeQuestion.
- P4-02B: QuizAttempt, QuizAttemptItem, and QuizAttemptAnswer.
- P4-03: immutable grading and mastery-evidence receipts.
- P4-06: FlashcardDeck, Flashcard, and FlashcardReview.
- P4-10 hardening: additive retained-history admission guards in
  `0007_assessment_resource_governance.sql`.

No future table is introduced before the repository behavior that uses it.

## Executable invariant map

| Invariant | Enforcement |
| --- | --- |
| A Practice set belongs to one Course | Foreign key plus Course-rooted repository lookup |
| An attempt cannot switch revisions | Immutable `practice_set_revision_id` |
| Ready questions cannot change | Repository state predicate and immutable ready revision |
| Stale tabs cannot overwrite answers | Compare-and-swap answer revision |
| Submission freezes answers | Attempt-state predicate in answer update |
| One graded item affects mastery once | Unique mastery-evidence idempotency receipt |
| Archived Course cannot create new work | Transactional Course-state and write-epoch check |
| Foreign and missing IDs look identical | One service-level non-enumerating `404` mapping |
| Flashcard rating does not claim mastery | No mastery adapter call from review persistence |
| Migration files cannot be rewritten | Stored artifact-byte checksum comparison |
| Retained attempts cannot grow without bound | Repository check plus the `0007` SQLite trigger caps each Practice set at 100 attempts |
| Autosave receipts cannot exhaust a profile database | Repository check plus the `0007` SQLite trigger caps each attempt at 2,048 receipts and 2 MiB of retained response JSON |
| Grading evidence cannot grow without bound | The complete evidence plan is bounded before insertion; the `0007` SQLite trigger independently caps each attempt at 4,096 rows and 2 MiB |
| Flashcard reviews cannot grow without bound | Repository check plus the `0007` SQLite trigger caps each deck at 10,000 retained reviews |

## Phase 4 beta resource-governance contract

The Phase 4 single-host beta preserves learner evidence instead of deleting it
silently. When a retained-history ceiling is reached, the new write returns a
conflict and all existing attempts, receipts, evidence, and reviews remain
readable.

Generated learning assets use one owner-wide transactional admission decision
across Practice and Flashcards:

- at most 4 queued or running generation operations;
- at most 64 retained generation operations;
- at most 16 retained generated drafts.

The exact idempotency replay is resolved before those ceilings, so retrying the
same accepted request never purchases or allocates duplicate work, including
after provider availability changes. Provider availability is checked before
allocating a new draft. Practice and Flashcards share four process-wide provider
execution permits; a timed-out call holds its permit until it actually exits, so
repeated timeouts cannot grow live provider threads without bound. The
deterministic local provider remains test-only; an unconfigured real provider is
represented to the browser as unavailable and fails before durable generation
allocation.

Attempt and deck history APIs use bounded pages: 50 rows by default and 100
rows maximum. These are admission and presentation bounds, not retention or
deletion jobs.

## Explicit exclusions

- No Practice, attempt, grading, Flashcard, or review tables in P4-01.
- No API, frontend, provider, generation, historical-data import, deployment, or
  hosted mutation in P4-01.
- No second database, independent lock, caller-provided owner, or parallel DDL
  bootstrap.
- No raw-SQL-string equality as the sole schema comparator.
- No automatic repair or adoption of unknown schemas.
- No push, merge, or remote checkpoint without separate approval.

## Definition of done for P4-01

P4-01 is complete only when P4-01A, P4-01B, and P4-01C each pass their tests,
the repository has exactly one managed-schema authority, existing Course and
BlueWay identities and values are preserved, fresh and upgraded manifests
converge, normal connections verify foreign keys, and an independent review
finds no unresolved P0-P2 issue.
