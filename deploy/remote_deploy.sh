#!/usr/bin/env bash
# Pull latest main and rebuild the Docker stack on the Selectel VDS.
# Progress is streamed to stdout (GitHub Actions) and /var/log/kinetic-deploy.log
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/app}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.yml}"
REPO_URL="${REPO_URL:-https://github.com/fuwiak/client_segmentation_deepseek.git}"
BRANCH="${BRANCH:-main}"
PG_IMAGE_MAJOR="${PG_IMAGE_MAJOR:-18}"
PG_VOLUME="${PG_VOLUME:-deploy_pg_data}"
DEPLOY_LOG="${DEPLOY_LOG:-/var/log/kinetic-deploy.log}"
TOTAL_STEPS=9

# Line-buffer stdout/stderr so GitHub Actions shows progress live over SSH.
export PYTHONUNBUFFERED=1
export BUILDKIT_PROGRESS=plain
export COMPOSE_PROGRESS=plain
if command -v stdbuf >/dev/null 2>&1; then
  exec > >(stdbuf -oL -eL tee -a "$DEPLOY_LOG") 2>&1
else
  exec > >(tee -a "$DEPLOY_LOG") 2>&1
fi

STEP_N=0
DEPLOY_START=$(date +%s)

ts() { date '+%H:%M:%S'; }

elapsed() {
  local now
  now=$(date +%s)
  echo "$((now - DEPLOY_START))s"
}

step() {
  STEP_N=$((STEP_N + 1))
  echo
  echo "════════════════════════════════════════════════════════"
  echo "[$(ts)] STEP ${STEP_N}/${TOTAL_STEPS} (+$(elapsed))  $*"
  echo "════════════════════════════════════════════════════════"
}

ok() { echo "[$(ts)] ✓ $*"; }
warn() { echo "[$(ts)] ⚠ $*"; }
fail() { echo "[$(ts)] ✗ $*" >&2; }

echo
echo "############################################################"
echo "[$(ts)] SELECTEL DEPLOY START"
echo "[$(ts)] log file: $DEPLOY_LOG"
echo "[$(ts)] app dir:  $APP_DIR"
echo "[$(ts)] branch:   $BRANCH"
echo "############################################################"

mkdir -p "$(dirname "$APP_DIR")"
mkdir -p "$(dirname "$DEPLOY_LOG")"
touch "$DEPLOY_LOG"

step "Sync git repo"
if [[ ! -d "$APP_DIR/.git" ]]; then
  rm -rf "$APP_DIR"
  git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"
git fetch origin --progress
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"
ok "HEAD=$(git rev-parse --short HEAD) $(git log -1 --pretty=%s)"

step "Prepare env (AUTH + secrets)"
mkdir -p deploy
if [[ -f /root/deploy.env && ! -f deploy/.env ]]; then
  cp /root/deploy.env deploy/.env
fi
if [[ ! -f deploy/.env ]]; then
  fail "deploy/.env missing (copy from /root/deploy.env)"
  exit 1
fi
if [[ -f /root/deploy.env ]]; then
  cp /root/deploy.env deploy/.env
fi

ensure_env_default() {
  local key="$1" value="$2"
  if ! grep -qE "^${key}=" deploy/.env; then
    printf '%s=%s\n' "$key" "$value" >> deploy/.env
    ok "added default $key"
  fi
}

ensure_env_default AUTH_ENABLED true
ensure_env_default AUTH_USERNAME admin
ensure_env_default AUTH_PASSWORD admin
ensure_env_default AUTH_SECRET_KEY iris-crm-session-secret

if ! grep -qE '^POSTGRES_PASSWORD=.+' deploy/.env; then
  fail "POSTGRES_PASSWORD missing/empty in deploy/.env"
  exit 1
fi
cp deploy/.env /root/deploy.env
ok "env ready ($(wc -l < deploy/.env) keys)"

step "Host firewall (22/80/443)"
if command -v ufw >/dev/null 2>&1; then
  ufw allow 22/tcp >/dev/null 2>&1 || true
  ufw allow 80/tcp >/dev/null 2>&1 || true
  ufw allow 443/tcp >/dev/null 2>&1 || true
  ufw --force enable >/dev/null 2>&1 || true
  ufw status verbose || true
elif command -v iptables >/dev/null 2>&1; then
  iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || iptables -I INPUT -p tcp --dport 80 -j ACCEPT
  iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || iptables -I INPUT -p tcp --dport 443 -j ACCEPT
  ok "iptables rules for 80/443"
else
  warn "no ufw/iptables — relying on Selectel security group"
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
  fail "$COMPOSE_FILE not found"
  exit 1
fi

ensure_postgres_volume_compatible() {
  if ! docker volume inspect "$PG_VOLUME" >/dev/null 2>&1; then
    ok "Postgres volume $PG_VOLUME does not exist yet — will be created fresh"
    return 0
  fi
  local layout
  layout="$(
    docker run --rm -v "${PG_VOLUME}:/pgvol:ro" alpine:3.20 \
      sh -c '
        if [ -f /pgvol/18/docker/PG_VERSION ]; then echo "ok18:$(cat /pgvol/18/docker/PG_VERSION)"
        elif [ -f /pgvol/*/docker/PG_VERSION ]; then
          v=$(cat /pgvol/*/docker/PG_VERSION 2>/dev/null | head -1 | tr -d "[:space:]")
          echo "okmaj:$v"
        elif [ -f /pgvol/data/PG_VERSION ]; then echo "legacy:$(cat /pgvol/data/PG_VERSION)"
        elif [ -f /pgvol/PG_VERSION ]; then echo "legacy:$(cat /pgvol/PG_VERSION)"
        else echo "empty"
        fi
      ' | tr -d "[:space:]"
  )"
  echo "Postgres volume layout=$layout image_major=$PG_IMAGE_MAJOR"
  local need_reset=0
  case "$layout" in
    empty) return 0 ;;
    ok18:"$PG_IMAGE_MAJOR") return 0 ;;
    okmaj:"$PG_IMAGE_MAJOR") return 0 ;;
    legacy:*|ok18:*|okmaj:*) need_reset=1 ;;
    *) need_reset=1 ;;
  esac
  if [[ "$need_reset" -eq 1 ]]; then
    warn "resetting incompatible postgres volume ($layout)"
    docker compose -f "$COMPOSE_FILE" stop web postgres 2>/dev/null || true
    docker compose -f "$COMPOSE_FILE" rm -f postgres 2>/dev/null || true
    docker volume rm "$PG_VOLUME"
  fi
}

wait_postgres_healthy() {
  local i st
  for i in $(seq 1 36); do
    st="$(docker inspect -f '{{.State.Health.Status}}' deploy-postgres-1 2>/dev/null || echo missing)"
    echo "[$(ts)] postgres health: $st ($i/36)"
    if [[ "$st" == "healthy" ]]; then
      return 0
    fi
    if [[ "$st" == "unhealthy" ]]; then
      docker logs deploy-postgres-1 --tail 40 || true
      return 1
    fi
    sleep 5
  done
  docker logs deploy-postgres-1 --tail 40 || true
  return 1
}

maybe_restore_dump() {
  local dump=/opt/migrate/rail.dump
  if [[ ! -f "$dump" ]]; then
    ok "no dump at $dump — skip restore"
    return 0
  fi
  local count rows pgpass
  count="$(
    docker compose -f "$COMPOSE_FILE" exec -T postgres \
      psql -U app -d app -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='customers';" \
      2>/dev/null || echo 0
  )"
  count="$(echo "$count" | tr -d '[:space:]')"
  if [[ "$count" == "1" ]]; then
    rows="$(
      docker compose -f "$COMPOSE_FILE" exec -T postgres \
        psql -U app -d app -Atc "SELECT count(*) FROM customers;" 2>/dev/null || echo 0
    )"
    rows="$(echo "$rows" | tr -d '[:space:]')"
    if [[ "${rows:-0}" -gt 100 ]]; then
      ok "DB already has $rows customers — skip dump restore"
      return 0
    fi
  fi
  echo "Restoring $dump into postgres..."
  pgpass="$(grep -E '^POSTGRES_PASSWORD=' deploy/.env | cut -d= -f2-)"
  docker compose -f "$COMPOSE_FILE" exec -T postgres \
    psql -U app -d app -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO app;"
  docker run --rm --network deploy_default \
    -v /opt/migrate:/out:ro \
    -e PGPASSWORD="$pgpass" \
    "postgres:${PG_IMAGE_MAJOR}-alpine" \
    pg_restore --no-owner --no-acl -d "postgresql://app:${pgpass}@postgres:5432/app" /out/rail.dump \
    || warn "pg_restore finished with warnings/errors (often OK for partial objects)"
}

step "Check Postgres volume layout"
ensure_postgres_volume_compatible

step "Start redis + postgres"
echo "Deploying $(git log -1 --oneline)"
docker compose -f "$COMPOSE_FILE" up -d redis postgres
ok "infra containers started"

step "Wait for Postgres healthy"
if ! wait_postgres_healthy; then
  fail "postgres did not become healthy"
  exit 1
fi
ok "postgres healthy"

step "Optional DB dump restore"
maybe_restore_dump

step "Build & start web + caddy (this can take several minutes)"
echo "[$(ts)] docker compose build/up — streaming build log…"
# --progress=plain keeps layer output visible over SSH/Actions.
docker compose -f "$COMPOSE_FILE" build --progress=plain web
ok "web image built"
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans
ok "stack up"

step "Health checks"
sleep 3
docker compose -f "$COMPOSE_FILE" ps
echo "--- listening ports ---"
ss -lntp 2>/dev/null | grep -E ':80|:443|:8000' || netstat -lntp 2>/dev/null | grep -E ':80|:443|:8000' || true
echo "--- curl web ---"
curl -fsS -m 10 http://127.0.0.1:8000/health
echo
curl -fsS -m 10 http://127.0.0.1:8000/health/ready || true
echo
echo "--- curl caddy ---"
curl -fsS -m 10 -H 'Host: kinetic-ai.ru' http://127.0.0.1/health || true
echo
ok "health checks done"

echo
echo "############################################################"
echo "[$(ts)] DEPLOY_OK $(git rev-parse --short HEAD)  total=$(elapsed)"
echo "[$(ts)] full log: $DEPLOY_LOG"
echo "############################################################"
