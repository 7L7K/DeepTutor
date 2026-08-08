# Vertical Slice B2 Implementation Receipt

Status:

- SOURCE / TEST / BUILD PROVEN
- AUTHENTICATED LOCAL BROWSER RUNTIME PROVEN
- CHAT PARKED
- NATIVE IOS SIMULATOR OPEN: local QA environment values are not present in
  this shell, so a fresh B2 rebuild/install was not run

## Branch and base

- Branch: `feature/blueway-exact-course-launch-b2`
- TEEECHR worktree: `/Users/home/Desktop/2k26/teeech/DeepTutor-blueway-launch-b2`
- Base: `a7e05848`
- HEAD: `a7e05848` before the split B2 commits; implementation and proof files
  are currently uncommitted pending final closeout.
- BlueWay branch: `feature/teeechr-web-course-launch-b2`
- BlueWay base: `d401a7b1`

## Contract

BlueWay launches:

```text
/launch/blueway?external_course_id=<courseId>&external_term_id=<termId>
```

Normal TEEECHR authentication is preserved. The authenticated TEEECHR owner
resolves the exact connection and Course/term mapping from untrusted hints, and
only then may the web route redirect to `/classes/{internalCourseId}`. The hints
are not a token, session, SSO credential, or Course-creation request. The launch
route never falls back to title search, generic Chat, generic home, or Course
creation.

## Evidence ledger

| Surface | Result | Evidence |
| --- | --- | --- |
| Exact owner + Course + term resolver | PASS | `tests/integrations/blueway/test_course_launch.py` — 7 focused tests passed, including legacy termless and ambiguity cases |
| Login continuation | PASS | `web/tests/api-auth-redirect.test.ts`, `web/tests/proxy-policy.test.ts`, browser continuation journey |
| Web launch route | PASS | `web/app/launch/blueway/page.tsx`, `web/components/launch/BlueWayLaunch.tsx`, 5 browser journeys passed |
| BlueWay handoff URL and state gate | PASS | `tests/teeechrCourseLaunch.test.ts` — 4 tests passed |
| Desktop browser launch | PASS | `docs/verification/2026-08-08-teeechr-b2-browser/user-a-exact-course-overview.png`, Playwright 5/5 |
| Native iOS simulator launch | OPEN | Simulator and Maestro are available, but the B2 build requires local QA environment values absent from this shell; prior Slice A app is not B2 proof |
| Narrow mobile browser destination | PASS | `docs/verification/2026-08-08-teeechr-b2-browser/narrow-mobile-exact-course-overview.png`, `390x844` |
| Keyboard/focus | PASS | narrow campaign focused and activated `Back to Classes` with Enter |
| Hosted TEEECHR/Supabase | NOT RUN | explicitly outside B2 local proof |
| Physical iPhone/TestFlight/release | NOT RUN | explicitly outside B2 local proof |

## Final closeout fields

These fields are intentionally blank until the exact final build and fixtures
are exercised:

- Exact Node/npm/Python runtime: Node `v22.23.2`, npm `10.9.8`, Python
  `3.11.15` from `/Users/home/.codex/runtimes/teeechr-b1-python311`.
- TEEECHR backend/frontend ports and process identity: disposable Uvicorn on
  `127.0.0.1:8034`, Next.js dev server on `localhost:3814` for the final
  browser run.
- BlueWay simulator/device/build identity: not run; this receipt does not claim
  native simulator proof.
- User A Biology Course + Fall 2026 mapping: owner
  `u_c8ad6002528849c78d92509b766c8601`, internal Course
  `crs_f85ece2874f84e4ead17453bc306eb7`, external Course
  `blueway-b2-biology-101`, external term `Fall 2026`.
- User A manual Course: `crs_decffcb7619747fc95024fe01fe1bb50` (`Psychology 201`).
- User B foreign Course denial: browser received bounded `course_not_found` and
  never rendered Biology.
- User C/zero or unavailable state: browser rendered `No Classes yet`; provider
  and hosted-unavailable states remain covered by source/unit state tests, not
  browser runtime in this pass.
- Screenshots and traces: `docs/verification/2026-08-08-teeechr-b2-browser/`
  contains the exact Course, login continuation, foreign denial, zero Course,
  term mismatch, narrow mobile screenshot, Playwright report, fixture, and
  runtime logs.
- Test output and build output: web `423 passed`, lint exit `0` with `0 errors`
  and `234 warnings`, TypeScript exit `0`, production build exit `0`;
  BlueWay full suite `3,471 passed | 2 todo` across 335 files, focused launch
  tests `4 passed`, typecheck exit `0`; backend launch resolver `7 passed`;
  full backend `3,866 passed, 3 failed, 8 skipped` with exactly the three
  accepted Chat authorization baseline failures.
- Accepted backend failures: deferred Chat tool authorization
  (`tests/agents/chat/test_agent_loop.py::test_loaded_deferred_tool_is_authorized_on_next_round_only`),
  unrelated RAG sandbox wiring
  (`tests/agents/chat/test_cli_app_wiring.py::test_an_unrelated_tool_is_not_handed_a_sandbox`),
  and forced-finish Chat context reporting
  (`tests/agents/chat/test_context_budget.py::test_forced_finish_still_reports_the_tools_the_turn_carried`).
  Each reproduced twice; none blocks Classes, Course Overview, Materials, or
  the exact BlueWay launch route. Chat remains parked.
- Owner-isolation result: User B could not resolve User A's owner-scoped map;
  repeated User A launch kept exactly two Courses and did not create a row.
- Responsive result: desktop and `390x844` browser proof passed.
- Keyboard/focus result: exact Course Overview link focused and activated with
  Enter at narrow width.
- TEEECHR implementation commits: backend `d8486d51`, web/auth `77ad469d`.
  BlueWay commits: checkpoint timeout `c3d11e7` and `634a5f2`, launch
  card/URL/state gate `eb4914e`. The documentation/proof receipt is committed
  in the TEEECHR docs commit `074587e0`; this push-state receipt is the final
  post-push docs commit.
- Push state: TEEECHR was pushed to `fork/feature/blueway-exact-course-launch-b2`;
  BlueWay was pushed to `origin/feature/teeechr-web-course-launch-b2`. Neither
  canonical main branch or TEEECHR upstream `origin` was modified.

No hosted, production-secret, physical-device, TestFlight, native simulator,
or release claim is made by this receipt until a separate proof packet records
it.
