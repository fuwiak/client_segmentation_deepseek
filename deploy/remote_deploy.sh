#!/usr/bin/env bash
# Pull latest main and rebuild the Docker stack on the Selectel VDS.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/app}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.yml}"
REPO_URL="${REPO_URL:-https://github.com/fuwiak/client_segmentation_deepseek.git}"
BRANCH="${BRANCH:-main}"

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

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "ERROR: $COMPOSE_FILE not found" >&2
  exit 1
fi

echo "Deploying $(git log -1 --oneline)"
docker compose -f "$COMPOSE_FILE" up -d --build --remove-orphans

sleep 5
docker compose -f "$COMPOSE_FILE" ps
curl -fsS -m 10 http://127.0.0.1:8000/health
echo
curl -fsS -m 10 http://127.0.0.1:8000/health/ready || true
echo
echo "DEPLOY_OK $(git rev-parse --short HEAD)"
