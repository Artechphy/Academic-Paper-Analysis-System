"""Request and response models for rule templates and rule items."""

import re
from datetime import datetime
from math import isfinite
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.db.seed import FJNU_RULES_BY_CODE
from app.engine.rules_catalog import ALIGNMENTS, POSITIONS, RULES_CATALOG

DegreeLevel = Literal["master", "doctor", "general"]
Severity = Literal["error", "warning"]
AppliesTo = Literal["docx", "pdf", "both"]
Category = Literal[
    "file", "page", "header_footer", "structure", "cover",
    "typography", "abstract", "figure_table", "reference",
]


_OPTIONAL_PARAMS = {
    "HEADER_FORMAT": {"odd_text_source", "even_pattern"},
    "DECLARATION_TYPOGRAPHY": {"body"},
    "ABSTRACT_CN_TYPOGRAPHY": {"body", "keywords"},
    "ABSTRACT_EN_TYPOGRAPHY": {"body", "keywords"},
    "TOC_TYPOGRAPHY": {"entry", "page_number"},
    "HEADING_TYPOGRAPHY": {"font_name", "bold"},
    "BODY_TYPOGRAPHY": {"font_name", "font_size_pt"},
    "WORD_COUNT_REQUIREMENTS": {"body_min_chinese_chars", "intro_min_chinese_chars", "intro_max_chinese_chars"},
}


def validate_rule_params(rule_code: str, params: dict[str, JsonValue]) -> None:
    seed = FJNU_RULES_BY_CODE.get(rule_code)
    if seed is None:
        return
    required = seed.params.keys() - _OPTIONAL_PARAMS.get(rule_code, set())
    if rule_code == "TOC_TYPOGRAPHY" and "entry" in params:
        required.add("page_number")
    if missing := required - params.keys():
        raise ValueError(f"缺少规则参数：{', '.join(sorted(missing))}")

    for key in params.keys() & seed.params.keys():
        value, example = params[key], seed.params[key]
        if value is None and rule_code == "WORD_COUNT_REQUIREMENTS":
            continue
        if type(example) in {int, float}:
            if type(value) not in {int, float} or (isinstance(value, float) and not isfinite(value)):
                raise ValueError(f"{key} 必须是有限数值")
        elif type(value) is not type(example) and not (key == "school_code" and type(value) is int):
            raise ValueError(f"{key} 的类型无效")
        if isinstance(example, list) and any(not isinstance(item, str) for item in value):
            raise ValueError(f"{key} 须为字符串列表")

    for key in ("pattern", "even_pattern", "forbidden_citation_pattern", "number_pattern"):
        if key not in params:
            continue
        try:
            re.compile(params[key])
        except (TypeError, re.error, OverflowError) as exc:
            raise ValueError(f"{key} 必须是有效的正则表达式") from exc
    if rule_code == "ABSTRACT_CONTENT_RULES" and not params["keyword_separator"]:
        raise ValueError("keyword_separator 不能为空")
    if rule_code == "FIGURE_TABLE_CAPTION":
        if params["number_format"] not in {"decimal", "roman"}:
            raise ValueError("number_format 必须为 decimal 或 roman")
        for kind in ("figure", "table"):
            position = params[kind].get("position")
            alignment = params[kind].get("alignment")
            if not isinstance(position, str) or position not in POSITIONS:
                raise ValueError(f"{kind} 的位置无效")
            if not isinstance(alignment, str) or alignment not in ALIGNMENTS:
                raise ValueError(f"{kind} 的对齐方式无效")


class _RuleItemFields(BaseModel):
    rule_code: str = Field(min_length=1, max_length=64)
    category: Category
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    severity: Severity = "error"
    applies_to: AppliesTo = "both"
    params: dict[str, JsonValue] = Field(default_factory=dict)
    enabled: bool = True
    sort_order: int = Field(default=0, ge=-(2**31), lt=2**31)


class RuleItemInput(_RuleItemFields):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_configuration(self) -> Self:
        if self.rule_code not in RULES_CATALOG:
            raise ValueError(f"未注册的规则代码：{self.rule_code}")
        validate_rule_params(self.rule_code, self.params)
        return self


class RuleItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    enabled: bool = Field(default_factory=lambda: True)
    severity: Severity = Field(default_factory=lambda: "error")
    params: dict[str, JsonValue] = Field(default_factory=dict)


class RuleSetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    version: str = Field(default="1.0.0", min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    degree_level: DegreeLevel = "master"
    is_active: bool = True
    manual_checklist: list[str] = Field(default_factory=list)
    source_rule_set_id: UUID | None = None
    rule_items: list[RuleItemInput] | None = None

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if (self.source_rule_set_id is None) == (self.rule_items is None):
            raise ValueError("须指定 source_rule_set_id 或提供 rule_items")
        if self.rule_items is not None:
            codes = {item.rule_code for item in self.rule_items}
            if len(codes) != len(self.rule_items):
                raise ValueError("同一模板的规则代码不能重复")
        return self


class RuleItemResponse(_RuleItemFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rule_set_id: UUID


class RuleSetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    version: str
    name: str
    description: str | None
    degree_level: DegreeLevel
    is_default: bool
    is_active: bool
    rule_count: int
    created_at: datetime
    updated_at: datetime


class RuleSetDetail(RuleSetResponse):
    manual_checklist: list[str]
    rule_items: list[RuleItemResponse]
