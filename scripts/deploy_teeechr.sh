#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-root@100.65.123.80}"
REMOTE_APP_DIR="${REMOTE_APP_DIR:-/opt/teeech/DeepTutor}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-/etc/teeech/teeech.env}"
CADDY_CONTAINER="${CADDY_CONTAINER:-gv5-caddy-1}"
CADDYFILE="${CADDYFILE:-/root/gv5/infra/Caddyfile}"
DOMAIN="${DOMAIN:-teeechr.gesahni.com}"
NETWORK="${NETWORK:-gv5_default}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Deploying ${DOMAIN} to ${REMOTE_HOST}:${REMOTE_APP_DIR}"

rsync -az --delete \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='venv' \
  --exclude='web/node_modules' \
  --exclude='web/.next' \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache' \
  --exclude='.uv-cache' \
  --exclude='.ruff_cache' \
  --exclude='.mypy_cache' \
  --exclude='.env' \
  --exclude='.env.*' \
  --exclude='data/' \
  --exclude='outputs/' \
  "${ROOT_DIR}/" "${REMOTE_HOST}:${REMOTE_APP_DIR}/"

ssh -o BatchMode=yes "${REMOTE_HOST}" bash <<REMOTE
set -euo pipefail

if [ ! -f "${REMOTE_ENV_FILE}" ]; then
  echo "Missing ${REMOTE_ENV_FILE}. Create it before deploying secrets." >&2
  exit 1
fi

cd "${REMOTE_APP_DIR}"

cat > web/.env.production <<EOF
NEXT_PUBLIC_API_BASE=https://${DOMAIN}
NEXT_PUBLIC_API_BASE_EXTERNAL=https://${DOMAIN}
EOF

cd web
npm install
npm run build
rm -rf .next/standalone/.next/static .next/standalone/public
mkdir -p .next/standalone/.next
cp -a .next/static .next/standalone/.next/static
cp -a public .next/standalone/public
cd "${REMOTE_APP_DIR}"

mkdir -p data outputs

cat > /opt/teeech/backend.Dockerfile <<'EOF'
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt pyproject.toml ./
COPY requirements ./requirements
RUN python -m pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8001
CMD ["python", "-m", "uvicorn", "deeptutor.api.main:app", "--host", "0.0.0.0", "--port", "8001"]
EOF

docker build -f /opt/teeech/backend.Dockerfile -t teeech-backend:latest .
docker rm -f teeech-backend teeech-web >/dev/null 2>&1 || true
docker run -d --name teeech-backend --restart unless-stopped --network "${NETWORK}" --env-file "${REMOTE_ENV_FILE}" -v "${REMOTE_APP_DIR}/data:/app/data" -v "${REMOTE_APP_DIR}/outputs:/app/outputs" teeech-backend:latest
docker run -d --name teeech-web --restart unless-stopped --network "${NETWORK}" --env-file "${REMOTE_ENV_FILE}" -e NODE_ENV=production -e HOSTNAME=0.0.0.0 -e PORT=3001 -v "${REMOTE_APP_DIR}/web/.next/standalone:/app" -w /app node:22-alpine node server.js

python3 - <<'PY'
from pathlib import Path

domain = "${DOMAIN}"
caddyfile = Path("${CADDYFILE}")
text = caddyfile.read_text() if caddyfile.exists() else ""
block = f"""

{domain} {{
  encode gzip

  @backend path /api/* /docs* /openapi.json /outputs/* /static/outputs/*
  reverse_proxy @backend teeech-backend:8001

  reverse_proxy teeech-web:3001
}}
"""
if domain not in text:
    caddyfile.write_text(text.rstrip() + block)
PY

docker exec "${CADDY_CONTAINER}" caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker exec "${CADDY_CONTAINER}" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile

health_check() {
  local url="\$1"
  local attempt
  for attempt in \$(seq 1 20); do
    if curl --max-time 20 -fsS -I "\$url" | sed -n '1,8p'; then
      return 0
    fi
    sleep 2
  done
  echo "Health check failed after retries: \$url" >&2
  return 1
}

health_check "https://${DOMAIN}"
health_check "https://${DOMAIN}/docs"
docker ps --filter name=teeech --format '{{.Names}} {{.Status}} {{.Networks}}'
REMOTE

echo "Deploy complete: https://${DOMAIN}"
