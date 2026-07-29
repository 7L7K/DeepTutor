# Changelog

## Unreleased

### Added

- Added private Course-owned manual Flashcards with durable draft/ready/archive
  decks, optimistic card revisions, append-only idempotent review evidence,
  restart-safe due schedules, deterministic Again/Hard/Good/Easy intervals,
  and a 180-day scheduling cap. The `/flashcards` workspace supports manual
  authoring, missed-card requeue, archive/restore, and identity/Course-scoped
  stale-response fencing without provider calls, mastery mutations, browser
  answer caches, or permanent deletion.
- Added durable Course-grounded Practice generation operations with frozen
  source receipts, strict citation and output validation, idempotent new-set
  and successor requests, bounded local-provider execution, restart
  reconciliation, and atomic ready publication. Generated drafts are reserved
  for the server operation, deterministic test indexes are fingerprint-bound,
  and unavailable, timed-out, stale, malformed, or interrupted work remains
  safely failed without publishing partial questions.
- Added the authenticated manual Course Practice API and `/practice`
  workspace: private set/revision/question authoring, immutable ready
  revisions, resumable attempts and history, CAS/idempotent answer saves,
  deterministic submit/grade/results, and archive/restore without deletion.
  Ready questions hide answer contracts until an owned attempt is durably
  graded; browser responses are fenced by identity, Course, and view epoch,
  and no answer or quiz snapshot is persisted in browser storage.
- Added SQLite-authoritative deterministic exact-answer grading for submitted
  Course quiz attempts. Immutable per-item/per-objective evidence binds the
  frozen answer contract, response, objective, result, error classification,
  item result, and aggregate score; a digest-checked outbox projects each
  mapped effect into Course mastery at most once and safely resumes after
  interruption or parent archive. Course learning reset now rejects any
  Course with grading history, and archive or Practice successor replacement
  terminalizes submitted ungraded attempts without deletion.
- Added Course-owned resumable quiz-attempt persistence with immutable
  ready-revision membership, server-authoritative question order, one active
  attempt per Practice set, CAS answer autosave, exact durable idempotency
  receipts, submission/abandonment freeze, and archive/successor
  terminalization without hard deletion.
- Added Course-owned manual Practice authoring persistence with immutable ready
  revisions and questions, successor history, server-resolved source receipts,
  typed answer/citation contracts, archive/restore epochs, and uniform
  owner-and-parent resolution. Generated Practice authority remains reserved
  for the later grounded-generation slice.
- Added the Phase 4 Course-database migration authority: ordered packaged SQL,
  exact-byte SHA-256 receipts, transactional postcondition and foreign-key
  checks, bounded structural drift diagnostics, and fail-closed adoption of
  only the approved Phase 3A Course-only or Course-plus-BlueWay schemas.
- Added deterministic migration proof for fresh and upgraded databases,
  replay, rollback, concurrent threads/processes, semantic schema drift, real
  private-database backup copies, and both full and CLI wheel packaging.
- Added a hermetic Phase 3A BlueWay regression command that exercises the real
  authenticated TEEECHR integration and Course routes against a loopback
  synthetic BlueWay HTTP authority. It proves two-owner isolation, encrypted
  credential persistence across service re-instantiation, remote revocation,
  same-subject reconnect, and non-duplicating Course mapping reuse without
  hosted accounts, devices, or paid providers.
- Added persistent single-host BlueWay secret authority and an owner-approved
  credential-recovery flow. Unreadable credentials now enter a durable
  generation-fenced recovery status; same-subject recovery retains the exact
  connection and Course identities, while a different BlueWay subject is rejected
  and its newly issued grant is revoked.
- Added a recovery Settings state that keeps imported Course material available,
  blocks Sync and Disconnect, and reuses the consent flow without exposing tokens,
  credential references, key IDs, paths, or crypto diagnostics.
- Added the disabled-by-default Phase 3 BlueWay academic-read integration foundation:
  owner-scoped delegated pairing, encrypted rotating credentials, durable sync receipts,
  exact external-course mappings, retained unlinked records, and deterministic immutable
  Course Knowledge bundles without BlueWay write-back or paid provider calls.
- Added a minimal BlueWay Settings surface for connect, pending approval, sync readiness,
  unlinked-record count, local-first disconnect, and revocation retry without exposing
  access or refresh credentials to the browser.
- Added the Phase 2 private Course foundation on the v1.5.2 baseline.
- Added per-profile `courses.db` storage with optimistic revisions, source lineage,
  archive/restore lifecycle, write epochs, crash reconciliation, and no Course
  hard-delete API.
- Added authenticated Course, Course-source, progress-stream, and Course-learning
  endpoints.
- Added immutable Course bindings for chat sessions and persisted Course/source
  provenance on Course user messages.
- Added opaque per-source Knowledge index shards behind each Course's single logical
  Knowledge authority so archived, failed, stale, and superseded sources cannot remain
  searchable through another source's shared index.
- Added a minimal user-scoped Course picker, source attachment controls, Course-aware
  Chat, and explicit no-model learning initialization in the web app.
- Added an explicitly opt-in, local-only deterministic Course provider for CI and
  browser integration proof without paid embedding or model calls.

### Changed

- Course and BlueWay repositories now share one path-scoped schema bootstrap
  and one packaged migration stream. The former independent DDL and replay
  repair paths were removed while normal connections continue to enforce
  foreign keys and SQLite WAL remains the cross-process writer authority.
- Phase 3A is accepted as engineering-complete for the current persistent
  single-host beta boundary. The repeatable owner/revocation/reconnect harness
  and final no-P0-P2 review close the local engineering lane; a second real
  Sign in with Apple owner, current device/browser flow, hosted fixture
  retirement, deployment, and release publication remain separate
  certification gates.
- Serialized same-process BlueWay SQLite schema bootstrap and made replay-index
  creation idempotent, preventing a request/background-worker initialization
  race while preserving the existing unique completed-snapshot replay guard.
- Completed the owner-approved live BlueWay credential recovery on the
  authoritative single-host runtime. The hosted pairing secret was rotated, the
  persistent authority survived a restart without bootstrap inputs, the same
  connection and opaque BlueWay subject were recovered, and one bounded sync
  preserved all Course/source/mapping/record identities while importing only the
  supported academic record categories.
- The live recovery runtime was restarted with the canonical BlueWay approval
  URL (`blueway-teeechr-beta.expo.app`) instead of the obsolete preview
  deployment. A consumed-and-revoked temporary approval was safely retried
  without changing retained learner data.
- Made the mimic-WebSocket test harness install an explicit local test identity,
  so the full suite no longer depends on whether the auth router happened to be
  imported before its isolated config fake.
- Phase 3A closeout repairs now bind every tool batch to the current round's
  authorized schema and reject an unauthorized batch atomically. Course mastery
  turns suppress build/assess actions and require a private, real `ask_user` reply
  receipt; valid no-speech transcripts are omitted; and auth-setting tests no longer
  leak settings state across tests.
- Added a production-shaped, provider-free import-to-Course-Chat proof that imported
  transcript-like instructions remain passive content and cannot acquire tool
  authority. Later receipts close the real transcript transfer and accepted
  engineering boundary; native two-owner browser/device certification and
  hosted fixture retirement remain parked.

- Reconciled the Phase 3 BlueWay checklist with the later hosted, native-consent,
  database-checkpoint, transcription, provider-smoke, and branch-publication
  evidence. Added the Phase 3A closeout and Phase 4 Course-owned Practice/Quiz/
  Flashcards roadmap while explicitly deferring historical learner-data import,
  upstream v1.5.5 integration, and any `main` promotion.

- BlueWay snapshots now preserve opaque `courseId` identity, classroom/room schedule
  text, assignments, notes, course facts, completed capture metadata, and completed
  normalized transcript segments while keeping raw audio, capture location snapshots,
  provider metadata, word timings, speaker/confidence data, credentials,
  profile/location/device data, arbitrary URLs, and unavailable source datasets
  outside the import.
- BlueWay sync stages every changed Course bundle before one generation-fenced SQLite
  visibility commit, retains prior ready Knowledge after failed replacement, archives
  remotely removed material from active retrieval, and permits deterministic retry of
  failed snapshots without losing failed-source provenance.
- Revalidate the current local account and role on every authenticated HTTP request
  and unified WebSocket command, before background turn/source commits, before tool
  execution, and while streaming turn events; disabled, removed, or role-changed
  accounts lose stale authority without waiting for token expiry.
- Account removal now disables and revokes the account while retaining its workspace.
- Admin Course data now uses the admin profile's private personal namespace rather than
  the global administrative workspace.
- Learning-turn cancellation now accepts a real session ID instead of treating a book
  or learning-path ID as a session.
- Cookie-authenticated unsafe browser requests and authenticated WebSocket upgrades now
  validate their Origin.
- Course archive and learning lifecycle changes now fence persisted and still-live turns,
  while Course session creation joins the archive lifecycle lock.
- Browser Course state now rejects stale identity/course responses, excludes archived
  selections, keeps existing generic sessions distinct from new Course drafts, treats
  archived Course transcripts as read-only until restore, and binds WebSocket control
  messages to the persisted session Course.
- Regeneration now validates and persists its replacement turn before removing the
  prior assistant answer, so rejected Course/source provenance leaves history intact.
- Source completion is now published only after the fenced Course database transition;
  staging and authorization failures always leave both the source and operation in a
  terminal failure/cancelled state.
- Source archive now rejects while any Course turn is active, so an in-flight turn cannot
  retain retrieval authority after its attached source becomes archived.
- Learning persistence now uses real optimistic compare-and-swap revisions, rejects
  malformed state instead of overwriting it, and permits explicit Course initialization
  to quarantine corrupt bytes before rebuilding the requested plan.
- Source attachment now requires a database-backed idempotency key, and restart progress
  reconciliation converts abandoned processing rows into a durable terminal failure.
- Ordinary users without a model assignment can still organize Courses, inspect retained
  data, and initialize explicit model-free learning objectives; only model-backed actions
  are disabled.
- Agentic chat now applies existing model temperature capabilities before raw provider
  calls, preventing GPT-5-family Course turns from sending unsupported sampling values.
- Capability/provider exceptions now terminate persisted turns as `failed` instead of
  producing a blank assistant message and a false `completed` status.

### Security and compatibility

- BlueWay now authenticates the encrypted refresh credential before creating a
  rotation receipt or entering `revocation_pending`. Credential failures fence and
  cancel in-flight work without provider calls, preserve the primary grant and
  imported learner data, and require explicit same-account recovery.
- Persistent BlueWay authority uses exclusive fsynced creation plus `0700`/`0600`,
  no-follow, owner, regular-file, and single-link checks. Legacy bootstrap persists
  a key only after all referenced envelopes authenticate; recovery bootstrap is a
  separate explicit operator mode and never overwrites unreadable envelopes.
- BlueWay pairing now uses a dedicated integration header rather than the Supabase `apikey` channel, and provider start/exchange calls no longer hold the global identity lock; current account authority is revalidated before every local commit and a newly issued remote grant is revoked if that commit is no longer authorized.

- BlueWay credentials use AES-256-GCM with owner/connection/provider/scope AAD and
  private no-follow files; connection, refresh, snapshot, Course, source, and background
  commits recheck owner and grant-generation authority and fail closed on account loss,
  disconnect, archive, replay conflict, malformed payloads, and oversized responses;
  browser status/connect results are identity- and request-epoch fenced across logout.
- The integration requires authenticated local JSON/SQLite mode, one process, pinned
  HTTPS endpoints, an explicit server secret and master key, and an operator-enabled
  BlueWay client. PocketBase, multiple replicas, sharing, raw-audio transfer, deployment,
  and hosted-provider proof remain outside this phase.
- Missing and foreign Course resources share the same not-found behavior.
- Generic Knowledge, attachment, history, Book, notebook, memory, and arbitrary KB
  selection cannot grant Course Chat access; Course Knowledge is resolved server-side.
- Course-bound sessions, messages, learning state, and managed Knowledge are hidden from
  generic destructive endpoints.
- Course turns now expose only server-derived RAG plus Course-local mastery tools; generic
  memory, notebook, web, execution, cron, GitHub, and deferred MCP tools cannot be
  auto-mounted from a prompt-injected Course source.
- RAG dispatch now enforces that `kb_name` belongs to the turn's server-attached Knowledge
  set instead of trusting the model-facing schema enum as authorization.
- Private profile directories and Course databases now enforce owner-only host permissions,
  archived Course sessions reject generic metadata writes, and revoked source tasks become
  terminal instead of remaining indefinitely active.
- Private-tree repair now enforces `0700` directories and `0600` files, rejects symlinks,
  hard links, and owner mismatches, removes macOS extended ACLs, and fails closed when a
  permission repair cannot be completed. Its SQLite walk and macOS ACL cleanup tolerate
  only a sidecar that is independently verified to have disappeared during the repair,
  preventing WAL/SHM churn from causing a transient API failure without weakening the
  checks for extant files. Upload and archive extraction use no-clobber, no-follow writes
  and operation-scoped rollback.
- Personal path resolution rejects traversal and symlink escapes. Course mastery resolves
  through the same strict personal profile path for learners and admins, and Course grading
  retries do not duplicate an already-recorded pending-question attempt.
- The local identity registry is written atomically with owner-only permissions and fails
  closed on corruption or duplicate immutable user IDs, preventing accidental first-admin
  bootstrap after identity-store damage.
- Course-source replacement has a database-enforced single-live-successor invariant, source
  archive checks the parent Course state in the same SQL write, and stale Course turn rows
  are reconciled after process restart before archive or learning cancellation decisions.
- Session SQLite upgrades preserve extended notebook columns and category rows, and all
  personal session database files enforce owner-only permissions.
- Startup and Course APIs fail closed when PocketBase is configured because Phase 2 has
  no PocketBase ownership implementation.
- Phase 2 remains single-process/local-storage only. Sharing, multi-server coordination,
  BlueWay, Practice, Flashcards, deployment, and production migration remain deferred.
- Startup now rejects configured multi-worker operation and holds an OS-level process lock
  so the single-process Course lifecycle contract cannot be bypassed accidentally.

### Validation

- Exact-`850e7316` local Phase 3A source/test receipt: backend
  `2862 passed, 6 skipped, 9 warnings`; web node suite `168 passed`; `tsc` pass;
  Next production build with `52` routes; lint `0` errors/`101` warnings; i18n
  parity pass with informational audit findings; Ruff, `git diff --check`, the
  bounded changed-range secret scan, and clean-worktree verification pass. This
  documentation-only superseding receipt follows that five-commit validated tip;
  immutable command/SHA evidence is Linear project comment
  `ffa56940-2ec2-4b56-9e8d-47fdf0b8436d`. No paid/provider call, deployment,
  push, merge, or Phase 3A-complete claim is implied.

- Added deterministic BlueWay protocol, credential-tamper, snapshot-boundary,
  same-title isolation, pairing-pending, replay, reconnect, archive/removal, retry,
  all-or-nothing Knowledge visibility, 50-profile, and concurrent non-provider tests;
  the reviewed hosted migrations and Edge functions now pass two-account pairing,
  owner-isolated sync, revoke/reconnect, process-restart, and concurrent status-read proof.
- A bounded real-provider smoke validated OpenAI `text-embedding-3-small` source indexing
  and a provenance-bound `gpt-5-mini` Course answer without title-generation fallback.
- Added a content-free real-transcript receipt: the owner-bound hosted aggregate
  has `7` non-empty completed transcripts and `2` valid no-speech completions;
  the completed TEEECHR sync retained the `7` searchable records in
  hash-matching private Course bundles, and a post-restart deterministic lookup
  emitted exactly one owner-authorized `blueway-course-bundle.json` citation
  while a foreign profile received none.
- Recorded the newly discovered credential-lifecycle beta blocker: the prior
  runtime kept the local AES master key and local copy of the matching pairing
  secret only in process environment, so its remaining encrypted credentials
  cannot support future sync or server-initiated revoke. The hosted pairing
  secret remains present and any later replacement requires separate approval.
  Phase 3A now requires persistent secret authority, decryptability preflight,
  and a safe owner-approved recovery path before disconnect/reconnect proof.
