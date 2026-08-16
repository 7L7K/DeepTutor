# TEEECHR Hosted Beta Receipt — 2026-08-12

This receipt records the hosted beta qualification state observed on 2026-08-12
America/Detroit. It is a dated release receipt, not a live status dashboard.
Re-run the VPS checks before relying on any value that may have changed.

## Release identity

| Field | Value |
| --- | --- |
| Product | TEEECHR |
| Environment | beta |
| Public hostname | `teeechr.gesahni.com` |
| Current observed VPS IPv4 | `167.172.138.159` |
| Deployed commit | `964c090ad8fdba452fa715a6034574313f091a96` |
| Deployed image | `teeechr:964c090ad8fdba452fa715a6034574313f091a96` |
| Image digest | `sha256:152a147102c8950e64878dde9119f14ebc9b3de7c2c6b6d5428c42f544366c13` |
| Historical source archive SHA-256 | `f3e24a7e6bd38827349b7cb92902d1805fc7dedfa5616685a7c6519ec854dfec` |
| Previous deployed commit | `82b33b75dc5916764b1050b724e5abf5db0e0593` |
| Previous deployed image | `teeechr:82b33b75dc5916764b1050b724e5abf5db0e0593` |
| Previous image ID | `sha256:b33f87c5d85478aa1e4a3783386af36d444db985a389725b4837f5ef6948d172` |
| Previous release directory | `/opt/teeechr/releases/82b33b75dc5916764b1050b724e5abf5db0e0593` |
| Persistent mount | `/opt/teeechr/data → /app/data` |

The production image was built from the clean isolated deployment branch. The
canonical local checkout contained unrelated user changes and was not reset,
staged, or merged as part of this release.

The source archive filename was `DeepTutor-964c090ad8fdba452fa715a6034574313f091a96.tar.gz`.
A read-only VPS audit on 2026-08-16 did not find that archive at
`/opt/teeechr/DeepTutor-964c090ad8fdba452fa715a6034574313f091a96.tar.gz`.
Therefore the recorded archive hash is historical receipt data, not a currently
available recovery artifact. Do not use it as independently verified source
proof until the archive is recovered or a new exact-SHA archive is created and
hashed with its filename, location, format, and retention record.

Because migration `0018` is a one-way compatibility boundary, the previous
`82b33b75` image is not a safe rollback target after a database has reached
`0018`. The compatible rollback candidate observed in the 2026-08-16 audit is
documented in the VPS runbook and must be re-verified before use.

## Runtime topology

```text
DNS: teeechr.gesahni.com
    ↓
Caddy container: public HTTP/HTTPS
    ↓
teeechr-app container: Next.js frontend + FastAPI backend
    ↓
/app/data
    ↓
/opt/teeechr/data on the VPS
```

The app container was healthy after deployment and after a full VPS reboot.
The app and Caddy containers restarted automatically with the new boot.

## Qualification results

| Gate | Result | Evidence boundary |
| --- | --- | --- |
| Hosted auth enabled | PASS | Authenticated qualification users logged in successfully |
| Course ownership isolation | PASS | Foreign Course reads returned HTTP 404 |
| Initial source ingestion | PASS | Source reached `ready` and materialized the exact text/index shard |
| Grounded Course Chat | PASS | Authenticated session persisted grounded source citation state |
| Real Practice generation | PASS | Qualified Luna operation completed and published five questions |
| Attempt persistence | PASS | Five intentionally incorrect answers survived fresh authenticated GET |
| Results | PASS | Attempt graded at 0/5 with persisted result state |
| Targeted Review | PASS | Review reopened with one targeted source |
| Application restart | PASS | Course/source/chat/practice/attempt/review identities survived |
| Full VPS reboot | PASS | Same hosted checks passed after reboot |

The hosted flow was:

```text
sign in
  → create/open Course
  → attach source
  → grounded Course Chat
  → qualified Practice generation
  → answer and refresh
  → Results
  → targeted Review
  → application restart
  → full VPS reboot
```

## Provider and budget

The deployment uses one server-owned encrypted OpenAI credential for the hosted
site. Individual users do not add provider keys.

| Field | Value |
| --- | --- |
| Generation profile | `llm-openai-global` |
| Generation logical model | `llm-gpt-5-6-luna` |
| Embedding profile | `embedding-openai-global` |
| Embedding logical model | `embedding-text-embedding-3-small` |
| Embedding dimension | 1536 |
| Lifetime ceiling | 1,000,000 microusd = $1.00 |
| Settled qualification usage | 1,361 microusd = $0.001361 |
| Reserved/uncertain usage | 0 microusd |
| Remaining recorded ceiling | 998,639 microusd = $0.998639 |

The provider audit found no raw API key in the catalog response or process
environment output. Provider credentials were stored as encrypted deployment
data with restricted permissions. User grants contained logical model access,
not credentials or filesystem paths.

## Security and network result

The firewall was active with default incoming deny and outgoing allow. The
expected public rules were SSH 22/tcp, HTTP 80/tcp, HTTPS 443/tcp, and HTTPS
HTTP/3 443/udp, with IPv6 equivalents.

Effective SSH settings were:

```text
PermitRootLogin without-password
PasswordAuthentication no
KbdInteractiveAuthentication no
X11Forwarding no
AllowTcpForwarding no
```

This is the current small-beta posture. A dedicated non-root deploy/operator
account remains a future hardening improvement.

## Storage result

At the final post-reboot snapshot:

```text
Root filesystem: 77G total, 11G used, 66G available, 15% used
TEEECHR data: 3.9M
```

No Postgres, Redis, Kubernetes, or separate production worker was required for
this beta topology.

## DNS and branding result

- `teeechr.gesahni.com` resolved to the current TEEECHR VPS.
- The stale `api.gesahni.com` record pointing to the retired server was removed
  and verified absent through public resolvers.
- The visible learner-facing product branding is TEEECHR.

## Source-control status at receipt time

The hosted image and server release receipt preserve the exact deployed source
identity. The clean deployment branch and tag still require verification on the
intended GitHub remote before GitHub can be called the authoritative recovery
copy for this release.

The canonical checkout was intentionally left dirty and untouched. This receipt
does not authorize a merge, reset, push, or cleanup of that checkout.

## Next operational actions

1. Push the exact clean deployment branch to the intended GitHub fork.
2. Verify the remote branch SHA equals the deployed commit.
3. Push and verify the tag `teeechr-hosted-beta-2026-08-12`.
4. Preserve the remote URLs and SHA in a follow-up release note.
5. Create/invite real student accounts and repeat the smallest hosted smoke
   before sharing the public URL broadly.

## Authority boundary

This receipt proves a hosted beta qualification run at the recorded time. It
does not prove that every future local change is deployed, that the canonical
checkout is clean, or that the provider budget will remain unchanged after
future operations. Recheck the exact commit, image, data mount, and hosted flow
for each release.
