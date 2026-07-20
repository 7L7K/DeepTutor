# TEEECHR v1.5.2 Phase 1 Handoff

## Outcome

Phase 1 is complete. The historical TEEECHR fork and its previously
uncommitted recovery state are preserved, and an untouched DeepTutor v1.5.2
baseline exists in a separate worktree with local source, test, build, and API
listener proof.

No TEEECHR product feature was migrated. Production was not changed.

## Preserved historical checkout

- Path: `/Users/home/Desktop/2k26/teeech/DeepTutor`
- Branch: `safety/teeechr-pre-v152-20260720`
- Starting historical HEAD: `e991e79f`
- Current preservation HEAD after this handoff commit: see `git log -1`
- Worktree state at handoff: clean

Preservation commits:

1. `a4773c83` — `docs: map pre-v1.5.2 TEEECHR changes`
2. `da1b6a05` — `chore: preserve backend recovery state`
3. `5d85c0a5` — `chore: preserve incomplete frontend recovery state`

The detailed behavior and migration decisions are recorded in
`docs/TEEECHR_V152_PHASE1_CHANGE_MAP.md`.

## Clean upstream baseline

- Path: `/Users/home/Desktop/2k26/teeech/DeepTutor-v1.5.2-baseline`
- Branch: `baseline/v1.5.2`
- Commit: `b728354863540466f5410bec3530eb55a9fe0edc`
- Tag/version: `v1.5.2`
- Tracking: `origin/main`
- Tracked source state at handoff: clean and identical to `origin/main`

Ignored local baseline artifacts:

- `.venv/` — fresh Python 3.11.15 environment
- `web/node_modules/` — fresh npm dependency install
- `web/.next/` — production build output
- `data/user/settings/main.yaml` — minimal local test configuration
- normal Python and test caches

These are baseline runtime artifacts only and are not committed.

## Validation evidence

### Repository and imports

- Exact v1.5.2 commit proved.
- CI import contract passed for the orchestrator, registries, runtime settings,
  unified WebSocket router, prompt manager, and logging exports.
- `deeptutor.__version__.__version__` reported `1.5.2`.

### Python

- Runtime: Python 3.11.15
- Installed source profile: `.[dev]`
- Installed the CI Partner requirements separately because the default test
  collection imports Telegram and other Partner channels.
- Ruff lint: passed.
- Ruff format check: 919 files already formatted.
- Full suite: 2,683 passed, 6 skipped, 9 warnings.

The first full-suite attempt had one local environment failure because the
shell PATH did not contain the virtualenv's `python` command. Re-running with
the virtualenv at the front of PATH passed the targeted sandbox test and the
entire suite. No source change was required.

### Frontend

- Dependency install: `npm ci --legacy-peer-deps` succeeded.
- Node tests: 157 passed, 0 failed.
- Next.js production build: succeeded.
- TypeScript stage: succeeded.
- Static generation: 51 routes completed.

The available machine runtime was Node 26.5.0. Upstream CI targets Node 22, so
an exact Node 22 reproduction remains separate proof rather than an inferred
claim.

### Local API listener

- Started the untouched FastAPI app on `127.0.0.1:8011`.
- `/` returned HTTP 200.
- `/docs` returned HTTP 200.
- `/api/v1/system/status` returned HTTP 200 and reported the backend online.
- `/api/v1/auth/status` returned HTTP 200 with local auth disabled and the
  local-admin identity.
- The server shut down cleanly after the smoke check.

No real model call, embedding call, search call, authenticated multi-user
flow, Knowledge ingestion, or production WebSocket turn was attempted.

## Baseline observations, not Phase 1 fixes

- `npm ci` reported 9 dependency audit findings: 1 low, 5 moderate, and 3 high.
  No automatic audit fix was run because that would change the untouched
  baseline.
- The build reported a seven-month-old Browserslist data set. It was not
  updated for the same reason.
- The build rewrote tracked `web/next-env.d.ts`; it was restored to the exact
  v1.5.2 content before handoff. The baseline tracked tree is clean.
- A configured default model name shown by `/api/v1/system/status` is not proof
  that provider credentials or a real model response work.

## Stop boundary

Stop here. The next phase must begin as a separately authorized migration
lane. Do not copy old TEEECHR modules wholesale into the baseline.

The recommended next lane is to define and validate the v1.5.2 identity and
data-ownership contract before implementing the TEEECHR access-code bridge.
Practice, Flashcards, Chat policy, Knowledge migration, and deployment remain
parked until that contract is approved.
