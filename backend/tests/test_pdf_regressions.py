"""PDF layout regressions exercised through the parser and the seeded rules."""
from contextlib import closing

import pymupdf
import pytest

from app.db.seed import FJNU_RULES_BY_CODE
from app.engine.evaluator import evaluate
from app.engine.utils import normalize_font_name
from app.parsers.pdf_parser import parse_pdf
from tests.fixtures_generator import CHAPTER, EXAMPLE, _PdfSample


EVEN_HEADER = "福建师范大学教育学硕士学位论文"
FULL_LINE = (EXAMPLE * 2)[:36]


def _parse(sample):
    return parse_pdf(sample.pdf.tobytes(), "20260001_测试.pdf")


def _violations(document, *codes):
    return evaluate(document, [FJNU_RULES_BY_CODE[code] for code in codes]).violations


def test_pdf_baseline_tolerance_still_flags_tight_spacing():
    with closing(pymupdf.open()) as pdf:
        # Small PDFs exercise the actual PyMuPDF baseline coordinates.
        page = pdf.new_page()
        for baseline in (100, 121.96, 142.46):
            page.insert_text((82, baseline), "A paragraph with a measured baseline", fontsize=12)
        page.insert_text((225, 80), "Main Text", fontsize=16)
        document = parse_pdf(pdf.tobytes(), "20260001_测试.pdf")

    finding, = _violations(document, "LINE_SPACING_MIN")
    assert "20.50 pt" in finding.actual
    measured = [p.line_spacing_pt for p in document.paragraphs if p.line_spacing_pt is not None]
    assert measured == pytest.approx([21.96, 20.5], abs=.01)


@pytest.mark.parametrize(("name", "family"), [
    ("NERFFC+HYShuSongErKW", "simsun"),
    ("宋体".encode().decode("latin-1"), "simsun"),
    ("宋体".encode("gbk").decode("latin-1"), "simsun"),
    ("å_ä1_2", "simsun"),
    ("STSongti-TC-Regular", "simsun"),
    ("LVLPJS+HYZhongHeiKW", "simhei"),
    ("黑体".encode().decode("latin-1"), "simhei"),
    ("TimesNewRomanPS-BoldItal", "times_new_roman"),
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
    continuation = next(p for p in document.paragraphs if p.text.startswith("English words"))
    assert continuation.paragraph_start_index == first.index
    wrong_chinese, wrong_english = _violations(document, "BODY_TYPOGRAPHY")
    assert wrong_chinese.actual == "字体为黑体"
    assert len(wrong_chinese.location["paragraph_indices"]) == 2
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
