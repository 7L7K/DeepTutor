# TEEECHR v1.5.7 Upstream Integration Plan

Status: integrated and locally beta-qualified (`PASS_WITH_PARKED_FOLLOWUPS`)
Target upstream: DeepTutor `v1.5.7` / `740ec413`
Source TEEECHR snapshot: `b8130e7f`
Shared base: `b7283548`
Integration branch: `feature/teeechr-v157-integration`
Integration commit: `c55d1e1a58c73f042794c00b7da182ff63090710`

The exact beta certification is recorded in
`docs/TEEECHR_V157_BETA_CERTIFICATION.md`. Historical learner migration and the
next advanced learner feature are separate follow-on contracts; neither was
silently included in the upstream merge.

## Goal

Create an upstream-based TEEECHR integration branch that retains DeepTutor
v1.5.7 improvements and preserves every reviewed TEEECHR ownership, Course,
BlueWay, Practice, Flashcard, learning, provider, accounting, and learner
experience contract. Qualification must distinguish source, automated tests,
database replay, local runtime, browser, provider, hosted, and release proof.

## Non-goals

- Do not update `origin/main` or `fork/main`.
- Do not merge the historical v1.3.7-era fork main.
- Do not deploy or publish a release.
- Do not migrate historical learner data.
- Do not mutate BlueWay hosted data or the recovered primary grant.
- Do not make paid-provider calls without a new explicit capped authorization.
- Do not add advanced learner features during integration.

## Integration method

Use a normal two-parent merge on a branch created from `origin/main`, but treat
the merge as an explicit reconciliation operation rather than accepting Git's
textual result as authority:

1. Create `feature/teeechr-v157-integration` at `740ec413`.
2. Merge `feature/teeechr-v152-phase5-course-study-intelligence` with commit
   creation paused.
3. Resolve the eight predicted textual conflicts against the contracts below.
4. Semantically review all 25 auto-merged overlap paths.
5. Review every newly carried non-overlap path for imports, migrations,
   registrations, packaging, and capability gates.
6. Validate the uncommitted merge tree before creating the integration commit.
7. Commit only after required local proof passes.
8. Push the integration branch for review; do not merge either main branch.

This method retains both histories and automatically carries non-overlapping
TEEECHR files while keeping the eight actual conflict decisions visible. It is
not permission to select `ours` or `theirs` wholesale.

## Conflict contracts

### 1. README

Keep upstream v1.5.7 release history. Retain the supported Node runtime guidance
and TEEECHR-specific development notes without describing local beta proof as
an upstream or production release.

### 2. Chat agentic pipeline

Compose upstream RAG coexistence and inventory answers with the TEEECHR
Course-turn resolver. Course mode may use only the authenticated Course-managed
ready sources selected by the server. Client-supplied KB names, generic Books,
and arbitrary attachments must not widen access.

### 3. Multi-user paths

Adopt upstream path additions while retaining the strict immutable-user Course
workspace resolver. Admin role must never redirect personal Course data into a
global or development-admin workspace. Ownership failures never fall back.

### 4. Model catalog

Add upstream Codex OAuth/provider definitions to the central typed registry.
Retain Luna-low for Chat and Luna-medium for Practice/Flashcards, exact
requested/actual model recording, versioned pricing authority, encrypted
credential resolution, and dormant rollback definitions. Provider display
names and client choices are never authority.

### 5. Turn runtime

Retain upstream batching, generated-file activity, and post-stream completion
fixes. Preserve Course/session immutability and re-resolve account, Course,
source revisions, operation, and write epoch for every WebSocket command and
immediately before background commits. Reconnect, subscribe, cancel, resume,
and regenerate must fail closed on mismatch.

### 6. Model-catalog tests

Combine both provider suites. Add explicit assertions that upstream provider
additions cannot replace active TEEECHR bindings, erase pricing receipts, or
activate dormant rollback models.

### 7. Workspace home page

Retain upstream workspace behavior while preserving General Chat versus Course
mode, Course selection, Course source controls, and learner actions. Identity
changes must clear Course-scoped browser state. No internal IDs or BlueWay
implementation terminology should become learner-facing.

### 8. Unified Chat context

Keep upstream unique optimistic IDs and generating-state fixes. Retain immutable
session/Course binding, identity/request epochs, stale-response discard,
Course-aware reconnect/control messages, and Course-derived resource authority.

## Implementation slices

### Slice I0 — authority and merge scaffold

- Prove source and target commits, clean worktree, remotes, and branch.
- Create the integration branch from `origin/main` at `740ec413`.
- Record the merge-tree receipt and conflict list.
- Start the no-commit merge.

Exit: only the eight predicted conflicts are unresolved; no unrelated or
generated files exist.

### Slice I1 — identity, paths, auth, and storage

- Reconcile `auth.py`, `multi_user/paths.py`, `path_service.py`,
  `knowledge_access.py`, PocketBase boundaries, and related tests.
- Preserve disabled/deleted/demoted-account enforcement.
- Preserve separate private workspaces for two users and two admins.
- Preserve foreign-resource indistinguishable `404` behavior.

Exit: focused identity, PathService, Course ownership, and PocketBase rejection
tests pass.

### Slice I2 — sessions, Chat, RAG, and WebSockets

- Resolve agent pipeline, protocol, stores, turn runtime, main router wiring,
  and Chat context conflicts.
- Compose upstream RAG and event batching with Course provenance.
- Preserve reconnect/cancel/resume/regenerate ownership checks.

Exit: generic Chat and Course Chat both pass; all cross-user/session/Course
adversarial tests pass.

### Slice I3 — provider, settings, and usage authority

- Reconcile model catalog, provider runtime, agentic client, settings APIs,
  tool registry, and tests.
- Import upstream Codex OAuth without weakening encrypted study credentials or
  versioned accounting.
- Keep provider resolution and qualification no-call by default.

Exit: catalog, provider-runtime, credential-redaction, budget, and requested /
actual-model tests pass without a provider call.

### Slice I4 — Knowledge and BlueWay

- Reconcile upstream Knowledge engines/inventory with Course-managed Knowledge.
- Carry BlueWay delegated connection, mapping, sync ledger, immutable source
  ingestion, transcript omission/tombstones, recovery, and isolation.
- Preserve the recovered primary connection; use fakes for integration tests.

Exit: Knowledge lifecycle, BlueWay hermetic lifecycle, source replacement,
revocation, and foreign-ID tests pass.

### Slice I5 — Practice, Flashcards, learning, and mastery

- Carry Course schema/migrations, manual and generated Practice, Flashcards,
  grading, mastery, General Study, scheduling, remediation, and learner actions.
- Reconcile any upstream quiz-card behavior without changing immutable grading
  evidence or Course ownership.

Exit: complete Course backend, database replay, Practice, Flashcard, mastery,
and provider-free generation tests pass.

### Slice I6 — frontend and product shell

- Resolve workspace, composer, messages, sidebar, settings navigation, Course
  shell, Practice, Flashcards, BlueWay settings, and identity-namespaced caches.
- Preserve upstream features unless there is a reviewed product-shell decision.
- Do not use integration as a branding redesign.

Exit: TypeScript, Node tests, focused lint, responsive browser journeys, and
two-user cache isolation pass.

### Slice I7 — packaging, startup, and build

- Start from upstream v1.5.7 packaging and launcher behavior.
- Reconcile upstream automatic `npm ci` recovery with TEEECHR's supported Node
  22/24 guards so unsupported runtimes fail before mutating package metadata.
- Validate Python packaging, source startup, restart, `npm ci`, TypeScript, and
  the 54-or-current-route production build under Node 22 or 24.

Exit: clean startup and shutdown leave the worktree unchanged; build exits
successfully; no local paths or secrets enter tracked configuration.

### Slice I8 — qualification and integration commit

- Run the full affected Python, SQL, Node, type, lint, shell, diff, and secret
  gates.
- Run fresh and upgrade database replay in disposable stores.
- Run authenticated browser journeys for two private users and multiple
  Courses across Chat, BlueWay status fakes, Practice, Flashcards, learning,
  archive/restore, logout/login, and restart.
- Review staged and unstaged state and create the integration commit only if
  the exact tree passes.
- Push the integration branch for review.

Exit: local integration verdict is `PASS` or
`PASS_WITH_PARKED_FOLLOWUPS`; production release remains closed.

## Required regression matrix

| Surface | Minimum proof |
| --- | --- |
| Auth | delete/disable/demotion on next HTTP and WS operation; Origin rejection |
| Paths | two users and two admins receive distinct private Course roots |
| Course | create/list/read/archive/restore, revisions, restart, no hard delete |
| Sources | immutable ready source, replacement lineage, failed ingestion, stale worker denial |
| Sessions | immutable Course binding across all WS control operations |
| Knowledge | server-derived Course resources; foreign IDs and arbitrary KB names denied |
| BlueWay | hermetic pair/sync/revoke/recover, no cross-owner export or duplicate source |
| Practice | manual/generated, resume, exact grading, citations, remediation, history |
| Flashcards | Course/General Study, conversation-drafted provenance, generation review, study |
| Learning | deterministic Course learning path, mastery persistence, correct cancellation ID |
| Provider | no-call resolution, encrypted credential, budget fences, uncertain accounting |
| Frontend | identity cache reset, Course switching, generic Chat, responsive study flows |
| Runtime | supported startup and build leave tracked metadata unchanged |

## Proof boundaries after local qualification

Even a green integration branch does not prove:

- a deployed backend or website;
- a packaged desktop/mobile artifact;
- a real second Apple/BlueWay identity;
- production secrets or hosted migrations;
- historical learner-data import;
- multi-server coordination;
- a paid Luna response on the integrated tree;
- release readiness or a canonical-main decision.

Those remain subsequent roadmap gates.

## Rollback

- The v1.5.2 TEEECHR feature branch remains preserved locally and on the fork.
- `origin/main` and `fork/main` remain unchanged.
- The integration branch can be abandoned without altering either authority.
- No migration or hosted mutation is allowed during integration construction.

## Plan verdict

`PASS`

The target, overlap set, conflict contracts, implementation slices, proof
matrix, rollback, and authority boundaries are specific enough to create the
v1.5.7 integration branch without guessing. The next action is Slice I0.

## Integration execution receipt — 2026-08-01

### Branch and parents

- Integration branch: `feature/teeechr-v157-integration`
- Upstream parent: `origin/main` at `740ec413` (`v1.5.7`)
- TEEECHR parent: `feature/teeechr-v152-phase5-course-study-intelligence`
  at `b8130e7f`
- `origin/main`, `fork/main`, BlueWay, hosted services, and learner data were
  not modified.

### Conflict resolution

The predicted eight-path conflict set was exact. Resolution retained:

- upstream RAG manifests, context budgeting, atomic model-catalog writes,
  session snapshots, optimistic assistant-message reconciliation, and the
  current workspace shell;
- TEEECHR immutable-user Course ownership, current-account revalidation,
  Course provenance, BlueWay delegated sources, Practice, Flashcards,
  General Study, mastery receipts, encrypted provider authority, and
  provider accounting;
- Node 22/24 development guards that reject unsupported runtimes before an
  upstream startup path can rewrite package metadata.

No unresolved index entries remain. Follow-up test repairs made generic
runtime tests independent of operator provider policy, made the HTTP auth
fixture independent of HTTPS deployment cookies, asserted the effective
ranked BlueWay record rather than its discarded bundle envelope, and replaced
stale migration-count literals with the packaged migration manifest count.

### Local qualification

All validation below used local or disposable storage and made no paid model
call:

| Surface | Result |
| --- | --- |
| Conflict Python compilation | Pass |
| Focused session, identity, and provider seams | 113 passed |
| Course core | 110 passed |
| Practice and Flashcards | 218 passed |
| BlueWay integration | 79 passed |
| Learning and mastery | 245 passed |
| Migration replay, concurrency, and package contents | 23 passed |
| Frontend Node tests | 416 passed |
| TypeScript | Pass |
| Diff whitespace check | Pass |
| Targeted secret-pattern scan | Pass |

The earlier monolithic backend run was stopped after 417 passing tests because
it obscured suite progress. The same affected surfaces were then split into
the bounded suites above; their three exposed regressions were repaired and
the complete split matrix passed.

### Integration verdict

`PASS_WITH_PARKED_FOLLOWUPS`

The source integration is qualified for a remote review snapshot. Beta
release certification remains a separate gate and must still prove supported
startup/restart, production build termination, authenticated browser journeys,
provider-off behavior, exact runtime identity, and a final clean-worktree
receipt. Historical learner-data migration remains design-only until its own
approved rehearsal and rollback contract.
