# TEEECHR v1.5.2 Phase 4 P4-01 Commit Map

Status: **P4-01 implemented locally; no push, merge, or deployment**

Starting point: local accepted commit
`af5eab79ec7b918242b228de67af358944323fd9`

No push, merge, deployment, hosted mutation, or BlueWay source change is
authorized by this map.

## Branch gate

Create the Phase 4 branch from the exact accepted starting commit only when
implementation begins. Record the branch name and base SHA in the canonical
Phase 4 plan. A remote checkpoint is recommended for durability but requires
separate user approval; local planning does not authorize a push.

## Commit 1 — Define the migration contract and manifest

Ownership:

- Phase 4 database contract
- machine-readable Phase 3A manifest
- P4-01 test specification

Exit gate:

- JSON parses;
- manifest matches fresh current Course-only and Course-plus-BlueWay fixtures;
- documentation contains no competing P4-01 sequence.

## Implemented commit 2 — P4-01A/B/C atomic database authority

Actual commit: `1cc75f2f`

The planned commits 2 through 4 were intentionally delivered as one atomic
green commit. The migration runner, approved baseline, repository cutover, and
their tests form one bootstrap authority; splitting them would have created
intermediate commits where production repositories and validation fixtures
disagreed about which schema path was authoritative.

### P4-01A migration kernel

Ownership:

- exact artifact discovery and ordering;
- ledger;
- exact-byte checksum enforcement;
- transaction runner;
- foreign-key verification;
- per-database lock integration;
- rollback, tamper, unknown-receipt, and concurrency tests.

Exit gate:

- focused P4-01A tests pass;
- no domain table other than `schema_migrations` is newly designed;
- existing Course/BlueWay behavior remains green.

### P4-01B baseline adoption

Ownership:

- `0000_phase3a_baseline.sql`;
- structural manifest comparator and bounded diff;
- empty, Course-only, and Course-plus-BlueWay classification;
- data-preservation and fresh/upgrade convergence tests.

Exit gate:

- exact known profiles converge;
- unknown or partial profiles fail before modification;
- domain row digests and identity sets remain unchanged;
- the BlueWay replay guard remains effective.

### P4-01C single bootstrap authority

Ownership:

- route fresh Course database creation through migrations;
- remove Course and BlueWay independent DDL/repair paths;
- make both repositories consume the migrated schema;
- repeated/restart/concurrent bootstrap tests.

Exit gate:

- exactly one managed-schema authority remains;
- normal connections enable and verify foreign keys;
- repeated startup performs no schema write;
- affected legacy tests pass.

## Commit 3 — P4-01 closeout

Ownership:

- changelog and plan ledger;
- complete affected validation receipt;
- independent security/data-lifecycle review;
- tracked, untracked, generated, credential, and database-state audit.

Exit gate:

- P4-01A/B/C definitions of done pass;
- no unresolved P0-P2 finding;
- no Practice, attempt, grading, Flashcard, API, UI, provider, or hosted work
  entered the slice;
- push/merge decision is explicit.

Every committed state remains green and independently reviewable. The
implementation is atomic for the authority-boundary reason above; later Phase
4 slices return to one behavior slice per reviewed local commit.
