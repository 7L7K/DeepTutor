# TEEECHR v1.5.2 Phase 4 Hardening Closeout

Status: **engineering implementation and integrated qualification complete**

Canonical plan:
`docs/TEEECHR_V152_PHASE3A_PHASE4_LEARNING_WORKFLOWS_PLAN.md`

This receipt covers the final security, safety, resource-governance, and
usability pass for the provider-free, private, single-host Phase 4 beta. It does
not authorize a push, merge, deployment, paid provider call, hosted mutation,
historical-data import, or upstream integration.

## Closed risks

### Generation admission and provider truth

- Practice and Flashcard generation share one owner-wide SQLite admission
  decision under `BEGIN IMMEDIATE`.
- New work stops at 4 outstanding operations, 64 retained operations, or 16
  retained generated drafts per owner.
- Exact-key replay is resolved before the ceilings and continues to return the
  original operation even if the provider later becomes unavailable.
- An unavailable provider is reported through authenticated Course capability
  state and rejected before a draft or operation is allocated.
- Provider deadlines cannot create unbounded live work: Practice and Flashcards
  share four process-wide execution permits, and a timed-out provider keeps its
  permit until the underlying call actually exits.
- Course, owner, state, revision, and write-epoch checks remain server
  authority; the browser cannot name a provider, Knowledge Base, source set, or
  owner.

### Assessment retention and write amplification

- One Practice set retains at most 100 attempts.
- One attempt retains at most 2,048 autosave receipts and 2 MiB of autosave
  response JSON.
- One attempt retains at most 4,096 grading-evidence rows and 2 MiB of grading
  JSON.
- One Flashcard deck retains at most 10,000 reviews.
- Repository checks provide safe product errors and additive migration `0007`
  adds database-level backstops. Existing evidence is never deleted.
- Attempt and deck history are returned in pages of 50, with a maximum requested
  page size of 100.

### Mastery projection and learning-plan integrity

- A grading projection builds and validates its complete evidence plan before
  inserting any new evidence.
- One attempt projection performs one Course-learning save and one SQLite batch
  acknowledgement transaction, avoiding a save-and-rewrite cycle for every
  objective.
- Course learning initialization rejects a non-identical replacement after
  grading evidence exists, including retained SQLite evidence that has not yet
  appeared in the learning file.
- An exact plan replay remains a no-op. Generic learning routes cannot mutate
  Course-derived learning-path IDs.

### Source lifecycle and learner-facing honesty

- The Course UI exposes processing, ready, failed, and archived source state and
  polls only while work is processing.
- A failed source can be replaced by creating a new immutable source with
  `supersedes_source_id`; it is never rewritten in place.
- Ready sources can be archived through the Course-owned API with their expected
  revision.
- Generated learner actions are hidden or disabled when generation is
  unavailable. The model-free “Explain simpler” action remains available.
- Practice attempts and Flashcard decks have bounded “load more” history, and
  newly added controls have visible labels and status/alert semantics.

## Security invariants retained

- Every lookup begins with the current authenticated account and private Course.
- Foreign and missing Course children use the same non-enumerating `404`.
- Admin role does not grant access to another learner’s Course database.
- Archived Courses and stale write epochs cannot start or commit new work.
- Browser state is fenced by immutable identity, Course, and request/view epoch.
- Client titles, filenames, source labels, operation IDs, and external labels
  never become ownership authority.

## Qualification matrix

Before this receipt may be marked complete, all of the following must pass from
the exact final worktree:

1. migration fresh replay, exact legacy adoption, checksum replay, and
   concurrent startup;
2. generation governance, provider-unavailable, exact replay, cross-feature
   concurrency, and source-authority tests;
3. assessment ceilings, pagination, grading projection, mastery idempotency,
   and learning reinitialization tests;
4. all affected backend Course/Practice/Flashcard/learning tests;
5. all web node tests and TypeScript;
6. the hermetic authenticated browser proof across a real backend restart;
7. Ruff, `git diff --check`, changed-range secret review, and the repository
   section closeout backcheck;
8. an independent read-only security review with no unresolved P0-P2 finding.

The exact counts and any remaining unproved surfaces must be recorded only
after those commands finish.

## 2026-07-29 qualification receipt

Current verdict: **PASS**

Passed on the final hardening worktree:

- 460 Course and learning tests, excluding only the separately executed
  wheel-packaging test;
- 65 focused provider, replay, timeout, learner-action, learning-integrity,
  source-lineage, and repository tests;
- 192 web node tests;
- TypeScript, ESLint with no errors, changed-Python Ruff, `git diff --check`,
  and a bounded high-confidence secret scan;
- the isolated root and CLI wheel-packaging test, using the machine's local
  offline build-dependency wheelhouse, proving both wheels contain migration
  `0007`;
- the hermetic authenticated browser campaign: two private owners and Courses,
  a real backend restart, identity and cache isolation, persisted quiz and
  learning state, provider-free manual Practice grading, provider-unavailable
  UI, and a complete Flashcard review;
- independent final review with no unresolved P0-P2 finding.

The Next.js production build passed all 54 static pages on the reviewed
hardening tree before the final browser-found score-format and locator-only
delta. A final sandbox retry could not finish because Google Fonts were
unreachable and Turbopack's offline fallback attempted a prohibited internal
port bind. The final delta passed TypeScript, ESLint, all web node tests, and the
complete rendered browser campaign. This is recorded as an environment note,
not a product failure or an unproved user flow.

The previously authorized local commit packaging may proceed. Push, merge,
deployment, and release publication remain separately gated.

## Deferred release surfaces

- Real or paid generation providers.
- Hosted BlueWay or production data changes.
- Native Apple/device certification and hosted fixture retirement.
- Multi-server coordination and production capacity.
- Historical learner-data import.
- Upstream DeepTutor integration.
- Push, merge, deployment, and release publication.
