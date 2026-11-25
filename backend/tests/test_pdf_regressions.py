"""PDF layout regressions exercised through the parser and the seeded rules."""
from contextlib import closing

import pymupdf
import pytest

from app.db.seed import FJNU_RULES_BY_CODE
from app.engine.evaluator import evaluate
from app.engine.utils import heading_level, normalize_font_name
from app.parsers.base import cover_elements
from app.parsers.pdf_parser import parse_pdf
from tests.fixtures_generator import CHAPTER, EXAMPLE, _PdfSample, _png


EVEN_HEADER = "福建师范大学教育学硕士学位论文"
FULL_LINE = (EXAMPLE * 2)[:36]


def _parse(sample):
    return parse_pdf(sample.pdf.tobytes(), "20260001_测试.pdf")


def _violations(document, *codes):
    return evaluate(document, [FJNU_RULES_BY_CODE[code] for code in codes]).violations


def test_pdf_baseline_tolerance_still_flags_tight_spacing():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page()
        sample.heading(CHAPTER, 88)
        for baseline in (112, 133.96, 177, 197.5):
            sample.text(FULL_LINE, baseline)
        document = _parse(sample)

    finding, = _violations(document, "LINE_SPACING_MIN")
    assert "20.50 pt" in finding.actual
    assert finding.severity == "warning"
    measured = [p for p in document.paragraphs if p.line_spacing_pt is not None]
    assert [p.line_spacing_pt for p in measured] == pytest.approx([21.96, 20.5], abs=.01)
    assert [p.line_count for p in measured] == [2, 2]


def test_pdf_line_spacing_records_minimum_within_one_paragraph():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page()
        sample.heading(CHAPTER, 88)
        for baseline in (112, 134, 154, 176):
            sample.text(FULL_LINE, baseline)
        document = _parse(sample)

    paragraph, = [p for p in document.paragraphs if p.line_spacings_pt]
    assert paragraph.line_spacing_pt == pytest.approx(22)
    assert paragraph.line_spacings_pt == pytest.approx([22, 20, 22])
    # Script/formula baselines are too close to measure line spacing.
    paragraph.line_spacing_samples.insert(1, paragraph.line_spacing_samples[0].model_copy(update={"spacing_pt": 3}))
    finding, = _violations(document, "LINE_SPACING_MIN")
    assert finding.location["paragraph_index"] == paragraph.index
    assert "最小基线间距约 20.00 pt" in finding.actual
    paragraph.line_spacing_samples.clear()
    paragraph.line_spacings_pt.insert(1, 3)
    legacy, = _violations(document, "LINE_SPACING_MIN")
    assert legacy.actual == finding.actual


@pytest.mark.parametrize(("name", "family"), [
    ("NERFFC+HYShuSongErKW", "simsun"),
    ("宋体".encode().decode("latin-1"), "simsun"),
    ("宋体".encode("gbk").decode("latin-1"), "simsun"),
    ("å_ä1_2", "simsun"),
    ("STSongti-TC-Regular", "simsun"),
    ("LVLPJS+HYZhongHeiKW", "simhei"),
    ("黑体".encode().decode("latin-1"), "simhei"),
    ("TimesNewRomanPS-BoldItal", "times_new_roman"),
    ("TeXGyreTermesX-Regular-Identity-H", "times_new_roman"),
    ("TeXGyreTermes-Italic", "times_new_roman"),
    ("NimbusRomNo9L-Medium-Identity-V", "times_new_roman"),
    ("HYKaiTiKW", "hykaitikw"),
])
def test_cnki_font_names(name, family):
    assert normalize_font_name(name) == family


def test_pdf_descriptor_font_and_wrapped_mixed_script_typography():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page()
        sample.heading(CHAPTER)
        sample.text(FULL_LINE[:31], 130)
        sample.text("and Latin words", 130, font="tiro", left=sample.left + 31 * 12)
        sample.text("English words on a continuation", 152, font="tiro")
        sample.text(FULL_LINE, 195, font="china-ts")
        sample.text(FULL_LINE, 217, font="china-ts")
        sample.text("Standalone English paragraph", 260, font="tiro")
        xref = next(font[0] for font in sample.page.get_fonts() if font[4] == "china-s")
        descendant = int(sample.pdf.xref_get_key(xref, "DescendantFonts")[1].strip("[]").split()[0])
        descriptor = int(sample.pdf.xref_get_key(descendant, "FontDescriptor")[1].split()[0])
        for obj, key in ((xref, "BaseFont"), (descendant, "BaseFont"), (descriptor, "FontName")):
            sample.pdf.xref_set_key(obj, key, "/OpaqueCJK")
        sample.pdf.xref_set_key(descriptor, "FontFamily", "(HYShuSongErKW)")
        document = _parse(sample)

    first = next(p for p in document.paragraphs if p.text.startswith(FULL_LINE[:31]) and "Latin" in p.text)
    assert first.font_name == "simsun"
    assert {run.font_name for run in first.runs} == {"simsun", "times_new_roman"}
    assert "English words on a continuation" in first.text and first.line_count == 2
    wrong_chinese, wrong_english = _violations(document, "BODY_TYPOGRAPHY")
    assert wrong_chinese.actual == "字体为黑体"
    wrong = document.paragraphs[wrong_chinese.location["paragraph_index"]]
    assert wrong.line_count == 2
    assert wrong_english.location["excerpt"] == "Standalone English paragraph"


def test_pdf_margins_use_regular_body_pages_and_retain_real_defect():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1, chapter=True)
        sample.heading(CHAPTER, 220)
        for index in range(23):
            sample.text(FULL_LINE, 255 + 22 * index)
        for number in (2, 3):
            sample.new_page(number, chapter=True)
            for index in range(31):
                sample.text(FULL_LINE, 98 + 22 * index, left=sample.left + (24 if number == 3 else 0))
        sample.new_page(4, chapter=True)
        for index in range(4):
            sample.text(FULL_LINE, 175 + 22 * index)
        document = _parse(sample)

    assert document.page_setups[0].top_margin_mm is None
    assert document.page_setups[1].top_margin_mm == pytest.approx(30, abs=1)
    assert document.page_setups[3].top_margin_mm is None
    finding, = _violations(document, "PAGE_MARGINS")
    assert finding.location["page"] == 3
    assert "左边距" in finding.actual


def test_pdf_decorations_do_not_create_figures_but_real_vector_art_does():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1, chapter=True)
        sample.heading(CHAPTER)
        page = sample.page
        page.draw_rect(pymupdf.Rect(28, 30, 567, 810), color=(0, 0, 0))
        page.draw_line((80, 55), (510, 55))
        page.draw_line((80, 57), (510, 57))
        for index in range(8):
            y = 130 + index * 22
            page.draw_rect(pymupdf.Rect(82, y, 515, y + 22), color=None, fill=(1, 1, 1))
        page.draw_rect(pymupdf.Rect(95, 320, 112, 337), fill=(0, 0, 0))
        page.draw_rect(pymupdf.Rect(205, 382, 379, 491), color=(0, 0, 1))
        page.draw_line((215, 475), (360, 403), color=(0, 0, 1))
        document = _parse(sample)

    figure, = document.figures_tables
    assert figure.kind == "figure" and not figure.caption_text
    finding, = _violations(document, "FIGURE_TABLE_CAPTION")
    assert finding.location["page"] == 1


def test_pdf_horizontal_table_rules_and_translated_caption():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        sample.text("表1 研究结果", 136, center=True)
        sample.text("Table 1 Study results", 155, center=True, font="tiro")
        for y in (165, 195, 225):
            sample.page.draw_line((160, y), (435, y))
        for y in (184, 214):
            sample.text("指标", y, left=180)
            sample.text("结果", y, left=340)
        sample.text("Table 1 shows the measured results.", 255, font="tiro")
        document = _parse(sample)

    table, = document.figures_tables
    assert (table.kind, table.relative_position, table.number_raw) == ("table", "above", "1")
    assert all(p.in_table for p in document.paragraphs if p.text in {"指标", "结果"})
    assert not _violations(document, "FIGURE_TABLE_CAPTION")


def test_three_line_table_keeps_staggered_columns_and_math_cells():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        sample.text("表1 指标说明", 132, center=True)
        sample.text("Table 1 Metric descriptions", 153, center=True, font="tiro")
        for y in (168, 220, 285):
            sample.page.draw_line((90, y), (512, y))
        sample.text("A1", 199, font="tiro", left=105)
        sample.text("右列跨越多行正文但仍属于一个表格单元", 182.5, left=156)
        sample.text("x + y = 2", 204, 10, font="cour", left=156)
        sample.text("B2", 251, font="tiro", left=105)
        sample.text("右列第二组说明使用另一条不齐的基线", 268, left=156)
        ref = next(font[0] for font in sample.page.get_fonts() if font[4] == "cour")
        sample.pdf.xref_set_key(ref, "BaseFont", "/CMMI12")
        document = _parse(sample)

    table, = document.figures_tables
    assert table.kind == "table" and table.relative_position == "above"
    assert {"A1", "B2", "x + y = 2"} <= set(table.inner_texts)
    assert not _violations(document, "FIGURE_TABLE_CAPTION", "BODY_TYPOGRAPHY")


def test_three_line_table_views_cells_when_caption_is_below_bottom_rule():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        for y in (166, 195, 257):
            sample.page.draw_line((100, y), (495, y))
        for y, values in (
            (184, ("试验组", "平均值")), (215, ("对照组", "十七")), (242, ("实验组", "二十")),
        ):
            sample.text(values[0], y, 10.5, left=120)
            sample.text(values[1], y + 1, 10.5, left=352)
        sample.text("表1 比较统计", 282, center=True)
        sample.text("Table 1 Comparison statistics", 305, center=True, font="tiro")
        document = _parse(sample)

    table, = document.figures_tables
    assert table.kind == "table" and table.relative_position == "below"
    assert table.object_bbox == (100, 166, 495, 257)
    assert len(table.inner_texts) == 6 and "对照组" in table.inner_texts
    finding, = _violations(document, "FIGURE_TABLE_CAPTION")
    assert finding.actual == "表题下方，居中"
    assert not _violations(document, "BODY_TYPOGRAPHY")


def test_aligned_ruled_tables_on_one_page_keep_their_own_caption_orientation():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        sample.text("表1 样本数据", 145, center=True)
        for top, values in ((162, ("样本分组", "观察数值")), (330, ("对照分组", "比较数值"))):
            for offset in (0, 30, 83):
                sample.page.draw_line((100, top + offset), (495, top + offset))
            for offset in (18, 53):
                sample.text(values[0], top + offset, 10.5, left=120)
                sample.text(values[1], top + offset, 10.5, left=352)
        sample.text("表2 对照数据", 439, center=True)
        sample.text("表1 结果显示，样本具有可比性。", 498)
        document = _parse(sample)

    assert [(f.number_raw, f.relative_position, f.object_bbox[1:4:2]) for f in document.figures_tables] == [
        ("1", "above", (162, 245)), ("2", "below", (330, 413)),
    ]
    assert any(p.text.startswith("表1 结果显示") and p.role == "body_text" for p in document.paragraphs)
    finding, = _violations(document, "FIGURE_TABLE_CAPTION")
    assert finding.actual == "表题下方，居中"


@pytest.mark.parametrize("figure_evidence", [None, "curve", "caption"])
def test_pdf_wide_questionnaire_with_single_digit_cells_respects_figure_evidence(figure_evidence):
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        columns = (100, 302, 340, 378, 416, 454, 492)
        for x in columns:
            sample.page.draw_line((x, 160), (x, 410))
        for row in range(11):
            y = 160 + row * 25
            sample.page.draw_line((100, y), (492, y))
        for row in range(10):
            y = 177 + row * 25
            sample.text(f"题项 {row + 1} 使用情况记录", y, 10.5, left=112)
            for index, x in enumerate(columns[1:-1], 1):
                sample.text(str(index), y, 10.5, left=x + 12, font="tiro")
        if figure_evidence == "curve":
            sample.page.draw_bezier((155, 225), (179, 274), (217, 181), (262, 235))
        elif figure_evidence == "caption":
            sample.text("图1 多列结构示意", 433, center=True)
        document = _parse(sample)

    unit, = document.figures_tables
    if figure_evidence:
        assert unit.kind == "figure"
        return
    assert unit.kind == "table"
    assert len(unit.inner_texts) == 60
    cells = [p for p in document.paragraphs if p.in_table]
    assert len(cells) == 60 and any(p.text == "5" for p in cells)
    assert not _violations(document, "BODY_TYPOGRAPHY")


def test_pdf_references_keep_first_location_and_merge_across_pages():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading("参考文献")
        sample.text("[1] " + FULL_LINE, 742)
        sample.new_page(2)
        sample.text("续行[EB/OL]. [2025-05-18]. https://example.org/paper", 98, left=sample.left + 18)
        sample.text("[2] 第二条文献确实缺少类型代码。", 120)
        document = _parse(sample)

    first, second = document.references
    assert (first.index_num, first.type_code, first.carrier_code) == (1, "EB", "OL")
    assert first.has_access_date and first.has_url
    assert document.paragraphs[first.paragraph_index].page_no == 1
    assert second.index_num == 2 and second.type_code is None
    finding, = _violations(document, "REFERENCE_GBT7714")
    assert finding.location["paragraph_index"] == second.paragraph_index


def test_pdf_section_evidence_and_header_parity_with_front_matter():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page()
        sample.text("福建师范大学", 120)
        sample.new_page("I")
        sample.text("摘要", 42, 10.45, center=True)
        sample.heading("摘要")
        sample.text("中文摘要正文。", 130)
        sample.text("关键词：格式；文档；版式", 152)
        sample.new_page("II")
        sample.heading("Abstract", font="tibo")
        sample.text("This is an abstract.", 130, font="tiro")
        sample.new_page("III")
        sample.text("中文文摘", 42, 10.45, center=True)
        sample.heading("中文文摘")
        sample.text("额外的文摘。", 130)
        sample.new_page("IV")
        sample.heading("目录")
        sample.text("绪论 ........ 1", 130)
        sample.text("第一章 一个较长的目录标题", 152, 15, bold=True)
        sample.text("的续行 ........ 2", 174)
        sample.new_page(1)
        sample.heading("绪论")
        sample.text(FULL_LINE, 130)
        sample.new_page(2)
        sample.heading(CHAPTER)
        sample.text(EVEN_HEADER, 42, 10.45, center=True)
        sample.text("参考文献", 132, 10.45)
        sample.text(FULL_LINE, 154)
        sample.new_page()
        sample.text(CHAPTER, 42, 10.45, center=True)
        sample.text(FULL_LINE, 100)
        sample.new_page()
        sample.text("真实错误页眉", 42, 10.45, center=True)
        sample.text(FULL_LINE, 100)
        document = _parse(sample)

    assert [(s.key, s.page_start) for s in document.sections] == [
        ("cover", 1), ("abstract_cn", 2), ("abstract_en", 3), ("cnki_abstract", 4), ("toc", 5),
        ("introduction", 6), ("body", 7),
    ]
    assert document.stats.abstract_cn_chars == len("中文摘要正文")
    assert any(header.page_no == 8 for header in document.headers_footers.odd_headers)
    finding, = _violations(document, "SECTION_ORDER", "HEADER_FORMAT")
    assert finding.rule_code == "HEADER_FORMAT" and finding.location["page"] == 9
    required = _violations(document, "REQUIRED_SECTIONS")
    assert {"declaration", "defense_signature"} <= {v.location["section"] for v in required}


def test_pdf_keeps_real_order_keyword_and_length_findings():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page()
        sample.heading("Abstract", font="tibo")
        sample.text("The abstract appears before the Chinese abstract.", 130, font="tiro")
        sample.new_page()
        sample.heading("摘要")
        sample.text("本研究提出新的方法。", 130)
        sample.text("关键词：版式分析；格式规范；文档" + FULL_LINE[:20], 152)
        sample.text("最后一组词", 174)
        document = parse_pdf(sample.pdf.tobytes(), "下载论文.pdf")

    findings = _violations(document, "FILE_NAME_PATTERN", "ABSTRACT_CONTENT_RULES", "SECTION_ORDER",
                           "WORD_COUNT_REQUIREMENTS")
    assert {finding.rule_code for finding in findings} == {
        "FILE_NAME_PATTERN", "SECTION_ORDER", "ABSTRACT_CONTENT_RULES", "WORD_COUNT_REQUIREMENTS",
    }
    assert any("最后一组词" in finding.actual for finding in findings if finding.rule_code == "ABSTRACT_CONTENT_RULES")
    assert document.stats.abstract_cn_chars == len("本研究提出新的方法")


def test_cover_rows_split_columns_and_join_multiline_titles():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page()
        sample.text("学 校 代 码：", 110, 14, left=82)
        sample.text("10394", 108, 10, font="tiro", left=208)
        sample.page.draw_line((197, 114), (250, 114))
        sample.text("图 书 分 类 号：", 110, 14, left=337)
        sample.text("G633.6", 103, 10, font="tiro", left=474)
        sample.page.draw_line((460, 114), (522, 114))
        sample.text("学", 150, 14, left=82)
        sample.text("号：", 149, 14, left=142)
        sample.text("QSX20260001", 148, 12, font="tiro", left=200)
        sample.text("专业学位硕士学位论文", 214, 30, center=True)
        sample.text("跨行论文标题的上半部分仍保留全部汉字", 261, 22, center=True, font="china-ts")
        sample.text("以及下半部分同样参与字数校验", 292, 22, center=True, font="china-ts")
        sample.text("An English Title Across", 323, 18, center=True, font="tiro")
        sample.text("Two Separate Lines", 349, 18, center=True, font="tiro")
        sample.text("学 科 专 业：________", 418)
        sample.text("论 文 作 者：马同学", 446)
        document = _parse(sample)

    elements = cover_elements(document.paragraphs)
    assert {key: elements[key][0] for key in ("school_code", "library_classification", "student_id", "author_name")} == {
        "school_code": "10394", "library_classification": "G633.6", "student_id": "QSX20260001", "author_name": "马同学",
    }
    code, classification = [elements[key][1] for key in ("school_code", "library_classification")]
    assert code.has_underline and classification.has_underline
    assert code.unit_kind == classification.unit_kind == "underline_row"
    assert code.bbox[2] < classification.bbox[0]
    assert elements["title_en"][0] == "An English Title Across Two Separate Lines"
    title, unit = elements["title_cn"]
    assert title.endswith("以及下半部分同样参与字数校验") and unit.line_count == 2
    findings = _violations(document, "COVER_ELEMENTS")
    assert any("中文题目有" in finding.actual for finding in findings)
    assert any(finding.actual == "下划线槽位未填" and "专业" in finding.message for finding in findings)


def test_scan_unit_and_signature_slot_review_are_warnings():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page()
        sample.text("论文题名内容", 170, 22, center=True)
        sample.new_page()
        sample.page.insert_image(sample.page.rect, stream=_png(), keep_proportion=False)
        sample.new_page()
        sample.heading("学位论文答辩委员会签名")
        sample.text("主席签名：____________", 190)
        sample.page.insert_image((150, 161, 187, 187), stream=_png(), keep_proportion=False)
        sample.text("委员签名：____________", 251)
        sample.new_page("I")
        sample.heading("摘要")
        sample.text("中文摘要正文", 133)
        document = _parse(sample)

    scan, = [unit for unit in document.paragraphs if unit.unit_kind == "scanned_page"]
    assert scan.page_no == 2 and scan.has_image
    assert any(s.key == "defense_signature" and s.page_start == 3 for s in document.sections)
    signed, blank = [p for p in document.paragraphs if p.field_label == "signature"]
    assert signed.has_signature_image and not blank.has_signature_image
    assert all(p.object_kind != "figure" for p in document.paragraphs if p.page_no == 3)
    findings = _violations(document, "COVER_ELEMENTS", "REQUIRED_SECTIONS")
    declaration, = [f for f in findings if f.location.get("section") == "declaration"]
    assert declaration.severity == "warning" and declaration.location["page"] == 2
    review, = [f for f in findings if f.actual == "签名下划线为空"]
    assert review.severity == "warning" and review.location["paragraph_index"] == blank.index
    assert any(f.severity == "error" and f.location.get("section") == "references" for f in findings)


def test_image_formula_subfigures_inner_text_and_wrapped_caption():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        page = sample.page
        page.insert_image((215, 157, 342, 181), stream=_png(), keep_proportion=False)
        sample.text("（2-1）", 177, right=True)
        page.insert_image((130, 235, 276, 355), stream=_png(), keep_proportion=False)
        page.insert_image((292, 238, 439, 355), stream=_png(), keep_proportion=False)
        sample.text("左侧图中文字", 269, 12, left=143)
        sample.text("右侧图中文字", 270, 12, left=303)
        sample.text("（图1：处理流程与两个阶段", 376, center=True)
        sample.text("的输出情况）", 396, center=True)
        document = _parse(sample)

    formula, figure = document.figures_tables
    assert formula.kind == "formula" and formula.number_raw == "2-1"
    assert document.paragraphs[formula.paragraph_index].unit_kind == "formula"
    assert figure.kind == "figure" and figure.subfigure_count == 2 and figure.relative_position == "below"
    assert figure.inner_texts == ["左侧图中文字", "右侧图中文字"]
    assert not any("图中文字" in p.text for p in document.paragraphs if p.role == "body_text")
    assert figure.object_bbox[:2] == (130, 235)
    assert document.paragraphs[figure.paragraph_index].line_count == 2
    assert figure.caption_text.endswith("的输出情况）")
    findings = _violations(document, "FIGURE_TABLE_CAPTION")
    style, = [f for f in findings if "题注格式不规范" in f.actual]
    assert "外括号" in style.actual and "多余冒号" in style.actual and style.severity == "error"


def _grid(sample, y):
    for x in (155, 286, 450):
        sample.page.draw_line((x, y), (x, y + 100))
    for dy in (0, 50, 100):
        sample.page.draw_line((155, y + dy), (450, y + dy))
    for dy in (26, 76):
        sample.text("左栏", y + dy, left=165)
        sample.text("右栏", y + dy, left=303)


def test_pdf_table_continuation_recognized_by_geometry_and_caption():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        sample.text("表1 汇总结果", 622, center=True)
        _grid(sample, 639)
        sample.new_page(2)
        _grid(sample, 102)
        sample.new_page(3)
        sample.text("Table1 (Continued) Results", 106, font="tiro", center=True)
        _grid(sample, 128)
        document = _parse(sample)

    a, b, c = document.figures_tables
    assert not a.is_continuation and a.object_bbox and a.inner_texts
    assert b.is_continuation and not b.caption_text and b.object_bbox
    assert c.is_continuation and "缺少空格" in c.caption_style_issue
    findings = _violations(document, "FIGURE_TABLE_CAPTION")
    finding, = findings
    assert finding.location["page"] == 3 and "题注格式不规范" in finding.actual


def test_single_row_table_continues_across_pages_with_different_columns():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        sample.text("表1 汇总结果", 525, center=True)
        _grid(sample, 543)
        sample.new_page(2)
        for x in (155, 245, 340, 450):
            sample.page.draw_line((x, 125), (x, 168))
        for y in (125, 168):
            sample.page.draw_line((155, y), (450, y))
        for x, text in ((168, "左栏"), (256, "中栏"), (354, "右栏")):
            sample.text(text, 151, left=x)
        document = _parse(sample)

    first, continued = document.figures_tables
    assert first.kind == continued.kind == "table"
    assert continued.is_continuation and continued.object_page_no == 2
    assert continued.object_bbox == (155, 125, 450, 168)
    assert not _violations(document, "FIGURE_TABLE_CAPTION")


@pytest.mark.parametrize("prose_between", [False, True])
def test_vector_grid_is_a_figure_and_its_separated_blocks_and_annotations_are_grouped(prose_between):
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        for x in (170, 245, 325):
            sample.page.draw_line((x, 140), (x, 210))
        for y in (140, 178, 210):
            sample.page.draw_line((170, y), (325, y))
        sample.page.draw_line((183, 150), (306, 203))
        for x, value in ((194, "A"), (263, "B")):
            sample.text(value, 165, 9, font="tiro", left=x)
        sample.page.draw_rect((174, 261, 320, 318), color=(0, 0, 0))
        sample.text("流程标签", 245, 9, left=205)
        if prose_between:
            sample.text(FULL_LINE, 230)
        sample.text("图1 两阶段流程", 346, center=True)
        document = _parse(sample)

    if prose_between:
        assert [item.kind for item in document.figures_tables] == ["figure", "figure"]
        assert all(item.subfigure_count == 1 for item in document.figures_tables)
        assert any(p.text == FULL_LINE and p.role == "body_text" for p in document.paragraphs)
        return
    figure, = document.figures_tables
    assert figure.kind == "figure" and figure.subfigure_count == 2 and figure.relative_position == "below"
    assert {"A", "B", "流程标签"} <= set(figure.inner_texts)
    assert not any(p.text == "流程标签" for p in document.paragraphs)


def test_pdf_sliced_figure_cross_page_caption_and_inline_formula():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        sample.text("此处公式嵌在正文", 177, left=87)
        sample.page.insert_image((188, 154, 271, 181), stream=_png(), keep_proportion=False)
        sample.page.insert_image((140, 528, 452, 620), stream=_png(), keep_proportion=False)
        sample.page.insert_image((140, 623, 452, 708), stream=_png(), keep_proportion=False)
        sample.text("图内标注", 678, 9, left=215)
        sample.new_page(2)
        sample.text("图1 上一页的插图", 131, center=True)
        document = _parse(sample)

    formula, figure = document.figures_tables
    assert formula.kind == "formula" and formula.object_bbox == (188, 154, 271, 181)
    assert figure.kind == "figure" and figure.relative_position == "below" and figure.object_page_no == 1
    assert document.paragraphs[figure.paragraph_index].page_no == 2
    assert figure.object_bbox == (140, 528, 452, 708) and figure.subfigure_count == 2
    assert "图内标注" in figure.inner_texts


def test_populated_grid_inside_connected_vector_canvas_is_not_a_table():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        sample.page.draw_rect((100, 140, 500, 400), color=(0, 0, 0))
        _grid(sample, 205)
        sample.page.draw_line((100, 155), (155, 205))
        document = _parse(sample)

    figure, = document.figures_tables
    assert figure.kind == "figure" and figure.object_bbox == (100, 140, 500, 400)
    assert {"左栏", "右栏"} <= set(figure.inner_texts)


def test_pdf_parallel_captions_sort_left_to_right_despite_baseline_jitter():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        sample.page.insert_image((84, 160, 276, 276), stream=_png(), keep_proportion=False)
        sample.page.insert_image((319, 160, 510, 276), stream=_png(), keep_proportion=False)
        sample.text("图1 左侧图", 302, left=131)
        sample.text("图2 右侧图", 301, left=378)
        document = _parse(sample)

    first, second = document.figures_tables
    assert [item.number_raw for item in (first, second)] == ["1", "2"]
    assert first.object_bbox[0] == 84 and second.object_bbox[0] == 319


@pytest.mark.parametrize(("lines", "translation", "font", "translation_font", "joiner"), [
    (("图1 多行图题的第一行", "图题第二行", "图题第三行", "图题余下部分"),
     "Figure 1 A caption over four lines", "china-s", "tiro", ""),
    (("Figure 1 A caption", "with a second line", "and a third line"),
     "图1 三行英文题注", "tiro", "china-s", " "),
])
def test_pdf_small_caption_wraps_and_bilingual_caption_is_deduplicated(lines, translation, font, translation_font, joiner):
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        sample.page.insert_image((155, 180, 440, 310), stream=_png(), keep_proportion=False)
        for i, line in enumerate(lines):
            sample.text(line, 335 + i * 22, 10.5, center=True, font=font)
        sample.text(translation, 335 + len(lines) * 22, 10.5, center=True, font=translation_font)
        document = _parse(sample)

    figure, = document.figures_tables
    assert figure.caption_text == joiner.join(lines) and figure.relative_position == "below"
    assert document.paragraphs[figure.paragraph_index].line_count == len(lines)


def test_pdf_centered_chapter_title_wraps_at_narrower_heading_width():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        line = "第一章 复杂模型的设计与分析方案"
        continuation, ending = "与相关应用过程", "及其验证方法"
        sample.heading(line, 124)
        sample.text(continuation, 155, 18, center=True)
        sample.heading(ending, 186)
        sample.text(FULL_LINE, 245)
        sample.text(FULL_LINE, 267)
        document = _parse(sample)

    heading, = [p for p in document.paragraphs if p.role == "chapter_heading"]
    assert heading.text == line + continuation + ending and heading.line_count == 3
    assert [run.bold for run in heading.runs] == [True, False, True]


def test_pdf_nested_vector_candidates_do_not_add_figures_or_subfigure_counts(monkeypatch):
    sample = _PdfSample(None)
    outer = (155, 165, 465, 335)
    # Some producers expose the enclosing cluster and two internal arrow clusters separately.
    monkeypatch.setattr(pymupdf.Page, "cluster_drawings", lambda self, **_: [
        (200, 195, 242, 234), outer, (320, 257, 371, 302),
    ])
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        sample.page.draw_rect(outer)
        sample.text("流程框内文字", 230, 9, left=220)
        sample.text("图1 流程总图", 358, center=True)
        document = _parse(sample)

    figure, = document.figures_tables
    assert figure.object_bbox == outer and figure.subfigure_count == 1
    assert figure.inner_texts == ["流程框内文字"]
    assert not _violations(document, "FIGURE_TABLE_CAPTION")


@pytest.mark.parametrize("has_prose", [False, True])
def test_pdf_figure_side_labels_keep_full_sentences_and_respect_nearby_prose(has_prose):
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        sample.page.draw_rect((192, 180, 482, 351))
        sample.text("聚合阶段：", 152, 9, left=103)
        sample.text("准备阶段", 226, 9, left=103)
        sample.text("这是一句完整的话。", 269, 9, left=90)
        if has_prose:
            sample.text(FULL_LINE, 164)
        sample.text("图1 流程总图", 377, center=True)
        document = _parse(sample)

    figure, = document.figures_tables
    assert ("聚合阶段：" in figure.inner_texts) is not has_prose
    assert ("准备阶段" in figure.inner_texts) is not has_prose
    assert any(p.text == "这是一句完整的话。" and p.role == "body_text" for p in document.paragraphs)


@pytest.mark.parametrize("horizontal_offset", [9, 23])
def test_pdf_bottom_figure_continues_as_the_captioned_top_figure_on_next_page(horizontal_offset):
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        sample.page.insert_image((140, 589, 454, 723), stream=_png(), keep_proportion=False)
        sample.new_page(2)
        sample.page.insert_image((140 + horizontal_offset, 110, 454 + horizontal_offset, 267),
                                 stream=_png(), keep_proportion=False)
        sample.text("图1 跨页图示", 292, center=True)
        document = _parse(sample)

    bottom, top = document.figures_tables
    continued = horizontal_offset <= 12
    assert bottom.object_page_no == 1 and bottom.is_continuation is continued
    assert top.object_page_no == 2 and top.relative_position == "below"
    assert [v.location["page"] for v in _violations(document, "FIGURE_TABLE_CAPTION")] == ([] if continued else [1])


@pytest.mark.parametrize(("title", "content"), [
    ("算法 1 样本处理", ("输入：样本序列", "输出：计算结果")),
    ("Algorithm 2 Sample processing", ("1: prepare the inputs", "2: return the results")),
])
def test_pdf_ruled_algorithm_is_not_body_text_or_an_uncaptioned_object(title, content):
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        shape = sample.page.new_shape()
        for y in (175, 216, 301):
            shape.draw_line((100, y), (495, y))
        for x in (100, 230, 495):
            shape.draw_line((x, 175), (x, 301))
        shape.finish()
        shape.commit()
        font = "tiro" if title.startswith("Algorithm") else "china-s"
        sample.text(title, 193, 10, font=font, left=112)
        preamble = "Input: data" if font == "tiro" else "输入说明：样本"
        sample.text(preamble, 209, 9, font=font, left=112)
        for y, line in zip((232, 268), content, strict=True):
            sample.text(line, y, 9, font=font, left=112)
            sample.text("阶段说明", y, 9, left=258)
        sample.text("正常正文保留原始段落。", 332)
        document = _parse(sample)

    pseudo = [p for p in document.paragraphs if p.text in {title, preamble, *content, "阶段说明"}]
    assert len(pseudo) == 6 and all(p.in_table for p in pseudo)
    assert any(p.text == "正常正文保留原始段落。" and not p.in_table for p in document.paragraphs)
    assert not document.figures_tables
    assert not _violations(document, "BODY_TYPOGRAPHY", "FIGURE_TABLE_CAPTION")


@pytest.mark.parametrize("text", [
    "图3-8（a）对于各组展示了不同结果。", "图3-11（a）是第一组图示。", "表4-1 为数据对照结果。",
    "图4-36 到图4-38展示了结果。", "Table X reveals the measured results.",
    "Table 2 and Table 3 contain the values.",
    "表3-10 结果显示，组间差异具有统计意义。", "图2-3 表明处理前后发生变化。",
    "表3-1 可知若干指标的分布。", "图3-1 如下所示。", "表3-2 如前所述描述全体样本。",
])
def test_pdf_prose_mentions_are_not_promoted_to_captions(text):
    from app.parsers.base import caption_parts

    assert caption_parts(text, pdf=True) is None


def test_pdf_latex_cover_math_and_hanging_reference_label():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page()
        sample.text("学术学位硕士学位论文", 270, 26, center=True)
        title = "异构环境下若干独立方法及其系统应用研究"
        sample.text(title, 323, 18, left=(sample.width - len(title) * 18) / 2 + 12)
        sample.new_page(1)
        sample.heading(CHAPTER)
        text = "设某一变量作为条件"
        sample.text(text, 164, left=90)
        sample.text("x + y", 164, 9, font="cour", left=90 + 12 * len(text) + 4)
        sample.text("(2-1)", 215, right=True, font="tiro")
        ref = next(font[0] for font in sample.page.get_fonts() if font[4] == "cour")
        sample.pdf.xref_set_key(ref, "BaseFont", "/CMMI12")
        sample.new_page(2)
        sample.heading("参考文献")
        sample.text("[1]", 156, font="tiro", left=90)
        sample.text("Smith. The title of the reference[M]. 2020.", 158, font="tiro", left=130)
        document = _parse(sample)

    assert cover_elements(document.paragraphs)["title_cn"][0] == title
    body = next(p for p in document.paragraphs if p.text.startswith(text))
    assert any(run.text.strip() == "x + y" and run.is_script for run in body.runs)
    formula, = [f for f in document.figures_tables if f.kind == "formula"]
    assert formula.number_raw == "2-1"
    reference, = document.references
    assert reference.index_num == 1 and "Smith." in reference.raw_text
    assert not _violations(document, "BODY_TYPOGRAPHY")


def test_white_image_print_separator_is_not_scanned_or_missing_a_page_number():
    white = pymupdf.Pixmap(b"P6\n8 8\n255\n" + b"\xff" * 192).tobytes("png")
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        sample.text(FULL_LINE, 150)
        sample.new_page()
        sample.page.insert_image(sample.page.rect, stream=white, keep_proportion=False)
        sample.new_page(2)
        sample.text(FULL_LINE, 150)
        document = _parse(sample)

    assert [p.page_no for p in document.page_setups if p.is_blank] == [2]
    assert not any(p.unit_kind == "scanned_page" for p in document.paragraphs)
    assert not _violations(document, "PAGE_NUMBER_STYLE")


def test_pdf_caption_like_table_cell_stays_inside_table():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        sample.text("表1 汇总结果", 144, center=True)
        _grid(sample, 160)
        sample.text("图1 处理流程", 207, left=165)
        document = _parse(sample)

    cell, = [p for p in document.paragraphs if p.text == "图1 处理流程"]
    assert cell.in_table and cell.role != "figure_caption"
    table, = document.figures_tables
    assert table.kind == "table" and table.relative_position == "above"
    assert cell.text in table.inner_texts
    assert not _violations(document, "FIGURE_TABLE_CAPTION")


def test_pdf_body_cross_page_subscript_frame_and_footnote():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1, chapter=True)
        sample.heading(CHAPTER)
        for y in (692, 714, 736):
            sample.text(FULL_LINE, y, left=95)
        sample.new_page()
        sample.text("2", sample.height - 42, 10.5, font="tiro", left=314)
        sample.text(FULL_LINE, 102, left=95)
        sample.text(FULL_LINE, 124, left=95)
        sample.text(FULL_LINE[:16], 146, left=95)
        sample.text("变量名称ABC", 207, left=95)
        sample.text("3", 211, 8, font="tiro", left=95 + 7 * 12)
        sample.text("① 引用的数据来源", 721, 9.5, left=95)
        document = _parse(sample)

    joined, = [p for p in document.paragraphs if (p.page_no, p.page_end) == (1, 2)]
    assert joined.line_count == 6 and joined.line_spacings_pt == pytest.approx([22, 22, 22, 22])
    assert [p.index for p in document.paragraphs] == list(range(len(document.paragraphs)))
    assert next(n for n in document.headers_footers.page_numbers if n.page_no == 2).alignment == "center"
    footnote, = [p for p in document.paragraphs if p.unit_kind == "footnote"]
    assert footnote.text.startswith("①")
    equation = next(p for p in document.paragraphs if p.text.startswith("变量"))
    assert any(run.text.strip() == "3" and run.is_script for run in equation.runs)
    assert not _violations(document, "BODY_TYPOGRAPHY")


def test_pdf_chinese_heading_levels_follow_chapter_numbering_system():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        sample.text("一、研究设计", 135, 15, bold=True)
        sample.text("（一）研究对象", 165, 14, bold=True)
        sample.text("第 二 章 模型应用", 260, 18, bold=True, center=True)
        sample.text("2.1 分段设计", 295, 15, bold=True, center=True)
        sample.text("一、设计任务", 325, 14, bold=True)
        sentence = "（1）成像速度：" + FULL_LINE + "。"
        sample.text(sentence, 360, 14, bold=True)
        document = _parse(sample)

    headings = {p.text: p.role for p in document.paragraphs if p.unit_kind == "heading"}
    assert headings["一、研究设计"] == "section_l2_heading"
    assert headings["（一）研究对象"] == "section_l3_heading"
    assert headings["一、设计任务"] == "section_l3_heading"
    assert heading_level(sentence) == 4
    assert next(p for p in document.paragraphs if p.text.startswith("（1）成像速度")).role == "body_text"


@pytest.mark.parametrize(("caption", "issue"), [
    ("图4-27 处理流程", None),
    ("（图1）处理流程", "外括号"),
    ("图1处理流程", "题注编号与标题间缺少空格"),
])
def test_pdf_caption_overlapping_image_edge_stays_bound(caption, issue):
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        sample.page.insert_image((145, 170, 450, 340), stream=_png(), keep_proportion=False)
        sample.text("图内单独标注", 214, center=True)
        sample.text(caption, 332, center=True)
        document = _parse(sample)

    figure, = document.figures_tables
    assert figure.caption_text == caption
    assert figure.object_bbox == (145, 170, 450, 340) and figure.relative_position == "below"
    assert figure.bbox[1] < figure.object_bbox[3] - 12
    assert figure.inner_texts == ["图内单独标注"]
    if issue:
        assert issue in figure.caption_style_issue
        assert any(issue in f.actual for f in _violations(document, "FIGURE_TABLE_CAPTION"))
    else:
        assert figure.caption_style_issue is None


@pytest.mark.parametrize("with_table", [False, True])
def test_pdf_appendix_outer_frame_preserves_text_and_embedded_objects(with_table):
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading("附录")
        sample.page.draw_rect((85, 129, 506, 736), color=(0, 0, 0), fill=(1, 1, 1) if with_table else None)
        for i in range(6):
            sample.text(f"第{i + 1}行附录正文保留原本的宋体字体与坐标。", 175 + i * 28, left=112)
        if with_table:
            _grid(sample, 380)
            sample.page.insert_image((150, 515, 390, 645), stream=_png(), keep_proportion=False)
            sample.text("图1 附录实物图", 665, center=True)
        document = _parse(sample)

    prose = [p for p in document.paragraphs if p.text.startswith("第") and p.role == "body_text"]
    assert sum(p.line_count for p in prose) == 6
    assert all(p.font_name == "simsun" and p.bbox[0] >= 110 for p in prose)
    figures = [obj for obj in document.figures_tables if obj.kind == "figure"]
    assert len(figures) == int(with_table)
    tables = [obj for obj in document.figures_tables if obj.kind == "table"]
    assert len(tables) == int(with_table)
    if with_table:
        assert figures[0].object_bbox == (150, 515, 390, 645) and not figures[0].inner_texts
        assert tables[0].object_bbox == (155, 380, 450, 480) and len(tables[0].inner_texts) == 4


def test_pdf_display_and_prose_use_distinct_wrap_evidence():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        sample.text("1.1 短标题", 135, 15, center=True, bold=True)
        sample.text("这是独立居中加粗正文", 158, 15, center=True, bold=True)
        title = "1.2 " + FULL_LINE[:25]
        sample.text(title, 205, 15, center=True, bold=True)
        sample.text("仍然是同一标题的续行", 228, 15, center=True, bold=True)
        sample.text(FULL_LINE[:-2] + "。", 290)
        sample.text("此外，另起一段的研究内容", 312)
        sample.text("（1）" + FULL_LINE[:33], 360)
        sample.text(FULL_LINE[:34], 382, left=sample.left + 24)
        sample.text("悬挂缩进的续行", 404, left=sample.left + 24)
        document = _parse(sample)

    units = {p.text: p for p in document.paragraphs}
    assert units["1.1 短标题"].line_count == 1
    assert units["这是独立居中加粗正文"].role == "body_text"
    assert units[title + "仍然是同一标题的续行"].line_count == 2
    assert units["此外，另起一段的研究内容"].line_count == 1
    assert next(p for p in document.paragraphs if p.text.startswith("（1）")).line_count == 3


def test_pdf_flush_left_paragraph_boundaries_after_sentence_punctuation():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        for start, chars, gap, next_text in (
            (150, 35, 22, "下一段文字从版心左侧开始。"),
            (270, 36, 27, "新的内容前有额外的段间距。"),
            (390, 36, 22, "仍在同一段内继续排印。"),
        ):
            sample.text(FULL_LINE, start)
            sample.text(FULL_LINE[:chars - 1] + "。", start + 22)
            sample.text(next_text, start + 22 + gap)
        document = _parse(sample)

    units = [p for p in document.paragraphs if p.role == "body_text"]
    assert [p.line_count for p in units] == [2, 1, 2, 1, 3]
    assert units[1].text.startswith("下一段") and units[3].text.startswith("新的内容")
    assert units[-1].text.endswith("仍在同一段内继续排印。")


def test_pdf_cross_page_font_finding_anchors_to_the_bad_run_on_page_two():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        for y in (692, 714, 736):
            sample.text(FULL_LINE, y)
        sample.new_page(2)
        sample.text(FULL_LINE, 102)
        sample.text("第二页上字体异常的折行", 124, font="china-ts")
        document = _parse(sample)

    merged, = [p for p in document.paragraphs if (p.page_no, p.page_end) == (1, 2)]
    bad_run, = [run for run in merged.runs if run.font_name == "simhei"]
    finding, = _violations(document, "BODY_TYPOGRAPHY")
    assert finding.location["page"] == bad_run.page_no == 2
    assert finding.location["bbox"] == list(bad_run.bbox)
    assert finding.location["paragraph_index"] == merged.index
    assert finding.location["excerpt"] == merged.text[:100]
    assert finding.location["highlight_excerpt"] == bad_run.text


def test_pdf_cross_page_spacing_finding_anchors_to_the_two_lines_on_page_two():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page(1)
        sample.heading(CHAPTER)
        for y in (692, 714, 736):
            sample.text(FULL_LINE, y)
        sample.new_page(2)
        sample.text(FULL_LINE, 102)
        sample.text("第二页换行收尾", 122)
        document = _parse(sample)

    merged, = [p for p in document.paragraphs if (p.page_no, p.page_end) == (1, 2)]
    assert merged.line_spacings_pt == pytest.approx([22, 22, 20])
    page_two = [r for r in merged.runs if r.page_no == 2]
    issue, = _violations(document, "LINE_SPACING_MIN")
    assert issue.location["page"] == 2 and issue.location["paragraph_index"] == merged.index
    assert issue.location["bbox"] == [page_two[0].bbox[0], page_two[0].bbox[1],
                                      page_two[0].bbox[2], page_two[1].bbox[3]]
    assert "20.00 pt" in issue.actual


def test_pdf_scan_coverage_and_front_bound_without_chinese_abstract():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page()
        sample.text("论文题名内容", 170, 22, center=True)
        sample.new_page()
        for offset in (0, 5):
            sample.page.insert_image((80 + offset, 145, 410 + offset, 545), stream=_png(),
                                     keep_proportion=False)
        sample.new_page()
        sample.page.insert_image(sample.page.rect, stream=_png(), keep_proportion=False)
        sample.new_page()
        sample.heading("目录")
        sample.text("第一章 设计与实现 ........ 1", 135)
        sample.new_page()
        sample.page.insert_image(sample.page.rect, stream=_png(), keep_proportion=False)
        sample.new_page(1)
        sample.heading(CHAPTER)
        document = _parse(sample)

    assert [p.page_no for p in document.paragraphs if p.unit_kind == "scanned_page"] == [3, 5]
    findings = _violations(document, "REQUIRED_SECTIONS")
    checks = {f.location.get("section"): f for f in findings}
    assert checks["abstract_cn"].severity == "error"
    front, = [f for f in findings if f.location.get("page") == 3]
    assert front.severity == "warning"
    assert "第 3 页" in front.actual and "声明" in front.actual and "答辩签名" in front.actual


def test_pdf_scan_after_english_abstract_is_reviewed_without_inferring_signatures():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page()
        sample.text("论文题名内容", 170, 22, center=True)
        sample.new_page()
        sample.heading("Abstract", font="tibo")
        sample.text("An abstract describing the purpose of this research.", 135, font="tiro")
        sample.new_page()
        sample.page.insert_image(sample.page.rect, stream=_png(), keep_proportion=False)
        sample.new_page(1)
        sample.heading(CHAPTER)
        sample.text(FULL_LINE, 130)
        sample.new_page(2)
        sample.page.insert_image(sample.page.rect, stream=_png(), keep_proportion=False)
        sample.new_page(3)
        sample.text(FULL_LINE, 130)
        document = _parse(sample)

    findings = _violations(document, "REQUIRED_SECTIONS")
    missing = {f.location.get("section"): f for f in findings if f.severity == "error"}
    assert {"abstract_cn", "declaration", "defense_signature"} <= missing.keys()
    reviews = [f for f in findings if f.severity == "warning"]
    assert [f.location["page"] for f in reviews] == [3, 5]
    assert all("排版" in f.message and f.location["bbox"] for f in reviews)


def test_pdf_cover_label_and_value_on_separate_lines_and_colonless_signature():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page()
        sample.text("学校代码", 113, 14, left=84)
        sample.text("10394", 136, 12, font="tiro", left=84)
        sample.text("图书分类号", 113, 14, left=340)
        sample.text("G633.6", 136, 12, font="tiro", left=340)
        sample.new_page()
        sample.heading("学位论文答辩委员会签名")
        sample.text("答辩委员会主席(签名)", 190, left=84)
        sample.page.draw_line((230, 194), (375, 194))
        document = _parse(sample)

    fields = cover_elements(document.paragraphs)
    assert fields["school_code"][0] == "10394"
    assert fields["library_classification"][0] == "G633.6"
    assert fields["school_code"][1].bbox[3] >= 136
    signature, = [p for p in document.paragraphs if p.field_label == "signature"]
    assert signature.has_underline and not signature.field_value
    assert signature.bbox[2] == 375
    assert any(f.severity == "warning" and f.actual == "签名下划线为空"
               for f in _violations(document, "COVER_ELEMENTS"))


def test_pdf_colonless_signature_slots_on_one_baseline_keep_their_own_images():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page()
        sample.heading("学位论文答辩委员会签名")
        sample.text("主席(签名)", 190, left=85)
        sample.text("委员(签名)", 190, left=330)
        rules = sample.page.new_shape()
        rules.draw_line((165, 194), (295, 194))
        rules.draw_line((410, 194), (525, 194))
        rules.finish()
        rules.commit()
        sample.page.insert_image((178, 163, 235, 193), stream=_png(), keep_proportion=False)
        document = _parse(sample)

    signed, blank = [p for p in document.paragraphs if p.field_label == "signature"]
    assert (signed.text, blank.text) == ("主席(签名)", "委员(签名)")
    assert signed.has_signature_image and not blank.has_signature_image
    assert signed.has_underline and blank.has_underline
    assert signed.bbox[2] < blank.bbox[0]
    assert not any(obj.kind == "figure" for obj in document.figures_tables)
    warning, = [f for f in _violations(document, "COVER_ELEMENTS") if f.actual == "签名下划线为空"]
    assert warning.severity == "warning" and warning.location["paragraph_index"] == blank.index


def test_pdf_empty_cover_field_does_not_consume_a_fragmented_label_below():
    sample = _PdfSample(None)
    with closing(sample.pdf):
        sample.new_page()
        sample.text("图书分类号：", 113, 14, left=340)
        sample.text("学号：QSX20210529", 137, 14, left=85)
        sample.text("密", 137, 14, left=342)
        sample.text("级：公开", 137, 14, left=394)
        document = _parse(sample)

    fields = cover_elements(document.paragraphs)
    assert fields["library_classification"][0] == ""
    assert fields["student_id"][0] == "QSX20210529"
    assert fields["classification"][0] == "公开"


def test_legacy_ir_loads_without_semantic_fields():
    from app.schemas.ir import DocumentIR

    document = DocumentIR.model_validate({
        "file_name": "legacy.pdf", "file_ext": "pdf", "page_count": 1,
        "paragraphs": [{"index": 0, "text": "旧正文", "page_no": 1, "paragraph_start_index": None}],
        "figures_tables": [{"kind": "figure", "caption_text": "", "number_raw": "", "paragraph_index": 0}],
    })
    paragraph, = document.paragraphs
    figure, = document.figures_tables
    assert paragraph.unit_kind == "paragraph" and paragraph.line_count == 1 and paragraph.line_spacings_pt == []
    assert paragraph.line_spacing_samples == []
    assert paragraph.page_end is None and paragraph.field_label is None and not paragraph.has_underline
    assert figure.subfigure_count == 1 and figure.inner_texts == [] and figure.object_bbox is None
