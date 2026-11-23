"""Edit one Word paragraph and rejudge the checks it can affect."""
from collections import Counter
from copy import deepcopy
import re

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.engine.evaluator import EvaluationResult, Violation, _RuleConfig, evaluate
from app.engine.utils import HAN, chapter_number, normalize_font_name
from app.parsers.base import analyze_document
from app.parsers.docx_parser import TRANSPARENT_WRAPPERS, _Styles, _paragraph, _run_text, _runs, _walk
from app.schemas.revisions import ParagraphDiff

FONT_NAMES = {"simsun": "宋体", "simhei": "黑体", "times_new_roman": "Times New Roman", "microsoft_yahei": "微软雅黑"}
SECTION_STYLES = {"DECLARATION_TYPOGRAPHY", "ABSTRACT_CN_TYPOGRAPHY", "ABSTRACT_EN_TYPOGRAPHY", "TOC_TYPOGRAPHY"}
LOCAL_RULES = SECTION_STYLES | {"BODY_TYPOGRAPHY", "HEADING_TYPOGRAPHY", "LINE_SPACING_MIN"}
TEXT_RULES = {"ABSTRACT_CONTENT_RULES", "REFERENCE_GBT7714", "WORD_COUNT_REQUIREMENTS",
              "REQUIRED_SECTIONS", "SECTION_ORDER"}
_XML_INVALID = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def paragraph_elements(document):
    index = 0
    for element in _walk(document.element.body, {qn("w:p"), qn("w:tbl")}, TRANSPARENT_WRAPPERS):
        if element.tag == qn("w:tbl"):
            index += 1
            for cell in element.iter(qn("w:p")):
                yield index, cell
                index += 1
        else:
            yield index, element
            index += 1


def find_paragraph_element(document, paragraph_index):
    for index, element in paragraph_elements(document):
        if index == paragraph_index:
            return element
        if index > paragraph_index:
            if index == paragraph_index + 1 and paragraph_index >= 0:
                raise ValueError("表格占位符不能编辑，请选中表格中的段落。")
            break
    raise ValueError("段落索引不存在。")


def validate_text(text):
    if _XML_INVALID.search(text):
        raise ValueError("文本包含 Word XML 不支持的控制字符。")


def _editable_runs(element):
    """Keep field codes, computed results, drawings and structural breaks intact."""
    field_depth = 0
    plain = {qn(f"w:{key}") for key in ("rPr", "t", "tab", "br", "cr", "noBreakHyphen", "lastRenderedPageBreak")}
    for run in _runs(element):
        fields = run.findall(qn("w:fldChar"))
        if fields:
            for field in fields:
                kind = field.get(qn("w:fldCharType"))
                field_depth = max(0, field_depth + {"begin": 1, "end": -1}.get(kind, 0))
            continue
        if field_depth or any(parent.tag == qn("w:fldSimple") for parent in run.iterancestors()):
            continue
        if all(child.tag in plain and child.get(qn("w:type")) not in {"page", "column"} for child in run):
            yield run


def replace_text(element, text):
    validate_text(text)
    targets = list(_editable_runs(element))
    with_text = [run for run in targets if _run_text(run)]
    if not targets and next(iter(_runs(element)), None) is not None:
        raise ValueError("该段仅包含图片、公式、域或分页符，没有可替换的纯文本。")
    protected = any(next(element.iter(qn(tag)), None) is not None
                    for tag in ("w:drawing", "w:pict", "m:oMath", "m:oMathPara"))
    if protected and not with_text:
        raise ValueError("图片或公式段落没有可替换的纯文本。")
    targets = with_text or targets[:1] or [element.add_r()]
    start = 0
    for run in targets[:-1]:
        end = start + len(_run_text(run))
        _replace_run_text(run, text[start:end])
        start = end
    _replace_run_text(targets[-1], text[start:])


def _replace_run_text(run, text):
    rendered_breaks = run.findall(qn("w:lastRenderedPageBreak"))
    run.text = text
    for marker in reversed(rendered_breaks):
        run.insert(1 if run.rPr is not None else 0, marker)


def style_run(run, *, font_name=None, font_size_pt=None, bold=None, east_asia_only=False):
    if all(value is None for value in (font_name, font_size_pt, bold)):
        return
    properties = run.get_or_add_rPr()
    if font_name is not None:
        validate_text(font_name)
        font = FONT_NAMES.get(normalize_font_name(font_name), font_name)
        fonts = properties.get_or_add_rFonts()
        slots = ("eastAsia",) if east_asia_only else ("eastAsia", "ascii", "hAnsi")
        for attr in slots:
            fonts.attrib.pop(qn(f"w:{attr}Theme"), None)
            fonts.set(qn(f"w:{attr}"), font)
    if font_size_pt is not None:
        size = str(round(font_size_pt * 2))
        properties.get_or_add_sz().set(qn("w:val"), size)
        if (node := properties.find(qn("w:szCs"))) is None:
            node = OxmlElement("w:szCs")
            properties.insert_element_before(node, "w:highlight", "w:u", "w:vertAlign", "w:rtl", "w:cs", "w:lang")
        node.set(qn("w:val"), size)
    if bold is not None:
        value = "1" if bold else "0"
        properties.get_or_add_b().set(qn("w:val"), value)
        properties.get_or_add_bCs().set(qn("w:val"), value)


def style_paragraph(element, *, font_name=None, font_size_pt=None, bold=None, alignment=None,
                    line_spacing_pt=None, preserve_latin=False):
    if alignment is not None or line_spacing_pt is not None:
        properties = element.get_or_add_pPr()
        if alignment is not None:
            properties.get_or_add_jc().set(qn("w:val"), "both" if alignment == "justify" else alignment)
        if line_spacing_pt is not None:
            spacing = properties.get_or_add_spacing()
            spacing.set(qn("w:line"), str(round(line_spacing_pt * 20)))
            spacing.set(qn("w:lineRule"), "atLeast")
    if any(value is not None for value in (font_name, font_size_pt, bold)):
        runs = list(_runs(element))
        if not runs and next(element.iter(qn("m:oMath")), None) is None:
            runs = [element.add_r()]
        texts = [_run_text(run) for run in runs]
        chinese = preserve_latin and normalize_font_name(font_name) in {"simsun", "simhei"} and any(
            HAN.search(text) for text in texts
        )
        for run, text in zip(runs, texts, strict=True):
            if text or len(runs) == 1:
                font = font_name if not chinese or HAN.search(text) else None
                style_run(run, font_name=font, font_size_pt=font_size_pt, bold=bold, east_asia_only=chinese)


def edit_paragraph(document, paragraph_index, edit, *, original=None):
    element = find_paragraph_element(document, paragraph_index)
    if edit.revert:
        if original is None:
            raise ValueError("无法读取原始段落。")
        original_element = deepcopy(find_paragraph_element(original, paragraph_index))
        element.getparent().replace(element, original_element)
        return original_element
    if edit.text is not None:
        replace_text(element, edit.text)
    style_paragraph(element, **edit.model_dump(exclude={"revert", "text"}, exclude_none=True))
    return element


def update_paragraph_ir(previous, document, element, index, *, restored=None):
    old = previous.paragraphs[index]
    revised = restored.model_copy(deep=True) if restored is not None else _paragraph(
        element, _Styles(document), index, old.section_index, old.page_no,
    )
    revised.in_table = old.in_table
    revised.section_index, revised.page_no = old.section_index, old.page_no
    current = previous.model_copy(update={"paragraphs": [p.model_copy() for p in previous.paragraphs]})
    current.paragraphs[index] = revised
    return analyze_document(current)


def _applicable(document, rule):
    paragraphs = document.paragraphs
    code, params = rule.rule_code, rule.params
    if code == "PAGE_MARGINS":
        return bool(document.page_setups)
    if code == "HEADER_FORMAT":
        body_sections = {p.section_index for p in paragraphs if p.section_key == "body" and p.text}
        return any(setup.section_index in body_sections for setup in document.page_setups)
    if code == "PAGE_NUMBER_STYLE":
        sections = set(params["roman_sections"]) | set(params["decimal_sections"])
        return any(p.text and p.section_key in sections and p.section_index is not None for p in paragraphs)
    if code == "LINE_SPACING_MIN":
        return any(p.text and not p.in_table and p.role != "other" and p.line_spacing_pt is not None for p in paragraphs)
    if code in SECTION_STYLES:
        return any(p.text and p.section_key == params["section_key"] for p in paragraphs)
    if code == "BODY_TYPOGRAPHY" and params.get("require_consistent_size"):
        return any(p.text and p.section_key in params["section_keys"] and p.role in {"body_text", "reference_entry"}
                   and p.font_size_pt is not None for p in paragraphs)
    if code == "ABSTRACT_CONTENT_RULES":
        return any(p.section_key == "abstract_cn" for p in paragraphs)
    return True


def evaluate_incremental(document, previous, previous_violations, rule_items, paragraph_index):
    """Reuse layout findings and evaluate isolated styling on one paragraph when possible."""
    old = previous.paragraphs[paragraph_index]
    new = document.paragraphs[paragraph_index]
    text_changed = old.text != new.text
    roles_changed = any((a.section_key, a.role, bool(a.text)) != (b.section_key, b.role, bool(b.text))
                        for a, b in zip(previous.paragraphs, document.paragraphs, strict=True))
    affected = {"COVER_ELEMENTS"} if old.section_key == "cover" or new.section_key == "cover" else set()
    if text_changed or roles_changed:
        affected |= TEXT_RULES | {"FIGURE_TABLE_CAPTION"}
    if old.alignment != new.alignment and new.role in {"figure_caption", "table_caption"}:
        affected.add("FIGURE_TABLE_CAPTION")
    if roles_changed:
        affected |= {"HEADER_FORMAT", "PAGE_NUMBER_STYLE"}
    elif text_changed and (
        new.role == "chapter_heading" or new.role == "section_heading" and new.section_key == "body"
        and (chapter_number(old.text) is not None or chapter_number(new.text) is not None)
    ):
        affected.add("HEADER_FORMAT")

    before = {}
    for finding in previous_violations:
        if isinstance(finding, dict):
            finding = Violation.model_validate(finding)
        before.setdefault(finding.rule_code, []).append(finding)
    isolated = document.model_copy(update={"paragraphs": [new]})
    findings = []
    passed = skipped = 0
    for item in rule_items:
        rule = _RuleConfig.from_item(item)
        code = rule.rule_code
        if not rule.enabled or rule.applies_to not in {"both", document.file_ext}:
            skipped += 1
            continue
        current = before.get(code, [])
        applies = _applicable(document, rule)
        if code in affected or code in LOCAL_RULES and (roles_changed or rule.params.get("require_consistent_size")):
            fresh = evaluate(document, [item])
            current, applies = fresh.violations, fresh.skipped_rules_count == 0
        elif code in LOCAL_RULES and applies:
            fresh = evaluate(isolated, [item])
            current = [item for item in current if item.location.get("paragraph_index") != paragraph_index]
            current.extend(fresh.violations)
            current.sort(key=lambda finding: finding.location.get("paragraph_index", -1))
        if applies:
            passed += not current
            findings.extend(current)
        else:
            skipped += 1
    errors = sum(finding.severity == "error" for finding in findings)
    applicable = len(rule_items) - skipped
    return EvaluationResult(
        verdict="fail" if errors else "pass", score=round(100 * passed / applicable, 2) if applicable else 100,
        error_count=errors, warning_count=len(findings) - errors, passed_rules_count=passed,
        skipped_rules_count=skipped, violations=findings,
    )


def resolved_findings(before, after):
    def key(finding):
        location = finding.location
        return (finding.rule_code, finding.expected, location.get("paragraph_index"),
                location.get("section"), location.get("page"), location.get("section_index"))
    remaining = Counter(key(f) for f in before if f.severity == "error")
    remaining.subtract(key(f) for f in after if f.severity == "error")
    return sum(count for count in remaining.values() if count > 0)


def paragraph_diff(before, after, source, summary):
    fields = {"font_name": "字体", "font_size_pt": "字号", "bold": "加粗",
              "alignment": "对齐", "line_spacing_pt": "行距", "line_spacing_rule": "行距模式"}
    styles = [f"{label}：{getattr(before, name)} → {getattr(after, name)}" for name, label in fields.items()
              if getattr(before, name) != getattr(after, name)]
    if (not styles and before.text == after.text
            and (before.runs != after.runs or before.toc_page_runs != after.toc_page_runs)):
        styles.append("段内文字格式已调整")
    if before.text == after.text and not styles:
        return None
    return ParagraphDiff(
        paragraph_index=after.index, page_no=after.page_no, section_key=after.section_key,
        before_text=before.text, after_text=after.text, style_changes=styles, source=source, summary=summary,
    )
