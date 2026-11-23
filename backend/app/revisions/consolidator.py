"""Group rule findings and pick a bounded set of PDF annotations."""
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import zip_longest

from app.schemas.revisions import AnchorLocation, RulebookEntry

GLOBAL_RULES = {
    "FILE_NAME_PATTERN", "PDF_NOT_IMAGE_ONLY", "PAGE_SIZE_A4", "PAGE_MARGINS", "REQUIRED_SECTIONS",
    "SECTION_ORDER", "WORD_COUNT_REQUIREMENTS", "HEADER_DOUBLE_BORDER",
}
POINT_RULES = {"COVER_ELEMENTS", "ABSTRACT_CONTENT_RULES", "FIGURE_TABLE_CAPTION", "REFERENCE_GBT7714"}
STYLE_RULES = {
    "BODY_TYPOGRAPHY", "LINE_SPACING_MIN", "HEADING_TYPOGRAPHY", "PAGE_NUMBER_STYLE",
    "ABSTRACT_CN_TYPOGRAPHY", "ABSTRACT_EN_TYPOGRAPHY", "DECLARATION_TYPOGRAPHY", "TOC_TYPOGRAPHY",
}
LAYOUT_RULES = {"PAGE_SIZE_A4", "PAGE_MARGINS", "HEADER_FORMAT", "HEADER_DOUBLE_BORDER", "PAGE_NUMBER_STYLE"}
AUTO_FIX_RULES = STYLE_RULES | LAYOUT_RULES | {"FILE_NAME_PATTERN"} | (POINT_RULES - {"FIGURE_TABLE_CAPTION"})


def _value(item, name, default=None):
    return item.get(name, default) if isinstance(item, Mapping) else getattr(item, name, default)


def _group(violations):
    result = defaultdict(list)
    for finding in violations:
        code = _value(finding, "rule_code")
        location = _value(finding, "location")
        point = ()
        if code in POINT_RULES:
            index = location.get("paragraph_index")
            point = (index, location.get("page"), location.get("section"),
                     _value(finding, "expected") if index is None else None)
        result[(code, *point)].append(finding)
    return result


def _anchors(locations):
    candidates = sorted(locations, key=lambda loc: (
        loc.get("page") or float("inf"), loc.get("bbox") is None,
        loc["paragraph_index"] if loc.get("paragraph_index") is not None else float("inf"),
    ))
    seen = set()
    result = []
    for location in candidates:
        anchor = AnchorLocation.model_validate(location)
        key = ("page", anchor.page) if anchor.page is not None else ("paragraph", anchor.paragraph_index)
        if (anchor.page is None and anchor.paragraph_index is None) or key in seen:
            continue
        seen.add(key)
        result.append(anchor)
    return result


def consolidate(violations, original_violations, rule_items, *, notes=None, editable=True) -> list[RulebookEntry]:
    current, original = _group(violations), _group(original_violations)
    rank = {_value(item, "rule_code") or _value(item, "code"): i for i, item in enumerate(rule_items)}
    entries = []
    keys = dict.fromkeys([*current, *original])
    for key in sorted(keys, key=lambda key: (rank.get(key[0], len(rank)), key[0])):
        code = key[0]
        now, before = current.get(key, []), original.get(key, [])
        findings = now or before
        counts = Counter(_value(f, "actual") for f in findings)
        locations = [_value(f, "location") for f in findings]
        guidance = _value(findings[0], "message")
        note = (notes or {}).get(code)
        scope = "point" if code in POINT_RULES else "cluster"
        if code in GLOBAL_RULES or (code == "HEADER_FORMAT" and (
            all(loc.get("page") is None for loc in locations) or len(now) > 1 and len(counts) == 1
        )):
            scope = "global"
        entries.append(RulebookEntry(
            rule_code=code, rule_name=_value(findings[0], "rule_name"), category=_value(findings[0], "category"),
            severity="error" if any(_value(f, "severity") == "error" for f in findings) else "warning",
            scope=scope, status=("fixed" if not now else "ignored" if note and note.ignore else "open"),
            total_count=len(now), original_count=len(before),
            expected="；".join(dict.fromkeys(_value(f, "expected") for f in findings))[:1200],
            actual_summary="；".join(f"{value}（{count} 处）" if count > 1 else value
                                    for value, count in counts.most_common(3))[:1200],
            guidance=note.guidance if note and note.guidance else guidance,
            bubble_note=(note.bubble_note if note and note.bubble_note else guidance)[:60],
            can_auto_fix=code in AUTO_FIX_RULES and (editable or code in POINT_RULES - {"FIGURE_TABLE_CAPTION"}),
            affected_paragraphs=sorted({loc["paragraph_index"] for loc in locations
                                        if loc.get("paragraph_index") is not None}
                                       | {i for loc in locations for i in loc.get("paragraph_indices", [])}),
            affected_pages=sorted({loc["page"] for loc in locations if loc.get("page") is not None}),
            representative_anchors=_anchors(locations),
        ))
    return entries


@dataclass(frozen=True)
class PdfAnnotation:
    entry: RulebookEntry
    anchor: AnchorLocation


def select_pdf_annotations(rulebook: list[RulebookEntry]) -> list[PdfAnnotation]:
    grouped = defaultdict(list)
    for entry in rulebook:
        if entry.status != "ignored":
            grouped[entry.rule_code].extend(PdfAnnotation(entry, anchor)
                                           for anchor in entry.representative_anchors if anchor.page is not None)
    def priority(item):
        return item.entry.status == "fixed", item.entry.severity != "error", item.anchor.bbox is None

    groups = [sorted(items, key=priority) for items in grouped.values()]
    per_page = Counter()
    selected = []
    for batch in zip_longest(*groups):
        for item in sorted((a for a in batch if a is not None), key=priority):
            if per_page[item.anchor.page] < 4:
                selected.append(item)
                per_page[item.anchor.page] += 1
                if len(selected) == 25:
                    return selected
    return selected
