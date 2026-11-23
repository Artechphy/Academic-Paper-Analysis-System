"""Parser entry points and format-independent document analysis."""
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path
import re
from typing import BinaryIO
import unicodedata

from app.engine.utils import chapter_number, count_chinese_chars, heading_key, heading_level
from app.schemas.ir import (
    DetectedSectionIR, DocumentIR, DocumentStatsIR, FigureTableIR, ParagraphIR,
    ReferenceIR, TextRunIR,
)

DocumentSource = str | Path | bytes | BinaryIO
CAPABILITIES = (
    "exact_margins", "exact_line_spacing", "exact_header_distance", "exact_header_border",
    "exact_page_number_style", "exact_font_runs", "exact_alignment",
)
CN_KEYWORDS = re.compile(r"^\s*关\s*键\s*(?:词|字)\s*[:：]?\s*")
INLINE_ABSTRACT = re.compile(r"^\s*(?:(中文)?摘\s*要|abstract)\s*[:：]\s*(?=\S)", re.I)
EN_KEYWORDS = re.compile(r"^\s*key\s*words?\s*[:：]?\s*", re.I)
TOC_PAGE = re.compile(r"(?:\t+|[.．…·]{2,}|\s+)([0-9０-９]+|[IVXLCDMivxlcdmⅠ-ⅿ]+)\s*$")
CAPTION = re.compile(r"^(图|表|Figure\b|Fig\.|Table\b)\s*((?:\([^)]*\)|[\w]+(?:[.．—–-][\w]+)*))?(?=\s|[:：、.]|$)", re.I)
CAPTION_COMPACT = re.compile(r"^([图表])\s*([0-9０-９一二三四五六七八九十]+(?:[.．—–-][0-9０-９一二三四五六七八九十]+)*)")
CAPTION_MENTION = re.compile(r"^(?:所示|可见[，。,.]|显示[了出]|as follows\b|above\b|below\b|shows?\b|"
                             r"illustrates?\b|demonstrates?\b|indicates?\b|presents?\b|\))", re.I)
FORMULA_NUMBER = re.compile(r"[（(]([0-9０-９]+(?:[.．—–-][0-9０-９]+)*)[）)]\s*$")
CONTENT_SECTIONS = {"introduction", "body", "conclusion", "appendix", "references",
                    "achievements", "acknowledgements", "resume"}
COVER_LABELS = {
    "school_code": r"学校(?:代码|编号|代号)|单位代码",
    "library_classification": r"图书分类号|中图分类号|分类号",
    "title_cn": r"中文(?:论文)?[题标][目题]|(?:论文)?题目",
    "title_en": r"英文(?:论文)?[题标][目题]|English\s+Title",
    "author_name": r"(?:论文)?作者(?:姓名)?|(?:研究)?生姓名|姓\s*名",
    "major": r"学科\s*[、/]?\s*专业|(?:学科)?专业(?:名称)?",
    "supervisor": r"指导(?:教师|老师|导师)|导\s*师(?:姓名)?",
    "student_id": r"学\s*号",
}
COVER_LABEL = re.compile(
    r"(?:^|\s)(?:" + "|".join(f"(?P<{key}>{pattern})" for key, pattern in COVER_LABELS.items())
    + r")\s*[:：]?\s*", re.I,
)


class ParseError(ValueError):
    """The source could not be read as a supported document."""


class BaseParser(ABC):
    @abstractmethod
    def parse(self, source: DocumentSource, file_name: str | None = None) -> DocumentIR:
        """Read a document from a path, bytes, or a binary stream."""


def read_source(source: DocumentSource, file_name: str | None, extension: str) -> tuple[bytes, str]:
    if isinstance(source, (str, Path)):
        path = Path(source)
        return path.read_bytes(), Path(file_name or path.name).name
    if isinstance(source, bytes):
        return source, Path(file_name or f"document.{extension}").name
    stream_name = getattr(source, "name", None)
    name = file_name or (stream_name if isinstance(stream_name, (str, Path)) else f"document.{extension}")
    return source.read(), Path(name).name


def parse_document(source: DocumentSource, file_name: str | None = None) -> DocumentIR:
    from app.parsers.docx_parser import DocxParser
    from app.parsers.pdf_parser import PdfParser

    name = file_name or (str(source) if isinstance(source, (str, Path)) else getattr(source, "name", ""))
    extension = Path(name).suffix.lower() if isinstance(name, (str, Path)) else ""
    if extension == ".docx":
        return DocxParser().parse(source, file_name)
    if extension == ".pdf":
        return PdfParser().parse(source, file_name)
    raise ParseError("文件扩展名须为 .docx 或 .pdf")


def dominant_run(runs: list[TextRunIR]) -> TextRunIR | None:
    weights = {}
    representative = {}
    for run in runs:
        if run.text.strip():
            key = (run.font_name, run.font_name_latin, run.font_size_pt, run.bold)
            weights[key] = weights.get(key, 0) + len(run.text.strip())
            representative[key] = run
    return representative[max(weights, key=weights.get)] if weights else None


def parse_reference(text: str, index: int) -> ReferenceIR:
    number = re.match(r"^\s*\[(\d+)\]", text)
    labels = re.finditer(r"\[([A-Za-z]+)(?:/([A-Za-z]+))?\]", text)
    label = next(labels, None)
    access_date = False
    for year, month, day in re.findall(r"\[((?:19|20)\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\]", text):
        try:
            date(int(year), int(month), int(day))
        except ValueError:
            continue
        access_date = True
        break
    return ReferenceIR(
        index_num=int(number[1]) if number else None,
        raw_text=text, paragraph_index=index,
        type_code=label[1] if label else None,
        carrier_code=label[2] if label else None,
        has_url=bool(re.search(r"\b(?:https?://|ftp://|www\.)[^\s\]，。]+", text, re.I)),
        has_access_date=access_date,
    )


def caption_parts(text: str, *, pdf=False) -> tuple[str, str] | None:
    match = CAPTION_COMPACT.match(text) or CAPTION.match(text)
    if not match:
        # Capture malformed numbering so that it can be reported.
        match = re.match(r"^([图表])\s*([A-Z]+)(?=\s|[\u3400-\u9fff])", text)
    if match:
        kind = "figure" if match[1].lower().startswith(("图", "fig")) else "table"
        # A phrase such as “图 表明……” or “Figure shows…” is ordinary prose.
        number = match[2] or ""
        if pdf and CAPTION_MENTION.match(text[match.end():].lstrip()):
            return None
        if len(number) > 1 and number.isalpha() and not re.fullmatch(r"[IVXLCDM一二三四五六七八九十]+", number, re.I):
            return None
        return kind, number
    return None


def cover_elements(paragraphs: list[ParagraphIR]) -> dict[str, tuple[str, ParagraphIR]]:
    elements = {}
    pending = None
    for paragraph in paragraphs:
        if paragraph.section_key != "cover" or not paragraph.text.strip():
            continue
        text = paragraph.text.strip()
        matches = list(COVER_LABEL.finditer(text))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            value = text[match.end():end].strip(" \t_：:")
            if value:
                elements[match.lastgroup] = (value, paragraph)
                pending = None
            else:
                pending = match.lastgroup
        if not matches:
            if pending:
                elements[pending] = (text, paragraph)
                pending = None
            elif paragraph.role == "cover_title":
                elements.setdefault("title_cn", (text, paragraph))
            elif re.fullmatch(r"[A-Za-z][A-Za-z0-9 ,.'’:\-()]+", text) and len(text.split()) >= 2:
                elements.setdefault("title_en", (text, paragraph))
    return elements


def classify_document(document: DocumentIR, *, pdf_headings: set[int] | None = None,
                      pdf_toc_entries: frozenset[int] | set[int] = frozenset()) -> None:
    current = "cover"
    has_title = False
    seen = set()
    pdf = pdf_headings is not None
    for paragraph in document.paragraphs:
        if not pdf:
            paragraph.role = "other"
        text = paragraph.text.strip()
        style = (paragraph.style_name or "").casefold()
        paragraph.section_key = current
        if not text or paragraph.role in {"footnote", "equation_fragment"} or paragraph.in_table and current != "cover":
            continue
        is_toc_style = bool(re.match(r"(?:toc|目录)\s*\d", style))
        looks_like_toc_entry = paragraph.toc_page_number is not None or TOC_PAGE.search(text)
        key = heading_key(text) if len(text) <= 90 else None
        level = heading_level(text, style) if len(text) <= 100 else None
        if pdf:
            if paragraph.index not in pdf_headings:
                key = level = None
            elif level is not None and level > 1:
                # A numbered subsection does not start a new thesis module.
                key = None
            elif re.fullmatch(r"中\s*文\s*文\s*摘", text) and current in {
                "cover", "abstract_cn", "abstract_en", "cnki_abstract"
            }:
                key = "cnki_abstract" if "abstract_cn" in seen else "abstract_cn"

        inline_abstract = INLINE_ABSTRACT.match(text)
        if current == "toc" and (is_toc_style or looks_like_toc_entry
                                 or (pdf and paragraph.index in pdf_toc_entries)):
            paragraph.role = "toc_entry"
        elif key:
            current = key
            paragraph.role = "section_heading"
        elif inline_abstract and (not pdf or current in {"cover", "abstract_cn", "abstract_en", "cnki_abstract"}
                                  or paragraph.index in pdf_headings):
            current = "abstract_en" if text.casefold().startswith("abstract") else "abstract_cn"
            paragraph.role = "body_text"
        elif level and (current != "cover" or chapter_number(text) is not None):
            if pdf and level > 1 and current not in CONTENT_SECTIONS:
                paragraph.role = "toc_entry" if current == "toc" else "body_text"
                continue
            if level == 1:
                current = "body"
                paragraph.role = "chapter_heading"
            else:
                if current not in CONTENT_SECTIONS:
                    current = "body"
                paragraph.role = f"section_l{level}_heading"
        elif current == "cover":
            title_label = COVER_LABEL.match(text)
            is_title_label = title_label and title_label.lastgroup == "title_cn" and text[title_label.end():].strip()
            explicit_title = style in {"title", "标题"} or is_title_label
            looks_like_title = (
                not has_title and title_label is None and 2 <= count_chinese_chars(text) <= 60
                and (paragraph.alignment == "center" or paragraph.index == 0)
                and not re.search(r"(?:大学|学位论文|封面)$", text)
                and not re.search(r"[。！？]", text)
            )
            if explicit_title or looks_like_title:
                paragraph.role = "cover_title"
                has_title = True
        elif (current == "abstract_cn" and CN_KEYWORDS.match(text)
              or current == "abstract_en" and EN_KEYWORDS.match(text)):
            paragraph.role = "keywords_cn" if current == "abstract_cn" else "keywords_en"
        elif current == "references":
            paragraph.role = "reference_entry"
        elif current == "toc":
            paragraph.role = "toc_entry"
        else:
            parts = caption_parts(text, pdf=pdf) if current in CONTENT_SECTIONS and len(text) <= 200 else None
            paragraph.role = f"{parts[0]}_caption" if parts else "body_text"
        paragraph.section_key = current
        seen.add(current)


def _sections(paragraphs: list[ParagraphIR]) -> list[DetectedSectionIR]:
    sections = []
    current = None
    for paragraph in paragraphs:
        if paragraph.section_key is None:
            continue
        if current is None or current.key != paragraph.section_key:
            current = DetectedSectionIR(
                key=paragraph.section_key, title=paragraph.text if paragraph.text else "",
                start_paragraph_index=paragraph.index, end_paragraph_index=paragraph.index,
                page_start=paragraph.page_no,
            )
            sections.append(current)
        current.end_paragraph_index = paragraph.index
        if not current.title and paragraph.text:
            current.title = paragraph.text
        current.chinese_char_count += count_chinese_chars(paragraph.text)
    return [section for section in sections if section.title]


def _figures_tables(paragraphs: list[ParagraphIR], *, pdf=False) -> list[FigureTableIR]:
    result = []
    chapter = None
    used_objects = set()
    visible = [p for p in paragraphs if not p.in_table and p.role not in {"footnote", "equation_fragment"}
               and (p.text.strip() or p.object_kind or p.has_image)]
    if pdf:
        captions = {"figure_caption", "table_caption"}
        merged = []
        for paragraph in visible:
            previous = merged[-1] if merged else None
            if (paragraph.role in captions and previous is not None and previous.role == paragraph.role
                    and previous.page_no == paragraph.page_no
                    and bool(re.match(r"^[图表]", previous.text)) != bool(re.match(r"^[图表]", paragraph.text))):
                parts = caption_parts(paragraph.text, pdf=True)
                if parts and parts[1] and caption_parts(previous.text, pdf=True) == parts:
                    continue
            merged.append(paragraph)
        visible = merged
    object_chapters = {}
    for index, paragraph in enumerate(visible):
        if paragraph.role in {"chapter_heading", "section_heading"}:
            number = chapter_number(paragraph.text)
            if number is not None:
                chapter = number
        if paragraph.object_kind in {"figure", "table"} and paragraph.section_key in CONTENT_SECTIONS:
            object_chapters[paragraph.index] = (paragraph, chapter)
        if paragraph.object_kind == "formula":
            number = FORMULA_NUMBER.search(paragraph.text)
            result.append(FigureTableIR(
                kind="formula", caption_text=paragraph.text, number_raw=number[1] if number else "",
                paragraph_index=paragraph.index, alignment=paragraph.alignment, chapter_index=chapter, bbox=paragraph.bbox,
            ))
        if paragraph.role not in {"figure_caption", "table_caption"}:
            continue
        parts = caption_parts(paragraph.text.strip(), pdf=pdf)
        if parts is None:
            continue
        kind, number = parts
        position = "unknown"
        offsets = (-1, 1) if kind == "figure" else (1, -1)
        for offset in offsets:
            neighbor_index = index + offset
            if not 0 <= neighbor_index < len(visible):
                continue
            neighbor = visible[neighbor_index]
            if neighbor.section_key != paragraph.section_key or neighbor.index in used_objects:
                continue
            if neighbor.object_kind == kind or kind == "figure" and neighbor.has_image:
                used_objects.add(neighbor.index)
                position = "below" if offset == -1 else "above"
                break
        result.append(FigureTableIR(
            kind=kind, caption_text=paragraph.text, number_raw=number, paragraph_index=paragraph.index,
            alignment=paragraph.alignment, relative_position=position, chapter_index=chapter, bbox=paragraph.bbox,
        ))
    for index, (paragraph, chapter) in object_chapters.items():
        if index not in used_objects:
            result.append(FigureTableIR(
                kind=paragraph.object_kind, caption_text="", number_raw="", paragraph_index=index, bbox=paragraph.bbox,
                alignment=paragraph.alignment, chapter_index=chapter,
            ))
    return sorted(result, key=lambda item: item.paragraph_index)


def analyze_document(document: DocumentIR, *, text_page_ratio: float = 1.0) -> DocumentIR:
    classify_document(document)
    return summarize_document(document, text_page_ratio=text_page_ratio)


def summarize_document(document: DocumentIR, *, text_page_ratio: float = 1.0) -> DocumentIR:
    paragraphs = document.paragraphs
    document.sections = _sections(paragraphs)
    document.figures_tables = _figures_tables(paragraphs, pdf=document.file_ext == "pdf")
    document.references = [parse_reference(p.text, p.index) for p in paragraphs if p.role == "reference_entry"]
    stats = DocumentStatsIR(text_page_ratio=text_page_ratio)
    for paragraph in paragraphs:
        count = count_chinese_chars(paragraph.text)
        stats.total_chinese_chars += count
        if paragraph.role != "body_text":
            continue
        if paragraph.section_key == "body":
            stats.body_chinese_chars += count
        if paragraph.section_key == "introduction":
            stats.intro_chinese_chars += count
        if paragraph.section_key == "abstract_cn":
            stats.abstract_cn_chars += count_chinese_chars(INLINE_ABSTRACT.sub("", paragraph.text))
        if paragraph.section_key == "abstract_en":
            stats.abstract_en_words += len(re.findall(r"[A-Za-z]+(?:[-'’][A-Za-z]+)*",
                                                        INLINE_ABSTRACT.sub("", paragraph.text)))
    document.stats = stats
    return document
