"""Extract PDF text and estimate layout from observed page geometry."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import re
from statistics import median

import pymupdf

from app.engine.utils import (
    FONT_FAMILIES, HAN, chapter_number, heading_key, heading_level, mm_to_pt, normalize_font_name, page_number_format,
    pdf_page_parities, pt_to_mm,
)
from app.parsers.base import (
    BaseParser, CAPABILITIES, COVER_LABEL, DocumentSource, FORMULA_NUMBER, ParseError, bilingual_captions,
    caption_parts, classify_document, dominant_run, pdf_caption_details, read_source, summarize_document,
)
from app.schemas.ir import DocumentIR, HeaderItemIR, LineSpacingSampleIR, PageNumberIR, PageSetupIR, ParagraphIR, TextRunIR


@dataclass
class _Line:
    box: pymupdf.Rect
    baseline: float
    paragraph: ParagraphIR
    content_x0: float | None = None
    content_x1: float | None = None
    run_baselines: list[float] = field(default_factory=list)
    glyphs: list[tuple[str, pymupdf.Rect | None]] = field(default_factory=list)
    inner_texts: list[str] = field(default_factory=list)
    columns: tuple[float, ...] = ()
    table_cells: tuple[pymupdf.Rect, ...] = ()
    subfigure_count: int = 1
    is_continuation: bool = False
    vector: bool = False
    figure_owner: "_Line | None" = field(default=None, repr=False)

    def __post_init__(self):
        self.content_x0 = self.box.x0 if self.content_x0 is None else self.content_x0
        self.content_x1 = self.box.x1 if self.content_x1 is None else self.content_x1


_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
_MAIN_SECTIONS = {"introduction", "body", "conclusion"}
_REFERENCE_START = re.compile(r"^\s*(?:[\[［]\s*\d+\s*[\]］]|\d{1,4}[)）、]|\d{1,3}\.\s+)")
_AUTHOR_START = re.compile(r"^(?:[A-Z][A-Za-z'-]+,\s+[A-Z]|[\u3400-\u9fff]{2,5}[.,．，、].*(?:\d{4}|\[[A-Z]))")
_TYPE_MARKER = re.compile(r"\[[A-Z]+(?:/[A-Z]+)?\]")
_TOC_LEADERS = re.compile(r"[.．…·]{3,}\s*(?:\d+|[IVXLCDMⅠ-ⅿ]+)?\s*$", re.I)
_SCRIPT_MARK = re.compile(r"(?:\[\s*\d+(?:\s*[-–,，]\s*\d+)*\s*\]|[①-⑳])")
_UNDERLINE = re.compile(r"[_＿]{2,}")
_FORM_SECTIONS = {"declaration", "defense_signature"}
_MATH_FONTS = {"symbol", "symbolmt", "symboltigerexpert", "mt_extra", "cambriamath"}
_MATH_FACE = re.compile(r"(?:(?:cmmi|cmsy|cmex|msam|msbm|txmi|txsy)\d*(?:identity[hv])?"
                        r"|newtxmath\w*|texgyretermes(?:x)?math\w*|latinmodernmath\w*)$")
_LATEX_ROMAN_FACE = re.compile(r"(?:cmr|lmr)\d*(?:identity[hv])?$")
_REFERENCE_LABEL = re.compile(r"[\[［]\s*\d+\s*[\]］]")
_NONWHITE_SAMPLE = bytes(int(value < 245) for value in range(256))
_SENTENCE_END = re.compile(r"[。！？!?；;.]\s*[”’」』）)]*$")
_PROSE_SENTENCE_END = re.compile(r"[。．.!?！？][”’」』）)\s]*$")
_FIGURE_SIDE_TOP_TOLERANCE = 30
_NEW_PARAGRAPH = re.compile(r"^(?:此外|其次|综上|总之|另一方面|本文|本节|Moreover\b|In conclusion\b)", re.I)
_LIST_START = re.compile(r"^(?:[（(][一二三四五六七八九十\d]+[）)]|[一二三四五六七八九十]+、|\d+[.)、]\s*|[•●▪])")
_SIGNATURE_LABEL = re.compile(r"[^。；：:_＿]{0,28}?(?:签\s*名|签\s*字)[）)]?\s*[:：]?")
_ALGORITHM_TITLE = re.compile(r"^(?:算法|Algorithm)\s*[\dA-Za-z.-]+", re.I)
_ALGORITHM_STEP = re.compile(r"^(?:输入|输出|(?:Input|Output)\b|\d+\s*[:：])", re.I)


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


def _alignment(box, width, *, center=None, tolerance=None):
    center = width / 2 if center is None else center
    tolerance = max(7, width * .017) if tolerance is None else tolerance
    middle = (box.x0 + box.x1) / 2
    if abs(middle - center) <= tolerance or (
        abs(center - width / 2) <= width * .05 and abs(middle - width / 2) <= tolerance
    ):
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
    runs = [run for run in paragraph.runs if not run.is_script] or paragraph.runs
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
    anchor.content_x0 = min(anchor.content_x0, line.content_x0)
    anchor.content_x1 = max(anchor.content_x1, line.content_x1)
    anchor.glyphs.extend((char, None) for char in separator)
    anchor.glyphs.extend(line.glyphs)
    anchor.run_baselines.extend(line.run_baselines)
    first.bbox = _bbox(anchor.box)
    _set_line_style(first)


def _span_box(boxes):
    bounds = pymupdf.Rect(boxes[0])
    for box in boxes[1:]:
        bounds |= box
    return bounds


def _flag_scripts(line):
    p = line.paragraph
    if len(p.runs) < 2:
        return
    main = max((i for i, run in enumerate(p.runs) if not run.is_script and not _SCRIPT_MARK.fullmatch(run.text.strip())),
               key=lambda i: p.runs[i].font_size_pt, default=0)
    main_size, baseline = p.runs[main].font_size_pt, line.run_baselines[main]
    for run, y in zip(p.runs, line.run_baselines, strict=True):
        small_shifted = run.font_size_pt <= main_size * .78 and abs(y - baseline) >= main_size * .10
        run.is_script |= small_shifted or bool(_SCRIPT_MARK.fullmatch(run.text.strip()))
    line.baseline = baseline
    _set_line_style(p)


def _math_font(name):
    return name in _MATH_FONTS or bool(_MATH_FACE.fullmatch((name or "").replace("_", "")))


def _lines(page, aliases=None):
    width = page.rect.width
    # MuPDF text/graphics coordinates are in the unrotated page coordinate system.
    rotation = page.rotation_matrix
    strokes = _stroke_origins(page)
    fonts = {}
    result = []
    blocks = page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES)["blocks"]
    for block in blocks:
        for line in block.get("lines", ()):
            runs, glyphs, baselines = [], [], []
            for span in line["spans"]:
                characters = span["chars"]
                text = "".join(char["c"] for char in characters)
                span_glyphs = [(char["c"], pymupdf.Rect(char["bbox"]) * rotation if not char["c"].isspace() else None)
                               for char in characters]
                glyphs.extend(span_glyphs)
                if not text.strip():
                    if runs:
                        runs[-1].text += text
                    continue
                name = _SUBSET_PREFIX.sub("", span["font"])
                if name not in fonts:
                    fonts[name] = (aliases or {}).get(name) or normalize_font_name(name)
                font = fonts[name]
                key = (span["font"], *(round(value, 1) for value in span["origin"]))
                bold = bool(span["flags"] & pymupdf.TEXT_FONT_BOLD
                            or re.search(r"bold|heavy|black|demi", span["font"], re.I) or key in strokes)
                run_boxes = [box for _, box in span_glyphs if box is not None and not box.is_empty]
                runs.append(TextRunIR(
                    text=text, font_name=font, font_name_latin=font if re.search(r"[A-Za-z]", text) else None,
                    font_size_pt=span["size"], bold=bold,
                    is_script=_math_font(font) or bool(span["flags"] & pymupdf.TEXT_FONT_SUPERSCRIPT),
                    page_no=page.number + 1, bbox=_bbox(_span_box(run_boxes)) if run_boxes else None,
                ))
                baselines.append((pymupdf.Point(span["origin"]) * rotation).y)
            boxes = [box for _, box in glyphs if box is not None and not box.is_empty]
            if not runs or not boxes:
                continue
            box = _span_box(boxes)
            trim = len(glyphs)
            first = next(i for i, (char, _) in enumerate(glyphs) if not char.isspace())
            while trim and glyphs[trim - 1][0].isspace():
                trim -= 1
            glyphs = glyphs[first:trim]
            text = "".join(char for char, _ in glyphs)
            number = FORMULA_NUMBER.search(text)
            formula = number and re.search(r"[=∑∫≈≤≥]", text[:number.start()])
            paragraph = ParagraphIR(
                index=0, page_no=page.number + 1, text=text, bbox=_bbox(box), alignment=_alignment(box, width),
                runs=runs, object_kind="formula" if formula else None,
            )
            _set_line_style(paragraph)
            unit = _Line(box, baselines[0], paragraph, run_baselines=baselines, glyphs=glyphs)
            _flag_scripts(unit)
            result.append(unit)
    return _join_line_fragments(result, width)


def _rows(lines, tolerance):
    rows = []
    for line in sorted(lines, key=lambda item: item.baseline):
        if rows and line.baseline - rows[-1][0].baseline <= tolerance:
            rows[-1].append(line)
        else:
            rows.append([line])
    return [sorted(row, key=lambda item: item.content_x0) for row in rows]


def _reading_order(lines):
    return [line for row in _rows(lines, tolerance=4.0) for line in row]


def _join_line_fragments(lines, width):
    result = []
    for row in _rows(lines, 1):
        previous = None
        for line in row:
            if previous:
                first, second = previous.paragraph, line.paragraph
                gap = line.content_x0 - previous.content_x1
                if first.text == second.text and abs(line.content_x0 - previous.content_x0) < 1:
                    continue
                if -1 <= gap <= max(first.font_size_pt, second.font_size_pt) * 1.05 and not (
                    first.object_kind or second.object_kind
                ):
                    _join_lines(previous, line, separator=" " if gap > 1 else "")
                    previous.paragraph.alignment = _alignment(previous.box, width)
                    continue
            result.append(line)
            previous = line

    # MuPDF can emit a raised or lowered inline run in its own line/block.
    removed = set()
    for line in result:
        p = line.paragraph
        if p.object_kind or len(p.text) > 15 or p.font_size_pt > 10.5 or p.text[0] in "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳":
            continue
        candidates = [other for other in result if (
            other is not line and not other.paragraph.object_kind and len(other.paragraph.text) >= 4
            and p.font_size_pt <= other.paragraph.font_size_pt * .78
            and 1.3 <= abs(other.baseline - line.baseline) <= other.paragraph.font_size_pt * .70
            and min(abs(other.content_x0 - line.content_x1), abs(other.content_x1 - line.content_x0)) <= 9
        )]
        if not candidates:
            continue
        anchor = min(candidates, key=lambda other: min(abs(other.content_x0 - line.content_x1),
                                                       abs(other.content_x1 - line.content_x0)))
        for run in p.runs:
            run.is_script = True
        if line.content_x0 < anchor.content_x0:
            anchor.paragraph.runs[:0] = p.runs
            anchor.paragraph.text = p.text + anchor.paragraph.text
            anchor.glyphs[:0] = line.glyphs
            anchor.run_baselines[:0] = line.run_baselines
            anchor.box |= line.box
            anchor.content_x0 = min(anchor.content_x0, line.content_x0)
            anchor.paragraph.bbox = _bbox(anchor.box)
        else:
            _join_lines(anchor, line, separator="")
        removed.add(id(line))
    return _reading_order(line for line in result if id(line) not in removed)


def _frame(lines, width, height):
    prose = [line for line in lines if (width * .55 <= line.content_x1 - line.content_x0 <= width * .88
             and height * .094 <= line.baseline <= height * .90 and 10.5 <= line.paragraph.font_size_pt <= 16
             and not caption_parts(line.paragraph.text, pdf=True))]
    if not prose:
        return (width * .14, width * .86), width / 2
    left = sorted(line.content_x0 for line in prose)
    right = sorted(line.content_x1 for line in prose)
    offset = len(prose) // 10
    frame = (left[offset], right[-1 - offset])
    return frame, sum(frame) / 2 if len(prose) >= 2 else width / 2


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
        if box.height <= 2:
            boxes = [box]
        else:
            boxes = [rect * page.rotation_matrix for item in path["items"] if (rect := _rule_rectangle(item)) is not None]
        for box in boxes:
            if box.height <= 2 and box.width >= 4:
                rows[round((box.y0 + box.y1) / 2)].append(box)
    # Some producers emit a separate filled strip for each cell in the same horizontal rule.
    return [
        (y, min(box.x0 for box in boxes), max(box.x1 for box in boxes))
        for y, boxes in sorted(rows.items())
        if sum(box.width for box in boxes) >= page.rect.width * .32
    ]


def _algorithm_blocks(lines, rules):
    blocks = []
    for index, (top, left, right) in enumerate(rules):
        if any(box.y0 <= top <= box.y1 and box.x0 <= left + 9 and right <= box.x1 + 9 for box in blocks):
            continue
        in_columns = [line for line in lines if line.baseline > top and line.paragraph.text
                      and left - 5 <= line.box.x0 and line.box.x1 <= right + 5]
        if not in_columns:
            continue
        title = in_columns[0]
        if title.baseline - top > 32 or not _ALGORITHM_TITLE.match(title.paragraph.text):
            continue
        end, contents = None, []
        for bottom, x0, x1 in rules[index + 1:]:
            if max(abs(x0 - left), abs(x1 - right)) > 9 or bottom <= title.baseline:
                continue
            content = [line for line in in_columns[1:] if line.baseline < bottom
                       and (end is None or line.baseline > end)]
            if any(_ALGORITHM_TITLE.match(line.paragraph.text) or caption_parts(line.paragraph.text, pdf=True)
                   for line in content):
                break
            has_steps = any(_ALGORITHM_STEP.match(line.paragraph.text) for line in content)
            if end is not None:
                if not has_steps or min(line.baseline for line in content) - end > 30:
                    break
            elif not has_steps:
                continue
            end = bottom
            contents.extend(content)
        if end is not None:
            blocks.append(pymupdf.Rect(left, top, right, end))
            for line in (title, *contents):
                line.paragraph.in_table = True
    return blocks


def _captioned_ruled_tables(lines, rules):
    captions = [
        line for line in lines if (parts := caption_parts(line.paragraph.text, pdf=True)) and parts[0] == "table"
    ]
    groups = []
    for caption in captions:
        if (groups and 0 <= caption.baseline - groups[-1][-1].baseline <= 36
                and bilingual_captions(groups[-1][-1].paragraph.text, caption.paragraph.text, pdf=True)):
            groups[-1].append(caption)
        else:
            groups.append([caption])
    used = []
    for index, group in enumerate(groups):
        above_edge, below_edge = group[0].box.y0, group[-1].baseline
        lower_limit = groups[index + 1][0].box.y0 if index + 1 < len(groups) else float("inf")
        upper_limit = groups[index - 1][-1].box.y1 if index > 0 else float("-inf")
        below = [rule for rule in rules if below_edge < rule[0] < lower_limit]
        above = [rule for rule in reversed(rules) if upper_limit < rule[0] <= above_edge]
        for available, edge in ((below, below_edge), (above, above_edge)):
            available = [(y, x0, x1) for y, x0, x1 in available if not any(
                box.y0 <= y <= box.y1 and max(abs(x0 - box.x0), abs(x1 - box.x1)) <= 9 for box in used
            )]
            if len(available) < 2 or abs(available[0][0] - edge) > 55:
                continue
            boundary, left, right = available[0]
            matching = [y for y, x0, x1 in available if max(abs(x0 - left), abs(x1 - right)) <= 9]
            # An empty band between widely spaced rules separates same-width tables.
            for gap_index, (a, b) in enumerate(zip(matching, matching[1:]), 1):
                if abs(b - a) >= 28 and not any(
                    min(a, b) < line.baseline < max(a, b) and left <= line.box.x0 < right and line.paragraph.text
                    for line in lines
                ):
                    matching = matching[:gap_index]
                    break
            if len(matching) < 2:
                continue
            top, bottom = sorted((boundary, matching[-1]))
            box = pymupdf.Rect(left, top, right, bottom)
            columns = _ruled_table_columns(lines, box)
            if len(columns) >= 2:
                used.append(box)
                yield box, columns
                break


def _ruled_table_columns(lines, box):
    inside = [line for line in lines if (box & line.box).get_area() >= line.box.get_area() * .8]
    rows = _rows(inside, tolerance=4.5)

    def starts(row_lines):
        intervals = sorted((line.content_x0, line.content_x1) for line in row_lines)
        columns = []
        edge = float("-inf")
        for x0, x1 in intervals:
            if x0 - edge >= 7:
                columns.append(x0)
            edge = max(edge, x1)
        return tuple(columns)

    columns = starts(line for row in rows for line in row)
    if len(columns) >= 2:
        return columns
    # A spanning heading may obscure the inter-column whitespace.
    repeated = Counter(tuple(round(x / 5) * 5 for x in starts(row)) for row in rows)
    return next((cols for cols, count in repeated.most_common() if len(cols) >= 2 and count >= 2), ())


def _object_line(page_no, kind, box, width, *, text="", has_image=False):
    return _Line(box, box.y0, ParagraphIR(
        index=0, page_no=page_no, text=text, bbox=_bbox(box), has_image=has_image, object_kind=kind,
        alignment=_alignment(box, width),
    ))


def _form_glyphs(row):
    glyphs, origins = [], []
    for line in row:
        if glyphs and glyphs[-1][1] and line.content_x0 - glyphs[-1][1].x1 > 2:
            glyphs.append((" ", None))
            origins.append(None)
        glyphs.extend(line.glyphs)
        origins.extend([id(line)] * len(line.glyphs))
    return glyphs, origins


def _rule_rectangle(item):
    if item[0] == "l":
        start, end = item[1:]
        return pymupdf.Rect(start.x, start.y, end.x, end.y).normalize()
    if item[0] == "re":
        return item[1]
    return None


def _form_rules(page, drawings):
    for path in drawings:
        for item in path["items"]:
            box = _rule_rectangle(item)
            if box is None:
                continue
            box = box * page.rotation_matrix
            if box.height <= 2.5 and 18 <= box.width <= page.rect.width * .75:
                yield box


def _signature_slots(text, glyphs, rules, baseline):
    if heading_key(text):
        return []
    if _UNDERLINE.fullmatch(text.replace(" ", "")):
        return [("signature", 0, 0)]
    gaps = []
    previous = None
    for index, (_, box) in enumerate(glyphs):
        if box is None:
            continue
        if previous is not None and box.x0 - previous.x1 >= 18:
            gaps.append(index)
        previous = box
    slots = []
    start = 0
    for end in [*gaps, len(text)]:
        sign = _SIGNATURE_LABEL.match(text, start, end)
        if sign:
            boxes = [box for _, box in glyphs[start:sign.end()] if box is not None]
            if boxes and (re.search(r"[:：]", sign[0]) or _UNDERLINE.search(text[sign.end():end])
                          or any(-2 <= rule.y0 - baseline <= 8 and boxes[0].x0 - 5 <= rule.x0 <= boxes[-1].x1 + 95
                                 for rule in rules)):
                slots.append(("signature", start, sign.end()))
        if sign or slots:
            start = end
    return slots


def _form_rows(lines, image_boxes, drawings, page, *, signature_page):
    width = page.rect.width
    rules = list(_form_rules(page, drawings))
    claimed = set()
    consumed = set()
    rows = _rows(lines, 4.5)
    label_fragments = set()
    if not signature_page:
        for row in rows:
            glyphs, origins = _form_glyphs(row)
            text = "".join(char for char, _ in glyphs)
            for match in COVER_LABEL.finditer(text):
                label_fragments.update(origins[match.start():match.end()])
    result = []
    for row in rows:
        row = [line for line in row if id(line) not in consumed]
        glyphs, _ = _form_glyphs(row)
        if not glyphs:
            result.extend(row)
            continue
        text = "".join(char for char, _ in glyphs)
        matches = _signature_slots(text, glyphs, rules, row[0].baseline) if signature_page else [
            (match.lastgroup, match.start(), match.end()) for match in COVER_LABEL.finditer(text)
        ]
        if not matches or matches[0][1] > 0:
            result.extend(row)
            continue

        for index, (label, start, value_start) in enumerate(matches):
            end = matches[index + 1][1] if index + 1 < len(matches) else len(text)
            boxes = [box for _, box in glyphs[start:end] if box is not None and not box.is_empty]
            if not boxes:
                continue
            box = _span_box(boxes)
            next_left = next((rect.x0 for _, rect in glyphs[end:] if rect is not None), width)
            supports = [rule for rule in rules if (
                -2 <= rule.y0 - row[0].baseline <= 8
                and rule.x0 > box.x0 - 5 and rule.x1 <= next_left + 3 and rule.x0 <= box.x1 + 95
            )]
            raw = text[start:end].strip()
            value = _UNDERLINE.sub("", text[value_start:end]).strip(" \t_＿：:")
            underline = bool(supports or _UNDERLINE.search(raw))
            continuation = None
            if not value and supports:
                above = [item for item in lines if id(item) not in consumed and (
                    4.5 < row[0].baseline - item.baseline <= 15 and id(item) not in label_fragments
                    and any(rule.x0 - 5 <= item.content_x0 <= item.content_x1 <= rule.x1 + 5 for rule in supports)
                )]
                if above:
                    value = " ".join(item.paragraph.text for item in above)
                    raw += " " + value
                    consumed.update(id(item) for item in above)
                    box |= _span_box([item.box for item in above])
            if not value and not signature_page and not _UNDERLINE.search(raw):
                below = [item for item in lines if id(item) not in consumed and id(item) not in label_fragments
                         and 4.5 < item.baseline - row[0].baseline <= 32
                         and box.x0 - 5 <= item.content_x0 <= min(next_left - 2, box.x1 + 12)
                         and item.content_x1 <= next_left + 3
                         and not (heading_key(item.paragraph.text) or caption_parts(item.paragraph.text, pdf=True)
                                  or item.paragraph.object_kind)]
                if below:
                    continuation = min(below, key=lambda item: (item.baseline, abs(item.content_x0 - box.x0)))
                    value = continuation.paragraph.text
                    raw += " " + value
                    consumed.add(id(continuation))
                    box |= continuation.box
            for rule in supports:
                box.include_point((rule.x0, rule.y0))
                box.include_point((rule.x1, rule.y1))
            images = [i for i, image in enumerate(image_boxes) if (
                signature_page and i not in claimed and image.height <= 65 and image.width <= width * .40
                and row[0].baseline - 45 <= image.y1 <= row[0].baseline + 8
                and image.x0 >= box.x0 - 25 and image.x1 <= next_left + 3 and image.x0 <= box.x1 + 45
                and (not supports or any(
                    rule.x0 - 3 <= (image.x0 + image.x1) / 2 <= rule.x1 + 3
                    and min(image.x1, rule.x1) - max(image.x0, rule.x0) >= image.width * .5
                    for rule in supports
                ))
            )]
            claimed.update(images)
            for image_index in images:
                box |= image_boxes[image_index]
            style = (continuation or max((item for item in row if item.content_x0 <= box.x1
                                          and item.content_x1 >= box.x0),
                                         key=lambda item: len(item.paragraph.text))).paragraph
            paragraph = ParagraphIR(
                index=0, page_no=page.number + 1, text=raw, bbox=_bbox(box), unit_kind="underline_row",
                role="underline_row", field_label=label, field_value=value, has_underline=underline or bool(images),
                has_signature_image=bool(images), alignment=_alignment(box, width),
                font_name=style.font_name, font_size_pt=style.font_size_pt, bold=style.bold,
                runs=style.runs if label == "title_cn" else [],
            )
            if label in {"title_cn", "title_en"} and value and not underline:
                paragraph.role = "cover_title" if label == "title_cn" else "cover_title_en"
                paragraph.unit_kind = "heading"
            result.append(_Line(box, row[0].baseline, paragraph))
    return ([line for line in result if id(line) not in consumed],
            [box for i, box in enumerate(image_boxes) if i not in claimed])


def _formula_units(lines, image_boxes, page_no, width):
    labels = [line for line in lines if not line.paragraph.in_table and FORMULA_NUMBER.fullmatch(line.paragraph.text)]
    fragments = [line for line in lines if line.paragraph.role == "equation_fragment"]
    used_lines, used_images, formulas = set(), set(), []

    def nearby(a, b):
        return max(a.y0 - b.y1, b.y0 - a.y1, 0)

    for label in labels:
        images = [i for i, box in enumerate(image_boxes) if (
            i not in used_images and 8 <= box.width <= width * .68 and 4 <= box.height <= 65
            and nearby(box, label.box) <= 19 and box.x0 <= label.box.x0 + 8
        )]
        parts = [line for line in fragments if id(line) not in used_lines and nearby(line.box, label.box) <= 15]
        if not (images or parts or re.search(r"[.．—–-]", label.paragraph.text)):
            continue
        boxes = [label.box, *(image_boxes[i] for i in images), *(line.box for line in parts)]
        formulas.append(_object_line(page_no, "formula", _span_box(boxes), width,
                                     text=label.paragraph.text, has_image=bool(images)))
        used_images.update(images)
        used_lines.update(id(line) for line in [label, *parts])

    group = []
    for line in lines:
        if id(line) in used_lines:
            continue
        if line.paragraph.role == "equation_fragment":
            if group and (nearby(group[-1].box, line.box) > 12
                          or line.baseline - group[0].baseline > 39):
                formulas.append(_fragment_formula(group, page_no, width))
                group = []
            group.append(line)
            used_lines.add(id(line))
        elif group and line.baseline - group[-1].baseline > 10:
            formulas.append(_fragment_formula(group, page_no, width))
            group = []
    if group:
        formulas.append(_fragment_formula(group, page_no, width))
    return ([line for line in lines if id(line) not in used_lines] + formulas,
            [box for i, box in enumerate(image_boxes) if i not in used_images])


def _fragment_formula(lines, page_no, width):
    ordered = _reading_order(lines)
    unit = _object_line(page_no, "formula", _span_box([line.box for line in ordered]), width,
                        text=" ".join(line.paragraph.text for line in ordered))
    unit.paragraph.runs = [run for line in ordered for run in line.paragraph.runs]
    return unit


def _caption_near(box, caption, *, below, max_gap):
    gap = caption.baseline - box.y1 if below else box.y0 - caption.box.y1
    return (-12 <= gap <= max_gap
            and max(box.x0 - caption.box.x1, caption.box.x0 - box.x1, 0) <= 15)


def _prose_between(lines, start, end, width, *, exclude=None):
    return any(start < line.baseline < end and line.box.width >= width * .50
               and line.paragraph.font_size_pt > 10.5 and not line.paragraph.in_table
               and (exclude is None or not exclude.contains(line.box))
               and not caption_parts(line.paragraph.text, pdf=True) for line in lines if line.paragraph.text)


def _contains_vector_candidate(outer, inner):
    area = inner.box.get_area()
    return ((outer.vector or inner.vector) and outer.box.get_area() >= area
            and (outer.box & inner.box).get_area() >= area * .85)


def _combine_subfigures(figures, lines, width):
    captions = [(line, details[1]) for line in lines
                if not line.paragraph.in_table
                and (details := pdf_caption_details(line.paragraph.text)) and details[0] == "figure"]
    remaining = sorted(figures, key=lambda item: (item.box.y0, item.box.x0))
    combined = []
    while remaining:
        first = remaining.pop(0)
        for second in remaining[:]:
            if _contains_vector_candidate(first, second) or _contains_vector_candidate(second, first):
                continue
            a, b = first.box, second.box
            vertical = min(a.y1, b.y1) - max(a.y0, b.y0)
            gap = max(a.x0 - b.x1, b.x0 - a.x1)
            upper, lower = sorted((a, b), key=lambda box: box.y0)
            vertical_gap = lower.y0 - upper.y1
            separates = (_prose_between(lines, upper.y1, lower.y0, width)
                         or any(upper.y1 - 10 <= caption.baseline < lower.y0 for caption, _ in captions))
            sliced = (max(abs(a.x0 - b.x0), abs(a.x1 - b.x1)) <= 8 and -3 <= vertical_gap <= 5
                      and not separates)
            horizontal = vertical >= min(a.height, b.height) * .58 and -4 <= gap <= width * .17
            area = a | b
            labels = {number for caption, number in captions if (
                _caption_near(area, caption, below=True, max_gap=75)
                and area.x0 - 12 <= (caption.box.x0 + caption.box.x1) / 2 <= area.x1 + 12
            )}
            vector_blocks = (
                first.vector and second.vector and gap <= width * .10 and vertical_gap <= 105
                and not separates
            )
            if not (sliced or (len(labels) == 1 and (horizontal or vector_blocks))):
                continue
            first.box = area
            first.content_x0, first.content_x1 = area.x0, area.x1
            first.paragraph.bbox = _bbox(area)
            first.subfigure_count += second.subfigure_count
            first.vector = first.vector and second.vector
            remaining.remove(second)
        combined.append(first)
    kept = []
    for figure in sorted(combined, key=lambda item: item.box.get_area(), reverse=True):
        if not any(_contains_vector_candidate(parent, figure) for parent in kept):
            kept.append(figure)
    return _reading_order(kept)


def _is_drawing_container(page, box, paths, lines, tables, images):
    """Recognize enclosing strokes on a page layout, including broken-up PDF paths."""
    contains_table = any((box & table.box).get_area() >= table.box.get_area() * .5 for table in tables)
    if not contains_table and (box.width < page.rect.width * .35 or box.height < page.rect.height * .15):
        return False
    edges = [0.0] * 4
    for path in paths:
        if path["type"] != "s" and not (path["type"] == "fs" and min(path.get("fill") or (0,)) >= .98):
            continue
        for item in path["items"]:
            if item[0] == "re":
                rect = item[1] * page.rotation_matrix
                if all(abs(a - b) <= 3 for a, b in zip(rect, box)):
                    edges = [box.width, box.width, box.height, box.height]
                    break
            if item[0] != "l":
                continue
            start, end = (point * page.rotation_matrix for point in item[1:])
            if abs(start.y - end.y) <= 2:
                extent = max(0, min(max(start.x, end.x), box.x1) - max(min(start.x, end.x), box.x0))
                for index, y in enumerate((box.y0, box.y1)):
                    if abs(start.y - y) <= 3:
                        edges[index] += extent
            if abs(start.x - end.x) <= 2:
                extent = max(0, min(max(start.y, end.y), box.y1) - max(min(start.y, end.y), box.y0))
                for index, x in enumerate((box.x0, box.x1), start=2):
                    if abs(start.x - x) <= 3:
                        edges[index] += extent
        if all(edge >= extent * .62 for edge, extent in zip(edges, (box.width, box.width, box.height, box.height))):
            break
    else:
        return False

    if contains_table:
        return True
    if any((box & image.box).get_area() >= image.box.get_area() * .9
           and image.box.get_area() <= box.get_area() * .75 for image in images):
        return True
    prose = [line for line in lines if not line.paragraph.object_kind and len(line.paragraph.text) >= 12
             and (line.box & box).get_area() >= line.box.get_area() * .75]
    if sum(line.box.width >= box.width * .38 for line in prose) >= 4:
        return True
    # A form can be laid out as several narrow fields on each row.
    return sum(len(row) >= 2 for row in _rows(prose, 4.5)) >= 4


def _table_continues(box, height, previous, captions):
    return (box.y0 <= height * .26 and not any(_caption_near(box, line, below=False, max_gap=65) for line in captions)
            and any(max(abs(box.x0 - other.box.x0), abs(box.x1 - other.box.x1)) <= 10 for other in previous))


def _grid_is_table(page, unit, paths, clusters, lines, table_captions, figure_captions):
    box = unit.box
    anchored = any(_caption_near(box, line, below=False, max_gap=65) for line in table_captions)
    if anchored:
        return True
    if any(_caption_near(box, line, below=True, max_gap=58) for line in figure_captions):
        return False
    contents = [line for line in lines if box.contains((line.box.tl + line.box.br) * .5)]
    filled = [line.box for line in contents if len(re.sub(r"[^\w]|_", "", line.paragraph.text)) >= 2]
    populated = sum(any((cell & text).get_area() >= text.get_area() * .5 for text in filled)
                    for cell in unit.table_cells)
    if populated * 2 < len(unit.table_cells):
        if box.width < page.rect.width * .55:
            return False
        # Wide questionnaires can have one phrase and several single-digit cells in each row.
        phrases = [line.box for line in contents if len(HAN.findall(line.paragraph.text)) >= 4
                   or len(re.findall(r"[A-Za-z]{2,}", line.paragraph.text)) >= 3]
        phrase_rows = {round(cell.y0) for cell in unit.table_cells
                       if any((cell & text).get_area() >= text.get_area() * .5 for text in phrases)}
        if len(phrase_rows) < 2:
            return False
    graphic_points = []
    for path in paths:
        for item in path["items"]:
            if item[0] not in {"l", "c"}:
                continue
            points = [point * page.rotation_matrix for point in item[1:]]
            xs, ys = [p.x for p in points], [p.y for p in points]
            if max(xs) - min(xs) >= 2 and max(ys) - min(ys) >= 2:
                graphic_points.append(pymupdf.Point(sum(xs) / len(xs), sum(ys) / len(ys)))
    if any(box.contains(point) for point in graphic_points):
        return False
    return not any(
        cluster.get_area() >= box.get_area() * 1.55
        and (cluster & box).get_area() >= box.get_area() * .9
        and (any(cluster.contains(point) for point in graphic_points)
             or not _is_drawing_container(page, cluster, paths, lines, [unit], []))
        for cluster in clusters
    )


def _inline_formula(box, lines, figure_captions):
    if (box.height > 36 or box.width > 120
            or any(_caption_near(box, caption, below=True, max_gap=42) for caption in figure_captions)):
        return False
    neighbors = [line for line in lines if len(line.paragraph.text) >= 5 and not line.paragraph.object_kind
                 and not line.paragraph.in_table
                 and line.paragraph.font_size_pt >= 10.5 and not caption_parts(line.paragraph.text, pdf=True)]
    if any(box.y0 - 4 <= line.baseline <= box.y1 + 5
           and 0 <= max(line.box.x0 - box.x1, box.x0 - line.box.x1) <= line.paragraph.font_size_pt * 1.7
           for line in neighbors):
        return True
    above = any(0 <= box.y0 - line.baseline <= 35 and line.box.x0 - 8 <= box.x0 <= line.box.x1
                for line in neighbors)
    below = any(0 <= line.baseline - box.y1 <= 35 and line.box.x0 - 8 <= box.x0 <= line.box.x1
                for line in neighbors)
    return above and below


def _detect_tables(page, lines, paths, clusters, previous_tables):
    # Recognize table cells before grouping equations; data cells may use LaTeX math fonts.
    width, height = page.rect.width, page.rect.height
    page_no = page.number + 1
    table_captions, figure_captions = [], []
    for line in lines:
        if parts := caption_parts(line.paragraph.text, pdf=True):
            (table_captions if parts[0] == "table" else figure_captions).append(line)
    tables = []
    algorithms = []
    if paths:
        rules = [path for path in paths if path["type"] != "f"
                 or min(path["rect"].width, path["rect"].height) <= 2]
        horizontal_rules = _horizontal_rules(page, rules)
        algorithms = _algorithm_blocks(lines, horizontal_rules)
        horizontal_rules = [(y, left, right) for y, left, right in horizontal_rules
                            if not any(box.y0 <= y <= box.y1 and box.x0 <= left + 9 and right <= box.x1 + 9
                                       for box in algorithms)]
        if rules:
            for table in page.find_tables(paths=rules, use_layout=False).tables:
                if table.col_count >= 2:
                    box = pymupdf.Rect(table.bbox) * page.rotation_matrix
                    if _inside_algorithms(box, algorithms):
                        continue
                    continued = _table_continues(box, height, previous_tables, table_captions)
                    if table.row_count < 2 and not continued:
                        continue
                    unit = _object_line(page_no, "table", box, width)
                    unit.table_cells = tuple(pymupdf.Rect(cell) * page.rotation_matrix
                                             for cell in table.cells if cell)
                    unit.columns = tuple(sorted({round(cell.x0) for cell in unit.table_cells}))
                    if continued or _grid_is_table(page, unit, paths, clusters, lines, table_captions, figure_captions):
                        unit.is_continuation = continued
                        tables.append(unit)
        for box, columns in _captioned_ruled_tables(lines, horizontal_rules):
            if not any((other.box & box).get_area() >= box.get_area() * .5 for other in tables):
                unit = _object_line(page_no, "table", box, width)
                unit.columns = columns
                tables.append(unit)
    for line in lines:
        area = line.box.get_area()
        if not area or line.paragraph.object_kind or line.paragraph.unit_kind == "underline_row":
            continue
        caption = caption_parts(line.paragraph.text, pdf=True)
        table = next((table for table in tables if (
            (table.box.contains(line.box) and (
                table.box.y0 + 1 < line.baseline < table.box.y1 - 1
                or any(cell.contains(line.box) for cell in table.table_cells)
            ))
            or (not caption and (table.box & line.box).get_area() >= area * .75)
        )), None)
        if table:
            line.paragraph.in_table = True
            table.inner_texts.append(line.paragraph.text)

    return tables, algorithms


def _inside_algorithms(box, algorithms):
    return any((box & block).get_area() >= box.get_area() * .85 for block in algorithms)


def _side_label_gap(line, figure):
    p = line.paragraph
    box = figure.box
    gap = max(box.x0 - line.box.x1, line.box.x0 - box.x1)
    if (0 <= gap <= 75 and box.y0 - _FIGURE_SIDE_TOP_TOLERANCE <= line.baseline <= box.y1 + 15
            and p.role == "other" and p.font_size_pt <= 10.5 and line.box.width < 150
            and not _SENTENCE_END.search(p.text) and not heading_key(p.text)):
        return gap
    return None


def _objects(page, lines, image_boxes, paths, clusters, tables, algorithms):
    width, height = page.rect.width, page.rect.height
    page_no = page.number + 1
    figures = []
    figure_captions = [line for line in lines if not line.paragraph.in_table
                       and (parts := caption_parts(line.paragraph.text, pdf=True)) and parts[0] == "figure"]
    inline = []
    for box in image_boxes:
        if not (22 <= box.width < width * .98 and 22 <= box.height < height * .9 and _body_graphics(box, width, height)):
            continue
        if any((other.box & box).get_area() >= max(other.box.get_area(), box.get_area()) * .85 for other in figures):
            continue
        if _inline_formula(box, lines, figure_captions):
            inline.append(_object_line(page_no, "formula", box, width, has_image=True))
            continue
        figures.append(_object_line(page_no, "figure", box, width, has_image=True))
    formulas = [line.box for line in lines if line.paragraph.object_kind == "formula"]
    for box in clusters:
        if (box.width >= 28 and box.height >= 28 and _body_graphics(box, width, height)
                and not _inside_algorithms(box, algorithms)
                and not any((image & box).get_area() >= box.get_area() * .8 for image in image_boxes)
                and not any((formula & box).get_area() >= box.get_area() * .75 for formula in formulas)
                and not any((table.box & box).get_area() >= box.get_area() * .5 for table in tables)
                and not _is_drawing_container(page, box, paths, lines, tables,
                                              [figure for figure in figures if not figure.vector])):
            unit = _object_line(page_no, "figure", box, width, has_image=True)
            unit.vector = True
            figures.append(unit)
    possible_inner_text = [line for line in lines if line.box.get_area() and not (
        line.paragraph.in_table or line.paragraph.object_kind or line.paragraph.unit_kind == "underline_row"
        or caption_parts(line.paragraph.text, pdf=True)
    )]
    figures = _combine_subfigures(figures, lines, width)
    prose_nearby = {}
    for line in possible_inner_text:
        area = line.box.get_area()
        p = line.paragraph
        figure = next((fig for fig in figures if (
            (pymupdf.Rect(fig.box.x0 - 3, fig.box.y0 - 3, fig.box.x1 + 3, fig.box.y1 + 3) & line.box)
            .get_area() >= area * .5
            or fig.vector and p.font_size_pt <= 10.5 and len(p.text) <= 36 and not _SENTENCE_END.search(p.text)
            and (pymupdf.Rect(fig.box.x0 - 14, fig.box.y0 - 14, fig.box.x1 + 14, fig.box.y1 + 14) & line.box)
            .get_area() >= area * .65
        )), None)
        if figure is None:
            candidates = []
            for candidate in figures:
                gap = _side_label_gap(line, candidate)
                if gap is None:
                    continue
                key = id(candidate)
                box = candidate.box
                if key not in prose_nearby:
                    prose_nearby[key] = _prose_between(lines, box.y0 - _FIGURE_SIDE_TOP_TOLERANCE,
                                                      box.y1 + 15, width, exclude=box)
                if not prose_nearby[key]:
                    candidates.append((gap, abs(line.baseline - (box.y0 + box.y1) / 2), candidate))
            if candidates:
                figure = min(candidates, key=lambda item: item[:2])[2]
        if figure:
            line.paragraph.in_figure = True
            line.figure_owner = figure
    return _reading_order(lines + tables + figures + inline)


def _page_number(line, position):
    p = line.paragraph
    return PageNumberIR(
        page_no=p.page_no, num_format=page_number_format(p.text), raw_text=p.text,
        position=position, alignment=p.alignment, bbox=p.bbox,
    )


def _image_union_area(boxes, page_rect):
    events = defaultdict(list)
    for box in boxes:
        clipped = box & page_rect
        if not clipped.is_empty:
            interval = (clipped.y0, clipped.y1)
            events[clipped.x0].append((interval, 1))
            events[clipped.x1].append((interval, -1))
    active = defaultdict(int)
    previous_x = area = 0.0
    for x, changes in sorted(events.items()):
        if active:
            covered = end = 0.0
            for y0, y1 in sorted(active):
                covered += max(0, y1 - max(y0, end))
                end = max(end, y1)
            area += (x - previous_x) * covered
        for interval, delta in changes:
            active[interval] += delta
            if not active[interval]:
                del active[interval]
        previous_x = x
    return area


def _is_visually_blank(page):
    pixmap = page.get_pixmap(dpi=36, colorspace=pymupdf.csGRAY, alpha=False, annots=False)
    samples = pixmap.samples
    return samples.translate(_NONWHITE_SAMPLE).count(b"\x01") <= len(samples) * .0003


def _add_page(page, result, font_cache, previous_tables):
    width, height = page.rect.width, page.rect.height
    page_no = page.number + 1
    rotation = page.rotation_matrix
    lines = _lines(page, _font_aliases(page, font_cache))
    image_boxes = [pymupdf.Rect(image["bbox"]) * rotation for image in page.get_image_info()]
    image_coverage = _image_union_area(image_boxes, page.rect) / page.rect.get_area()
    useful_chars = sum(sum(character.isalnum() for character in line.paragraph.text) for line in lines)
    scanned = image_coverage >= .5 and useful_chars < 25
    blank = (not useful_chars or scanned) and _is_visually_blank(page)
    scanned = scanned and not blank
    (left, right), center = _frame(lines, width, height)
    for line in lines:
        p = line.paragraph
        number = page_number_format(p.text) != "none"
        band = line.baseline > height * .92 or line.baseline < height * .083
        tolerance = max(15, width * .025) if number and band else (
            max(15, width * .025) if page_no == 1 and p.font_size_pt >= 16
            else max(12, width * .020) if caption_parts(p.text, pdf=True) else None
        )
        p.alignment = _alignment(line.box, width, center=center, tolerance=tolerance)
        if number and band and _alignment(line.box, width, tolerance=tolerance) == "center":
            # Running numbers may use the physical page center on inset or table-heavy pages.
            p.alignment = "center"
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
    result.page_setups.append(PageSetupIR(page_no=page_no, width_mm=pt_to_mm(width), height_mm=pt_to_mm(height),
                                          is_blank=blank))
    if blank:
        return [], False, False, (left, right)
    body = _reading_order(body)
    if scanned:
        placeholder = ParagraphIR(index=0, page_no=page_no, page_end=page_no, text="", bbox=_bbox(page.rect),
                                  role="scanned_page", unit_kind="scanned_page", has_image=True)
        return [_Line(page.rect, 0, placeholder)], True, False, (left, right)

    drawings = page.get_drawings()
    signature_page = any(heading_key(line.paragraph.text) in _FORM_SECTIONS
                         and (line.paragraph.font_size_pt or 0) >= 14 for line in body[:8])
    if page_no == 1 or signature_page:
        body, image_boxes = _form_rows(body, image_boxes, drawings, page, signature_page=signature_page)
    paths = list(_drawing_paths(page, drawings))
    clusters = [pymupdf.Rect(coords) * rotation for coords in page.cluster_drawings(drawings=paths)] if paths else []
    tables, algorithms = _detect_tables(page, body, paths, clusters, previous_tables)
    _mark_footnotes(page, body, drawings)
    _mark_math_fragments(body)
    body, image_boxes = _formula_units(body, image_boxes, page_no, width)
    page_lines = _objects(page, body, image_boxes, paths, clusters, tables, algorithms)
    for line in page_lines:
        line.glyphs.clear()
        line.run_baselines.clear()
    body_characters = sum(sum(char.isalnum() for char in line.paragraph.text) for line in body)
    return page_lines, False, body_characters >= 4, (left, right)


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
    for row in lines:
        p = row.paragraph
        if p.text and row.box.y0 >= height * .65 and (p.font_size_pt or 0) <= 10.5 and re.match(r"^[①-⑳]", p.text):
            p.role = "footnote"


def _mark_math_fragments(lines):
    math_lines = [
        line for line in lines if not line.paragraph.in_table and any(_math_font(run.font_name) for run in line.paragraph.runs)
    ]
    for line in lines:
        p = line.paragraph
        if p.in_table:
            continue
        math_context = any(_math_font(run.font_name) for run in p.runs)
        symbols = re.search(r"[=∑∫≈≤≥×÷±√∞∏∂]", p.text)
        if math_context or symbols:
            for run in p.runs:
                if (_LATEX_ROMAN_FACE.fullmatch((run.font_name or "").replace("_", ""))
                        and not HAN.search(run.text) and not re.search(r"[A-Za-z]{3,}", run.text)):
                    run.is_script = True
            _set_line_style(p)
        # Equation editors can draw each numerator, operator and subscript as a separate PDF line.
        if (p.role == "other" and not p.object_kind and not HAN.search(p.text) and len(p.text) <= 35
                and not (_REFERENCE_LABEL.fullmatch(p.text) or FORMULA_NUMBER.fullmatch(p.text))
                and not re.search(r"[A-Za-z]{5,}", p.text)
                and (symbols and any(_LATEX_ROMAN_FACE.fullmatch((run.font_name or "").replace("_", ""))
                                     for run in p.runs)
                     or any(abs(line.baseline - other.baseline) <= p.font_size_pt * 1.4
                        and max(line.box.x0 - other.box.x1, other.box.x0 - line.box.x1) <= 24
                        for other in math_lines))):
            p.role = "equation_fragment"


def _heading_evidence(lines_by_page):
    headings, toc_entries = set(), set()
    for lines in lines_by_page:
        text_lines = [line for line in lines
                      if line.paragraph.text and line.paragraph.role == "other" and not line.paragraph.in_table
                      and not line.paragraph.in_figure and not line.paragraph.object_kind]
        leader_lines = [i for i, line in enumerate(text_lines) if _TOC_LEADERS.search(line.paragraph.text)]
        if len(leader_lines) >= 2:
            # Long TOC titles can occupy a line by themselves before the dotted continuation.
            toc_entries.update(line.paragraph.index for line in text_lines[:leader_lines[-1] + 1]
                               if heading_key(line.paragraph.text) != "toc")
        for i, line in enumerate(text_lines):
            p = line.paragraph
            if p.font_size_pt < 11.5:
                continue
            if len(p.text) >= 24 and re.search(r"[：:。！？!?]", p.text):
                continue
            level = heading_level(p.text)
            if level and level >= 3 and not p.bold and p.font_size_pt < 13.5 and len(p.text) >= 24:
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
            setup.left_margin_mm = pt_to_mm(sorted(line.content_x0 for line in prose)[len(prose) // 10])
            right_edges = sorted(line.content_x1 for line in prose)
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


def _append_unit(anchor, line, *, previous_line=None, separator=None):
    first, other = anchor.paragraph, line.paragraph
    if separator is None:
        separator = "" if HAN.search(first.text[-1:]) or HAN.match(other.text) else " "
    first.text += separator + other.text
    first.runs.extend(other.runs)
    first.line_count += other.line_count
    first.page_end = other.page_end or other.page_no
    if previous_line is not None and previous_line.paragraph.page_no == other.page_no:
        spacing = line.baseline - previous_line.baseline
        first.line_spacings_pt.append(spacing)
        first.line_spacing_samples.append(LineSpacingSampleIR(
            spacing_pt=spacing, page_no=other.page_no, bbox=_bbox(previous_line.box | line.box),
        ))
    if first.page_no == other.page_no:
        first.bbox = _bbox(pymupdf.Rect(first.bbox) | line.box)
    if first.runs:
        _set_line_style(first)


def _adjust_pdf_subheadings(lines_by_page):
    chapter = []
    for line in (line for lines in lines_by_page for line in lines):
        p = line.paragraph
        if p.role in {"chapter_heading", "section_heading"}:
            _use_chinese_heading_levels(chapter)
            chapter = []
        chapter.append(p)
    _use_chinese_heading_levels(chapter)


def _use_chinese_heading_levels(chapter):
    if any(p.role == "section_l2_heading" for p in chapter):
        return
    for p in chapter:
        if p.role == "section_l3_heading" and re.match(r"^[一二三四五六七八九十]+、", p.text):
            p.role = "section_l2_heading"
        if p.role == "section_l4_heading" and re.match(r"^[（(][一二三四五六七八九十]+[）)]", p.text):
            p.role = "section_l3_heading"


def _merge_cover_titles(lines):
    anchor = previous = english = None
    for line in lines:
        p = line.paragraph
        if p.section_key != "cover" or not p.text or p.object_kind:
            continue
        if p.role == "cover_title" and anchor is None:
            anchor = previous = line
            continue
        if not anchor:
            continue
        if p.field_label and p.role != "cover_title_en":
            if line.baseline > anchor.baseline:
                break
            continue
        size = p.font_size_pt or 0
        gap = line.baseline - previous.baseline
        if (p.alignment != "center" and p.role != "cover_title_en" or size < 16
                or not 0 < gap <= 2.2 * (previous.paragraph.font_size_pt or size)):
            break
        if english is None and HAN.search(p.text) and abs(size - anchor.paragraph.font_size_pt) < 2:
            original = anchor.paragraph
            if original.field_label == "title_cn":
                original.field_value = (original.field_value or "") + p.text
            _append_unit(anchor, line)
        elif re.search(r"[A-Za-z]", p.text) and not HAN.search(p.text):
            if english is None:
                english = line
                p.role = "cover_title_en"
            else:
                if english.paragraph.field_label == "title_en":
                    english.paragraph.field_value = (english.paragraph.field_value or "") + " " + p.text
                _append_unit(english, line, separator=" ")
        else:
            break
        if line is not english:
            p.text, p.runs = "", []
        previous = line


def _same_body_type(previous, current):
    return (previous.font_name == current.font_name and previous.bold == current.bold
            and abs(previous.font_size_pt - current.font_size_pt) <= .6)


def _body_line_gap(lines):
    gaps = Counter()
    for previous, line in zip(lines, lines[1:]):
        p, q = previous.paragraph, line.paragraph
        if (p.role != q.role or p.role != "body_text" or p.in_table or q.in_table
                or not _same_body_type(p, q)):
            continue
        gap = line.baseline - previous.baseline
        if q.font_size_pt * .9 <= gap <= q.font_size_pt * 2.15:
            gaps[round(gap * 2) / 2] += 1
    return gaps.most_common(1)[0][0] if gaps and max(gaps.values()) >= 2 else None


def _wide_wrap(previous, line, frame, previous_frame, *, normal_gap, same_page):
    p, q = previous.paragraph, line.paragraph
    left, right = frame
    prev_left, prev_right = previous_frame
    size = q.font_size_pt
    if previous.content_x1 - previous.content_x0 < (prev_right - prev_left) * .73:
        return False
    left_offset = line.content_x0 - left
    previous_offset = previous.content_x0 - prev_left
    hanging = (left_offset <= size * 3 and (
        previous_offset > size * .75 and abs(left_offset - previous_offset) <= size * .5
        or _LIST_START.match(p.text) and left_offset > previous_offset
    ))
    if (previous.content_x1 < prev_right - size * 1.55
            or left_offset > size * .75 and not hanging
            or abs(left_offset - previous_offset) > size * 2.9
            or abs(p.font_size_pt - size) > 2.3 or q.alignment == "right"):
        return False
    if _LIST_START.match(q.text):
        return False
    if _PROSE_SENTENCE_END.search(p.text):
        return (same_page and previous.content_x1 >= prev_right - size * .6
                and left_offset <= previous_offset + size * .6 and _same_body_type(p, q)
                and normal_gap is not None and line.baseline - previous.baseline <= normal_gap + max(1.5, size * .12))
    return True


def _display_wrap(anchor, previous, line, frame):
    p, q = previous.paragraph, line.paragraph
    width = frame[1] - frame[0]
    size = p.font_size_pt
    role = anchor.paragraph.role
    caption = role.endswith("_caption")
    if q.role != "body_text" and not (caption and q.in_figure):
        return False
    if not size or not q.font_size_pt or abs(q.font_size_pt - size) > .6:
        return False
    gap = line.baseline - previous.baseline
    max_gap = max(size * 2.35, 25.0) if caption else size * 2.05
    if not size * .8 <= gap <= max_gap or heading_key(q.text):
        return False
    same_left_band = previous.box.width >= width * .55 and abs(line.content_x0 - previous.content_x0) <= size
    centered = p.alignment == q.alignment == "center"
    if caption:
        return (centered or same_left_band) and not (_SENTENCE_END.search(p.text) and _NEW_PARAGRAPH.match(q.text))
    centered_chapter = centered and role == "chapter_heading"
    heading_width = max(anchor.box.width, previous.box.width) if centered_chapter else previous.box.width
    return (not q.in_figure and (centered_chapter or q.bold == p.bold) and (centered or same_left_band)
            and heading_width >= width * (.55 if centered_chapter else .70) and not heading_key(p.text)
            and not (_SENTENCE_END.search(p.text) or _SENTENCE_END.search(q.text)
                     or _NEW_PARAGRAPH.match(q.text) or _LIST_START.match(q.text)))


def _merge_logical_units(result, lines_by_page, frames):
    output = []
    previous = anchor = None
    previous_index = None
    for page_index, (setup, lines, frame) in enumerate(zip(result.page_setups, lines_by_page, frames, strict=True)):
        height = mm_to_pt(setup.height_mm)
        page_gap = _body_line_gap(lines)
        for line in lines:
            p = line.paragraph
            if not p.text and not p.object_kind and p.role != "scanned_page":
                continue
            p.page_end = p.page_end or p.page_no
            if p.role == "footnote":
                output.append(line)
                continue
            if previous is not None and anchor is not None and p.section_key == anchor.paragraph.section_key:
                role = anchor.paragraph.role
                same_page = page_index == previous_index
                distance = line.baseline - previous.baseline
                if same_page and (role.endswith("_heading") or role.endswith("_caption")) and _display_wrap(
                    anchor, previous, line, frame
                ) and not p.object_kind and not p.in_table:
                    _append_unit(anchor, line)
                    p.in_figure = False
                    previous = line
                    continue
                if (role == p.role == "body_text" and not p.object_kind and not p.in_table
                        and not anchor.paragraph.object_kind and not anchor.paragraph.in_table):
                    cross_page = (page_index == previous_index + 1 and line.baseline <= height * .24
                                  and previous.baseline >= mm_to_pt(result.page_setups[previous_index].height_mm) * .79)
                    valid_gap = same_page and p.font_size_pt * .72 <= distance <= p.font_size_pt * 2.55
                    samples = anchor.paragraph.line_spacing_samples
                    recent_gap = samples[-1].spacing_pt if samples and samples[-1].page_no == p.page_no else page_gap
                    if (valid_gap or cross_page) and _wide_wrap(
                        previous, line, frame, frames[previous_index], normal_gap=recent_gap, same_page=same_page,
                    ):
                        _append_unit(anchor, line, previous_line=previous)
                        previous, previous_index = line, page_index
                        continue
            if p.in_figure:
                previous = anchor = None
                continue
            output.append(line)
            previous = anchor = line
            previous_index = page_index

    for index, line in enumerate(output):
        p = line.paragraph
        p.index = index
        if p.line_spacings_pt:
            p.line_spacing_pt = median(p.line_spacings_pt)
            p.line_spacing_rule = "estimated"
    return output


def _mark_table_continuations(result, lines_by_page):
    previous = []
    for setup, lines in zip(result.page_setups, lines_by_page, strict=True):
        height = mm_to_pt(setup.height_mm)
        tables = [line for line in lines if line.paragraph.object_kind == "table"]
        captions = [line for line in lines if line.paragraph.role == "table_caption"]
        for table in tables:
            table.is_continuation = _table_continues(table.box, height, previous, captions)
        previous = [table for table in tables if table.box.y1 >= height * .72]


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
            _append_unit(line, continuation)
            p.text, p.runs, p.role = "", [], "other"
            previous = continuation


def _merge_reference_lines(result, lines_by_page):
    anchor = previous = None
    right = 0
    for setup, lines in zip(result.page_setups, lines_by_page, strict=True):
        for row in _rows(lines, tolerance=2.5):
            for label, entry in zip(row, row[1:]):
                p, q = label.paragraph, entry.paragraph
                gap = entry.content_x0 - label.content_x1
                if (p.role == q.role == "reference_entry" and _REFERENCE_LABEL.fullmatch(p.text)
                        and not _REFERENCE_START.match(q.text) and 0 <= gap <= p.font_size_pt * 3.5):
                    _join_lines(label, entry)
                    q.text, q.runs, q.role = "", [], "other"
        widths = [line.box.x1 for line in lines if line.paragraph.role == "reference_entry"]
        if not widths:
            anchor = previous = None
            continue
        width = mm_to_pt(setup.width_mm)
        page_right = max(widths)
        for line_index, line in enumerate(lines):
            p = line.paragraph
            if not p.text and not p.object_kind:
                continue
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
                    _append_unit(anchor, line, previous_line=previous if close and not cross_page else None,
                                 separator=separator)
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
                lines_by_page, frames = [], []
                scanned_pages, text_pages = set(), set()
                font_cache = {}
                previous_tables = []
                for page in pdf:
                    lines, scanned, text_page, frame = _add_page(page, result, font_cache, previous_tables)
                    previous_tables = [line for line in lines if line.paragraph.object_kind == "table"
                                       and line.box.y1 >= page.rect.height * .72]
                    frames.append(frame)
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
                _adjust_pdf_subheadings(lines_by_page)
                _measure(result, lines_by_page)
                _mark_table_continuations(result, lines_by_page)
                _merge_reference_lines(result, lines_by_page)
                for setup, lines in zip(result.page_setups, lines_by_page, strict=True):
                    _merge_keyword_lines(lines, mm_to_pt(setup.width_mm))
                    _merge_cover_titles(lines)
                units = _merge_logical_units(result, lines_by_page, frames)
                result.paragraphs = [unit.paragraph for unit in units]
                objects = {unit.paragraph.index: {"inner_texts": unit.inner_texts, "subfigure_count": unit.subfigure_count,
                                                  "is_continuation": unit.is_continuation}
                           for unit in units if unit.paragraph.object_kind in {"figure", "table"}}
                summarize_document(result, text_page_ratio=len(text_pages) / pdf.page_count, pdf_objects=objects)
                figures = {(unit.paragraph.page_no, unit.paragraph.bbox): unit
                           for unit in units if unit.paragraph.object_kind == "figure"}
                for lines in lines_by_page:
                    for line in lines:
                        if line.figure_owner and line.paragraph.in_figure:
                            line.figure_owner.inner_texts.append(line.paragraph.text)
                for item in result.figures_tables:
                    page_no = item.object_page_no or result.paragraphs[item.paragraph_index].page_no
                    if item.kind == "figure" and (owner := figures.get((page_no, item.object_bbox))):
                        item.inner_texts = owner.inner_texts
                return result
        except (OSError, RuntimeError, ValueError, TypeError, IndexError, KeyError) as exc:
            raise ParseError(f"无法解析 PDF 文件：{exc}") from exc


def parse_pdf(source: DocumentSource, file_name: str | None = None) -> DocumentIR:
    return PdfParser().parse(source, file_name)
