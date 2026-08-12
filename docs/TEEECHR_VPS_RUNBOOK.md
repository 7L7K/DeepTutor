# TEEECHR VPS Runbook

This is the operating map for the hosted TEEECHR beta deployment. It describes
the DigitalOcean VPS, the public request path, persistent data, source/build/
deployment boundaries, and the safe workflow for future work.

This document is an operational guide, not a secret store. Never place API
keys, passwords, private SSH material, JWTs, raw credential files, or complete
qualification credential files here.

## Operator shorthand

When the user says **VPS**, use this target unless they explicitly name another
server:

| Item | Current value |
| --- | --- |
| Provider | DigitalOcean Droplet |
| Local SSH alias | `deeptutor-vps` |
| Public hostname | `teeechr.gesahni.com` |
| Current observed IPv4 | `167.172.138.159` |
| Server application root | `/opt/teeechr` |
| Persistent host data | `/opt/teeechr/data` |
| Public web entry | Caddy on ports 80/443 |
| App container | `teeechr-app` |
| Reverse-proxy container | `teeechr-caddy` |
| App frontend | Next.js, container port 3782 |
| App backend | FastAPI, container port 8001 |

The hostname and SSH alias are the durable identifiers. The IP address can
change and should be rechecked before a new deployment or DNS operation.

## Production request path

```text
student browser
    ↓
teeechr.gesahni.com
    ↓
DigitalOcean Droplet
    ↓
Caddy: TLS, HTTP redirect, reverse proxy
    ↓
teeechr-app Docker container
    ├─ Next.js frontend (:3782)
    └─ FastAPI backend (:8001)
        ├─ auth and ownership checks
        ├─ Course/Chat/Practice/Review APIs
        ├─ deployment-owned provider runtime
        └─ /app/data
             ↓ bind mount
        /opt/teeechr/data
```

The browser uses the public frontend origin. The frontend handles the public
`/api/*` and `/ws/*` paths and forwards them to the backend inside the app
container. The backend is not intended to be the public browser entry point.

## Runtime and persistence model

The deployed application runs from a Docker image. It does not run directly
from a Git checkout on the VPS. The deployment release directory and receipt
identify which source archive and commit produced that image.

The persistent data boundary is:

```text
/opt/teeechr/data  →  /app/data
```

That tree contains the live deployment state, including:

- authentication accounts and deployment settings;
- per-user workspaces and Course records;
- uploaded source material and derived indexes;
- Practice sets, attempts, answers, and Review state;
- deployment-wide model profiles and logical user grants;
- encrypted provider credential envelopes and usage records;
- logs and audit information.

Code deployment must preserve this tree. A restart or image replacement is not
a data reset. Any migration, restore, deletion, or data-tree rewrite requires a
separate explicit operation with a backup and a receipt.

There is currently no required Postgres, Redis, Kubernetes, or separate worker
service in this beta topology. The single app container and persistent data
tree are the current source of runtime truth.

## Provider model

The beta uses a deployment-owned OpenAI credential. Individual users do not
enter provider keys.

```text
authenticated user
    ↓ logical model grant
TEEECHR provider runtime
    ↓ encrypted deployment credential
OpenAI model/embedding endpoint
```

The hosted configuration uses the qualified Luna generation model and
`text-embedding-3-small` embeddings. The credential is not placed in browser
state, user grants, Course records, or ordinary process environment output.

The hosted beta has a small lifetime usage ceiling. Provider changes must be
admin-gated, budgeted, tested with a tiny probe, and recorded without exposing
the secret or raw request content.

## Security posture

The intended public surface is:

- TCP 22 for SSH key access;
- TCP 80 for HTTP redirect;
- TCP 443 for HTTPS;
- UDP 443 for HTTP/3 where enabled.

The firewall defaults to deny incoming traffic and allows outgoing traffic.
SSH is key-only for the current beta, with password and keyboard-interactive
authentication disabled. Root key login may remain temporarily enabled for
operations, but a dedicated deploy/operator user is a future hardening item.

The current SSH hardening expectations are:

```text
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
X11Forwarding no
AllowTcpForwarding no
```

Before trusting a new state, verify the effective configuration with `sshd -T`
and verify the firewall rather than relying only on a configuration file.

## Read-only inspection

The default operator mode is read-only. Use the SSH alias and do not print
credential files or environment values containing secrets.

```bash
ssh deeptutor-vps

# Runtime identity and health
docker ps
docker inspect teeechr-app

# Deployment receipt and persistent mount
cat /opt/teeechr/DEPLOYMENT
docker inspect teeechr-app

# Disk and data footprint
df -h / /opt/teeechr/data
du -sh /opt/teeechr/data

# Network/security posture
ufw status verbose
sshd -T -C user=root,host=teeechr.gesahni.com,addr=127.0.0.1
```

Safe inspection should answer:

1. Is Caddy running?
2. Is the app container healthy?
3. Which exact image tag and commit are running?
4. Is `/opt/teeechr/data` still mounted to `/app/data`?
5. Is the public hostname serving HTTPS?
6. Are the expected auth, provider, budget, and isolation checks still true?
7. Is there enough disk space?

## Local source and release workflow

The canonical local repository is:

```text
/Users/home/Desktop/2k26/teeech/DeepTutor
```

Normal development should happen on a feature branch or isolated worktree.
The canonical checkout may contain unrelated user edits; never reset it, use a
deployment as a substitute for it, or stage all files with `git add .` without
reviewing the boundary.

The release chain is:

```text
clean feature worktree
    ↓ focused tests and diff review
local commit
    ↓ push exact branch/commit
GitHub branch or release tag
    ↓ build from exact SHA
Docker image tagged with SHA
    ↓ deploy and record
VPS release + DEPLOYMENT receipt
    ↓ hosted verification
public beta
```

Commit, push, merge, and deploy are separate authorizations. “Commit this” does
not mean push. “Push this” does not mean merge or deploy. “Deploy this” must
name or resolve to an exact source commit.

The VPS is an output of the source/build chain. Do not edit application source
directly on the server as a normal development method.

For the plain-language explanation of local files, commits, pushes, PRs,
`main`, and deployment, see
[`TEEECHR_CHANGE_WORKFLOW.md`](./TEEECHR_CHANGE_WORKFLOW.md).

## Deployment checklist

Before a code deployment:

- identify the exact source commit;
- prove the release worktree is clean and contains only the intended slice;
- run focused tests and the relevant build check;
- ensure the commit is available on the intended GitHub remote;
- build/tag the image with the exact commit SHA;
- record the image digest and source archive hash;
- confirm the existing data mount and rollback reference;
- deploy without deleting or replacing `/opt/teeechr/data`;
- wait for container health;
- check HTTPS, auth, and the affected hosted flow;
- preserve a dated deployment receipt.

For provider, auth, persistence, or Course changes, the relevant hosted proof
must be repeated. A healthy container alone is not enough.

## Rollback boundary

Rollback means restoring a known prior application image and deployment file
while preserving the current data tree unless a separately authorized data
rollback is required.

Before rollback, capture:

- current `DEPLOYMENT` receipt;
- current image tag/digest;
- current container logs relevant to the failure;
- current data-tree size and mount;
- the exact prior release/image to restore.

After rollback, verify health, auth, Course access, and persistence. Do not use
Git reset or destructive data commands as a substitute for an operational
rollback.

## Documentation boundaries

`AGENTS.md` contains stable behavior rules. This runbook contains the topology
and procedure. A dated hosted-beta receipt contains release-specific facts.
Temporary credentials, API keys, private SSH material, and raw provider files
belong in neither the repository nor these documents.

## Current known release debt

The hosted image and VPS release receipt identify commit
`964c090ad8fdba452fa715a6034574313f091a96`. The exact clean deployment branch
and beta tag must be verified on the intended GitHub remote before treating
remote source control as the authoritative recovery copy. Do not merge that
release into a dirty canonical checkout as part of this verification.
