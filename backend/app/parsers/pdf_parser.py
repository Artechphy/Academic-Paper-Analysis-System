"""Extract PDF text and estimate layout from observed page geometry."""
from collections import defaultdict
from dataclasses import dataclass
import re
from statistics import median

import pymupdf

from app.engine.utils import (
    FONT_FAMILIES, HAN, chapter_number, heading_key, heading_level, mm_to_pt, normalize_font_name, page_number_format,
    pdf_page_parities, pt_to_mm,
)
from app.parsers.base import (
    BaseParser, CAPABILITIES, DocumentSource, FORMULA_NUMBER, ParseError, caption_parts, classify_document,
    dominant_run, read_source, summarize_document,
)
from app.schemas.ir import DocumentIR, HeaderItemIR, PageNumberIR, PageSetupIR, ParagraphIR, TextRunIR


@dataclass
class _Line:
    box: pymupdf.Rect
    baseline: float
    paragraph: ParagraphIR


_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
_MAIN_SECTIONS = {"introduction", "body", "conclusion"}
_REFERENCE_START = re.compile(r"^\s*(?:[\[［]\s*\d+\s*[\]］]|\d{1,4}[)）、]|\d{1,3}\.\s+)")
_AUTHOR_START = re.compile(r"^(?:[A-Z][A-Za-z'-]+,\s+[A-Z]|[\u3400-\u9fff]{2,5}[.,．，、].*(?:\d{4}|\[[A-Z]))")
_TYPE_MARKER = re.compile(r"\[[A-Z]+(?:/[A-Z]+)?\]")
_TOC_LEADERS = re.compile(r"[.．…·]{3,}\s*(?:\d+|[IVXLCDMⅠ-ⅿ]+)?\s*$", re.I)
_MATH_FONTS = {"symbol", "symbolmt", "symboltigerexpert", "mt_extra", "cambriamath"}


def _font_aliases(page, cache):
    aliases = {}
    for xref, _, _, base_name, *_ in page.get_fonts():
        name = _SUBSET_PREFIX.sub("", base_name)
        if not xref or normalize_font_name(name) in FONT_FAMILIES:
            continue
        if xref not in cache:
            pdf = page.parent
            kind, descendants = pdf.xref_get_key(xref, "DescendantFonts")
            descendant = re.match(r"\[\s*(\d+)\s+\d+\s+R", descendants) if kind == "array" else None
            font_xref = int(descendant[1]) if descendant else xref
            kind, descriptor = pdf.xref_get_key(font_xref, "FontDescriptor")
            descriptor_xref = int(descriptor.split()[0]) if kind == "xref" else None
            # xref_get_key decodes PDF strings and name escapes.
            fields = [pdf.xref_get_key(descriptor_xref, key)[1] if descriptor_xref else
                      pdf.xref_get_key(font_xref, f"FontDescriptor/{key}")[1]
                      for key in ("FontName", "FontFamily")]
            cache[xref] = next((family for field in fields
                                if (family := normalize_font_name(field.removeprefix("/"))) in FONT_FAMILIES), None)
        if cache[xref]:
            aliases[name] = cache[xref]
    return aliases


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


def _set_line_style(paragraph):
    runs = paragraph.runs
    main = dominant_run([run for run in runs if HAN.search(run.text)] or runs)
    latin = dominant_run([run for run in runs if run.font_name_latin and not HAN.search(run.text)])
    paragraph.font_name = main.font_name
    paragraph.font_size_pt = main.font_size_pt
    paragraph.bold = main.bold
    paragraph.font_name_latin = latin.font_name_latin if latin else main.font_name_latin


def _bbox(box):
    return tuple(round(value, 2) for value in box)


def _join_lines(anchor, line, *, separator=" "):
    first, second = anchor.paragraph, line.paragraph
    first.text += separator + second.text
    first.runs.extend(second.runs)
    anchor.box |= line.box
    first.bbox = _bbox(anchor.box)
    _set_line_style(first)


def _lines(page, aliases=None):
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
                name = _SUBSET_PREFIX.sub("", span["font"])
                font = (aliases or {}).get(name) or normalize_font_name(name)
                key = (span["font"], *(round(value, 1) for value in span["origin"]))
                bold = bool(
                    span["flags"] & pymupdf.TEXT_FONT_BOLD
                    or re.search(r"bold|heavy|black|demi", span["font"], re.I)
                    or key in strokes
                )
                runs.append(TextRunIR(
                    text=text, font_name=font, font_name_latin=font if re.search(r"[A-Za-z]", text) else None,
                    font_size_pt=span["size"], bold=bold, is_script=bool(span["flags"] & pymupdf.TEXT_FONT_SUPERSCRIPT),
                ))
            if not runs:
                continue
            box = pymupdf.Rect(line["bbox"]) * rotation
            if box.is_empty:
                continue
            text = "".join(run.text for run in runs).strip()
            number = FORMULA_NUMBER.search(text)
            formula = number and re.search(r"[=∑∫≈≤≥]", text[:number.start()])
            paragraph = ParagraphIR(
                index=0, page_no=page.number + 1, text=text, bbox=_bbox(box), alignment=_alignment(box, width),
                runs=runs, object_kind="formula" if formula else None,
            )
            _set_line_style(paragraph)
            result.append(_Line(
                box, (pymupdf.Point(line["spans"][0]["origin"]) * rotation).y,
                paragraph,
            ))
    return _join_line_fragments(result, width)


def _join_line_fragments(lines, width):
    rows = []
    for line in sorted(lines, key=lambda item: item.baseline):
        if rows and abs(rows[-1][0].baseline - line.baseline) <= 1:
            rows[-1].append(line)
        else:
            rows.append([line])
    result = []
    for row in rows:
        previous = None
        for line in sorted(row, key=lambda item: item.box.x0):
            if previous:
                first, second = previous.paragraph, line.paragraph
                gap = line.box.x0 - previous.box.x1
                if first.text == second.text and abs(line.box.x0 - previous.box.x0) < 1:
                    continue
                if (-1 <= gap <= max(first.font_size_pt, second.font_size_pt) * 1.05
                        and not (first.object_kind or second.object_kind)):
                    _join_lines(previous, line, separator=" " if gap > 1 else "")
                    first.alignment = _alignment(previous.box, width)
                    continue
            result.append(line)
            previous = line
    return result


def _body_graphics(box, width, height):
    is_page_frame = (box.width >= width * .84 and box.height >= height * .72
                     and box.y0 <= height * .12 and box.y1 >= height * .88)
    return box.y1 > height * .083 and box.y0 < height * .92 and not is_page_frame


def _drawing_paths(page, drawings):
    width, height = page.rect.width, page.rect.height
    for path in drawings:
        box = path["rect"] * page.rotation_matrix
        if not _body_graphics(box, width, height):
            continue
        fill = path.get("fill")
        if path["type"] == "f" and fill is not None and min(fill) >= .98:
            # Word/PDF converters often paint a white box behind every text line.
            continue
        yield path


def _horizontal_rules(page, paths):
    rows = defaultdict(list)
    for path in paths:
        box = path["rect"] * page.rotation_matrix
        if box.height <= 2 and box.width >= 4:
            rows[round((box.y0 + box.y1) / 2)].append(box)
    # Some producers emit a separate filled strip for each cell in the same horizontal rule.
    return [
        (y, min(box.x0 for box in boxes), max(box.x1 for box in boxes))
        for y, boxes in sorted(rows.items())
        if sum(box.width for box in boxes) >= page.rect.width * .32
    ]


def _captioned_ruled_tables(lines, rules):
    captions = [
        line for line in lines if (parts := caption_parts(line.paragraph.text, pdf=True)) and parts[0] == "table"
    ]
    for index, caption in enumerate(captions):
        start = caption.baseline
        limit = captions[index + 1].box.y0 if index + 1 < len(captions) else float("inf")
        available = [(y, left, right) for y, left, right in rules if start < y < limit]
        if len(available) < 2 or available[0][0] - start > 55:
            continue
        top, left, right = available[0]
        matching = [y for y, x0, x1 in available if max(abs(x0 - left), abs(x1 - right)) <= 9]
        if len(matching) < 2:
            continue
        box = pymupdf.Rect(left, top, right, matching[-1])
        inside = [line for line in lines if (box & line.box).get_area() >= line.box.get_area() * .8]
        cells_by_row = defaultdict(int)
        for line in inside:
            if line.box.width < box.width * .8:
                cells_by_row[round(line.baseline)] += 1
        if sum(count >= 2 for count in cells_by_row.values()) >= 2:
            yield box


def _objects(page, lines, image_boxes, drawings):
    width, height = page.rect.width, page.rect.height
    objects = [("figure", box) for box in image_boxes
               if 22 <= box.width < width * .98 and 22 <= box.height < height * .9
               and _body_graphics(box, width, height)]
    paths = list(_drawing_paths(page, drawings))
    if paths:
        # Table detection only needs rules. A filled rectangle in a diagram is not a cell boundary.
        rules = [path for path in paths if path["type"] != "f"
                 or min(path["rect"].width, path["rect"].height) <= 2]
        tables = [pymupdf.Rect(table.bbox) * page.rotation_matrix
                  for table in page.find_tables(paths=rules, use_layout=False).tables
                  if table.row_count >= 2 and table.col_count >= 2] if rules else []
        for table in _captioned_ruled_tables(lines, _horizontal_rules(page, rules)):
            if not any((other & table).get_area() >= table.get_area() * .5 for other in tables):
                tables.append(table)
        objects += [("table", box) for box in tables]
        for (x0, y0, x1, y1) in page.cluster_drawings(drawings=paths):
            box = pymupdf.Rect(x0, y0, x1, y1) * page.rotation_matrix
            if (box.width >= 28 and box.height >= 28 and _body_graphics(box, width, height)
                    and not any((image & box).get_area() >= box.get_area() * .8 for image in image_boxes)
                    and not any((table & box).get_area() >= box.get_area() * .5 for table in tables)):
                objects.append(("figure", box))
        for line in lines:
            if any((box & line.box).get_area() >= line.box.get_area() * .8 for box in tables):
                line.paragraph.in_table = True
    for kind, box in objects:
        if any(line.paragraph.object_kind == kind and (line.box & box).get_area() >= box.get_area() * .8
               for line in lines):
            continue
        lines.append(_Line(box, box.y0, ParagraphIR(
            index=0, page_no=page.number + 1, text="", bbox=_bbox(box), has_image=kind == "figure",
            object_kind=kind, alignment=_alignment(box, width),
        )))
    return sorted(lines, key=lambda line: (round(line.box.y0, 1), line.box.x0))


def _page_number(line, position):
    p = line.paragraph
    return PageNumberIR(
        page_no=p.page_no, num_format=page_number_format(p.text), raw_text=p.text,
        position=position, alignment=p.alignment, bbox=p.bbox,
    )


def _add_page(page, result, font_cache):
    width, height = page.rect.width, page.rect.height
    page_no = page.number + 1
    rotation = page.rotation_matrix
    lines = _lines(page, _font_aliases(page, font_cache))
    image_boxes = [pymupdf.Rect(image["bbox"]) * rotation for image in page.get_image_info()]
    image_coverage = sum((box & page.rect).get_area() for box in image_boxes) / page.rect.get_area()
    useful_chars = sum(sum(character.isalnum() for character in line.paragraph.text) for line in lines)
    scanned = image_coverage >= .5 and useful_chars < 25
    header_candidates = []
    body = []
    numbers = []
    body_end = max((line.box.y1 for line in lines if line.baseline <= height * .92), default=0)
    for line in lines:
        p = line.paragraph
        if line.baseline > height * .92 and page_number_format(p.text) != "none":
            numbers.append(_page_number(line, "footer"))
        elif line.baseline < height * .083 and page_number_format(p.text) != "none":
            numbers.append(_page_number(line, "header"))
        elif line.baseline < height * .083 and len(p.text) <= 100:
            header_candidates.append(line)
        elif line.baseline > height * .92 and line.box.y0 - body_end >= 8 and len(p.text) <= 95:
            continue
        else:
            body.append(line)

    headers = result.headers_footers
    # A running head sits above the body with a clear gap, including on otherwise blank pages.
    for line in header_candidates:
        p = line.paragraph
        if ((p.font_size_pt or 0) > 15
                or (not scanned and (not body and not numbers or body and body[0].box.y0 - line.box.y1 < 8))):
            body.append(line)
            continue
        headers.default_headers.append(HeaderItemIR(
            text=p.text, font_name=p.font_name, font_size_pt=p.font_size_pt, bold=p.bold,
            alignment=p.alignment, page_no=page_no, runs=p.runs, bbox=p.bbox,
        ))

    headers.page_numbers.extend(numbers or [PageNumberIR(page_no=page_no)])
    result.page_setups.append(PageSetupIR(page_no=page_no, width_mm=pt_to_mm(width), height_mm=pt_to_mm(height)))
    body.sort(key=lambda item: (item.baseline, item.box.x0))
    _join_chapter_title(body, width)
    _mark_math_fragments(body)
    drawings = [] if scanned else page.get_drawings()
    _mark_footnotes(page, body, drawings)
    page_lines = body if scanned else _objects(page, body, image_boxes, drawings)
    body_characters = sum(sum(character.isalnum() for character in line.paragraph.text) for line in body)
    # Sparse title/transition pages are legitimate. An image-dominated page with a token OCR layer is not.
    text_page = body_characters >= 4 and not scanned
    return page_lines, scanned, text_page


def _join_chapter_title(lines, width):
    if len(lines) < 2:
        return
    anchor = lines[0]
    p = anchor.paragraph
    size = p.font_size_pt
    if size < 15 or chapter_number(p.text) is None:
        return
    previous = anchor
    while len(lines) > 1:
        next_line = lines[1]
        q = next_line.paragraph
        if (abs(q.font_size_pt - size) > .5 or q.alignment != "center"
                or not 0 < next_line.baseline - previous.baseline <= size * 2.1
                or chapter_number(q.text) is not None or heading_key(q.text)):
            break
        lines.pop(1)
        _join_lines(anchor, next_line, separator="" if HAN.search(p.text[-1:]) and HAN.match(q.text) else " ")
        p.alignment = _alignment(anchor.box, width)
        previous = next_line


def _mark_footnotes(page, lines, drawings):
    width, height = page.rect.width, page.rect.height
    for drawing in drawings:
        box = drawing["rect"] * page.rotation_matrix
        if (box.height <= 1 and width * .07 <= box.width <= width * .32
                and width * .08 <= box.x0 <= width * .2 and height * .5 <= box.y0 < height * .9):
            following = [line for line in lines if line.box.y0 >= box.y0]
            if (following and following[0].box.y0 - box.y0 <= 18
                    and all(line.paragraph.font_size_pt <= 10.5 for line in following)):
                for line in following:
                    line.paragraph.role = "footnote"


def _mark_math_fragments(lines):
    math_lines = [
        line for line in lines if any(run.font_name in _MATH_FONTS for run in line.paragraph.runs)
    ]
    for line in lines:
        p = line.paragraph
        # Equation editors can draw each numerator, operator and subscript as a separate PDF line.
        if (not p.object_kind and not HAN.search(p.text) and len(p.text) <= 35
                and not re.search(r"[A-Za-z]{5,}", p.text)
                and any(abs(line.baseline - other.baseline) <= p.font_size_pt * 1.4
                        and max(line.box.x0 - other.box.x1, other.box.x0 - line.box.x1) <= 24
                        for other in math_lines)):
            p.role = "equation_fragment"


def _heading_evidence(lines_by_page):
    headings, toc_entries = set(), set()
    for lines in lines_by_page:
        text_lines = [line for line in lines
                      if line.paragraph.text and line.paragraph.role == "other" and not line.paragraph.in_table]
        leader_lines = [i for i, line in enumerate(text_lines) if _TOC_LEADERS.search(line.paragraph.text)]
        if len(leader_lines) >= 2:
            # Long TOC titles can occupy a line by themselves before the dotted continuation.
            toc_entries.update(line.paragraph.index for line in text_lines[:leader_lines[-1] + 1]
                               if heading_key(line.paragraph.text) != "toc")
        for i, line in enumerate(text_lines):
            p = line.paragraph
            if p.font_size_pt < 11.5:
                continue
            level = heading_level(p.text)
            if level == 1 and re.match(r"^第\s*.+?\s*章\s*[:：]", p.text) and len(p.text) > 40:
                continue
            if i == 0 or p.font_size_pt >= 15 and (p.bold or p.alignment == "center"):
                headings.add(p.index)
            elif level and level > 1 and (p.bold or p.alignment == "center" or p.font_size_pt >= 13.5):
                headings.add(p.index)
    return headings, toc_entries


def _measure(result, lines_by_page):
    candidates = {}
    for setup, lines in zip(result.page_setups, lines_by_page, strict=True):
        body = [line for line in lines if line.paragraph.role == "body_text"
                and line.paragraph.section_key in _MAIN_SECTIONS and not line.paragraph.object_kind]
        _measure_spacing(lines)
        width, height = mm_to_pt(setup.width_mm), mm_to_pt(setup.height_mm)
        prose = [line for line in body if line.box.width >= width * .55]
        if len(prose) < 8 or prose[-1].baseline - prose[0].baseline < height * .45:
            continue
        main_lines = [line for line in lines if line.paragraph.section_key in _MAIN_SECTIONS
                      and line.paragraph.text and not line.paragraph.in_table
                      and line.paragraph.role not in {"footnote", "equation_fragment"}
                      and not line.paragraph.object_kind]
        opener = any(line.paragraph.role in {"section_heading", "chapter_heading"} for line in main_lines)
        if any(line.paragraph.object_kind in {"figure", "table"} and line.box.y0 < main_lines[0].box.y0
               for line in lines):
            continue
        geometry = (round(setup.width_mm), round(setup.height_mm))
        candidates.setdefault(geometry, []).append((setup, prose, main_lines, opener))

    for pages in candidates.values():
        representative = [page for page in pages if not page[3]] or pages
        bottoms = []
        usual_top = median(min(line.box.y0 for line in lines) for _, _, lines, _ in representative)
        for setup, prose, lines, _ in representative:
            top = min(line.box.y0 for line in lines)
            if top <= usual_top + 42:
                setup.top_margin_mm = pt_to_mm(top)
            setup.left_margin_mm = pt_to_mm(sorted(line.box.x0 for line in prose)[len(prose) // 10])
            right_edges = sorted(line.box.x1 for line in prose)
            setup.right_margin_mm = setup.width_mm - pt_to_mm(right_edges[-1 - len(prose) // 10])
            bottom = setup.height_mm - pt_to_mm(max(line.box.y1 for line in lines))
            if bottom <= setup.height_mm * .20:
                bottoms.append((setup, bottom))
        # Use several full text pages as witnesses, so one low annotation cannot set the limit.
        if bottoms:
            bottom_edge = sorted(bottom for _, bottom in bottoms)[len(bottoms) // 10]
            for setup, bottom in bottoms:
                if bottom <= bottom_edge + 4:
                    setup.bottom_margin_mm = bottom


def _measure_spacing(lines):
    spaced = [line for line in lines if line.paragraph.role in {"body_text", "reference_entry"}
              and not line.paragraph.object_kind]
    for previous, current in zip(spaced, spaced[1:]):
        first, second = previous.paragraph, current.paragraph
        distance = current.baseline - previous.baseline
        size = max(first.font_size_pt, second.font_size_pt)
        if (first.section_key == second.section_key and abs(previous.box.x0 - current.box.x0) < 32
                and size * .72 <= distance <= max(38, size * 3)):
            first.line_spacing_pt = distance
            first.line_spacing_rule = "estimated"


def _mark_body_paragraphs(lines, width):
    body_lines = [line for line in lines if line.paragraph.role == "body_text" and not line.paragraph.object_kind]
    if not body_lines:
        return
    right_edges = sorted(line.box.x1 for line in body_lines)
    right = right_edges[-1 - len(right_edges) // 10]
    previous = None
    anchor = None
    for line in lines:
        p = line.paragraph
        if p.role != "body_text" or p.object_kind:
            previous = None
            continue
        size = p.font_size_pt
        wraps = (previous is not None and previous.paragraph.section_key == p.section_key
                 and previous.box.width >= width * .55 and previous.box.x1 >= right - size * 1.5
                 and -size * 2.5 <= line.box.x0 - previous.box.x0 <= size * .4
                 and size * .72 <= line.baseline - previous.baseline <= size * 2.5
                 and p.alignment != "right")
        if wraps:
            p.paragraph_start_index = anchor.index
            anchor.bbox = _bbox(pymupdf.Rect(anchor.bbox) | line.box)
        else:
            anchor = p
        previous = line


def _merge_keyword_lines(lines, width):
    for index, line in enumerate(lines):
        anchor = line.paragraph
        if anchor.role not in {"keywords_cn", "keywords_en"}:
            continue
        previous = line
        for continuation in lines[index + 1:]:
            p = continuation.paragraph
            if (p.section_key != anchor.section_key or p.role != "body_text"
                    or previous.box.x1 < width * .78 or previous.box.width < width * .55
                    or not 0 < continuation.baseline - previous.baseline <= 32
                    or not -36 <= continuation.box.x0 - previous.box.x0 <= 6):
                break
            separator = "" if HAN.search(anchor.text[-1:]) and HAN.match(p.text) else " "
            anchor.text += separator + p.text
            anchor.runs.extend(p.runs)
            anchor.bbox = _bbox(pymupdf.Rect(anchor.bbox) | continuation.box)
            p.text, p.runs, p.role = "", [], "other"
            previous = continuation


def _merge_reference_lines(result, lines_by_page):
    anchor = previous = None
    right = 0
    for setup, lines in zip(result.page_setups, lines_by_page, strict=True):
        widths = [line.box.x1 for line in lines if line.paragraph.role == "reference_entry"]
        if not widths:
            anchor = previous = None
            continue
        width = mm_to_pt(setup.width_mm)
        page_right = max(widths)
        for line_index, line in enumerate(lines):
            p = line.paragraph
            if p.role != "reference_entry":
                anchor = previous = None
                continue
            if previous is not None and not _REFERENCE_START.match(p.text):
                first = anchor.paragraph
                size = p.font_size_pt
                indent = line.box.x0 >= anchor.box.x0 + 4
                same_column = abs(line.box.x0 - anchor.box.x0) <= size * 5
                full_line = previous.box.width >= width * .55 and previous.box.x1 >= right - size * 1.5
                cross_page = p.page_no == previous.paragraph.page_no + 1 and line_index == 0
                close = 0 < line.baseline - previous.baseline <= max(29, size * 2.5)
                separate_entry = not indent and (_AUTHOR_START.match(p.text)
                                                   or _TYPE_MARKER.search(p.text) and _TYPE_MARKER.search(first.text))
                if same_column and (cross_page or close) and not separate_entry and (indent or full_line):
                    # Keep the first source line as the reference's location.
                    url_wrap = full_line and re.search(r"(?:https?://|www\.)\S+$", first.text)
                    separator = "" if url_wrap or HAN.search(first.text[-1:]) and HAN.match(p.text) else " "
                    first.text += separator + p.text
                    first.runs.extend(p.runs)
                    # An annotation on the first page can only enclose lines on that page.
                    if first.page_no == p.page_no:
                        first.bbox = _bbox(pymupdf.Rect(first.bbox) | line.box)
                    p.text, p.runs, p.role = "", [], "other"
                    previous, right = line, page_right
                    continue
            anchor = previous = line
            right = page_right


def _assign_headers(result):
    headers = result.headers_footers
    pending, headers.default_headers = headers.default_headers, []
    parities = dict(pdf_page_parities(range(1, result.page_count + 1), headers.page_numbers))
    for item in pending:
        (headers.odd_headers if parities[item.page_no] else headers.even_headers).append(item)


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
                font_cache = {}
                for page in pdf:
                    lines, scanned, text_page = _add_page(page, result, font_cache)
                    page_no = page.number + 1
                    lines_by_page.append(lines)
                    if scanned:
                        scanned_pages.add(page_no)
                    if text_page:
                        text_pages.add(page_no)
                    for line in lines:
                        line.paragraph.index = len(result.paragraphs)
                        result.paragraphs.append(line.paragraph)
                headings, toc_entries = _heading_evidence(lines_by_page)
                classify_document(result, pdf_headings=headings, pdf_toc_entries=toc_entries)
                _assign_headers(result)
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
                for setup, lines in zip(result.page_setups, lines_by_page, strict=True):
                    width = mm_to_pt(setup.width_mm)
                    _merge_keyword_lines(lines, width)
                    _mark_body_paragraphs(lines, width)
                return summarize_document(result, text_page_ratio=len(text_pages) / pdf.page_count)
        except (OSError, RuntimeError, ValueError, TypeError, IndexError, KeyError) as exc:
            raise ParseError(f"无法解析 PDF 文件：{exc}") from exc


def parse_pdf(source: DocumentSource, file_name: str | None = None) -> DocumentIR:
    return PdfParser().parse(source, file_name)
