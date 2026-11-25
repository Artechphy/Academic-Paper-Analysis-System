# 论文分析系统（v1 MVP）交接文档（HANDOFF）

> 更新时间：2026-11-24  
> 工作区路径：`/Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统`  
> 当前分支：`main`

---

## 1. 目标与已对齐边界

### 1.1 核心目标与当前口径
- **核心功能**：批量上传论文（同时支持 `.docx` 与 `.pdf`），识别论文格式合规状态（`PASS` / `FAIL` / `ERROR`），并给出按页面顺序排列、原文与规则严格可对照的中文违规明细与在线修订工作台。
- **内置标准规范**：对齐 **《福建师范大学研究生学位论文基本要求与书写格式（修订）》（师大研〔2019〕7号）**，数据库预置 3 套模板：
  1. `fjnu_master_2019`（默认，福建师范大学硕士学位论文规范，21 条规则）
  2. `fjnu_doctor_2019`（福建师范大学博士学位论文规范，21 条规则）
  3. `general_academic_v1`（通用中文学术论文基础规范，6 条规则）
- **已确认产品口径（2026-11-24 对齐）**：
  - 同一规则在同一段落命中的多项子问题**合并为同一条综合违规**（不重复拆分）；跨规则同段问题在页面视图下聚合在同一原文卡片内展示。
  - **暂不处理全英文论文正文**（`肖晓晶.pdf`、`方宏杰.pdf` 保留现状），仅对中文论文中的纯西文/代码/参考文献行放行 `Times New Roman` 及常见等宽字体。
  - 支持对历史已上传论文执行 **「重新解析并检测」**（`reparse=true`），刷新旧 `papers.parsed_ir` 快照，同时保持已有修订会话的历史原稿快照不被破坏。
- **技术栈与环境约束**：
  - 数据库：**Docker Compose 启动 PostgreSQL 18**（映射端口 `55432:5432`，避免冲突本地 Homebrew PG 18 的 `5432`）
  - 后端：Python 3.13（`uv` 管理的 `backend/.venv`）+ FastAPI + SQLAlchemy 2.0 + Alembic + psycopg3 + `python-docx` + `lxml` + `PyMuPDF`
  - 前端：React 19 + TypeScript + Vite + Tailwind CSS v4 + `lucide-react`（**pnpm**）
- **协作分工与防 Goodhart 验收约束**：
  - 后端/解析器/规则引擎/API 由本机 Codex CLI 持久化双会话执行（`impl`：`01a20753-44f3-7782-8848-f71415b18a01`，`audit`：`01a20be9-7f5d-7f90-a7cb-3d2ebb70e044`）；前端与编排验收由 Antigravity 直接完成。
  - 验收目标不以“合成单测全绿”为终点，而是同时卡 **Dev Golden 真实页面真值集 + 5 项全链路不变量 + 视觉 Overlay 原稿核验 + Holdout 盲测随机抽检**。

---

## 2. 已完成进展与验证证据

### Git 里程碑历史
| 里程碑 | 内容与验证状态 |
| :--- | :--- |
| 规格沉淀 (`0c37bd1`) | 初始化仓库、`.gitignore` 与完整技术规格书 [SPEC.md](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/SPEC.md) |
| **M1–M3 后端底座与 REST API** (`541a6f1`–`92e52e0`) | PG 18 容器、6 张核心表、Alembic 迁移与触发器/视图、幂等种子、`.docx`/`.pdf` 双解析器、21 条福师大规则与 11 个基础 REST 接口。 |
| **M4 前端工作台 + 知网调优** (`2bc6edf`–`ed89c8e`) | React 工作台、5 篇真实知网 PDF 首轮调优、PG 18 全栈端到端验收。 |
| **Phase 5 论文修订对照工作台** (`0e6b7cb`–`205da40`) | [PHASE5_SPEC.md](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/PHASE5_SPEC.md)、规则书、DOCX 在线编校与增量重判、Agent 一键修复与左右对照、XeLaTeX 气泡批注 PDF 导出及工作台 UI 重构。 |
| **Phase 6 PDF 基本单位重构与严重级别分级** | 扩展 [ir.py](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/backend/app/schemas/ir.py)（逻辑自然段、下划线行、扫描页、图内文字、续表、子图与题注格式问题），新增迁移 [0003_spacing_rule_severity.py](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/backend/alembic/versions/0003_spacing_rule_severity.py) 将行距/边距/核验类降级为 `warning`。 |
| **Phase 7 违规明细全链路修复、图表/三线表/LaTeX 兼容与双盲验收**（本轮完成） | 1. **P0 排序、综合违规、原文对照与重解析**：[check_service.py](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/backend/app/services/check_service.py) 废除随机 `uuid4` 排序改按 `(page, paragraph_index, severity, rule_code, id)` 稳定排序并支持 `reparse=True`；[evaluator.py](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/backend/app/engine/evaluator.py) 新增 `merge_paragraph_violations` 合并同规则同段子问题；[rules_catalog.py](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/backend/app/engine/rules_catalog.py) 清除页码/字数/摘要借用正文作 `excerpt`、补齐缺题注对象描述与 `BODY_TYPOGRAPHY` `highlight_excerpt`、修复 DOCX 无缓存 `PAGE` 域误报与中文论文纯西文/代码行字体口径。<br>2. **前端违规明细升级**：[ViolationDrawer.tsx](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/frontend/src/components/ViolationDrawer.tsx) 默认提供「按页面顺序」视图（同段多规则聚合 + `异常片段` 高亮），支持切回「按规则分组」，顶部新增「重新解析并检测」按钮。<br>3. **P1/P2 图表、三线表与 LaTeX 通用解析**：[pdf_parser.py](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/backend/app/parsers/pdf_parser.py)、[base.py](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/backend/app/parsers/base.py)、[utils.py](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/backend/app/engine/utils.py) 重构三线表行容差聚类/宽列/双语表题/下置表题回溯；完善表格 vs 矢量图仲裁（保护宽幅问卷网格表、不误吞立体几何/架构图）；支持垂直切片图合并、矢量流程图多簇合并与侧边短标注吸收、跨页连体大图与跨页图题、1 行续表、同行并排左→右排序、3–4 行五号题注与多行章标题合并、正文提及过滤；全面兼容 LaTeX（`TeXGyreTermesX`、数学字体、算法伪代码三线框、参考文献悬挂 `[1]` 标签、18 pt 封面中文题目、双面打印纯白留白页）。<br>4. **全量验证**：PostgreSQL 18 全量 pytest **200 passed, 0 failed**（含真 LibreOffice / XeLaTeX 转换）；`pnpm --dir frontend build` **0 错误通过**；Dev 4 篇 + Holdout 3 篇全链路 5 项不变量全部为 **0**，Dev Golden 从 **19/44 提升至 43/44**。 |

### 中文论文 7 篇实测结果（Dev 4 篇 + Holdout 3 篇盲测，`FJNU_MASTER_RULES`）

> 样本存放于 `.gitignore` 忽略的 `input/caj/` 与 `input/pdf/`；新增的 4 篇 `.caj` 均已无损转为 `repaired=False` 的标准 PDF（含入选优秀论文名单的 LaTeX 参考基准 `吴立钊.pdf`）。

| 分组 | 样本论文 | 页数 | Error / Warning（修复前 → 后） | 已绑定图/表（修复后） | 5 项不变量违例 | 视觉核验说明 |
| :--- | :--- | ---: | ---: | ---: | ---: | :--- |
| Dev | `上官慧华.pdf`（数学教育/Word） | 101 | 270/13 → 180/9 | 57 / 10 | **0** | p.38 垂直切片与跨页连体图、p.46 正方体矢量图与 `图4-10/4-11` 顺序、p.81 章标题页眉通过 |
| Dev | `王飞扬.pdf`（光学工程/Word） | 90 | 251/6 → 43/6 | 54 / 14 | **0** | p.73 标准三线表 `表5-3`、p.41 3–4 行双语图题、p.17 公式编号全部通过 |
| Dev | `卢诗谕.pdf`（音乐教育/Word） | 127 | 294/23 → 240/23 | 39 / 6 | **0** | p.64 1 行跨页续表识别为续表；真外括号题注、偶数页页眉、分类文献召回 100% |
| Dev（优论基准） | `吴立钊.pdf`（计算机/LaTeX） | 100 | 2,180/83 → 375/80 | 21 / 12 | **0** | 封面题目、英文摘要字体、LaTeX 公式/算法框/参考文献悬挂标签、纯白留白页全修通 |
| Holdout（盲测） | `刘紫玲.pdf`（海洋可视化/Word） | 88 | 193/11 → 36/11 | 56 / 16 | **0** | 首轮未见即绑定 56/57 图 + 16/16 表；中文论文纯代码行放行后误报清零 |
| Holdout（盲测） | `陈诚.pdf`（公共管理/Word） | 73 | 203/10 → 179/10 | 4 / 3 | **0** | p.33 下置表题 `表3-1` 准确检出 `table_below` |
| Holdout（盲测） | `谢琳璇.pdf`（体育心理/Word） | 130 | 389/13 → 98/13 | 13 / 57 | **0** | 首轮即框出 57 张 SPSS 多级表头三线表；收口问卷网格表后 Error 降 74.8% |

---

## 3. 下一阶段优先待解决问题（本轮暂不处理）

### P0-1：内嵌原生 PDF 阅读器（替换当前 PDF 的 HTML 段落模拟渲染）
- **现状与问题**：
  - 当前修订工作台 [RevisionWorkspace.tsx](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/frontend/src/components/RevisionWorkspace.tsx) 对 `.pdf` 论文依旧复用 [DocxReaderEditor.tsx](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/frontend/src/components/DocxReaderEditor.tsx) 的结构化 HTML 段落流渲染逻辑。
  - 在 HTML 模拟渲染下，PDF 中的所有插图仅显示 `插图 （图像区域）` 占位文案，表格仅显示 `表格结构单元` 占位条与散落单元格文本，**用户完全无法在页面上看到真实的图片、图表与原版排版**，也无法直观核对规则违规是否对应原稿位置。
- **下一阶段目标方案**：
  1. **后端原件流接口**：新增只读 PDF 原件接口（如 `GET /api/v1/papers/{paper_id}/source` 或 `GET /api/v1/revisions/{session_id}/source-pdf`，支持 `Range` 请求与 `application/pdf` 响应头），直接返回 `paper.storage_path` 中的原始 PDF。
  2. **前端内嵌 PDF 阅读器组件**（如新建 `frontend/src/components/PdfNativeViewer.tsx`，基于 `pdfjs-dist`）：
     - 按页虚拟化/懒加载渲染原生 PDF Canvas（含缩放、页码跳转、缩略/连续滚动）；
     - 在每页 Canvas 上叠放透明 SVG/HTML **坐标高亮层（Overlay）**，直接读取 `ViolationLocation.bbox`（PDF 点坐标 `pt` 映射到当前缩放视口）绘制可点击高亮框；
     - 与右侧 [RulebookPanel.tsx](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/frontend/src/components/RulebookPanel.tsx) 双向联动：点击规则锚点（`P.N` / `第 M 段`）自动滚动到原生 PDF 对应页并闪烁高亮对应 `bbox`；点击高亮框弹出对应违规明细与改写建议。
     - `.docx` 保持现有可编辑 HTML 画布（或支持切换预览 LibreOffice 转换后的 PDF）。

### P0-2：图表渲染异常与 ECharts 图片无法识别
- **现状与用户验收反馈**：
  1. **前端图表渲染问题**：阅读器与详情页中对图表（含 PDF 插图/矢量图与 DOCX 嵌入式图片/Excel Chart）均缺少真实图像预览，导致用户看到图表区域无法可视化核验。
  2. **ECharts 导出图片无法识别**：在真实验收中，使用 ECharts 生成并插入论文的可视化图表图片（如 `input/pdf/基于ECharts的海洋数据可视化平台设计_刘紫玲.pdf` 及同类 ECharts 截图/矢量导出图）存在无法识别或图表边界/渲染异常的情况。
- **下一阶段排查与修复切入点**：
  1. 结合 P0-1 的原生 PDF 阅读器 + 视觉 Overlay，逐页核查 `刘紫玲.pdf`（及同类含 ECharts 图表论文）的 PDF 底层对象结构（`page.get_images(full=True)`、`page.get_image_info(xrefs=True)`、`Form XObject` 嵌套图像、透明蒙版 `SMask`、`page.get_drawings()` 矢量柱/折线/饼图、图内 ECharts 坐标轴与图例文本、以及被误判为装饰图或被 `image_boxes` 尺寸/覆盖率过滤掉的 ECharts 图片）。
  2. 排查 `pdf_parser.py` 中 `_objects()`、`_body_graphics()`、`_is_drawing_container()`、`_combine_subfigures()` 对 ECharts 多图层/带白底/带渐变背景/SVG 转 PDF 矢量图的过滤与聚合边界，补齐 ECharts 图表专项 Golden 页面标注与回归测试。
  3. 同步解决 DOCX 嵌入式图片/Chart 的前端真实缩略图渲染与 PDF 详情卡片中的图表裁切预览（如后端按 `page` + `bbox` 提供按需裁切图或由前端原生 PDF 渲染层直接呈现）。

### P1：盲测复核记录的 3 处残余解析小边角
1. `谢琳璇.pdf` p.32 正文以「`表现、领导力和团队参与...`」起段，因 `^表` 后紧跟汉字被宽松兜底题注正则误命中（需收紧 [base.py](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/backend/app/parsers/base.py) 中文无数字题注匹配）。
2. `陈诚.pdf` p.33 表题下置的三线表最底行因紧贴表题被漏包 1 行（[pdf_parser.py](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/backend/app/parsers/pdf_parser.py) 向上回溯三线表底线容差微调）。
3. `吴立钊.pdf` p.10 流程图左上角最顶行 `模型聚合阶段：` 仍留有 1 条 9 pt 正文排版提示（紧贴图顶短标签的连通块扩展）。

### P2：中长期既有待办
1. **多 LLM 模型效果对比（DeepSeek vs OpenAI vs Gemini）**：在真实学位论文上对比关键词精简、摘要去引用、参考文献补全及自然语言指令遵循的准确率与耗时。
2. **外语专业全英文学位论文模板**：为外语专业硕博论文增补英文排版与字数规则模板（解耦中文正文宋体要求）。
3. **工程文档补齐**：按需补充根目录 `README.md` 与 `TEST-PLAN.md`。

---

## 4. 后端 API 精确契约速查

Schema 源文件：[rules.py](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/backend/app/schemas/rules.py)、[checks.py](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/backend/app/schemas/checks.py)、[revisions.py](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/backend/app/schemas/revisions.py)

- `GET /api/v1/health` → `{ status: "ok" | "unavailable", database: "connected" | "unreachable" }`
- `GET /api/v1/rule-sets` → `RuleSetResponse[]`
- `GET /api/v1/rule-sets/{rule_set_id}` → `RuleSetDetail`
- `POST /api/v1/rule-sets` → `RuleSetCreate` → `201 RuleSetDetail`
- `PATCH /api/v1/rule-items/{rule_item_id}` → `{ enabled?, severity?, params? }` → `RuleItemResponse`
- `POST /api/v1/batches/check`（`multipart/form-data`）：`files`, `rule_set_id`, `batch_name?` → `201 BatchDetail`
- `GET /api/v1/batches` → `BatchSummary[]`
- `GET /api/v1/batches/{batch_id}?verdict=pass|fail|error&q=...` → `BatchDetail`
- `GET /api/v1/check-runs/{run_id}` → `CheckRunDetail`（`violations` 按页码→段序稳定排序，同规则同段已合并，`location` 含 `page_end?`、`highlight_excerpt?`、`bbox?`）
- `POST /api/v1/papers/{paper_id}/recheck` → `{ rule_set_id: UUID, reparse?: boolean }` → `201 CheckRunDetail`
- `GET /api/v1/stats/overview` → `StatsOverview`
- `POST /api/v1/check-runs/{run_id}/revisions` → `201 RevisionSessionDetail`
- `GET /api/v1/revisions/{session_id}` → `RevisionSessionDetail`
- `PATCH /api/v1/revisions/{session_id}/paragraphs/{paragraph_index}` → `ParagraphEditRequest` → `ParagraphEditResponse`
- `PATCH /api/v1/revisions/{session_id}/document-settings` → `DocumentSettingsRequest` → `RevisionSessionDetail`
- `POST /api/v1/revisions/{session_id}/auto-fix` → `{ instruction?, rule_codes? }` → `RevisionSessionDetail`
- `POST /api/v1/revisions/{session_id}/export/annotated-pdf` → `{ page_mode: "issues_only" | "full" }` → `AnnotatedPdfExportResponse`
- `GET /api/v1/revisions/{session_id}/download/{kind}`（`kind`: `docx` | `annotated_pdf`）→ 文件下载流

---

## 5. 运行环境与日常启动命令

1. **Docker PostgreSQL 18 容器**：
   ```bash
   docker compose up -d --wait
   cd backend && .venv/bin/alembic upgrade head && .venv/bin/python -m app.db.seed
   TEST_DATABASE_URL="postgresql+psycopg://paper_admin:paper_admin_dev@127.0.0.1:55432/paper_analyzer" backend/.venv/bin/pytest -q
   ```
2. **本地前后端启动命令**：
   ```bash
   # 后端 FastAPI（http://127.0.0.1:8000）
   backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
   # 前端 Vite（http://127.0.0.1:5173）
   pnpm --dir frontend dev --host 127.0.0.1 --port 5173
   ```
3. **DeepSeek LLM 默认配置（`backend/.env`）**：未配置 `LLM_API_KEY` 时自动降级为确定性规则修复与文案；本机导出默认 `/opt/homebrew/bin/xelatex` 与 `/opt/homebrew/bin/soffice`。
