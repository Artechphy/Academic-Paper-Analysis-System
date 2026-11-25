from dataclasses import asdict, replace
import re
from uuid import uuid4

import pytest

from app.db.models import RuleItem
from app.db.seed import BUILTIN_TEMPLATES, FJNU_MASTER_RULES, FJNU_RULES_BY_CODE, GENERAL_ACADEMIC_RULES
from app.engine.evaluator import evaluate
from app.engine.rules_catalog import RULES_CATALOG, Finding
from app.parsers.base import parse_document
from app.revisions.incremental import evaluate_incremental
from app.schemas.ir import DocumentIR, DocumentStatsIR, FigureTableIR, PageNumberIR, ParagraphIR, TextRunIR
from tests.fixtures_generator import (
    DOCX_RULE_FAILURES, PDF_RULE_FAILURES, make_fjnu_docx, make_fjnu_pdf, make_general_docx, make_scan,
)


def _summarize(result):
    return [(v.rule_code, v.expected, v.actual, v.location) for v in result.violations[:15]]


def test_rules_cover_seed_codes():
    assert len(FJNU_MASTER_RULES) == 21
    for template in BUILTIN_TEMPLATES:
        assert {rule.code for rule in template.rules if rule.severity == "warning"} == (
            {"LINE_SPACING_MIN", "PAGE_MARGINS"} & {rule.code for rule in template.rules}
        )
    assert set(RULES_CATALOG) == {rule.code for rule in FJNU_MASTER_RULES}
    assert set(DOCX_RULE_FAILURES) | set(PDF_RULE_FAILURES) == set(RULES_CATALOG)
    assert {rule.code for rule in GENERAL_ACADEMIC_RULES} <= set(RULES_CATALOG)


@pytest.mark.parametrize(("template_index", "generator", "options", "passed", "skipped"), [
    (0, make_fjnu_docx, {}, 20, 1),
    (0, make_fjnu_pdf, {}, 19, 2),
    (1, make_fjnu_docx, {"degree": "doctor"}, 20, 1),
    (2, make_general_docx, {}, 5, 1),
], ids=["master-docx", "master-pdf", "doctor-docx", "general-docx"])
def test_complete_compliant_document(tmp_path, template_index, generator, options, passed, skipped):
    snapshot = parse_document(generator(tmp_path, **options)).model_dump(mode="json")
    result = evaluate(snapshot, BUILTIN_TEMPLATES[template_index].rules)
    assert not result.violations, _summarize(result)
    assert (result.verdict, result.score) == ("pass", 100)
    assert (result.passed_rules_count, result.skipped_rules_count) == (passed, skipped)
    assert (result.error_count, result.warning_count) == (0, 0)


_SPACING_WARNINGS = {"PAGE_MARGINS", "LINE_SPACING_MIN"}


@pytest.mark.parametrize("rule_code", DOCX_RULE_FAILURES)
def test_one_docx_rule_failure(tmp_path, rule_code):
    ir = parse_document(make_fjnu_docx(tmp_path, violation=rule_code))
    result = evaluate(ir, FJNU_MASTER_RULES)
    assert {v.rule_code for v in result.violations} == {rule_code}, _summarize(result)
    expect_warning = rule_code in _SPACING_WARNINGS | {"HEADER_FORMAT"}
    assert result.verdict == ("pass" if expect_warning else "fail")
    assert result.error_count == (0 if expect_warning else len(result.violations))
    assert result.warning_count == (len(result.violations) if expect_warning else 0)
    assert result.score == 95
    for item in result.violations:
        assert re.search(r"[\u4e00-\u9fff]", item.expected)
        assert re.search(r"[\u4e00-\u9fff]", item.actual)
        assert re.search(r"[\u4e00-\u9fff]", item.message)
        assert item.location


@pytest.mark.parametrize("rule_code", PDF_RULE_FAILURES)
def test_one_pdf_rule_failure(tmp_path, rule_code):
    ir = parse_document(make_fjnu_pdf(tmp_path, violation=rule_code))
    result = evaluate(ir, FJNU_MASTER_RULES)
    assert {v.rule_code for v in result.violations} == {rule_code}, _summarize(result)
    expect_warning = rule_code in _SPACING_WARNINGS
    assert result.verdict == ("pass" if expect_warning else "fail")
    assert result.error_count == (0 if expect_warning else len(result.violations))
    assert result.warning_count == (len(result.violations) if expect_warning else 0)
    assert result.score == round(100 * 18 / 19, 2)


def test_severity_enabled_applicability_and_parameter_update(tmp_path):
    ir = parse_document(make_fjnu_docx(tmp_path, violation="PAGE_SIZE_A4"))
    seeds = {rule.code: rule for rule in FJNU_MASTER_RULES}
    config = RuleItem(
        id=uuid4(), rule_code=seeds["PAGE_SIZE_A4"].code, category="page", name="纸张尺寸",
        severity="warning", applies_to="both", enabled=True, params=seeds["PAGE_SIZE_A4"].params,
    )
    docx_only = asdict(seeds["PAGE_MARGINS"]) | {"enabled": False}
    result = evaluate(ir, [config, docx_only, seeds["PDF_NOT_IMAGE_ONLY"], seeds["FILE_NAME_PATTERN"]])
    assert (result.verdict, result.score, result.error_count, result.warning_count) == ("pass", 50, 0, 3)
    assert (result.passed_rules_count, result.skipped_rules_count) == (1, 2)
    assert {v.rule_item_id for v in result.violations} == {config.id}
    config.params = config.params | {"width_mm": 220}
    assert evaluate(ir, [config]).score == 100


def test_general_body_consistency_checks_minor_runs(tmp_path):
    ir = parse_document(make_general_docx(tmp_path))
    body = next(p for p in ir.paragraphs if p.section_key == "body" and p.role == "body_text")
    body.runs.append(body.runs[0].model_copy(update={"text": "异常字号", "font_size_pt": 15}))
    result = evaluate(ir, GENERAL_ACADEMIC_RULES)
    assert {v.rule_code for v in result.violations} == {"BODY_TYPOGRAPHY"}


def test_scanned_and_failed_documents_have_different_verdicts(tmp_path):
    scan = parse_document(make_scan(tmp_path))
    rule = next(rule for rule in FJNU_MASTER_RULES if rule.code == "PDF_NOT_IMAGE_ONLY")
    assert evaluate(scan, [rule]).verdict == "fail"
    assert evaluate(scan, [replace(rule, params={"allow_image_only": True})]).verdict == "pass"
    failure = evaluate(None, FJNU_MASTER_RULES, parse_status="failed")
    assert failure.verdict == "error" and failure.score == 0
    assert not failure.violations


def test_title_spacing_threshold_is_inclusive(tmp_path):
    ir = parse_document(make_fjnu_docx(tmp_path))
    title = next(p for p in ir.paragraphs if p.role == "chapter_heading")
    rule = next(rule for rule in FJNU_MASTER_RULES if rule.code == "LINE_SPACING_MIN")
    title.line_spacing_pt = 21.5
    assert evaluate(ir, [rule]).verdict == "pass"
    title.line_spacing_pt = 21.45
    violation, = evaluate(ir, [rule]).violations
    assert violation.location["paragraph_index"] == title.index


def test_combined_findings_keep_first_page_anchor_and_highest_severity(monkeypatch):
    code = "BODY_TYPOGRAPHY"
    first_box = [1, 2, 3, 4]
    monkeypatch.setitem(RULES_CATALOG, code, lambda doc, params: [
        Finding("字体", "黑体", "改字体", {"page": 4, "page_end": 5, "paragraph_index": 0,
                                         "paragraph_indices": [3], "highlight_excerpt": "错误字体"}, severity="warning"),
        Finding("字号", "10 pt", "改字号", {"page": 2, "paragraph_index": 0, "bbox": first_box,
                                          "paragraph_indices": [1], "highlight_excerpt": "错误字号"}),
        Finding("字体", "黑体", "改字体", {"page": 3, "paragraph_index": 0, "highlight_excerpt": "错误字体"}),
        Finding("全文", "问题甲", "检查", {}, severity="warning"),
        Finding("全文", "问题乙", "检查", {}, severity="warning"),
    ])
    document = DocumentIR(file_name="稿件.pdf", file_ext="pdf", page_count=5)
    result = evaluate(document, [FJNU_RULES_BY_CODE[code]])
    issue, *global_issues = result.violations
    assert (result.verdict, result.error_count, result.warning_count) == ("fail", 1, 2)
    assert len(global_issues) == 2
    assert (issue.expected, issue.actual, issue.message) == ("字体；字号", "黑体；10 pt", "改字体；改字号")
    assert issue.location == {
        "page": 2, "page_end": 5, "paragraph_index": 0, "bbox": first_box,
        "paragraph_indices": [0, 1, 3], "highlight_excerpt": "错误字体；错误字号",
    }


@pytest.mark.parametrize("file_ext", ["pdf", "docx"])
def test_page_number_locations_only_use_recognized_folio_text(file_ext):
    pdf = file_ext == "pdf"
    document = DocumentIR(
        file_name=f"稿件.{file_ext}", file_ext=file_ext, page_count=2,
        paragraphs=[
            ParagraphIR(index=0, page_no=1 if pdf else None, section_index=None if pdf else 0,
                        section_key="toc", text="目录首段"),
            ParagraphIR(index=1, page_no=2 if pdf else None, section_index=None if pdf else 1,
                        section_key="body", text="正文首段"),
        ],
    )
    rule = FJNU_RULES_BY_CODE["PAGE_NUMBER_STYLE"]
    missing_loc = {"section": "toc"} | ({"page": 1} if pdf else {"section_index": 0})
    for item in (None, PageNumberIR(page_no=1 if pdf else None, section_index=0, raw_text="I"),
                 PageNumberIR(page_no=1 if pdf else None, section_index=0, num_format="decimal", raw_text="",
                              alignment="left", position="header")):
        document.headers_footers.page_numbers = [item] if item else []
        finding = evaluate(document, [rule]).violations[0]
        assert finding.location == missing_loc
        if not pdf and item and item.num_format == "decimal":
            assert finding.actual == "阿拉伯数字，位于页眉，左对齐"
    document.headers_footers.page_numbers = [PageNumberIR(
        page_no=2 if pdf else None, section_index=None if pdf else 1, num_format="roman", raw_text="II",
    )]
    wrong = evaluate(document, [rule]).violations[-1]
    assert wrong.location["excerpt"] == "II" and wrong.location["section"] == "body"
    assert "paragraph_index" not in wrong.location


def test_length_and_missing_keywords_anchor_to_sections_only():
    document = DocumentIR(
        file_name="稿件.pdf", file_ext="pdf", page_count=4,
        paragraphs=[
            ParagraphIR(index=0, page_no=1, section_key="abstract_cn", role="section_heading", text="摘 要"),
            ParagraphIR(index=1, page_no=1, section_key="abstract_cn", role="body_text", text="已有研究[1]。"),
            ParagraphIR(index=2, page_no=2, section_key="introduction", text="绪论"),
            ParagraphIR(index=3, page_no=3, section_key="body", text="第一章"),
        ],
    )
    length = evaluate(document, [FJNU_RULES_BY_CODE["WORD_COUNT_REQUIREMENTS"]]).violations
    assert [item.location for item in length] == [{"page": 2, "section": "introduction"}, {"page": 3, "section": "body"}]
    length_issue, citation, keywords = evaluate(document, [FJNU_RULES_BY_CODE["ABSTRACT_CONTENT_RULES"]]).violations
    assert length_issue.location == keywords.location == {"page": 1, "section": "abstract_cn"}
    assert citation.location["excerpt"] == "已有研究[1]。" and citation.location["paragraph_index"] == 1
    document.paragraphs.append(ParagraphIR(
        index=4, page_no=1, section_key="abstract_cn", role="keywords_cn", text="关键词：格式,字体",
    ))
    keywords = evaluate(document, [FJNU_RULES_BY_CODE["ABSTRACT_CONTENT_RULES"]]).violations[-1]
    assert keywords.location["excerpt"] == "关键词：格式,字体" and keywords.location["paragraph_index"] == 4


def test_figure_findings_follow_page_order_and_describe_uncaptioned_objects():
    document = DocumentIR(file_name="稿件.pdf", file_ext="pdf", page_count=3, paragraphs=[
        ParagraphIR(index=1, page_no=1, text="图3 研究流程"),
        ParagraphIR(index=2, page_no=2, text=""),
        ParagraphIR(index=3, page_no=3, text=""),
    ], figures_tables=[
        FigureTableIR(kind="figure", paragraph_index=3, caption_text="", number_raw="", object_bbox=(0, 0, 60, 45)),
        FigureTableIR(kind="table", paragraph_index=2, caption_text="", number_raw="", inner_texts=["组别", "观察值"]),
        FigureTableIR(kind="figure", paragraph_index=1, caption_text="图3 研究流程", number_raw="3",
                      caption_style_issue="间距异常"),
    ])
    findings = evaluate(document, [FJNU_RULES_BY_CODE["FIGURE_TABLE_CAPTION"]]).violations
    assert [(v.location["page"], v.location["paragraph_index"]) for v in findings] == [(1, 1), (2, 2), (3, 3)]
    assert all(part in findings[0].actual for part in ("题注格式不规范", "图题位置", "实际题注编号"))
    assert [v.location["excerpt"] for v in findings] == ["图3 研究流程", "表格区域（含：组别、观察值）", "插图区域（约 60×45 pt）"]


def test_times_roman_reference_exception_requires_chinese_body_and_retains_size_check():
    reference = "[1] Smith. Typography practice[M]. 2020."
    document = DocumentIR(file_name="稿件.pdf", file_ext="pdf", page_count=2, paragraphs=[
        ParagraphIR(index=0, page_no=1, role="body_text", section_key="body", text="正文"),
        ParagraphIR(index=1, page_no=2, role="reference_entry", section_key="references", text=reference,
                    runs=[TextRunIR(text=reference, font_name="texgyretermesx", font_size_pt=12)]),
    ])
    rule = FJNU_RULES_BY_CODE["BODY_TYPOGRAPHY"]
    assert all(v.location["paragraph_index"] != 1 for v in evaluate(document, [rule]).violations)
    document.paragraphs[0].text = "English-only body"
    assert any(v.location["paragraph_index"] == 1 for v in evaluate(document, [rule]).violations)
    document.paragraphs[0].text = "正文"
    document.paragraphs[1].runs[0].font_size_pt = 9
    issue, = [v for v in evaluate(document, [rule]).violations if v.location["paragraph_index"] == 1]
    assert "字号" in issue.actual and "字体" not in issue.actual


@pytest.mark.parametrize("file_ext", ["docx", "pdf"])
@pytest.mark.parametrize("han_count", [0, 199, 200])
def test_western_body_font_exceptions_leave_size_and_other_fonts_checked(file_ext, han_count):
    def paragraph(index, text, font="simsun", size=12, role="body_text", section="body"):
        return ParagraphIR(index=index, text=text, role=role, section_key=section,
                           runs=[TextRunIR(text=text, font_name=font, font_size_pt=size)])

    document = DocumentIR(file_name=f"稿件.{file_ext}", file_ext=file_ext, page_count=1,
                          stats=DocumentStatsIR(body_chinese_chars=han_count), paragraphs=[
        paragraph(0, "汉" * han_count or "An English thesis"),
        paragraph(1, "SELECT name FROM items;", "CourierNewPSMT"),
        paragraph(2, "English terminology.", "times_new_roman"),
        paragraph(3, "SELECT 1;", "DejaVu Sans Mono Bold", 10),
        paragraph(4, "An unsuitable font.", "arial"),
        paragraph(5, "中英混合 SELECT", "Consolas"),
        paragraph(6, "[1] Smith. Methods[M]. 2020.", "Fira Code Medium", role="reference_entry", section="references"),
    ])
    rule = FJNU_RULES_BY_CODE["BODY_TYPOGRAPHY"]
    issues = {issue.location["paragraph_index"]: issue for issue in evaluate(document, [rule]).violations}
    if han_count >= 200:
        assert set(issues) == {3, 4, 5}
        assert "字号" in issues[3].actual and "字体" not in issues[3].actual
    else:
        assert set(issues) == {1, 2, 3, 4, 5, 6}
        assert "字号" in issues[3].actual and "字体" in issues[3].actual


def test_incremental_body_typography_rechecks_other_paragraphs_at_language_threshold():
    def paragraph(index, text, font):
        return ParagraphIR(index=index, text=text, role="body_text", section_key="body",
                           runs=[TextRunIR(text=text, font_name=font, font_size_pt=12)])

    previous = DocumentIR(file_name="稿件.docx", file_ext="docx", page_count=1,
                          paragraphs=[paragraph(0, "汉" * 199, "simsun"), paragraph(1, "SELECT 1;", "Consolas")],
                          stats=DocumentStatsIR(body_chinese_chars=199))
    current = previous.model_copy(update={
        "paragraphs": [paragraph(0, "汉" * 200, "simsun"), previous.paragraphs[1]],
        "stats": DocumentStatsIR(body_chinese_chars=200),
    })
    rules = [FJNU_RULES_BY_CODE["BODY_TYPOGRAPHY"]]
    issues = evaluate(previous, rules).violations
    assert [issue.location["paragraph_index"] for issue in issues] == [1]
    assert evaluate_incremental(current, previous, issues, rules, 0).violations == evaluate(current, rules).violations == []
