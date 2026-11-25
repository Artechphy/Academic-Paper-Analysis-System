# Ubuntu 云服务器部署指南（Docker + Nginx + GitHub Actions CI/CD）

本方案面向低成本演示环境，使用 **GitHub Actions** 免费构建 Linux 容器镜像并推送至 **GitHub Container Registry (GHCR)**，再通过 SSH 自动部署到任意 **Ubuntu 22.04 / 24.04 云服务器**。云服务器本地无需编译 TeX/LibreOffice 或前端包，只需拉取镜像运行即可。

---

## 1. 服务器配置建议

| 资源项 | 推荐配置（演示流畅） | 最低配置（极限省钱） | 说明 |
| :--- | :--- | :--- | :--- |
| **系统** | Ubuntu 22.04 / 24.04 LTS | Ubuntu 22.04 / 24.04 LTS | 64 位 x86_64 |
| **CPU / 内存** | **2 vCPU / 4 GiB RAM** | **2 vCPU / 2 GiB RAM** | 2 GiB 机型务必开启 4 GiB Swap 且设 `UVICORN_WORKERS=1` |
| **磁盘** | **≥ 30 GiB** | **≥ 25 GiB** | `backend` 镜像含 LibreOffice + XeLaTeX + 中文字体，解压后约 2.2 GiB |
| **开放端口** | `22`（SSH）、`80`（HTTP） | `22`、`80` | `postgres:5432` 与 `backend:8000` 仅 Docker 内网互通，不暴露公网 |

---

## 2. Ubuntu 服务器一次性初始化

登录你的 Ubuntu 云服务器后，拉取或上传本仓库的 `deploy/` 目录（或直接执行以下命令）：

```bash
# 1. 下载或进入仓库后，以 2G Swap（2G 内存机器建议改 SWAP_SIZE=4G）执行初始化：
chmod +x deploy/bootstrap-ubuntu.sh
SWAP_SIZE=2G ./deploy/bootstrap-ubuntu.sh

# 2. 检查生成的生产环境变量：
nano /opt/paper-analyzer/.env
```

重点检查 `/opt/paper-analyzer/.env` 中以下参数：
- `POSTGRES_PASSWORD`：`bootstrap-ubuntu.sh` 已自动生成随机密码（若未生成请手动修改）。
- `UVICORN_WORKERS`：4 GiB 内存设为 `2`；2 GiB 内存建议改为 `1`。
- `LLM_API_KEY`：如需演示 AI 改写，填入 DeepSeek Key；留空则自动降级为确定性规则修复。

> 若需要把当前非 root 登录用户加入 `docker` 组后立即生效，可执行 `newgrp docker` 或重连一次 SSH。

---

## 3. 配置 GitHub Secrets（触发自动部署）

在 GitHub 仓库 **Settings → Secrets and variables → Actions → Repository secrets** 中添加：

| Secret 名称 | 必填 | 示例 / 说明 |
| :--- | :---: | :--- |
| `DEPLOY_HOST` | 是 | Ubuntu 服务器公网 IP 或域名 |
| `DEPLOY_USER` | 是 | SSH 登录用户名（如 `ubuntu` 或 `root`，需具备免密码运行 `docker` 权限） |
| `DEPLOY_SSH_KEY` | 是 | 用于连接服务器的 SSH 私钥完整内容（`-----BEGIN ...-----`） |
| `DEPLOY_PORT` | 否 | SSH 端口，不填默认 `22` |
| `GHCR_USER` | 私有库必填 | 你的 GitHub 用户名（若仓库为 Public 且 GHCR 镜像公开，可不填） |
| `GHCR_TOKEN` | 私有库必填 | 具备 `read:packages` 权限的 GitHub Classic PAT（供服务器 `docker login ghcr.io` 拉取私有镜像） |

> 提示：在配置好 `DEPLOY_HOST` 和 `DEPLOY_SSH_KEY` 之前，推送 `main` 分支仍然会正常执行测试并推送镜像到 GHCR，远程 SSH 部署步骤会自动跳过，不会导致流水线报错。

---

## 4. 发布与验收

1. **自动触发**：向 `main` 分支推送代码，`.github/workflows/deploy.yml` 会自动执行：
   - 前端构建校验（`pnpm build`）
   - 后端镜像构建并在容器内连接 `postgres:18-alpine` 执行全量 `pytest`
   - 推送 `backend:sha-<7位>` / `web:sha-<7位>` 与 `latest` 到 GHCR
   - SSH 上传 `docker-compose.prod.yml` 与 `deploy.sh` 到 `/opt/paper-analyzer/`，执行 `alembic upgrade head`、`python -m app.db.seed` 并重启容器
2. **手动触发 / 指定版本回滚**：
   - 在 GitHub 仓库 **Actions → Build and Deploy to Ubuntu** 点击 **Run workflow**，输入历史标签（如 `sha-abc1234`）即可回滚或重放部署。
3. **验收检查**：
   - 浏览器访问 `http://<服务器IP>/` 能打开工作台；
   - 访问 `http://<服务器IP>/api/v1/health` 返回 `{"status":"ok","database":"connected"}`；
   - 上传一篇 `.docx` 或 `.pdf` 论文检测并导出批注 PDF，验证中文批注正常生成。

---

## 5. 常用运维与排障命令

在 Ubuntu 服务器 `/opt/paper-analyzer` 目录下执行：

```bash
# 查看容器状态与实时日志
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f --tail=100 backend web

# 手动回滚到指定标签
./deploy.sh sha-abc1234

# 演示结束后停机并清理数据卷（彻底释放磁盘）
docker compose -f docker-compose.prod.yml down -v
docker system prune -af
```

### 国内云服务器网络提示
- 若服务器位于国内且访问 `ghcr.io` 较慢，可为 Docker daemon 配置可用的 registry mirror，或直接在 GitHub Actions 中保留构建，在服务器上配置 HTTP/HTTPS 代理供 Docker daemon 拉取镜像（`/etc/systemd/system/docker.service.d/http-proxy.conf`）。
- 如需公网演示时增加一层简易账号密码弹窗，取消 `frontend/nginx.conf` 中 `auth_basic` 两行注释，并在 `docker-compose.prod.yml` 为 `web` 挂载 `.htpasswd` 文件即可。
