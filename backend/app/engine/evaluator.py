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
    passed = skipped = applicable = errors = warnings = 0
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
            violations.append(Violation(
                rule_item_id=rule.rule_item_id, rule_code=rule.rule_code, category=rule.category,
                rule_name=rule.name, severity=rule.severity, location=finding.location,
                expected=finding.expected, actual=finding.actual, message=finding.message,
            ))
            if rule.severity == "error":
                errors += 1
            else:
                warnings += 1
    return EvaluationResult(
        verdict="fail" if errors else "pass", score=round(100 * passed / applicable, 2) if applicable else 100,
        error_count=errors, warning_count=warnings, passed_rules_count=passed, skipped_rules_count=skipped,
        duration_ms=round((perf_counter() - start) * 1000), violations=violations,
    )
