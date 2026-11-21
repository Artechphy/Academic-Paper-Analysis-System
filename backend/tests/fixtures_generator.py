"""Create reproducible DOCX and PDF samples without external fonts or office software."""
from io import BytesIO
from pathlib import Path
import re

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt
import pymupdf

DOCX_RULE_FAILURES = (
    "FILE_NAME_PATTERN", "PAGE_SIZE_A4", "PAGE_MARGINS", "LINE_SPACING_MIN", "HEADER_FORMAT",
    "HEADER_DOUBLE_BORDER", "PAGE_NUMBER_STYLE", "REQUIRED_SECTIONS", "SECTION_ORDER",
    "COVER_ELEMENTS", "DECLARATION_TYPOGRAPHY", "ABSTRACT_CN_TYPOGRAPHY", "ABSTRACT_EN_TYPOGRAPHY",
    "TOC_TYPOGRAPHY", "HEADING_TYPOGRAPHY", "BODY_TYPOGRAPHY", "ABSTRACT_CONTENT_RULES",
    "WORD_COUNT_REQUIREMENTS", "FIGURE_TABLE_CAPTION", "REFERENCE_GBT7714",
)
PDF_RULE_FAILURES = ("PDF_NOT_IMAGE_ONLY", "PAGE_SIZE_A4", "PAGE_MARGINS", "LINE_SPACING_MIN", "HEADER_FORMAT",
                     "PAGE_NUMBER_STYLE", "FIGURE_TABLE_CAPTION", "REFERENCE_GBT7714")
TITLE_CN = "论文版式分析方法研究"
TITLE_EN = "Research on Academic Document Layout"
CHAPTER = "第一章 版式分析方法"
ABSTRACT = "论文研究文档版式特征与学术排版检测方法并验证规则判断结果"
EXAMPLE = "本文依据论文排版规范分析结构字体段落和版面信息并通过样本验证检测方法"
COVER = (
    "学校编号：10394", "图书分类号：TP311", "作者姓名：测试作者",
    "专业：软件工程", "导师：测试导师", "学号：20260001",
)
REFERENCES = (
    "[1] 张三. 文档分析研究[J]. 信息学报, 2024.",
    "[2] 李四. 版面数据规范[EB/OL]. [2025-05-18]. https://example.org/layout",
)


def _repeated(text, count):
    return (text * (count // len(text) + 1))[:count]


def _png():
    data = b"P6\n96 96\n255\n" + bytes([40, 90, 155]) * (96 * 96)
    return pymupdf.Pixmap(data).tobytes("png")


def _element(name, **attributes):
    element = OxmlElement(f"w:{name}")
    for key, value in attributes.items():
        element.set(qn(f"w:{key}"), str(value))
    return element


def _font(properties, cn, latin="Times New Roman"):
    fonts = properties.get_or_add_rFonts()
    for attribute, value in (("eastAsia", cn), ("ascii", latin), ("hAnsi", latin)):
        fonts.attrib.pop(qn(f"w:{attribute}Theme"), None)
        fonts.set(qn(f"w:{attribute}"), value)


def _styles(document):
    normal = document.styles["Normal"]
    _font(normal.element.get_or_add_rPr(), "宋体")
    normal.font.size = Pt(12)
    normal.paragraph_format.line_spacing = Pt(22)
    for name, size, center, font in (
        ("Thesis title", 22, True, "黑体"), ("Declaration title", 18, True, "黑体"),
        ("Thesis heading", 18, True, "宋体"), ("Heading 1", 18, True, "宋体"),
        ("Heading 2", 15, True, "宋体"), ("Heading 3", 14, False, "宋体"),
        ("Heading 4", 12, False, "宋体"), ("Declaration contents", 14, False, "宋体"),
        ("TOC 1", 12, False, "宋体"),
    ):
        style = document.styles[name] if name in document.styles else document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style.base_style = normal
        _font(style.element.get_or_add_rPr(), font)
        style.font.size = Pt(size)
        style.font.bold = name not in {"Declaration contents", "Thesis title"}
        style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER if center else WD_ALIGN_PARAGRAPH.LEFT
    char_style = document.styles.add_style("TOC Page Number", WD_STYLE_TYPE.CHARACTER)
    _font(char_style.element.get_or_add_rPr(), "Times New Roman")
    char_style.font.size = Pt(12)


def _setup(section, violation):
    section.page_width = Mm(220 if violation == "PAGE_SIZE_A4" else 210)
    section.page_height = Mm(297)
    section.top_margin = Mm(37 if violation == "PAGE_MARGINS" else 30)
    section.bottom_margin = Mm(30)
    section.left_margin = Mm(29)
    section.right_margin = Mm(28)
    section.header_distance = Mm(22 if violation == "HEADER_FORMAT" else 15)


def _set_numbering(section, fmt, *, complex_field):
    previous = section._sectPr.find(qn("w:pgNumType"))
    if previous is not None:
        section._sectPr.remove(previous)
    section._sectPr.append(_element("pgNumType", fmt=fmt, start=1))
    for footer in (section.footer, section.even_page_footer):
        footer.is_linked_to_previous = False
        p = footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if complex_field:
            p.add_run()._r.append(_element("fldChar", fldCharType="begin"))
            instruction = _element("instrText")
            instruction.text = " PAGE "
            p.add_run()._r.append(instruction)
            p.add_run()._r.append(_element("fldChar", fldCharType="separate"))
            p.add_run("I")
            p.add_run()._r.append(_element("fldChar", fldCharType="end"))
        else:
            field = _element("fldSimple", instr="PAGE")
            field.append(p.add_run("1")._r)
            p._p.append(field)


def _headers(section, degree, violation):
    for header, title in (
        (section.header, CHAPTER),
        (section.even_page_header, f"福建师范大学教育学{'博士' if degree == 'doctor' else '硕士'}学位论文"),
    ):
        header.is_linked_to_previous = False
        p = header.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(title)
        run.font.size = Pt(10.5)
        _font(run._r.get_or_add_rPr(), "SimSun")
        border = _element("pBdr")
        border.append(_element("bottom", val="double", sz=12 if degree == "doctor" else (
            12 if violation == "HEADER_DOUBLE_BORDER" else 4
        )))
        p._p.get_or_add_pPr().append(border)


def make_fjnu_docx(directory: Path, *, degree="master", violation=None) -> Path:
    if violation is not None and violation not in DOCX_RULE_FAILURES:
        raise ValueError(violation)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("论文.docx" if violation == "FILE_NAME_PATTERN" else "20260001_测试.docx")
    document = Document()
    _styles(document)
    document.settings.odd_and_even_pages_header_footer = True
    _setup(document.sections[0], violation)

    title = document.add_paragraph(TITLE_CN, "Thesis title")
    if violation == "COVER_ELEMENTS":
        _font(title.runs[0]._r.get_or_add_rPr(), "微软雅黑")
    english_title = document.add_paragraph(TITLE_EN)
    english_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for line in COVER:
        document.add_paragraph(line)
    document.add_paragraph("独创性和使用授权声明", "Declaration title")
    declaration = document.add_paragraph("本人声明本论文由本人独立完成。", "Declaration contents")
    if violation == "DECLARATION_TYPOGRAPHY":
        declaration.runs[0].font.size = Pt(12)
    if violation != "REQUIRED_SECTIONS":
        document.add_paragraph("学位论文答辩签名表", "Thesis heading")
        document.add_paragraph("签名栏")

    front = document.add_section()
    _setup(front, violation)
    _set_numbering(front, "decimal" if violation == "PAGE_NUMBER_STYLE" else "upperRoman", complex_field=True)
    document.add_paragraph("摘 要", "Thesis heading")
    cn = document.add_paragraph(_repeated(ABSTRACT, 810 if degree == "doctor" else 510))
    if violation == "ABSTRACT_CN_TYPOGRAPHY":
        cn.runs[0].font.size = Pt(13)
    document.add_paragraph("关键词：" + ("版面;格式;文档" if violation == "ABSTRACT_CONTENT_RULES" else "版面；格式；文档"))
    en = document.add_paragraph("Abstract", "Thesis heading")
    if violation == "ABSTRACT_EN_TYPOGRAPHY":
        en.runs[0].bold = False
    document.add_paragraph("This study evaluates academic document layout with explicit formatting rules.")
    document.add_paragraph("Keywords: layout; formatting; document")
    document.add_paragraph("目 录", "Thesis heading")
    toc = document.add_paragraph("绪论\t", "TOC 1")
    field = _element("fldSimple", instr="PAGEREF Intro \\h")
    page = toc.add_run("1", style="TOC Page Number")
    if violation == "TOC_TYPOGRAPHY":
        page.font.name = "Arial"
    field.append(page._r)
    toc._p.append(field)
    document.add_paragraph("第一章 版式分析方法\t", "TOC 1").add_run("2", style="TOC Page Number")

    body = document.add_section()
    _setup(body, violation)
    _set_numbering(body, "decimal", complex_field=False)
    _headers(body, degree, violation)
    document.add_paragraph("绪论", "Thesis heading")
    document.add_paragraph(_repeated(EXAMPLE, 3150))
    document.add_paragraph(CHAPTER, "Heading 1")
    heading = document.add_paragraph("1.1 研究设计", "Heading 2")
    if violation == "HEADING_TYPOGRAPHY":
        heading.runs[0].font.size = Pt(13)
    document.add_paragraph("1.1.1 设计方法", "Heading 3")
    document.add_paragraph("1.1.1.1 研究范围", "Heading 4")
    body_size = 50500 if degree == "doctor" else 30500
    if violation == "WORD_COUNT_REQUIREMENTS":
        body_size = 1000
    for start in range(0, body_size, 450):
        paragraph = document.add_paragraph(_repeated(EXAMPLE, min(450, body_size - start)))
        if not start and violation == "LINE_SPACING_MIN":
            paragraph.paragraph_format.line_spacing = Pt(20)
        if not start and violation == "BODY_TYPOGRAPHY":
            paragraph.add_run("独立字体违规").font.size = Pt(13)
    figure = document.add_paragraph()
    figure.add_run().add_picture(BytesIO(_png()), width=Mm(26))
    caption = document.add_paragraph("图3 文档结构" if violation == "FIGURE_TABLE_CAPTION" else "图1 文档结构")
    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption = document.add_paragraph("表1-1 版式指标")
    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
    document.add_table(2, 2).cell(0, 0).text = "格式指标"
    document.add_paragraph("结论", "Thesis heading")
    document.add_paragraph("论文版式可通过结构化规则检测。")
    document.add_paragraph("参考文献", "Thesis heading")
    for reference in REFERENCES:
        document.add_paragraph(reference.replace("[2]", "[3]", 1) if violation == "REFERENCE_GBT7714" else reference)
    sections = ["攻读学位期间科研成果", "致谢", "个人简历"]
    if violation == "SECTION_ORDER":
        sections[0], sections[1] = sections[1], sections[0]
    for section in sections:
        document.add_paragraph(section, "Thesis heading")
        document.add_paragraph("此处为独立模块的合成样本内容。")
    document.save(path)
    return path


def make_general_docx(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    document = Document()
    _styles(document)
    section = document.sections[0]
    _setup(section, None)
    section.top_margin = section.bottom_margin = section.left_margin = section.right_margin = Mm(25.4)
    document.add_paragraph("文档布局研究", "Title")
    document.add_paragraph("摘要", "Thesis heading")
    document.add_paragraph("本文研究学术文档的布局。")
    document.add_paragraph("关键词：布局；文档；文本")
    document.add_paragraph("正文", "Thesis heading")
    document.add_paragraph("正文采用小四号字号。")
    document.add_paragraph("第二段也采用同一字号。")
    document.add_paragraph("参考文献", "Thesis heading")
    document.add_paragraph("[1] 张三. 文档分析研究[J]. 信息学报, 2024.")
    document.add_paragraph("[2] 李四. 电子版式资料[EB/OL].")
    path = directory / "通用论文.docx"
    document.save(path)
    return path


def _font_resource(pdf, page):
    """Install the standard Adobe-GB1 Song and Hei CJK font resources."""
    for alias, base in (("china-s", "STSong-Light"), ("china-ts", "SimHei")):
        # Different resource names prevent PyMuPDF from deduplicating the two fonts.
        xref = page.insert_font(fontname=alias)
        pdf.xref_set_key(xref, "BaseFont", f"/{base}")
        descendant = int(re.search(r"\d+", pdf.xref_get_key(xref, "DescendantFonts")[1])[0])
        pdf.xref_set_key(descendant, "BaseFont", f"/{base}")
        descriptor = int(re.search(r"\d+", pdf.xref_get_key(descendant, "FontDescriptor")[1])[0])
        pdf.xref_set_key(descriptor, "FontName", f"/{base}")
        if alias == "china-ts":
            pdf.xref_set_key(xref, "Encoding", "/UniGB-UTF16-H")
            pdf.xref_set_key(descendant, "CIDSystemInfo", "<< /Registry (Adobe) /Ordering (GB1) /Supplement 5 >>")


class _PdfSample:
    def __init__(self, violation):
        self.pdf = pymupdf.open()
        self.violation = violation
        self.width = float(Mm(210).pt)
        self.height = float(Mm(297).pt)
        self.left = float(Mm(37 if violation == "PAGE_MARGINS" else 29).pt)
        self.main_number = 0
        self.bad_header_written = False
        self.page = None

    def new_page(self, number=None, *, chapter=False):
        width = Mm(220).pt if self.page is None and self.violation == "PAGE_SIZE_A4" else self.width
        self.page = self.pdf.new_page(width=width, height=self.height)
        _font_resource(self.pdf, self.page)
        if number is not None:
            displayed = "X" if self.violation == "PAGE_NUMBER_STYLE" and number == "II" else str(number)
            self.text(displayed, self.height - 42, 10.5, center=True, font="tiro",
                      right=self.violation == "PAGE_NUMBER_STYLE" and number == "II")
        if chapter:
            title = CHAPTER if number % 2 else "福建师范大学教育学硕士学位论文"
            if self.violation == "HEADER_FORMAT" and not self.bad_header_written:
                title = "错误页眉"
                self.bad_header_written = True
            self.text(title, 42, 10.5, center=True)

    def text(self, text, y, size=12, *, center=False, right=False, bold=False, font="china-s", left=None):
        if font.startswith("china"):
            width = len(text) * size
        else:
            width = pymupdf.get_text_length(text, fontname=font, fontsize=size)
        x = (self.width - width) / 2 if center else self.left if left is None else left
        if right:
            x = self.width - 86 - width
        self.page.insert_text((x, y), text, fontsize=size, fontname=font,
                              render_mode=2 if bold else 0, border_width=.035)

    def heading(self, text, y=100, size=18, font="china-s"):
        self.text(text, y, size, center=True, bold=True, font=font)

    def long_section(self, title, count, *, chapter=False):
        spacing = 18 if self.violation == "LINE_SPACING_MIN" and chapter else 22
        payload = _repeated(EXAMPLE, count)
        start = 0
        while start < count:
            self.main_number += 1
            self.new_page(self.main_number, chapter=chapter)
            y = 98
            if not start:
                self.heading(title)
                y = 121
            lines = 30 if not start else 31
            excerpt = payload[start:start + lines * 36]
            start += len(excerpt)
            for offset in range(0, len(excerpt), 36):
                self.text(excerpt[offset:offset + 36], y, right=False)
                y += spacing
            if chapter and self.main_number == 4 and self.violation == "PDF_NOT_IMAGE_ONLY":
                # Preserve all other evidence while making the majority of the main matter scanned.
                image = _png()
                for _ in range(42):
                    self.main_number += 1
                    self.new_page(self.main_number, chapter=True)
                    box = pymupdf.Rect(30, 76, self.width - 30, self.height - 76)
                    self.page.insert_image(box, stream=image, keep_proportion=False)


def make_fjnu_pdf(directory: Path, *, violation=None) -> Path:
    if violation is not None and violation not in PDF_RULE_FAILURES:
        raise ValueError(violation)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "20260001_测试.pdf"
    sample = _PdfSample(violation)
    try:
        sample.new_page()
        sample.text(TITLE_CN, 125, 22, center=True, font="china-ts")
        sample.text(TITLE_EN, 155, 16, center=True, font="tiro")
        for index, text in enumerate(COVER):
            sample.text(text, 220 + index * 26)
        sample.new_page()
        sample.heading("独创性和使用授权声明", font="china-ts")
        sample.text("本人声明本论文由本人独立完成。", 132, 14)
        sample.new_page()
        sample.heading("学位论文答辩签名表")
        sample.text("签名栏", 132)
        sample.new_page("I")
        sample.heading("摘要")
        payload = _repeated(ABSTRACT, 510)
        for offset in range(0, len(payload), 36):
            sample.text(payload[offset:offset + 36], 122 + offset // 36 * 22)
        sample.text("关键词：版面；格式；文档", 465)
        sample.new_page("II")
        sample.heading("Abstract", font="tibo")
        sample.text("This study evaluates document layout with explicit formatting rules.", 122, font="tiro")
        sample.text("Keywords: layout; formatting; document", 144, font="tiro")
        sample.new_page("III")
        sample.heading("目录")
        sample.text("绪论 ........ 1", 122)
        sample.text("第一章 版式分析方法 ........ 4", 144)
        sample.long_section("绪论", 3150)
        sample.long_section(CHAPTER, 30500, chapter=True)

        sample.main_number += 1
        sample.new_page(sample.main_number, chapter=True)
        center = sample.width / 2
        sample.page.insert_image(pymupdf.Rect(center - 40, 112, center + 40, 184), stream=_png())
        sample.text("图1 文档结构", 204, center=violation != "FIGURE_TABLE_CAPTION")
        sample.text("表1-1 版式指标", 250, center=True)
        for column in range(3):
            x = center - 100 + column * 100
            sample.page.draw_line((x, 263), (x, 331))
        for row in range(3):
            y = 263 + row * 34
            sample.page.draw_line((center - 100, y), (center + 100, y))
        for index, text in enumerate(("版面", "字体", "边距", "字号")):
            sample.text(text, 285 + (index // 2) * 34, left=center - 68 + index % 2 * 100)

        for title, text in (("结论", "论文版式可通过结构化规则检测。"),
                            ("参考文献", REFERENCES[0]), ("攻读学位期间科研成果", "科研成果说明"),
                            ("致谢", "在此向同学致谢。"), ("个人简历", "个人简历说明")):
            sample.main_number += 1
            sample.new_page(sample.main_number)
            sample.heading(title)
            sample.text(text, 125)
            if title == "参考文献":
                description, url = REFERENCES[1].rsplit(" ", 1)
                sample.text(description, 147)
                if violation != "REFERENCE_GBT7714":
                    sample.text(url, 169, font="tiro", left=sample.left + 18)
        sample.pdf.save(path, garbage=4, deflate=True)
    finally:
        sample.pdf.close()
    return path


def make_scan(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "20260001_扫描.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=Mm(210).pt, height=Mm(297).pt)
        page.insert_image(page.rect, stream=_png(), keep_proportion=False)
        document.save(path)
    return path


def make_damaged(directory: Path, extension: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"20260001_损坏.{extension}"
    path.write_bytes(b"invalid document")
    return path
