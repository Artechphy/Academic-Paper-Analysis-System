import type { AppliesTo, DegreeLevel, RuleCategory, Verdict } from '../types/api';

export const CATEGORY_LABELS: Record<RuleCategory, string> = {
  file: '文件与文本层',
  page: '页面与行距',
  header_footer: '页眉与页码',
  structure: '结构与顺序',
  cover: '封面要素',
  typography: '字体与排版',
  abstract: '摘要与篇幅',
  figure_table: '图表题注',
  reference: '参考文献',
};

export const CATEGORY_ORDER: RuleCategory[] = [
  'file',
  'page',
  'header_footer',
  'structure',
  'cover',
  'typography',
  'abstract',
  'figure_table',
  'reference',
];

export const SECTION_LABELS: Record<string, string> = {
  cover: '封面',
  declaration: '独创性与授权声明',
  defense_signature: '答辩签名表',
  abstract_cn: '中文摘要',
  cnki_abstract: '知网中文文摘',
  abstract_en: '英文摘要',
  toc: '目录',
  introduction: '绪论',
  body: '正文',
  conclusion: '结论',
  appendix: '附录',
  references: '参考文献',
  achievements: '科研成果',
  acknowledgements: '致谢',
  resume: '个人简历',
};

export const DEGREE_LABELS: Record<DegreeLevel, string> = {
  master: '硕士规范',
  doctor: '博士规范',
  general: '通用规范',
};

export const APPLIES_TO_LABELS: Record<AppliesTo, string> = {
  both: 'DOCX & PDF',
  docx: '仅 DOCX',
  pdf: '仅 PDF',
};

export const CAPABILITY_LABELS: Record<string, string> = {
  exact_margins: '精确页边距',
  exact_line_spacing: '精确行距',
  exact_header_distance: '精确页眉边距',
  exact_header_border: '页眉双横线检测',
  exact_page_number_style: '精确页码样式',
  exact_font_runs: '精确字体样式',
  exact_alignment: '精确段落对齐',
};

export const VERDICT_META: Record<
  Verdict,
  { label: string; shortLabel: string; badgeClass: string; dotClass: string }
> = {
  pass: {
    label: '格式合格',
    shortLabel: '合格',
    badgeClass: 'bg-[#ECFDF5] text-[#15803D] border-[#BBF7D0]',
    dotClass: 'bg-[#16A34A]',
  },
  fail: {
    label: '格式有问题',
    shortLabel: '有问题',
    badgeClass: 'bg-[#FEF2F2] text-[#B91C1C] border-[#FECACA]',
    dotClass: 'bg-[#DC2626]',
  },
  error: {
    label: '解析异常',
    shortLabel: '异常',
    badgeClass: 'bg-[#FFFBEB] text-[#B45309] border-[#FDE68A]',
    dotClass: 'bg-[#D97706]',
  },
};

export function getCategoryLabel(category: string): string {
  return CATEGORY_LABELS[category as RuleCategory] ?? category;
}

export function getSectionLabel(key: string): string {
  return SECTION_LABELS[key] ?? key;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function formatPercent(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined || Number.isNaN(ratio)) return '—';
  return `${(ratio * 100).toFixed(1)}%`;
}

export function formatScore(score: number | null | undefined): string {
  if (score === null || score === undefined || Number.isNaN(score)) return '—';
  return score.toFixed(1);
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
}

export const FONT_LABELS: Record<string, string> = {
  simsun: '宋体',
  simhei: '黑体',
  times_new_roman: 'Times New Roman',
  microsoft_yahei: '微软雅黑',
};

export const ALIGNMENT_LABELS: Record<string, string> = {
  left: '左对齐',
  center: '居中',
  right: '右对齐',
  justify: '两端对齐',
};

export const SCOPE_LABELS: Record<string, string> = {
  global: '全局规范',
  cluster: '同类聚合',
  point: '单点定位',
};

export function getFontLabel(fontName: string | null | undefined): string {
  if (!fontName) return '未识别';
  return FONT_LABELS[fontName] ?? fontName;
}

export function getAlignmentLabel(alignment: string | null | undefined): string {
  if (!alignment) return '默认';
  return ALIGNMENT_LABELS[alignment] ?? alignment;
}
