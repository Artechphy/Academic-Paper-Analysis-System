# 论文格式合规性分析系统（v1 MVP）技术规格书（SPEC）

## 1. 项目定位与目标
本系统为《高级数据库开发》课程项目「论文分析系统」的 **v1 MVP**，核心目标：
- **批量识别哪些论文格式有问题（`FAIL`），哪些论文格式没问题（`PASS`）**，并给出可定位、可解释的违规依据（规则名、严重级别、页码/段落/文本摘录、期望值 vs 实际值）。
- 同时支持 **`.docx`**（优先高精度解析）与 **`.pdf`**（版面/字体/结构解析 + 扫描件检测）。
- 以 **《福建师范大学研究生学位论文基本要求与书写格式（修订）》（师大研〔2019〕7号）** 为核心内置规范（提供 **硕士版 `fjnu_master_2019`（默认）** 与 **博士版 `fjnu_doctor_2019`**），同时内置 **通用学术论文规范 (`general_academic_v1`)**，所有规则模板与参数均持久化于 PostgreSQL 18，支持按模板切换、开关单条规则、调整级别与参数，并支持基于已解析快照免重解析重检。

---

## 2. 技术栈与目录结构
- **数据库**：PostgreSQL 18（Docker Compose 启动独立容器，宿主机映射端口 `55432:5432` 避免与本地 5432 冲突）
- **后端**：Python 3.13（`uv` 管理虚拟环境 `backend/.venv`）、FastAPI、SQLAlchemy 2.0、Alembic、psycopg v3、Pydantic v2、`python-docx`、`lxml`、`PyMuPDF (fitz)`
- **前端**：React 19 + TypeScript + Vite + Tailwind CSS + Lucide Icons
- **目录布局**：
```text
论文分析系统/
├── SPEC.md
├── README.md
├── docker-compose.yml
├── .gitignore
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db/
│   │   │   ├── session.py
│   │   │   ├── base.py
│   │   │   ├── models.py
│   │   │   └── seed.py
│   │   ├── schemas/
│   │   │   ├── ir.py
│   │   │   ├── rules.py
│   │   │   └── checks.py
│   │   ├── parsers/
│   │   │   ├── base.py
│   │   │   ├── docx_parser.py
│   │   │   └── pdf_parser.py
│   │   ├── engine/
│   │   │   ├── evaluator.py
│   │   │   ├── rules_catalog.py
│   │   │   └── utils.py
│   │   ├── services/
│   │   │   ├── paper_service.py
│   │   │   └── check_service.py
│   │   └── api/
│   │       └── v1/
│   │           ├── router.py
│   │           ├── rule_sets.py
│   │           ├── batches.py
│   │           ├── papers.py
│   │           └── stats.py
│   └── tests/
│       ├── conftest.py
│       ├── fixtures_generator.py
│       ├── test_parsers.py
│       ├── test_engine.py
│       └── test_api.py
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── index.html
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── api/
        ├── types/
        └── components/
```

---

## 3. Docker Compose 与 PostgreSQL 18 设计

### 3.1 Docker Compose (`docker-compose.yml`)
- 镜像：`postgres:18-alpine`
- 容器名：`paper_analyzer_pg18`
- 端口：`55432:5432`
- 环境变量：`POSTGRES_DB=paper_analyzer`，`POSTGRES_USER=paper_admin`，`POSTGRES_PASSWORD=paper_admin_dev`
- 健康检查：`pg_isready -U paper_admin -d paper_analyzer`
- 持久化卷：`pg18_data:/var/lib/postgresql/data`（注意：PostgreSQL 18 官方镜像挂载路径如为 `/var/lib/postgresql`，请按 `postgres:18-alpine` 实际规范配置卷路径，避免启动警告/失败！）

### 3.2 核心数据表（PostgreSQL 18）
1. **`rule_sets`（规则模板表）**
   - `id` UUID PK
   - `code` VARCHAR(64) NOT NULL
   - `version` VARCHAR(32) NOT NULL DEFAULT '1.0.0'
   - `name` VARCHAR(128) NOT NULL
   - `description` TEXT
   - `degree_level` VARCHAR(32) NOT NULL DEFAULT 'master' (`master` | `doctor` | `general`)
   - `is_default` BOOLEAN NOT NULL DEFAULT FALSE
   - `is_active` BOOLEAN NOT NULL DEFAULT TRUE
   - `manual_checklist` JSONB NOT NULL DEFAULT '[]'::jsonb（无法自动判定的纸质/主观复核项清单）
   - `created_at` TIMESTAMPTZ NOT NULL DEFAULT now()
   - `updated_at` TIMESTAMPTZ NOT NULL DEFAULT now()
   - 唯一约束：`UNIQUE(code, version)`
   - 部分唯一索引：仅允许一条 `is_default = TRUE` 的模板

2. **`rule_items`（规则配置明细表）**
   - `id` UUID PK
   - `rule_set_id` UUID FK -> `rule_sets(id)` ON DELETE CASCADE
   - `rule_code` VARCHAR(64) NOT NULL
   - `category` VARCHAR(32) NOT NULL (`file` | `page` | `header_footer` | `structure` | `cover` | `typography` | `abstract` | `figure_table` | `reference`)
   - `name` VARCHAR(128) NOT NULL
   - `description` TEXT NOT NULL
   - `severity` VARCHAR(16) NOT NULL CHECK (`severity` IN ('error', 'warning'))
   - `applies_to` VARCHAR(16) NOT NULL CHECK (`applies_to` IN ('docx', 'pdf', 'both'))
   - `params` JSONB NOT NULL DEFAULT '{}'::jsonb
   - `enabled` BOOLEAN NOT NULL DEFAULT TRUE
   - `sort_order` INT NOT NULL DEFAULT 0
   - 唯一约束：`UNIQUE(rule_set_id, rule_code)`
   - 索引：`GIN(params)`、`BTREE(rule_set_id, category)`

3. **`papers`（论文文档与解析快照表）**
   - `id` UUID PK
   - `file_name` VARCHAR(255) NOT NULL（原始文件名，用于 `学号_姓名` 命名规则检查）
   - `file_ext` VARCHAR(16) NOT NULL CHECK (`file_ext` IN ('docx', 'pdf'))
   - `file_size` BIGINT NOT NULL
   - `sha256` CHAR(64) NOT NULL
   - `storage_path` TEXT NOT NULL
   - `page_count` INT
   - `detected_title` VARCHAR(512)
   - `parse_status` VARCHAR(16) NOT NULL CHECK (`parse_status` IN ('success', 'failed'))
   - `parse_error` TEXT
   - `parsed_ir` JSONB（统一 Format IR 快照，支持换模板免重解析重检）
   - `created_at` TIMESTAMPTZ NOT NULL DEFAULT now()
   - 索引：`BTREE(sha256)`、`GIN(parsed_ir)`（便于按解析元数据查询）
   - 注意：同一文件内容可能以不同文件名上传（如修正文件名后重传），因此 `sha256` 建普通索引用于复用物理文件存储，不阻塞带新文件名的重新上传检测。

4. **`check_batches`（批量检测批次表）**
   - `id` UUID PK
   - `name` VARCHAR(128) NOT NULL
   - `rule_set_id` UUID FK -> `rule_sets(id)`
   - `total_count` INT NOT NULL DEFAULT 0
   - `pass_count` INT NOT NULL DEFAULT 0
   - `fail_count` INT NOT NULL DEFAULT 0
   - `error_count` INT NOT NULL DEFAULT 0
   - `status` VARCHAR(16) NOT NULL CHECK (`status` IN ('pending', 'running', 'completed', 'failed'))
   - `created_at` TIMESTAMPTZ NOT NULL DEFAULT now()
   - `completed_at` TIMESTAMPTZ

5. **`check_runs`（单篇检测结论表）**
   - `id` UUID PK
   - `batch_id` UUID FK -> `check_batches(id)` ON DELETE SET NULL
   - `paper_id` UUID FK -> `papers(id)` ON DELETE CASCADE
   - `rule_set_id` UUID FK -> `rule_sets(id)`
   - `verdict` VARCHAR(16) NOT NULL CHECK (`verdict` IN ('pass', 'fail', 'error'))
   - `score` NUMERIC(5,2) NOT NULL DEFAULT 100.00
   - `error_count` INT NOT NULL DEFAULT 0
   - `warning_count` INT NOT NULL DEFAULT 0
   - `passed_rules_count` INT NOT NULL DEFAULT 0
   - `skipped_rules_count` INT NOT NULL DEFAULT 0
   - `duration_ms` INT NOT NULL DEFAULT 0
   - `checked_at` TIMESTAMPTZ NOT NULL DEFAULT now()
   - 索引：`BTREE(batch_id, verdict)`、`BTREE(paper_id, checked_at DESC)`、`BTREE(rule_set_id, verdict)`

6. **`check_violations`（逐条违规明细表）**
   - `id` UUID PK
   - `check_run_id` UUID FK -> `check_runs(id)` ON DELETE CASCADE
   - `rule_item_id` UUID FK -> `rule_items(id)` ON DELETE SET NULL
   - `rule_code` VARCHAR(64) NOT NULL
   - `category` VARCHAR(32) NOT NULL
   - `rule_name` VARCHAR(128) NOT NULL
   - `severity` VARCHAR(16) NOT NULL CHECK (`severity` IN ('error', 'warning'))
   - `location` JSONB NOT NULL DEFAULT '{}'::jsonb（含 `page`, `paragraph_index`, `section`, `excerpt`）
   - `expected` TEXT NOT NULL
   - `actual` TEXT NOT NULL
   - `message` TEXT NOT NULL
   - 索引：`BTREE(check_run_id, severity)`、`BTREE(rule_code)`、`GIN(location)`

### 3.3 PostgreSQL 高级数据库特性（课程亮点，由 Alembic 迁移创建）
1. **数据库触发器**：在 `check_runs` 插入/更新/删除时，自动重算所属 `check_batches` 的 `total_count / pass_count / fail_count / error_count`，保证汇总计数强一致性。
2. **分析视图**：
   - `v_rule_violation_stats`：聚合统计高频违规规则 TOP N、影响论文数、占总违规比例。
   - `v_batch_summary`：聚合各批次通过率、平均分、平均耗时。
3. **JSONB + GIN 索引**与**显式事务边界**：单篇论文解析与检测落库原子提交，避免半成品脏数据。

---

## 4. 统一文档格式 IR（Format IR）

解析器（`.docx` 与 `.pdf`）均输出同一套 Pydantic Schema `DocumentIR`（序列化后存入 `papers.parsed_ir`）：
- `file_name`: str
- `file_ext`: `"docx" | "pdf"`
- `page_count`: int
- `capabilities`: dict[str, bool]（明确声明解析精度：`exact_margins`, `exact_line_spacing`, `exact_header_distance`, `exact_header_border`, `exact_page_number_style`, `exact_font_runs`, `exact_alignment`）
- `is_image_only_pdf`: bool（PDF 文本层检测：正文页文本字符密度极低或几乎全为图像时置 `True`）
- `page_setups`: list[PageSetupIR]（每节/典型页面的 `width_mm`, `height_mm`, `top_margin_mm`, `bottom_margin_mm`, `left_margin_mm`, `right_margin_mm`, `header_distance_mm`, `odd_even_headers`）
- `headers_footers`: HeaderFooterIR
  - `odd_headers`: list[HeaderItemIR]（`text`, `font_name`, `font_size_pt`, `alignment`, `bottom_border_style`, `bottom_border_pt`）
  - `even_headers`: list[HeaderItemIR]
  - `default_headers`: list[HeaderItemIR]
  - `page_numbers`: list[PageNumberIR]（`section_index` / `page_no`, `num_format`: `"roman" | "decimal" | "none"`, `alignment`, `raw_text`）
- `paragraphs`: list[ParagraphIR]
  - `index`: int
  - `page_no`: int | None
  - `section_key`: str | None（自动归类所属文档区块：`cover`, `declaration`, `defense_signature`, `abstract_cn`, `abstract_en`, `toc`, `introduction`, `body`, `conclusion`, `appendix`, `references`, `achievements`, `acknowledgements`, `resume`）
  - `role`: str（`section_heading`, `chapter_heading`, `section_l2_heading`, `section_l3_heading`, `section_l4_heading`, `body_text`, `keywords_cn`, `keywords_en`, `toc_entry`, `figure_caption`, `table_caption`, `reference_entry`, `cover_title`, `other`）
  - `text`: str
  - `font_name`: str | None（主字体，含中文字体回退解析如 OOXML `w:rFonts eastAsia` 与样式继承）
  - `font_name_latin`: str | None（西文字体）
  - `font_size_pt`: float | None
  - `bold`: bool | None
  - `alignment`: str | None（`left` | `center` | `right` | `justify`）
  - `line_spacing_pt`: float | None
  - `line_spacing_rule`: str | None（`at_least` | `exact` | `multiple` | `estimated`）
  - `style_name`: str | None
  - `has_image`: bool
- `sections`: list[DetectedSectionIR]（识别出的顶层模块列表：`key`, `title`, `start_paragraph_index`, `end_paragraph_index`, `page_start`, `chinese_char_count`）
- `figures_tables`: list[FigureTableIR]（`kind`: `"figure" | "table" | "formula"`, `caption_text`, `number_raw`, `paragraph_index`, `alignment`, `relative_position`: `"below" | "above" | "unknown"`）
- `references`: list[ReferenceIR]（`index_num`: int | None, `raw_text`: str, `paragraph_index`: int, `type_code`: str | None, `carrier_code`: str | None, `has_url`: bool, `has_access_date`: bool）
- `stats`: DocumentStatsIR（`total_chinese_chars`, `body_chinese_chars`, `intro_chinese_chars`, `abstract_cn_chars`, `abstract_en_words`, `text_page_ratio`）

### 中文字号与字体的规范映射（`engine/utils.py`）
- 字号（pt，默认容差 `±0.5pt`）：
  - 二号 = `22.0pt`
  - 小二号 = `18.0pt`
  - 小三号 = `15.0pt`
  - 四号 = `14.0pt`
  - 小四号 = `12.0pt`
  - 五号 = `10.5pt`
- 字体归一化（处理中英文别名与 PDF 嵌入子集前缀如 `ABCDEF+SimSun`）：
  - 宋体：`SimSun`, `NSimSun`, `Songti SC`, `STSong`, `宋体`, `华文宋体`, `方正书宋`
  - 黑体：`SimHei`, `Heiti SC`, `STHeiti`, `黑体`, `微软雅黑` 需区分（微软雅黑不算标准黑体，仅标准黑体族归为 `simhei`）
  - Times New Roman：`Times New Roman`, `TimesNewRomanPS`, `Times-Roman`, `TimesNewRoman`

---

## 5. 内置规则模板（严格对齐福建师范大学 2019 规范）

所有福师大规则默认 **`severity = "error"`**（用户明确要求判 `error`），并支持在数据库与前端随时按需切换 `enabled` 或 `severity`。

### 5.1 模板 1：`fjnu_master_2019`（默认，福建师范大学硕士学位论文规范）
| `rule_code` | 类别 | 检查内容与关键参数 | `applies_to` |
| :--- | :--- | :--- | :--- |
| `FILE_NAME_PATTERN` | `file` | 文件名符合 `学号_姓名`（正则 `^\d+_.+\.(docx\|pdf)$`） | `both` |
| `PDF_NOT_IMAGE_ONLY` | `file` | PDF 正文不得为纯图片转换（必须含可选中文本层） | `pdf` |
| `PAGE_SIZE_A4` | `page` | 纸张尺寸 A4（`210×297mm`，容差 `±2.5mm`） | `both` |
| `PAGE_MARGINS` | `page` | 上 `30mm`、下 `30mm`、左 `29mm`、右 `28mm`（docx 容差 `±1.5mm`；pdf 估算容差 `±5mm`） | `both` |
| `LINE_SPACING_MIN` | `page` | 行距最小值 `22pt`（docx 精确校验 `>= 21.5pt`；pdf 基于基线间距校验） | `both` |
| `HEADER_FORMAT` | `header_footer` | 奇偶页不同页眉：单数页为章及标题，双数页匹配 `福建师范大学.+硕士学位论文`；5号宋体 (`10.5pt`)、居中、距边界 `15mm`（docx 精确；pdf 校验奇偶文本与字号） | `both` |
| `HEADER_DOUBLE_BORDER` | `header_footer` | 页眉下方双横线，硕士线粗 `0.5pt`（容差 `±0.25pt`，仅 docx OOXML 精确检测） | `docx` |
| `PAGE_NUMBER_STYLE` | `header_footer` | 页码居中于底部；摘要与目录为罗马数字，绪论/正文/结论/附录/参考文献为阿拉伯数字 | `both` |
| `REQUIRED_SECTIONS` | `structure` | 必须包含：封面、独创性和使用授权声明、学位论文答辩签名表、中文摘要、英文摘要、目录、绪论、正文、结论、参考文献、攻读学位期间科研成果、致谢、个人简历（附录可选） | `both` |
| `SECTION_ORDER` | `structure` | 已出现各模块严格遵守规范先后顺序（若存在附录，须位于结论与参考文献之间） | `both` |
| `COVER_ELEMENTS` | `cover` | 封面须含学校编号 `10394`、图书分类号、中英文题目、作者姓名、专业、导师、学号等关键要素；中文题目二号黑体 (`22pt`) 且 ≤ 20 汉字 | `both` |
| `DECLARATION_TYPOGRAPHY` | `typography` | 独创性和使用授权声明：标题小二号黑体加粗居中 (`18pt`)，正文四号宋体 (`14pt`) | `both` |
| `ABSTRACT_CN_TYPOGRAPHY` | `typography` | 中文摘要：标题小二号宋体加粗居中 (`18pt`)，正文及关键词小四号宋体 (`12pt`) | `both` |
| `ABSTRACT_EN_TYPOGRAPHY` | `typography` | 英文摘要 (`Abstract`)：标题小二号 Times New Roman 加粗居中 (`18pt`)，正文及 Keywords 小四号 Times New Roman (`12pt`) | `both` |
| `TOC_TYPOGRAPHY` | `typography` | 目录：标题小二号宋体加粗居中 (`18pt`)，条目小四号宋体加粗 (`12pt`)，页码小四号 TNR 加粗 (`12pt`) | `docx` |
| `HEADING_TYPOGRAPHY` | `typography` | 绪论/章/结论/附录/参考文献/科研成果/致谢/简历标题：小二号宋体加粗居中 (`18pt`)；节标题：小三号宋体加粗居中 (`15pt`)；条标题：四号宋体加粗 (`14pt`)；款标题：小四号宋体加粗 (`12pt`) | `both` |
| `BODY_TYPOGRAPHY` | `typography` | 正文、绪论、结论及附后各部分正文：小四号宋体 (`12pt`) | `both` |
| `ABSTRACT_CONTENT_RULES` | `abstract` | 中文摘要 ≥ `500` 汉字，不出现参考文献序号 `[1]`；关键词 `3–5` 个、`；` 分隔、总汉字数 ≤ `15` | `both` |
| `WORD_COUNT_REQUIREMENTS` | `abstract` | 硕士正文总汉字数 ≥ `30000`，绪论字数 `3000–5000` | `both` |
| `FIGURE_TABLE_CAPTION` | `figure_table` | 图、表采用阿拉伯数字连续或分章编号；图题位于图下方居中，表题位于表上方居中 | `both` |
| `REFERENCE_GBT7714` | `reference` | 参考文献按 `[1][2]...` 顺序连续编号；符合 GB/T 7714-2015 文献类型标识码（`M/C/G/N/J/D/R/S/P/DB/CP/EB/A/CM/DS/Z` 及 `/OL`, `/CD`, `/MT`, `/DK`）；电子文献须含检索日期与网址 | `both` |

### 5.2 模板 2：`fjnu_doctor_2019`（福建师范大学博士学位论文规范）
复用全部 21 条规则代码，仅参数不同：
- `HEADER_FORMAT`：双数页匹配 `福建师范大学.+博士学位论文`
- `HEADER_DOUBLE_BORDER`：线粗 `1.5pt`
- `ABSTRACT_CONTENT_RULES`：中文摘要 ≥ `800` 汉字
- `WORD_COUNT_REQUIREMENTS`：正文总汉字数 ≥ `50000`，绪论 ≤ `10000`

### 5.3 模板 3：`general_academic_v1`（通用中文学术论文基础规范）
用于非福师大论文的通用检查：A4 纸张、基础页边距、非扫描件 PDF、必备基础结构（标题/摘要/关键词/正文/参考文献）、正文字号一致性、参考文献连续编号与类型标识。

### 5.4 人工复核清单（`manual_checklist`，不触发自动 `FAIL`）
展示在详情页底部供人工二次把关：
1. 封面书脊竖排印制（小三号黑体，距上边线 50mm / 距下边线 30mm）
2. 独创性和使用授权声明是否附本人与导师手写签名扫描件
3. 学位论文答辩签名表是否附答辩委员会主席与成员手写签字扫描件
4. 个人简历左上角是否放置作者小 2 寸彩照
5. 绪论内容与摘要无雷同、正文逻辑严谨与每章小结完整性

---

## 6. 判定逻辑
- `parse_status == 'failed'`（文件损坏/非合法 docx 或 pdf） → `verdict = 'error'`
- `parse_status == 'success'` 且 `error_count == 0` → `verdict = 'pass'`（格式没问题）
- `parse_status == 'success'` 且 `error_count > 0` → `verdict = 'fail'`（格式有问题）
- `score`：满分 100，按启用且适用的规则通过率计算（`round(100 * passed / applicable, 2)`），仅作辅助展示，**最终是否合格严格以 `verdict` 为准**。

---

## 7. REST API 契约（`/api/v1`）
- `GET /api/v1/health`：健康检查（含数据库连接状态）
- `GET /api/v1/rule-sets`：列出所有规则模板及规则数
- `GET /api/v1/rule-sets/{id}`：获取模板详情与全部 `rule_items` 及 `manual_checklist`
- `POST /api/v1/rule-sets`：创建自定义规则模板（支持从已有模板克隆或 JSON 导入）
- `PATCH /api/v1/rule-items/{id}`：更新单条规则的 `enabled`、`severity`、`params`
- `POST /api/v1/batches/check`（`multipart/form-data`）：批量上传多个 `.docx` / `.pdf` 文件 + `rule_set_id` + 可选 `batch_name`，同步解析、执行规则、事务入库并返回完整批次汇总与每篇判定结果
- `GET /api/v1/batches`：列出历史检测批次（含汇总统计）
- `GET /api/v1/batches/{id}`：获取某批次下所有论文的判定列表（支持按 `verdict=pass|fail|error` 和关键字筛选）
- `GET /api/v1/check-runs/{id}`：获取单篇检测详情（含全部 `violations`、`manual_checklist`、论文基础统计与解析能力摘要）
- `POST /api/v1/papers/{id}/recheck`：指定新的 `rule_set_id`，直接复用 `papers.parsed_ir` 重新检测并生成新 `check_run`（无需重传重解析）
- `GET /api/v1/stats/overview`：读取 PostgreSQL 视图返回总检测篇数、总合格率、高频违规规则 TOP 10

---

## 8. 轻量 Web 前端设计（React + Vite + TypeScript）
核心围绕「快速上传 → 一眼分辨合格/有问题 → 点开看精准定位原因 → 灵活调规则重检」：
1. **顶部工作栏**：系统标题、当前规则模板下拉选择器（默认「福建师范大学硕士学位论文规范 2019」）、**「规则配置」**抽屉按钮（可查看每条规范参数、实时开关规则或调整 `error/warning`）。
2. **批量上传区**：支持拖拽/多选 `.docx` 与 `.pdf` 文件，一键开始检测（展示解析与检测进度）。
3. **结果总览与筛选**：
   - 4 个指标卡：总论文数、格式没问题（`PASS`，绿色）、格式有问题（`FAIL`，红色）、解析异常（`ERROR`，琥珀色）。
   - 筛选标签（全部 / 有问题 / 没问题 / 异常）+ 文件名搜索 + 批次切换下拉框。
4. **论文判定列表**：每行显示文件名、类型标签（DOCX/PDF）、**明确结论徽章（合格 / 有问题 / 异常）**、错误数、警告数、合规分、耗时、快捷「详情」与「换模板重检」按钮。
5. **违规详情抽屉**：
   - 论文解析摘要（页数、正文字数、摘要字数、识别出的章节列表）
   - 违规项卡片列表（按 `error` 优先排序：规则名、类别、所在位置/页码/文本摘录、`期望值` vs `实际值`、中文修复建议）
   - 底部折叠区：「需人工复核项清单」
6. **统计弹窗/标签页**（轻量）：展示数据库统计视图返回的高频格式错误 TOP N。

---

## 9. 里程碑拆分（Codex 调度计划）
- **M1（基础设施与数据层）**：`docker-compose.yml`、Python `uv` 项目配置、PostgreSQL 18 SQLAlchemy 模型、Alembic 初始迁移（含触发器、索引、分析视图）、3 套规则模板种子数据、FastAPI 骨架与 `/health`。
- **M2（核心解析器与规则引擎）**：`.docx` 与 `.pdf` 解析器（产出统一 `DocumentIR`）、21 条数据驱动规则引擎、合成测试样本生成器（生成 100% 合规及逐项违规的福师大 `.docx`/`.pdf` 样本）+ `pytest` 单元测试全部通过。
- **M3（业务服务与 REST API）**：完整 API 接口（规则模板管理、批量上传检测、批次查询、单篇详情、免重解析重检、统计视图接口）+ 集成测试全通过。
- **M4（React 前端与端到端联调）**：轻量简洁的 React + Vite + Tailwind UI、连接真实后端、启动前后端及 Docker PG 18 做全流程端到端验证。
