#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/paper-analyzer}"
SWAP_SIZE="${SWAP_SIZE:-2G}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$(id -u)" -ne 0 ]]; then
  SUDO="sudo"
else
  SUDO=""
fi

echo "==> [1/4] 检查并安装 Docker 与 Docker Compose 插件..."
if ! command -v docker >/dev/null 2>&1; then
  $SUDO apt-get update
  $SUDO apt-get install -y --no-install-recommends ca-certificates curl gnupg
  curl -fsSL https://get.docker.com | $SUDO sh
  if [[ -n "${SUDO_USER:-}" ]]; then
    $SUDO usermod -aG docker "$SUDO_USER" || true
  fi
fi

if ! docker compose version >/dev/null 2>&1; then
  $SUDO apt-get update
  $SUDO apt-get install -y --no-install-recommends docker-compose-plugin
fi

$SUDO systemctl enable --now docker

echo "==> [2/4] 检查并配置 Swap (${SWAP_SIZE})..."
if [[ -z "$(swapon --show --noheadings)" ]]; then
  if [[ ! -f /swapfile ]]; then
    $SUDO fallocate -l "$SWAP_SIZE" /swapfile || $SUDO dd if=/dev/zero of=/swapfile bs=1M count=2048
    $SUDO chmod 600 /swapfile
    $SUDO mkswap /swapfile
  fi
  $SUDO swapon /swapfile
  if ! grep -q '^/swapfile ' /etc/fstab; then
    echo '/swapfile none swap sw 0 0' | $SUDO tee -a /etc/fstab >/dev/null
  fi
  echo "    已启用 ${SWAP_SIZE} Swap"
else
  echo "    检测到已存在 Swap，跳过创建"
fi

echo "==> [3/4] 初始化部署目录 ${APP_DIR}..."
$SUDO mkdir -p "$APP_DIR"
if [[ -n "${SUDO_USER:-}" ]]; then
  $SUDO chown -R "${SUDO_USER}:${SUDO_USER}" "$APP_DIR"
fi

if [[ ! -f "${APP_DIR}/.env" ]]; then
  if [[ -f "${SCRIPT_DIR}/.env.prod.example" ]]; then
    cp "${SCRIPT_DIR}/.env.prod.example" "${APP_DIR}/.env"
  else
    cat > "${APP_DIR}/.env" <<'EOF'
POSTGRES_DB=paper_analyzer
POSTGRES_USER=paper_admin
POSTGRES_PASSWORD=change_me_to_a_strong_password
IMAGE_PREFIX=ghcr.io/artechphy/academic-paper-analysis-system
IMAGE_TAG=latest
HTTP_PORT=80
UVICORN_WORKERS=2
CORS_ORIGINS=["http://localhost"]
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=
LLM_MODEL=deepseek-chat
LLM_TIMEOUT_S=25.0
EOF
  fi
  # 自动生成随机数据库密码替换占位符
  if command -v openssl >/dev/null 2>&1; then
    RAND_PW="$(openssl rand -hex 16)"
    sed -i "s/change_me_to_a_strong_password/${RAND_PW}/" "${APP_DIR}/.env"
  fi
  chmod 600 "${APP_DIR}/.env"
  echo "    已生成 ${APP_DIR}/.env（权限 600）"
else
  echo "    已存在 ${APP_DIR}/.env，保留原有配置"
fi

echo "==> [4/4] 初始化完成！"
echo "后续步骤："
echo "  1. 按需检查并编辑：${APP_DIR}/.env（例如填入 LLM_API_KEY，2C2G 机器建议设 UVICORN_WORKERS=1）"
echo "  2. 如启用了 UFW 防火墙，请确认放行 SSH 与 HTTP："
echo "     sudo ufw allow OpenSSH && sudo ufw allow 80/tcp"
echo "  3. 在 GitHub 仓库 Secrets 中配置 DEPLOY_HOST / DEPLOY_USER / DEPLOY_SSH_KEY，推送 main 即可自动部署。"
