"""JSON-serializable snapshot shared by the parsers and the rule engine."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Alignment = Literal["left", "center", "right", "justify"]
NumberFormat = Literal["roman", "decimal", "none"]
SpacingRule = Literal["at_least", "exact", "multiple", "estimated"]


class IRModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)


class TextStyleIR(IRModel):
    font_name: str | None = None
    font_size_pt: float | None = None
    bold: bool | None = None


class TextRunIR(TextStyleIR):
    text: str
    font_name_latin: str | None = None
    is_script: bool = False
    page_no: int | None = None
    bbox: tuple[float, float, float, float] | None = None


class PageSetupIR(IRModel):
    width_mm: float | None = None
    height_mm: float | None = None
    top_margin_mm: float | None = None
    bottom_margin_mm: float | None = None
    left_margin_mm: float | None = None
    right_margin_mm: float | None = None
    header_distance_mm: float | None = None
    odd_even_headers: bool | None = None
    section_index: int | None = None
    page_no: int | None = None
    is_blank: bool = False


class HeaderItemIR(TextStyleIR):
    text: str
    bbox: tuple[float, float, float, float] | None = None
    alignment: Alignment | None = None
    bottom_border_style: str | None = None
    bottom_border_pt: float | None = None
    section_index: int | None = None
    page_no: int | None = None
    chapter_field: bool = False
    runs: list[TextRunIR] = Field(default_factory=list)


class PageNumberIR(IRModel):
    section_index: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    page_no: int | None = None
    num_format: NumberFormat = "none"
    alignment: Alignment | None = None
    raw_text: str = ""
    position: Literal["header", "footer", "unknown"] = "footer"
    variant: Literal["default", "even", "first"] = "default"


class HeaderFooterIR(IRModel):
    odd_headers: list[HeaderItemIR] = Field(default_factory=list)
    even_headers: list[HeaderItemIR] = Field(default_factory=list)
    default_headers: list[HeaderItemIR] = Field(default_factory=list)
    page_numbers: list[PageNumberIR] = Field(default_factory=list)


UnitKind = Literal["paragraph", "heading", "caption", "figure", "table", "formula", "underline_row",
                   "footnote", "reference", "toc_entry", "scanned_page", "other"]


class LineSpacingSampleIR(IRModel):
    spacing_pt: float
    page_no: int
    bbox: tuple[float, float, float, float]


class ParagraphIR(TextStyleIR):
    index: int
    bbox: tuple[float, float, float, float] | None = None
    page_no: int | None = None
    paragraph_start_index: int | None = None
    unit_kind: UnitKind = "paragraph"
    page_end: int | None = None
    line_count: int = 1
    line_spacings_pt: list[float] = Field(default_factory=list)
    line_spacing_samples: list[LineSpacingSampleIR] = Field(default_factory=list)
    field_label: str | None = None
    field_value: str | None = None
    has_underline: bool = False
    has_signature_image: bool = False
    in_figure: bool = False
    section_key: str | None = None
    role: str = "other"
    text: str
    font_name_latin: str | None = None
    alignment: Alignment | None = None
    line_spacing_pt: float | None = None
    line_spacing_rule: SpacingRule | None = None
    style_name: str | None = None
    has_image: bool = False
    section_index: int | None = None
    runs: list[TextRunIR] = Field(default_factory=list)
    toc_page_number: str | None = None
    toc_page_style: TextStyleIR | None = None
    toc_entry_runs: list[TextRunIR] = Field(default_factory=list)
    toc_page_runs: list[TextRunIR] = Field(default_factory=list)
    object_kind: Literal["figure", "table", "formula"] | None = None
    in_table: bool = False


class DetectedSectionIR(IRModel):
    key: str
    title: str
    start_paragraph_index: int
    end_paragraph_index: int
    page_start: int | None = None
    chinese_char_count: int = 0


class FigureTableIR(IRModel):
    kind: Literal["figure", "table", "formula"]
    bbox: tuple[float, float, float, float] | None = None
    caption_text: str
    number_raw: str
    paragraph_index: int
    alignment: Alignment | None = None
    relative_position: Literal["below", "above", "unknown"] = "unknown"
    chapter_index: int | None = None
    caption_style_issue: str | None = None
    is_continuation: bool = False
    subfigure_count: int = 1
    inner_texts: list[str] = Field(default_factory=list)
    object_bbox: tuple[float, float, float, float] | None = None
    object_page_no: int | None = None


class ReferenceIR(IRModel):
    index_num: int | None = None
    raw_text: str
    paragraph_index: int
    type_code: str | None = None
    carrier_code: str | None = None
    has_url: bool = False
    has_access_date: bool = False


class DocumentStatsIR(IRModel):
    total_chinese_chars: int = 0
    body_chinese_chars: int = 0
    intro_chinese_chars: int = 0
    abstract_cn_chars: int = 0
    abstract_en_words: int = 0
    text_page_ratio: float = Field(default=1.0, ge=0, le=1)


class DocumentIR(IRModel):
    file_name: str
    file_ext: Literal["docx", "pdf"]
    page_count: int = Field(ge=0)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    is_image_only_pdf: bool = False
    page_setups: list[PageSetupIR] = Field(default_factory=list)
    headers_footers: HeaderFooterIR = Field(default_factory=HeaderFooterIR)
    paragraphs: list[ParagraphIR] = Field(default_factory=list)
    sections: list[DetectedSectionIR] = Field(default_factory=list)
    figures_tables: list[FigureTableIR] = Field(default_factory=list)
    references: list[ReferenceIR] = Field(default_factory=list)
    stats: DocumentStatsIR = Field(default_factory=DocumentStatsIR)
