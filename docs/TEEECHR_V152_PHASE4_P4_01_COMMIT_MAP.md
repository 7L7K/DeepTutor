# TEEECHR v1.5.2 Phase 4 P4-01 Commit Map

Status: **planned; no Phase 4 implementation commit exists**

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

## Commit 2 — Add P4-01A migration kernel

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

## Commit 3 — Add P4-01B baseline adoption

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

## Commit 4 — Add P4-01C single bootstrap authority

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

## Commit 5 — P4-01 closeout

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

Every commit must leave the repository green and independently reviewable. Do
not collapse the sequence into one large database-foundation commit.
