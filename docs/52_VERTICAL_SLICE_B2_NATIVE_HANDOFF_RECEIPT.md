# Vertical Slice B2 Native Handoff Receipt

Status:

- SOURCE / TEST / BUILD PROVEN
- AUTHENTICATED LOCAL IOS SIMULATOR HANDOFF PROVEN
- LOCAL AUTH/RPC/EDGE/TEEECHR WORKSPACE READ PROVEN
- AUTHENTICATED LOCAL BROWSER RUNTIME PROVEN
- CHAT PARKED
- HOSTED, PHYSICAL DEVICE, TESTFLIGHT, AND RELEASE OPEN

This receipt closes the local native handoff rung for Vertical Slice B2. It does
not promote local Simulator QA into hosted, physical-device, TestFlight, or
production proof.

## Branches and source identity

TEEECHR:

- Branch: `feature/blueway-exact-course-launch-b2`
- Checkout: `/Users/home/Desktop/2k26/teeech/DeepTutor-blueway-launch-b2`
- Base: `a7e058488080a4f6934a7ea5173242291a0aa3ab`
- Source HEAD used by the native artifact: `bed8d78b22c114e7c37ffbe34ff3d02c8d97ab04`
- Remote: `fork/feature/blueway-exact-course-launch-b2`

BlueWay:

- Branch: `feature/teeechr-web-course-launch-b2`
- Checkout: `/Users/home/Developer/BlueWay-teeechr-launch-b2`
- Source HEAD used by the native artifact: `634a5f258e037010472a6293fbacd23616f2d873`
- Remote: `origin/feature/teeechr-web-course-launch-b2`
- The BlueWay checkout had untracked/generated native QA screenshots during the
  run; they were preserved and not cleaned or committed by this closeout.

No canonical main branch, Slice A branch, historical migration worktree, frozen
migration, hosted environment, production secret, or production configuration
was modified.

## Native runtime

| Component | Exact runtime |
| --- | --- |
| Node | `v22.23.2` at `/opt/homebrew/opt/node@22/bin` |
| npm | `10.9.8` |
| Python | `3.11.15` from `/Users/home/.codex/runtimes/teeechr-b1-python311` |
| Maestro | `2.6.1` |
| Java | OpenJDK 17 at `/opt/homebrew/opt/openjdk@17` |
| Xcode | `27.0 (27A5218g)` |
| Supabase CLI | `2.109.1` |
| Simulator | `BlueWay QA – iPhone 17 Pro Max`, iOS `27.0` |
| Simulator UDID | `7459A96D-A43F-4FB8-99CC-2BCD221DE77D` |

Native app artifact:

- Bundle ID: `com.bleeew.copilot.authqa`
- Version: `1.8.11 (22)`
- JavaScript bundle SHA-256:
  `7e3731dce4e0d3e69ce79a3f85b97f6b67a27dc74de28c1c3fd369d8874e28f4`
- Native executable SHA-256:
  `1f13a6f58078076be12fb597a3ea6f9d3cc2986a04bd8e517f9f4b52a6ecd9fb`
- Build result: `** BUILD SUCCEEDED **`
- Durable identity receipt:
  [`native-build-receipt.txt`](verification/2026-08-08-teeechr-b2-native-handoff-final/artifact/native-build-receipt.txt)

The `.app` itself remains under `/private/tmp/blueway-b2-native-derived-final/`.
The durable manifest preserves the exact bundle and executable hashes; this is
not a durable release archive.

## Fixture identity and local services

The disposable local runtime used one authQA User A and the exact Biology
mapping:

- External Course ID: `course_1234567890_bio101`
- Canonical external term ID: `fall-2026`
- TEEECHR internal Course ID: `crs_1c392a9eab9247409d7efb92dbdf7cad`
- Display title: `Biology 101 - Foundations of Biology`
- Workspace state: `ready`
- Connected sources: `1`
- Meetings: `1`
- External subject: `teeechr-native-user-a`
- No password, access token, refresh token, or secret is recorded here.

The direct local Edge preflight returned:

```text
schema_version = teeechr.workspace.v1
status = ready
course.external_course_id = course_1234567890_bio101
course.external_term_id = fall-2026
course.title = Biology 101 - Foundations of Biology
connected_sources_count = 1
meetings_count = 1
is_stale = false
```

The local services were disposable only: TEEECHR backend `127.0.0.1:8767`,
TEEECHR web `127.0.0.1:3813`, and the local authQA session bridge. No hosted
Supabase or hosted TEEECHR service was used.

## Exact native journey

The successful Maestro flow performed this bounded journey:

1. Launch the authenticated `com.bleeew.copilot.authqa` build on the exact
   Simulator.
2. Load the `teeechr-biology` QA fixture through the app's Simulator QA screen.
3. Open `Schedule → Classes → Biology 101 - Foundations of Biology`.
4. Assert the real ready card: `TEEECHR workspace ready`, `1 connected sources ·
   1 meetings`, and `Study with TEEECHR`.
5. Tap `Study with TEEECHR`.
6. Safari opened the local TEEECHR launch route:

   ```text
   http://127.0.0.1:3813/launch/blueway?external_course_id=course_1234567890_bio101&external_term_id=fall-2026
   ```

7. The authenticated TEEECHR session resolved the owner-scoped exact mapping
   and rendered the Course Overview with:

   ```text
   /classes/crs_1c392a9eab9247409d7efb92dbdf7cad
   ```

   ```text
   Biology 101 - Foundations of Biology
   Term: fall-2026
   ```

The canonical term ID is intentionally preserved across the handoff. The
earlier authenticated browser campaign used its human-readable fixture value
and separately proved `Term: Fall 2026`. The native screenshot therefore proves
the exact normalized identity `fall-2026`, while friendly-label parity is a
representation detail to address separately if the native surface must render
the title-cased label literally.

## Durable evidence

The final native handoff card is under:

[`docs/verification/2026-08-08-teeechr-b2-native-handoff-final/`](verification/2026-08-08-teeechr-b2-native-handoff-final/)

- [SHA-256 manifest](verification/2026-08-08-teeechr-b2-native-handoff-final/SHA256SUMS): all durable files verify successfully with `shasum -a 256 -c`.
- [Manifest](verification/2026-08-08-teeechr-b2-native-handoff-final/manifest.json): passed, exit code `0`, exact simulator, bundle, source commit, and hashes.
- [Authenticated native handoff JUnit](verification/2026-08-08-teeechr-b2-native-handoff-final/junit/maestro.xml): `1` test passed in `22s`.
- [Native login continuation JUnit](verification/2026-08-08-teeechr-b2-native-handoff-final/junit/maestro-authenticated-login.xml): `1` full card-to-login-to-Biology flow passed in `55s`.
- [Ready BlueWay card screenshot](verification/2026-08-08-teeechr-b2-native-handoff-final/artifacts/artifacts/screenshots/B2-native-final-biology-ready-study-with-teeechr.png).
- [Exact TEEECHR Biology screenshot](verification/2026-08-08-teeechr-b2-native-handoff-final/artifacts/artifacts/screenshots/B2-native-final-teeechr-biology-course.png).
- [Maestro command receipt](verification/2026-08-08-teeechr-b2-native-handoff-final/artifacts/artifacts/2026-08-08_121544/commands-(B2%20native%20authenticated%20exact%20Course%20handoff).json).
- [Maestro/XCTest log](verification/2026-08-08-teeechr-b2-native-handoff-final/artifacts/artifacts/2026-08-08_121544/xctest_runner_2026-08-08_121545.log).

The first failed native run and the intermediate authQA card proof remain in
their earlier verification directories as negative/intermediate evidence. They
are not used as the final pass claim.

## Regression and browser evidence

- TEEECHR web: `423 passed`; lint exit `0` with `0` errors and `234` warnings;
  TypeScript exit `0`; production build exit `0`.
- TEEECHR backend: `3,866 passed, 3 failed, 8 skipped`; the three accepted
  Chat authorization baseline failures remain deferred and Chat remains parked.
- BlueWay: `3,471 passed | 2 todo` across `335` files; focused launch tests,
  typecheck, and diff checks passed.
- Browser B2 campaign: `5/5` Playwright journeys passed, including exact
  Course/term launch, normal-auth continuation, repeated launch without a
  duplicate Course/map, foreign-account denial, zero-Course state, wrong-term
  refusal, narrow mobile, and keyboard/focus proof.
- Browser evidence: `docs/verification/2026-08-08-teeechr-b2-browser/`.

## Proof boundary and remaining risk

Proven in this packet:

- BlueWay Course → exact TEEECHR web launch intent.
- Owner-scoped Course and term resolution.
- Local authenticated Auth/RPC/Edge/TEEECHR read path.
- Native authQA card, local Safari handoff, and exact Course destination.
- Browser desktop/mobile, direct-link, repeat-launch, cross-user denial, zero
  Course, and keyboard/focus behavior.

Still open and deliberately not claimed:

- Hosted Supabase Edge and hosted TEEECHR runtime.
- Physical iPhone, TestFlight, production secrets, release signing, rollback,
  monitoring, and production deployment.
- Chat authorization repair; Chat remains parked.

### P2 UI polish (parked)

The native Course header currently renders the canonical normalized term ID
`fall-2026`, while the browser campaign renders the human-readable label
`Fall 2026`. Authorization, Course resolution, and term matching remain exact;
this is display-label parity, not identity corruption.

When Course Chat or Course-header work next touches this surface, render the
human-readable academic term label while preserving the canonical normalized
term ID underneath. Do not rebuild this B2 proof artifact for capitalization or
formatting alone.

## Push/commit state

The B2 branches were already pushed before this closeout:

- TEEECHR: `fork/feature/blueway-exact-course-launch-b2` at
  `bed8d78b22c114e7c37ffbe34ff3d02c8d97ab04`.
- BlueWay: `origin/feature/teeechr-web-course-launch-b2` at
  `634a5f258e037010472a6293fbacd23616f2d873`.

This native evidence and receipt pass was not committed or pushed. The new
receipt and verification directory are local uncommitted closeout artifacts;
canonical main and the existing B2 branch history were not changed.
