# Vertical Slice B1 Implementation Receipt

Status:

- SOURCE / TEST / BUILD PROVEN
- BROWSER RUNTIME OPEN — desktop functional flow, owner isolation, loading,
  empty, failed-source, upload-surface, and request-count proof captured;
  narrow-mobile and keyboard/focus proof remain open because the in-app Browser
  viewport/focus harness did not apply the requested controls.
- CHAT PARKED

Closeout verdict: `BLOCKED_MISSING_PROOF`

Branch: `feature/teeechr-web-course-hub-slice-b1`

Base: `ffa8233763ad621c170575f27f41d7fdec623691`

Initial B1 HEAD: `31351e84`

Final implementation commit: `b91b1315` (`fix(classes): close Course Hub browser audit gaps`)

## Runtime

- Browser: Codex In-app Browser, local authenticated runtime.
- Frontend: `http://localhost:3812`, Next.js `16.2.3` development server.
- Backend: `http://127.0.0.1:8031`, Uvicorn, `AUTH_ENABLED=true`.
- Node: `v22.23.2`; npm: `10.9.8`.
- Python: `3.11.15`, `/Users/home/.codex/runtimes/teeechr-b1-python311`.
- Disposable runtime root: `/tmp/teeechr-b1-browser.l0kAUG`.

The runtime root is an execution location only. Durable browser evidence is
under `docs/verification/2026-08-07-teeechr-b1-browser/`.

## Fixtures

- User A `user_a` (`u_a199c17d13c342059ddcd892b05145ca`): Biology 101
  (`crs_2990d73a0be64dd3864b9375b4b9f57a`) is BlueWay-connected with term
  `Fall 2026`; Psychology 201 (`crs_ac18fd6c89644bf2afc40915345c3ba7`) is a
  separate manual Course with null term metadata.
- User B `user_b` (`u_e42fe49aa6db4bab8bf5cfcd525b69b3`): separate Course
  `crs_043f88620ad04d9f9b5ccf3a3dcd9c5b`.
- User C `user_c` (`u_feb4b81d44e245bc997fd3738b5a824c`): zero Courses.
- Biology failed-source fixture: `lab-notes.pdf`, source
  `src_0655185fe38d42a385255e3fe7e73801`, state `failed`.

No passwords or auth tokens are stored in the repository.

## Browser campaign

User A completed the authenticated flow through the real local frontend and
backend:

1. Sign in and land on `/classes`; Biology 101 and Psychology 201 render as
   two distinct Course cards.
2. Open `/classes/crs_2990d73a0be64dd3864b9375b4b9f57a`; Biology title and
   `Term: Fall 2026` render.
3. Open `/classes/{courseId}/materials`; the loading state, failed source row,
   and `Attach source` upload surface render.
4. Return to the Course Hub, open Practice at `/practice`, and return with
   browser history; Biology remains the selected Course.
5. Open Review at `/flashcards`, and return with browser history; Biology
   remains the selected Course.
6. Refresh the Course Hub with `Ctrl+R`; title and term remain present.
7. Reopen Biology by direct URL; the same title and term render.
8. Select `Back to Classes`; both User A Course cards render again.

Authorization and state checks:

- User B opening User A's Biology URL receives `Course resource not found` in a
  truthful alert and does not see the Course header or destinations.
- User C sees `No Classes yet` and the private Course creation prompt.
- User A's Biology and Psychology rows retain separate immutable Course IDs;
  only Biology has the provider term projection, while Psychology remains
  `Term not linked yet`.

Durable screenshots:

- `desktop-classes.jpg`
- `desktop-biology-overview.jpg`
- `materials-loading.jpg`
- `desktop-materials-failed.jpg`
- `materials-upload.jpg`
- `zero-courses.jpg`
- `unauthorized-course.jpg`
- `responsive-attempt-fixed-viewport-classes.jpg`
- `responsive-attempt-fixed-viewport-overview.jpg`
- `responsive-attempt-fixed-viewport-materials.jpg`
- `keyboard-focus-attempt.jpg`

## Performance check

A fresh User A `/classes` navigation was traced with backend access logging. It
issued exactly one `GET /api/v1/courses` owner-scoped summary request and no
per-Course source-count, mapping, or provider requests. The first trace found
two identical summary calls caused by initial identity resolution; the final
implementation commit removes that duplicate by keeping the Course refresh
callback stable.

Durable trace: `verification/2026-08-07-teeechr-b1-browser/request-count-classes.txt`.

## Responsive and keyboard/focus boundary

The campaign requested a `390x844` narrow viewport. The Codex In-app Browser
accepted the capability call but continued to report `window.innerWidth=845`,
`window.innerHeight=998`, and `max-width:767px=false`; a fresh tab reported a
fixed `1280x720` viewport. The retained fixed-viewport images are diagnostic
attempts, not accepted narrow-mobile proof. The source still contains the
responsive contract: AppShell's `max-md` drawer and Course cards'
`md:grid-cols-2` breakpoint.

The Course-card links carry `focus-visible:ring-2` styling and the mobile shell
marks a closed drawer `inert`. Browser interaction did not produce a durable
focused-element assertion in the in-app harness; `keyboard-focus-attempt.jpg`
is retained as diagnostic evidence, not as an accessibility-release claim.

Durable boundary note: `verification/2026-08-07-teeechr-b1-browser/responsive-capability-check.txt`.

## Validation

Backend baseline accepted from the B1 packet:

- `3859 passed, 3 failed, 8 skipped, 10 warnings`.
- The three deferred failures are the pre-existing Chat authorization nodes:
  `tests/agents/chat/test_agent_loop.py::test_loaded_deferred_tool_is_authorized_on_next_round_only`,
  `tests/agents/chat/test_cli_app_wiring.py::test_an_unrelated_tool_is_not_handed_a_sandbox`,
  and `tests/agents/chat/test_context_budget.py::test_forced_finish_still_reports_the_tools_the_turn_carried`.
- No Course ownership, Course list/read, Course identity, source, or B1 route
  failure was added.

Final web validation after `b91b1315`:

- `npm run test:node`: `417 passed, 0 failed`.
- `npm run lint`: exit `0`, `0 errors`, `230 warnings`.
- `npx tsc --noEmit`: exit `0`.
- `npm run build`: exit `0`; Next.js `16.2.3`; `/classes`,
  `/classes/[courseId]`, and `/classes/[courseId]/materials` generated.

## Files and commits

The implementation commit contains only the two closeout fixes:

- `web/context/CourseContext.tsx` — one owner-scoped Course summary request on
  initial `/classes` load.
- `web/components/courses/CourseOverview.tsx` — truthful unauthorized Course
  error instead of an indefinite loading state.

The receipt and durable evidence are separate closeout documentation changes.
The pre-existing uncommitted Chat test edits remain outside these commits and
were not staged or changed by this closeout.

## Push state and remaining gates

- Pushed successfully to `fork/feature/teeechr-web-course-hub-slice-b1`.
- Remote branch now contains commit `428c5bfb` and tracks the local feature
  branch.
- `origin` and all canonical/main branches remain untouched.
- The local worktree still has the two pre-existing Chat test edits; they were
  not staged, committed, or pushed by this closeout.

B2 must not claim complete browser closure until a working browser target
supplies the requested narrow-mobile and keyboard/focus proof.

This receipt does not claim hosted Supabase, hosted TEEECHR, physical iPhone,
TestFlight, production secrets, VoiceOver, Dynamic Type, migration-zero
bootstrap, release/rollback/monitoring, or production deployment proof.
