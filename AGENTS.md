# DeepTutor — Agent-Native Architecture

## Overview

DeepTutor is an **agent-native** intelligent learning companion organized
around a two-layer plugin model — single-shot **Tools** invoked by the
LLM, and multi-stage **Capabilities** that take over a turn — exposed
through three entry points: CLI, WebSocket API, and Python SDK.

## Public branding boundary

`TEEECHR` is the only learner-facing product name. Any new or edited web UI,
metadata, accessibility label, localization string, loading/error state,
settings description, help text, sample learner content, test assertion for
visible copy, or other public product surface must use `TEEECHR` and must not
introduce `DeepTutor` or `deeptutor` as visible branding.

Keep `DeepTutor` / `deeptutor` only when the identifier is explicitly technical
or historical, including repository and package names, Python imports, API
routes, environment variables, storage keys, CLI commands, migrations, GitHub
URLs, archived receipts, screenshots, provenance artifacts, and fixtures that
intentionally document legacy behavior. When in doubt, classify the occurrence
before editing; never rename a technical contract merely to make a search clean.

## Hosted VPS operating boundary

When the user says **VPS** in this workspace, they mean the DigitalOcean
TEEECHR beta deployment reached through the local SSH alias `deeptutor-vps` and
served at `https://teeechr.gesahni.com`. The hostname and SSH alias are the
durable operator identifiers; verify both before making an operational change.

The VPS is a deployment target, not the development checkout. Its public path
is DNS → Caddy → the `teeechr-app` Docker container. The app container carries
the Next.js frontend and FastAPI backend; persistent runtime state is mounted
from `/opt/teeechr/data` on the host to `/app/data` in the container. Student
accounts, Courses, sources, attempts, provider settings, encrypted credentials,
usage records, and logs live in that data tree and must be preserved across code
deployments.

Source, build, deployment, and runtime proof are separate claims:

```text
local feature worktree → local commit → GitHub branch/tag
    → image tagged with the exact commit → VPS deployment receipt
    → hosted health and behavior checks
```

Do not treat a dirty checkout, a successful local build, a healthy container, or
an image label as proof of the other layers. Before deployment, establish the
exact source commit, clean release boundary, image tag/digest, persistent data
mount, rollback reference, and relevant hosted checks. Never merge or reset a
dirty canonical checkout to make a deployment convenient.

Default VPS inspection is read-only. Do not change containers, firewall, SSH,
DNS, provider settings, credentials, runtime data, or deployment files unless
the user explicitly authorizes that operation. Provider credentials are
deployment-owned and encrypted; individual users must receive logical model
access, never a provider key.

Use `docs/TEEECHR_VPS_RUNBOOK.md` for the current topology and operational
procedure, and the dated hosted-beta receipt for release-specific facts. Keep
temporary passwords, API keys, private SSH material, and raw credential files
out of source control and documentation.

## Change and release workflow contract

Use these meanings consistently:

| Phrase | Meaning in this workspace |
| --- | --- |
| local | Files in the selected checkout/worktree on the user's computer |
| commit | A saved local Git checkpoint; not a push, merge, or deployment |
| GitHub | The remote source repository, normally the `7L7K/DeepTutor` fork |
| `main` | A Git branch; changing it does not automatically change the website |
| PR | A review request to merge one GitHub branch into another, usually `main` |
| website / production | The live TEEECHR site at `teeechr.gesahni.com` |
| VPS | The DigitalOcean deployment described in `docs/TEEECHR_VPS_RUNBOOK.md` |
| deploy | Build/run an exact approved commit on the VPS and verify the hosted result |

The normal path is:

```text
local feature worktree
    → local tests and diff review
    → local commit
    → push feature branch to GitHub
    → PR/review or explicit merge decision
    → approved commit on GitHub/main or a release tag
    → Docker image tagged with that exact SHA
    → explicit VPS deployment
    → hosted health and behavior checks
```

Non-negotiable boundaries:

- Editing locally changes only the local files until a commit is made.
- A commit changes only local Git history until it is pushed.
- A push changes GitHub but does not merge or deploy.
- A PR requests a merge; it does not deploy unless a separately authorized
  automation exists and is explicitly part of the release contract.
- Merging into `main` changes source control; it does not automatically change
  the public website.
- Deploying changes the public website; it must use an exact source commit and
  preserve `/opt/teeechr/data`.
- Never deploy from a dirty checkout, stage with `git add .` without reviewing
  the boundary, reset unrelated user work, or edit production source directly.
- Keep code changes, runtime data changes, provider changes, DNS changes, and
  security changes as separate authorized lanes.

Instruction shorthand:

- “Inspect/check the VPS” means read-only inspection.
- “Change this locally” means edit and validate; do not push or deploy.
- “Commit this” means create a narrow local commit; do not push or deploy.
- “Push this” means publish the named branch/commit to the intended remote; do
  not merge or deploy.
- “Open a PR” means push the branch if needed and prepare the review request;
  do not merge it.
- “Put it on main” means merge/reconcile source control; do not deploy unless
  the user also authorizes production release.
- “Put it on the website” or “deploy it” means resolve the exact commit, build
  and deploy it, preserve data, and run hosted verification.

When a request uses “main,” “GitHub,” “website,” or “VPS” ambiguously, state
which boundary you are about to cross before acting. If a dirty checkout or
uncertain source identity makes the request unsafe, stop at inspection and
explain the smallest safe next step.

Keep the ELI5 explanation and release checklist in
`docs/TEEECHR_CHANGE_WORKFLOW.md`.

## Architecture

```
Entry Points:  CLI (Typer)  |  WebSocket /api/v1/ws  |  Python SDK
                    ↓                   ↓                   ↓
              ┌─────────────────────────────────────────────────┐
              │              ChatOrchestrator                    │
              │   routes UnifiedContext → selected Capability    │
              │   (defaults to `chat`)                           │
              └──────────┬──────────────┬───────────────────────┘
                         │              │
              ┌──────────▼──┐  ┌────────▼──────────┐
              │ ToolRegistry │  │ CapabilityRegistry │
              │  (Level 1)   │  │   (Level 2)        │
              └──────────────┘  └────────────────────┘
```

All capabilities emit on a shared `StreamBus`; the orchestrator fans
events out to consumers. Runtime settings live in
`data/user/settings/*.json` — project-root `.env` files are intentionally
ignored.

### Level 1 — Tools

Single-function tools the LLM picks on demand. Four user-toggleable tools
surface in `/settings/tools`:

| Tool           | Description                                   |
| -------------- | --------------------------------------------- |
| `brainstorm`   | Breadth-first idea exploration with rationale |
| `web_search`   | Web search with citations                     |
| `paper_search` | arXiv preprint search                         |
| `reason`       | Dedicated deep-reasoning LLM call             |

The rest are **context-gated**: the chat capability auto-mounts them from
`ToolMountFlags` (presence of a KB, attachments, sandbox availability, …), and
any of them can also be force-enabled via `--tool`. Auto-mounted set: `rag`,
`read_source`, `read_memory`, `write_memory`, `read_skill`, `load_tools`,
`exec`, `code_execution` (sandboxed Python: NL intent → code → run),
`list_notebook`, `write_note`, `web_fetch`, `github`, `cron`,
`ask_user` (pauses the turn and resumes with the user's reply), plus the
mastery-path tools. `geogebra_analysis` is parked under
`COMING_SOON_TOOL_TYPES`.

### Level 2 — Capabilities

Multi-stage pipelines that own the turn:

| Capability       | Stages                                                |
| ---------------- | ----------------------------------------------------- |
| `chat`           | exploring → responding (single agentic loop, default) |
| `mastery_path`   | responding (Guided Learning — chat loop + mastery tools, gated per topic type) |
| `deep_solve`     | planning → reasoning → writing                        |
| `deep_question`  | ideation → generation                                 |
| `deep_research`  | rephrasing → decomposing → researching → reporting    |
| `visualize`      | analyzing → generating → reviewing (SVG / Chart.js / Mermaid / HTML; or routes to Manim sub-stages via `render_type`) |
| `math_animator`  | concept_analysis → concept_design → code_generation → code_retry → summary → render_output |

All capabilities converge on `emit_capability_result()` in
`deeptutor/capabilities/_shared.py` so every turn emits the same envelope
(response payload + `cost_summary` from `UsageTracker`). Status copy and
prompts are i18n'd via `capabilities/prompts/{en,zh}/<name>.yaml`.

## CLI Usage

```bash
# Install
pip install deeptutor      # Full app (CLI + Web/API + packaged Web assets)
pip install deeptutor-cli  # CLI-only

# Run any capability
deeptutor run chat "Explain Fourier transform"
deeptutor run deep_solve "Solve x^2=4" -t rag --kb my-kb
deeptutor run visualize "Animate sine wave" --config render_mode=manim_video

# Interactive REPL
deeptutor chat
# (inside the REPL: /regenerate or /retry re-runs the last user message)

# Partners (IM-connected companions)
deeptutor partner list

# Knowledge bases, memory, server
deeptutor kb list
deeptutor kb create my-kb --doc textbook.pdf
deeptutor memory show
deeptutor serve --port 8001       # API server only
deeptutor start                   # backend + frontend together
```

## Key Files

| Path                                       | Purpose                              |
| ------------------------------------------ | ------------------------------------ |
| `deeptutor/runtime/orchestrator.py`        | `ChatOrchestrator` — unified entry   |
| `deeptutor/runtime/launcher.py`            | Backend + frontend lifecycle / port discovery |
| `deeptutor/runtime/registry/`              | Tool + Capability registries         |
| `deeptutor/runtime/bootstrap/builtin_capabilities.py` | Built-in capability class paths |
| `deeptutor/services/config/runtime_settings.py` | JSON settings + process-env overrides |
| `deeptutor/core/stream.py`, `stream_bus.py` | StreamEvent protocol + async fan-out |
| `deeptutor/core/tool_protocol.py`          | `BaseTool` + `ToolDefinition`         |
| `deeptutor/core/capability_protocol.py`    | `BaseCapability` + `CapabilityManifest` |
| `deeptutor/core/context.py`                | `UnifiedContext` dataclass            |
| `deeptutor/tools/builtin/__init__.py`      | All built-in tool wrappers           |
| `deeptutor/capabilities/`                  | Built-in capability implementations  |
| `deeptutor/app.py`                         | `DeepTutorApp` — Python SDK facade    |
| `deeptutor_cli/main.py`                    | Typer CLI entry point                |
| `deeptutor/api/routers/unified_ws.py`      | Unified WebSocket endpoint           |

## Dependency Layers

Public install paths and source extras are defined in `pyproject.toml`.
Requirements files mirror the same dependency groups for Docker/CI installs.

```
pip install deeptutor      — Full app (CLI + Web/API + packaged Web assets)
pip install deeptutor-cli  — CLI-only (LLM + RAG + providers + document parsing)
pip install -e .           — Source install for development

Source extras (.[ extra ], defined in pyproject.toml):
.[cli]            — CLI-only dependency set
.[server]         — Web/API server dependencies
.[partners]       — Partner channel SDKs + MCP client  (legacy alias: .[tutorbot])
.[matrix]         — Matrix channel for Partners (matrix-nio; needs libolm)
.[matrix-e2e]     — Matrix with end-to-end encryption (matrix-nio[e2e])
.[math-animator]  — Manim addon (powers `visualize` Manim renders + `deeptutor run math_animator`)
.[dev]            — Test / lint tooling
.[all]            — Everything above

## Migration-bound release reconciliation

When two branches or PRs touch the same migration version, schema boundary, or
release artifact:

1. Identify one authoritative migration owner before merging either branch.
2. Treat dependent branches as consumers of that migration; they must not carry
   competing SQL artifacts, checksums, or latest-version assumptions.
3. Record the required merge and deployment order in a release ledger.
4. Read each PR's actual `headRefName`, `headRefOid`, and `baseRefOid` from
   GitHub before editing or pushing. Do not infer PR ownership from similarly
   named local or remote branches.
5. After the migration-owner PR merges, reconcile every dependent PR against
   the exact new base SHA before trusting earlier CI.
6. CI from an earlier head or base is stale and cannot authorize a merge.
7. For a one-way migration, name the minimum rollback binary before applying
   it. Never restart an older incompatible image afterward.
8. Build deployment artifacts only from the final merge SHA, not from a dirty
   checkout, PR head, local branch label, or short display SHA.

## Release identity and dirty-checkout boundaries

Before deploying a runtime that emits release-correlated events, verify that
its application version and environment are explicit and non-empty in the
effective runtime configuration. Distinguish application environment from
deployment tier when they use different labels, such as production runtime
behavior on a beta host.

A dirty canonical checkout must not be used as release source. Use an isolated
worktree for reconciliation and a Git archive of the exact merge SHA for
artifact construction. Preserve unrelated staged, unstaged, and untracked
canonical changes.
```

## Migration-bound release reconciliation

When two branches or PRs touch the same migration version, schema boundary, or
release artifact:

1. Identify one authoritative migration owner before merging either branch.
2. Treat dependent branches as consumers of that migration; they must not carry
   competing SQL artifacts, checksums, or latest-version assumptions.
3. Record the required merge and deployment order in a release ledger.
4. Read each PR's actual `headRefName`, `headRefOid`, and `baseRefOid` from
   GitHub before editing or pushing. Do not infer PR ownership from similarly
   named local or remote branches.
5. After the migration-owner PR merges, reconcile every dependent PR against
   the exact new base SHA before trusting earlier CI.
6. CI from an earlier head or base is stale and cannot authorize a merge.
7. For a one-way migration, name the minimum rollback binary before applying
   it. Never restart an older incompatible image afterward.
8. Build deployment artifacts only from the exact approved release tag or
   merge SHA, and verify that a tag resolves to the intended merge commit. Do
   not build from a dirty checkout, PR head, local branch label, or short SHA.

## Release identity and dirty-checkout boundaries

Before deploying a runtime that emits release-correlated events, verify that
its application version and environment are explicit and non-empty in the
effective runtime configuration. Distinguish application environment from
deployment tier when they use different labels, such as production runtime
behavior on a beta host.

A dirty canonical checkout must not be used as release source. Use an isolated
worktree for reconciliation and a Git archive of the exact merge SHA for
artifact construction. Preserve unrelated staged, unstaged, and untracked
canonical changes.
