"""Handlers for the rule codes stored in rule_items.

A handler returns findings, an empty list for a pass, or None if the evidence
needed by the rule is unavailable. Thresholds and policy choices come from params.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import re
import unicodedata
from typing import Literal

from app.engine.utils import FONT_SUFFIX, HAN, SECTION_NAMES, chapter_number, count_chinese_chars, normalize_font_name, pdf_page_parities
from app.parsers.base import CN_KEYWORDS, cover_elements

SECTION = SECTION_NAMES.get
FONT_NAMES = {"simsun": "宋体", "simhei": "黑体", "times_new_roman": "Times New Roman",
              "microsoft_yahei": "微软雅黑"}
ALIGNMENTS = {"center": "居中", "left": "左对齐", "right": "右对齐", "justify": "两端对齐"}
NUMBERS = {"roman": "罗马数字", "decimal": "阿拉伯数字", "none": "未识别到页码"}
POSITIONS = {"header": "页眉", "footer": "页脚", "below": "下方", "above": "上方", "unknown": "位置无法确认"}
COVER_ELEMENTS = {
    "school_code": "学校编号", "library_classification": "图书分类号", "title_cn": "中文题目",
    "title_en": "英文题目", "author_name": "作者姓名", "major": "专业",
    "supervisor": "导师", "student_id": "学号", "title": "论文题目", "keywords": "关键词",
}
_NON_PROSE_UNITS = {"footnote", "formula", "scanned_page"}
CHINESE_BODY_MIN_CHARS = 200
_CODE_FONT_FAMILIES = (
    "couriernew", "courier", "consolas", "menlo", "monaco", "lucidaconsole", "liberationmono",
    "dejavusansmono", "cascadiamono", "cascadiacode", "sourcecodepro", "jetbrainsmono", "firacode",
    "nimbusmonops", "sfmono", "ibmplexmono", "robotomono", "monospace",
)
SIDES = {"top": "上", "bottom": "下", "left": "左", "right": "右"}


@dataclass
class Finding:
    expected: str
    actual: str
    message: str
    location: dict = field(default_factory=dict)
    severity: Literal["error", "warning"] | None = None


def _location(paragraph=None, *, page=None, section=None, section_index=None, excerpt=None):
    if paragraph is not None:
        page = getattr(paragraph, "page_no", None) or page
        section = getattr(paragraph, "section_key", None) or section
        section_index = getattr(paragraph, "section_index", section_index)
        excerpt = getattr(paragraph, "text", None) or getattr(paragraph, "raw_text", None) or excerpt
    bbox = getattr(paragraph, "bbox", None)
    values = {
        "page": page, "paragraph_index": getattr(paragraph, "index", None),
        "section": section, "section_index": section_index, "excerpt": excerpt[:100] if excerpt else None,
        "bbox": list(bbox) if bbox is not None else None,
        "page_end": getattr(paragraph, "page_end", None) if getattr(paragraph, "page_end", None) != page else None,
    }
    return {key: value for key, value in values.items() if value is not None}


def _near(value, target, tolerance):
    return value is not None and abs(value - target) <= tolerance + 1e-6


def _value(value, unit=""):
    return "未识别" if value is None else f"{value:g}{unit}"


def _compact(text):
    return re.sub(r"[\s\u3000]+", "", unicodedata.normalize("NFKC", text))


def _style(allowed, actual, tolerance):
    expected = []
    observed = []
    for key, label in (("font_name", "字体"), ("font_size_pt", "字号"), ("bold", "加粗"),
                       ("alignment", "对齐"), ("text", "标题文字")):
        if key not in allowed:
            continue
        target = allowed[key]
        value = getattr(actual, key, None)
        if key == "font_size_pt":
            if _near(value, target, tolerance):
                continue
            description = f"{target:g} pt（容差 ±{tolerance:g} pt）"
            current = _value(value, " pt")
        elif key == "font_name":
            target, value = normalize_font_name(target), normalize_font_name(value)
            if target == value:
                continue
            description = FONT_NAMES.get(target, target)
            current = FONT_NAMES.get(value, value)
        elif key == "bold":
            if target == value:
                continue
            description = "是" if target else "否"
            current = ("是" if value else "否") if value is not None else None
        elif key == "alignment":
            if target == value:
                continue
            description = ALIGNMENTS.get(target, target)
            current = ALIGNMENTS.get(value, value)
        else:
            if value and _compact(value) == _compact(target):
                continue
            description, current = target, value
        expected.append(f"{label}为{description}")
        observed.append(f"{label}为{current or '未识别'}")
    return "，".join(expected), "，".join(observed)


def _typography(paragraph, allowed, tolerance, label, *, runs=None, sample=None, chinese_context=None,
                ignore_scripts=False, locate_runs=False, alternative_font=None):
    sample = sample if sample is not None else paragraph
    runs = paragraph.runs if runs is None else runs
    run_rules = {key: value for key, value in allowed.items() if key in {"font_name", "font_size_pt", "bold"}}
    if chinese_context is None:
        chinese_context = bool(HAN.search(paragraph.text))
    chinese_font = normalize_font_name(run_rules.get("font_name")) in {"simsun", "simhei"}
    latin_rules = {key: value for key, value in run_rules.items() if key != "font_name"}
    entries = []
    for run in runs:
        if ignore_scripts and run.is_script:
            continue
        if not any(character.isalnum() for character in run.text):
            continue
        targets = latin_rules if chinese_font and chinese_context and not HAN.search(run.text) else run_rules
        entries.append((targets, run))
    if not entries and not (ignore_scripts and runs and all(run.is_script for run in runs)):
        entries = [(run_rules, sample)]
    entries.append(({key: value for key, value in allowed.items() if key not in run_rules}, paragraph))
    failures_by_page = defaultdict(list)
    for targets, actual in entries:
        if alternative_font and "font_name" in targets and alternative_font(normalize_font_name(actual.font_name)):
            targets = {key: value for key, value in targets.items() if key != "font_name"}
        wanted, observed = _style(targets, actual, tolerance)
        if wanted:
            page = getattr(actual, "page_no", None) if locate_runs else None
            failures_by_page[page or paragraph.page_no].append((wanted, observed, actual))
    findings = []
    for page, failures in failures_by_page.items():
        location = _location(paragraph)
        if locate_runs:
            fragments = [item for _, _, item in failures if item is not paragraph]
            if fragments:
                location["highlight_excerpt"] = " ".join(item.text.strip() for item in fragments)[:100]
            if page is not None and page != paragraph.page_no:
                location["page"] = page
                location.pop("bbox", None)
            boxes = list(zip(*(item.bbox for item in fragments if getattr(item, "bbox", None))))
            if boxes:
                location["bbox"] = [min(boxes[0]), min(boxes[1]), max(boxes[2]), max(boxes[3])]
            if fragments or page != paragraph.page_no:
                location.pop("page_end", None)
        findings.append(Finding(
            "；".join(dict.fromkeys(wanted for wanted, _, _ in failures)),
            "；".join(dict.fromkeys(actual for _, actual, _ in failures)),
            f"请调整{label}的排版。", location,
        ))
    return findings


def file_name(doc, params):
    if re.fullmatch(params["pattern"], doc.file_name):
        return []
    return [Finding(f"文件名匹配 {params['pattern']}", f"文件名为「{doc.file_name}」",
                    "请按规范重命名论文文件。", _location(excerpt=doc.file_name))]


def image_only(doc, params):
    if params["allow_image_only"] or not doc.is_image_only_pdf:
        return []
    return [Finding("正文含可选择的文本层", f"PDF 缺少可用正文文本层，含文本页占比 {doc.stats.text_page_ratio:.0%}",
                    "请导出含文本层的 PDF 或进行文字识别。", _location(excerpt=doc.file_name))]


def page_size(doc, params):
    expected = f"纸张为 {params['width_mm']:g} × {params['height_mm']:g} mm（容差 ±{params['tolerance_mm']:g} mm）"
    if not doc.page_setups:
        return [Finding(expected, "未识别到页面尺寸", "请检查页面设置。")]
    return [
        Finding(expected, f"实际尺寸为 {_value(page.width_mm)} × {_value(page.height_mm)} mm",
                "请在页面设置中调整纸张尺寸。", _location(page=page.page_no, section_index=page.section_index))
        for page in doc.page_setups
        if not (_near(page.width_mm, params["width_mm"], params["tolerance_mm"])
                and _near(page.height_mm, params["height_mm"], params["tolerance_mm"]))
    ]


def page_margins(doc, params):
    tolerance = params[f"{doc.file_ext}_tolerance_mm"]
    findings = []
    observed = False
    for page in doc.page_setups:
        wrong = []
        for side, label in SIDES.items():
            target = params[f"{side}_mm"]
            value = getattr(page, f"{side}_margin_mm")
            if value is None and doc.file_ext == "pdf":
                continue
            observed = True
            if not _near(value, target, tolerance):
                wrong.append((f"{label}边距 {target:g} mm（容差 ±{tolerance:g} mm）",
                              f"{label}边距 {_value(value, ' mm')}"))
        if wrong:
            findings.append(Finding(
                "，".join(item[0] for item in wrong), "，".join(item[1] for item in wrong),
                "请调整页面边距。" if doc.file_ext == "docx" else "请根据 PDF 版面估算结果核对源文件的页边距。",
                _location(page=page.page_no, section_index=page.section_index),
            ))
    return findings if observed else None


def line_spacing(doc, params):
    if doc.file_ext == "pdf" and params["pdf_measurement"] != "baseline":
        return None
    tolerance = params["docx_tolerance_pt"]
    if doc.file_ext == "pdf":
        tolerance = params.get("pdf_tolerance_pt", tolerance)
    minimum = params["min_pt"]
    paragraphs = [
        p for p in doc.paragraphs if p.text and not (p.in_table or p.in_figure)
        and p.unit_kind not in _NON_PROSE_UNITS | {"underline_row"}
        and p.role not in {"other", "footnote", "scanned_page", "underline_row"} and p.object_kind != "formula"
        and p.line_spacing_pt is not None and (doc.file_ext == "docx" or p.line_spacing_rule == "estimated")
    ]
    if not paragraphs:
        return None
    findings = []
    for paragraph in paragraphs:
        spacing = paragraph.line_spacing_pt
        label = "段落行距"
        anchor = None
        if doc.file_ext == "pdf":
            label = "段内最小基线间距约"
            credible_gap = max(5, (paragraph.font_size_pt or 0) * .72)
            if paragraph.line_spacing_samples:
                anchor = min((sample for sample in paragraph.line_spacing_samples if sample.spacing_pt >= credible_gap),
                             key=lambda sample: sample.spacing_pt, default=None)
                if anchor is None:
                    continue
                spacing = anchor.spacing_pt
            elif paragraph.line_spacings_pt:
                spacing = min((gap for gap in paragraph.line_spacings_pt if gap >= credible_gap), default=None)
                if spacing is None:
                    continue
        if spacing + tolerance < minimum:
            location = _location(paragraph)
            if anchor is not None:
                location.update(page=anchor.page_no, bbox=list(anchor.bbox))
                location.pop("page_end", None)
                if anchor.page_no != paragraph.page_no:
                    location.pop("excerpt", None)
            findings.append(Finding(
                f"行距至少 {minimum:g} pt（容差 {tolerance:g} pt）", f"{label} {spacing:.2f} pt",
                "请增大段落行距。", location,
            ))
    return findings


def _header_style(item, params, keys, location):
    expected, actual = _style({key: params[key] for key in keys if key in params}, item,
                              params["font_size_tolerance_pt"])
    return [Finding(expected, actual, "请调整页眉排版。", location)] if expected else []


def _physical_pages(paragraph):
    if paragraph.page_no is None:
        return ()
    return range(paragraph.page_no, (paragraph.page_end or paragraph.page_no) + 1)


def header_format(doc, params):
    headers = doc.headers_footers
    findings = []
    pdf = doc.file_ext == "pdf"
    fields = set(params["pdf_fields"]) if pdf else {"odd_text", "even_text", "font_size_pt", "font_name", "alignment"}
    even_pattern = params.get("even_pattern")

    if pdf:
        chapters = [p for p in doc.paragraphs if p.role in {"chapter_heading", "section_heading"}
                    and chapter_number(p.text) is not None]
        body_pages = sorted({page for p in doc.paragraphs if p.section_key == "body" and (p.text or p.object_kind)
                             for page in _physical_pages(p)})
        if not body_pages:
            return None
        candidates_by_page = defaultdict(list)
        for item in headers.odd_headers + headers.even_headers:
            candidates_by_page[item.page_no].append(item)
        for page, parity in pdf_page_parities(body_pages, headers.page_numbers):
            location = _location(page=page, section="body")
            candidates = candidates_by_page[page]
            chapter = next((p for p in reversed(chapters) if p.page_no is not None and p.page_no <= page), None)
            findings.extend(_header_slot(candidates, params, fields, bool(parity), [chapter] if chapter else [],
                                         location, even_pattern))
        return findings

    chapters = [p for p in doc.paragraphs if p.role == "chapter_heading" or (
        p.role == "section_heading" and p.section_key == "body" and chapter_number(p.text) is not None
    )]
    body_sections = {p.section_index for p in doc.paragraphs if p.section_key == "body" and p.text}
    targets = [setup for setup in doc.page_setups if setup.section_index in body_sections]
    if not targets:
        return None
    for setup in targets:
        index = setup.section_index
        location = _location(section_index=index, section="body")
        if setup.odd_even_headers != params["odd_even_headers"]:
            findings.append(Finding(
                "启用奇偶页不同页眉" if params["odd_even_headers"] else "采用统一页眉",
                "已启用奇偶页不同页眉" if setup.odd_even_headers else "未启用奇偶页不同页眉",
                "请调整分节的奇偶页页眉设置。", location,
            ))
        if not _near(setup.header_distance_mm, params["header_distance_mm"], .02):
            findings.append(Finding(
                f"页眉距边界 {params['header_distance_mm']:g} mm",
                f"实际距离 {_value(setup.header_distance_mm, ' mm')}", "请调整页眉距边界的距离。", location, severity="warning",
            ))
        local_chapters = [p for p in chapters if p.section_index == index]
        if not local_chapters:
            local_chapters = [p for p in chapters if p.section_index is not None and index is not None and p.section_index < index][-1:]
        odd = headers.odd_headers if setup.odd_even_headers else headers.default_headers
        findings.extend(_header_slot([item for item in odd if item.section_index == index],
                                     params, fields, True, local_chapters, location, even_pattern))
        if params["odd_even_headers"]:
            findings.extend(_header_slot([item for item in headers.even_headers if item.section_index == index],
                                         params, fields, False, [], location, even_pattern))
    return findings


def _header_slot(items, params, fields, odd, chapters, location, even_pattern):
    side = "奇数页" if odd else "偶数页"
    text_field = "odd_text" if odd else "even_text"
    expected = "页眉显示本章章号及标题" if odd else f"页眉匹配 {even_pattern}"
    if not items:
        return [Finding(f"{side}{expected}", "未识别到页眉", f"请设置{side}页眉。", location)]
    selected = items[0]
    matches = items
    if text_field in fields:
        if odd and params.get("odd_text_source") == "chapter_heading":
            titles = {_compact(p.text) for p in chapters}
            matches = [item for item in items if item.chapter_field or _compact(item.text) in titles]
        elif not odd and even_pattern:
            matches = [item for item in items if re.fullmatch(even_pattern, item.text.strip())
                       or re.fullmatch(even_pattern, _compact(item.text))]
        if not matches:
            return [Finding(f"{side}{expected}", f"页眉文字为「{selected.text}」", f"请修改{side}页眉文字。",
                            location | _location(selected))]
        selected = matches[0]
    return _header_style(selected, params, fields, location | _location(selected))


def double_border(doc, params):
    headers = doc.headers_footers
    items = [*headers.odd_headers, *headers.even_headers, *headers.default_headers]
    style = "双横线" if params["style"] == "double" else params["style"]
    return [Finding(
        f"页眉下边框为{style}，线宽 {params['width_pt']:g} pt（容差 ±{params['tolerance_pt']:g} pt）",
        f"下边框样式为{item.bottom_border_style or '无'}，线宽 {_value(item.bottom_border_pt, ' pt')}",
        "请调整页眉下边框的线型及宽度。",
        _location(item),
    ) for item in items if item.bottom_border_style != params["style"]
        or not _near(item.bottom_border_pt, params["width_pt"], params["tolerance_pt"])]


def page_numbers(doc, params):
    formats = {key: "roman" for key in params["roman_sections"]} | {
        key: "decimal" for key in params["decimal_sections"]
    }
    pdf = doc.file_ext == "pdf"
    blank_pages = {page.page_no for page in doc.page_setups if page.is_blank} if pdf else set()
    indexed = defaultdict(list)
    for item in doc.headers_footers.page_numbers:
        indexed[item.page_no if pdf else item.section_index].append(item)
    required = defaultdict(dict)
    for paragraph in doc.paragraphs:
        if not paragraph.text or paragraph.section_key not in formats:
            continue
        for index in _physical_pages(paragraph) if pdf else (paragraph.section_index,):
            if index is not None and index not in blank_pages:
                required[index].setdefault(formats[paragraph.section_key], paragraph)
    if not required:
        return None
    if pdf:
        # Also check pages with only graphics between numbered text pages in the same group.
        sorted_pages = sorted(required)
        for previous, current in zip(sorted_pages, sorted_pages[1:]):
            if required[previous].keys() == required[current].keys():
                for page in range(previous + 1, current):
                    if page not in blank_pages:
                        required[page] = required[previous]
    result = []
    for index, format_paragraphs in sorted(required.items()):
        layouts = defaultdict(list)
        for item in indexed[index]:
            layouts[item.variant].append(item)
        for fmt, paragraph in format_paragraphs.items():
            for variant, candidates in (layouts or {"default": []}).items():
                wrong = [item for item in candidates if not (
                    item.num_format == fmt and item.alignment == params["alignment"] and item.position == params["position"]
                )]
                if candidates and not wrong:
                    continue
                item = wrong[0] if wrong else None
                recognized = item and item.num_format != "none" and (not pdf or item.raw_text.strip())
                actual = "未识别到页码"
                variant_text = {"first": "首页", "even": "偶数页", "default": ""}[variant]
                location = _location(page=index if pdf else None, section=paragraph.section_key,
                                     section_index=None if pdf else index)
                if recognized:
                    actual = (f"{NUMBERS[item.num_format]}，位于{POSITIONS[item.position]}，"
                              f"{ALIGNMENTS.get(item.alignment, '对齐未知')}")
                    location.update(_location(item))
                    if not item.raw_text.strip():
                        location.pop("excerpt", None)
                result.append(Finding(
                    f"{variant_text}{POSITIONS.get(params['position'], params['position'])}页码为"
                    f"{NUMBERS[fmt]}且{ALIGNMENTS.get(params['alignment'], params['alignment'])}",
                    actual, f"请调整{SECTION(paragraph.section_key, paragraph.section_key)}的页码格式与位置。", location,
                ))
    return result


def required_sections(doc, params):
    keys = {section.key for section in doc.sections}
    cover_end = max((p.page_no for p in doc.paragraphs
                     if p.page_no and p.section_key == "cover" and p.text), default=1)
    module_start = min((s.page_start for s in doc.sections if s.page_start
                        and s.key in {"abstract_cn", "abstract_en", "toc", "introduction", "body"}), default=0)
    scans = [p for p in doc.paragraphs if p.unit_kind == "scanned_page" and p.page_no]
    front_scans = [p for p in scans if cover_end < p.page_no < module_start]
    findings = []
    for key in params["required_sections"]:
        if key in keys:
            continue
        label = SECTION(key, key)
        if front_scans and key in {"declaration", "defense_signature"}:
            pages = "、".join(str(p.page_no) for p in front_scans)
            findings.append(Finding(f"包含{label}", f"检测到第 {pages} 页为扫描图像页，疑似含{label}。",
                                    "请人工核验扫描页内容。", _location(front_scans[0]) | {"section": key},
                                    severity="warning"))
        else:
            findings.append(Finding(f"包含{label}", f"未识别到{label}", f"请补充{label}。", _location(section=key)))
    if module_start and not doc.is_image_only_pdf:
        for scan in scans:
            if scan.page_no >= module_start and scan.page_no > cover_end:
                findings.append(Finding("图文版式可核验", f"第 {scan.page_no} 页为扫描图像页",
                                        "建议人工核验该页图文排版。", _location(scan), severity="warning"))
    elements = cover_elements(doc.paragraphs)
    found = {
        "title": any(elements[key][0] for key in ("title_cn", "title_en") if key in elements),
        "keywords": any(p.role in {"keywords_cn", "keywords_en"} and
                        (CN_KEYWORDS.sub("", p.text).strip() if p.role == "keywords_cn"
                         else re.sub(r"^key\s*words?\s*[:：]?\s*", "", p.text, flags=re.I).strip())
                        for p in doc.paragraphs),
    }
    for key in params.get("required_elements", []):
        label = COVER_ELEMENTS.get(key, key)
        if not found.get(key, key in elements):
            findings.append(Finding(f"包含{label}", f"未识别到{label}", f"请补充{label}。"))
    return findings


def section_order(doc, params):
    paragraphs = {p.index: p for p in doc.paragraphs}
    order = {key: i for i, key in enumerate(params["section_order"])}
    last = None
    results = []
    for section in doc.sections:
        key = section.key
        if key not in order:
            continue
        if last is not None and order[key] < order[last]:
            results.append(Finding(
                f"{SECTION(key, key)}位于{SECTION(last, last)}之前",
                f"{SECTION(key, key)}出现在{SECTION(last, last)}之后",
                "请按规范重新排列文档模块。",
                _location(paragraphs.get(section.start_paragraph_index),
                          page=section.page_start, section=key, excerpt=section.title)
                | {"paragraph_index": section.start_paragraph_index},
            ))
        else:
            last = key
    return results


def cover(doc, params):
    elements = cover_elements(doc.paragraphs)
    findings = []
    for key in params["required_elements"]:
        if key not in elements:
            label = COVER_ELEMENTS.get(key, key)
            findings.append(Finding(f"封面含{label}", f"未识别到{label}", f"请在封面补充{label}。", _location(section="cover")))
        elif not elements[key][0]:
            paragraph = elements[key][1]
            actual = "下划线槽位未填" if paragraph.has_underline else "已识别标签，字段为空"
            label = COVER_ELEMENTS.get(key, key)
            findings.append(Finding(f"封面含{label}", actual, f"请填写封面的{label}。", _location(paragraph)))
    if "school_code" in elements and elements["school_code"][0]:
        code, p = elements["school_code"]
        if _compact(code) != str(params["school_code"]):
            findings.append(Finding(f"学校编号为 {params['school_code']}", f"学校编号为 {code}",
                                    "请更正封面的学校编号。", _location(p)))
    if "title_cn" in elements and elements["title_cn"][0]:
        title, p = elements["title_cn"]
        maximum = params["title_cn_max_chinese_chars"]
        count = count_chinese_chars(title)
        if count > maximum:
            findings.append(Finding(f"中文题目至多 {maximum} 个汉字", f"中文题目有 {count} 个汉字",
                                    "请精简封面中文题目。", _location(p)))
        findings.extend(_typography(p, params["title_cn_style"], params["font_size_tolerance_pt"], "封面中文题目"))
    for paragraph in doc.paragraphs:
        if (paragraph.section_key in {"declaration", "defense_signature"} and paragraph.unit_kind == "underline_row"
                and paragraph.field_label == "signature" and paragraph.has_underline
                and not (paragraph.field_value or paragraph.has_signature_image)):
            findings.append(Finding("签名栏已签署", "签名下划线为空", "请人工核验签名栏。",
                                    _location(paragraph), severity="warning"))
    return findings


def section_typography(doc, params):
    key = params["section_key"]
    label = SECTION(key, key)
    tolerance = params["font_size_tolerance_pt"]
    paragraphs = [p for p in doc.paragraphs if p.section_key == key and p.text and not (p.in_figure or p.in_table)
                  and p.unit_kind not in _NON_PROSE_UNITS]
    if not paragraphs:
        return None
    findings = []
    for p in paragraphs:
        if p.role == "section_heading":
            findings.extend(_typography(p, params["heading"], tolerance, f"{label}标题", ignore_scripts=True))
        elif p.role == "body_text" and "body" in params:
            findings.extend(_typography(p, params["body"], tolerance, f"{label}正文", ignore_scripts=True))
        elif p.role in {"keywords_cn", "keywords_en"} and "keywords" in params:
            findings.extend(_typography(p, params["keywords"], tolerance, f"{label}关键词", ignore_scripts=True))
        elif p.role == "toc_entry" and "entry" in params:
            findings.extend(_typography(p, params["entry"], tolerance, "目录条目",
                                        runs=p.toc_entry_runs or p.runs, ignore_scripts=True))
            if p.toc_page_number is None:
                findings.append(Finding("目录条目显示页码", "未识别到目录页码", "请更新目录页码。", _location(p)))
            else:
                findings.extend(_typography(p, params["page_number"], tolerance, "目录页码",
                                            runs=p.toc_page_runs, sample=p.toc_page_style, ignore_scripts=True))
    return findings


def heading_typography(doc, params):
    findings = []
    base_style = {key: params[key] for key in ("font_name", "bold") if key in params}
    for paragraph in doc.paragraphs:
        if paragraph.section_key in params["section_keys"] and paragraph.role in params["roles"]:
            style = base_style | params["roles"][paragraph.role]
            findings.extend(_typography(paragraph, style, params["font_size_tolerance_pt"], "章节标题"))
    return findings


def _western_body_font(name):
    if name == "times_new_roman":
        return True
    compact = (name or "").replace("_", "")
    return any((compact == family or compact.startswith(family) and FONT_SUFFIX.fullmatch(compact[len(family):]))
               for family in _CODE_FONT_FAMILIES)


def body_typography(doc, params):
    allowed = {key: params[key] for key in ("font_name", "font_size_pt", "bold", "alignment") if key in params}
    paragraphs = [p for p in doc.paragraphs if p.section_key in params["section_keys"]
                  and p.role in {"body_text", "reference_entry"} and p.text and not (p.in_table or p.in_figure)
                  and p.unit_kind not in _NON_PROSE_UNITS and p.role != "footnote" and p.object_kind != "formula"]
    tolerance = params["font_size_tolerance_pt"]
    chinese_body = doc.stats.body_chinese_chars >= CHINESE_BODY_MIN_CHARS
    chinese_reference_context = chinese_body or any(
        p.role == "body_text" and p.section_key in {"introduction", "body", "conclusion"} and HAN.search(p.text)
        for p in doc.paragraphs
    )
    wants_simsun = normalize_font_name(allowed.get("font_name")) == "simsun"

    def alternative_font(paragraph):
        if not wants_simsun or HAN.search(paragraph.text):
            return None
        if chinese_body:
            return _western_body_font
        # Preserve the narrower reference exception for short Chinese documents.
        if (chinese_reference_context and paragraph.role == "reference_entry"
                and re.search(r"[A-Za-z]", paragraph.text)):
            return lambda name: name == "times_new_roman"
        return None
    if params.get("require_consistent_size"):
        sizes = [p.font_size_pt for p in paragraphs if p.font_size_pt is not None]
        if not sizes:
            return None
        # Use the most frequent paragraph size as the reference for each run.
        allowed = allowed | {"font_size_pt": Counter(sizes).most_common(1)[0][0]}
    if doc.file_ext != "pdf":
        return [finding for p in paragraphs for finding in _typography(
            p, allowed, tolerance, "正文", ignore_scripts=True, alternative_font=alternative_font(p),
        )]

    groups = defaultdict(list)
    for paragraph in paragraphs:
        start = paragraph.paragraph_start_index
        groups[paragraph.index if start is None else start].append(paragraph)
    findings = []
    for lines in groups.values():
        chinese = any(HAN.search(line.text) for line in lines)
        group_findings = {}
        for line in lines:
            for finding in _typography(line, allowed, tolerance, "正文", chinese_context=chinese,
                                       ignore_scripts=True, locate_runs=True, alternative_font=alternative_font(line)):
                key = (finding.expected, finding.actual, finding.location.get("page"))
                if key in group_findings:
                    locations = group_findings[key].location
                    locations.setdefault("paragraph_indices", [locations["paragraph_index"]]).append(line.index)
                    highlights = dict.fromkeys(filter(None, (locations.get("highlight_excerpt"),
                                                             finding.location.get("highlight_excerpt"))))
                    if highlights:
                        locations["highlight_excerpt"] = "；".join(highlights)[:100]
                else:
                    group_findings[key] = finding
        findings.extend(group_findings.values())
    return findings


def abstract_content(doc, params):
    paragraphs = [p for p in doc.paragraphs if p.section_key == "abstract_cn"]
    if not paragraphs:
        return None
    findings = []
    section_location = _location(page=paragraphs[0].page_no, section="abstract_cn")
    minimum = params["min_chinese_chars"]
    count = doc.stats.abstract_cn_chars
    if count < minimum:
        findings.append(Finding(f"中文摘要至少 {minimum} 个汉字", f"摘要有 {count} 个汉字",
                                "请补充中文摘要正文。", section_location))
    for p in paragraphs:
        if p.role == "body_text" and re.search(params["forbidden_citation_pattern"], p.text):
            findings.append(Finding("摘要中不含参考文献序号", "摘要中出现参考文献序号",
                                    "请去除摘要中的参考文献序号。", _location(p)))
    keywords = next((p for p in paragraphs if p.role == "keywords_cn"), None)
    text = CN_KEYWORDS.sub("", keywords.text).strip() if keywords else ""
    separator = params["keyword_separator"]
    parts = [word.strip() for word in text.split(separator)] if text else []
    size = count_chinese_chars(text)
    low, high = params["keyword_min_count"], params["keyword_max_count"]
    max_chars = params["keyword_max_total_chinese_chars"]
    other_separators = set("；;，,、") - set(separator)
    if not (low <= len(parts) <= high and all(parts) and size <= max_chars
            and not any(character in text for character in other_separators)):
        findings.append(Finding(
            f"{low}–{high} 个关键词，用「{separator}」分隔，合计至多 {max_chars} 个汉字",
            f"按指定分隔符得到 {len(parts)} 项、共 {size} 个汉字，原文为「{text or '未识别'}」",
            "请核对中文关键词的数量、长度及分隔符。", _location(keywords) if keywords is not None else section_location,
        ))
    return findings


def word_count(doc, params):
    findings = []
    for prefix, key, label, count in (
        ("intro", "introduction", "绪论", doc.stats.intro_chinese_chars),
        ("body", "body", "正文", doc.stats.body_chinese_chars),
    ):
        low = params.get(f"{prefix}_min_chinese_chars")
        high = params.get(f"{prefix}_max_chinese_chars")
        if (low is not None and count < low) or (high is not None and count > high):
            limits = "且".join(item for item in (f"至少 {low}" if low is not None else "",
                                                  f"至多 {high}" if high is not None else "") if item)
            p = next((p for p in doc.paragraphs if p.section_key == key and p.text), None)
            findings.append(Finding(f"{label}{limits} 个汉字", f"{label}有 {count} 个汉字",
                                    f"请调整{label}篇幅。", _location(page=p.page_no if p else None, section=key)))
    return findings


def _object_excerpt(item):
    name = "插图区域" if item.kind == "figure" else "表格区域"
    if item.inner_texts:
        sample = "、".join(text.strip() for text in item.inner_texts if text.strip())
        if sample:
            hint = "含文字" if item.kind == "figure" else "含"
            return f"{name}（{hint}：{sample[:85]}{('…' if len(sample) > 85 else '')}）"
    if box := item.object_bbox or item.bbox:
        return f"{name}（约 {box[2] - box[0]:g}×{box[3] - box[1]:g} pt）"
    return name


def figure_table(doc, params):
    paragraphs = {p.index: p for p in doc.paragraphs}
    grouped = defaultdict(list)
    findings = []
    formats = {"decimal": r"[0-9]+", "roman": r"[IVXLCDMivxlcdm]+"}
    token = formats[params["number_format"]]
    def order(index):
        paragraph = paragraphs.get(index)
        return ((paragraph.page_no or 0) if paragraph else 0, index)

    for item in sorted(doc.figures_tables, key=lambda item: order(item.paragraph_index)):
        if item.kind not in {"figure", "table"}:
            continue
        if not item.caption_text:
            if item.is_continuation:
                continue
            label = "图题" if item.kind == "figure" else "表题"
            location = _location(paragraphs.get(item.paragraph_index), excerpt=_object_excerpt(item))
            findings.append(Finding(f"对象附有{label}", f"未识别到{label}", f"请补充{label}。",
                                    location))
            continue
        grouped[item.kind].append(item)
        if item.caption_style_issue:
            findings.append(Finding(
                "题注格式规范", f"题注格式不规范：{item.caption_style_issue}", "请调整题注标识与编号格式。",
                _location(paragraphs.get(item.paragraph_index)),
            ))
        expected = params[item.kind]
        if item.relative_position != expected["position"] or item.alignment != expected["alignment"]:
            label = "图题" if item.kind == "figure" else "表题"
            position = POSITIONS[item.relative_position]
            align = ALIGNMENTS.get(item.alignment, "对齐未知")
            findings.append(Finding(
                f"{label}位于对象{POSITIONS[expected['position']]}并{ALIGNMENTS[expected['alignment']]}",
                f"{label}{position}，{align}", f"请核对{label}位置及对齐。", _location(paragraphs.get(item.paragraph_index)),
            ))

    def numeric(value):
        if value.isdecimal():
            return int(value)
        digits = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
        numbers = [digits[character] for character in value.upper()]
        return sum(-number if index + 1 < len(numbers) and number < numbers[index + 1] else number
                   for index, number in enumerate(numbers))

    for kind, items in grouped.items():
        continuous = 0
        chapters = defaultdict(int)
        possible = set(params["numbering_modes"])
        previous_number = None
        for item in items:
            number = unicodedata.normalize("NFKC", item.number_raw)
            if kind == "table" and (item.is_continuation or (
                doc.file_ext == "pdf" and number and number == previous_number
                and re.search(r"\(\s*continued\s*\)", item.caption_text, re.I)
            )):
                if number and previous_number and number != previous_number:
                    findings.append(Finding(f"续表沿用表号 {previous_number}", f"续表编号为 {number}",
                                            "请更正续表编号。", _location(paragraphs.get(item.paragraph_index))))
                continue
            previous_number = number
            single = re.fullmatch(f"({token})", number)
            paired = re.fullmatch(f"({token})[.\u2013\u2014-]({token})", number)
            matches = set()
            continuous += 1
            if single and numeric(single[1]) == continuous:
                matches.add("continuous")
            if paired:
                chapter, index = numeric(paired[1]), numeric(paired[2])
                chapters[chapter] += 1
                if chapter > 0 and (item.chapter_index is None or chapter == item.chapter_index) and index == chapters[chapter]:
                    matches.add("by_chapter")
            if possible & matches:
                possible &= matches
                continue
            modes = {"continuous": "连续编号", "by_chapter": "分章编号"}
            expected = "或".join(modes.get(mode, mode) for mode in params["numbering_modes"])
            label = "图" if kind == "figure" else "表"
            findings.append(Finding(
                f"{label}采用{NUMBERS[params['number_format']]}{expected}", f"实际题注编号为「{item.number_raw or '缺失'}」",
                f"请更正{label}题注编号并核对编号顺序。", _location(paragraphs.get(item.paragraph_index)),
            ))
    return sorted(findings, key=lambda item: (item.location.get("page") or 0,
                                              item.location.get("paragraph_index") or 0))


def references(doc, params):
    paragraphs = {p.index: p for p in doc.paragraphs}
    findings = []
    expected_index = params["numbering_start"]
    if not doc.references and any(s.key == "references" for s in doc.sections):
        return [Finding("参考文献包含可编号的文献条目", "参考文献区块为空", "请填写参考文献。", _location(section="references"))]
    for ref in doc.references:
        location = _location(paragraphs.get(ref.paragraph_index)) or _location(section="references", excerpt=ref.raw_text)
        match = re.match(params["number_pattern"], ref.raw_text)
        number = int(match[1]) if match and match.lastindex and match[1].isdecimal() else None
        if number is None or params["require_consecutive_numbers"] and number != expected_index:
            expected = (f"第 {expected_index} 条参考文献的编号匹配 {params['number_pattern']}"
                        if params["require_consecutive_numbers"] else f"编号匹配 {params['number_pattern']}")
            findings.append(Finding(expected, f"实际编号为 {number if number is not None else '未识别'}",
                                    "请按规定格式及顺序调整参考文献编号。", location))
        expected_index += 1
        if ref.type_code not in params["type_codes"] or (
            ref.carrier_code is not None and ref.carrier_code not in params["carrier_codes"]
        ):
            code = "/".join(value for value in (ref.type_code, ref.carrier_code) if value)
            findings.append(Finding(
                f"文献类型为 {'、'.join(params['type_codes'])}，可选载体为 {'、'.join(params['carrier_codes'])}",
                f"实际标识为「{code or '缺失'}」", "请填写规范的 GB/T 7714 文献类型及载体标识。", location,
            ))
        if ref.carrier_code == "OL" or ref.type_code == "EB" and ref.carrier_code is None:
            missing = []
            if params["electronic_require_url"] and not ref.has_url:
                missing.append("网址")
            if params["electronic_require_access_date"] and not ref.has_access_date:
                missing.append("检索日期")
            if missing:
                label = "及".join(missing)
                findings.append(Finding(f"电子文献含{label}", f"缺少{label}", f"请为电子文献补充{label}。", location))
    return findings


RULES_CATALOG = {
    "FILE_NAME_PATTERN": file_name,
    "PDF_NOT_IMAGE_ONLY": image_only,
    "PAGE_SIZE_A4": page_size,
    "PAGE_MARGINS": page_margins,
    "LINE_SPACING_MIN": line_spacing,
    "HEADER_FORMAT": header_format,
    "HEADER_DOUBLE_BORDER": double_border,
    "PAGE_NUMBER_STYLE": page_numbers,
    "REQUIRED_SECTIONS": required_sections,
    "SECTION_ORDER": section_order,
    "COVER_ELEMENTS": cover,
    "DECLARATION_TYPOGRAPHY": section_typography,
    "ABSTRACT_CN_TYPOGRAPHY": section_typography,
    "ABSTRACT_EN_TYPOGRAPHY": section_typography,
    "TOC_TYPOGRAPHY": section_typography,
    "HEADING_TYPOGRAPHY": heading_typography,
    "BODY_TYPOGRAPHY": body_typography,
    "ABSTRACT_CONTENT_RULES": abstract_content,
    "WORD_COUNT_REQUIREMENTS": word_count,
    "FIGURE_TABLE_CAPTION": figure_table,
    "REFERENCE_GBT7714": references,
}
