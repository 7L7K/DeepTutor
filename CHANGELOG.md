# Changelog

## Unreleased

### Added

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

- Phase 3A closeout repairs now bind every tool batch to the current round's
  authorized schema and reject an unauthorized batch atomically. Course mastery
  turns suppress build/assess actions and require a private, real `ask_user` reply
  receipt; valid no-speech transcripts are omitted; and auth-setting tests no longer
  leak settings state across tests.
- Added a production-shaped, provider-free import-to-Course-Chat proof that imported
  transcript-like instructions remain passive content and cannot acquire tool
  authority. This is local proof only: a current real BlueWay export/sync-to-
  CourseSource/citation receipt, browser isolation, revoke/reconnect, fixture
  cleanup, and final Phase 3A closeout remain open.

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

- Current local Phase 3A receipt: backend `2861 passed, 6 skipped, 9 warnings`;
  focused repaired suite `119 passed`; web node suite `168 passed`; `tsc` pass; Next
  production build with `52` routes; lint `0` errors/`101` warnings; i18n parity
  pass with informational audit findings; Ruff and `git diff --check` pass; and an
  independent review found no P0-P2 issue. No paid/provider call, deployment, push,
  merge, or Phase 3A-complete claim is implied.

- Added deterministic BlueWay protocol, credential-tamper, snapshot-boundary,
  same-title isolation, pairing-pending, replay, reconnect, archive/removal, retry,
  all-or-nothing Knowledge visibility, 50-profile, and concurrent non-provider tests;
  the reviewed hosted migrations and Edge functions now pass two-account pairing,
  owner-isolated sync, revoke/reconnect, process-restart, and concurrent status-read proof.
- A bounded real-provider smoke validated OpenAI `text-embedding-3-small` source indexing
  and a provenance-bound `gpt-5-mini` Course answer without title-generation fallback.
