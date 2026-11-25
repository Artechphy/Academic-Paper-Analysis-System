import type { FileExt, Severity, Verdict, ViolationResponse } from './api';

export type Alignment = 'left' | 'center' | 'right' | 'justify';
export type UnitKind =
  | 'paragraph'
  | 'heading'
  | 'caption'
  | 'figure'
  | 'table'
  | 'formula'
  | 'underline_row'
  | 'footnote'
  | 'reference'
  | 'toc_entry'
  | 'scanned_page'
  | 'other';
export type RuleScope = 'global' | 'cluster' | 'point';
export type RuleStatus = 'open' | 'fixed' | 'ignored';
export type DiffSource = 'manual' | 'rule' | 'llm';
export type PageMode = 'issues_only' | 'full';

export interface TextRunIR {
  text: string;
  font_name: string | null;
  font_size_pt: number | null;
  bold: boolean | null;
  font_name_latin: string | null;
  is_script: boolean;
}

export interface ParagraphIR {
  index: number;
  bbox: [number, number, number, number] | null;
  page_no: number | null;
  paragraph_start_index: number | null;
  unit_kind?: UnitKind;
  page_end?: number | null;
  line_count?: number;
  field_label?: string | null;
  field_value?: string | null;
  has_underline?: boolean;
  has_signature_image?: boolean;
  in_figure?: boolean;
  section_key: string | null;
  role: string;
  text: string;
  font_name: string | null;
  font_name_latin: string | null;
  font_size_pt: number | null;
  bold: boolean | null;
  alignment: Alignment | null;
  line_spacing_pt: number | null;
  line_spacing_rule: 'at_least' | 'exact' | 'multiple' | 'estimated' | null;
  style_name: string | null;
  has_image: boolean;
  section_index: number | null;
  runs: TextRunIR[];
  object_kind: 'figure' | 'table' | 'formula' | null;
  in_table: boolean;
}

export interface AnchorLocation {
  page: number | null;
  paragraph_index: number | null;
  bbox: number[] | null;
  excerpt: string | null;
}

export interface RulebookEntry {
  rule_code: string;
  rule_name: string;
  category: string;
  severity: Severity;
  scope: RuleScope;
  status: RuleStatus;
  total_count: number;
  original_count: number;
  expected: string;
  actual_summary: string;
  guidance: string;
  bubble_note: string;
  can_auto_fix: boolean;
  affected_paragraphs: number[];
  affected_pages: number[];
  representative_anchors: AnchorLocation[];
}

export interface ParagraphDiff {
  paragraph_index: number;
  page_no: number | null;
  section_key: string | null;
  before_text: string;
  after_text: string;
  style_changes: string[];
  source: DiffSource;
  summary: string;
}

export interface RevisionFeedbackItem {
  id: string;
  version: number;
  author: 'user' | 'agent';
  rule_code: string | null;
  paragraph_index: number | null;
  instruction: string;
  summary: string | null;
  created_at: string;
}

export interface RevisionSessionDetail {
  id: string;
  check_run_id: string;
  paper_id: string;
  rule_set_id: string;
  file_name: string;
  target_file_name: string;
  file_ext: FileExt;
  editable: boolean;
  version: number;
  comparison_ready: boolean;
  annotated_pdf_ready: boolean;
  annotated_page_mode: PageMode | null;
  llm_used: boolean;
  llm_model: string | null;
  verdict: Verdict;
  score: number;
  error_count: number;
  warning_count: number;
  original_error_count: number;
  rulebook: RulebookEntry[];
  original_paragraphs: ParagraphIR[];
  current_paragraphs: ParagraphIR[];
  violations: ViolationResponse[];
  changes: ParagraphDiff[];
  modified_paragraphs: number[];
  feedbacks: RevisionFeedbackItem[];
  updated_at: string;
}

export interface ParagraphEditRequest {
  text?: string;
  font_name?: string | null;
  font_size_pt?: number | null;
  bold?: boolean | null;
  alignment?: Alignment | null;
  line_spacing_pt?: number | null;
  revert?: boolean;
}

export interface ParagraphEditResponse {
  paragraph: ParagraphIR;
  paragraph_violations: ViolationResponse[];
  resolved_count: number;
  remaining_count: number;
  verdict: Verdict;
  score: number;
  error_count: number;
  warning_count: number;
  rulebook: RulebookEntry[];
  changes: ParagraphDiff[];
  modified_paragraphs: number[];
  version: number;
}

export interface DocumentSettingsRequest {
  target_file_name?: string;
  fix_page_size_a4?: boolean;
  fix_margins?: boolean;
  fix_headers?: boolean;
}

export interface AutoFixRequest {
  instruction?: string | null;
  rule_codes?: string[] | null;
}

export interface AnnotatedPdfExportResponse {
  annotated_pdf_ready: boolean;
  page_mode: PageMode;
  page_count: number;
  download_url: string;
}
