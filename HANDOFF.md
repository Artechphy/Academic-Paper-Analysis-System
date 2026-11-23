# 论文分析系统（v1 MVP）交接文档（HANDOFF）

> 更新时间：2026-11-23  
> 工作区路径：`/Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统`  
> 当前分支：`main`

---

## 1. 目标与已对齐边界

### 1.1 v1 MVP 核心目标
- **核心功能**：批量上传论文（同时支持 `.docx` 与 `.pdf`），准确识别哪些论文格式有问题（`FAIL`）、哪些格式没问题（`PASS`）、哪些文件损坏无法解析（`ERROR`），并给出可定位的中文违规明细（规则名、类别、严重级别、页码/段落/摘录、期望值 vs 实际值）。
- **内置标准规范**：严格对齐用户提供的 **《福建师范大学研究生学位论文基本要求与书写格式（修订）》（师大研〔2019〕7号）**，数据库预置 3 套模板：
  1. `fjnu_master_2019`（默认，福建师范大学硕士学位论文规范，21 条规则）
  2. `fjnu_doctor_2019`（福建师范大学博士学位论文规范，21 条规则）
  3. `general_academic_v1`（通用中文学术论文基础规范，6 条规则）
- **判定严格度（用户已明确）**：福师大模板全部 21 条规则默认 `severity = "error"`（包含文件名 `学号_姓名`、总字数 3万/5万、答辩签名表）；同时数据库与 API 支持实时开关单条规则、切换 `error`/`warning`、调参、克隆模板，并支持基于 `papers.parsed_ir` JSONB 快照免重解析重检。
- **技术栈与环境约束（用户已明确）**：
  - 数据库：**Docker Compose 启动 PostgreSQL 18**（映射端口 `55432:5432`，避免冲突本地 Homebrew PG 18 的 `5432`）
  - 后端：Python 3.13（`uv` 管理的 `backend/.venv`）+ FastAPI + SQLAlchemy 2.0 + Alembic + psycopg3 + `python-docx` + `lxml` + `PyMuPDF`
  - 前端：React 19 + TypeScript + Vite + Tailwind CSS v4 + `lucide-react`（**pnpm**）
- **分工约束（用户已明确）**：
  - 后端/解析器/规则引擎/API：由 **Codex CLI (`OpenAI Codex v0.171.0`, `gpt-6.2-sol`, `reasoning effort: high`)** 协作实现（M1–M3 及真实知网 PDF 调优已完成）
  - **Milestone 4 前端开发**：由 Antigravity 直接实现（已完成并构建通过）
  - **网络与记忆偏好（已完成同步）**：本地 `65533` 代理端口已停用、后续网络访问优先直连，已同步至 `~/.gemini/config/plugins/personal-memory/rules/AGENTS.md` 与 `references/profile-snapshot-2026-11-20.md`。

---

## 2. 已完成进展与验证证据

### Git 提交与里程碑历史
| 里程碑 | 内容与验证状态 |
| :--- | :--- |
| 规格沉淀 (`0c37bd1`) | 初始化仓库、`.gitignore` 与完整技术规格书 [SPEC.md](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/SPEC.md) |
| **M1 基础设施与数据层** (`541a6f1`) | `docker-compose.yml`（`name: paper-analyzer`，PG 18 卷挂载 `/var/lib/postgresql`）、`backend/pyproject.toml`、`backend/uv.lock`、6 张核心表、Alembic `0001_initial.py`（含触发器 `trg_sync_check_batch_counts` 与分析视图 `v_rule_violation_stats` / `v_batch_summary`）、幂等种子脚本 `seed.py`、FastAPI `/api/v1/health`。 |
| **M2 解析器与规则引擎** (`487a563`) | 统一 `DocumentIR`、`.docx`（OOXML）与 `.pdf`（PyMuPDF）双解析器、21 条福师大规则与通用规则引擎、样本生成器。原 61 项 pytest 通过。 |
| **M3 业务服务与完整 REST API** (`92e52e0`) | 完整实现 SPEC 第 7 节全部 11 个 REST 接口、SHA-256 去重存储、事务回滚保护、免重解析重检、SQLite 等价触发器/视图集成测试。原 69 项 pytest 通过。 |
| **M4 React 前端 + 知网 PDF 解析调优 + PG 18 全栈验收**（已完成） | 1. **`.gitignore` 与前端依赖**：忽略 `.pnpm-store/`、`input/` 与 `*.tsbuildinfo`；`frontend/pnpm-workspace.yaml` 启用 `esbuild: true` 并完成 `pnpm install --dir frontend`。<br>2. **前端工作台（`frontend/src/`）**：实现完整学术编校工作台（`TopBar`、`UploadZone`、`KpiBar`、`ResultsTable`、`ViolationDrawer` 规则分组聚合与手动复核清单、`RuleConfigDrawer` 实时调参与模板克隆、`StatsView` TOP 10 统计与历史批次汇总）。`pnpm --dir frontend build`（`tsc -b && vite build`）**0 错误通过**。<br>3. **5 篇真实知网硕士论文 PDF 调优（Codex CLI）**：修复 PDF 基线行距容差、嵌入式/乱码宋体映射与混排英文处理、代表性正文页边距采样、装饰性矢量图过滤、跨行参考文献合并、页眉/目录误切换模块及 `cnki_abstract` 识别；新增 [test_pdf_regressions.py](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/backend/tests/test_pdf_regressions.py) 17 项回归测试。<br>4. **PostgreSQL 18 真库与端到端全栈验收**：`docker compose up -d --wait` 启动 `paper_analyzer_pg18`（健康运行于 `127.0.0.1:55432`），`alembic upgrade head` 与两次 `python -m app.db.seed` 幂等通过；`TEST_DATABASE_URL="postgresql+psycopg://paper_admin:paper_admin_dev@127.0.0.1:55432/paper_analyzer" backend/.venv/bin/pytest -q` **86 项全部通过**。浏览器访问 `http://127.0.0.1:5173` 完成 `PG18 已连接`、合成样本（`PASS`/`FAIL`/`ERROR`）、违规抽屉与免重解析重检、21 条规则配置与模板克隆、2 篇真实知网 PDF 批量检测及 `统计洞察` 视图全流程验收，零控制台与接口错误。 |

### 5 篇真实知网 PDF（`input/pdf/`）调优前后对比（`FJNU_MASTER_RULES`）
| 样本论文 | 页数 | 调优前违规数 → 调优后违规数 | 说明 |
| :--- | ---: | ---: | :--- |
| `基于“互联网+”的高中生数学自主学习策略研究_上官慧华.pdf` | 101 | 7,191 → 439 | 恢复答辩签名表与科研成果模块，真实文件名/缺声明/关键词超长/正文字数仍精准检出 |
| `多模态话语分析视角下高中英语深度阅读教学模式的建构研究_肖晓晶.pdf` | 128 | 3,576 → 779 | 识别英文专著/章结构与 `cnki_abstract` |
| `快速光声成像系统的优化设计及若干应用_王飞扬.pdf` | 90 | 1,866 → 372 | 中文摘要字数恢复准确提取（805 字），消除大量伪图题与换行参考文献误报 |
| `福州市中考英语口语人机对话考试现状调查研究_方宏杰.pdf` | 111 | 5,065 → 769 | 识别英文正文章节结构与 `cnki_abstract`，真实顺序/关键词缺陷保留 |
| `高师音乐教育专业“艺术实践+思政”育人模式探究_卢诗谕.pdf` | 127 | 4,371 → 354 | 识别结论与附录模块，正文字数（52,022 字）与绪论超长仍准确判定 |

---

## 3. 后端 API 精确契约速查（前端已全部对接）

Schema 源文件：[rules.py](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/backend/app/schemas/rules.py)、[checks.py](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/backend/app/schemas/checks.py)

- `GET /api/v1/health` → `{ status: "ok" | "unavailable", database: "connected" | "unreachable" }`
- `GET /api/v1/rule-sets` → `RuleSetResponse[]`
- `GET /api/v1/rule-sets/{rule_set_id}` → `RuleSetDetail`
- `POST /api/v1/rule-sets` → `RuleSetCreate` → `201 RuleSetDetail`
- `PATCH /api/v1/rule-items/{rule_item_id}` → `{ enabled?, severity?, params? }` → `RuleItemResponse`
- `POST /api/v1/batches/check`（`multipart/form-data`）：`files`, `rule_set_id`, `batch_name?` → `201 BatchDetail`
- `GET /api/v1/batches` → `BatchSummary[]`
- `GET /api/v1/batches/{batch_id}?verdict=pass|fail|error&q=...` → `BatchDetail`
- `GET /api/v1/check-runs/{run_id}` → `CheckRunDetail`
- `POST /api/v1/papers/{paper_id}/recheck` → `{ rule_set_id: UUID }` → `201 CheckRunDetail`
- `GET /api/v1/stats/overview` → `StatsOverview`

---

## 4. 运行环境状态与日常启动指南

1. **Docker PostgreSQL 18 容器**：
   - `paper_analyzer_pg18`（`postgres:18-alpine`，端口 `55432:5432`）已拉取并初始化完成，Alembic 迁移与 3 套规则模板种子均已落库，真库全量测试（86 项）通过。
   - 若后续重启宿主机，可执行以下命令拉起数据库或重跑真库测试：
     ```bash
     docker compose up -d --wait
     cd backend && .venv/bin/alembic upgrade head && .venv/bin/python -m app.db.seed
     TEST_DATABASE_URL="postgresql+psycopg://paper_admin:paper_admin_dev@127.0.0.1:55432/paper_analyzer" backend/.venv/bin/pytest -q
     ```
2. **本地前后端开发启动命令**：
   ```bash
   # 终端 1（后端 FastAPI）
   cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
   # 终端 2（前端 Vite）
   pnpm --dir frontend dev --host 127.0.0.1 --port 5173
   ```
   访问 `http://127.0.0.1:5173`，顶部状态显示 `PG18 已连接` 即可正常使用。
