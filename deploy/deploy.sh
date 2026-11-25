#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${APP_DIR}/docker-compose.prod.yml"
ENV_FILE="${APP_DIR}/.env"
LAST_TAG_FILE="${APP_DIR}/.last_deployed_tag"

ARG_TAG="${1:-}"
OVERRIDE_IMAGE_TAG="${IMAGE_TAG:-}"
OVERRIDE_IMAGE_PREFIX="${IMAGE_PREFIX:-}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [[ -n "$OVERRIDE_IMAGE_PREFIX" ]]; then
  export IMAGE_PREFIX="$OVERRIDE_IMAGE_PREFIX"
fi
export IMAGE_TAG="${ARG_TAG:-${OVERRIDE_IMAGE_TAG:-${IMAGE_TAG:-latest}}}"

PREVIOUS_TAG=""
if [[ -f "$LAST_TAG_FILE" ]]; then
  PREVIOUS_TAG="$(tr -d '[:space:]' < "$LAST_TAG_FILE")"
fi

LOGGED_IN_GHCR=false
if [[ -n "${GHCR_USERNAME:-}" && -n "${GHCR_TOKEN:-}" ]]; then
  echo "==> 登录 GHCR (${GHCR_USERNAME})..."
  printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USERNAME" --password-stdin
  LOGGED_IN_GHCR=true
fi

echo "==> 拉取镜像 (IMAGE_PREFIX=${IMAGE_PREFIX:-ghcr.io/artechphy/academic-paper-analysis-system}, IMAGE_TAG=${IMAGE_TAG})..."
docker compose -f "$COMPOSE_FILE" pull backend web

if [[ "$LOGGED_IN_GHCR" == "true" ]]; then
  docker logout ghcr.io >/dev/null 2>&1 || true
fi

echo "==> 启动 PostgreSQL 18 并等待健康..."
docker compose -f "$COMPOSE_FILE" up -d --wait postgres

echo "==> 执行数据库迁移与预置规则种子..."
docker compose -f "$COMPOSE_FILE" run --rm --no-deps backend sh -c "alembic upgrade head && python -m app.db.seed"

echo "==> 启动/更新 backend 与 web 服务..."
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans

HEALTH_URL="http://127.0.0.1:${HTTP_PORT:-80}/api/v1/health"
echo "==> 校验健康状态 (${HEALTH_URL})..."
HEALTHY=false
for _ in $(seq 1 30); do
  BODY="$(curl -sf "$HEALTH_URL" || true)"
  if [[ "$BODY" == *'"status":"ok"'* && "$BODY" == *'"database":"connected"'* ]]; then
    HEALTHY=true
    echo "    健康检查通过: ${BODY}"
    break
  fi
  sleep 2
done

if [[ "$HEALTHY" != "true" ]]; then
  echo "::error::健康检查超时，打印最近日志："
  docker compose -f "$COMPOSE_FILE" logs --tail=80 backend web || true
  if [[ -n "$PREVIOUS_TAG" && "$PREVIOUS_TAG" != "$IMAGE_TAG" ]]; then
    echo "==> 回滚到上一可用版本: ${PREVIOUS_TAG}"
    export IMAGE_TAG="$PREVIOUS_TAG"
    docker compose -f "$COMPOSE_FILE" up -d --remove-orphans || true
  fi
  exit 1
fi

printf '%s\n' "$IMAGE_TAG" > "$LAST_TAG_FILE"
echo "==> 清理未使用的旧镜像..."
docker image prune -f >/dev/null 2>&1 || true
echo "==> 部署完成 (当前版本: ${IMAGE_TAG})"
