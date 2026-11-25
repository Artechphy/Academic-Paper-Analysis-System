"""Evaluate persisted rule configurations against a parsed snapshot."""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.engine.rules_catalog import RULES_CATALOG
from app.schemas.ir import DocumentIR


class Violation(BaseModel):
    rule_item_id: UUID | None = None
    rule_code: str
    category: str
    rule_name: str
    severity: Literal["error", "warning"]
    location: dict[str, Any] = Field(default_factory=dict)
    expected: str
    actual: str
    message: str


class EvaluationResult(BaseModel):
    verdict: Literal["pass", "fail", "error"]
    score: float
    error_count: int = 0
    warning_count: int = 0
    passed_rules_count: int = 0
    skipped_rules_count: int = 0
    duration_ms: int = 0
    violations: list[Violation] = Field(default_factory=list)


@dataclass(frozen=True)
class _RuleConfig:
    rule_code: str
    category: str
    name: str
    severity: str
    applies_to: str
    params: dict
    enabled: bool
    rule_item_id: UUID | None

    @classmethod
    def from_item(cls, item):
        def get(key, default=None):
            return item.get(key, default) if isinstance(item, Mapping) else getattr(item, key, default)

        return cls(
            rule_code=get("rule_code") or get("code"), category=get("category"),
            name=get("name"), severity=get("severity") or "error",
            applies_to=get("applies_to") or "both", params=get("params") or {},
            enabled=get("enabled") is not False, rule_item_id=get("id"),
        )


def _merge_group(group: list[Violation]) -> Violation:
    locations = [item.location for item in group]
    location = min(locations, key=lambda loc: (loc.get("page") is None, loc.get("page") or 0,
                                               loc.get("bbox") is None)).copy()
    pages = [loc[key] for loc in locations for key in ("page", "page_end") if loc.get(key) is not None]
    location.pop("page_end", None)
    if pages and location.get("page") is not None and max(pages) > location["page"]:
        location["page_end"] = max(pages)
    if any("paragraph_indices" in loc for loc in locations):
        location["paragraph_indices"] = sorted(
            {location["paragraph_index"]} | {index for loc in locations for index in loc.get("paragraph_indices", [])}
        )
    highlights = dict.fromkeys(loc["highlight_excerpt"] for loc in locations if loc.get("highlight_excerpt"))
    if highlights:
        location["highlight_excerpt"] = "；".join(highlights)[:100]
    return group[0].model_copy(update={
        "severity": "error" if any(item.severity == "error" for item in group) else "warning",
        "location": location,
        **{key: "；".join(dict.fromkeys(getattr(item, key) for item in group))
           for key in ("expected", "actual", "message")},
    })


def merge_paragraph_violations(violations: Iterable[Violation]) -> list[Violation]:
    """Combine findings for the same rule and paragraph in first-appearance order."""
    groups = {}
    for ordinal, item in enumerate(violations):
        index = item.location.get("paragraph_index")
        key = (item.rule_code, index) if index is not None else ordinal
        groups.setdefault(key, []).append(item)
    return [items[0] if len(items) == 1 else _merge_group(items) for items in groups.values()]


def evaluate(
    document: DocumentIR | Mapping | None,
    rules: Iterable,
    *,
    parse_status: Literal["success", "failed"] = "success",
) -> EvaluationResult:
    """Accept RuleItem rows, seed rules, or equivalent dictionaries without importing the database."""
    start = perf_counter()
    if parse_status == "failed" or document is None:
        return EvaluationResult(verdict="error", score=0)
    if not isinstance(document, DocumentIR):
        document = DocumentIR.model_validate(document)
    passed = skipped = applicable = 0
    violations = []
    for item in rules:
        rule = _RuleConfig.from_item(item)
        if not rule.enabled or rule.applies_to not in {"both", document.file_ext}:
            skipped += 1
            continue
        handler = RULES_CATALOG.get(rule.rule_code)
        if handler is None:
            raise ValueError(f"未注册的规则代码：{rule.rule_code}")
        findings = handler(document, rule.params)
        if findings is None:
            skipped += 1
            continue
        applicable += 1
        if not findings:
            passed += 1
        for finding in findings:
            severity = "warning" if rule.severity == "warning" or finding.severity == "warning" else "error"
            violations.append(Violation(
                rule_item_id=rule.rule_item_id, rule_code=rule.rule_code, category=rule.category,
                rule_name=rule.name, severity=severity, location=finding.location,
                expected=finding.expected, actual=finding.actual, message=finding.message,
            ))
    violations = merge_paragraph_violations(violations)
    errors = sum(item.severity == "error" for item in violations)
    return EvaluationResult(
        verdict="fail" if errors else "pass", score=round(100 * passed / applicable, 2) if applicable else 100,
        error_count=errors, warning_count=len(violations) - errors, passed_rules_count=passed, skipped_rules_count=skipped,
        duration_ms=round((perf_counter() - start) * 1000), violations=violations,
    )
