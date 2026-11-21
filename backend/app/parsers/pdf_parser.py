"""Extract PDF text and estimate layout from observed page geometry."""
from dataclasses import dataclass
import re
from statistics import median

import pymupdf

from app.engine.utils import heading_key, normalize_font_name, page_number_format, pt_to_mm
from app.parsers.base import (
    BaseParser, CAPABILITIES, DocumentSource, FORMULA_NUMBER, ParseError, analyze_document,
    dominant_run, parse_reference, read_source,
)
from app.schemas.ir import DocumentIR, HeaderItemIR, PageNumberIR, PageSetupIR, ParagraphIR, TextRunIR


@dataclass
class _Line:
    box: pymupdf.Rect
    baseline: float
    paragraph: ParagraphIR


def _alignment(box, width):
    if abs((box.x0 + box.x1) / 2 - width / 2) <= max(7, width * .017):
        return "center"
    if box.x0 > width * .55 and box.x1 > width * .8:
        return "right"
    return "left"


def _stroke_origins(page):
    painted = set()
    stroked = set()
    for trace in page.get_texttrace():
        if trace["type"] not in {0, 1} or not trace["chars"]:
            continue
        key = (trace["font"], *(round(value, 1) for value in trace["chars"][0][2]))
        if trace["type"] == 0:
            painted.add(key)
        elif trace["linewidth"] and trace["linewidth"] >= .12:
            stroked.add(key)
    return painted & stroked


def _lines(page):
    width = page.rect.width
    # MuPDF text/graphics coordinates are in the unrotated page coordinate system.
    rotation = page.rotation_matrix
    strokes = _stroke_origins(page)
    result = []
    for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)["blocks"]:
        for line in block.get("lines", ()):
            runs = []
            for span in line["spans"]:
                text = span["text"]
                if not text.strip():
                    if runs:
                        runs[-1].text += text
                    continue
                font = normalize_font_name(span["font"])
                key = (span["font"], *(round(value, 1) for value in span["origin"]))
                bold = bool(
                    span["flags"] & pymupdf.TEXT_FONT_BOLD
                    or re.search(r"bold|heavy|black|demi", span["font"], re.I)
                    or key in strokes
                )
                runs.append(TextRunIR(
                    text=text, font_name=font, font_name_latin=font if re.search(r"[A-Za-z]", text) else None,
                    font_size_pt=span["size"], bold=bold,
                ))
            if not runs:
                continue
            box = pymupdf.Rect(line["bbox"]) * rotation
            if box.is_empty:
                continue
            main = dominant_run(runs)
            latin = dominant_run([run for run in runs if run.font_name_latin])
            text = "".join(run.text for run in runs).strip()
            number = FORMULA_NUMBER.search(text)
            formula = number and re.search(r"[=∑∫≈≤≥]", text[:number.start()])
            result.append(_Line(
                box, (pymupdf.Point(line["spans"][0]["origin"]) * rotation).y,
                ParagraphIR(
                    index=0, page_no=page.number + 1, text=text,
                    font_name=main.font_name, font_name_latin=latin.font_name_latin if latin else None,
                    font_size_pt=main.font_size_pt, bold=main.bold,
                    alignment=_alignment(box, width), runs=runs, object_kind="formula" if formula else None,
                ),
            ))
    return sorted(result, key=lambda item: (round(item.box.y0, 1), item.box.x0))


def _objects(page, lines, image_boxes):
    width, height = page.rect.width, page.rect.height
    objects = [("figure", box) for box in image_boxes
               if 22 <= box.width < width * .98 and 22 <= box.height < height * .9]
    drawings = page.get_drawings()
    if drawings:
        tables = [pymupdf.Rect(table.bbox) * page.rotation_matrix
                  for table in page.find_tables(paths=drawings, use_layout=False).tables]
        objects += [("table", box) for box in tables]
        for (x0, y0, x1, y1) in page.cluster_drawings(drawings=drawings):
            box = pymupdf.Rect(x0, y0, x1, y1) * page.rotation_matrix
            if (box.width >= 28 and box.height >= 28 and box.get_area() < width * height * .75
                    and not any((table & box).get_area() >= box.get_area() * .5 for table in tables)):
                objects.append(("figure", box))
        lines = [line for line in lines if not any(
            kind == "table" and (box & line.box).get_area() >= line.box.get_area() * .8
            for kind, box in objects
        )]
    for kind, box in objects:
        if any(line.paragraph.object_kind == kind and (line.box & box).get_area() >= box.get_area() * .8
               for line in lines):
            continue
        lines.append(_Line(box, box.y0, ParagraphIR(
            index=0, page_no=page.number + 1, text="", has_image=kind == "figure",
            object_kind=kind, alignment=_alignment(box, width),
        )))
    return sorted(lines, key=lambda line: (round(line.box.y0, 1), line.box.x0))


def _page_number(line, position):
    p = line.paragraph
    return PageNumberIR(
        page_no=p.page_no, num_format=page_number_format(p.text), raw_text=p.text,
        position=position, alignment=p.alignment,
    )


def _add_page(page, result):
    width, height = page.rect.width, page.rect.height
    page_no = page.number + 1
    rotation = page.rotation_matrix
    lines = _lines(page)
    image_boxes = [pymupdf.Rect(image["bbox"]) * rotation for image in page.get_image_info()]
    image_coverage = sum((box & page.rect).get_area() for box in image_boxes) / page.rect.get_area()
    useful_chars = sum(sum(character.isalnum() for character in line.paragraph.text) for line in lines)
    scanned = image_coverage >= .5 and useful_chars < 25
    header_candidates = []
    body = []
    numbers = []
    for line in lines:
        p = line.paragraph
        if line.baseline > height * .92 and page_number_format(p.text) != "none":
            numbers.append(_page_number(line, "footer"))
        elif line.baseline < height * .083 and page_number_format(p.text) != "none":
            numbers.append(_page_number(line, "header"))
        elif line.baseline < height * .082 and not heading_key(p.text) and len(p.text) <= 95:
            header_candidates.append(line)
        else:
            body.append(line)

    document_page_no = page_no
    for number in numbers:
        if number.position == "footer" and number.num_format == "decimal":
            match = re.search(r"\d+", number.raw_text)
            if match:
                document_page_no = int(match[0])
                break
    headers = result.headers_footers
    target = headers.odd_headers if document_page_no % 2 else headers.even_headers
    # High cover text is content. A running head normally sits above the body text with a clear gap.
    for line in header_candidates:
        p = line.paragraph
        if (p.font_size_pt or 0) > 15 or (not scanned and (not body or body[0].box.y0 - line.box.y1 < 8)):
            body.append(line)
            body.sort(key=lambda item: (item.box.y0, item.box.x0))
            continue
        target.append(HeaderItemIR(
            text=p.text, font_name=p.font_name, font_size_pt=p.font_size_pt, bold=p.bold,
            alignment=p.alignment, page_no=page_no, runs=p.runs,
        ))

    headers.page_numbers.extend(numbers or [PageNumberIR(page_no=page_no)])
    result.page_setups.append(PageSetupIR(page_no=page_no, width_mm=pt_to_mm(width), height_mm=pt_to_mm(height)))
    page_lines = body if scanned else _objects(page, body, image_boxes)
    body_characters = sum(sum(character.isalnum() for character in line.paragraph.text) for line in body)
    # Sparse title/transition pages are legitimate. An image-dominated page with a token OCR layer is not.
    text_page = body_characters >= 4 and not scanned
    return page_lines, scanned, text_page


def _measure(result, lines_by_page):
    bottoms = {}
    for setup, lines in zip(result.page_setups, lines_by_page, strict=True):
        body = [line for line in lines if line.paragraph.role == "body_text"
                and line.paragraph.section_key in {"introduction", "body", "conclusion"}
                and line.paragraph.object_kind is None]
        if len(body) >= 3:
            main_lines = [line for line in lines if line.paragraph.section_key in {"introduction", "body", "conclusion"}
                          and line.paragraph.text and line.paragraph.object_kind is None]
            setup.top_margin_mm = pt_to_mm(min(line.box.y0 for line in main_lines))
            setup.left_margin_mm = pt_to_mm(min(line.box.x0 for line in body))
            right = setup.width_mm - pt_to_mm(max(line.box.x1 for line in body))
            bottom = setup.height_mm - pt_to_mm(max(line.box.y1 for line in body))
            # A short or ragged line does not reveal where the right margin was set.
            if max(line.box.width for line in body) >= setup.width_mm * 72 / 25.4 * .60:
                setup.right_margin_mm = right
            if bottom <= setup.height_mm * .20:
                geometry = (round(setup.width_mm, 1), round(setup.height_mm, 1))
                bottoms.setdefault(geometry, []).append((setup, bottom))
        spaced = [line for line in lines if line.paragraph.role in {"body_text", "reference_entry"}
                  and line.paragraph.object_kind is None]
        for previous, current in zip(spaced, spaced[1:]):
            first, second = previous.paragraph, current.paragraph
            distance = current.baseline - previous.baseline
            max_size = max(first.font_size_pt or 0, second.font_size_pt or 0)
            if (first.section_key == second.section_key and abs(previous.box.x0 - current.box.x0) < 32
                    and max(2, max_size * .4) <= distance <= max(38, max_size * 3)):
                first.line_spacing_pt = distance
                first.line_spacing_rule = "estimated"

    for candidates in bottoms.values():
        minimum = min(bottom for _, bottom in candidates)
        for setup, bottom in candidates:
            if bottom <= minimum + 4:
                setup.bottom_margin_mm = bottom


def _merge_reference_lines(result, lines_by_page):
    for lines in lines_by_page:
        anchor = previous = None
        for line in lines:
            p = line.paragraph
            if p.role != "reference_entry":
                anchor = previous = None
                continue
            start = re.match(r"^\s*(?:\[\d+\]|\d+[.)、]|[A-Z][A-Za-z]+,)", p.text)
            if previous is not None and not start:
                width_pt = result.page_setups[p.page_no - 1].width_mm * 72 / 25.4
                hanging_indent = line.box.x0 >= anchor.box.x0 + 4
                full_line = previous.box.x1 >= width_pt * .79
                type_marker = r"\[[A-Za-z]+(?:/[A-Za-z]+)?\]"
                separate_type = re.search(type_marker, p.text) and re.search(type_marker, anchor.paragraph.text)
                close = 0 < line.baseline - previous.baseline <= max(29, (p.font_size_pt or 12) * 2.3)
                if close and not separate_type and (hanging_indent or full_line):
                    anchor.paragraph.text += " " + p.text
                    anchor.paragraph.runs.extend(p.runs)
                    p.text, p.runs, p.role = "", [], "other"
                    previous = line
                    continue
            anchor = previous = line
    result.references = [parse_reference(p.text, p.index) for p in result.paragraphs if p.role == "reference_entry"]


class PdfParser(BaseParser):
    def parse(self, source: DocumentSource, file_name: str | None = None) -> DocumentIR:
        try:
            data, name = read_source(source, file_name, "pdf")
            with pymupdf.open(stream=data, filetype="pdf") as pdf:
                if not pdf.is_pdf or pdf.needs_pass or pdf.page_count == 0 or pdf.is_repaired:
                    raise ValueError("PDF 为空、已加密或结构损坏")
                capabilities = dict.fromkeys(CAPABILITIES, False)
                capabilities["exact_font_runs"] = True
                result = DocumentIR(file_name=name, file_ext="pdf", page_count=pdf.page_count,
                                    capabilities=capabilities)
                lines_by_page = []
                scanned_pages, text_pages = set(), set()
                for page in pdf:
                    lines, scanned, text_page = _add_page(page, result)
                    page_no = page.number + 1
                    lines_by_page.append(lines)
                    if scanned:
                        scanned_pages.add(page_no)
                    if text_page:
                        text_pages.add(page_no)
                    for line in lines:
                        line.paragraph.index = len(result.paragraphs)
                        result.paragraphs.append(line.paragraph)
                analyze_document(result, text_page_ratio=len(text_pages) / pdf.page_count)
                content_pages = {
                    p.page_no for p in result.paragraphs
                    if p.section_key in {"introduction", "body", "conclusion", "references"}
                }
                if content_pages:
                    # Include intervening image pages, which have no paragraphs to classify.
                    first, last = min(content_pages), max(content_pages)
                    content_pages = set(range(first, last + 1))
                else:
                    content_pages = set(range(1, pdf.page_count + 1))
                result.is_image_only_pdf = (
                    not (content_pages & text_pages) or len(content_pages & scanned_pages) > len(content_pages) / 2
                    or len(scanned_pages) > pdf.page_count / 2
                )
                _measure(result, lines_by_page)
                _merge_reference_lines(result, lines_by_page)
                return result
        except (OSError, RuntimeError, ValueError, TypeError, IndexError, KeyError) as exc:
            raise ParseError(f"无法解析 PDF 文件：{exc}") from exc


def parse_pdf(source: DocumentSource, file_name: str | None = None) -> DocumentIR:
    return PdfParser().parse(source, file_name)
