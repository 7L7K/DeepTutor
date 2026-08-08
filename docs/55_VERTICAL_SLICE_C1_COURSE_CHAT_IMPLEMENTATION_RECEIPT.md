# Vertical Slice C1 — Course Chat Implementation Receipt

## Status

```text
SOURCE / TEST / BUILD / LOCAL AUTHENTICATED BROWSER PROVEN
HOSTED / PHYSICAL DEVICE / RELEASE OPEN
```

C1 is complete for the bounded local web slice. The authoritative learner
journey is now:

```text
/classes/{courseId}
    -> owner-authorized Course Chat route
    -> server-derived current ready sources for that exact Course
    -> existing unified Chat runtime
    -> supported answer or bounded abstention/failure
    -> validated versioned Course citation
    -> persisted owner + Course + session receipt
    -> refresh/direct-link reopen under the same Course
```

No BlueWay checkout, hosted environment, production configuration, secret,
frozen migration, or canonical integration branch was modified. C1 did not
add a database migration or a second Chat engine.

## Repository identity

- Worktree: `/Users/home/Desktop/2k26/teeech/DeepTutor-course-chat-c1`
- Branch: `feature/teeechr-course-chat-c1`
- Base: `794651672b038f99e764b12ae50786dd6aefbc61`
- Final implementation/proof HEAD: `1d6a36e5f76ce3db53e0e5971cc890945aaaa143`
- Intended publication target:
  `fork/feature/teeechr-course-chat-c1`
- Upstream `origin`: not a push target for this slice
- Merge state: unmerged
- Luna delegation: unavailable in this session; the primary agent completed
  the bounded closeout as authorized.

## Product boundary delivered

TEEECHR web owns the full learning workspace. BlueWay remains outside this
worktree and remains a Course-entry/context product.

C1 delivers only:

- Course-scoped Chat entry and direct-link routes;
- owner-, Course-, and session-bound unified Chat;
- deterministic ready/processing/failed/no-materials/partial readiness;
- ready-source-only provider context;
- unsupported-answer abstention;
- durable validated Course citation anchors;
- historical citation display using the title snapshot;
- bounded provider-unavailable and unauthorized states; and
- human-readable academic term presentation while retaining the normalized
  term identity underneath.

C1 does not deliver Chat-to-Practice, Results, remediation, Study Sessions,
Progress, syllabus parsing, recommendations, hosted deployment, physical
device proof, or release proof.

## Exact routes and APIs

### Browser routes

| Route | Implementation |
| --- | --- |
| `/classes` | `web/app/(workspace)/classes/page.tsx` -> `web/components/courses/ClassesHome.tsx` |
| `/classes/{courseId}` | `web/app/(workspace)/classes/[courseId]/page.tsx` -> `web/components/courses/CourseOverview.tsx` |
| `/classes/{courseId}/chat` | `web/app/(workspace)/classes/[courseId]/chat/page.tsx` -> `web/components/courses/CourseChatRoute.tsx` |
| `/classes/{courseId}/chat/{sessionId}` | `web/app/(workspace)/classes/[courseId]/chat/[sessionId]/page.tsx` -> the same Course wrapper and unified Chat host |
| `/classes/{courseId}/materials` | existing Course Materials route and upload/progress UI |

### Server routes used by the slice

| Contract | Route |
| --- | --- |
| Owner Course list | `GET /api/v1/courses` |
| Exact Course read | `GET /api/v1/courses/{courseId}` |
| Chat readiness | `GET /api/v1/courses/{courseId}/chat-readiness` |
| Real processing fixture upload | `POST /api/v1/courses/{courseId}/sources` |
| Session read/reopen | `GET /api/v1/sessions/{sessionId}` |
| Turn start/resume | authenticated `/api/v1/ws` with exact `course_id` |

`deeptutor/api/routers/unified_ws.py` rejects a missing, foreign, or
Course-mismatched session through the same bounded not-found behavior.
`deeptutor/courses/service.py` derives the provider view from the current
authenticated Course; browser-provided owner or arbitrary source authority is
not trusted.

## Source-readiness and grounding contract

The authoritative projection is `CourseChatReadiness` in
`deeptutor/courses/chat_contract.py`:

- `ready`: current ready source, eligible for the Course provider view;
- `processing`: unavailable until a live source task becomes ready;
- `failed`: unavailable and surfaced truthfully;
- `archived` or superseded: excluded from new turns;
- `partial`: Chat is allowed only with the ready subset and discloses the
  unavailable count; and
- zero ready: no provider call and no Chat session creation.

The authenticated final fixture proved:

```text
User A: c1_alice
  Biology 101 / Fall 2026
    1 ready + 1 processing + 1 failed
    deterministic fact: ATP stores usable cellular energy
  Psychology 201 / Fall 2026
    distinct ready source
    deterministic fact: working memory temporarily holds information
  Empty Course Lab
    zero sources
  Processing Course
    real authenticated upload with a live backend task
  Failed Course
    failed source only
  Unsupported Question Course
    ready source with no supporting retrieval fragment
  Provider Unavailable Course
    ready source with a deterministic terminal provider event

User B: c1_bob
  Bob Private Chemistry

User C: c1_carol
  zero Courses
```

The generated opaque user, Course, source, session, and turn IDs are preserved
in `backend/fixture.json`, `backend/browser-state.json`,
`backend/backend-receipt.json`, and
`backend/provider-unavailable-terminal-frames.ndjson` under the verification
directory. They are synthetic local proof identities, not production data.

## Citation schema and persistence

No new table was required. Course citation anchors are validated and stored
inside the existing durable assistant-message event JSON. The versioned shape
is implemented in `deeptutor/courses/chat_contract.py` and contains:

```text
schema_version
course_id
source_id
source_revision
source_content_hash
source_title_snapshot
locator_type
locator_value
retrieval_fragment_id
```

Locator and fragment values remain null when retrieval does not provide them;
C1 never invents a page, slide, section, or timestamp. Source ID,
revision/hash, and title snapshot preserve historical identity. The browser
renders the human title snapshot and does not expose the physical KB name,
local path, database path, or raw provider path.

`deeptutor/services/session/turn_runtime.py` now also persists an event-only
assistant receipt for a terminal Course Chat provider failure. Generic Chat
retains its existing rule against persisting blank assistant answers. The
failed Course `done` event carries the durable user/assistant message IDs, and
`web/context/UnifiedChatContext.tsx` refreshes that exact failed session after
the receipt commits. This closes the route-remount race that could otherwise
erase the visible provider-unavailable card.

## Automated validation

All commands used the supported local runtimes:

```text
Node  v22.23.2  (/opt/homebrew/opt/node@22/bin)
npm   10.9.8
Python 3.11.15 (/Users/home/.codex/runtimes/teeechr-b1-python311/bin/python)
```

### Backend

```text
/Users/home/.codex/runtimes/teeechr-b1-python311/bin/python -m pytest -q tests
3885 passed, 8 skipped, 10 warnings in 538.02s
```

Result: zero failures. The warnings are the pre-existing pytest temporary
directory cleanup warnings. The full output is archived at
`backend/pytest-full.txt`.

Focused contracts include:

- `tests/courses/test_course_chat_c1_contract.py`
- `tests/courses/test_deterministic_provider_contract.py`
- `tests/api/test_unified_ws_turn_runtime.py`
- owner/source/session/authorization tests under `tests/courses`,
  `tests/multi_user`, and `tests/agents/chat`

### Web

Commands ran from `web/` with Node 22 explicitly on `PATH`:

```text
npm run test:node
430 passed, 0 failed

npm run lint
0 errors, 241 warnings

npx tsc --noEmit
passed with no TypeScript diagnostics

npm run build
passed; Next.js 16.2.3 production build
```

The build route table contains:

```text
/classes
/classes/[courseId]
/classes/[courseId]/chat
/classes/[courseId]/chat/[sessionId]
/classes/[courseId]/materials
```

The 241 lint warnings are accepted pre-existing i18n/image/unused-directive
warnings; lint exits zero. C1 introduced no lint error.

## Local authenticated browser proof

Command:

```text
./scripts/test-course-chat-c1
```

Final committed-source result:

```text
4 passed in 14.0s
branch=feature/teeechr-course-chat-c1
head=1d6a36e5f76ce3db53e0e5971cc890945aaaa143
```

The campaign proved:

- `/classes` lists Biology and Psychology with one owner-scoped Course list
  request on initial landing;
- Biology renders `Fall 2026`, mixed-source disclosure, the exact grounded
  answer, and the Biology citation;
- refresh, Back to Course, and direct-link reopen retain Course, session,
  answer, and citation;
- the 390×844 viewport keeps the header, answer, citation, and composer inside
  the viewport;
- keyboard Tab/Enter reaches the Course Chat link and then the composer with
  visible focus;
- Psychology produces a distinct answer and source citation; neither
  Biology's source ID nor ATP answer appears in the Psychology session, and
  vice versa;
- a Biology session cannot be opened under the Psychology route;
- User B cannot read User A's Course or session URL and receives the same
  bounded not-found result;
- the no-materials, live-processing-only, and failed-only routes show truthful
  bounded states, render no Chat composer, invoke no Chat provider, and create
  zero Chat sessions;
- the unsupported question returns the exact bounded abstention with no
  citation;
- the provider-unavailable turn persists a two-message Course session and
  remains visible as a terminal error card; and
- User C receives the truthful zero-Course Classes state.

The final backend receipt independently confirms:

- Biology and Psychology have different Course/source/KB identities;
- both citations preserve revision `2`, source content hashes, and title
  snapshots;
- no raw provider path is persisted;
- blocked Course session counts are all zero;
- the provider failure has `message_count=2` and `turn_terminal=true`; and
- `classes_landing_course_list_calls=1`.

## Screenshot and evidence index

Verification root:

`docs/verification/2026-08-08-teeechr-course-chat-c1/`

Required screenshots:

- `screenshots/course-overview-desktop.png`
- `screenshots/course-chat-grounded-desktop.png`
- `screenshots/course-chat-grounded-mobile.png`
- `screenshots/course-chat-psychology-grounded.png`
- `screenshots/course-chat-session-mismatch.png`
- `screenshots/course-chat-zero-ready.png`
- `screenshots/course-chat-processing-only.png`
- `screenshots/course-chat-failed-only.png`
- `screenshots/course-chat-unsupported.png`
- `screenshots/course-chat-provider-unavailable.png`
- `screenshots/course-chat-foreign-denied.png`
- `screenshots/classes-zero-course.png`

Machine-readable and command evidence:

- `runtime.txt`
- `playwright-output.txt`
- `backend/fixture.json`
- `backend/browser-state.json`
- `backend/backend-receipt.json`
- `backend/provider-unavailable-terminal-frames.ndjson`
- `backend/pytest-full.txt`
- `web-test-node.txt`
- `web-lint.txt`
- `web-typecheck.txt`
- `web-build.txt`
- `CHECKSUMS.sha256`

`CHECKSUMS.sha256` covers every archived evidence file except itself.

## Commit chain

The C1 branch keeps tests, server contracts, web surface, repair work, and
proof separate:

```text
dbae0199 docs(c1): record Course Chat execution audit
71a5377a test(chat): lock Course grounding and citation contracts
528486bd feat(chat): enforce Course material readiness
a0955afa feat(chat): persist validated Course citations
b4a56b43 feat(chat): add exact Course Chat workspace
58f42aac fix(chat): preserve legacy regeneration snapshots
643da253 test(chat): expect stale ingestion to fail closed
4c700b0b test(chat): assert sanitized Course citation receipt
833080f4 fix(chat): keep deterministic Course proof provider hermetic
7d5ac8cb fix(classes): render human academic term labels
d1205a4b fix(chat): present human Course source references
fe9ae485 test(e2e): prove authenticated Course Chat closeout
84ec7c4a fix(chat): persist Course provider failure receipts
1d6a36e5 test(e2e): close Course Chat runtime state matrix
```

## Publication state

At receipt creation, the intended push is pending:

```text
fork/feature/teeechr-course-chat-c1
```

Do not push this branch to upstream `origin`, do not merge it into the current
integration branch, and do not start C2 from an unpublished local-only head.
The final push verification and docs closeout commit are recorded in the
follow-up publication update to this receipt.

## Closeout verdict and remaining risks

Closeout verdict: `PASS_WITH_PARKED_FOLLOWUPS`.

C1's source, tests, build, local authenticated browser, owner isolation,
Course isolation, responsive layout, focus order, and durable proof are
closed. These remain explicitly open and do not invalidate the local slice:

- hosted/provider environment proof;
- production model/provider error behavior;
- physical-device proof;
- release/TestFlight/deployment proof;
- production secret rotation and operations;
- dependency-audit remediation;
- the accepted 241-warning lint backlog; and
- accessibility work beyond the bounded keyboard/focus and responsive checks
  captured here.

Next slice remains C2 only after this branch and receipt are published to the
fork. C2 must not reopen C1's owner/Course/source/session identity contracts.
