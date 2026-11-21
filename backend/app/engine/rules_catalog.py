"""Handlers for the rule codes stored in rule_items.

A handler returns findings, an empty list for a pass, or None if the evidence
needed by the rule is unavailable. Thresholds and policy choices come from params.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import re
import unicodedata

from app.engine.utils import HAN, SECTION_NAMES, count_chinese_chars, normalize_font_name
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
SIDES = {"top": "上", "bottom": "下", "left": "左", "right": "右"}


@dataclass
class Finding:
    expected: str
    actual: str
    message: str
    location: dict = field(default_factory=dict)


def _location(paragraph=None, *, page=None, section=None, section_index=None, excerpt=None):
    if paragraph is not None:
        page = paragraph.page_no
        section = paragraph.section_key
        section_index = paragraph.section_index
        excerpt = paragraph.text
    values = {
        "page": page, "paragraph_index": paragraph.index if paragraph is not None else None,
        "section": section, "section_index": section_index, "excerpt": excerpt[:100] if excerpt else None,
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


def _typography(paragraph, allowed, tolerance, label, *, runs=None, sample=None):
    sample = sample if sample is not None else paragraph
    runs = paragraph.runs if runs is None else runs
    run_rules = {key: value for key, value in allowed.items() if key in {"font_name", "font_size_pt", "bold"}}
    entries = []
    for run in runs:
        if not any(character.isalnum() for character in run.text):
            continue
        targets = run_rules
        if run_rules.get("font_name") in {"simsun", "simhei"} and HAN.search(paragraph.text) and not HAN.search(run.text):
            targets = {key: value for key, value in run_rules.items() if key != "font_name"}
        entries.append((targets, run))
    entries = entries or [(run_rules, sample)]
    entries.append(({key: value for key, value in allowed.items() if key not in run_rules}, paragraph))
    failures = list(dict.fromkeys(_style(wanted, actual, tolerance) for wanted, actual in entries))
    failures = [(wanted, actual) for wanted, actual in failures if wanted]
    if not failures:
        return []
    return [Finding(
        "；".join(dict.fromkeys(wanted for wanted, _ in failures)),
        "；".join(dict.fromkeys(actual for _, actual in failures)),
        f"请调整{label}的排版。", _location(paragraph),
    )]


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
    tolerance = params["docx_tolerance_pt"] if doc.file_ext == "docx" else .01
    minimum = params["min_pt"]
    paragraphs = [
        p for p in doc.paragraphs if p.text and not p.in_table and p.role != "other"
        and p.line_spacing_pt is not None and (doc.file_ext == "docx" or p.line_spacing_rule == "estimated")
    ]
    if not paragraphs:
        return None
    return [Finding(
        f"行距至少 {minimum:g} pt" + (f"（容差 {tolerance:g} pt）" if doc.file_ext == "docx" else ""),
        f"{'基线间距约' if doc.file_ext == 'pdf' else '段落行距'} {p.line_spacing_pt:.2f} pt",
        "请增大段落行距。", _location(p),
    ) for p in paragraphs if p.line_spacing_pt + tolerance < minimum]


def _header_style(item, params, keys, location):
    expected, actual = _style({key: params[key] for key in keys if key in params}, item,
                              params["font_size_tolerance_pt"])
    return [Finding(expected, actual, "请调整页眉排版。", location)] if expected else []


def header_format(doc, params):
    headers = doc.headers_footers
    chapters = [p for p in doc.paragraphs if p.role == "chapter_heading"]
    findings = []
    pdf = doc.file_ext == "pdf"
    fields = set(params["pdf_fields"]) if pdf else {"odd_text", "even_text", "font_size_pt", "font_name", "alignment"}
    even_pattern = params.get("even_pattern")

    if pdf:
        body_pages = sorted({p.page_no for p in doc.paragraphs if p.section_key == "body" and p.page_no is not None})
        if not body_pages:
            return None
        for page in body_pages:
            location = _location(page=page, section="body")
            number = next((item for item in headers.page_numbers if item.page_no == page
                           and item.num_format == "decimal" and item.position == "footer"), None)
            raw = re.search(r"\d+", number.raw_text) if number else None
            parity = int(raw[0]) % 2 if raw else page % 2
            candidates = [item for item in (headers.odd_headers if parity else headers.even_headers)
                          if item.page_no == page]
            chapter = next((p for p in reversed(chapters) if p.page_no is not None and p.page_no <= page), None)
            findings.extend(_header_slot(candidates, params, fields, bool(parity), [chapter] if chapter else [],
                                         location, even_pattern))
        return findings

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
                f"实际距离 {_value(setup.header_distance_mm, ' mm')}", "请调整页眉距边界的距离。", location,
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
                            location | {"excerpt": selected.text[:100]})]
        selected = matches[0]
    return _header_style(selected, params, fields, location | {"excerpt": selected.text[:100]})


def double_border(doc, params):
    headers = doc.headers_footers
    items = [*headers.odd_headers, *headers.even_headers, *headers.default_headers]
    style = "双横线" if params["style"] == "double" else params["style"]
    return [Finding(
        f"页眉下边框为{style}，线宽 {params['width_pt']:g} pt（容差 ±{params['tolerance_pt']:g} pt）",
        f"下边框样式为{item.bottom_border_style or '无'}，线宽 {_value(item.bottom_border_pt, ' pt')}",
        "请调整页眉下边框的线型及宽度。",
        _location(section_index=item.section_index, excerpt=item.text),
    ) for item in items if item.bottom_border_style != params["style"]
        or not _near(item.bottom_border_pt, params["width_pt"], params["tolerance_pt"])]


def page_numbers(doc, params):
    formats = {key: "roman" for key in params["roman_sections"]} | {
        key: "decimal" for key in params["decimal_sections"]
    }
    pdf = doc.file_ext == "pdf"
    indexed = defaultdict(list)
    for item in doc.headers_footers.page_numbers:
        indexed[item.page_no if pdf else item.section_index].append(item)
    required = defaultdict(dict)
    for paragraph in doc.paragraphs:
        index = paragraph.page_no if pdf else paragraph.section_index
        if index is not None and paragraph.text and paragraph.section_key in formats:
            required[index].setdefault(formats[paragraph.section_key], paragraph)
    if not required:
        return None
    if pdf:
        # Also check pages with only graphics between numbered text pages in the same group.
        sorted_pages = sorted(required)
        for previous, current in zip(sorted_pages, sorted_pages[1:]):
            if required[previous].keys() == required[current].keys():
                for page in range(previous + 1, current):
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
                actual = NUMBERS[item.num_format] if item else "未识别到页码"
                if item and item.num_format != "none":
                    actual += f"，位于{POSITIONS[item.position]}，{ALIGNMENTS.get(item.alignment, '对齐未知')}"
                variant_text = {"first": "首页", "even": "偶数页", "default": ""}[variant]
                location = _location(paragraph)
                if pdf:
                    location["page"] = index
                result.append(Finding(
                    f"{variant_text}{POSITIONS.get(params['position'], params['position'])}页码为"
                    f"{NUMBERS[fmt]}且{ALIGNMENTS.get(params['alignment'], params['alignment'])}",
                    actual, f"请调整{SECTION(paragraph.section_key, paragraph.section_key)}的页码格式与位置。", location,
                ))
    return result


def required_sections(doc, params):
    keys = {section.key for section in doc.sections}
    findings = [
        Finding(f"包含{SECTION(key, key)}", f"未识别到{SECTION(key, key)}", f"请补充{SECTION(key, key)}。",
                _location(section=key))
        for key in params["required_sections"] if key not in keys
    ]
    elements = cover_elements(doc.paragraphs)
    found = {
        "title": "title_cn" in elements or "title_en" in elements,
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
                {"section": key, "paragraph_index": section.start_paragraph_index,
                 **_location(page=section.page_start, excerpt=section.title)},
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
    if "school_code" in elements:
        code, p = elements["school_code"]
        if _compact(code) != str(params["school_code"]):
            findings.append(Finding(f"学校编号为 {params['school_code']}", f"学校编号为 {code}",
                                    "请更正封面的学校编号。", _location(p)))
    if "title_cn" in elements:
        title, p = elements["title_cn"]
        maximum = params["title_cn_max_chinese_chars"]
        count = count_chinese_chars(title)
        if count > maximum:
            findings.append(Finding(f"中文题目至多 {maximum} 个汉字", f"中文题目有 {count} 个汉字",
                                    "请精简封面中文题目。", _location(p)))
        findings.extend(_typography(p, params["title_cn_style"], params["font_size_tolerance_pt"], "封面中文题目"))
    return findings


def section_typography(doc, params):
    key = params["section_key"]
    label = SECTION(key, key)
    tolerance = params["font_size_tolerance_pt"]
    paragraphs = [p for p in doc.paragraphs if p.section_key == key and p.text]
    if not paragraphs:
        return None
    findings = []
    for p in paragraphs:
        if p.role == "section_heading":
            findings.extend(_typography(p, params["heading"], tolerance, f"{label}标题"))
        elif p.role == "body_text" and "body" in params:
            findings.extend(_typography(p, params["body"], tolerance, f"{label}正文"))
        elif p.role in {"keywords_cn", "keywords_en"} and "keywords" in params:
            findings.extend(_typography(p, params["keywords"], tolerance, f"{label}关键词"))
        elif p.role == "toc_entry" and "entry" in params:
            findings.extend(_typography(p, params["entry"], tolerance, "目录条目",
                                        runs=p.toc_entry_runs or p.runs))
            if p.toc_page_number is None:
                findings.append(Finding("目录条目显示页码", "未识别到目录页码", "请更新目录页码。", _location(p)))
            else:
                findings.extend(_typography(p, params["page_number"], tolerance, "目录页码",
                                            runs=p.toc_page_runs, sample=p.toc_page_style))
    return findings


def heading_typography(doc, params):
    findings = []
    base_style = {key: params[key] for key in ("font_name", "bold") if key in params}
    for paragraph in doc.paragraphs:
        if paragraph.section_key in params["section_keys"] and paragraph.role in params["roles"]:
            style = base_style | params["roles"][paragraph.role]
            findings.extend(_typography(paragraph, style, params["font_size_tolerance_pt"], "章节标题"))
    return findings


def body_typography(doc, params):
    allowed = {key: params[key] for key in ("font_name", "font_size_pt", "bold", "alignment") if key in params}
    paragraphs = [p for p in doc.paragraphs if p.section_key in params["section_keys"]
                  and p.role in {"body_text", "reference_entry"} and p.text]
    tolerance = params["font_size_tolerance_pt"]
    if params.get("require_consistent_size"):
        sizes = [p.font_size_pt for p in paragraphs if p.font_size_pt is not None]
        if not sizes:
            return None
        # Use the most frequent paragraph size as the reference for each run.
        allowed = allowed | {"font_size_pt": Counter(sizes).most_common(1)[0][0]}
    return [finding for p in paragraphs for finding in _typography(p, allowed, tolerance, "正文")]


def abstract_content(doc, params):
    paragraphs = [p for p in doc.paragraphs if p.section_key == "abstract_cn"]
    if not paragraphs:
        return None
    findings = []
    minimum = params["min_chinese_chars"]
    count = doc.stats.abstract_cn_chars
    if count < minimum:
        findings.append(Finding(f"中文摘要至少 {minimum} 个汉字", f"摘要有 {count} 个汉字",
                                "请补充中文摘要正文。", _location(paragraphs[0])))
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
            "请核对中文关键词的数量、长度及分隔符。", _location(keywords or paragraphs[0]),
        ))
    return findings


def word_count(doc, params):
    findings = []
    for prefix, key, label, count in (
        ("body", "body", "正文", doc.stats.body_chinese_chars),
        ("intro", "introduction", "绪论", doc.stats.intro_chinese_chars),
    ):
        low = params.get(f"{prefix}_min_chinese_chars")
        high = params.get(f"{prefix}_max_chinese_chars")
        if (low is not None and count < low) or (high is not None and count > high):
            limits = "且".join(item for item in (f"至少 {low}" if low is not None else "",
                                                  f"至多 {high}" if high is not None else "") if item)
            p = next((p for p in doc.paragraphs if p.section_key == key and p.text), None)
            findings.append(Finding(f"{label}{limits} 个汉字", f"{label}有 {count} 个汉字",
                                    f"请调整{label}篇幅。", _location(p, section=key)))
    return findings


def figure_table(doc, params):
    paragraphs = {p.index: p for p in doc.paragraphs}
    grouped = defaultdict(list)
    findings = []
    formats = {"decimal": r"[0-9]+", "roman": r"[IVXLCDMivxlcdm]+"}
    token = formats[params["number_format"]]
    for item in doc.figures_tables:
        if item.kind not in {"figure", "table"}:
            continue
        if not item.caption_text:
            label = "图题" if item.kind == "figure" else "表题"
            findings.append(Finding(f"对象附有{label}", f"未识别到{label}", f"请补充{label}。",
                                    _location(paragraphs.get(item.paragraph_index))))
            continue
        grouped[item.kind].append(item)
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
        for item in items:
            number = unicodedata.normalize("NFKC", item.number_raw)
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
    return findings


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
