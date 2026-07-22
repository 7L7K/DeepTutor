# TEEECHR v1.5.2 Phase 3 — BlueWay Private Academic Integration

Status: approved implementation contract
TEEECHR base: `8d297d24b6a458f49c59e54ed457487cccaf8f51`
TEEECHR branch: `feature/teeechr-v152-phase3-blueway-integration`
BlueWay base: `d379385b5bebafc024b754432ddf546fb8cb2bfe`
BlueWay branch: `feature/teeechr-blueway-runtime-enablement`
Last updated: 2026-07-22

Implementation checkouts:

- TEEECHR: `/Users/home/Desktop/2k26/teeech/DeepTutor-v1.5.2-baseline`
- BlueWay Phase 3 worktree: `/Users/home/Developer/BlueWay-teeechr-integration`
- BlueWay canonical parent checkout: `/Users/home/Developer/BlueWay-local`
  (left on its independently active Class Capture branch; Phase 3 must not switch
  or modify that checkout)

## 1. Goal and non-goals

### Goal

Allow one authenticated TEEECHR profile to connect one BlueWay account once and
immediately begin a private, read-only import of all supported academic data.
BlueWay `courseId` is mapped to an opaque private TEEECHR Course, structured
academic records remain queryable, course material becomes immutable
CourseSource/Knowledge input, and ready lecture transcripts become provenance-
preserving Course sources. The design targets one persistent application process
and at most 50 registered beta users.

### Non-goals

- BlueWay write-back or bidirectional conflict resolution.
- Per-course consent or sharing with instructors/students.
- Raw lecture-audio transfer to or retention by TEEECHR.
- Paid transcription, embedding, or chat-provider calls without separate approval.
- Production deployment, TestFlight work, multi-server/multi-worker support, or
  PocketBase support.
- Hard deletion, account-workspace purge, or automatic removal of learner-created
  TEEECHR work.
- Importing location history, home address, mobility data, analytics, device IDs,
  notification IDs, local URIs, setup state, caches, or review drafts.
- Practice, Flashcards, generated learning plans, Canvas/LMS, or broad UI redesign.

## 2. Contract stub

1. The connecting TEEECHR user and BlueWay subject are immutable identities;
   email, title, filename, and display name are never authority.
2. BlueWay grants only `academic.read.v1` through a short-lived, replay-resistant
   device authorization flow protected by PKCE.
3. TEEECHR stores rotating refresh credentials encrypted under a server-held key;
   browsers never receive BlueWay credentials.
4. The initial connection queues a complete, bounded, versioned academic snapshot.
5. Only records with a valid BlueWay `courseId` enter a Course automatically.
   Unlinked records remain private in a “Needs course” queue.
6. Course and mapping records commit atomically in the user’s existing `courses.db`.
7. Knowledge sources are immutable. Changed BlueWay material creates a successor
   CourseSource linked through `supersedes_source_id`.
8. Disconnect/revocation increments a generation fence, stops future work, removes
   credentials, and preserves imported material without hard deletion.
9. Course Chat continues to resolve Knowledge and provenance server-side. Imported
   transcript text is untrusted content and cannot grant tools or data authority.
10. Completion requires deterministic cross-repo proof, two-user isolation proof,
    50-profile beta-scale proof, changelog updates, and a repository closeout review.

## 3. Authoritative data boundary

### Included immediately after connection

- active and historical accepted classes;
- class meeting rows, including displayed classroom/room text, and course-linked
  schedule events;
- assignments;
- student-authored class notes;
- class links;
- course profiles;
- accepted syllabus facts;
- sanitized course-source metadata and extracted source text when available;
- Class Capture metadata and recording notes when available to the account export;
- ready raw transcript revisions and their time-segment metadata;
- future revisions of the preceding record types.

### Preserved but not auto-linked

Academic records without a valid BlueWay `courseId` are stored with
`state = 'unlinked'`. They are visible only to the owning TEEECHR profile and are
never assigned by title, time, place, filename, or fuzzy similarity.

### Excluded

- Supabase access/refresh tokens and BlueWay login credentials;
- user email and general identity-profile fields;
- home, live/device/precise location, mobility, place-note, place-visit, and
  location-history data (ordinary classroom/room display text attached to an
  accepted class meeting is academic schedule data and is included transparently);
- analytics, installation IDs, device secrets, OS permissions, and native
  notification IDs;
- setup/migration markers, import sessions, review drafts, caches, and diagnostics;
- local file URIs and arbitrary remote URLs;
- raw `.m4a` audio;
- cleaned or AI-derived transcript layers until separately produced and identified.

## 4. Doc alignment matrix

| Concern | Existing authority | Phase 3 intent | Acceptance check |
| --- | --- | --- | --- |
| TEEECHR private owner | `deeptutor/multi_user/paths.py:personal_scope_for_user`, `get_personal_path_service` | Every connection, record, Course, source, credential, run, and UI cache resolves through immutable TEEECHR `user_id` | Two users and two admins cannot read or mutate one another’s integration IDs |
| Current-account authority | `deeptutor/api/routers/auth.py:require_auth`, `ws_revalidate_auth` | Revalidate the current TEEECHR account before sync and immediately before every authority-bearing commit | Disable/delete/identity-switch/provider-revocation races fail closed; admin-to-user role change preserves the same private learner scope |
| Course aggregate | `deeptutor/courses/models.py:Course`, `CourseSource`; `repository.py:CourseRepository` | Add mapping/sync tables to the same private `courses.db`; retain opaque local Course IDs | Course plus external mapping commits atomically; no title matching |
| Source immutability | `CourseSource.supersedes_source_id`, `content_sha256`, `idempotency_key` | Render deterministic BlueWay Course bundles and transcripts; create successors only when hashes change | Replay creates no duplicate; changed hash creates exactly one successor |
| Source commit fences | `deeptutor/courses/ingestion.py:run_source_operation` | Add connection/generation authority to existing owner/course/source revision and write-epoch fences | Disconnect/archive/revision changes prevent late ready commits |
| Course Chat provenance | `deeptutor/courses/service.py:resolve_course_turn_payload`; session message metadata | Reuse server-derived Course/source IDs, revisions, and fingerprints | Client-supplied BlueWay IDs never grant Course/Knowledge authority |
| BlueWay class identity | `src/features/courseIdentity/courseId`; `docs/blueway-data-contract.md:courseId` | Preserve exact BlueWay `courseId` in a mapping table; one Course may have multiple meeting rows | Same-title classes remain distinct; meeting IDs do not become Course IDs |
| BlueWay account datasets | `src/features/storage/dataRegistry.ts:datasetDefinitions`; `accountSync/cloudDatasetService.ts` | Build a narrow server-owned academic export instead of exposing raw `user_datasets` | Fixed allowlist and field-exclusion tests pass |
| BlueWay Class Capture | `classCaptureCloudBackupTypes.ts`; private backup functions/migrations | Export metadata/transcripts only; raw audio remains BlueWay authority | No audio URL/bytes appear in export, TEEECHR disk, logs, or manifests |
| BlueWay authentication | `src/features/auth/supabaseAuthClient.ts`; Supabase user-auth Edge pattern | BlueWay user approves a TEEECHR device authorization; BlueWay subject comes from `auth.uid()` | Forged owner/email/client values do not affect grant owner |
| Single-host beta | `deeptutor/courses/deployment.py:SingleProcessCourseLock` | Reuse durable SQLite runs and one process-level coordinator | Multiple worker startup remains rejected; restart reconciliation passes |

## 5. TEEECHR storage contract

BlueWay relationship tables are created inside each owner’s existing `courses.db`.
Credential ciphertext remains outside SQLite under a fixed personal path. This keeps
Course creation plus external mapping atomic while separating secrets from Course
metadata and Knowledge content.

### `blueway_connections`

```sql
CREATE TABLE blueway_connections (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    external_subject TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN (
            'pending', 'active', 'revocation_pending', 'disconnected', 'error'
        )
    ),
    scope_version TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    grant_generation INTEGER NOT NULL DEFAULT 1 CHECK (grant_generation >= 1),
    credential_ref TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    connected_at REAL,
    last_sync_at REAL,
    disconnected_at REAL
);

CREATE UNIQUE INDEX blueway_one_writable_or_revoking_connection
ON blueway_connections(owner_user_id)
WHERE state IN ('active', 'revocation_pending');
```

### `blueway_course_maps`

```sql
CREATE TABLE blueway_course_maps (
    connection_id TEXT NOT NULL
        REFERENCES blueway_connections(id) ON DELETE RESTRICT,
    external_course_id TEXT NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
    remote_title TEXT NOT NULL,
    remote_state TEXT NOT NULL CHECK (remote_state IN ('active', 'archived')),
    remote_hash TEXT NOT NULL,
    first_seen_snapshot_id TEXT NOT NULL,
    last_seen_snapshot_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (connection_id, external_course_id),
    UNIQUE (connection_id, course_id)
);
```

### `blueway_records`

```sql
CREATE TABLE blueway_records (
    connection_id TEXT NOT NULL
        REFERENCES blueway_connections(id) ON DELETE RESTRICT,
    record_kind TEXT NOT NULL,
    external_record_id TEXT NOT NULL,
    external_course_id TEXT,
    course_id TEXT REFERENCES courses(id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK (state IN ('current', 'unlinked', 'archived')),
    remote_revision TEXT,
    content_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    current_source_id TEXT REFERENCES course_sources(id) ON DELETE RESTRICT,
    first_seen_snapshot_id TEXT NOT NULL,
    last_seen_snapshot_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (connection_id, record_kind, external_record_id)
);
```

Record kinds:

```text
class_meeting, schedule_event, assignment, class_note, class_link,
course_profile, syllabus_fact, source_text, capture_metadata,
capture_note, transcript_raw, transcript_cleaned
```

### `blueway_sync_runs`

```sql
CREATE TABLE blueway_sync_runs (
    id TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL
        REFERENCES blueway_connections(id) ON DELETE RESTRICT,
    expected_generation INTEGER NOT NULL,
    snapshot_id TEXT,
    snapshot_sha256 TEXT,
    state TEXT NOT NULL CHECK (state IN (
        'queued', 'fetching', 'validating', 'staging',
        'indexing', 'completed', 'failed', 'cancelled'
    )),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    counts_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL
);

CREATE UNIQUE INDEX blueway_snapshot_replay
ON blueway_sync_runs(connection_id, snapshot_id)
WHERE snapshot_id IS NOT NULL;
```

### Credential file

```text
data/users/<user_id>/user/integration_credentials/<connection_id>.enc
```

AES-256-GCM associated data:

```text
owner_user_id | connection_id | provider | scope_version
```

Required configuration:

```text
TEEECHR_BLUEWAY_INTEGRATION_ENABLED
TEEECHR_BLUEWAY_BASE_URL
TEEECHR_BLUEWAY_APPROVAL_URL
TEEECHR_BLUEWAY_CLIENT_ID
TEEECHR_BLUEWAY_API_SECRET
TEEECHR_INTEGRATION_MASTER_KEY
```

`TEEECHR_BLUEWAY_APPROVAL_URL` is a pinned HTTPS BlueWay app/universal-link route;
it is separate from the Supabase Edge origin. `TEEECHR_BLUEWAY_API_SECRET`
authenticates only the TEEECHR server to BlueWay's
pairing/token Edge boundary through `x-teeechr-integration-secret`; it is never a
Supabase `apikey`, secret API key, or service-role credential. It is never returned to the browser or stored in a
personal Course database. BlueWay's short rotation-receipt encryption key remains a
separate Edge secret and is never sent by TEEECHR.

Integration-enabled startup fails closed when TEEECHR authentication, the master
key, the pinned HTTPS BlueWay origin, or the supported local SQLite backend is
unavailable. Loopback HTTP is allowed only in explicit development tests.

## 6. Delegated connection protocol

1. Authenticated TEEECHR `POST /connect/start` generates a high-entropy device
   secret, PKCE verifier/challenge, and a ten-minute local attempt.
2. BlueWay returns a high-entropy device code plus a human-readable one-time user
   code/deep link.
3. The signed-in BlueWay app displays the complete academic-data consent and calls
   a user-authenticated Edge Function with the app's expected account ID. The
   approval transaction requires `auth.uid()` to equal that expected account and
   derives the grant subject from the same value; an auth-token switch fails before
   any approval commit.
4. TEEECHR polls with the device code and PKCE verifier. The code is one-use and
   bound to the configured client/audience.
5. Approval returns the immutable approved BlueWay subject, an opaque grant
   reference, a five-minute access token, and rotating refresh token scoped only
   to `academic.read.v1`. None of these values are returned to the TEEECHR browser.
6. BlueWay stores token hashes, enforces one active TEEECHR grant per BlueWay
   account, rotates refresh tokens, detects reuse, and supports immediate revocation.
   The client is seeded disabled. Approval snapshots the exact opaque active grant
   ID, if any; only a successful exchange may atomically replace that exact grant.
   Abandoned approval leaves a working grant untouched, and a delayed stale exchange
   cannot displace a newer grant. Every refresh carries a unique rotation request ID.
   For at most 60 seconds,
   BlueWay retains an encrypted rotation receipt so an identical retry can receive
   the same successor token; reuse with a different request ID revokes the family.
   Expired encrypted receipts are deleted by a durable database cleanup independent
   of future refresh traffic.
7. TEEECHR encrypts the refresh credential, removes pairing secrets, creates the
   active connection record, and queues the first full sync. It rejects new pairing
   while a local connection is active or revocation-pending; reconnect begins only
   after the earlier local and remote authority is safely terminal.

Disabling the registered integration client is an emergency kill switch, not only an
admission flag. Approval, exchange, refresh, and export all recheck it; revocation
remains available while disabled.

BlueWay private tables:

```text
blueway_teeechr_private.integration_clients
blueway_teeechr_private.pairing_requests
blueway_teeechr_private.grants
blueway_teeechr_private.refresh_token_families
blueway_teeechr_private.refresh_tokens
blueway_teeechr_private.refresh_rotation_receipts
```

No private table is directly granted to `anon` or `authenticated`. Security-
definer functions use fixed `search_path` values and explicit owner/client checks.
The private schema/tables/functions are also revoked directly from `service_role`;
that role receives execute only on the narrow public RPC boundary. Deleting a
BlueWay auth account cascades through pairing/grant/token/receipt metadata so a
stale integration cannot block account deletion. This cascade never reaches
TEEECHR's retained private Course history.

## 7. BlueWay export contract

```http
GET /functions/v1/teeechr-export?cursor=<opaque>
Authorization: Bearer <academic-read-token>
```

```json
{
  "schema_version": 1,
  "snapshot_id": "bws_<64-lowercase-hex>",
  "snapshot_revision": 42,
  "generated_at": "2026-07-21T00:00:00Z",
  "complete": true,
  "next_cursor": null,
  "datasets": {
    "courses": [],
    "class_meetings": [],
    "schedule_events": [],
    "assignments": [],
    "class_notes": [],
    "class_links": [],
    "course_profiles": [],
    "syllabus_facts": [],
    "source_texts": [],
    "capture_metadata": [],
    "capture_notes": [],
    "transcripts": []
  },
  "unavailable": [],
  "payload_sha256": "<sha256>"
}
```

Every exported record has an immutable ID, optional exact `course_id`, revision,
content hash, and explicit state. Records without native revisions derive one from
canonical JSON. Missing records are archived locally only after the final complete
snapshot and full payload hash are verified. An `unavailable` dataset is not an
empty dataset and carries no deletion authority; previous records/sources for that
dataset remain unchanged until a later complete snapshot explicitly includes it.

No adapter may silently slice, skip, or coerce a malformed or oversized record. A
snapshot that exceeds any bound fails as a whole with a safe code, unless every page
belongs to one stable subject-bound snapshot with per-dataset completeness receipts.
Repeated reads of unchanged account truth produce the same snapshot ID and hash;
pagination never creates a new snapshot identity per request.

Beta limits:

```text
500 records/page
5 MiB response/page
64 KiB structured record
32 KiB note
2 MiB source text
5 MiB transcript
500 records/complete beta snapshot
```

Larger paginated snapshots and a 20,000-record ceiling remain a future protocol
extension. Phase 3 rejects pagination instead of silently truncating or presenting
a partial snapshot as complete.

Completed capture metadata may include recording name, duration/timestamps, and
exact Course/meeting identifiers. Capture location snapshots remain excluded.

The export constructs data from a fixed academic allowlist. It never returns raw
`user_datasets` rows, arbitrary URLs, service-role material, auth/profile/location/
device data, or raw audio.

## 8. TEEECHR API contract

```text
POST /api/v1/integrations/blueway/connect/start
GET  /api/v1/integrations/blueway/connect/{attempt_id}/status
POST /api/v1/integrations/blueway/connect/{attempt_id}/poll
GET  /api/v1/integrations/blueway
POST /api/v1/integrations/blueway/sync
GET  /api/v1/integrations/blueway/sync-runs/{run_id}
GET  /api/v1/integrations/blueway/unlinked
POST /api/v1/integrations/blueway/disconnect
```

All TEEECHR routes resolve the owner from the current authenticated request. Foreign
connection, run, Course, record, and attempt identifiers return the same `404`.
Disconnect requires the expected connection revision. One local transaction first
sets `revocation_pending`, increments the generation, and cancels local work. The
server then revokes BlueWay and removes credentials. A network failure leaves the
connection locally fenced in `revocation_pending` and retries remote revocation;
the browser never regains sync authority merely because BlueWay is unavailable.
Imported data is retained.

The observational `GET .../status` never exchanges credentials or mutates authority.
The browser uses the Origin-protected `POST .../poll` to ask the server to perform one
bounded exchange attempt; tokens remain server-only and a successful exchange is
idempotent/one-use.

## 9. Durable sync algorithm

1. Persist a `queued` run and return `202`.
2. A single-process coordinator enforces one run/connection and at most three
   concurrent BlueWay syncs.
3. Revalidate the current TEEECHR account and connection generation.
4. Refresh the scoped BlueWay access token with rotation/reuse protection.
5. Fetch every bounded export page into a `0700` personal temporary directory;
   each file is `0600`.
6. Reject redirects, foreign hosts, cursor loops, schema drift, duplicate IDs,
   oversized/decompression-bomb payloads, silent truncation, unstable snapshot IDs,
   hash mismatch, and partial deletion.
7. Revalidate account, immutable subject, connection state, and generation.
8. Use `BEGIN IMMEDIATE` on personal `courses.db` to create new Courses, permanent
   mappings, structured records, and the snapshot receipt. Recheck exact owner,
   connection state, subject, and expected generation inside that same transaction;
   a pre-transaction check is not commit authority.
9. Preserve learner-renamed TEEECHR Course titles. Store BlueWay title separately.
10. Mark prior records absent only after complete-snapshot verification. Any source
    that represented a now-absent record is archived and removed from active Course
    retrieval in the same lifecycle operation; its immutable bytes and message
    provenance remain retained for historical citation display.
11. Render deterministic JSON/Markdown bundles for changed Courses.
12. Create immutable processing CourseSource rows using deterministic idempotency
    keys and the previous source as `supersedes_source_id`.
13. Queue indexing. Structured import may complete while Knowledge status remains
    `processing`.
14. Before final source commit, revalidate account, connection generation, subject,
    Course state/revision/write epoch, and source operation/revision.
15. On restart, requeue safe interrupted fetch/staging runs and reconcile orphaned
    processing sources. Permanent auth/schema/integrity failures do not retry.

## 10. Generated Course sources

Per changed Course:

```text
blueway-course-snapshot.json
blueway-course-snapshot.md
```

Deterministic ordering is record kind, BlueWay course ID, record ID, and timestamp.
The idempotency key is:

```text
blueway:<external_subject>:<external_course_id>:<bundle_sha256>
```

Existing browser upload and generated-source ingestion share one internal staging
pipeline. Server code does not fake an HTTP `UploadFile`. Generated input carries:

```text
provider, connection_id, expected_generation, external_subject, snapshot_id
```

Imported text is wrapped as untrusted academic content. Links are rendered as text
only and never fetched by synchronization.

## 11. Transcript contract

BlueWay retains raw audio. A ready transcript export contains capture ID, exact
BlueWay course ID, recorded/stopped timestamps, duration, language, revision, hash,
layer, and timestamped segments. TEEECHR creates an immutable
`blueway_transcript_raw` CourseSource. Corrected transcripts create successors.

Raw, cleaned, and AI-derived layers remain distinct. Transcript text never appears
in logs and cannot activate tools, change Course identity, select Knowledge, or
grant cross-workspace access. Provider-backed transcription remains disabled until
the provider, price, data-retention policy, and one bounded paid proof are approved.

## 12. Task breakdown and implementation checklist

### P3-01 — Freeze contract and branches

- **Scope:** Phase 3 plan, both canonical repository states, branch identity.
- **Inputs/outputs:** this document and branch proof.
- **Acceptance:**
  - [x] TEEECHR base and branch recorded.
  - [x] BlueWay base and branch recorded.
  - [x] Goal/non-goals, schema, APIs, limits, and exit gates recorded.
  - [x] Every referenced implementation symbol is rechecked before closeout.
- **Doc alignment:** `TEEECHR_V152_PHASE2_*`, BlueWay `CODEX_TRUTH_PACK.md`.
- **Risk:** either base moves. Resolve by reporting exact current SHAs; never silently
  rebase or rewrite.

### P3-02 — BlueWay delegated authorization database

- **Scope:** Supabase migrations and shared validation only.
- **Inputs/outputs:** private pairing/grant/token tables and hardened functions.
- **Acceptance:**
  - [ ] Owner is derived from authenticated claims.
  - [ ] Codes expire and cannot replay.
  - [ ] PKCE/client/audience checks pass.
  - [ ] Refresh rotation and family reuse revocation pass.
  - [ ] Reuse revocation remains committed after the RPC returns its typed denial;
        it is not undone by a raised PostgreSQL exception.
  - [ ] One active grant/account is enforced.
  - [ ] Private schema/table privileges are denied directly.
  - [ ] BlueWay auth-account deletion removes private grant/token metadata without
        being blocked by restrictive foreign keys.
- **Risk:** hand-rolled OAuth mistakes. Use a narrow device-authorization subset,
  hashed secrets, exact states, and independent SQL/security review.

### P3-03 — BlueWay bounded academic export

- **Scope:** export function, fixed record adapters, sanitizer, schemas, tests.
- **Inputs/outputs:** versioned complete/paginated academic snapshots.
- **Acceptance:**
  - [ ] Exact dataset and field allowlist.
  - [ ] `courseId` preserved; titles never become identity.
  - [ ] Page/body/record/text/transcript limits enforced.
  - [ ] The 501st, malformed, or oversized record fails the snapshot instead of
        disappearing from a response marked complete.
  - [ ] Unchanged account truth has a stable snapshot ID across page requests.
  - [ ] Partial pages cannot imply deletion.
  - [ ] Auth/profile/location/device/raw-audio fields are absent.
  - [ ] Deterministic fixtures and hashes pass.
- **Risk:** several sources are local/deferred today. Export reports them explicitly
  unavailable until account-owned sanitized content exists; it never invents data.

### P3-04 — BlueWay connection consent and fresh snapshot

- **Scope:** feature-local Expo route/store/client and focused tests.
- **Inputs/outputs:** connection code entry/deep link, consent, approval, revocation.
- **Acceptance:**
  - [ ] Consent copy names included and excluded categories.
  - [ ] Latest supported account data uploads before approval.
  - [ ] Account switch invalidates stale approval work.
  - [ ] No tokens enter BlueWay dataset stores or analytics.
  - [ ] No broad Profile/class/Schedule redesign.
- **Risk:** remote auth/runtime proof is distinct from deterministic source/tests.

### P3-05 — TEEECHR encrypted connection authority

- **Scope:** configuration, `PathService`, encryption, models, repository, API start/status.
- **Inputs/outputs:** active personal connection and encrypted rotating credential.
- **Acceptance:**
  - [ ] AES-GCM AAD binds owner/connection/provider/scope.
  - [ ] Tamper, wrong key, wrong owner, and key-version tests fail closed.
  - [ ] Files/directories are `0600`/`0700`.
  - [ ] Integration-enabled startup rejects missing auth/key/TLS/local backend.
  - [ ] Browser never receives access/refresh tokens.
- **Risk:** credential rotation crash. Replace the encrypted file atomically before
  using the successor token for further work. Retry a lost response only with the
  identical rotation request ID inside the encrypted receipt window; different reuse
  is a security event, not an ordinary retry.

### P3-06 — TEEECHR Course mapping and structured mirror

- **Scope:** `courses.db` schema and repository/service methods.
- **Inputs/outputs:** connection, Course map, record, and sync-run rows.
- **Acceptance:**
  - [ ] Schema migration is idempotent with foreign keys/WAL/checks/indexes.
  - [ ] Course plus first mapping is one transaction.
  - [ ] Same-title/different-ID classes remain separate.
  - [ ] Learner Course rename is preserved.
  - [ ] Unlinked records remain unlinked.
  - [ ] Complete snapshots archive missing records; partial snapshots do not.
  - [ ] `unavailable` datasets retain earlier records and sources; they never act
        as an empty authoritative dataset.
  - [ ] Archived remote records and transcripts leave active Course retrieval while
        their immutable historical provenance remains available.
- **Risk:** mixed repository concurrency. Use `BEGIN IMMEDIATE`, busy timeout, the
  current single-process invariant, and per-connection operation locks.

### P3-07 — Strict client and durable sync coordinator

- **Scope:** HTTP client, validator, coordinator, restart reconciliation.
- **Inputs/outputs:** durable run receipts and imported structured records.
- **Acceptance:**
  - [ ] Pinned HTTPS origin, no redirects, strict timeouts and size caps.
  - [ ] Token refresh once on 401; auth failures stop safely.
  - [ ] Snapshot replay and conflict behavior are deterministic.
  - [ ] Disconnect/disable/archive/revision races fail closed.
  - [ ] Offline disconnect immediately enters `revocation_pending` and blocks all
        local work until remote revocation can be retried.
  - [ ] Startup resumes pending revocation and refuses a second connection until
        the first is remotely revoked or explicitly repaired.
  - [ ] Restart requeues only safe interrupted states.
  - [ ] Maximum three concurrent syncs and one per connection.
- **Risk:** background work outlives authority. Carry and revalidate generation at
  every stage and before commits.

### P3-08 — Generated academic CourseSource ingestion

- **Scope:** internal Course ingestion refactor, renderer, task authority fencing.
- **Inputs/outputs:** deterministic JSON/Markdown CourseSource bundles.
- **Acceptance:**
  - [ ] Browser upload behavior remains unchanged.
  - [ ] Internal input follows the same format/size/path checks.
  - [ ] Identical bundle hash creates no duplicate.
  - [ ] Changed bundle creates one successor.
  - [ ] Revoked/archived/stale work cannot become ready.
  - [ ] Provenance survives regeneration.
- **Risk:** RAG provider calls. Automated validation uses deterministic local providers.

### P3-09 — Transcript-ready source support

- **Scope:** export validator, record mirror, renderer, source kinds, fixtures.
- **Inputs/outputs:** immutable timestamped transcript CourseSources.
- **Acceptance:**
  - [ ] No raw audio reaches TEEECHR.
  - [ ] Raw/cleaned/derived layers remain distinct.
  - [ ] Replacement preserves old hash/provenance.
  - [ ] Malicious transcript instructions cannot widen tools/Knowledge.
  - [ ] Transcript content never appears in logs.
  - [ ] No paid provider call runs.
- **Risk:** real transcripts do not exist yet. Deterministic fixtures prove ingestion;
  provider generation remains a separately approved subphase.

### P3-10 — Minimal TEEECHR UI

- **Scope:** Settings integration route, status card, Course badge, unlinked list.
- **Inputs/outputs:** connect, sync status, Sync now, disconnect, readiness states.
- **Acceptance:**
  - [ ] No course picker during initial connection.
  - [ ] Connection acceptance and Knowledge readiness are shown separately.
  - [ ] Logout/identity switch clears all stale integration state.
  - [ ] Disconnect explains retained local material.
  - [ ] No credentials in browser persistence.
  - [ ] Generic Course Chat/learning behavior remains intact.
- **Risk:** broad settings redesign. Keep feature-local components and reuse current
  Settings and CourseContext patterns.

### P3-11 — Adversarial validation and beta-scale proof

- **Scope:** BlueWay tests/SQL tests, TEEECHR pytest/web tests, deterministic E2E.
- **Inputs/outputs:** test reports and explicit proof boundaries.
- **Acceptance:**
  - [ ] Wrong owner/client/audience/PKCE, expired/replayed code tests.
  - [ ] Token rotation/reuse/revocation tests.
  - [ ] Identical refresh retry returns its bounded receipt; different reuse revokes
        the token family.
  - [ ] Two-user and two-admin isolation tests.
  - [ ] Duplicate/out-of-order/partial/corrupt/oversized snapshot tests.
  - [ ] Disable/disconnect/archive/revision/crash race tests.
  - [ ] Prompt-injection/unsafe URL/log-redaction tests.
  - [ ] 50 profiles and ten concurrent non-provider operations.
  - [ ] Two-user browser proof with two courses each.
  - [ ] Source/tests, browser, backend/data, provider, deployment, simulator, and
    physical-device claims remain separate.
- **Risk:** hosted Supabase mutation. Default proof is local SQL/fakes; any hosted
  proof requires explicit approval and a reversible test-account plan.

### P3-12 — Closeout

- **Scope:** diffs, tracked/untracked files, changelogs, handoff, commits.
- **Acceptance:**
  - [ ] `section-closeout-backcheck` completed.
  - [ ] Independent diff/security/data-lifecycle review completed.
  - [ ] TEEECHR and BlueWay changelogs updated.
  - [ ] No secrets, build output, DBs, transcripts, tokens, or QA artifacts tracked.
  - [ ] Exact untested proof surfaces reported.
  - [ ] Commit-or-park decision made separately in each repository.
  - [ ] No push/deployment occurs without explicit authority.

## 13. Verification plan

### TEEECHR focused checks

```text
pytest tests/integrations/blueway tests/courses tests/multi_user
ruff check <changed-python-files>
web npm run test:node -- <focused-tests>
web npm run build
git diff --check
```

### BlueWay focused checks

```text
npm test -- <teeechr-integration-tests>
npm run typecheck
supabase db lint or repository-equivalent local SQL verification
git diff --check
```

### Broad checks

- Full TEEECHR pytest suite.
- Full TEEECHR frontend node test suite, TypeScript, and production build.
- Full BlueWay Vitest suite and TypeScript check.
- Deterministic cross-repo pairing/export/sync fixture with no network provider.
- Fifty-profile isolation seed and ten concurrent sync/status operations.
- Authenticated browser proof with two TEEECHR users and distinct BlueWay fixtures.

### Database-specific gates

TEEECHR personal SQLite:

- initialize the Phase 3 schema twice and compare `sqlite_master`;
- assert `PRAGMA journal_mode = WAL`, `foreign_keys = 1`, `quick_check = ok`,
  and an empty `foreign_key_check` result;
- enumerate indexes and partial unique constraints for one-active connection,
  snapshot replay, external Course identity, source successors, and live operations;
- exercise every state/check/FK constraint with an invalid insert or transition;
- prove `BEGIN IMMEDIATE` disconnect-versus-map and stale-generation races;
- prove two profiles produce distinct `0600` database files and cannot open rows
  through any API identifier;
- reopen after process restart and reconcile queued/processing/revocation-pending
  states deterministically;
- verify no integration API or foreign-key cascade can hard-delete Course history.

BlueWay private Postgres/Supabase schema:

- apply the additive migration to a disposable local database twice;
- inspect schema/table/function ACLs: no direct `anon`/`authenticated` access to
  private tables and only the two owner-authenticated approval/revocation RPCs;
- verify RLS is enabled, every security-definer function has a fixed empty
  `search_path`, and every extension/object reference is schema-qualified;
- exercise pending → approved → exchanged, expiration/denial, active → revoked,
  refresh rotation/receipt/reuse, and disabled-client transitions;
- prove `auth.uid()` is the sole approval owner and service callers cannot supply a
  different academic subject to export;
- prove the private one-active-grant constraint and exact client/audience/scope
  checks under concurrent transactions;
- prove service responses and database errors never log or return stored hashes,
  receipt ciphertext, service credentials, or another subject's identifiers;
- run local migration/schema lint when the Supabase CLI/database is available;
  absence of that runtime remains an explicit unproved hosted-backend surface.

### Proof boundaries

The following remain independent and cannot be inferred from one another:

- hosted Supabase migration/function deployment (proved below);
- real BlueWay account pairing and owner-isolated sync (proved below through
  authenticated HTTP/API surfaces; the signed-in browser click remains open);
- real transcript-provider generation (not proved);
- real embeddings/chat retrieval over imported transcripts (not proved);
- Expo web preview rendering (proved) versus native simulator/physical iPhone
  runtime (not proved);
- local TEEECHR runtime (proved) versus deployment or multi-server behavior
  (not proved);
- GitHub push/PR/release state (not yet proved in this ledger).

## 14. Risks and unknowns

1. **Transcription provider and retention:** unknown and intentionally disabled.
   Connection/export/sync and deterministic transcript ingestion proceed first.
2. **Deferred BlueWay source text/capture notes:** some data is currently device-local.
   The export reports absence honestly until sanitized account-owned copies exist.
3. **Cross-repository atomicity:** impossible. Each repository is independently
   reviewed/committed; runtime protocol compatibility is proven with shared fixtures.
4. **Single-process durability:** supported. Multiple workers/replicas remain rejected.
5. **Windows host permissions:** TEEECHR’s current private POSIX/macOS proof does not
   establish Windows DACL isolation. Do not claim Windows multi-profile privacy.
6. **BlueWay local branch divergence:** the canonical checkout is 11 commits ahead of
   `origin/main`. Preserve that history; do not rebase, reset, or push implicitly.
7. **Concurrent BlueWay transcription work:** the canonical BlueWay checkout is on
   `feature/class-capture-transcription-foundation` with independent uncommitted
   schema, function, runtime, test, and documentation work. Phase 3 was therefore
   built in `/Users/home/Developer/BlueWay-teeechr-integration`. The two reviewed
   branches must be integrated explicitly after both are stable; no file copying,
   checkout switching, reset, or inferred merge is authorized.

## 15. Exit criteria

Phase 3 is complete only when:

- [x] One authenticated TEEECHR user can complete deterministic BlueWay pairing.
- [x] Pairing immediately queues a complete private academic sync.
- [x] Every valid BlueWay course maps to exactly one private TEEECHR Course.
- [ ] Unlinked records are retained without guessed ownership.
- [x] Structured records, encrypted connection authority, ready Course bundles, and
      both isolated profiles survived a local TEEECHR process restart.
- [ ] Changed academic bundles and transcripts use immutable CourseSource successors.
- [x] Disconnect/revocation blocks late work and preserves imported data.
- [x] No BlueWay write-back, hard deletion, raw-audio import, or paid provider call exists.
- [ ] Ownership, replay, race, payload, prompt-injection, and log-redaction gates pass.
- [ ] Beta-scale deterministic proof passes for 50 profiles.
- [ ] Both repositories pass the final focused and broad relevant checks.
- [ ] Changelogs, handoff, diff review, untracked review, and closeout backcheck are done.
- [ ] Untested live/provider/deployment/device surfaces are reported explicitly.

## 16. Implementation and proof ledger

This ledger separates implemented source contracts from runtime claims that require
an actual Supabase/Postgres/Edge/browser/device environment. A checked source item
does not imply that an unchecked live surface works.

### Implemented source checklist

- [x] Both implementation checkouts and immutable bases were re-proved before work.
- [x] BlueWay client registration is additive and seeded disabled.
- [x] BlueWay device authorization binds client, audience, PKCE, one-use codes,
      authenticated `auth.uid()`, and an exact opaque replacement grant ID.
- [x] Refresh tokens rotate with bounded encrypted retry receipts; different-request
      reuse revokes the family; expired receipts have an independent cleanup job.
- [x] Client disable is rechecked under row locks for approval, exchange, refresh,
      and export while owner/server revocation remains available.
- [x] BlueWay private tables/functions have explicit privilege revocation and narrow
      public RPC grants in the migration source.
- [x] The academic export uses an exact dataset/field allowlist, a database-side
      count/byte preflight before JSON aggregation, Edge-side record/body limits,
      stable hashes, and no silent truncation.
- [x] Completed normalized transcripts export only owner-matched segment text and
      timing with exact Course/capture identity; audio, provider metadata, word
      timings, speaker/confidence data, storage paths, and location remain excluded.
- [x] Raw audio, object paths, arbitrary URLs, profile/auth/device data, home/live/
      precise location, mobility, place history, and capture location snapshots are
      absent from the export contract and consent copy.
- [x] TEEECHR integration startup is fail-closed for auth, one-process/local-SQLite,
      HTTPS/pinned origins, client/server configuration, and a 32-byte master key.
- [x] Credentials are AES-256-GCM owner/connection/provider/scope bound, versioned,
      atomically replaced, directory-fsynced, and protected by explicit filesystem
      ownership, hard-link, symlink, and `0600`/`0700` checks.
- [x] Connections, exact Course maps, records, and durable runs live in the owner's
      existing `courses.db` with WAL, foreign keys, transactions, and generation
      fences.
- [x] The same BlueWay subject reconnects to the same exact Course/source identity;
      a different subject cannot reuse it even with identical titles and IDs.
- [x] `unavailable` datasets retain their own prior authority only. They do not stop
      available datasets from archiving explicitly removed or absent records.
- [x] Generated Course bundles use deterministic local indexing only; ready source
      visibility and record bindings commit atomically after current-owner,
      connection-generation, Course-state, revision, and write-epoch checks.
- [x] Identity disable/delete and final source visibility use the documented
      identity-then-Course lock order, with a real two-thread interleaving test.
- [x] Snapshot validation rejects unknown/nested/wrongly typed optional fields and
      invalid transcript layers, durations, timestamps, or segment ordering.
- [x] Disconnect is local-first and generation-fenced; imported Course data remains.
- [x] Minimal BlueWay consent and TEEECHR Settings surfaces expose no credential or
      export payload in browser persistence and clear identity-scoped state.
- [x] Both changelogs distinguish the deployed hosted proof from still-unproved
      provider, signed-in-browser, native-device, and TEEECHR-hosting surfaces.
- [x] No paid model, embedding, transcription, or chat-provider call was made.
- [x] No paid provider, raw audio transfer, BlueWay write-back, or hard deletion
      was exercised. Hosted migrations, three Edge Functions, and an Expo preview
      were deliberately deployed for the reviewed runtime proof below.

### Local deterministic proof captured on 2026-07-22

- TEEECHR full Python suite before the final SQLite-sidecar hardening: `2835 passed,
  6 skipped`; the final impacted Course/identity/BlueWay suite then passed `218`
  tests, and the last focused permission-repair run passed `6` adversarial tests.
  Only the pre-existing shared pytest temporary-directory cleanup warning remained.
- TEEECHR focused Course/Knowledge/identity/path/BlueWay suite: `95 passed` before
  the final validator hardening; the final full suite above includes the final tree.
- TEEECHR Ruff over every changed Python surface: pass.
- TEEECHR web node suite: `168 passed`; TypeScript: pass; production build: pass,
  including `/settings/blueway`.
- BlueWay final focused integration/transcription suite: `170 passed` across `13`
  test files; TypeScript: pass.
- BlueWay full Vitest suite: `238` files passed and `2` unrelated release/native
  policy files failed (`2559` tests passed, `10` failed, `2` todo). The isolated
  worktree intentionally has no generated iOS project and its installed Expo Audio
  dependency has not run the repository lifecycle patch. Phase 3 focused tests pass.
- Cross-repository fixture byte comparison: exact match, SHA-256
  `a47f0041c2c66f3b36c32f7d9618b8718a2cc2596d8a9e564ebe751192da040c`.
- `git diff --check`: pass in both repositories.
- Secret-pattern scan over the new TEEECHR integration/browser surfaces: no match.
- Final independent source/security review: no remaining P0, P1, or P2 finding.
  The reviewer reproduced a broken-symlink ACL retry edge case; the final `lstat()`
  repair and adversarial regression were re-reviewed and received a PASS verdict.
- `supabase db lint --local`: not run successfully; the CLI could not connect to a
  local Postgres instance (`LegacyDbConnectError` / `PgClient: Failed to connect`).

### Hosted/runtime proof captured on 2026-07-22

- [x] Applied the Class Capture transcription and Phase 3 integration migrations to
      Supabase project `bzpgfrzvhorhoensjtsz`, including forward repairs for SQL
      ambiguity, completed-transcript export, PostgreSQL-safe device-code validation,
      and explicit refresh-token revocation state.
- [x] Hosted `db lint --level error` returns no findings. All seven integration
      tables have RLS enabled; `anon`, `authenticated`, and `service_role` have no
      private-schema usage; public RPC execute grants match the contract.
- [x] Deployed `teeechr-pairing`, `teeechr-connection`, and `teeechr-export`. Missing
      and wrong integration secrets return `401`; the dedicated secret is rejected
      as a Supabase API key; unauthenticated consent calls return `401`.
- [x] Ran concurrent hosted refresh, revoke, and export calls on separate sessions:
      no `40P01`/`40001`, the grant/family were revoked, and every refresh/access
      token row recorded revocation. The disposable concurrency rows were removed.
- [x] Provisioned two real email-confirmed Supabase test accounts. Each JWT saw only
      its own same-titled schedule row; Alice's foreign-owner insert returned `403`.
- [x] Paired two separate authenticated local TEEECHR profiles to those two BlueWay
      accounts, exchanged credentials server-side, completed both syncs, produced one
      ready deterministic Course bundle per owner, and returned `404` for both crossed
      Course reads despite identical course titles.
- [x] Restarted the TEEECHR process with the same protected configuration; both
      profiles retained active connections and exactly one private Course. A transient
      SQLite `courses.db-shm` disappearance found during the proof now has focused
      permission-walk and macOS ACL-batch regressions without weakening symlink,
      hard-link, owner, or extant-file rejection. After restart, a hosted Bob sync
      completed while 40 concurrent integration/Course reads all returned `200`.
- [x] Disconnected and reconnected each live test profile independently. Both remote
      revocations completed, both replacement pairings used the real account JWT, both
      syncs completed, and each profile retained its original private Course identity.
- [x] Deployed the consent route to
      `https://blueway-teeechr-beta--e8zhh5g89c.expo.app/teeechr-connect` and verified
      its included/excluded/retention copy. The preview correctly disables approval
      when signed out.

### Remaining enablement checklist

- [ ] Complete a fresh full migration replay in disposable Supabase/Postgres and a
      pre-migration logical dump. Docker was unavailable for the CLI reset/dump; the
      hosted forward ledger and idempotent repair paths were checked instead.
- [ ] Complete the signed-in consent click in BlueWay web/native UI. The deployed web
      build has no supported sign-in flow, so current approval proof used the same real
      user JWT against the deployed user-auth Edge Function rather than injecting a
      browser session or adding a test backdoor.
- [ ] Disable the disposable client/accounts when the proof packet is closed. They remain
      enabled temporarily so the signed-in browser/native and real-transcript gaps can be
      exercised without reprovisioning identities.
- [ ] Produce a completed account-owned Class Capture transcript through a real
      provider. The database/export/TEEECHR ingestion contract is deployed, but the
      transcription worker/webhook/completion/deletion-retention runtime is not built
      and the hosted project currently has zero transcript rows.
- [ ] Prove malicious imported instructions remain ordinary Course Knowledge text
      through the exact Chat/RAG runtime with no tool or cross-workspace authority.
- [ ] Run a paid chat/embedding smoke only after provider credentials/model choice are
      explicitly available; none are configured in this TEEECHR checkout.
- [ ] Push both reviewed branches and record remote commit identities after final
      backcheck. TEEECHR must target the user's `fork`, never upstream `origin`.

Current classification: **hosted database/Edge and two-owner API pairing/sync pass;
signed-in browser, real transcription/provider, native device, TEEECHR hosting, and
final push remain separate open proof surfaces**.

### Local reviewed commits

TEEECHR (`feature/teeechr-v152-phase3-blueway-integration`):

- `42166282` — private BlueWay Course sync, credential, repository, API, and tests;
- `9d7c0337` — BlueWay Settings UI and stale-identity response fencing;
- `96e2a227` — contract, proof ledger, and changelog.
- `dcc08fa4` — runtime credential/identity hardening and SQLite-sidecar permission repair.

BlueWay (pre-enablement commits, originally on `feature/teeechr-blueway-integration`):

- `28f16fc` — private delegated authority, bounded academic export, and tests;
- `a35cc5d` — signed-in consent route, account-switch fencing, and changelog.
- `19d8b53` — exact reviewed default-off Class Capture transcription foundation;
- `b1551dc` — hosted SQL/Edge security repairs and completed-transcript export.

The runtime repairs are now committed locally after the final backcheck; hosted
migrations, three Edge Functions, the seeded client, and the Expo preview are enabled
as recorded above. No branch has yet been pushed or merged. The canonical BlueWay
Class Capture checkout remained untouched; its exact default-off transcription patch
was copied byte-for-byte into the isolated integration worktree before hosted migration.
