"""Read Word styles and section settings from the DOCX package."""
from io import BytesIO
import re
import struct
from zipfile import BadZipFile

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from lxml import etree

from app.engine.utils import HAN, normalize_font_name
from app.parsers.base import (
    BaseParser, CAPABILITIES, DocumentSource, ParseError, TOC_PAGE, analyze_document,
    dominant_run, read_source,
)
from app.schemas.ir import DocumentIR, HeaderItemIR, PageNumberIR, PageSetupIR, ParagraphIR, TextRunIR, TextStyleIR

FIELD_PAGE = re.compile(r"^\s*PAGE(?:\s|$)", re.I)
FIELD_STYLE = re.compile(r'^\s*STYLEREF\s+(?:"([^"]+)"|(\S+))', re.I)
ALIGNMENTS = {"left": "left", "start": "left", "right": "right", "end": "right",
              "center": "center", "both": "justify", "distribute": "justify"}
ON_VALUES = {"1", "true", "on"}
PAGE_FORMATS = dict.fromkeys(("decimal", "decimalZero", "decimalFullWidth", "decimalHalfWidth", "decimalFullWidth2"), "decimal")
PAGE_FORMATS.update(dict.fromkeys(("lowerRoman", "upperRoman"), "roman"))
TRANSPARENT_WRAPPERS = {qn(f"w:{name}") for name in ("sdt", "sdtContent", "customXml", "ins")}
RUN_WRAPPERS = TRANSPARENT_WRAPPERS | {qn(f"w:{name}") for name in ("hyperlink", "smartTag", "fldSimple")}


def _child(element, name):
    return element.find(qn(f"w:{name}")) if element is not None else None


def _attr(element, name="val"):
    return element.get(qn(f"w:{name}")) if element is not None else None


def _on(element):
    return element is not None and (_attr(element) is None or _attr(element) in ON_VALUES)


def _twips_mm(element, name):
    value = _attr(element, name)
    return int(value) * 25.4 / 1440 if value is not None else None


def _walk(container, tags, wrappers):
    for child in container:
        if child.tag in tags:
            yield child
        elif child.tag in wrappers:
            yield from _walk(child, tags, wrappers)


def _runs(paragraph):
    return _walk(paragraph, {qn("w:r")}, RUN_WRAPPERS)


def _run_text(run):
    return "".join(
        {qn("w:tab"): "\t", qn("w:br"): "\n", qn("w:cr"): "\n", qn("w:noBreakHyphen"): "-"}
        .get(child.tag, child.text or "" if child.tag == qn("w:t") else "")
        for child in run
    )


def _fields(paragraph):
    """Yield field instructions and their cached result in XML reading order."""
    stack = []
    for node in paragraph.iter():
        if node.tag == qn("w:fldSimple"):
            yield _attr(node, "instr") or "", "".join(
                child.text or "" for child in node.iter(qn("w:t"))
            )
        elif node.tag == qn("w:fldChar"):
            kind = _attr(node, "fldCharType")
            if kind == "begin":
                stack.append(["", "", False])
            elif kind == "separate" and stack:
                stack[-1][2] = True
            elif kind == "end" and stack:
                instruction, result, _ = stack.pop()
                yield instruction, result
        elif stack and node.tag == qn("w:instrText"):
            stack[-1][0] += node.text or ""
        elif stack and stack[-1][2] and node.tag == qn("w:t"):
            stack[-1][1] += node.text or ""


class _Styles:
    def __init__(self, document):
        styles = document.styles.element
        self.styles = {_attr(style, "styleId"): style for style in styles.findall(qn("w:style"))}
        self.defaults = {
            _attr(style, "type"): _attr(style, "styleId") for style in self.styles.values()
            if _attr(style, "default") in ON_VALUES
        }
        defaults = _child(styles, "docDefaults")
        self.default_paragraph = _child(_child(defaults, "pPrDefault"), "pPr")
        self.default_run = _child(_child(defaults, "rPrDefault"), "rPr")
        self.theme = self._theme_fonts(document)
        self.theme_language = _child(document.settings.element, "themeFontLang")

    @staticmethod
    def _theme_fonts(document):
        theme = next((rel.target_part for rel in document.part.rels.values()
                      if rel.reltype == RELATIONSHIP_TYPE.THEME and not rel.is_external), None)
        if theme is None:
            return {}
        root = etree.fromstring(theme.blob, parser=etree.XMLParser(resolve_entities=False, no_network=True))
        scheme = root.find(".//" + qn("a:fontScheme"))
        result = {}
        if scheme is not None:
            for family in ("major", "minor"):
                group = scheme.find(qn(f"a:{family}Font"))
                if group is None:
                    continue
                for key in ("latin", "ea", "cs"):
                    child = group.find(qn(f"a:{key}"))
                    if child is not None:
                        result[family, key] = child.get("typeface") or None
                for font in group.findall(qn("a:font")):
                    result[family, font.get("script")] = font.get("typeface")
        return result

    def _chain(self, style_id):
        chain = []
        seen = set()
        while style_id in self.styles and style_id not in seen:
            seen.add(style_id)
            style = self.styles[style_id]
            chain.append(style)
            style_id = _attr(_child(style, "basedOn"))
        return chain[::-1]

    def paragraph(self, paragraph):
        direct = _child(paragraph, "pPr")
        style_id = _attr(_child(direct, "pStyle")) or self.defaults.get("paragraph")
        styles = self._chain(style_id)
        paragraph_chain = [self.default_paragraph, *(_child(s, "pPr") for s in styles), direct]
        run_chain = [self.default_run, *(_child(s, "rPr") for s in styles)]
        return _attr(_child(self.styles.get(style_id), "name")), paragraph_chain, run_chain

    def _theme_name(self, value, slot):
        family = "major" if value.startswith("major") else "minor"
        if slot != "eastAsia":
            return self.theme.get((family, "latin"))
        language = (_attr(self.theme_language, "eastAsia") or "zh-CN").lower()
        script = "Jpan" if language.startswith("ja") else "Hang" if language.startswith("ko") else (
            "Hant" if any(region in language for region in ("tw", "hk", "mo", "hant")) else "Hans"
        )
        return self.theme.get((family, "ea")) or self.theme.get((family, script))

    def _font(self, chain, slots):
        for properties in reversed(chain):
            fonts = _child(properties, "rFonts")
            for slot in slots:
                theme = _attr(fonts, f"{slot}Theme")
                name = (self._theme_name(theme, slot) if theme else None) or _attr(fonts, slot)
                if name:
                    return normalize_font_name(name)
        return None

    def run(self, inherited, direct, text):
        style_id = _attr(_child(direct, "rStyle")) or self.defaults.get("character")
        styled = [*inherited, *(_child(s, "rPr") for s in self._chain(style_id))]
        chain = [*styled, direct]
        latin = self._font(chain, ("ascii", "hAnsi"))
        # Resolve each script independently. A direct ASCII override does not erase inherited eastAsia.
        east_asia = self._font(chain, ("eastAsia",)) or latin
        sizes = [_attr(_child(properties, "sz")) for properties in reversed(chain)]
        size = next((int(value) / 2 for value in sizes if value is not None), None)
        bold = _on(_child(styled[0], "b"))
        for properties in styled[1:]:
            if _on(_child(properties, "b")):
                bold = not bold
        override = _child(direct, "b")
        if override is not None:
            bold = _on(override)
        return TextRunIR(
            text=text, font_name=east_asia if HAN.search(text) else latin or east_asia,
            font_name_latin=latin, font_size_pt=size, bold=bold,
        )


def _property(chain, name, attribute="val"):
    return next((value for properties in reversed(chain)
                 if (value := _attr(_child(properties, name), attribute)) is not None), None)


def _paragraph(element, styles, index, section_index, page_no):
    style_name, properties, inherited_runs = styles.paragraph(element)
    runs = [styles.run(inherited_runs, _child(run, "rPr"), _run_text(run)) for run in _runs(element)]
    text = "".join(run.text for run in runs).strip()
    main = dominant_run(runs)
    latin = dominant_run([run for run in runs if re.search(r"[A-Za-z0-9]", run.text)]) or main
    line = _property(properties, "spacing", "line")
    rule = _property(properties, "spacing", "lineRule") or "auto"
    if rule in {"exact", "atLeast"} and line is not None:
        spacing = int(line) / 20
        spacing_rule = "exact" if rule == "exact" else "at_least"
    else:
        sizes = [run.font_size_pt for run in runs if run.text.strip() and run.font_size_pt is not None]
        spacing = (int(line) / 240 if line is not None else 1) * max(sizes) if sizes else None
        spacing_rule = "multiple" if spacing is not None else None

    has_image = any(next(element.iter(qn(tag)), None) is not None for tag in ("w:drawing", "w:pict"))
    has_formula = next(element.iter(qn("m:oMath")), None) is not None
    result = ParagraphIR(
        index=index, section_index=section_index, page_no=page_no, text=text, style_name=style_name,
        font_name=main.font_name if main else None,
        font_name_latin=latin.font_name_latin if latin else None,
        font_size_pt=main.font_size_pt if main else None, bold=main.bold if main else None,
        alignment=ALIGNMENTS.get(_property(properties, "jc") or "left"),
        line_spacing_pt=spacing, line_spacing_rule=spacing_rule, has_image=has_image,
        object_kind="formula" if has_formula else "figure" if has_image else None,
        runs=runs,
    )
    raw_text = "".join(run.text for run in runs)
    number = TOC_PAGE.search(raw_text)
    if number:
        offset = 0
        entry_runs = []
        for run in runs:
            end = offset + len(run.text)
            for start, stop, selected in (
                (0, number.start(), entry_runs), (*number.span(1), result.toc_page_runs),
            ):
                overlap_start, overlap_end = max(start, offset), min(stop, end)
                if overlap_start < overlap_end:
                    selected.append(run.model_copy(update={"text": run.text[overlap_start-offset:overlap_end-offset]}))
            offset = end
        result.toc_entry_runs = entry_runs
        result.toc_page_number = number[1]
        page_run = dominant_run(result.toc_page_runs)
        if page_run:
            result.toc_page_style = TextStyleIR(
                font_name=page_run.font_name, font_size_pt=page_run.font_size_pt, bold=page_run.bold,
            )
        if re.match(r"(?:toc|目录)\s*\d", style_name or "", re.I):
            result.runs = entry_runs
            main = dominant_run(entry_runs)
            if main:
                result.font_name, result.font_size_pt, result.bold = main.font_name, main.font_size_pt, main.bold
    return result


def _border(paragraph, styles):
    _, properties, _ = styles.paragraph(paragraph)
    for layer in reversed(properties):
        edge = _child(_child(layer, "pBdr"), "bottom")
        if edge is not None:
            width = _attr(edge, "sz")
            return _attr(edge), int(width) / 8 if width is not None else None
    return None, None


def _header_items(root, styles, index):
    if root is None:
        return []
    items = []
    for element in root.iter(qn("w:p")):
        paragraph = _paragraph(element, styles, 0, index, None)
        chapter_field = False
        for instruction, _ in _fields(element):
            match = FIELD_STYLE.match(instruction)
            if match and re.fullmatch(r"(?:heading\s*1|标题\s*1|章标题|1)", match[1] or match[2], re.I):
                chapter_field = True
        if paragraph.text or chapter_field:
            style, width = _border(element, styles)
            items.append(HeaderItemIR(
                text=paragraph.text, section_index=index, font_name=paragraph.font_name,
                font_size_pt=paragraph.font_size_pt, bold=paragraph.bold, alignment=paragraph.alignment,
                bottom_border_style=style, bottom_border_pt=width, chapter_field=chapter_field,
                runs=paragraph.runs,
            ))
    return items


def _page_number(root, styles, index, variant, position, number_format):
    result = []
    if root is None:
        return result
    for element in root.iter(qn("w:p")):
        for instruction, cached in _fields(element):
            if not FIELD_PAGE.match(instruction):
                continue
            _, properties, _ = styles.paragraph(element)
            switch = re.search(r"\\\*\s*(roman|arabic)\b", instruction, re.I)
            fmt = {"roman": "roman", "arabic": "decimal"}.get(switch[1].lower()) if switch else number_format
            result.append(PageNumberIR(
                section_index=index, num_format=fmt, alignment=ALIGNMENTS.get(_property(properties, "jc") or "left"),
                raw_text=cached, variant=variant, position=position,
            ))
    return result


def _sections(document, styles, result):
    odd_even = _on(_child(document.settings.element, "evenAndOddHeaders"))
    inherited = {}
    number_format = "decimal"
    for index, section in enumerate(document.sections):
        properties = section._sectPr
        size = _child(properties, "pgSz")
        margins = _child(properties, "pgMar")
        result.page_setups.append(PageSetupIR(
            section_index=index, width_mm=_twips_mm(size, "w"), height_mm=_twips_mm(size, "h"),
            top_margin_mm=_twips_mm(margins, "top"), bottom_margin_mm=_twips_mm(margins, "bottom"),
            left_margin_mm=_twips_mm(margins, "left"), right_margin_mm=_twips_mm(margins, "right"),
            header_distance_mm=_twips_mm(margins, "header"), odd_even_headers=odd_even,
        ))
        first_page = _on(_child(properties, "titlePg"))
        page_number_settings = _child(properties, "pgNumType")
        fmt = _attr(page_number_settings, "fmt")
        if page_number_settings is not None:
            number_format = PAGE_FORMATS.get(fmt or "decimal", "none")
        for position in ("header", "footer"):
            for node in properties.findall(qn(f"w:{position}Reference")):
                part = document.part.related_parts[node.get(qn("r:id"))]
                inherited[position, _attr(node, "type")] = part.element
        for variant in ("default", "even", "first"):
            if variant == "even" and not odd_even or variant == "first" and not first_page:
                continue
            header = inherited.get(("header", variant))
            footer = inherited.get(("footer", variant))
            if variant != "first":
                headers = result.headers_footers
                target = headers.even_headers if variant == "even" else headers.odd_headers if odd_even else headers.default_headers
                target.extend(_header_items(header, styles, index))
            numbers = _page_number(footer, styles, index, variant, "footer", number_format)
            numbers += _page_number(header, styles, index, variant, "header", number_format)
            result.headers_footers.page_numbers.extend(
                numbers or [PageNumberIR(section_index=index, variant=variant)]
            )


def _body(document, styles):
    paragraphs = []
    current_section = 0
    explicit_page = 1
    has_saved_pagination = next(document.element.body.iter(qn("w:lastRenderedPageBreak")), None) is not None
    sections = list(document.sections)
    for element in _walk(document.element.body, {qn("w:p"), qn("w:tbl")}, TRANSPARENT_WRAPPERS):
        if element.tag == qn("w:tbl"):
            page_no = explicit_page if has_saved_pagination else None
            paragraphs.append(ParagraphIR(
                index=len(paragraphs), section_index=current_section, page_no=page_no, text="", object_kind="table",
            ))
            for cell_paragraph in element.iter(qn("w:p")):
                paragraph = _paragraph(cell_paragraph, styles, len(paragraphs), current_section, page_no)
                paragraph.in_table = True
                paragraphs.append(paragraph)
            continue
        _, properties, _ = styles.paragraph(element)
        page_before = _property(properties, "pageBreakBefore")
        if page_before in ON_VALUES or (page_before is None and any(
            _on(_child(layer, "pageBreakBefore")) for layer in properties
        )):
            explicit_page += 1
        manual_breaks = sum(_attr(br, "type") == "page" for br in element.iter(qn("w:br")))
        rendered_breaks = sum(1 for _ in element.iter(qn("w:lastRenderedPageBreak")))
        page_no = explicit_page if has_saved_pagination else None
        paragraphs.append(_paragraph(element, styles, len(paragraphs), current_section, page_no))
        explicit_page += max(manual_breaks, rendered_breaks)
        section_end = _child(_child(element, "pPr"), "sectPr")
        if section_end is not None:
            current_section += 1
            # The following section's break type determines how that section starts.
            next_section = sections[current_section]._sectPr
            if _attr(_child(next_section, "type")) not in {"continuous", "nextColumn"}:
                if not rendered_breaks:
                    explicit_page += 1
                break_type = _attr(_child(next_section, "type"))
                if break_type in {"oddPage", "evenPage"} and explicit_page % 2 != (break_type == "oddPage"):
                    explicit_page += 1
    return paragraphs, explicit_page


def _saved_page_count(document):
    part = next((rel.target_part for rel in document.part.package.rels.values()
                 if rel.reltype == RELATIONSHIP_TYPE.EXTENDED_PROPERTIES and not rel.is_external), None)
    if part:
        root = etree.fromstring(part.blob, parser=etree.XMLParser(resolve_entities=False, no_network=True))
        value = root.findtext("{*}Pages")
        if value and value.isdecimal():
            return int(value)
    return 0


class DocxParser(BaseParser):
    def parse(self, source: DocumentSource, file_name: str | None = None) -> DocumentIR:
        try:
            data, name = read_source(source, file_name, "docx")
            document = Document(BytesIO(data))
            styles = _Styles(document)
            paragraphs, minimum_pages = _body(document, styles)
            result = DocumentIR(
                file_name=name, file_ext="docx", page_count=max(minimum_pages, _saved_page_count(document)),
                capabilities=dict.fromkeys(CAPABILITIES, True), paragraphs=paragraphs,
            )
            _sections(document, styles, result)
            return analyze_document(result)
        except (OSError, BadZipFile, PackageNotFoundError, etree.LxmlError, KeyError, TypeError,
                ValueError, IndexError, AttributeError, RuntimeError, struct.error) as exc:
            raise ParseError(f"无法解析 DOCX 文件：{exc}") from exc


def parse_docx(source: DocumentSource, file_name: str | None = None) -> DocumentIR:
    return DocxParser().parse(source, file_name)
