# Vertical Slice C0 — Course Chat Authorization Receipt

## Scope

C0 repaired the three parked Course Chat authorization-boundary tests. No
Course Chat UI was added or exposed, and no BlueWay or B2 source was changed.

## Repository identity

Branch:

`feature/teeechr-course-chat-c0`

Base:

`6f9a9d470bae01c540486a57b5c61e81a74d7aba`

C0 implementation HEAD before this receipt commit:

`7422e8d24319086aa16b40990a06895902cb0de2`

Commits:

- `b6c35bf3` — `fix(chat): bind deferred schemas before agent loop`
- `7422e8d2` — `test(chat): align authorization fixtures with turn scope`

## Authorization contracts closed

- Deferred tools loaded during one round become callable on the next round,
  never retroactively or in the same unauthorized batch.
- An unrelated tool does not receive a CLI-app sandbox or Course execution
  workspace.
- Forced-finish context accounting retains the tool schemas carried by the
  actual turn even though the finishing request sends no tools.
- The existing attached-KB RAG authorization guard remains enforced.

## Backend proof

- Full backend suite: `3,869 passed, 0 failed, 8 skipped`
- Focused C0 Chat authorization campaign: all three tests passed twice
- Course and multi-user isolation suites: `477 passed`
- Python runtime: `3.11.15`

## Web proof

- Node tests: `423 passed`
- Lint: `0 errors`
- TypeScript: passed
- Production build: passed
- Node runtime: `22.23.2`
- npm: `10.9.8`

## Closeout boundary

C0 is local source, test, and build proven. The receipt is intended to be
force-added as this exact ignored file and pushed to:

`fork/feature/teeechr-course-chat-c0`

C1 must begin from the final pushed C0 commit in a separate worktree. C1 is
responsible for the owner-scoped Course Chat surface, ready-source binding,
truthful citations, session/Course persistence, and runtime proof. Practice,
Results, and Review remain deferred to C2.
