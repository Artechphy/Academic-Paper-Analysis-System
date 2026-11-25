"""Parser entry points and format-independent document analysis."""
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import date
from pathlib import Path
import re
from typing import BinaryIO
import unicodedata

from app.engine.utils import chapter_number, count_chinese_chars, heading_key, heading_level, mm_to_pt
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
CAPTION_MENTION = re.compile(
    r"^(?:[（(]\s*[a-z]\s*[）)]\s*)?(?:所示|可见[，。,.]|结果显示|表明|可知|如下|如前|显示[了出]|对于|是|为(?!了)|"
    r"(?:到|至|和|及|与)\s*(?:图|表)\s*\d|as follows\b|above\b|below\b|"
    r"(?:shows?|reveals?|illustrates?|demonstrates?|indicates?|presents?|summari[sz]es?)\b|"
    r"(?:and|to|through)\s+(?:(?:Tables?|Figures?)\b|Fig\.)|\))", re.I,
)
_PDF_CAPTION = re.compile(
    r"^(?P<open>[（(])?\s*(?P<label>续表|表格|图|表|Figure|Fig\.|Table)(?P<space>\s*)"
    r"(?P<number>[0-9０-９一二三四五六七八九十]+(?:[.．—–-][0-9０-９一二三四五六七八九十]+)*"
    r"|[IVXLCDM]+(?=\s|[):：）]|$))?",
    re.I,
)
_CONTINUED = re.compile(r"续表|[（(]\s*(?:continued|续)\s*[）)]", re.I)
FORMULA_NUMBER = re.compile(r"[（(]([0-9０-９]+(?:[.．—–-][0-9０-９]+)*)[）)]\s*$")
CONTENT_SECTIONS = {"introduction", "body", "conclusion", "appendix", "references",
                    "achievements", "acknowledgements", "resume"}
COVER_LABELS = {
    "school_code": r"学\s*校\s*(?:代\s*码|编\s*号|代\s*号)|单\s*位\s*代\s*码",
    "library_classification": r"(?:图\s*书\s*|中\s*图\s*)?分\s*类\s*号",
    "title_cn": r"中\s*文\s*(?:论\s*文\s*)?[题标]\s*[目题]|(?:论\s*文\s*)?题\s*目",
    "title_en": r"英\s*文\s*(?:论\s*文\s*)?[题标]\s*[目题]|English\s+Title",
    "author_name": r"(?:论\s*文\s*)?作\s*者(?:\s*姓\s*名)?|(?:研\s*究\s*)?生\s*姓\s*名|姓\s*名",
    "major": r"(?:学\s*科\s*[、/]?\s*)?专\s*业(?!\s*学\s*位)(?:\s*名\s*称)?",
    "supervisor": r"指\s*导\s*(?:教\s*师|老\s*师|导\s*师)|导\s*师(?:\s*姓\s*名)?",
    "student_id": r"学\s*号",
    "classification": r"密\s*级",
    "research_direction": r"研\s*究\s*方\s*向",
    "study_mode": r"学\s*习\s*形\s*式",
    "training_unit": r"培\s*养\s*单\s*位",
    "submission_date": r"提\s*交\s*时\s*间",
    "completion_date": r"完\s*成\s*时\s*间",
}
COVER_LABEL = re.compile(
    r"(?<!\S)(?:" + "|".join(f"(?P<{key}>{pattern})" for key, pattern in COVER_LABELS.items())
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


def pdf_caption_details(text):
    """Return capture and style evidence independently."""
    match = _PDF_CAPTION.match(text.strip())
    if not match:
        return None
    label = match["label"].lower()
    number = match["number"] or ""
    suffix = text.strip()[match.end():]
    rest = suffix.lstrip()
    closes_number = bool(match["open"] and rest.startswith((")", "）")))
    title = rest[1:].lstrip() if closes_number else rest
    if CAPTION_MENTION.match(title):
        return None
    if not number and label != "续表":
        return None
    kind = "figure" if label.startswith(("图", "fig")) else "table"
    issues = []
    if match["open"]:
        issues.append("题注使用外括号")
    if label == "表格":
        issues.append("应使用“表”作为表题标识")
    if label.isascii() and not match["space"]:
        issues.append("英文标识与编号之间缺少空格")
    if title.startswith((":", "：")):
        issues.append("编号后有多余冒号")
    elif number and not closes_number and suffix and not suffix[0].isspace() and re.match(r"[\w]", suffix):
        issues.append("题注编号与标题间缺少空格")
    return kind, number, "、".join(issues) or None, bool(_CONTINUED.search(text))


def caption_parts(text: str, *, pdf=False) -> tuple[str, str] | None:
    if pdf and (details := pdf_caption_details(text)):
        return details[:2]
    match = CAPTION_COMPACT.match(text) or CAPTION.match(text)
    if not match:
        # Capture malformed numbering so that it can be reported.
        match = re.match(r"^([图表])\s*([A-Z]+)(?=\s|[\u3400-\u9fff])", text)
    if match:
        kind = "figure" if match[1].lower().startswith(("图", "fig")) else "table"
        # A phrase such as “图 表明……” or “Figure shows…” is ordinary prose.
        number = match[2] or ""
        if CAPTION_MENTION.match(text[match.end():].lstrip()):
            return None
        if len(number) > 1 and number.isalpha() and not re.fullmatch(r"[IVXLCDM一二三四五六七八九十]+", number, re.I):
            return None
        return kind, number
    return None


def bilingual_captions(a, b, *, pdf=False):
    first, second = caption_parts(a, pdf=pdf), caption_parts(b, pdf=pdf)
    chinese = re.compile(r"^[（(]?\s*[图表续]")
    return bool(first and second and first[1] and first == second
                and bool(chinese.match(a)) != bool(chinese.match(b)))


def cover_elements(paragraphs: list[ParagraphIR]) -> dict[str, tuple[str, ParagraphIR]]:
    elements = {}
    pending = None
    for paragraph in paragraphs:
        if paragraph.section_key != "cover" or not paragraph.text.strip():
            continue
        if paragraph.field_label:
            if paragraph.field_label in COVER_LABELS:
                elements[paragraph.field_label] = (paragraph.field_value or "", paragraph)
            pending = None
            continue
        text = paragraph.text.strip()
        matches = list(COVER_LABEL.finditer(text))
        if matches and matches[0].start() > 0:
            matches = []
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
            elif paragraph.role == "cover_title_en" or re.fullmatch(r"[A-Za-z][A-Za-z0-9 ,.'’:\-()]+", text) and len(text.split()) >= 2:
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
        if (not text or paragraph.role in {"footnote", "equation_fragment", "scanned_page", "underline_row"}
                or paragraph.in_figure or paragraph.object_kind == "formula" and pdf
                or paragraph.in_table and current != "cover"):
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
            explicit_title = style in {"title", "标题"} or is_title_label or paragraph.role == "cover_title"
            looks_like_title = (
                not has_title and title_label is None and 2 <= count_chinese_chars(text) <= 60
                and (paragraph.alignment == "center" or paragraph.index == 0)
                and not re.search(r"(?:大学|学位论文|封面)$", text)
                and (not pdf or (paragraph.font_size_pt or 0) >= 16)
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


def _figures_tables(paragraphs: list[ParagraphIR]) -> list[FigureTableIR]:
    result = []
    chapter = None
    used_objects = set()
    visible = [p for p in paragraphs if not p.in_table and (p.text.strip() or p.object_kind or p.has_image)]
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
        parts = caption_parts(paragraph.text.strip())
        if parts is None:
            continue
        if (index and visible[index - 1].role == paragraph.role
                and bilingual_captions(visible[index - 1].text, paragraph.text)):
            continue
        kind, number = parts
        position = "unknown"
        offsets = (-1, -2, 1, 2) if kind == "figure" else (1, 2, -1, -2)
        for offset in offsets:
            neighbor_index = index + offset
            if not 0 <= neighbor_index < len(visible):
                continue
            neighbor = visible[neighbor_index]
            if neighbor.section_key != paragraph.section_key or neighbor.index in used_objects:
                continue
            if abs(offset) == 2:
                between = visible[index + offset // 2]
                if between.role != paragraph.role or not bilingual_captions(paragraph.text, between.text):
                    continue
            if neighbor.object_kind == kind or kind == "figure" and neighbor.has_image:
                used_objects.add(neighbor.index)
                position = "below" if offset < 0 else "above"
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


def _pdf_figure_continuations(objects, heights, captioned):
    continuations = set()
    for page in sorted(heights, reverse=True):
        if page - 1 not in heights:
            continue
        candidates = []
        for later, chapter in objects.get((page, "figure"), ()):
            if (later.index not in captioned and later.index not in continuations
                    or not later.bbox or later.bbox[1] > heights[page] * .16):
                continue
            for earlier, earlier_chapter in objects.get((page - 1, "figure"), ()):
                if earlier.index in captioned or not earlier.bbox or earlier.bbox[3] < heights[page - 1] * .78:
                    continue
                if earlier.section_key != later.section_key or (chapter and earlier_chapter and chapter != earlier_chapter):
                    continue
                left_delta = abs(earlier.bbox[0] - later.bbox[0])
                right_delta = abs(earlier.bbox[2] - later.bbox[2])
                if max(left_delta, right_delta) <= 12:
                    candidates.append((left_delta + right_delta, earlier.index, later.index))
        linked = set()
        for _, previous, current in sorted(candidates):
            if previous not in continuations and current not in linked:
                continuations.add(previous)
                linked.add(current)
    return continuations


def _pdf_figures_tables(paragraphs, metadata, page_setups):
    captions = defaultdict(list)
    objects = defaultdict(list)
    result = []
    chapter = None
    previous_caption = None
    for paragraph in paragraphs:
        if paragraph.role in {"chapter_heading", "section_heading"}:
            chapter = chapter_number(paragraph.text) or chapter
        if paragraph.object_kind == "formula":
            number = FORMULA_NUMBER.search(paragraph.text)
            result.append(FigureTableIR(
                kind="formula", caption_text=paragraph.text, number_raw=number[1] if number else "",
                paragraph_index=paragraph.index, alignment=paragraph.alignment, chapter_index=chapter,
                bbox=paragraph.bbox, object_bbox=paragraph.bbox,
            ))
        elif paragraph.object_kind in {"figure", "table"} and paragraph.section_key in CONTENT_SECTIONS:
            objects[paragraph.page_no, paragraph.object_kind].append((paragraph, chapter))
        elif paragraph.role in {"figure_caption", "table_caption"}:
            details = pdf_caption_details(paragraph.text)
            if not details:
                parts = caption_parts(paragraph.text, pdf=True)
                if not parts:
                    continue
                details = (*parts, None, bool(_CONTINUED.search(paragraph.text)))
            # Adjacent Chinese/English translations are two labels for the same object.
            signature = (paragraph.page_no, details[0], details[1])
            chinese = bool(re.match(r"^[（(]?\s*[图表续]", paragraph.text))
            if (details[1] and previous_caption and previous_caption[0] == signature
                    and previous_caption[1] != chinese and paragraph.index - previous_caption[2] <= 2):
                continue
            previous_caption = signature, chinese, paragraph.index
            captions[paragraph.page_no, details[0]].append((paragraph, chapter, details))

    matched, used = {}, set()
    for key, page_captions in captions.items():
        candidates = []
        page_objects = objects[key]
        kind = key[1]
        for ci, (caption, caption_chapter, (_, number, _, _)) in enumerate(page_captions):
            for oi, (obj, object_chapter) in enumerate(page_objects):
                if caption.section_key != obj.section_key or not (caption.bbox and obj.bbox):
                    continue
                if caption_chapter is not None and object_chapter is not None and caption_chapter != object_chapter:
                    continue
                cx0, cy0, cx1, cy1 = caption.bbox
                ox0, oy0, ox1, oy1 = obj.bbox
                # The first printed line supplies a more reliable edge than the union of a wrapped caption.
                first_box = next((run.bbox for run in caption.runs if run.bbox and run.text.strip()), None)
                line_bottom = first_box[3] if first_box else min(cy1, cy0 + 17)
                baseline = line_bottom - (caption.font_size_pt or 12) * .27
                below = baseline > (oy0 + oy1) / 2
                gap = cy0 - oy1 if below else oy0 - cy1
                edge_distance = baseline - oy1 if below else oy0 - baseline
                horizontal_gap = max(ox0 - cx1, cx0 - ox1, 0)
                centered = ox0 - 8 <= (cx0 + cx1) / 2 <= ox1 + 8
                near_numbered_edge = below and number and centered and edge_distance >= -14
                overlap = 23 if near_numbered_edge else 12
                if not -overlap <= gap <= 77 or horizontal_gap > 65:
                    continue
                penalty = 22 if below != (kind == "figure") else 0
                offset = abs(cx0 + cx1 - ox0 - ox1) / 2
                cost = max(gap, 0) + abs(min(edge_distance, 0)) + penalty + horizontal_gap
                cost += min(12, abs(caption.index - obj.index)) + min(12, offset * .10)
                candidates.append((cost, ci, oi, "below" if below else "above"))
        for _, ci, oi, position in sorted(candidates):
            caption, obj = page_captions[ci][0], page_objects[oi][0]
            if caption.index not in matched and obj.index not in used:
                matched[caption.index] = (obj, position)
                used.add(obj.index)

    heights = {setup.page_no: mm_to_pt(setup.height_mm) for setup in page_setups
               if setup.page_no is not None and setup.height_mm}
    for (page, kind), page_captions in captions.items():
        if kind != "figure" or page not in heights or page - 1 not in heights:
            continue
        candidates = []
        for caption, chapter, _ in page_captions:
            if caption.index in matched or not caption.bbox or caption.bbox[1] > heights[page] * .28:
                continue
            for obj, obj_chapter in objects[page - 1, kind]:
                if obj.index in used or not obj.bbox or obj.bbox[3] < heights[page - 1] * .68:
                    continue
                if obj.section_key != caption.section_key or (chapter and obj_chapter and chapter != obj_chapter):
                    continue
                cx0, cy0, cx1, _ = caption.bbox
                ox0, _, ox1, oy1 = obj.bbox
                if max(cx0 - ox1, ox0 - cx1, 0) > 30:
                    continue
                cost = cy0 + (heights[page - 1] - oy1) + abs(cx0 + cx1 - ox0 - ox1) * .25
                candidates.append((cost, caption.index, obj.index, obj))
        for _, index, _, obj in sorted(candidates, key=lambda match: match[:3]):
            if index not in matched and obj.index not in used:
                matched[index] = (obj, "below")
                used.add(obj.index)

    continuations = _pdf_figure_continuations(objects, heights, used)
    for (_, kind), page_captions in captions.items():
        for caption, chapter, (_, number, issue, continuation) in page_captions:
            obj, position = matched.get(caption.index, (None, "unknown"))
            extra = dict(metadata.get(obj.index, {})) if obj else {}
            inferred = extra.pop("is_continuation", False)
            result.append(FigureTableIR(
                kind=kind, caption_text=caption.text, number_raw=number, paragraph_index=caption.index,
                alignment=caption.alignment, relative_position=position, chapter_index=chapter, bbox=caption.bbox,
                object_bbox=obj.bbox if obj else None, object_page_no=obj.page_no if obj else None,
                caption_style_issue=issue,
                is_continuation=kind == "table" and (continuation or inferred), **extra,
            ))
    for (_, kind), page_objects in objects.items():
        for obj, chapter in page_objects:
            if obj.index not in used:
                extra = dict(metadata.get(obj.index, {}))
                if obj.index in continuations:
                    extra["is_continuation"] = True
                result.append(FigureTableIR(
                    kind=kind, caption_text="", number_raw="", paragraph_index=obj.index, bbox=obj.bbox,
                    object_bbox=obj.bbox, object_page_no=obj.page_no, alignment=obj.alignment, chapter_index=chapter,
                    **extra,
                ))
    return sorted(result, key=lambda item: item.paragraph_index)


def _unit_kind(paragraph):
    if paragraph.object_kind:
        return paragraph.object_kind
    if paragraph.role in {"footnote", "underline_row", "scanned_page", "toc_entry"}:
        return paragraph.role
    if paragraph.role == "reference_entry":
        return "reference"
    if paragraph.role.endswith("_caption"):
        return "caption"
    if paragraph.role.endswith("_heading") or paragraph.role.startswith("cover_title"):
        return "heading"
    return "paragraph" if paragraph.text else "other"


def analyze_document(document: DocumentIR, *, text_page_ratio: float = 1.0) -> DocumentIR:
    classify_document(document)
    return summarize_document(document, text_page_ratio=text_page_ratio)


def summarize_document(document: DocumentIR, *, text_page_ratio: float = 1.0, pdf_objects=None) -> DocumentIR:
    paragraphs = document.paragraphs
    document.sections = _sections(paragraphs)
    for paragraph in paragraphs:
        paragraph.unit_kind = _unit_kind(paragraph)
    if document.file_ext == "docx":
        document.figures_tables = _figures_tables(paragraphs)
    elif pdf_objects is not None or not document.figures_tables:
        document.figures_tables = _pdf_figures_tables(paragraphs, pdf_objects or {}, document.page_setups)
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
