# Phase 5 技术规格书：论文修订对照工作台（PHASE5_SPEC）

> 更新时间：2026-11-23  
> 状态：已与用户对齐全部核心交互与技术边界；后端实现 100% 委托 Codex CLI（复用会话 `01a20753-44f3-7782-8848-f71415b18a01`），前端由 Antigravity 直接实现。

---

## 1. 目标与核心交互闭环

Phase 5 在已有「批量检测 → 结论列表 → 违规详情抽屉」之上，新增 **「调整论文」** 独立工作台，打通以下 6 步闭环：

1. **错误聚类成可查规则书（Rulebook）**：将单篇检测产出的几十至数百条原始 `check_violations` 按规则/类别收敛为可检索、可筛选的规则书（区分「全局」「同类聚合」「单点」），彻底消除原始报错刷屏。
2. **进入「调整论文」页面**：从结果表或详情抽屉点击「调整论文」，创建或恢复持久化的 `RevisionSession`（保留原文档与原始 `parsed_ir` 不可变快照）。
3. **DOCX 结构化阅读器 + 原位错误标注**：按真实段落索引渲染类纸张阅读视图（还原封面、各级标题、正文、图表占位、参考文献的字体/字号/加粗/对齐/行距），在有问题的段落旁挂接行内高亮与右侧错误气泡。
4. **手动修改与「改哪段判哪段」增量重判（DOCX）**：点击任意段落可编辑文字或排版样式（字体/字号/加粗/对齐/行距），保存后精准更新工作副本 `.docx` 对应 OOXML `<w:p>` 节点并增量重判，改对后错误气泡实时消去、得分与规则书状态同步更新；支持单段一键撤销还原。
5. **Agent「一键修改」+ 左右双重对照 + 用户指令迭代**：
   - 确定性 OOXML 修复器 + DeepSeek LLM 语义文本修复器协同工作。
   - 自动切换为**左右双重对照视图**：左侧为只读原稿（高亮变更处），右侧为可继续手动微调的修订稿（同样支持单段编辑、撤销与增量重判）。
   - 支持用户输入自然语言建议（如“保留英文引用段字体”“关键词保留‘高中生’并压缩至 15 字内”）再次触发 Agent 调整。
6. **产物导出下载**：
   - `.docx` 支持导出最终修订版 `.docx`（融合 Agent 修复 + 人工二次修改，支持建议合规文件名 `学号_姓名.docx`）。
   - `.docx` 与 `.pdf` 均支持导出 **LaTeX 气泡批注 PDF**（`xelatex` + `pdfpages` + `tikz`，左页原样保真 + 右侧批注栏箭头指向 `bbox` 坐标，支持「仅问题页（快）」与「完整论文」双模式）。

### 1.1 格式能力边界（已确认）
- **`.docx`（`editable = true`）**：支持全流程（可查规则书 + 在线段落编辑 + 改哪段判哪段 + 一键修复 + 左右双栏同步编辑对照 + 下载 `.docx` + 导出 LaTeX 气泡 PDF）。
- **`.pdf`（`editable = false`）**：支持只读规则书 + 文本类改写建议与用户反馈迭代 + 左右对照原摘录与建议稿 + 导出 LaTeX 气泡 PDF；调用段落写接口或下载 `.docx` 返回 `HTTP 400`。

### 1.2 LLM 接入与后续优化点（已确认）
- **当前默认接入**：OpenAI 兼容 HTTP 客户端（复用 `httpx`），默认配置 **DeepSeek**（`LLM_BASE_URL=https://api.deepseek.com/v1`，`LLM_MODEL=deepseek-chat`，`LLM_API_KEY` 通过 `.env` 注入）。未配置 API Key 或接口异常时自动降级为纯确定性样式修复与规则文案，保证本地零外部依赖可快速演示部署。
- **后续优化点（写入交接文档待办）**：开展多模型对比评测（**DeepSeek vs OpenAI vs Gemini** 在中文学术规范文本压缩、参考文献 GB/T 7714 修复与指令遵循上的准确率与延迟）。

---

## 2. 既有模块扩展（最小改动、向后兼容）

### 2.1 `DocumentIR` 与 `location.bbox` 坐标透传
1. **`backend/app/schemas/ir.py`**：
   - 为 `ParagraphIR`、`HeaderItemIR`、`PageNumberIR`、`FigureTableIR` 增加可选字段：
     `bbox: tuple[float, float, float, float] | None = None`（PDF 点坐标 `[x0, y0, x1, y1]`，左上角为原点，单位 pt）。
   - `PageSetupIR` 已有 `width_mm`/`height_mm`，若未显式存 pt，LaTeX 渲染器可通过 `mm_to_pt` 或直接读取 PyMuPDF 原页面 `rect`。
2. **`backend/app/parsers/pdf_parser.py` & `backend/app/parsers/base.py`**：
   - `_lines()` 阶段已有 `box`（`pymupdf.Rect`），赋值到 `ParagraphIR.bbox = (round(box.x0, 2), round(box.y0, 2), round(box.x1, 2), round(box.y1, 2))`；在 `_join_line_fragments`、跨行段落合并及参考文献合并时，计算联合包围盒 `union bbox`（`min x0, min y0, max x1, max y1`）。
   - 页眉、页码与图表对象同步填充 `bbox`。
3. **`backend/app/engine/rules_catalog.py`**：
   - `_location()` 当传入 `paragraph`（或其他含 `bbox` 对象）且其 `bbox` 非空时，将 `"bbox": list(bbox)` 写入 `location` 字典。
   - **向后兼容**：既有历史 `papers.parsed_ir` 或 `check_violations.location` 无 `bbox` 时默认 `None`，不影响既有任何规则判断与测试。

### 2.2 `backend/app/config.py`
在 `Settings` 中新增：
- `llm_base_url: str = "https://api.deepseek.com/v1"`
- `llm_api_key: str | None = None`
- `llm_model: str = "deepseek-chat"`
- `llm_timeout_s: float = 25.0`
- `xelatex_bin: str = "/opt/homebrew/bin/xelatex"`
- `soffice_bin: str = "/opt/homebrew/bin/soffice"`
- `revisions_dir: Path = Path(__file__).resolve().parents[1] / "storage" / "revisions"`

---

## 3. 数据库设计（Alembic `0002_revision_sessions.py`）

在 `backend/app/db/models.py` 与新迁移 `backend/alembic/versions/0002_revision_sessions.py` 新增 2 张表（同步兼容 `backend/tests/conftest.py` 的 SQLite JSONB→JSON 转换）：

1. **`revision_sessions`（修订会话与工作状态表）**
   - `id`: UUID PK
   - `check_run_id`: UUID FK → `check_runs(id)` `ON DELETE CASCADE`
   - `paper_id`: UUID FK → `papers(id)` `ON DELETE CASCADE`
   - `rule_set_id`: UUID FK → `rule_sets(id)`
   - `target_file_name`: `VARCHAR(255)` NOT NULL（初始为 `paper.file_name`，可在修订中调整为 `学号_姓名.docx`）
   - `working_docx_path`: `TEXT` NULL（`.docx` 工作副本磁盘路径）
   - `annotated_pdf_path`: `TEXT` NULL（最近一次编译生成的 LaTeX 气泡 PDF 路径）
   - `annotated_page_mode`: `VARCHAR(16)` NULL（`'issues_only' | 'full'`）
   - `version`: `INT` NOT NULL DEFAULT `1`
   - `comparison_ready`: `BOOLEAN` NOT NULL DEFAULT `FALSE`
   - `llm_used`: `BOOLEAN` NOT NULL DEFAULT `FALSE`
   - `llm_model`: `VARCHAR(64)` NULL
   - `verdict`: `VARCHAR(16)` NOT NULL CHECK (`'pass' | 'fail' | 'error'`)
   - `score`: `NUMERIC(5,2)` NOT NULL DEFAULT `100.00`
   - `error_count`: `INT` NOT NULL DEFAULT `0`
   - `warning_count`: `INT` NOT NULL DEFAULT `0`
   - `original_error_count`: `INT` NOT NULL DEFAULT `0`
   - `current_ir`: `JSONB` NOT NULL
   - `current_violations`: `JSONB` NOT NULL DEFAULT `'[]'::jsonb`
   - `rulebook`: `JSONB` NOT NULL DEFAULT `'[]'::jsonb`
   - `changes`: `JSONB` NOT NULL DEFAULT `'[]'::jsonb`（记录变更段落 Diff）
   - `modified_paragraphs`: `JSONB` NOT NULL DEFAULT `'[]'::jsonb`（已改动段落索引数组）
   - `created_at`: `TIMESTAMPTZ` NOT NULL DEFAULT `now()`
   - `updated_at`: `TIMESTAMPTZ` NOT NULL DEFAULT `now()`
   - 索引：`BTREE(check_run_id, updated_at DESC)`

2. **`revision_feedbacks`（用户意见与 Agent 执行记录表）**
   - `id`: UUID PK
   - `session_id`: UUID FK → `revision_sessions(id)` `ON DELETE CASCADE`
   - `version`: `INT` NOT NULL
   - `author`: `VARCHAR(16)` NOT NULL CHECK (`'user' | 'agent'`)
   - `rule_code`: `VARCHAR(64)` NULL
   - `paragraph_index`: `INT` NULL
   - `instruction`: `TEXT` NOT NULL
   - `summary`: `TEXT` NULL
   - `created_at`: `TIMESTAMPTZ` NOT NULL DEFAULT `now()`
   - 索引：`BTREE(session_id, created_at)`

---

## 4. 后端修订引擎包（`backend/app/revisions/`）

### 4.1 `consolidator.py` — 错误聚类与规则书构建
- 输入：当前 `violations` 列表、原始 `original_violations`（用于保留 `original_count` 及已修复统计）、`rule_items`。
- 聚类逻辑（每条规则产出 1 条或按局部异常细分的 `RulebookEntry`）：
  - **`global`（全局项）**：`FILE_NAME_PATTERN`、`PDF_NOT_IMAGE_ONLY`、`PAGE_SIZE_A4`、`PAGE_MARGINS`、`REQUIRED_SECTIONS`、`SECTION_ORDER`、`WORD_COUNT_REQUIREMENTS`、`HEADER_FORMAT`（若整篇统一不符）、`HEADER_DOUBLE_BORDER`。全篇合并为 1 条，附受影响页码概览与修改指引。
  - **`cluster`（同类聚合项）**：`BODY_TYPOGRAPHY`、`LINE_SPACING_MIN`、`HEADING_TYPOGRAPHY`、`PAGE_NUMBER_STYLE`、`ABSTRACT_CN_TYPOGRAPHY`、`ABSTRACT_EN_TYPOGRAPHY`、`DECLARATION_TYPOGRAPHY`、`TOC_TYPOGRAPHY`。合并全部同名规则违规，汇总 `total_count`、受影响段落/页码区间，并按页挑选代表性锚点（`representative_anchors`）。
  - **`point`（单点内容项）**：`COVER_ELEMENTS`、`ABSTRACT_CONTENT_RULES`、`FIGURE_TABLE_CAPTION`、`REFERENCE_GBT7714`。
- **气泡密度限制**：面向 PDF 导出的标注抽取层（`select_pdf_annotations(rulebook)`）严格控制**单页最多 4 个气泡、全篇最多 25 个代表性气泡**，确保页面清爽可读。
- **状态判定**：`status = "fixed"` 当 `original_count > 0` 且当前 `total_count == 0`；否则 `"open"`（或用户标记忽略时 `"ignored"`）。

### 4.2 `incremental.py` — OOXML 精准定位、单段编辑与「改哪段判哪段」增量重判
- **OOXML `<w:p>` 索引映射（必须与 `docx_parser._body` 完全一致）**：
  - 使用 `docx_parser._walk(document.element.body, {qn("w:p"), qn("w:tbl")}, TRANSPARENT_WRAPPERS)` 遍历文档主体：
    - 遇到普通 `<w:p>` 时映射到当前 `ParagraphIR.index`；
    - 遇到 `<w:tbl>` 时先跳过 1 个索引（对应 `docx_parser` 插入的 `object_kind="table"` 占位 `ParagraphIR`），再按 `element.iter(qn("w:p"))` 顺序映射每个表格单元格内的 `<w:p>`。
  - 提供 `find_paragraph_element(document, paragraph_index)`，若指向占位 `table` 对象或越界则抛出清晰 `ValueError`。
- **单段 OOXML 修改与撤销**：
  - **文本修改**：若原段含 `<w:drawing>`/`<w:pict>`（图片段）或公式节点 `<m:oMath>`，禁止直接清空重排，仅编辑纯文本 Run（保留首条 `<w:rPr>` 格式）；普通文本段更新 `<w:t>` 文本并保持原有 `<w:rPr>`/`<w:pPr>`。
  - **样式修改**：
    - `font_name`：通过 OOXML `w:rFonts` 同时写入 `eastAsia` 与 `ascii`/`hAnsi`（映射关系：`simsun → 宋体`、`simhei → 黑体`、`times_new_roman → Times New Roman`、`microsoft_yahei → 微软雅黑`）；若指定 `times_new_roman` 则三槽均设为 `Times New Roman`。
    - `font_size_pt`：写入 `w:sz` / `w:szCs`（`int(round(pt * 2))`）。
    - `bold`：写入 `w:b` / `w:bCs`。
    - `alignment`：写入 `<w:jc w:val="..."/>`（`justify → both`）。
    - `line_spacing_pt`：写入 `<w:spacing w:line="{int(round(pt * 20))}" w:lineRule="atLeast"/>`（若指定值 `< 22` 且需精确表达或 `>= 22`，均可正确被 `docx_parser` 解析为 `line_spacing_pt`）。
  - **撤销（`revert=true`）**：从不可变原件 `paper.storage_path` 读取对应 `paragraph_index` 的原始 `<w:p>` XML 节点替换回工作 `.docx`（并从 `paper.parsed_ir` 还原该段 `ParagraphIR`），保证 100% 无损复原。
- **增量重判 `evaluate_incremental`**：
  - 更新工作副本 `.docx` 后，直接更新内存 `DocumentIR` 中该段的字段与 `analyze_document(ir)`（重算 `sections`、`figures_tables`、`references`、`stats`，耗时 < 5ms）；
  - 按影响范围精确重判：
    - 仅重跑受当前段落影响的段落级规则（如 `BODY_TYPOGRAPHY`、`LINE_SPACING_MIN`、`HEADING_TYPOGRAPHY`、各部分排版规则、`FIGURE_TABLE_CAPTION`、`REFERENCE_GBT7714`、`COVER_ELEMENTS`、`ABSTRACT_CONTENT_RULES`）以及依赖统计/顺序的全局汇总规则（`WORD_COUNT_REQUIREMENTS`、`REQUIRED_SECTIONS`、`SECTION_ORDER`）；页面设置与文件名规则在未修改页面设置时直接沿用既有结论（修改页面设置时重跑页面/页眉/文件名规则）；
    - 重新计算 `verdict`、`score`、`error_count`、`warning_count`、`rulebook`，同时返回该段落当前剩余违规 `paragraph_violations` 及本轮消除的错误数 `resolved_count`。

### 4.3 `docx_fixer.py` — 确定性 OOXML 一键修复器（方案 B）
针对工作副本 `.docx`，仅修改可确定性安全修复的样式与结构属性，**绝不编造正文内容或破坏无关图表公式**：
1. **页面与页眉页脚**：
   - 将所有节设为 A4（`210×297mm`）及规范页边距（读取当前模板 `PAGE_MARGINS` 参数，默认 `30/30/29/28mm`）；
   - 开启奇偶页不同页眉（`odd_and_even_pages_header_footer = True`），按模板配置修复页眉文字（奇数页章标题/偶数页匹配模板正则如 `福建师范大学教育学硕士学位论文`）、5 号宋体居中、距边界 `15mm` 与规范双横线底边框（硕士 `0.5pt` / 博士 `1.5pt`）；
   - 修复页脚页码位置居中及摘要/目录罗马数字、正文阿拉伯数字格式。
2. **排版样式**：
   - 按模板 `BODY_TYPOGRAPHY`、`LINE_SPACING_MIN`、`HEADING_TYPOGRAPHY`、`DECLARATION_TYPOGRAPHY`、`ABSTRACT_CN_TYPOGRAPHY`、`ABSTRACT_EN_TYPOGRAPHY`、`TOC_TYPOGRAPHY` 自动校正对应区块段落字体、字号、加粗、对齐与最小行距（`>= 22pt`）。
3. **应用 LLM 文本改写建议**：
   - 对 LLM 返回且通过安全校验（非空、非正文叙事段落）的 `text_replacements`（如关键词压缩精简、清除中文摘要内的 `[1]` 序号、参考文献 GB/T 7714 格式修补），按 `paragraph_index` 写回 `.docx` 并记录 `ParagraphDiff(source="llm")`。
4. **Word 原生审阅批注（兜底提示）**：
   - 对于无法自动补齐的缺失项（如缺独创性声明、正文字数不足 30000 字），在对应段落或文档首段写入说明记录与规则书提示（若写入 Word `w:comment` 须保证 OOXML 合法且 `python-docx` / `libreoffice` 可无报错打开）。
5. **全量复检**：修复完成后用 `parse_docx` 重解析工作副本 `.docx` 并执行全量 `evaluate`，生成完整 `changes: ParagraphDiff[]` 并置 `comparison_ready = True`。

### 4.4 `llm_advisor.py` — DeepSeek OpenAI 兼容 JSON Advisor
- 使用 `httpx.Client` 向 `{settings.llm_base_url}/chat/completions` 发送请求（`Authorization: Bearer {settings.llm_api_key}`，`model=settings.llm_model`，`response_format={"type": "json_object"}`）。
- **单次结构化输入**（严格控制 Token 与延迟在 2–4 秒）：
  - 当前规则书摘要（最多 25 条，含 `rule_code`, `expected`, `actual_summary`, 样本摘录）
  - 文本类待修段落片段（如 `abstract_cn` 段落、`keywords_cn` 段落、异常参考文献条目、封面超长题目）
  - 本轮用户自然语言指令 `instruction`（如有）及历史反馈摘要
- **Pydantic 校验输出 `AdvisorOutput`**：
  - `summary`: 本轮修订总评（中文）
  - `rulebook_notes`: `dict[rule_code, { bubble_note: str, guidance: str, ignore: bool }]`（简洁清晰的中文气泡文案 ≤ 60 字）
  - `text_replacements`: `list[{ paragraph_index: int, new_text: str, reason: str }]`（安全护栏：仅允许作用于 `abstract_cn` / `keywords_cn` / `reference_entry` / `cover_title` / `heading` 编号，若某条 `new_text` 对非参考文献/非关键词正文缩水 > 45% 则自动丢弃，防止误删内容）
- **无 Key / 异常优雅降级**：若 `settings.llm_api_key` 为空或请求超时/返回非法 JSON，不抛 500，记录 `llm_used=False` 并回退到确定性中文建议模板与基础规则清洗（如自动去除摘要中 `[1]` 引用标记）。

### 4.5 `latex_annotator.py` — LaTeX `pdfpages + tikz` 气泡批注 PDF 编译
1. **获取原底稿 PDF**：
   - 若论文为 `.pdf`：直接使用 `paper.storage_path`（只读）。
   - 若论文为 `.docx`：若已做过修订/一键修复则对最新工作 `.docx` 转换，否则对原 `.docx` 按 `sha256` 缓存调用 `/opt/homebrew/bin/soffice --headless --convert-to pdf --outdir ...` 生成底稿 PDF。
2. **生成 `.tex` 并编译**：
   - 使用 `/opt/homebrew/bin/xelatex -interaction=nonstopmode -halt-on-error`，支持两种 `page_mode`：
     - `"issues_only"`（默认，1–3 秒）：第 1 页修订总览封面 + 仅包含代表性气泡的页面；
     - `"full"`：第 1 页修订总览封面 + 原文档全部分页。
   - **纸张与气泡布局**：
     - 采用横版/宽幅自定义纸张（例如宽 `297mm × 高 297mm`，左侧 `0..210mm` 居中/贴左嵌入原 A4 页面，右侧 `215..290mm` 为批注栏）。
     - 在右侧批注栏放置带色圆角 `tikz` 气泡卡片（`ERROR` 红框、`WARN` 橙框、`FIXED` 绿框），内置纵向防重叠算法（按 `y` 排序递增卡位），并用折线箭头指向原页 `bbox`（若无 `bbox` 则指向对应页右侧边缘估计位置）。
   - **字体与转义**：使用 macOS 已核验中文字体 `\setCJKmainfont{Songti SC}`（或 `STSong`）；实现严格 LaTeX 转义函数转义 `\`、`{`、`}`、`$`、`&`、`#`、`%`、`^`、`~`、`_` 并剔除控制字符，确保任何中文/英文/公式摘录都 100% 编译通过。

---

## 5. 精确 API 与 Schema 契约（`/api/v1`）

源文件：`backend/app/schemas/revisions.py`、`backend/app/services/revision_service.py`、`backend/app/api/v1/revisions.py`。

### 5.1 关键 Schema
- `AnchorLocation`: `{ page: int | None = None, paragraph_index: int | None = None, bbox: list[float] | None = None, excerpt: str | None = None }`
- `RulebookEntry`:
  - `rule_code: str`
  - `rule_name: str`
  - `category: str`
  - `severity: Literal["error", "warning"]`
  - `scope: Literal["global", "cluster", "point"]`
  - `status: Literal["open", "fixed", "ignored"]`
  - `total_count: int`
  - `original_count: int`
  - `expected: str`
  - `actual_summary: str`
  - `guidance: str`
  - `bubble_note: str`
  - `can_auto_fix: bool`
  - `affected_paragraphs: list[int]`
  - `affected_pages: list[int]`
  - `representative_anchors: list[AnchorLocation]`
- `ParagraphDiff`:
  - `paragraph_index: int`
  - `page_no: int | None = None`
  - `section_key: str | None = None`
  - `before_text: str`
  - `after_text: str`
  - `style_changes: list[str]`（如 `["字体: 微软雅黑 → 宋体", "字号: 14pt → 12pt"]`）
  - `source: Literal["manual", "rule", "llm"]`
  - `summary: str`
- `RevisionFeedbackItem`:
  - `id: UUID`, `version: int`, `author: Literal["user", "agent"]`, `rule_code: str | None`, `paragraph_index: int | None`, `instruction: str`, `summary: str | None`, `created_at: datetime`
- `RevisionSessionDetail`:
  - `id: UUID`, `check_run_id: UUID`, `paper_id: UUID`, `rule_set_id: UUID`
  - `file_name: str`, `target_file_name: str`, `file_ext: Literal["docx", "pdf"]`, `editable: bool`
  - `version: int`, `comparison_ready: bool`, `annotated_pdf_ready: bool`, `annotated_page_mode: Literal["issues_only", "full"] | None`
  - `llm_used: bool`, `llm_model: str | None`
  - `verdict: Verdict`, `score: float`, `error_count: int`, `warning_count: int`, `original_error_count: int`
  - `rulebook: list[RulebookEntry]`
  - `original_paragraphs: list[ParagraphIR]`
  - `current_paragraphs: list[ParagraphIR]`
  - `violations: list[ViolationResponse]`（无 DB violation id 时用确定性合成或 `UUID` 兼容字段）
  - `changes: list[ParagraphDiff]`
  - `modified_paragraphs: list[int]`
  - `feedbacks: list[RevisionFeedbackItem]`
  - `updated_at: datetime`
- `ParagraphEditRequest`:
  - `{ text?: str, font_name?: str | None, font_size_pt?: float | None, bold?: bool | None, alignment?: Alignment | None, line_spacing_pt?: float | None, revert?: bool }`
- `ParagraphEditResponse`:
  - `{ paragraph: ParagraphIR, paragraph_violations: list[ViolationResponse], resolved_count: int, remaining_count: int, verdict: Verdict, score: float, error_count: int, warning_count: int, rulebook: list[RulebookEntry], changes: list[ParagraphDiff], modified_paragraphs: list[int], version: int }`
- `DocumentSettingsRequest`:
  - `{ target_file_name?: str, fix_page_size_a4?: bool, fix_margins?: bool, fix_headers?: bool }`
- `AutoFixRequest`:
  - `{ instruction?: str | None, rule_codes?: list[str] | None }`
- `AnnotatedPdfExportRequest`:
  - `{ page_mode?: Literal["issues_only", "full"] }`
- `AnnotatedPdfExportResponse`:
  - `{ annotated_pdf_ready: bool, page_mode: Literal["issues_only", "full"], page_count: int, download_url: str }`

### 5.2 7 个 REST 接口
1. `POST /api/v1/check-runs/{run_id}/revisions`（Query `force_new: bool = False`）→ `201 RevisionSessionDetail`
2. `GET /api/v1/revisions/{session_id}` → `RevisionSessionDetail`
3. `PATCH /api/v1/revisions/{session_id}/paragraphs/{paragraph_index}` → `ParagraphEditResponse`
4. `PATCH /api/v1/revisions/{session_id}/document-settings` → `RevisionSessionDetail`
5. `POST /api/v1/revisions/{session_id}/auto-fix` → `RevisionSessionDetail`
6. `POST /api/v1/revisions/{session_id}/export/annotated-pdf` → `AnnotatedPdfExportResponse`
7. `GET /api/v1/revisions/{session_id}/download/{kind}`（`kind: Literal["docx", "annotated_pdf"]`）→ `FileResponse`

---

## 6. 前端「调整论文」工作台设计（`frontend/src/`）

1. **入口接入**：在 [ResultsTable.tsx](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/frontend/src/components/ResultsTable.tsx) 操作列与 [ViolationDrawer.tsx](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/frontend/src/components/ViolationDrawer.tsx) 顶部工具条增加 **「调整论文」** 主按钮（`parse_status === 'success'` 时可用）。
2. **三区协同工作台（[RevisionWorkspace.tsx](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/frontend/src/components/RevisionWorkspace.tsx)）**：
   - **顶部 Sticky 工具条**：返回工作台、文件名与实时 `verdict / score / 错误数变化 (如 4 → 0)`、文档级快捷修复（仅 `.docx`：规范文件名 / A4 / 页边距 / 奇偶页眉）、**「一键修改（Agent 修复）」**、「单栏编辑 / 左右双重对照」切换、「下载修订 DOCX」、「导出 LaTeX 气泡批注 PDF（仅问题页 / 完整论文）」。
   - **左侧栏（[RulebookPanel.tsx](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/frontend/src/components/RulebookPanel.tsx)）**：可查规则书，支持关键字搜索、状态筛选（全部 / 未修复 / 已修复）、展示 `全局 / 同类聚合 / 单点` 徽章与影响数，点击锚点标签直接滚动定位到目标段落。
   - **主阅读编校区（[DocxReaderEditor.tsx](file:///Users/artechphy/Documents/作业/大三上/高级数据库开发/论文分析系统/frontend/src/components/DocxReaderEditor.tsx)）**：
     - 纸张视觉流式阅读器，按 `role` 渲染题目、各级标题、正文、图表占位与参考文献，在段落旁挂接行内高亮与右侧错误气泡。
     - 单击任意段落打开行内编辑 + 浮动样式栏（字体、字号、加粗、对齐、行距、`保存并重判`、`撤销还原`），保存即时触发单段增量重判并清除已解决气泡。
     - 点击「一键修改」后默认进入**左右双重对照**：左栏只读原稿（标出变更前原文与高亮）vs 右栏 Agent 修复后的可编辑修订稿（**仍支持右侧直接点击继续修改与增量重判**）。
   - **底部用户反馈栏**：支持输入自然语言意见（如“英文摘要不要改动专业术语”“保留这个关键词”）提交给 Agent 执行下一轮修订迭代并展示版本记录（`v1 → v2`）。
