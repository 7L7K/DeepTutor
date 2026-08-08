# Vertical Slice C1 — Course Chat Execution Packet

## Status and boundary

This packet is the Phase 1 read-only audit for C1. It freezes the current
route, data, authorization, grounding, citation, persistence, and test seams
before product code is changed.

C1 goal:

```text
/classes/{courseId}
    -> Course Chat entry
    -> Course-scoped Chat session
    -> server-authorized ready Course sources only
    -> truthful source references
    -> refresh/reopen without losing Course identity
```

C1 does not build BlueWay SSO, hosted integration, syllabus parsing, Course
timeline intelligence, Practice, Review, Progress, recommendations, Study
Sessions, or a new provider architecture. BlueWay and the B2 launch lane are
outside this worktree.

The C1 implementation must not expose Course Chat as complete until the
Course-source readiness, owner isolation, session binding, citation, and
runtime tests below are green.

## Repository identity

- Worktree: `/Users/home/Desktop/2k26/teeech/DeepTutor-course-chat-c1`
- Branch: `feature/teeechr-course-chat-c1`
- Audit base and current HEAD: `794651672b038f99e764b12ae50786dd6aefbc61`
- Base commit: the pushed C0 receipt commit
  `docs(c0): record Chat authorization closeout`
- Fork remote: `https://github.com/7L7K/DeepTutor.git`
- Upstream remote: `https://github.com/HKUDS/DeepTutor.git`
- Luna delegation: unavailable in this session; the primary agent performed
  the bounded audit as authorized.
- Product source changes before this packet: none.

## Phase 0 accepted baseline

The C1 worktree was created from the final pushed C0 commit and the untouched
baseline was rerun with the supported local runtimes.

### Runtime setup

- Node: `v22.23.2` from `/opt/homebrew/opt/node@22/bin`
- npm: `10.9.8`
- Python: `3.11.15` from
  `/Users/home/.codex/runtimes/teeechr-b1-python311/bin/python`
- Web dependencies: installed with `npm ci --legacy-peer-deps`; the lockfile
  is unchanged.
- Local Python settings are ignored, non-secret runtime settings only. No
  credentials, provider keys, `auth.json`, hosted values, or production
  configuration were copied.

### Backend proof

```text
/Users/home/.codex/runtimes/teeechr-b1-python311/bin/python -m pytest -q tests
3869 passed, 8 skipped, 10 warnings in 498.07s

/Users/home/.codex/runtimes/teeechr-b1-python311/bin/python -m pytest -q tests/agents/chat tests/courses tests/multi_user
567 passed, 7 warnings in 291.11s
```

There were zero backend failures. The warnings were pytest temporary-directory
cleanup warnings and did not change test outcomes.

### Web proof

All commands below ran with the Node 22 runtime above from `web/`:

```text
npm run test:node
423 passed, fail 0, skip 0, todo 0

npm run lint
0 errors, 234 warnings

npx tsc --noEmit
passed; no diagnostics

npm run build
passed; production build completed
```

The build emitted the existing authenticated Course routes, including
`/classes`, `/classes/[courseId]`, `/classes/[courseId]/materials`, and the
existing `/home/[[...sessionId]]` Chat route.

The install reported 11 existing npm audit findings (1 low, 4 moderate, 6
high). They are parked as dependency-security work; C1 does not run
`npm audit fix` or change dependency files.

## Current route tree

### Browser routes

| Route | Current implementation | C1 disposition |
| --- | --- | --- |
| `/classes` | `web/app/(workspace)/classes/page.tsx:1-4` -> `ClassesHome` | REUSE; add the Course Chat destination only after the entry contract is defined |
| `/classes/{courseId}` | `web/app/(workspace)/classes/[courseId]/page.tsx:1-4` -> `CourseOverview` | EXTEND; add a real Course Chat destination and preserve current truthful unavailable states |
| `/classes/{courseId}/materials` | `web/app/(workspace)/classes/[courseId]/materials/page.tsx:1-4` -> `CourseMaterials` | REUSE; its source states are the readiness surface |
| `/home` and `/home/{sessionId}` | `web/app/(workspace)/home/[[...sessionId]]/page.tsx` | REUSE through a Course-scoped entry wrapper; do not fork the Chat engine |
| `/practice` | existing web route | PARK for C2; Course Chat must not expose it as a Chat completion requirement |
| `/flashcards` | existing web route | PARK for C2 |
| `/launch/blueway` | existing B2 launch route | OUT OF SCOPE; do not modify BlueWay or B2 |

### Authenticated landing behavior

The authenticated Course landing route is `/classes`. `ClassesHome` loads the
owner-scoped Course summary through `useCourses` at
`web/components/courses/ClassesHome.tsx:6`, renders Course cards at lines
`21-25`, filters academic Courses at `54-69`, and renders the truthful zero
state at `129-169`. Its Course links are stable IDs:
`/classes/${encodeURIComponent(course.id)}`.

The current Course Overview loads the route parameter with `useParams`, calls
`getCourse(courseId)`, and selects the loaded Course at
`web/components/courses/CourseOverview.tsx:15-45`. It renders not-found/error
states and the Classes return link at `63-112`. Materials is the only currently
working source destination at `128-160`; Practice and Review remain existing
destinations while Chat is deliberately held out at `163-177`.

## Current data and authorization flow

### Course identity and owner isolation

1. `web/context/CourseContext.tsx:55-70` resolves the authenticated user and
   clears the prior user's local Course selection when identity changes.
2. `web/context/CourseContext.tsx:73-93` makes one owner-scoped
   `listCourses()` request, validates any stored active Course against that
   response, and drops invalid or archived selections.
3. `web/lib/course-api.ts:47-59` maps the list/read API to
   `GET /api/v1/courses` and `GET /api/v1/courses/{courseId}`.
4. `deeptutor/api/main.py:429-451` mounts the Course router behind the
   authenticated dependency.
5. `deeptutor/api/routers/courses.py:545-567` implements create/list/read.
6. `deeptutor/courses/service.py:191-201` requires the current authenticated
   user and opens that user's private Course database.
7. `deeptutor/courses/repository.py:209-230` filters list/read by
   `owner_user_id`; a foreign Course becomes the same not-found outcome rather
   than an ID oracle.
8. `deeptutor/courses/models.py:14-35` defines the stable Course identity,
   title, optional term, workspace kind, lifecycle state, revision, and write
   epoch. `term` is an unambiguous mapped term, not a title-derived guess.

### Course source readiness

- `deeptutor/courses/models.py:38-53` defines source identity, display name,
  state (`processing`, `ready`, `failed`, `archived`), manifest, content hash,
  revision, operation, and replacement relationship.
- `deeptutor/api/routers/courses.py:2139-2222` exposes owner-scoped source
  list/read/upload/progress/archive endpoints.
- `deeptutor/courses/service.py:134-167` lists sources and reconciles an
  abandoned processing operation without adjudicating another Course.
- `deeptutor/courses/service.py:249-287` is the authoritative turn resolver:
  it selects only current `ready` sources, removes superseded sources, and
  rejects stale or mismatched regeneration provenance.
- `deeptutor/courses/service.py:289-341` derives opaque per-source Course KB
  shards, rejects client-supplied KB authority, and stores the Course/source
  provenance snapshot.
- `deeptutor/courses/learner_actions.py:19-39` contains the equivalent bounded
  ready-current-source rule used by other Course learner actions.

Current backend behavior is safe for authorization but incomplete for the C1
user contract when a Course has zero ready sources: the resolver derives an
empty source/KB set and the deterministic test provider can emit a
“no authorized Course source” answer. C1 must add a truthful UI/runtime state
and tests so a learner never mistakes an ungrounded response for a
source-grounded Course answer.

### Session and Course binding

- `web/lib/course-selection.ts:33-55` treats a persisted session's Course ID
  as authoritative; only a new draft inherits the selected Course.
- `web/context/UnifiedChatContext.tsx:245-269` stores the Course ID alongside
  the session entry; `:337-357` carries it into optimistic user messages.
- `web/context/UnifiedChatContext.tsx:1359-1519` computes the session-bound
  Course ID and includes `course_id` in the `start_turn` payload.
- `web/context/UnifiedChatContext.tsx:1215-1258` rehydrates persisted sessions,
  including `session.course_id`, and the route page's load path is at
  `web/app/(workspace)/home/[[...sessionId]]/page.tsx:956-1055`.
- `web/lib/unified-ws.ts:52-147` defines the turn/session messages and the
  optional Course ID; `:158-221` retains Course identity through resume and
  reconnect.
- `deeptutor/api/routers/sessions.py:123-190` lists and reads owner sessions;
  foreign sessions return `404 Session not found`.
- `deeptutor/api/routers/sessions.py:193-259` allows Course session metadata
  writes only while the Course is active; Course sessions are retained rather
  than deleted at `217-232`.
- `deeptutor/api/routers/unified_ws.py:44-113` authenticates the WebSocket,
  chooses the personal runtime for Course turns, and requires the persisted
  session Course ID to equal the requested Course ID.
- `deeptutor/api/routers/unified_ws.py:144-183` applies the same binding to
  turn/session subscriptions; `:255-323` applies it to active-turn checks and
  cancellation; `:366-403` applies it to regeneration.

### Turn authorization and server-derived grounding

`deeptutor/courses/service.py:219-341` is the Course Chat server seam. It:

- rejects General Study and archived Courses;
- allows only `chat` and `mastery_path` capabilities;
- rejects generic attachments, notebooks, history, books, memory, and other
  cross-workspace references;
- resolves current ready source IDs from the authenticated Course;
- rejects client-provided KB names that do not exactly equal the derived
  source shards;
- limits Course Chat's built-in tools to server-authorized RAG; and
- persists Course revision, source IDs, source revisions, and source hashes in
  the turn snapshot.

The runtime records that snapshot in
`deeptutor/services/session/turn_runtime.py:159-211` and preserves it for
regeneration at `:1044-1061`. This is the authoritative grounding identity;
the browser must not construct a second Course or select a provider KB itself.

## Citation and source presentation audit

### What is already reusable

- `deeptutor/core/stream.py:28-47` defines the `sources` stream event and
  structured event metadata.
- `deeptutor/core/stream_bus.py:215-229` emits source rows into a stream event.
- `deeptutor/agents/chat/agent_loop.py:203-215` emits accumulated tool source
  rows at the end of the agent loop.
- `deeptutor/courses/deterministic_provider.py:109-143` emits a local source
  row containing `type`, knowledge-base name, and source path when a
  server-authorized Course shard is used. This provider is explicitly test
  only and is not a production provider option.
- `web/components/chat/home/TracePanels.tsx:1002-1004` collects source rows
  from trace metadata and `:1155-1165` renders a compact source label.
- `web/lib/markdown-display.ts:365-535` and
  `web/components/common/SimpleMarkdownRenderer.tsx:351-406` already support
  citation-style markdown links and research/RAG/web citation labels.

### C1 gap that must be closed

The current renderer does not yet define a Course citation contract. The
existing trace source label is not a durable, clickable Course-source receipt,
and the markdown citation helper recognizes research IDs and generic
`rag-*`/`web-*` style references rather than the Course source manifest.

C1 must therefore extend, rather than replace, the existing stream/render
machinery with a Course citation record whose fields are derived only from the
persisted server source snapshot and actual source event, for example:

```text
course_source_id
display_name
content_sha256 or source revision
manifest locator when supplied
course_id
```

The UI may display a compact source name and locator, but it must not invent a
page, paragraph, source ID, or citation target. If an answer has no actual
source event/reference, it must render as ungrounded or unavailable rather than
claiming a citation. C1 should add a stable source anchor and a durable
reopen/refresh test; full document-preview UX can remain a later slice.

## Route decision and minimal change plan

### Canonical C1 route

Add a Course-scoped Chat entry under:

```text
/classes/{courseId}/chat
/classes/{courseId}/chat/{sessionId}
```

The route is the learner-facing Course entry. It must first resolve the
owner-scoped Course, show its title/term and source-readiness state, and then
hand the conversation to the existing unified Chat engine. A session URL must
remain explicitly Course-scoped and must reject a session whose persisted
`course_id` does not equal the route Course ID.

### Classification

| Surface | Decision | Reason |
| --- | --- | --- |
| Course Chat route entry | WRAP | Add a Course-owned entry and guard; do not fork the existing Chat runtime |
| Existing `/home/[[...sessionId]]` Chat host | REUSE / small EXTEND | Keep the tested composer, stream, reconnect, branch, and session UI |
| `CourseOverview` | EXTEND | Add only the now-real Course Chat destination and truthful readiness label |
| `CourseContext` and `course-selection` | EXTEND | Bind the route Course explicitly and prevent stale per-user selection from winning |
| `UnifiedChatContext` | EXTEND | Rehydrate and send the explicit Course/session identity through every turn control path |
| `resolve_course_turn_payload` | REUSE / test EXTEND | Keep server-derived source authority; add zero-ready-source behavior tests if needed |
| Course repository/service | REUSE | Owner isolation and source state semantics already exist and passed baseline |
| Stream source metadata | EXTEND | Add a truthful Course-source citation/anchor shape |
| Practice, Review, Progress, recommendations | PARK | C2 or later; no dead destinations from C1 Chat |

The implementation should prefer a shared Chat surface/component or a thin
entry wrapper over duplicating `page.tsx`. If the current page cannot be
reused without routing through ambient localStorage selection, refactor only
the smallest host boundary needed to accept an explicit `courseId` and
optional `sessionId`. The URL and server binding remain authoritative; local
selection is only a convenience for a new draft.

### Ordered implementation gates

1. Add route-level owner/identity tests and a stable Course Chat route test.
2. Add the zero-ready-source state and ready-source-only send/grounding test.
3. Make the Course Overview Chat destination real only when those states are
   represented truthfully.
4. Reuse the existing session/WS path and prove initial turn, refresh, reopen,
   and wrong-Course session denial.
5. Extend source events/rendering into truthful Course citations and test a
   citation target from actual source metadata.
6. Run the full backend and web gates, then perform local browser proof. No
   hosted, device, production, or BlueWay proof is implied by this packet.

## Failure-state contract

| Condition | Required C1 behavior |
| --- | --- |
| Unauthenticated | Use the existing auth/login boundary; do not leak Course existence |
| Foreign or missing Course ID | Not-found/unauthorized state; no session or source details |
| Foreign or mismatched session ID | Not-found/unauthorized Course Chat state; no fallback to generic Chat |
| Archived Course | Read-only history may be shown; new/regenerated turns are disabled and the server remains authoritative |
| Source processing | Show processing/readiness state; do not call it grounded-ready |
| Zero ready sources | Truthful “no ready Course sources” state; no fabricated Course answer or citation |
| Failed/archived/superseded source | Exclude from retrieval and citation authority |
| Source changed during regeneration | Surface provenance-unavailable failure and require a new grounded turn |
| WebSocket/session mismatch | Fail closed with the existing generic not-found/error boundary |
| Provider unavailable | Show an explicit unavailable/error state; never silently fall back to generic or hosted data |

## Test and fixture map

### Existing backend tests to reuse or extend

- `tests/courses/test_turn_contract.py:42-101` — server-derived Course
  resources, safe Course tool surface, and capabilities.
- `tests/courses/test_turn_contract.py:156-220` — Course RAG name
  authorization, ready-source selection, and exact regeneration provenance.
- `tests/courses/test_turn_contract.py:246-306` — cross-workspace fields,
  client KB injection, managed KB authority, and non-Course capability denial.
- `tests/api/test_course_sessions_api.py:42-78` — owner session listing/read,
  Course-session retention, and archived metadata-write denial.
- `tests/api/test_unified_ws_turn_runtime.py:94-124` — persisted Course/source
  provenance snapshot.
- `tests/api/test_unified_ws_turn_runtime.py:240-280` — live authorization
  revocation during a stream.
- `tests/api/test_unified_ws_turn_runtime.py:374-437` — replayable events,
  session materialization, and source manifest persistence.
- `tests/services/session/test_source_inventory.py` — branch-isolated source
  inventory and source identity behavior.
- `tests/services/session/test_turn_event_flush.py` — durable event flush and
  refresh/reopen evidence.
- `tests/multi_user/test_resource_isolation.py` — existing per-user resource
  isolation coverage.

C1 additions should target the route binding, zero-ready-source behavior,
Course citation record/anchor, and refresh/reopen path rather than re-testing
the whole repository layer through a new fixture system.

### Existing web tests to reuse or extend

- `web/tests/unified-ws-course-identity.test.ts` — explicit Course identity on
  reconnect/control messages.
- `web/tests/course-api.test.ts` — Course API response and source behavior.
- `web/tests/course-selection.test.ts` — per-user selection validation and
  persisted-session Course identity.
- `web/tests/session-activity.test.ts` — session activity/reopen UI behavior.
- `web/tests/e2e/blueway-launch-b2.spec.ts` — existing B2 browser fixture and
  user-isolation conventions; do not modify BlueWay or claim B2 as C1 proof.

### Required C1 fixtures and proof

Use one owner-private Course fixture with at least one ready source, one
processing/failed source state, a separate user with a foreign Course URL, and
a zero-ready-source/zero-Course account. Prove:

- `/classes/{courseId}/chat` resolves the exact owner Course;
- a first message creates a session bound to that Course;
- the answer's source record comes from the ready source event;
- refresh and `/classes/{courseId}/chat/{sessionId}` reopen the same Course and
  messages;
- another user cannot read the Course or session URL;
- no-ready-source behavior is truthful and fail-closed;
- a citation anchor points to actual source metadata, not a generated ID; and
- Course Chat does not issue a per-Course provider call or use a generic KB.

## Explicit implementation non-goals

- no BlueWay repository edits, launch changes, SSO, or B2 artifact rebuild;
- no TEEECHR Slice A or historical-migration edits;
- no frozen migration SQL changes;
- no hosted environment, production secret, or deployment changes;
- no general Chat redesign;
- no Course duplication or title/term matching heuristic;
- no syllabus parser, timeline intelligence, Study Sessions, Progress redesign,
  recommendation engine, Practice, or Review implementation;
- no claim of hosted, physical-device, TestFlight, release, or production proof.

## Start gate for C1 product code

The Phase 0 gate is green. Product code may begin only against this packet and
the minimal route/readiness/citation plan above. Before exposing the destination
from `CourseOverview`, the new focused tests for Course route authorization,
ready-source-only grounding, session reopen, and truthful citations must pass.
