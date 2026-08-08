# Vertical Slice B2 — BlueWay Course to Exact TEEECHR Web Course

Status: source/test/build proven; authenticated local browser campaign passed.
Native-simulator, hosted, physical-device, and release proof remain separate
gates.

## Scope freeze

| Surface | B2 decision |
| --- | --- |
| BlueWay | Launch/context product. The existing accepted Course page owns the `Study with TEEECHR` action. |
| TEEECHR web | Complete learning product. The launch destination is the existing authenticated Course Overview. |
| Authentication | Normal TEEECHR sign-in. No cross-product SSO, shared token, or BlueWay credential is introduced. |
| Database | Existing owner-scoped Course and BlueWay mapping tables only. No migration change. |
| Destination | `/classes/{internalCourseId}` after exact owner + Course + term resolution. |
| Excluded | BlueWay launch/SSO redesign, syllabus parsing, timeline intelligence, Study Sessions, recommendations, Progress redesign, hosted deployment, production secrets. |

The authoritative implementation branches are:

- TEEECHR: `feature/blueway-exact-course-launch-b2`, worktree
  `/Users/home/Desktop/2k26/teeech/DeepTutor-blueway-launch-b2`, base
  `a7e058488080a4f6934a7ea5173242291a0aa3ab`.
- BlueWay: `feature/teeechr-web-course-launch-b2`, worktree
  `/Users/home/Developer/BlueWay-teeechr-launch-b2`, base
  `d401a7b1c9bb489810ab1d85676bbb54c8ce3c6a`.

The B1 worktree, BlueWay canonical `main`, Slice A branches, historical
migration worktrees, hosted environments, and production configuration are not
part of this packet.

## Launch contract

BlueWay creates a bounded URL from the configured
`EXPO_PUBLIC_TEEECHR_WEB_URL`:

```text
/launch/blueway?external_course_id=<BlueWay courseId>&external_term_id=<normalized termId>
```

Both values are untrusted hints. They are not owner identifiers, TEEECHR local
Course IDs, credentials, authorization tokens, short-lived launch state, a
session, SSO, or a request to create data. The
TEEECHR web route:

1. is protected by the normal TEEECHR auth gate;
2. preserves the complete launch URL through `/login?next=...` when a session is
   missing or expires;
3. calls `GET /api/v1/integrations/blueway/launch` with the two hints;
4. derives the owner from the authenticated request-local user context;
5. queries only the owner’s BlueWay connections and exact
   `(external_course_id, external_term_id)` mapping;
6. returns the internal Course ID only for a proven `ready` or `stale` mapping;
7. redirects to `/classes/{internalCourseId}` only after that success.

The resolver never searches by title, never creates a Course, never accepts an
owner from query data, and never reveals a foreign learner’s matching Course.
The launch endpoint is read-only and returns `private, no-store`; it does not
mint or consume a launch token.

## State matrix

| State | Meaning | Browser behavior |
| --- | --- | --- |
| `ready` | Exact owner/connection/Course/term map is active, Course is active, and usable material is present. | Redirect to the internal Course Overview. |
| `stale` | The same exact mapping is proven but its last successful sync is outside the freshness window. | Still redirect to the internal Course Overview; freshness remains truthful. |
| `login_required` | No valid TEEECHR session is available. | Preserve the full launch query and send the learner to normal sign-in. |
| `course_not_ready` | Exact map exists but Course/material/sync state is not openable yet. | Show a bounded message and link to Classes. |
| `connection_revoked` | The exact map is tied to a revoked, disconnecting, or errored BlueWay connection. | Show a bounded reconnect message; do not launch. |
| `course_not_found` | No owner-scoped exact map exists, including foreign-account or malformed hints. | Show a generic not-found message without existence disclosure. |
| `term_mismatch` | The Course identity exists for the owner, but the requested academic term does not match. | Show a term-specific mismatch message; do not fall back by title. |
| `temporarily_unavailable` | Credential recovery, provider sync failure, or local launch read failure. | Show retry-safe bounded failure; BlueWay data is unchanged. |

## BlueWay card behavior

The existing `TeeechrWorkspaceCard` is extended only for `ready` and `stale`:

- `Study with TEEECHR` opens the exact launch URL.
- Missing web configuration or an unopenable URL is an explicit bounded warning.
- `syncing`, not-ready, consent, revoked, and unavailable states retain their
  existing truthful copy and do not expose a launch action.
- BlueWay does not add Chat, Practice, Review, Progress, or recommendation
  controls.

## Test and file map

| Contract | Implementation | Proof |
| --- | --- | --- |
| Owner/term exact match and no duplicate creation | `deeptutor/integrations/blueway/launch.py` | `tests/integrations/blueway/test_course_launch.py` |
| Authenticated launch API | `deeptutor/integrations/blueway/router.py` | Focused integration route tests plus backend suite |
| Query-preserving login continuation | `web/proxy.ts`, `web/lib/api.ts` | `web/tests/proxy-policy.test.ts`, `web/tests/api-auth-redirect.test.ts` |
| Launch request/response validation | `web/lib/blueway-launch-api.ts` | `web/tests/blueway-launch-api.test.ts` |
| Exact TEEECHR route and bounded states | `web/app/launch/blueway/page.tsx`, `web/components/launch/BlueWayLaunch.tsx` | Web node tests, typecheck, build, browser campaign |
| BlueWay handoff URL | `src/features/teeechrIntegration/teeechrLaunch.ts` | `tests/teeechrCourseLaunch.test.ts` |
| BlueWay ready/stale action | `src/features/teeechrIntegration/TeeechrWorkspaceCard.tsx` | BlueWay typecheck, focused test, simulator/browser launch campaign |

## Required proof campaign

The final campaign must use two distinct Course mappings for the same display
title where needed (for example, Biology 101 Fall 2026 and Biology 101 Winter
2027), plus a manual Course and a separate owner. It must record:

- BlueWay Biology page → `Study with TEEECHR` → exact TEEECHR Course Overview;
- sign-in-required continuation and direct-link refresh/reopen;
- stale mapping remains openable;
- wrong-term launch is refused;
- User B cannot open User A’s launch URL;
- repeated launch does not create a second Course or map;
- unavailable/revoked/not-ready states are bounded;
- one owner-scoped launch lookup rather than per-Course provider calls;
- desktop and narrow mobile screenshots, Course header, and keyboard/focus
  evidence at the appropriate web/native proof surfaces.

## Local browser proof

The bounded runner `scripts/test-blueway-launch-b2` created a disposable
authenticated runtime on Node 22 and Python 3.11, seeded User A's private
BlueWay-connected Biology 101 Course plus a separate manual Psychology 201
Course, and ran five Playwright journeys. Durable evidence is under
`docs/verification/2026-08-08-teeechr-b2-browser/`.

The final campaign passed:

1. User A opened `/classes`, saw Biology 101 and Psychology 201, launched the
   exact Biology mapping, and landed on the fixture's owner-scoped internal
   Course route. The Overview showed `Biology 101` and `Term: Fall 2026`.
2. Repeating the same launch returned to the same internal Course and left the
   owner list at exactly two Courses; no duplicate Course or map was created.
3. An unauthenticated launch preserved the exact Course/term intent through
   `/login?next=...` and resumed at the exact Course after normal sign-in.
4. User B received the bounded `course_not_found` state for User A's launch
   URL. User C received the truthful `No Classes yet` state.
5. A `Winter 2027` term hint was refused with `term_mismatch` and did not open
   Biology.
6. At `390x844`, the exact Course header and destinations remained usable, and
   keyboard focus plus Enter activation of `Back to Classes` passed.

The local campaign made two exact launch API requests for the repeated-launch
test, one per launch, and each request used the single owner-scoped resolver
query. No hosted provider, Supabase, production secret, physical device, or
release artifact was involved.

## Regression and security closeout

- Legacy termless resolver coverage proves one NULL-term mapping may resolve,
  term-qualified mappings are never used as a fallback, blank terms are
  rejected, and multiple exact mappings fail closed.
- Auth continuation rejects external origins, scheme-relative and encoded
  scheme-relative paths, JavaScript/data/file schemes, duplicate launch keys,
  unknown launch keys, and malformed launch identity. Launch API and proxy
  responses are private and non-cacheable.
- BlueWay URL construction permits HTTPS production destinations and loopback
  HTTP local QA only; it rejects credentials and arbitrary schemes, encodes
  opaque IDs, and sends only external Course/term hints.
- Full backend regression preserves the accepted three unrelated Chat
  authorization failures; those failures do not block the exact Course launch
  surfaces and Chat remains parked.
