"""Apply template-driven repairs to an editable Word package."""
from collections import Counter
from copy import deepcopy
import re

from docx.enum.section import WD_ORIENT, WD_SECTION_START
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from app.engine.utils import chapter_number
from app.parsers.base import TOC_PAGE, cover_elements
from app.parsers.docx_parser import FIELD_PAGE, ON_VALUES, _Styles, _body, _child, _fields, _on, _property, _run_text, _runs
from app.revisions.incremental import _editable_runs, paragraph_elements, replace_text, style_paragraph, style_run


def _xml(tag, **attributes):
    element = OxmlElement(f"w:{tag}")
    for name, value in attributes.items():
        element.set(qn(f"w:{name}"), str(value))
    return element


def _copy_story(source, destination):
    for child in list(destination.element):
        destination.element.remove(child)
    relationships = {}
    for source_element in source.element:
        child = deepcopy(source_element)
        for node in child.iter():
            for attribute, value in list(node.attrib.items()):
                if attribute.partition("}")[0] != qn("r:id").partition("}")[0] or value not in source.rels:
                    continue
                if value not in relationships:
                    rel = source.rels[value]
                    target = rel.target_ref if rel.is_external else rel.target_part
                    relationships[value] = destination.relate_to(target, rel.reltype, rel.is_external)
                node.set(attribute, relationships[value])
        destination.element.append(child)


def _local_part(story):
    if not story.is_linked_to_previous:
        return story.part
    source = story.part
    if not story.is_linked_to_previous:
        return source
    story.is_linked_to_previous = False
    destination = story.part
    _copy_story(source, destination)
    return destination


def _put_field(paragraph, instruction, cached):
    field = _xml("fldSimple", instr=instruction)
    field.append(paragraph.add_run(cached)._r)
    paragraph._p.append(field)


def _set_border(paragraph, params):
    properties = paragraph.get_or_add_pPr()
    borders = properties.find(qn("w:pBdr"))
    if borders is None:
        borders = _xml("pBdr")
        properties.insert_element_before(borders, "w:shd", "w:tabs", "w:spacing", "w:ind", "w:jc", "w:rPr", "w:sectPr")
    bottom = borders.find(qn("w:bottom"))
    if bottom is None:
        bottom = _xml("bottom")
        next_side = next((node for node in borders if node.tag in {qn("w:right"), qn("w:between"), qn("w:bar")}), None)
        if next_side is None:
            borders.append(bottom)
        else:
            next_side.addprevious(bottom)
    for name, value in {"val": params["style"], "sz": round(params["width_pt"] * 8),
                        "space": 1, "color": "auto"}.items():
        bottom.set(qn(f"w:{name}"), str(value))


def _is_chapter(paragraph):
    if re.search(r"[。！？；;!?]\s*$", paragraph.text) and not re.fullmatch(
        r"(?:heading|标题)\s*1", paragraph.style_name or "", re.I
    ):
        return False
    return paragraph.role == "chapter_heading" or (
        paragraph.role == "section_heading" and paragraph.section_key == "body"
        and chapter_number(paragraph.text) is not None
    )


def _odd_title(paragraphs, index):
    local = [p for p in paragraphs if p.section_index == index and _is_chapter(p)]
    if len(local) > 1 and all((p.style_name or "").lower() == "heading 1" for p in local):
        return local[0].text, "STYLEREF 1"
    preceding = [p for p in paragraphs if _is_chapter(p) and p.section_index < index]
    chapter = next(iter(local), preceding[-1] if preceding else None)
    return (chapter.text if chapter else None), None


def _even_title(story, params, cover, degree):
    pattern = params.get("even_pattern")
    if not pattern:
        return None
    degree_name = "博士" if degree == "doctor" else "硕士"
    major = cover.get("major", ("学术", None))[0]
    possibilities = [p.text for p in story.paragraphs] + [
        f"福建师范大学{major}{degree_name}学位论文",
        f"福建师范大学学术{degree_name}学位论文",
    ]
    return next((text for text in possibilities if re.fullmatch(pattern, text.strip())), None)


def _repair_header(story, title, field, style, border):
    if title is None and border is None:
        return
    if title is not None or not story.is_linked_to_previous:
        _local_part(story)
    elif story.is_linked_to_previous:
        return
    if title is not None:
        paragraphs = story.paragraphs
        paragraph = next((p for p in paragraphs if p.text.strip() == title), None)
        if paragraph is None:
            paragraph = next((p for p in paragraphs if not any(
                next(p._p.iter(qn(tag)), None) is not None
                for tag in ("w:drawing", "w:pict", "m:oMath", "w:fldChar", "w:fldSimple")
            )), None)
        if paragraph is None:
            paragraph = story.add_paragraph()
        if field:
            if not any(code.strip().upper() == field for code, _ in _fields(paragraph._p)):
                if not list(_fields(paragraph._p)):
                    replace_text(paragraph._p, "")
                _put_field(paragraph, field, title)
        elif paragraph.text.strip() != title:
            replace_text(paragraph._p, title)
        style_paragraph(paragraph._p, **style)
    if border:
        for paragraph in story.paragraphs:
            if paragraph.text.strip() or list(_fields(paragraph._p)):
                _set_border(paragraph._p, border)


def _insert_section_break(preceding, next_paragraph, following, styles):
    props = preceding.get_or_add_pPr()
    if props.find(qn("w:sectPr")) is not None:
        return False
    props.append(deepcopy(following))
    has_break = any(br.get(qn("w:type")) == "page" for br in preceding.iter(qn("w:br")))
    _, layers, _ = styles.paragraph(next_paragraph)
    marker = _property(layers, "pageBreakBefore")
    has_break |= marker in ON_VALUES or marker is None and any(_on(_child(layer, "pageBreakBefore")) for layer in layers)
    following.start_type = WD_SECTION_START.CONTINUOUS if has_break else WD_SECTION_START.NEW_PAGE
    return True


def _split_numbering_sections(document, paragraphs, number_params):
    """Use existing paragraph boundaries for front/main numbering transitions."""
    formats = {key: "upperRoman" for key in number_params["roman_sections"]}
    formats.update(dict.fromkeys(number_params["decimal_sections"], "decimal"))
    elements = dict(paragraph_elements(document))
    section_properties = [section._sectPr for section in document.sections]
    styles = _Styles(document)
    previous = None
    previous_format = None
    for paragraph in paragraphs:
        if paragraph.in_table or paragraph.index not in elements:
            continue
        if previous is None or previous.section_index != paragraph.section_index:
            previous_format = None
        current_format = formats.get(paragraph.section_key)
        if (current_format and paragraph.text and previous is not None and previous.section_index == paragraph.section_index
                and previous_format != current_format and (previous_format or previous.text)):
            _insert_section_break(elements[previous.index], elements[paragraph.index],
                                  section_properties[paragraph.section_index], styles)
        if paragraph.text:
            previous_format = current_format or previous_format
        previous = paragraph


def _split_custom_chapters(document, paragraphs):
    chapters = {}
    for paragraph in paragraphs:
        if _is_chapter(paragraph):
            chapters.setdefault(paragraph.section_index, []).append(paragraph)
    starts = {p.index for group in chapters.values() if not all(
        (p.style_name or "").casefold() == "heading 1" for p in group
    ) for p in group[1:]}
    if not starts:
        return False
    section_properties = [section._sectPr for section in document.sections]
    styles = _Styles(document)
    previous = None
    changed = False
    for index, element in paragraph_elements(document):
        p = paragraphs[index]
        if p.in_table:
            continue
        if index in starts and previous is not None:
            following = section_properties[p.section_index]
            if _insert_section_break(previous, element, following, styles):
                for header in list(following.findall(qn("w:headerReference"))):
                    following.remove(header)
                number = following.find(qn("w:pgNumType"))
                if number is not None:
                    number.attrib.pop(qn("w:start"), None)
                changed = True
        previous = element
    return changed


def _section_membership(document, paragraphs):
    body, _ = _body(document, _Styles(document))
    return [p.model_copy(update={"section_index": parsed.section_index})
            for p, parsed in zip(paragraphs, body, strict=True)]


def _enable_even_footers(document):
    has_default = has_even = False
    for section in document.sections:
        has_default |= not section.footer.is_linked_to_previous
        has_even |= not section.even_page_footer.is_linked_to_previous
        if has_default and not has_even:
            _copy_story(section.footer.part, _local_part(section.even_page_footer))
            has_even = True


def _remove_page_fields(element):
    for field in list(element.iter(qn("w:fldSimple"))):
        if FIELD_PAGE.match(field.get(qn("w:instr"), "")):
            field.getparent().remove(field)
    stack = []
    for run in list(_runs(element)):
        for active in stack:
            active[1].append(run)
        for node in run:
            if node.tag == qn("w:instrText") and stack:
                stack[-1][0].append(node.text or "")
            if node.tag != qn("w:fldChar"):
                continue
            kind = node.get(qn("w:fldCharType"))
            if kind == "begin":
                stack.append(([], [run]))
            elif kind == "end" and stack:
                instruction, runs = stack.pop()
                if FIELD_PAGE.match("".join(instruction)):
                    for field_run in runs:
                        if field_run.getparent() is not None:
                            field_run.getparent().remove(field_run)


def _page_number(section, fmt, params, *, first_of_format, odd_even):
    sect = section._sectPr
    number = sect.find(qn("w:pgNumType"))
    if number is None:
        number = _xml("pgNumType")
        sect.insert_element_before(number, "w:cols", "w:formProt", "w:vAlign", "w:noEndnote", "w:titlePg",
                                   "w:textDirection", "w:bidi", "w:rtlGutter", "w:docGrid")
    number.set(qn("w:fmt"), fmt)
    if first_of_format:
        number.set(qn("w:start"), "1")
    elif qn("w:start") in number.attrib:
        del number.attrib[qn("w:start")]

    variants = [""]
    if odd_even:
        variants.append("even_page_")
    if section.different_first_page_header_footer:
        variants.append("first_page_")
    for prefix in variants:
        target = getattr(section, prefix + params["position"])
        other = getattr(section, prefix + ("header" if params["position"] == "footer" else "footer"))
        other_exists = not other.is_linked_to_previous or any(
            FIELD_PAGE.match(code) for paragraph in other.paragraphs for code, _ in _fields(paragraph._p)
        )
        if other_exists:
            for paragraph in _local_part(other).element.iter(qn("w:p")):
                _remove_page_fields(paragraph)
        part = _local_part(target)
        paragraphs = list(part.element.iter(qn("w:p")))
        page_paragraph = next((p for p in paragraphs if any(FIELD_PAGE.match(code) for code, _ in _fields(p))), None)
        for paragraph in paragraphs:
            _remove_page_fields(paragraph)
        if page_paragraph is None:
            page_paragraph = next((p for p in paragraphs if not any(
                _run_text(run) or next(run.iter(qn("w:drawing")), None) is not None for run in _runs(p)
            )), None)
        paragraph = Paragraph(page_paragraph, target) if page_paragraph is not None else target.add_paragraph()
        _put_field(paragraph, "PAGE", "I" if fmt == "upperRoman" else "1")
        style_paragraph(paragraph._p, alignment=params["alignment"])


def fix_document_layout(document, ir, rule_params, selected, *, degree="master"):
    paragraphs, formats = ir.paragraphs, {}
    if "PAGE_NUMBER_STYLE" in selected:
        number_params = rule_params["PAGE_NUMBER_STYLE"]
        _split_numbering_sections(document, paragraphs, number_params)
        paragraphs = _section_membership(document, paragraphs)
        formats = dict.fromkeys(number_params["roman_sections"], "upperRoman")
        formats.update(dict.fromkeys(number_params["decimal_sections"], "decimal"))

    header = rule_params.get("HEADER_FORMAT", {})
    border = rule_params.get("HEADER_DOUBLE_BORDER") if "HEADER_DOUBLE_BORDER" in selected else None
    if "HEADER_FORMAT" in selected:
        if _split_custom_chapters(document, paragraphs):
            paragraphs = _section_membership(document, paragraphs)
        enable_even = header.get("odd_even_headers", True)
        if enable_even and not document.settings.odd_and_even_pages_header_footer and not formats:
            _enable_even_footers(document)
        document.settings.odd_and_even_pages_header_footer = enable_even
    odd_even = document.settings.odd_and_even_pages_header_footer
    cover = cover_elements(paragraphs)
    by_section = {}
    for paragraph in paragraphs:
        by_section.setdefault(paragraph.section_index, []).append(paragraph)
    previous_format = None
    for index, section in enumerate(document.sections):
        if "PAGE_SIZE_A4" in selected:
            params = rule_params["PAGE_SIZE_A4"]
            section.orientation = WD_ORIENT.PORTRAIT
            section.page_width, section.page_height = Mm(params["width_mm"]), Mm(params["height_mm"])
        if "PAGE_MARGINS" in selected:
            params = rule_params["PAGE_MARGINS"]
            for side, default in (("top", 30), ("bottom", 30), ("left", 29), ("right", 28)):
                setattr(section, f"{side}_margin", Mm(params.get(f"{side}_mm", default)))
        section_paragraphs = by_section.get(index, [])
        is_body = any(p.section_key == "body" and p.text for p in section_paragraphs)
        if "HEADER_FORMAT" in selected and is_body:
            section.header_distance = Mm(header.get("header_distance_mm", 15))
            style = {key: header[key] for key in ("font_name", "font_size_pt", "alignment") if key in header}
            odd, field = _odd_title(paragraphs, index)
            _repair_header(section.header, odd, field, style, border)
            if odd_even:
                even = _even_title(section.even_page_header, header, cover, degree)
                _repair_header(section.even_page_header, even, None, style, border)
        elif border:
            stories = (section.header, section.even_page_header) if odd_even else (section.header,)
            for story in stories:
                _repair_header(story, None, None, {}, border)
        fmt = next((formats[p.section_key] for p in section_paragraphs if p.text and p.section_key in formats), None)
        if fmt:
            _page_number(section, fmt, number_params, first_of_format=fmt != previous_format, odd_even=odd_even)
            previous_format = fmt


def _styles(style):
    return {name: style[name] for name in ("font_name", "font_size_pt", "bold", "alignment") if name in style}


def _toc_styles(element, params):
    runs = list(_runs(element))
    content = "".join(_run_text(run) for run in runs)
    number = TOC_PAGE.search(content)
    editable = set(_editable_runs(element))
    offset = 0
    for run in runs:
        text = _run_text(run)
        end = offset + len(text)
        if text:
            start_number = number.start(1) if number else len(content)
            if offset < start_number < end and run in editable:
                following = deepcopy(run)
                run.addnext(following)
                run.text = text[:start_number - offset]
                following.text = text[start_number - offset:]
                style_run(following, **_styles(params["page_number"]))
            selected = params["page_number"] if offset >= start_number else params["entry"]
            style_run(run, **_styles(selected))
        offset = end


def fix_typography(document, ir, rule_params, selected, findings):
    affected = {}
    for violation in findings:
        index = violation.location.get("paragraph_index")
        if index is not None and violation.rule_code in selected:
            affected.setdefault(index, set()).add(violation.rule_code)

    body = rule_params.get("BODY_TYPOGRAPHY", {})
    sizes = Counter(p.font_size_pt for p in ir.paragraphs if p.font_size_pt is not None
                    and p.role in {"body_text", "reference_entry"} and p.section_key in body.get("section_keys", []))
    dominant_size = sizes.most_common(1)[0][0] if sizes else None
    cover_title = cover_elements(ir.paragraphs).get("title_cn")
    for index, element in paragraph_elements(document):
        p = ir.paragraphs[index]
        for code in sorted(affected.get(index, ())):
            params = rule_params[code]
            if code == "LINE_SPACING_MIN":
                style_paragraph(element, line_spacing_pt=params["min_pt"])
            elif code == "BODY_TYPOGRAPHY":
                style = _styles(params)
                if params.get("require_consistent_size") and dominant_size is not None:
                    style["font_size_pt"] = dominant_size
                style_paragraph(element, **style, preserve_latin=True)
            elif code == "HEADING_TYPOGRAPHY":
                style_paragraph(element, **(_styles(params) | _styles(params["roles"][p.role])), preserve_latin=True)
            elif code == "COVER_ELEMENTS" and cover_title and cover_title[1].index == index:
                style_paragraph(element, **_styles(params["title_cn_style"]), preserve_latin=True)
            elif params.get("section_key") == p.section_key:
                if p.role == "toc_entry" and "entry" in params:
                    _toc_styles(element, params)
                    continue
                kind = {"section_heading": "heading", "body_text": "body",
                        "keywords_cn": "keywords", "keywords_en": "keywords"}.get(p.role)
                if kind in params:
                    style_paragraph(element, **_styles(params[kind]), preserve_latin=True)
                    if "text" in params[kind] and p.text != params[kind]["text"] and not p.object_kind:
                        replace_text(element, params[kind]["text"])


def add_review_comments(document, violations):
    if not hasattr(document, "add_comment"):
        return False
    existing = {comment.text for comment in document.comments if comment.author == "论文修订"}
    elements = dict(paragraph_elements(document))
    first = next((p for p in elements.values() if any(_run_text(run) for run in _runs(p))), None)
    added = False
    for issue in violations:
        if issue.rule_code not in {"REQUIRED_SECTIONS", "WORD_COUNT_REQUIREMENTS", "SECTION_ORDER"}:
            continue
        note = f"{issue.expected}。{issue.message}"
        if note in existing:
            continue
        element = elements.get(issue.location.get("paragraph_index"), first)
        if element is None:
            continue
        run = next((r for r in _runs(element) if _run_text(r)), None)
        if run is not None:
            document.add_comment(Run(run, Paragraph(element, document)), text=note, author="论文修订")
            existing.add(note)
            added = True
    return added
