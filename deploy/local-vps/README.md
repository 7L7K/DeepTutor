# Local VPS mirror

This bundle runs the production Docker image behind Caddy on the local machine.
It is meant to catch deployment-shaped bugs before the VPS: same-origin API
rewrites, WebSocket routing, frontend/backend startup, runtime settings, and
data persistence.

The local stack is intentionally isolated from the repository's existing
development Compose file and from other Docker projects. It uses:

- the `production` target in the root `Dockerfile`;
- an app container with internal ports `8001` and `3782`;
- a Caddy reverse proxy on `http://127.0.0.1:18080`;
- a private `deploy/local-vps/data` bind mount for test data;
- a local `/api/version` marker and `X-TEEECHR-Commit` header showing the source
  commit and dirty state.

## Start it

From the repository root:

```bash
./scripts/vps-local up
```

Then open [http://127.0.0.1:18080](http://127.0.0.1:18080). The command builds
the image, starts both containers, waits for the backend health check, and runs
same-origin smoke checks.

Useful commands:

```bash
./scripts/vps-local status
./scripts/vps-local logs --no-follow
./scripts/vps-local smoke
./scripts/vps-local down
```

The host ports can be changed if needed:

```bash
LOCAL_VPS_HTTP_PORT=28080 LOCAL_VPS_HTTPS_PORT=28443 ./scripts/vps-local up
```

## Provider and authentication testing

The first boot creates safe settings in the isolated data directory. It does
not copy `provider.env`, VPS secrets, or production user data. This means the
stack can validate the shell, proxy, API, and frontend without making a model
request.

When no LLM profile exists, `scripts/vps-local up` seeds a credential-free
OpenAI profile for the catalog's default text-generation model. The profile is
safe to commit as tooling; the API key remains environment-only. Existing LLM
profiles are left unchanged.

To test authenticated chat and streaming, configure a local provider and local
auth settings in the app's Settings screen, or place intentionally local-only
configuration under `deploy/local-vps/data/user/settings/`. Never place VPS
credentials in this directory or commit them.

If the repository-root `.env` contains a local-only `LLM_API_KEY`,
`scripts/vps-local` reads that file explicitly and passes only `LLM_API_KEY` to
the app container. The key is not persisted in `model_catalog.json` or exposed
by the public settings catalog.

The local default has authentication disabled, matching the application's safe
fresh-install default. Before beta release, enable auth locally and repeat the
browser smoke test with a disposable local account; that is the closest local
proof of the VPS login and chat path.

## Stop and reset

`down` preserves local test data. To remove only this bundle's data, use the
explicit confirmation flag:

```bash
./scripts/vps-local reset --yes
```

This does not touch the repository's existing `data/` directory, Git state, or
any other Docker Compose project.
