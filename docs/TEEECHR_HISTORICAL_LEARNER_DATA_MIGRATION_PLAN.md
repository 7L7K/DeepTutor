# TEEECHR Historical Learner-Data Migration Plan

Date: 2026-08-01
Status: zero-write classifier and authenticated review UI implemented; reviewed
apply remains locked
Historical source authority: `DeepTutor` branch
`safety/teeechr-pre-v152-20260720` at `3c2d5a47`
Target authority: the per-user Course database and learning store on
`feature/teeechr-v157-integration`

## Goal

Provide a deterministic, privacy-safe path for a learner to bring eligible
historical sessions, Practice attempts, Flashcard decks, cards, and review
history into the new immutable-user Course model without guessing ownership,
Course membership, source provenance, or mastery authority.

The first deliverable is a zero-write classifier and review report. Import is a
separate, explicitly authorized operation.

## Why direct copy is unsafe

The historical store and current Course store encode different authority:

| Historical record | Historical authority | Required target authority |
| --- | --- | --- |
| Session | `tester_id`, session ID | immutable `owner_user_id`; optional reviewed Course binding |
| Practice attempt | tester + session + serialized quiz | owner + Course + Practice set + immutable ready revision |
| Practice item | attempt + question text/answer | immutable question revision, answer row, grading evidence |
| Flashcard deck | tester + topic/KB names | owner + destination workspace + explicit provenance mode |
| Flashcard card | deck + front/back/source text | immutable deck binding, ordinal, citations/provenance |
| Flashcard review | deck/card + rating/time | owned card + durable review state/history |
| Learning/mastery | legacy learning-path files | `lp_<course_id>` and verified objective identity |

Names, titles, filenames, KB names, browser cookies, display text, and the
historical default tester ID are never sufficient ownership or Course evidence.
They may help a human recognize a record, but they cannot authorize an import.

## Immutable inputs

A migration campaign freezes:

- source checkout commit and migration-tool version;
- source database SHA-256, size, and SQLite schema fingerprint;
- source database opened with `mode=ro` and `PRAGMA query_only=ON`;
- target owner immutable user ID;
- target Course IDs and their current revisions/write epochs;
- a user-reviewed identity map and destination map; and
- a campaign ID and manifest hash.

No raw prompt, answer, transcript, or learner text belongs in logs or the
machine-readable campaign summary.

## Classification contract

Every legacy parent and child receives exactly one classification:

### `importable`

The user explicitly confirmed the source identity and destination. All required
parents exist, child relationships are intact, and the conversion is
deterministic.

### `ambiguous`

The record may belong to the learner, but ownership, Course destination,
provenance, objective identity, or chronology is not strong enough to decide.
It requires explicit user review and is never imported by default.

### `orphaned`

A required parent is absent or inconsistent, such as a Practice item without
its attempt, a card without its deck, or a review without its card.

### `duplicate`

An equivalent record is already represented by a prior migration receipt. The
receipt key must use the campaign/source fingerprint plus stable legacy table
and primary key; titles and content alone are not authority.

### `rejected`

The record violates the target contract, is malformed, crosses owners, depends
on an unsupported state, or would require fabricated provenance/mastery.

## Destination policy

### Sessions and messages

- Import only after immutable source-owner confirmation.
- Preserve historical timestamps and source IDs in a migration provenance
  envelope; allocate new target IDs.
- Leave the session Course-less unless the user explicitly maps it to a Course.
- A later Course association creates a reviewed derivative; it does not rewrite
  the historical session as originally Course-bound.

### Practice

- Convert one eligible historical quiz snapshot into a manual Practice set and
  one immutable ready revision in the chosen Course.
- Convert attempts and item responses only when the full question/answer
  relationship is intact.
- Preserve the historical score as imported history, not as new authoritative
  exact-v1 grading evidence.
- Do not update current Course mastery from a legacy score. Mastery requires a
  new target-native attempt or a separately reviewed evidence-import contract.
- In-progress historical attempts default to `ambiguous`; do not silently
  resume them under a new revision contract.

### Flashcards

- Import eligible decks as manual, conversation-drafted, or legacy-imported
  provenance; never label them Course-grounded merely because an old KB name
  resembles a Course source.
- The user may choose General Study or an existing Course as the destination.
- Preserve front, back, hint, tag, ordering, and safe legacy source label.
- Import review events only when deck/card lineage is complete. Rebuild current
  scheduling state deterministically from the ordered events using the target
  scheduler version recorded in the receipt.
- Imported General Study reviews never affect Course mastery.

### Learning and mastery

- Do not map a legacy book/path to `lp_<course_id>` by title.
- Import modules/objectives only through an explicit reviewed objective map.
- Default legacy mastery, error records, and review queues to archival evidence,
  not live Course authority.
- A future evidence-import lane may promote reviewed records, but it needs its
  own algorithm/version receipt and rollback contract.

## Dry-run output

The zero-write command should produce:

```text
campaign_id
source_commit
source_database_sha256
source_schema_fingerprint
target_schema_version
target_owner_designation
counts_by_table_and_classification
relationship_failures_by_safe_code
proposed_destinations_by_opaque_id
required_user_decisions
manifest_sha256
```

The human report may show user-recognizable titles only in the authenticated
local review UI. Exported logs and test fixtures use opaque designations.

## Reviewed apply contract

Apply remains unavailable until the user approves the exact dry-run manifest.
When implemented, it must:

1. revalidate the current account and target Course/write epochs;
2. confirm the source fingerprint and approved manifest are unchanged;
3. copy the source database to a read-only campaign snapshot;
4. transact one parent aggregate at a time;
5. write a migration receipt before exposing the aggregate as ready;
6. be idempotent across interruption and retry;
7. fail closed rather than select a default/admin workspace; and
8. finish with a second zero-write comparison report.

No hard delete, source rewrite, or implicit merge is permitted.

## Rollback

Imported aggregates carry a campaign ID. Rollback archives only the aggregates
created by that campaign and leaves pre-existing target data untouched. Because
the product is archive-only, rollback does not erase source history or break
receipt lineage. Restoring a rolled-back campaign requires a new reviewed apply
decision.

## Required tests before apply exists

- two users with identical titles cannot cross-map or collide;
- the historical default tester ID cannot select an owner automatically;
- ambiguous and orphaned rows remain zero-write;
- retry after interruption creates no duplicate parent or child;
- a stale Course write epoch aborts before commit;
- foreign Course and owner mappings return a safe denial;
- archived target Courses reject new import work;
- legacy scores do not mutate current mastery;
- legacy KB names cannot create Course-grounded provenance;
- review reconstruction is deterministic across restart;
- rollback archives only the campaign-created aggregates; and
- dry-run reports contain no credential, raw answer, transcript, or private
  path disclosure.

## Implementation slices

1. Build a read-only source adapter and schema fingerprint validator.
2. Build the classification engine and machine-readable manifest.
3. Build the authenticated local review UI for identity and destination maps.
4. Add disposable old/new fixture databases and adversarial tests.
5. Run a zero-write dry run against the real historical store with only counts
   and safe designations in the evidence report.
6. Review the manifest with the user.
7. Only then implement and authorize reviewed apply and archive rollback.

## Zero-write implementation receipt

The first five slices are implemented on
`feature/teeechr-historical-migration-dry-run`:

- server-owned source discovery with no browser-supplied filesystem path;
- SQLite `mode=ro`, `query_only`, `trusted_schema=OFF`, integrity checking, and
  before/after source hashing;
- opaque historical-owner selection and authenticated destination validation;
- deterministic `importable`, `ambiguous`, `orphaned`, `duplicate`, and
  `rejected` counts with campaign and manifest hashes;
- an authenticated Settings > Historical Data review screen; and
- fixture, API, client-contract, build, and real-source zero-write proof.

The real preserved local source was recognized as compatible and exposed seven
opaque owner profiles. The most active profile's no-destination report counted
82 session/message records as importable and 84 Practice/Flashcard records as
ambiguous because the learner has not yet selected target workspaces. It found
no orphaned, duplicate, or rejected records in that profile. No legacy text,
raw ID, username, title, path, credential, Course database, mastery state, or
historical source bytes were returned or changed.

## Current decision

The learner may now review the zero-write report. Actual copy/apply, receipt
persistence, idempotent retry, archive rollback, and post-apply comparison are
still unavailable. Implementing those mutation surfaces requires a separate
explicit approval of the reviewed manifest and destinations. Until then, this
phase makes no historical, Course, Flashcard, Practice, or mastery writes.
