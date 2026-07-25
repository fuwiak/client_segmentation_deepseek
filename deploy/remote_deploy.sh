#!/usr/bin/env bash
# Pull latest main and rebuild the Docker stack on the Selectel VDS.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/app}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.yml}"
REPO_URL="${REPO_URL:-https://github.com/fuwiak/client_segmentation_deepseek.git}"
BRANCH="${BRANCH:-main}"
PG_IMAGE_MAJOR="${PG_IMAGE_MAJOR:-18}"
PG_VOLUME="${PG_VOLUME:-deploy_pg_data}"

mkdir -p "$(dirname "$APP_DIR")"

if [[ ! -d "$APP_DIR/.git" ]]; then
  rm -rf "$APP_DIR"
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
git fetch origin
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"

mkdir -p deploy
if [[ -f /root/deploy.env && ! -f deploy/.env ]]; then
  cp /root/deploy.env deploy/.env
fi

if [[ ! -f deploy/.env ]]; then
  echo "ERROR: deploy/.env missing (copy from /root/deploy.env)" >&2
  exit 1
fi

if ! grep -qE '^POSTGRES_PASSWORD=.+' deploy/.env; then
  echo "ERROR: POSTGRES_PASSWORD missing/empty in deploy/.env" >&2
  exit 1
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "ERROR: $COMPOSE_FILE not found" >&2
  exit 1
fi

ensure_postgres_volume_compatible() {
  # Postgres 18+ mounts /var/lib/postgresql (not .../data). Legacy PGDATA layouts must be wiped.
  if ! docker volume inspect "$PG_VOLUME" >/dev/null 2>&1; then
    echo "Postgres volume $PG_VOLUME does not exist yet — will be created fresh."
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
    echo "WARNING: resetting incompatible postgres volume ($layout)."
    docker compose -f "$COMPOSE_FILE" stop web postgres 2>/dev/null || true
    docker compose -f "$COMPOSE_FILE" rm -f postgres 2>/dev/null || true
    docker volume rm "$PG_VOLUME"
  fi
}

wait_postgres_healthy() {
  local i
  for i in $(seq 1 36); do
    local st
    st="$(docker inspect -f '{{.State.Health.Status}}' deploy-postgres-1 2>/dev/null || echo missing)"
    echo "postgres health: $st ($i/36)"
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
    return 0
  fi
  # Only restore when customers table is missing/empty after volume recreate.
  local count
  count="$(
    docker compose -f "$COMPOSE_FILE" exec -T postgres \
      psql -U app -d app -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='customers';" \
      2>/dev/null || echo 0
  )"
  count="$(echo "$count" | tr -d '[:space:]')"
  if [[ "$count" == "1" ]]; then
    local rows
    rows="$(
      docker compose -f "$COMPOSE_FILE" exec -T postgres \
        psql -U app -d app -Atc "SELECT count(*) FROM customers;" 2>/dev/null || echo 0
    )"
    rows="$(echo "$rows" | tr -d '[:space:]')"
    if [[ "${rows:-0}" -gt 100 ]]; then
      echo "DB already has $rows customers — skip dump restore."
      return 0
    fi
  fi
  echo "Restoring $dump into postgres..."
  local pgpass
  pgpass="$(grep -E '^POSTGRES_PASSWORD=' deploy/.env | cut -d= -f2-)"
  docker compose -f "$COMPOSE_FILE" exec -T postgres \
    psql -U app -d app -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO app;"
  docker run --rm --network deploy_default \
    -v /opt/migrate:/out:ro \
    -e PGPASSWORD="$pgpass" \
    "postgres:${PG_IMAGE_MAJOR}-alpine" \
    pg_restore --no-owner --no-acl -d "postgresql://app:${pgpass}@postgres:5432/app" /out/rail.dump \
    || echo "WARNING: pg_restore finished with warnings/errors (often OK for partial objects)"
}

ensure_postgres_volume_compatible

echo "Deploying $(git log -1 --oneline)"
# Start infra first so we can wait on health before web.
docker compose -f "$COMPOSE_FILE" up -d redis postgres
if ! wait_postgres_healthy; then
  echo "ERROR: postgres did not become healthy" >&2
  exit 1
fi
maybe_restore_dump

docker compose -f "$COMPOSE_FILE" up -d --build --remove-orphans

sleep 5
docker compose -f "$COMPOSE_FILE" ps
curl -fsS -m 10 http://127.0.0.1:8000/health
echo
curl -fsS -m 10 http://127.0.0.1:8000/health/ready || true
echo
echo "DEPLOY_OK $(git rev-parse --short HEAD)"
