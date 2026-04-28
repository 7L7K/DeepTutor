# DeepTutor Private Tester Runbook

## Live target

- Domain: `https://teeechr.gesahni.com`
- DNS: Cloudflare `A` record, DNS-only, `teeechr.gesahni.com -> 165.22.177.84`
- VPS public IP: `165.22.177.84`
- VPS Tailscale target: `root@100.65.123.80`
- App path on VPS: `/opt/teeech/DeepTutor`
- Runtime env on VPS: `/etc/teeech/teeech.env`

## Runtime layout

- Reverse proxy: existing Dockerized Caddy container `gv5-caddy-1`
- Caddyfile source on host: `/root/gv5/infra/Caddyfile`
- Docker network: `gv5_default`
- Web container: `teeech-web`, serves Next standalone on port `3001`
- Backend container: `teeech-backend`, serves FastAPI/Uvicorn on port `8001`
- Persistent data mount: `/opt/teeech/DeepTutor/data:/app/data`
- Persistent outputs mount: `/opt/teeech/DeepTutor/outputs:/app/outputs`

## Caddy route

```caddy
teeechr.gesahni.com {
  encode gzip

  @backend path /api/* /docs* /openapi.json /outputs/* /static/outputs/*
  reverse_proxy @backend teeech-backend:8001

  reverse_proxy teeech-web:3001
}
```

## Deploy

Run from the local repo:

```bash
scripts/deploy_teeechr.sh
```

The script:

- rsyncs source to `/opt/teeech/DeepTutor`
- preserves remote secrets by excluding `.env*`
- preserves runtime learner data by excluding `data/` and `outputs/`
- writes `web/.env.production` with `NEXT_PUBLIC_API_BASE=https://teeechr.gesahni.com`
- installs web deps and builds Next
- copies `.next/static` and `public` into `.next/standalone`
- rebuilds `teeech-backend`
- restarts `teeech-backend` and `teeech-web`
- validates/reloads Caddy
- checks `https://teeechr.gesahni.com` and `https://teeechr.gesahni.com/docs`

Important: Next standalone will serve HTML but fail hydration if `.next/static` is not copied into `.next/standalone/.next/static`. If the access gate is stuck on `Checking...`, check static assets first.

## Access codes

Create or rotate tester codes on the VPS:

```bash
ssh root@100.65.123.80 'docker exec teeech-backend python scripts/manage_testers.py upsert --tester-id tester-1 --display-name PrivateTester1 --access-code "new-code-here"'
```

Smoke-test an access code:

```bash
curl -i -X POST https://teeechr.gesahni.com/api/v1/access/claim \
  -H 'content-type: application/json' \
  --data '{"access_code":"new-code-here"}'
```

## Chat websocket checks

Expected public websocket URL:

```text
wss://teeechr.gesahni.com/api/v1/ws
```

If chat creates a session but the UI stays on `Stop generating`, check:

```bash
ssh root@100.65.123.80 'docker logs --tail 220 teeech-backend 2>&1'
ssh root@100.65.123.80 'docker exec teeech-backend python - <<'"'"'PY'"'"'
import sqlite3
con = sqlite3.connect("data/user/chat_history.db")
cur = con.cursor()
for row in cur.execute("select id, session_id, status, error from turns order by created_at desc limit 5"):
    print(row)
for row in cur.execute("select id, session_id, role, substr(content,1,160) from messages order by id desc limit 8"):
    print(row)
PY'
```

Known fixed bug: `turn_belongs_to_tester()` must verify ownership by joining `turns` to `sessions`. If it relies on serialized turn data, websocket subscriptions can silently reject the owning tester and the browser will never receive the answer.

## Knowledge bases

Live KB data is persisted on the VPS through the backend container mount:

```bash
/opt/teeech/DeepTutor/data/knowledge_bases
```

Inside the backend container this is:

```bash
/app/data/knowledge_bases
```

The authoritative registry is:

```bash
/opt/teeech/DeepTutor/data/knowledge_bases/kb_config.json
```

Private tester scoping is name-prefix based. A browser-visible KB named `nce-2026` for tester `tester-1` is stored internally as:

```text
tester-1__nce-2026
```

Expected per-KB layout:

```text
data/knowledge_bases/<tester-id>__<kb-name>/
  raw/                  # Uploaded source files
  llamaindex_storage/   # Persisted vector index
  metadata.json         # Provider, timestamps, file hashes
```

Core API checks:

```bash
curl -b /tmp/teeechr-cookie.txt https://teeechr.gesahni.com/api/v1/knowledge/health
curl -b /tmp/teeechr-cookie.txt https://teeechr.gesahni.com/api/v1/knowledge/list
curl -b /tmp/teeechr-cookie.txt https://teeechr.gesahni.com/api/v1/knowledge/default
```

Create a KB from a local PDF through the public API:

```bash
curl -c /tmp/teeechr-cookie.txt \
  -H 'content-type: application/json' \
  -d '{"access_code":"<tester-access-code>"}' \
  https://teeechr.gesahni.com/api/v1/access/claim

curl -b /tmp/teeechr-cookie.txt \
  -X POST https://teeechr.gesahni.com/api/v1/knowledge/create \
  -F 'name=nce-2026' \
  -F 'rag_provider=llamaindex' \
  -F 'files=@/path/to/file.pdf;type=application/pdf'
```

If the Knowledge page appears to do nothing, check backend logs for the create request:

```bash
ssh root@100.65.123.80 'docker logs --tail=200 teeech-backend | grep "POST /api/v1/knowledge/create"'
```

No `POST /api/v1/knowledge/create` means the browser did not submit the form. The Create card requires both a KB name and at least one file. A successful create should immediately register a task, write `kb_config.json`, copy files into `raw/`, and build `llamaindex_storage/`.

## Knowledge use in Practice and Flashcards

Knowledge bases do not replace the model. They provide retrieval context that the model uses to create grounded learner material.

Practice quiz flow with a KB:

```text
selected public KB name
-> backend scopes it to <tester-id>__<kb-name>
-> RAG retrieval pulls relevant excerpts
-> idea agent uses excerpts to create question templates
-> generator model writes questions, answers, distractors, and explanations
-> quiz submission agent grades submitted answers
```

Flashcards flow with a KB:

```text
selected public KB names
-> backend scopes them to internal tester KB names
-> RAG retrieval pulls excerpts
-> flashcard LLM writes active-recall cards from those excerpts
-> first batch can return before the rest of a progressive deck finishes
```

Why this still uses the model: retrieval can find relevant text, but it cannot reliably author exam-style stems, balanced distractors, correct answers, explanations, remediation, or score a submitted quiz without generation/reasoning. The KB should improve grounding and reduce generic questions, but it is not currently a deterministic question-bank renderer.

Known fixed bug: interactive quiz submissions send `quiz_submission_context` as runtime-only deep-question config. This key must be stripped before public config validation and then routed to `QuizSubmissionAgent`; otherwise the user sees `Invalid deep question config: quiz_submission_context: Extra inputs are not permitted`.

## Basic chat routing

Basic no-tool prompts should use the direct quick-reply path instead of the full thinking/acting/observing pipeline. Examples:

- `hi`
- `say hi in one sentence`
- `I want to start an exam`
- `explain this simply`

The direct path should not activate when tools, attachments, knowledge bases, or artifact-generation intents are present.

## Useful health checks

```bash
curl -I https://teeechr.gesahni.com
curl -I https://teeechr.gesahni.com/docs
curl -I https://teeechr.gesahni.com/_next/static/chunks/0n_sovpwu9bzp.css
ssh root@100.65.123.80 'docker ps --filter name=teeech --format "{{.Names}} {{.Status}} {{.Networks}}"'
```

## Logs

```bash
ssh root@100.65.123.80 'docker logs --tail 200 teeech-backend 2>&1'
ssh root@100.65.123.80 'docker logs --tail 100 teeech-web 2>&1'
ssh root@100.65.123.80 'docker exec teeech-backend tail -n 200 data/user/logs/deeptutor_$(date +%Y%m%d).log'
```

## Local regression tests

```bash
pytest tests/api/test_turn_subscription_scope.py tests/agents/chat/test_agentic_parallel_tools.py
```

## Current private tester scope

Keep the first tester surface focused on:

- Chat
- Practice
- Flashcards
- Knowledge

Keep TutorBot, Co-Writer, tournament, and broader experimental lanes hidden until the core loop is stable.
