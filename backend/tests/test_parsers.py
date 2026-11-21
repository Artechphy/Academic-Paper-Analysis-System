from io import BytesIO
import json

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Pt
import pymupdf
import pytest

from app.engine.utils import (
    chapter_number, chinese_size_to_pt, count_chinese_chars, normalize_font_name, page_number_format,
)
from app.parsers.base import CAPABILITIES, ParseError, cover_elements, parse_document
from app.parsers.docx_parser import parse_docx
from app.parsers.pdf_parser import parse_pdf
from app.schemas.ir import DocumentIR
from tests.fixtures_generator import (
    make_damaged, make_fjnu_docx, make_fjnu_pdf, make_scan, TITLE_CN,
)


@pytest.mark.parametrize(("source", "expected"), [
    ("ABCDEF+NSimSun", "simsun"), ("Songti SC", "simsun"), ("STSong-Light", "simsun"),
    ("方正书宋", "simsun"), ("宋体", "simsun"), ("华文宋体", "simsun"),
    ("ABCDEF+TimesNewRomanPS-BoldMT", "times_new_roman"), ("Times-Roman", "times_new_roman"),
    ("DEFABC+SimHei", "simhei"), ("黑体", "simhei"), ("STHeiti", "simhei"),
    ("Heiti SC", "simhei"), ("微软雅黑", "microsoft_yahei"), ("Microsoft YaHei Bold", "microsoft_yahei"),
    (None, None),
])
def test_font_normalization(source, expected):
    assert normalize_font_name(source) == expected


def test_formatting_utilities():
    assert [chinese_size_to_pt(size) for size in ("二号", "小二号", "小三号", "四号", "小四号", "五号")] == [
        22, 18, 15, 14, 12, 10.5,
    ]
    assert count_chinese_chars("𠮷汉字 abc 123") == 3
    assert chapter_number("第二十一章 标题") == 21
    assert chapter_number("第12章 标题") == 12
    assert page_number_format("— Ⅳ —") == "roman"
    assert page_number_format("第 １２ 页") == "decimal"
    assert page_number_format("IIX") == page_number_format("第十二页") == "none"


def test_docx_extracts_section_layout_styles_and_fields(tmp_path):
    path = make_fjnu_docx(tmp_path)
    ir = parse_docx(BytesIO(path.read_bytes()), file_name=path.name)
    assert ir.capabilities == dict.fromkeys(CAPABILITIES, True)
    assert ir.page_count == 3
    assert len(ir.page_setups) == 3
    for setup in ir.page_setups:
        assert (setup.width_mm, setup.height_mm) == pytest.approx((210, 297), abs=.03)
        assert (setup.top_margin_mm, setup.bottom_margin_mm, setup.left_margin_mm,
                setup.right_margin_mm, setup.header_distance_mm) == pytest.approx((30, 30, 29, 28, 15), abs=.03)
        assert setup.odd_even_headers
    odd, even = ir.headers_footers.odd_headers[0], ir.headers_footers.even_headers[0]
    assert odd.text == "第一章 版式分析方法"
    assert "硕士学位论文" in even.text
    for item in (odd, even):
        assert (item.font_name, item.font_size_pt, item.alignment) == ("simsun", 10.5, "center")
        assert (item.bottom_border_style, item.bottom_border_pt) == ("double", .5)
    numbers = {(item.section_index, item.variant): item for item in ir.headers_footers.page_numbers}
    assert (numbers[1, "default"].num_format, numbers[1, "default"].raw_text) == ("roman", "I")
    assert (numbers[2, "even"].num_format, numbers[2, "even"].raw_text) == ("decimal", "1")

    chap = next(p for p in ir.paragraphs if p.role == "chapter_heading")
    assert (chap.font_name, chap.font_name_latin, chap.font_size_pt, chap.bold, chap.alignment) == (
        "simsun", "times_new_roman", 18, True, "center",
    )
    assert (chap.line_spacing_rule, chap.line_spacing_pt) == ("exact", 22)
    assert {p.role for p in ir.paragraphs} >= {"section_l2_heading", "section_l3_heading", "section_l4_heading"}
    toc = next(p for p in ir.paragraphs if p.role == "toc_entry")
    assert (toc.font_name, toc.bold, toc.toc_page_number) == ("simsun", True, "1")
    assert (toc.toc_page_style.font_name, toc.toc_page_style.font_size_pt, toc.toc_page_style.bold) == (
        "times_new_roman", 12, True,
    )
    assert cover_elements(ir.paragraphs)["title_cn"][0] == TITLE_CN
    assert ir.stats.body_chinese_chars == 30500
    assert ir.stats.intro_chinese_chars == 3150
    assert ir.stats.abstract_cn_chars == 510
    assert [(x.kind, x.relative_position, x.number_raw) for x in ir.figures_tables] == [
        ("figure", "below", "1"), ("table", "above", "1-1"),
    ]
    assert [ref.index_num for ref in ir.references] == [1, 2]
    assert ir.references[1].has_url and ir.references[1].has_access_date
    assert DocumentIR.model_validate(json.loads(json.dumps(ir.model_dump(mode="json")))) == ir


def test_docx_at_least_spacing_multiple_and_inherited_header(tmp_path):
    source = make_fjnu_docx(tmp_path)
    document = Document(source)
    p = document.add_paragraph("字号字号")
    p.paragraph_format.line_spacing = 2.0
    p = document.add_paragraph("最小间距")
    p.paragraph_format.line_spacing = Pt(22)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.AT_LEAST
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    section = document.add_section()
    assert section.header.is_linked_to_previous
    document.add_paragraph("同一节页眉适用于后续节。")
    document.save(source)
    ir = parse_document(source)
    data = {p.text: p for p in ir.paragraphs}
    assert (data["字号字号"].line_spacing_rule, data["字号字号"].line_spacing_pt) == ("multiple", 24)
    assert (data["最小间距"].line_spacing_rule, data["最小间距"].alignment) == ("at_least", "justify")
    assert [item.section_index for item in ir.headers_footers.odd_headers] == [2, 3]


def test_pdf_extracts_observed_and_estimated_evidence(tmp_path):
    path = make_fjnu_pdf(tmp_path)
    ir = parse_pdf(path)
    assert ir.capabilities == {key: key == "exact_font_runs" for key in CAPABILITIES}
    with pymupdf.open(path) as pdf:
        assert ir.page_count == pdf.page_count
    assert ir.page_setups[0].width_mm == pytest.approx(210, abs=.01)
    measured = [page for page in ir.page_setups if page.bottom_margin_mm is not None]
    assert measured and measured[0].bottom_margin_mm == pytest.approx(30, abs=2)
    assert measured[0].left_margin_mm == pytest.approx(29, abs=1)
    assert measured[0].right_margin_mm == pytest.approx(28, abs=1)
    assert ir.headers_footers.odd_headers and ir.headers_footers.even_headers
    assert [p.raw_text for p in ir.headers_footers.page_numbers if p.num_format == "roman"] == ["I", "II", "III"]
    assert any(p.num_format == "decimal" and p.position == "footer" for p in ir.headers_footers.page_numbers)
    paragraphs = [p for p in ir.paragraphs if p.line_spacing_rule == "estimated" and p.section_key == "body"]
    assert paragraphs and paragraphs[0].line_spacing_pt == pytest.approx(22)
    assert ir.stats.text_page_ratio == 1 and not ir.is_image_only_pdf
    assert ir.stats.intro_chinese_chars == 3150
    assert ir.stats.abstract_cn_chars == 510
    assert ir.stats.body_chinese_chars == 30500
    assert [(x.kind, x.relative_position) for x in ir.figures_tables] == [("figure", "below"), ("table", "above")]
    assert ir.references[1].raw_text.endswith("https://example.org/layout")
    assert ir.references[1].has_url and ir.references[1].has_access_date
    assert DocumentIR.model_validate(ir.model_dump(mode="json")) == ir


def test_pure_scan(tmp_path):
    ir = parse_document(make_scan(tmp_path))
    assert ir.is_image_only_pdf
    assert ir.stats.text_page_ratio == 0
    assert ir.page_count == 1


@pytest.mark.parametrize("extension", ["docx", "pdf"])
def test_corrupt_document_is_parse_error(tmp_path, extension):
    with pytest.raises(ParseError, match=f"无法解析 {extension.upper()}"):
        parse_document(make_damaged(tmp_path, extension))


def test_docx_extracts_formatting_from_cover_table_value(tmp_path):
    source = tmp_path / "封面表格.docx"
    document = Document()
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "中文题目"
    p = table.cell(0, 1).paragraphs[0]
    run = p.add_run(TITLE_CN)
    run.font.name = "Times New Roman"
    run._r.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "SimHei")
    run.font.size = Pt(22)
    table.cell(1, 0).text = "学校编号"
    table.cell(1, 1).text = "10394"
    document.add_paragraph("摘要：通过文档验证解析行为。")
    document.save(source)
    ir = parse_docx(source)
    cover = cover_elements(ir.paragraphs)
    assert cover["title_cn"][0] == TITLE_CN
    assert (cover["title_cn"][1].font_name, cover["title_cn"][1].font_size_pt) == ("simhei", 22)
    assert cover["title_cn"][1].font_name_latin == "times_new_roman"
    assert cover["school_code"][0] == "10394"
    assert ir.stats.abstract_cn_chars == 10


def test_pdf_rejects_truncated_document_with_pdf_signature(tmp_path):
    original = make_scan(tmp_path)
    truncated = original.read_bytes().split(b"startxref", 1)[0]
    with pytest.raises(ParseError, match="无法解析 PDF"):
        parse_pdf(truncated, original.name)
