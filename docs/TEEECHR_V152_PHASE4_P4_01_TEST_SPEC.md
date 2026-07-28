# TEEECHR v1.5.2 Phase 4 P4-01 Test Specification

Status: **approved test contract; tests not implemented**

Parent contract:
`docs/TEEECHR_V152_PHASE4_DATABASE_CONTRACT.md`

## Test locations

Expected implementation layout:

```text
tests/courses/migrations/test_runner.py
tests/courses/migrations/test_baseline_adoption.py
tests/courses/migrations/test_bootstrap_authority.py
tests/courses/migrations/fixtures/
```

Fixtures must be constructed from checked-in schema artifacts or explicit
legacy-shape builders. No fixture may copy a real user's database or personal
data.

## P4-01A — Migration kernel

| Case | Required result |
| --- | --- |
| Migration discovery | Exact numeric ordering; duplicate version or name is rejected |
| Exact-byte checksum | Receipt matches SHA-256 of checked-in SQL bytes |
| Tampered artifact | Checksum mismatch blocks startup before pending writes |
| Recorded unknown migration | Startup blocks rather than guessing |
| SQL failure | Entire active migration and receipt roll back |
| Failed postcondition | Entire active migration and receipt roll back |
| Foreign-key violation | `foreign_key_check` fails and active migration rolls back |
| Concurrent startup | One writer applies; the other observes the committed receipt |
| Actionable diagnostics | Failure identifies migration and structural/postcondition cause |
| Normal connection | Foreign-key enforcement is enabled and verified |

## P4-01B — Phase 3A baseline adoption

| Case | Required result |
| --- | --- |
| Fresh empty database | Canonical Phase 3A schema exists and ledger contains exactly one receipt |
| Exact Course-only legacy profile | Empty BlueWay objects are added, all Course/source rows remain identical, and one receipt exists |
| Exact Course-plus-BlueWay profile | Baseline is adopted without rewriting domain rows |
| Partial core schema | Startup fails and the database remains logically unchanged |
| Unknown managed schema | Startup fails with a bounded structural difference |
| Unknown unmanaged object | Allowed only when explicitly allowlisted |
| Managed-name collision | Startup fails closed |
| Existing domain data | IDs, counts, mappings, payloads, timestamps, revisions, and values remain identical |
| Fresh versus adopted | Canonical managed-schema manifests match |
| Replay guard | `blueway_snapshot_replay` remains continuously effective |

Data preservation is proved with before/after canonical row digests plus explicit
counts and identity sets. File-byte equality is not required because WAL,
page-layout, and ledger writes legitimately change SQLite bytes.

## P4-01C — Single bootstrap authority

| Case | Required result |
| --- | --- |
| Fresh `CourseRepository` | Schema is created only through the migration runner |
| Fresh `BlueWayRepository` | Performs no DDL and consumes the migrated schema |
| Repeated startup | No schema or receipt write occurs |
| Restart | Opens normally and performs no extra migration |
| Concurrent repository wrappers | Share the same per-database schema lock authority |
| Legacy ad hoc repair paths | Removed or reduced to calling the migration runner |
| Existing Phase 3A suites | Course and BlueWay repository tests remain green |

## Slice-local qualification after P4-01

Every later slice carries its own proof:

| Slice | Immediate qualification |
| --- | --- |
| Practice persistence | Two-user isolation, restart, archive, successor revision |
| Attempts | Concurrent autosaves, stale revision rejection, submission freeze |
| Grading | Double-submit and worker retry cannot duplicate grade or mastery evidence |
| Manual UI | Refresh, back navigation, restart, archive, and cross-user browser isolation |
| Generation | Fake provider, malformed output, citation enforcement, fenced final commit |
| Flashcards | Restart-safe scheduling, append-only reviews, and missed-card loop |

P4-09 retains the integrated 50-profile, extended-concurrency, full-browser, and
cross-feature qualification. It must not be the first time basic slice
invariants are tested.

## P4-01 regression command policy

Each P4-01 commit must run:

1. its focused new tests;
2. existing `tests/courses`;
3. existing BlueWay repository/bootstrap tests affected by DDL removal;
4. Ruff on changed Python;
5. `git diff --check`.

The P4-01 closeout additionally runs the repository's broader affected backend
suite and the section-closeout backcheck. No paid provider, hosted database,
BlueWay deployment, or real-user database is involved.
