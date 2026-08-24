# Changelog

## Unreleased

- Added the Day 5 runtime-data backup/restore boundary. The explicit utility
  creates a manifest-verified archive of one stopped `data/` tree, rejects
  symbolic links, hard links, and special files, excludes the ephemeral Course
  process lock, and restores into a validated staging tree. Replacing a
  non-empty target requires `--replace` and preserves the prior tree beside the
  restored one for recovery. Added isolated round-trip, lock, and private-tree
  safety tests.

- Hardened the school-ready learner Course loop for provider-off use. Active
  Course Chat now discloses when answers are general, processing, failed, or
  partially grounded without hiding the Chat surface. A learner can create and
  recover the first manual Practice draft, including after reload or an
  ambiguous revision-creation response; known revisions must finish opening or
  expose Retry before draft recovery is offered. Materials polling is
  serialized, preserves actionable failures, and rejects stale responses.
  Flashcards keeps manual decks usable when optional generation support or deck
  details fail, hides unpublished generated shells, and prevents stale support
  responses from stealing a newer deck selection. Capability checks now fail
  closed initially, preserve confirmed access during background refresh, expose
  retryable failures, and do not discard an unsent Chat draft.

- Restricted assigned-learner Partner consultations to a fail-closed delegated
  boundary. Caller provenance, live assignment, model shareability, and
  per-learner session identity are revalidated before Partner work; owner-bound
  model profiles and owner/global memory, management commands, host execution,
  cron, GitHub, notebooks, MCP/deferred tools, and other unreviewed capabilities
  are unavailable to assignees while direct owner behavior remains compatible.
  Added a disposable Day 3 browser campaign for two-user Course/source/study
  isolation, provider-off repair presentation, deterministic-local grounding,
  cold process restart, zero paid-provider usage, source identity, and
  cleanup-before-sentinel evidence.

- Kept normal learner chat from requesting deployment-wide subagent settings.
  The composer now reads only an authenticated, learner-safe consult-budget
  projection while backend models, prompts, and execution permissions remain
  admin-only.

- Hardened the school-ready multi-user boundary around subagents and Partners.
  Subagent execution policy now always resolves from deployment-owned settings,
  Partner assignments are revalidated whenever a saved connection is listed or
  used, host-local CLI connections cannot be assigned to or activated by a
  learner, and missing authenticated request context now fails closed instead
  of inheriting local-administrator authority. Learner-safe Partner discovery
  remains available while management deep links stay administrator-only.

- Restricted learner Knowledge Base configuration to existing, writable bases
  and reviewed retrieval fields, with learner-safe read/write responses that do
  not expose stored paths or connector credentials. Host-folder and external
  connector workflows are now administrator-only, generic grants exclude live
  connected resources, and legacy learner pointer metadata remains inert. The
  browser now hides those deployment controls unless administrator status is
  confirmed. Legacy `/settings/mcp` links now carry learners to the account-safe
  `/space/mcp` surface while the deployment registry remains administrator-only.
  Added a disposable learner/admin browser campaign that records the safe
  projections, denied admin surfaces, route gates, and browser errors without
  touching real account data.

- Added the learner Course surfaces for local-first beta qualification: distinct
  Overview, Practice, Flashcards, and Materials flows; Course-grounded quiz and
  flashcard creation; editable learner cards; and admin-only navigation and
  deployment-wide Knowledge settings. Course migration `0019` records learner
  flashcard edits while preserving generated-card provenance.

- Added the TEEECHR hosted VPS operating map and 2026-08-12 beta receipt,
  documenting the DigitalOcean/Caddy/Docker topology, persistent data boundary,
  deployment-owned provider model, source-to-release workflow, security posture,
  qualification evidence, and remaining remote source-control closeout.
- Added the ELI5 TEEECHR change workflow defining local edits, commits, GitHub
  pushes, pull requests, `main`, exact-SHA deployment, hosted verification, and
  the rules that keep those boundaries separate.
- Documented the existing pre-commit recipe, current local-hook/CI coverage,
  and the explicit manual production gates; future hook and deployment-workflow
  automation remains a separate implementation lane.

- Added a compatibility bridge for BlueWay observability migration `0018`.
  The bridge upgrades `0017` databases, preserves pre-observability behavior,
  and can hydrate connection rows after the full observability release has
  written a trace value. Applying `0018` establishes this bridge as the minimum
  supported rollback floor; pre-`0018` binaries cannot reopen an upgraded
  database.

- Hardened Docker publication so each amd64 and arm64 artifact is built once,
  verified by immutable digest, checked for release identity and attestation
  structure, and assembled into public tags only from the verified manifest.
  Release runs are serialized, version tags share the PyPI normalization
  contract, and lifecycle status/failure events preserve durable
  `revocation_pending` and concurrently cancelled states.

- Added failure-isolated, privacy-bounded BlueWay lifecycle observability from
  pairing through Course launch, with durable safe correlation references and
  migration support. Pairing replay now retries a stranded initial sync,
  binds to the exact connection that approved it, and cannot affect a later
  replacement account. Lifecycle events now survive the production logging
  default, preserve release and request correlation, and agree with durable
  cancellation, expiry, recovery, revocation, launch, and sync-deduplication
  states. Migration startup is serialized across processes with a private
  sidecar lock without rolling back earlier committed versions when a later
  migration fails.

- Hardened mobile TEEECHR sign-in with whitespace-safe email matching and
  mobile input attributes, added server-only privacy-bounded login diagnostics
  with a safe attempt reference header, and added accessible show/hide controls
  to login and registration password fields. Public authentication failures
  remain generic and credentials, hashes, tokens, cookies, and caller-supplied
  correlation IDs are never logged.

- Added dedicated `/connect/blueway` and `/connect/blueway/complete` routes for
  same-phone BlueWay pairing. The TEEECHR page now makes the native app handoff
  primary, keeps QR behind an explicit cross-device disclosure, validates the
  completion request server-side, and fails closed for malformed links.

- Fixed the pairing recovery path so browser approval polling cannot overlap.
  Pending requests now expose an explicit Stop pairing action, terminal requests
  expose Redo connection, and completion-race errors explain when the server is
  safely finishing the previous approval instead of leaving the page in a
  misleading pending state.

- Fixed BlueWay workspace reactivation to require a current exact active
  Course/term mapping, and atomically consume each verified assertion `jti` so
  replayed reads cannot refresh the local launch lease. Direct launch authority
  is now explicitly bounded to the 60-second assertion lifetime. Added a
  distinct replay-protected revocation assertion that clears the exact local
  launch lease immediately when delivered, plus a dry-run-by-default command
  for upgrading every supported user Course database.

- Added the C4 provider-free materialization path for the exact C3-H3
  model-qualified Biology Practice and Review artifacts. Single-choice option
  identities and four-source-citation remediation provenance are now persisted
  through the existing Course runtime without making a provider request.
- Added the secure reverse TEEECHR workspace read contract with dedicated
  metadata-only authorization, Ed25519 assertion verification, and the exact
  sanitized `teeechr.workspace.v1` projection. This documents the contract only;
  it makes no runtime or deployment claim.

### Fixed

- Kept BlueWay course mappings backward-compatible for exports without terms
  while qualifying map, record-routing, reconnect, and bundle idempotency
  identity by `external_course_id` plus optional `external_term_id` when a
  term is present.

### Added

- Added the C3-H2 bounded assessment runtime for private Course Practice.
  Successor revisions can now carry explicitly normalized short-answer
  contracts or immutable single-choice option IDs, grade both paths through
  matching Python and SQLite authority, persist acknowledged autosaves and
  frozen option presentation across reloads, withhold answer-adjacent evidence
  until Results, and fail closed on malformed, foreign, incomplete, or
  invalidated evidence. The learner UI uses native radio controls and serialized
  per-item autosave; no provider output or unsigned human-review recommendation
  is promoted by this runtime change.
- Centralized TEEECHR text-generation model, capability, reasoning, pricing,
  long-context, and per-feature policy in the deployment-owned model catalog.
  GPT-5.6 Luna is now the sole active model: General Chat and Course Chat use
  low reasoning, while Flashcards and Practice use medium reasoning. GPT-5
  Mini remains defined only as an inactive emergency rollback. The frozen
  16-call Mini/Luna comparison used
  zero retries and settled at $0.012788 against its $0.25 cap: both Chat
  features passed all required domain, source, citation, handoff, security, and
  validation gates. A subsequent Luna-only four-pathway medium-reasoning run
  hardened Practice question clarity, used no Mini calls or retries, passed all
  Flashcard and Practice domain/security graders, and settled at $0.002546
  against its $0.15 cap.
  General Chat and Course Chat resolve their server-controlled default and
  versioned Mini/Luna usage pricing through the policy, while Flashcards and
  Practice no longer carry duplicate Mini allowlists or price constants. Paid
  provider receipts retain
  requested and actual model identities plus pricing, prompt, schema,
  reasoning, and `store: false` versions; incomplete registries, unsupported
  capabilities or reasoning settings, invalid long-context pricing, and
  unexpected actual models fail closed before publication. The separate
  Course-generation settings file now controls only paid-call enablement and
  its dedicated credential, with read compatibility for its prior v1 shape.
- Froze the provider-free Mini-versus-Luna qualification pack across General
  Chat, Course Chat, Course and conversation Flashcards, Course and General
  Study Practice, and the Make Flashcards and Quiz Me handoffs. The validator
  requires identical hashed inputs, low reasoning, one call with no retries,
  exact requested/actual model and pricing provenance, complete usage/cost and
  artifact receipts, case-specific graders, and passing security validation.
  The frozen pack carries no paid-call authority or spend cap.
- Accelerated direct `deeptutor start` launches by deferring unrelated Chat,
  Knowledge, OpenAI, Anthropic, memory, notebook, and other CLI command imports.
  The full command tree still loads for ordinary CLI commands and root help,
  while the web launcher can print status and begin backend startup immediately.
- Closed the current-beta Practice/Quiz quality checklist. Course switches now
  clear stale Practice state and show an exact-Course loading state; ready,
  archived, and failed-generation history have distinct learner surfaces; and
  Courses with no ready source offer a direct manual fallback. Quiz attempts
  now use a focused one-question layout with numbered navigation, keyboard
  focus, guarded save/submit/abandon actions, mobile-width containment, and
  clearer `correct out of total` results, explanations, citations, retry, and
  missed-answer Flashcard actions. Exact-answer autosave rejects malformed and
  oversized payloads before persistence, while tests explicitly preserve the
  immutable `exact-v1` Unicode/trim/case behavior and park punctuation, number,
  and accepted-variant changes behind a future `exact-v2` evidence contract.
- Added the Phase 6 private Course Practice intelligence journey. Learners can
  create a durable provider-free quiz plan from Practice or the exact owned
  Course Chat message, edit and review its title, focus, sources, count,
  difficulty, and timing, then explicitly confirm one idempotent grounded
  generation operation. Generated quizzes open directly into a resumable
  attempt, preserve an untimed or reload-safe advisory timer, grade through the
  existing deterministic server authority, display learner-facing Course
  source citations, and prepare missed-answer Flashcard remediation. SQLite
  migration 0011 adds owner-bound revisioned plans, immutable timing receipts,
  cancellation/write-epoch fences, and replay-safe confirmation bindings.
  Manual Practice remains available when provider use is disabled; malformed
  provider output, missing evidence, stale sources, archive, revocation,
  cancellation, and uncertain usage accounting fail without publishing a
  ready quiz or changing mastery.
- Refined active Flashcard study into a focused notecard surface: deck
  management and neighboring prompts are hidden after study begins, while
  private numbered navigation lets learners move between unfinished cards
  without exposing their questions.
- Kept deployment-owned model and provider authority in the global settings
  namespace while Course Chat uses a private personal workspace. Administrators
  can now run Course Chat with the active server model without the personal
  Course scope incorrectly resolving an empty per-user model catalog.
- Resolved General Chat Flashcard actions from the same authenticated session
  store that owns the conversation while continuing to save General Study and
  destination Course decks in the learner's private Course workspace.
- Made General Chat Flashcard planning produce a useful no-spend title, learning
  focus, and coverage preview from the paired learner question and meaningful
  explanation headings. Unrelated zero-overlap turns are excluded, and the
  frozen receipt preserves the authenticated session namespace so confirmed
  generation reloads the exact reviewed conversation. Administrator-scope
  conversation work now revalidates the current role before reading context,
  before provider admission, and before committing candidates, so demotion
  fails the queued operation closed.
- Added private General Study and conversation-drafted Flashcards. General Chat
  can now prepare an editable, no-spend Flashcard plan from a bounded relevant
  message branch, freeze exact message receipts, save to General Study by
  default or an explicitly selected Course without claiming Course grounding,
  then confirm once in a centered modal, generate validated cards, publish them
  automatically, and open the first study card. The normal learner journey no
  longer exposes candidate operations or requires separate Save cards and
  Start studying actions; Activity retains restart-safe recovery. General Study
  is blocked from Course sources, Knowledge,
  Practice, learning, and mastery; generated counts support 1 through 48; one
  ready Course source is automatic while multiple sources remain learner
  selectable; and changed conversation authority fails before provider use.
- Made grounded Course Flashcards reject unsupported topics before any paid
  provider call, rank individual imported BlueWay records by the learner's
  focus with an explicit policy for every exported record kind, validate
  workspace card relevance without mistaking Chat or Practice workflow copy
  for a learner topic, re-derive every Chat/Practice confirmation from its
  owned server binding, and keep coverage check, confirmation, progress,
  review, and save in one continuous Create journey.
- Made the creation form select ready Course material by default, prevent the
  final grounding source from being silently removed, replace internal BlueWay
  bundle names with learner-facing copy, and visibly label the optional deck
  name and required learning topic.
- Reorganized Course Flashcards into a study-first Study, Create, and Activity
  experience. Provider-off Courses now present a direct manual path instead of
  disabled generation controls; grounded requests keep advanced choices
  optional and retain explicit provider confirmation; generation activity uses
  learner-safe state and recovery copy; automatic finalization atomically
  publishes validated cards; and study uses Show answer, Got it, and Study again while
  keeping scheduler dates internal. Raw objective IDs, operation states, and
  provider error codes no longer appear in the normal learner surface.
  Restored vertical scrolling within the shared fixed-height application shell
  and added authenticated browser coverage for the study-first shell, manual
  fallback, automatic finalization, restart persistence, and narrow-height overflow.
- Repaired the Phase 3 BlueWay-to-Phase 5 Flashcard provenance bridge for
  already-ready Course sources. Startup reconciliation now rebuilds only a
  missing or stale derived deterministic index whose owner-scoped immutable
  raw bundle still matches the persisted Course source receipt; traversal,
  symlink, hard-link, foreign-owner, malformed-bundle, identity, and digest
  failures remain fail-closed. The GPT-5 Mini Flashcard adapter now sends a
  bounded allowlist of exact citation excerpts instead of the full source text
  field, constrains structured output to permitted card types, objectives, and
  source receipts, and omits quote literals that OpenAI strict Structured
  Outputs cannot represent. An authenticated browser proof used one existing
  verified BlueWay Course bundle to generate three cited candidates, excluded
  one weak candidate at the learner-review gate, published an immutable
  two-card deck, and proved the ready deck survived a backend restart. The
  successful `store=false` request used 967 input and 488 output tokens for an
  estimated $0.001218; both paid-provider gates were disabled afterward.
- Hardened the separately gated Phase 5 paid-provider pilot with a persistent
  disabled-by-default $10 lifetime ceiling, pre-call cost reservation,
  post-call settlement, quarterly alert thresholds, and administrative
  remaining-budget totals. The OpenAI
  adapter now disables SDK retries, bounds its HTTP request inside the worker
  deadline, pins GPT-5 Mini to minimal reasoning, enforces a 14,400-token
  global output maximum with a 1,200-token three-card budget, sends a one-way
  user safety identifier, rejects incomplete or empty structured responses,
  and records cached/reasoning token and response metadata without persisting
  prompts or Course excerpts. Missing or malformed usage metadata keeps the
  conservative reservation `uncertain` instead of releasing it as zero spend.
  Paid admission also fails closed unless the administrative policy carries
  the exact qualified GPT-5 Mini pricing-version stamp. A separately approved
  bounded smoke
  produced three grounded structured cards with `store=false` for an estimated
  $0.001064; the preceding default-reasoning response exhausted its output
  ceiling and was safely rejected and settled.
- Separated paid Flashcard generation from the active Chat model catalog.
  Phase 5 now uses an admin-only, disabled-by-default GPT-5 Mini binding whose
  credential and enablement cannot silently configure ordinary Chat.
  Provider credentials are AES-256-GCM envelopes with authenticated
  credential-reference binding, a separate private persistent master key,
  strict ownership/link/permission checks, and automatic one-way migration
  from the former private plaintext JSON format.
- Stabilized the provider-unavailable Flashcard state so the settled server
  reason always retains the visible manual-Flashcard fallback instead of
  briefly showing it only while capability status is loading.
- Closed the provider-free Phase 5 single-host engineering boundary with an
  authenticated five-test browser campaign. Disposable Alice/Bob Courses,
  learning state, a five-question quiz, manual Practice/Flashcards, grounded
  candidate staging, learner review, immutable publication, and durable review
  all passed across actual backend process restarts without contacting a model.
- Added the provider-free Phase 5 Course Study Intelligence foundation.
  Flashcard generation now starts with a server-normalized, Course-owned brief
  and a separate visible confirmation; revalidates the current account,
  Course/write epoch, draft target, and exact source receipts immediately
  before provider use and again before persistence; stages normalized cited
  candidates for seven-day learner review; and publishes only the learner's
  selected order as an immutable generated deck. Chat's existing `Make
  flashcards` action and graded Practice misses create non-mutating proposals
  through the same authority contract. Manual Flashcards remain available
  without a provider.
- Added a server-only provider credential authority that migrates catalog API
  keys into opaque-reference encrypted files, rejects unsafe symlink,
  hard-link, ownership, permission, malformed-envelope, and authentication
  failures, and returns only redacted configured status to browser Settings.
  Added a disabled-by-default,
  administrative single-host provider usage ledger with per-user/global
  concurrency and daily token reservations, settlement, release, and
  conservative uncertain-outcome accounting.
- Added a strict GPT-5 Mini Responses API Flashcard adapter with structured
  output, `store=false`, no tools or web access, bounded untrusted Course
  excerpts, exact evidence-quote validation, no automatic paid retry, and a
  deterministic local provider for provider-free tests only. Real-provider
  calls, model-quality claims, deployment, push, and merge remain separately
  approved gates.
- Added a provider-free Phase 4 beta qualification campaign. Fifty saved
  profiles receive isolated Course/Practice/Flashcard/learning databases; ten
  Course operations run concurrently; normal bcrypt/JWT requests prove current
  role and disabled-account revalidation; deterministic local Practice and
  Flashcard workers prove malicious source text cannot become owner, tool,
  provider, or Knowledge authority. A hermetic two-user browser command creates
  same-titled private Courses and a five-question quiz, kills and restarts the
  backend process, then proves persistence, foreign-ID `404`, logout/cache
  isolation, and current-Course selection safety without paid calls.
- Added Course-scoped learner actions to the latest persisted assistant turn:
  Quiz me, Explain simpler, Make flashcards, and Review weak topics. The server
  re-resolves the authenticated Course, exact session/message, current ready
  source set, and committed weak-objective evidence; the browser carries no
  prompt, provider, Knowledge-base, source, objective, tool, path, or ownership
  authority. Action responses are fenced by immutable user identity, Course,
  session, message, revision, write epoch, and request epoch. Idempotent
  generation replay schedules at most one live worker, and Course-learning
  reads redact pending answers, learner text, grading receipts, and diagnostic
  notes.
- Added Course-grounded Flashcard generation with frozen source receipts,
  citation-enforced immutable cards, idempotent operation replay, explicit
  successor lineage, atomic review-schedule publication, safe terminal failure
  receipts, restart reconciliation, and account/Course/write-epoch commit
  fencing. Generated decks require ready Course sources and remain unavailable
  to manual card or ready-state APIs; manual decks are visibly labeled as not
  source-grounded. The provider seam remains fail-closed outside the explicit
  deterministic local test mode, so validation performs no paid calls.
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

### Fixed

- Removed the unsupported `uniqueItems` keyword from the strict OpenAI
  Structured Outputs schema used by Practice generation. Duplicate objective
  IDs remain rejected by TEEECHR before publication. Provider request failures
  now emit only bounded status, category, opaque operation-ID, and opaque
  request-ID diagnostics; learner content and raw upstream error messages are
  never logged.

### Changed

- Hardened the Phase 4 beta boundary with transactional owner-wide Practice and
  Flashcard generation admission, truthful provider capability reporting before
  durable allocation, additive SQLite retained-history guards, bounded attempt
  and deck pagination, batch mastery projection, retained-evidence protection
  for Course learning reinitialization, and a visible immutable Course-source
  failure/archive/replacement lifecycle. Existing learning evidence is retained;
  reaching a ceiling rejects the new write rather than deleting history.
  Isolated wheels prove migration `0007` is packaged, and the exact-tree
  authenticated browser campaign now passes two-owner restart isolation,
  provider-free Practice grading, provider-unavailable UI, and Flashcard review.
- Recorded the earlier provider-free Phase 4 engineering campaign: its then-tested
  tree passed 399 Python tests, 185 web node tests, TypeScript, full lint with no
  errors, a 54-page production build, and a disposable two-user browser flow
  across an actual backend restart. The later hardening work above reopens only
  its affected exact-tree qualification gates. Real or paid providers, native
  Apple/device certification, hosted fixture retirement, deployment,
  historical-data import, and upstream integration remain separate release
  gates.
- Hardened macOS private-workspace ACL repair against SQLite WAL/SHM
  disappearance-and-recreation races. Volatile sidecars receive a bounded
  retry with repeated owner, regular-file, link-count, symlink, mode `0600`,
  and ACL enforcement; persistent or non-sidecar failures still fail closed.
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
