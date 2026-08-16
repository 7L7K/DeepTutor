# TEEECHR Change Workflow — ELI5 Version

This is the simple mental model for changing TEEECHR without confusing local
files, GitHub, pull requests, or the live website.

## The five places to keep separate

Think of the project as five desks:

| Desk | What it is | What it does |
| --- | --- | --- |
| Local files | Your computer | Where we edit and test code |
| Local Git | Save points on your computer | Records commits and branches |
| GitHub | The shared source shelf | Stores pushed branches, commits, PRs, and tags |
| Docker image | A packed application snapshot | Carries one exact source commit toward deployment |
| VPS/website | The live classroom | Runs the selected image and stores student data |

The most important rule is that movement from one desk to the next is explicit.
Saving a file does not push it. Pushing does not merge it. Merging does not
deploy it. Deploying code does not replace the live student data.

## What the words mean

### Local

Local means the files on this computer. When we edit a file locally, only the
local working copy changes.

```text
edit CourseShell.tsx
    → local file changed
    → GitHub unchanged
    → website unchanged
```

### Branch

A branch is a labeled line of work. It lets us work on one idea without
changing the stable line immediately.

Examples:

```text
main
codex/teeechr-course-reminders
codex/teeechr-provider-settings
```

For normal feature work, use a feature branch or isolated worktree. Do not use a
dirty `main` checkout as a scratchpad for unrelated changes.

### Commit

A commit is a saved checkpoint in local Git. It gives a group of changes an
identity, such as:

```text
964c090ad8fdba452fa715a6034574313f091a96
```

A commit is not yet on GitHub and is not yet on the website.

### Push

Pushing uploads a local branch or commit to GitHub.

```text
local branch → GitHub branch
```

After a push, GitHub has the code. The public website has not changed unless a
separate deployment process runs.

### Pull request

A pull request, or PR, says:

> “Please review this feature branch and decide whether it should be merged
> into `main`.”

The PR is a review lane. It allows us to inspect the diff, run checks, discuss
the change, and decide whether it belongs in the stable branch.

```text
feature branch → PR → review/tests → merge decision
```

Opening a PR does not mean we have merged it. Merging does not automatically
mean the VPS has been updated.

### `main`

`main` is a Git branch, not the live website.

```text
GitHub/main changed
    ≠
website changed
```

The website changes only when an approved commit is packaged into an image,
deployed to the VPS, and verified.

### Deploy

Deploying means taking one exact approved commit, packaging it as a Docker
image, and making that image run on the VPS.

```text
approved commit
    → Docker image tagged with the commit SHA
    → VPS container
    → health check
    → hosted behavior check
```

The deployment must preserve the existing `/opt/teeechr/data` mount. Code is
updated; student accounts, Courses, sources, attempts, and provider usage data
remain in the persistent data tree.

## The normal change journey

### 1. Start locally

We identify the correct clean starting point and create a feature branch or
worktree.

For the current project, future work must start from a clean, remotely verified
commit or tag. The 2026-08-12 hosted-beta tag and its deployed commit are
historical receipt fields; verify that the ref exists on the intended remote
before using it. If it cannot be verified, stop and select another exact
remote ref rather than substituting a local branch or dirty checkout.

### 2. Make the change

Edit the relevant source files locally. At this stage:

- GitHub is unchanged;
- the VPS is unchanged;
- the public website is unchanged;
- the change can still be reviewed or abandoned locally.

### 3. Test and review locally

Run the smallest useful checks, inspect the diff, and confirm that no unrelated
files, secrets, generated artifacts, or user changes are included.

### 4. Commit the change

Commit only the intended slice. Now the change has a local source identity.

```text
working files → local commit
```

### 5. Push the feature branch

Push the branch to the intended GitHub remote.

```text
local commit → GitHub feature branch
```

This is the point where the work becomes available for remote review and
recovery. It is still not production.

### 6. Open and review the PR

The PR should identify:

- what changed;
- why it changed;
- what was tested;
- what remains unproven;
- whether it is safe to deploy;
- whether it changes data, auth, provider, security, or DNS behavior.

The PR can be merged only after the intended review decision. Do not assume a
PR should be merged just because the local tests pass.

### 7. Merge or select a release commit

After review, the approved source may be merged into `main`, or a specific
release branch/tag may be selected. Record the exact SHA.

```text
approved source commit = the one and only input to deployment
```

### 8. Deploy explicitly

Build the Docker image from that exact SHA, deploy it to the VPS, and preserve a
deployment receipt containing the commit, image tag/digest, data mount, and
health result.

### 9. Verify the hosted product

The hosted checks depend on the change. They may include:

- public HTTPS and container health;
- authentication;
- user ownership and cross-user denial;
- Course persistence;
- provider reachability and budget accounting;
- the affected learner flow;
- restart/reboot persistence when storage or startup behavior changed.

Only after those checks pass should we call the change deployed.

## What happens when someone says something short

These are the default interpretations:

| Request | Default action |
| --- | --- |
| “Check the VPS” | Read-only inspection |
| “Change this locally” | Edit and validate; do not push |
| “Commit this” | Make a narrow local commit; do not push |
| “Push this” | Push the named branch/commit; do not merge or deploy |
| “Open a PR” | Push/prepare the review request; do not merge |
| “Put it on main” | Merge/reconcile source control; do not deploy automatically |
| “Put it on the website” | Resolve exact commit, deploy, and verify hosted behavior |
| “Fix production” | Inspect first, identify the failing layer, then ask/act within scope |

If a request is ambiguous, the assistant should say which boundary it believes
the request crosses before changing anything.

## The rules that protect us

1. Never reset, discard, or overwrite dirty user work without explicit approval.
2. Never use `git add .` as a shortcut in a dirty checkout.
3. Never mix unrelated code, docs, security, provider, DNS, or data changes in
   one commit unless that coupling is intentional and documented.
4. Never deploy from a dirty or unidentified source tree.
5. Never treat a healthy container as proof that the learner flow works.
6. Never treat local proof as hosted proof.
7. Never put credentials in source, docs, browser state, or chat messages.
8. Never edit application source directly on the VPS as normal development.
9. Every deployment gets an exact commit, image identity, data-mount check, and
   dated receipt.
10. Keep the stable beta tag immutable and create a new tag for a new release.

## Hooks and gates

The repository already contains a `.pre-commit-config.yaml` with checks for
whitespace and file endings, malformed YAML/JSON/TOML, merge conflicts, large
files, Ruff lint/format, Prettier, secret detection, Bandit, and a relaxed
Mypy pass.

That configuration is the recipe, not proof that every computer is enforcing
it. At the time this workflow was written, this checkout did not have the
`pre-commit` executable installed and had no active local hook under
`.git/hooks/`. A future setup should install the tool and run:

```bash
pre-commit install
pre-commit run --all-files
```

The local hook is a convenience. GitHub CI remains the shared authority for a
pull request. The current `tests.yml` workflow runs lint, frontend tests,
Python import checks, and Python tests for code-related pushes/PRs targeting
`main` or `dev`. It does not currently run for docs-only changes because its
path filter excludes the documentation-only paths.

The current deployment is intentionally manual. There is no rule saying that
merging a PR automatically changes the VPS. A production deployment must still
be explicitly approved and must prove:

- exact source commit and clean release boundary;
- image tag and digest;
- preserved `/opt/teeechr/data` mount;
- healthy app and Caddy containers;
- public HTTPS;
- the hosted behavior affected by the change;
- a dated deployment receipt.

The next sensible guardrail improvement is a small docs-validation CI job and a
manual, exact-SHA deployment workflow. Those should be separate implementation
work, tested independently, and should not be smuggled into an ordinary docs
PR.

## Current TEEECHR release model

The hosted beta release is identified by:

```text
tag:    teeechr-hosted-beta-2026-08-12
commit: 964c090ad8fdba452fa715a6034574313f091a96
```

That receipt records a historical recovery point for the running site. Before
using it for rollback or future development, verify the tag, commit, image, and
release directory on the intended remote/VPS. Future development should start
from a clean known branch/worktree, not from the dirty canonical checkout.

## One-sentence memory aid

```text
Edit locally → commit → push to GitHub → PR/review → merge or tag → deploy exact SHA → verify website.
```
