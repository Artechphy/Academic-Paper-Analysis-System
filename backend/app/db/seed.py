"""Install the built-in rule templates with `python -m app.db.seed`."""

from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import RuleItem, RuleSet


@dataclass(frozen=True)
class RuleSeed:
    code: str
    category: str
    name: str
    description: str
    params: dict[str, Any]
    applies_to: str = "both"


@dataclass(frozen=True)
class TemplateSeed:
    code: str
    name: str
    description: str
    degree_level: str
    rules: tuple[RuleSeed, ...]
    manual_checklist: tuple[str, ...] = ()
    is_default: bool = False


FJNU_MANUAL_CHECKLIST = (
    "封面书脊竖排印制（小三号黑体，距上边线 50mm、距下边线 30mm）",
    "独创性和使用授权声明是否附本人与导师手写签名扫描件",
    "学位论文答辩签名表是否附答辩委员会主席与成员手写签字扫描件",
    "个人简历左上角是否放置作者小 2 寸彩照",
    "绪论内容与摘要是否无雷同、正文逻辑是否严谨、每章小结是否完整",
)

FJNU_SECTION_ORDER = (
    "cover", "declaration", "defense_signature", "abstract_cn", "abstract_en", "toc",
    "introduction", "body", "conclusion", "appendix", "references", "achievements",
    "acknowledgements", "resume",
)

FJNU_MASTER_RULES = (
    RuleSeed(
        "FILE_NAME_PATTERN", "file", "论文文件命名", "文件名采用学号_姓名格式。",
        {"pattern": r"^\d+_.+\.(docx|pdf)$"},
    ),
    RuleSeed(
        "PDF_NOT_IMAGE_ONLY", "file", "PDF 正文文本层", "PDF 正文须含可选中的文本层。",
        {"allow_image_only": False}, applies_to="pdf",
    ),
    RuleSeed(
        "PAGE_SIZE_A4", "page", "A4 纸张", "页面宽度及高度须符合 A4 纸张尺寸。",
        {"width_mm": 210, "height_mm": 297, "tolerance_mm": 2.5},
    ),
    RuleSeed(
        "PAGE_MARGINS", "page", "页边距", "检查上、下、左、右页边距，PDF 使用估算容差。",
        {
            "top_mm": 30, "bottom_mm": 30, "left_mm": 29, "right_mm": 28,
            "docx_tolerance_mm": 1.5, "pdf_tolerance_mm": 5,
        },
    ),
    RuleSeed(
        "LINE_SPACING_MIN", "page", "最小行距", "行距至少 22pt，DOCX 最低实测 21.5pt，PDF 按基线间距估算。",
        {"min_pt": 22, "docx_tolerance_pt": 0.5, "pdf_measurement": "baseline"},
    ),
    RuleSeed(
        "HEADER_FORMAT", "header_footer", "奇偶页页眉", "奇数页页眉显示章及标题，偶数页显示对应的福师大学位论文名称。",
        {
            "odd_even_headers": True,
            "odd_text_source": "chapter_heading",
            "even_pattern": r"福建师范大学.+硕士学位论文",
            "font_name": "simsun", "font_size_pt": 10.5, "font_size_tolerance_pt": 0.5,
            "alignment": "center", "header_distance_mm": 15,
            "pdf_fields": ["odd_text", "even_text", "font_size_pt"],
        },
    ),
    RuleSeed(
        "HEADER_DOUBLE_BORDER", "header_footer", "页眉双横线", "页眉下方使用规范粗细的双横线。",
        {"style": "double", "width_pt": 0.5, "tolerance_pt": 0.25}, applies_to="docx",
    ),
    RuleSeed(
        "PAGE_NUMBER_STYLE", "header_footer", "页码格式", "页码位于底部居中，摘要和目录用罗马数字，其余规定章节用阿拉伯数字。",
        {
            "position": "footer", "alignment": "center",
            "roman_sections": ["abstract_cn", "abstract_en", "toc"],
            "decimal_sections": ["introduction", "body", "conclusion", "appendix", "references"],
        },
    ),
    RuleSeed(
        "REQUIRED_SECTIONS", "structure", "必备文档模块", "论文须包含规范规定的模块，附录可选。",
        {"required_sections": [key for key in FJNU_SECTION_ORDER if key != "appendix"]},
    ),
    RuleSeed(
        "SECTION_ORDER", "structure", "文档模块顺序", "已出现的模块须遵守规定顺序，附录位于结论和参考文献之间。",
        {"section_order": list(FJNU_SECTION_ORDER)},
    ),
    RuleSeed(
        "COVER_ELEMENTS", "cover", "封面要素与中文题目", "封面须包含规范要素，学校编号为 10394，中文题目采用二号黑体且至多 20 个汉字。",
        {
            "required_elements": [
                "school_code", "library_classification", "title_cn", "title_en",
                "author_name", "major", "supervisor", "student_id",
            ],
            "school_code": "10394", "title_cn_max_chinese_chars": 20,
            "title_cn_style": {"font_name": "simhei", "font_size_pt": 22},
            "font_size_tolerance_pt": 0.5,
        },
    ),
    RuleSeed(
        "DECLARATION_TYPOGRAPHY", "typography", "独创性和使用授权声明排版", "声明标题小二号黑体加粗居中，正文四号宋体。",
        {
            "section_key": "declaration", "font_size_tolerance_pt": 0.5,
            "heading": {"font_name": "simhei", "font_size_pt": 18, "bold": True, "alignment": "center"},
            "body": {"font_name": "simsun", "font_size_pt": 14},
        },
    ),
    RuleSeed(
        "ABSTRACT_CN_TYPOGRAPHY", "typography", "中文摘要排版", "中文摘要标题小二号宋体加粗居中，正文及关键词小四号宋体。",
        {
            "section_key": "abstract_cn", "font_size_tolerance_pt": 0.5,
            "heading": {"font_name": "simsun", "font_size_pt": 18, "bold": True, "alignment": "center"},
            "body": {"font_name": "simsun", "font_size_pt": 12},
            "keywords": {"font_name": "simsun", "font_size_pt": 12},
        },
    ),
    RuleSeed(
        "ABSTRACT_EN_TYPOGRAPHY", "typography", "英文摘要排版", "Abstract 标题小二号 Times New Roman 加粗居中，正文及 Keywords 小四号 Times New Roman。",
        {
            "section_key": "abstract_en", "font_size_tolerance_pt": 0.5,
            "heading": {
                "text": "Abstract", "font_name": "times_new_roman", "font_size_pt": 18,
                "bold": True, "alignment": "center",
            },
            "body": {"font_name": "times_new_roman", "font_size_pt": 12},
            "keywords": {"font_name": "times_new_roman", "font_size_pt": 12},
        },
    ),
    RuleSeed(
        "TOC_TYPOGRAPHY", "typography", "目录排版", "目录标题小二号宋体加粗居中，条目小四号宋体加粗，页码小四号 Times New Roman 加粗。",
        {
            "section_key": "toc", "font_size_tolerance_pt": 0.5,
            "heading": {"font_name": "simsun", "font_size_pt": 18, "bold": True, "alignment": "center"},
            "entry": {"font_name": "simsun", "font_size_pt": 12, "bold": True},
            "page_number": {"font_name": "times_new_roman", "font_size_pt": 12, "bold": True},
        }, applies_to="docx",
    ),
    RuleSeed(
        "HEADING_TYPOGRAPHY", "typography", "各级标题排版", "各级标题使用宋体加粗，顶层标题和节标题居中。",
        {
            "section_keys": [
                "introduction", "body", "conclusion", "appendix", "references", "achievements",
                "acknowledgements", "resume",
            ],
            "font_name": "simsun", "bold": True, "font_size_tolerance_pt": 0.5,
            "roles": {
                "section_heading": {"font_size_pt": 18, "alignment": "center"},
                "chapter_heading": {"font_size_pt": 18, "alignment": "center"},
                "section_l2_heading": {"font_size_pt": 15, "alignment": "center"},
                "section_l3_heading": {"font_size_pt": 14},
                "section_l4_heading": {"font_size_pt": 12},
            },
        },
    ),
    RuleSeed(
        "BODY_TYPOGRAPHY", "typography", "正文排版", "正文、绪论、结论及附后各部分的正文采用小四号宋体。",
        {
            "section_keys": [
                "introduction", "body", "conclusion", "appendix", "references", "achievements",
                "acknowledgements", "resume",
            ],
            "font_name": "simsun", "font_size_pt": 12, "font_size_tolerance_pt": 0.5,
        },
    ),
    RuleSeed(
        "ABSTRACT_CONTENT_RULES", "abstract", "中文摘要与关键词", "中文摘要须达到规定字数且不得出现参考文献序号，关键词用全角分号分隔。",
        {
            "min_chinese_chars": 500, "forbidden_citation_pattern": r"\[\d+\]",
            "keyword_min_count": 3, "keyword_max_count": 5, "keyword_separator": "；",
            "keyword_max_total_chinese_chars": 15,
        },
    ),
    RuleSeed(
        "WORD_COUNT_REQUIREMENTS", "abstract", "正文与绪论字数", "检查正文总汉字数及绪论汉字数是否满足学位要求。",
        {"body_min_chinese_chars": 30000, "intro_min_chinese_chars": 3000, "intro_max_chinese_chars": 5000},
    ),
    RuleSeed(
        "FIGURE_TABLE_CAPTION", "figure_table", "图表编号与题注", "图和表采用阿拉伯数字连续或分章编号，图题下方居中，表题上方居中。",
        {
            "number_format": "decimal", "numbering_modes": ["continuous", "by_chapter"],
            "figure": {"position": "below", "alignment": "center"},
            "table": {"position": "above", "alignment": "center"},
        },
    ),
    RuleSeed(
        "REFERENCE_GBT7714", "reference", "参考文献编号与类型", "参考文献按顺序连续编号，采用 GB/T 7714-2015 类型标识，电子文献须含检索日期与网址。",
        {
            "number_pattern": r"^\[(\d+)\]", "numbering_start": 1, "require_consecutive_numbers": True,
            "type_codes": ["M", "C", "G", "N", "J", "D", "R", "S", "P", "DB", "CP", "EB", "A", "CM", "DS", "Z"],
            "carrier_codes": ["OL", "CD", "MT", "DK"],
            "electronic_require_url": True, "electronic_require_access_date": True,
        },
    ),
)

DOCTOR_PARAM_OVERRIDES = {
    "HEADER_FORMAT": {"even_pattern": r"福建师范大学.+博士学位论文"},
    "HEADER_DOUBLE_BORDER": {"width_pt": 1.5},
    "ABSTRACT_CONTENT_RULES": {"min_chinese_chars": 800},
    "WORD_COUNT_REQUIREMENTS": {
        "body_min_chinese_chars": 50000, "intro_min_chinese_chars": None, "intro_max_chinese_chars": 10000,
    },
}
FJNU_DOCTOR_RULES = tuple(
    replace(rule, params=rule.params | DOCTOR_PARAM_OVERRIDES[rule.code])
    if rule.code in DOCTOR_PARAM_OVERRIDES else rule
    for rule in FJNU_MASTER_RULES
)

FJNU_RULES_BY_CODE = {rule.code: rule for rule in FJNU_MASTER_RULES}
GENERAL_ACADEMIC_RULES = (
    FJNU_RULES_BY_CODE["PDF_NOT_IMAGE_ONLY"],
    FJNU_RULES_BY_CODE["PAGE_SIZE_A4"],
    replace(
        FJNU_RULES_BY_CODE["PAGE_MARGINS"],
        description="检查上、下、左、右基础页边距，默认各为 25.4mm。",
        params=FJNU_RULES_BY_CODE["PAGE_MARGINS"].params | {
            "top_mm": 25.4, "bottom_mm": 25.4, "left_mm": 25.4, "right_mm": 25.4,
        },
    ),
    RuleSeed(
        "REQUIRED_SECTIONS", "structure", "基础文档结构", "论文须包含题目、摘要、关键词、正文及参考文献。",
        {"required_sections": ["abstract_cn", "body", "references"], "required_elements": ["title", "keywords"]},
    ),
    RuleSeed(
        "BODY_TYPOGRAPHY", "typography", "正文字号一致性", "正文段落字号须一致。",
        {"section_keys": ["body"], "require_consistent_size": True, "font_size_tolerance_pt": 0.5},
    ),
    replace(
        FJNU_RULES_BY_CODE["REFERENCE_GBT7714"],
        description="参考文献须按顺序连续编号，并标明文献类型。",
        params=FJNU_RULES_BY_CODE["REFERENCE_GBT7714"].params | {
            "electronic_require_url": False, "electronic_require_access_date": False,
        },
    ),
)

BUILTIN_TEMPLATES = (
    TemplateSeed(
        "fjnu_master_2019", "福建师范大学硕士学位论文规范 2019",
        "福建师范大学研究生学位论文基本要求与书写格式（修订），师大研〔2019〕7号，硕士版。",
        "master", FJNU_MASTER_RULES, FJNU_MANUAL_CHECKLIST, is_default=True,
    ),
    TemplateSeed(
        "fjnu_doctor_2019", "福建师范大学博士学位论文规范 2019",
        "福建师范大学研究生学位论文基本要求与书写格式（修订），师大研〔2019〕7号，博士版。",
        "doctor", FJNU_DOCTOR_RULES, FJNU_MANUAL_CHECKLIST,
    ),
    TemplateSeed(
        "general_academic_v1", "通用中文学术论文基础规范",
        "检查非福师大中文学术论文的基本排版、结构与参考文献格式。",
        "general", GENERAL_ACADEMIC_RULES,
    ),
)
BUILTIN_VERSION = "1.0.0"


def _ensure_rule_set(session: Session, template: TemplateSeed) -> UUID:
    statement = insert(RuleSet).values(
        code=template.code,
        version=BUILTIN_VERSION,
        name=template.name,
        description=template.description,
        degree_level=template.degree_level,
        is_default=template.is_default,
        manual_checklist=list(template.manual_checklist),
    )
    rule_set_id = session.scalar(
        statement.on_conflict_do_nothing().returning(RuleSet.id)
    )
    if rule_set_id is None and template.is_default:
        # A database may already have a different default template.
        rule_set_id = session.scalar(
            statement.values(is_default=False)
            .on_conflict_do_nothing(index_elements=[RuleSet.code, RuleSet.version])
            .returning(RuleSet.id)
        )
    if rule_set_id is not None:
        return rule_set_id

    return session.execute(
        select(RuleSet.id).where(RuleSet.code == template.code, RuleSet.version == BUILTIN_VERSION)
    ).scalar_one()


def seed_builtin_templates(session: Session) -> None:
    for template in BUILTIN_TEMPLATES:
        rule_set_id = _ensure_rule_set(session, template)
        rule_items = [
            {
                "rule_set_id": rule_set_id,
                "rule_code": rule.code,
                "category": rule.category,
                "name": rule.name,
                "description": rule.description,
                "severity": "error",
                "applies_to": rule.applies_to,
                "params": rule.params,
                "sort_order": position,
            }
            for position, rule in enumerate(template.rules, start=1)
        ]
        session.execute(
            insert(RuleItem).values(rule_items).on_conflict_do_nothing(
                index_elements=[RuleItem.rule_set_id, RuleItem.rule_code]
            )
        )


def main() -> None:
    from app.db.session import SessionLocal

    with SessionLocal.begin() as session:
        seed_builtin_templates(session)


if __name__ == "__main__":
    main()
