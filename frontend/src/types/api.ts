export type HealthStatus = 'ok' | 'unavailable';
export type DatabaseStatus = 'connected' | 'unreachable';

export interface HealthResponse {
  status: HealthStatus;
  database: DatabaseStatus;
}

export type DegreeLevel = 'master' | 'doctor' | 'general';
export type Severity = 'error' | 'warning';
export type AppliesTo = 'docx' | 'pdf' | 'both';
export type RuleCategory =
  | 'file'
  | 'page'
  | 'header_footer'
  | 'structure'
  | 'cover'
  | 'typography'
  | 'abstract'
  | 'figure_table'
  | 'reference';

export type Verdict = 'pass' | 'fail' | 'error';
export type FileExt = 'docx' | 'pdf';
export type ParseStatus = 'success' | 'failed';
export type BatchStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface RuleItemResponse {
  id: string;
  rule_set_id: string;
  rule_code: string;
  category: RuleCategory;
  name: string;
  description: string;
  severity: Severity;
  applies_to: AppliesTo;
  params: Record<string, unknown>;
  enabled: boolean;
  sort_order: number;
}

export interface RuleItemUpdate {
  enabled?: boolean;
  severity?: Severity;
  params?: Record<string, unknown>;
}

export interface RuleSetResponse {
  id: string;
  code: string;
  version: string;
  name: string;
  description: string | null;
  degree_level: DegreeLevel;
  is_default: boolean;
  is_active: boolean;
  rule_count: number;
  created_at: string;
  updated_at: string;
}

export interface RuleSetDetail extends RuleSetResponse {
  manual_checklist: string[];
  rule_items: RuleItemResponse[];
}

export interface RuleSetCreate {
  code: string;
  version?: string;
  name: string;
  description?: string | null;
  degree_level?: DegreeLevel;
  is_active?: boolean;
  manual_checklist?: string[];
  source_rule_set_id?: string | null;
}

export interface DocumentStatsIR {
  total_chinese_chars: number;
  body_chinese_chars: number;
  intro_chinese_chars: number;
  abstract_cn_chars: number;
  abstract_en_words: number;
  text_page_ratio: number;
}

export interface DetectedSectionIR {
  key: string;
  title: string;
  start_paragraph_index: number;
  end_paragraph_index: number;
  page_start: number | null;
  chinese_char_count: number;
}

export interface IRSummary {
  page_count: number;
  stats: DocumentStatsIR;
  sections: DetectedSectionIR[];
  capabilities: Record<string, boolean>;
  is_image_only_pdf: boolean;
}

export interface ViolationLocation {
  page?: number | null;
  page_end?: number | null;
  paragraph_index?: number | null;
  section?: string | null;
  section_index?: number | null;
  excerpt?: string | null;
  highlight_excerpt?: string | null;
  [key: string]: unknown;
}

export interface ViolationResponse {
  id: string;
  rule_item_id: string | null;
  rule_code: string;
  category: string;
  rule_name: string;
  severity: Severity;
  location: ViolationLocation;
  expected: string;
  actual: string;
  message: string;
}

export interface CheckRunSummary {
  id: string;
  batch_id: string | null;
  paper_id: string;
  rule_set_id: string;
  file_name: string;
  file_ext: FileExt;
  file_size: number;
  page_count: number | null;
  detected_title: string | null;
  parse_status: ParseStatus;
  parse_error: string | null;
  verdict: Verdict;
  score: number;
  error_count: number;
  warning_count: number;
  passed_rules_count: number;
  skipped_rules_count: number;
  duration_ms: number;
  checked_at: string;
}

export interface CheckRunDetail extends CheckRunSummary {
  ir_summary: IRSummary | null;
  violations: ViolationResponse[];
  manual_checklist: string[];
}

export interface BatchSummary {
  id: string;
  name: string;
  rule_set_id: string;
  status: BatchStatus;
  created_at: string;
  completed_at: string | null;
  total_count: number;
  pass_count: number;
  fail_count: number;
  error_count: number;
  pass_rate: number;
  avg_score: number | null;
  avg_duration_ms: number | null;
}

export interface BatchDetail extends BatchSummary {
  results: CheckRunSummary[];
}

export interface RuleViolationStats {
  rule_code: string;
  rule_name: string;
  category: string;
  violation_count: number;
  affected_paper_count: number;
  violation_ratio: number;
  violation_rank: number;
}

export interface StatsOverview {
  total_count: number;
  pass_count: number;
  fail_count: number;
  error_count: number;
  pass_rate: number;
  top_violations: RuleViolationStats[];
}
