#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${APP_DIR}/docker-compose.prod.yml"
ENV_FILE="${APP_DIR}/.env"
LAST_TAG_FILE="${APP_DIR}/.last_deployed_tag"

read_env_val() {
  local key="$1"
  [[ -f "$ENV_FILE" ]] || return 0
  awk -F= -v k="$key" '
    $0 ~ /^[[:space:]]*#/ { next }
    $1 == k { sub(/^[^=]*=/, ""); print; exit }
  ' "$ENV_FILE" | tr -d '\r'
}

COMPOSE_ARGS=(-f "$COMPOSE_FILE")
if [[ -f "$ENV_FILE" ]]; then
  COMPOSE_ARGS+=(--env-file "$ENV_FILE")
fi

ARG_TAG="${1:-}"
FILE_IMAGE_PREFIX="$(read_env_val IMAGE_PREFIX)"
FILE_IMAGE_TAG="$(read_env_val IMAGE_TAG)"
FILE_HTTP_PORT="$(read_env_val HTTP_PORT)"

if [[ -n "${IMAGE_PREFIX:-}" ]]; then
  export IMAGE_PREFIX
elif [[ -n "$FILE_IMAGE_PREFIX" ]]; then
  export IMAGE_PREFIX="$FILE_IMAGE_PREFIX"
fi

export IMAGE_TAG="${ARG_TAG:-${IMAGE_TAG:-${FILE_IMAGE_TAG:-latest}}}"
HTTP_PORT="${HTTP_PORT:-${FILE_HTTP_PORT:-80}}"

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
docker compose "${COMPOSE_ARGS[@]}" pull backend web

if [[ "$LOGGED_IN_GHCR" == "true" ]]; then
  docker logout ghcr.io >/dev/null 2>&1 || true
fi

echo "==> 启动 PostgreSQL 18 并等待健康..."
docker compose "${COMPOSE_ARGS[@]}" up -d --wait postgres

echo "==> 执行数据库迁移与预置规则种子..."
docker compose "${COMPOSE_ARGS[@]}" run --rm --no-deps backend sh -c "alembic upgrade head && python -m app.db.seed"

echo "==> 启动/更新 backend 与 web 服务..."
docker compose "${COMPOSE_ARGS[@]}" up -d --remove-orphans

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
  docker compose "${COMPOSE_ARGS[@]}" logs --tail=80 backend web || true
  if [[ -n "$PREVIOUS_TAG" && "$PREVIOUS_TAG" != "$IMAGE_TAG" ]]; then
    echo "==> 回滚到上一可用版本: ${PREVIOUS_TAG}"
    export IMAGE_TAG="$PREVIOUS_TAG"
    docker compose "${COMPOSE_ARGS[@]}" up -d --remove-orphans || true
  fi
  exit 1
fi

printf '%s\n' "$IMAGE_TAG" > "$LAST_TAG_FILE"
echo "==> 清理未使用的旧镜像..."
docker image prune -f >/dev/null 2>&1 || true
echo "==> 部署完成 (当前版本: ${IMAGE_TAG})"
