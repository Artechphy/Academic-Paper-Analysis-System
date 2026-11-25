import { useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  ArrowLeft,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  FileCheck2,
  FileText,
  Layers,
  Loader2,
  RefreshCw,
  RotateCcw,
  Wand2,
  X,
} from 'lucide-react';
import type { CheckRunDetail, RuleSetResponse, Severity, ViolationResponse } from '../types/api';
import {
  CAPABILITY_LABELS,
  formatDuration,
  formatFileSize,
  formatPercent,
  formatScore,
  getCategoryLabel,
  getSectionLabel,
} from '../utils/format';
import { VerdictBadge } from './VerdictBadge';

interface ViolationDrawerProps {
  open: boolean;
  loading: boolean;
  detail: CheckRunDetail | null;
  ruleSets: RuleSetResponse[];
  rechecking: boolean;
  openingRevision: boolean;
  onClose: () => void;
  onRecheck: (paperId: string, ruleSetId: string, reparse?: boolean) => Promise<void>;
  onOpenRevision: (runId: string) => void;
}

type ViewMode = 'page' | 'rule';

interface ViolationGroup {
  ruleCode: string;
  ruleName: string;
  category: string;
  severity: Severity;
  items: ViolationResponse[];
}

interface PageParagraphCluster {
  key: string;
  paragraphIndex: number | null;
  section: string | null;
  excerpt: string | null;
  pageEnd: number | null;
  items: ViolationResponse[];
}

interface PageGroup {
  key: string;
  page: number | null;
  label: string;
  errorCount: number;
  warningCount: number;
  totalCount: number;
  clusters: PageParagraphCluster[];
}

function compareByLocation(a: ViolationResponse, b: ViolationResponse): number {
  const pa = a.location?.page ?? -1;
  const pb = b.location?.page ?? -1;
  if (pa !== pb) return pa - pb;
  const ia = a.location?.paragraph_index ?? -1;
  const ib = b.location?.paragraph_index ?? -1;
  if (ia !== ib) return ia - ib;
  if (a.severity !== b.severity) return a.severity === 'error' ? -1 : 1;
  return a.rule_code.localeCompare(b.rule_code);
}

export function ViolationDrawer({
  open,
  loading,
  detail,
  ruleSets,
  rechecking,
  openingRevision,
  onClose,
  onRecheck,
  onOpenRevision,
}: ViolationDrawerProps) {
  const [shouldRender, setShouldRender] = useState(open);
  const [visible, setVisible] = useState(false);

  const [targetRuleSetId, setTargetRuleSetId] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('page');
  const [expandedRuleGroups, setExpandedRuleGroups] = useState<Record<string, boolean>>({});
  const [expandedPageGroups, setExpandedPageGroups] = useState<Record<string, boolean>>({});
  const [showAllItems, setShowAllItems] = useState<Record<string, boolean>>({});
  const [showCapabilities, setShowCapabilities] = useState(false);
  const [checklistOpen, setChecklistOpen] = useState(false);
  const [checkedManualByPaper, setCheckedManualByPaper] = useState<
    Record<string, Record<number, boolean>>
  >({});

  // Smooth right-to-left mount/unmount slide transition
  useEffect(() => {
    if (open) {
      setShouldRender(true);
      let raf1 = 0;
      let raf2 = 0;
      raf1 = window.requestAnimationFrame(() => {
        raf2 = window.requestAnimationFrame(() => {
          setVisible(true);
        });
      });
      return () => {
        window.cancelAnimationFrame(raf1);
        window.cancelAnimationFrame(raf2);
      };
    }

    setVisible(false);
    const timer = window.setTimeout(() => {
      setShouldRender(false);
    }, 260);
    return () => window.clearTimeout(timer);
  }, [open]);

  const ruleGroups = useMemo<ViolationGroup[]>(() => {
    if (!detail) return [];
    const map = new Map<string, ViolationGroup>();
    for (const v of detail.violations) {
      const existing = map.get(v.rule_code);
      if (existing) {
        existing.items.push(v);
        if (v.severity === 'error') existing.severity = 'error';
      } else {
        map.set(v.rule_code, {
          ruleCode: v.rule_code,
          ruleName: v.rule_name,
          category: v.category,
          severity: v.severity,
          items: [v],
        });
      }
    }
    return Array.from(map.values())
      .map((group) => ({
        ...group,
        items: [...group.items].sort(compareByLocation),
      }))
      .sort((a, b) => {
        if (a.severity !== b.severity) return a.severity === 'error' ? -1 : 1;
        if (a.items.length !== b.items.length) return b.items.length - a.items.length;
        return a.ruleCode.localeCompare(b.ruleCode);
      });
  }, [detail]);

  const pageGroups = useMemo<PageGroup[]>(() => {
    if (!detail) return [];
    const sorted = [...detail.violations].sort(compareByLocation);
    const map = new Map<string, { page: number | null; items: ViolationResponse[] }>();
    for (const v of sorted) {
      const page = v.location?.page ?? null;
      const key = page === null ? 'global' : `p-${page}`;
      const existing = map.get(key);
      if (existing) {
        existing.items.push(v);
      } else {
        map.set(key, { page, items: [v] });
      }
    }

    return Array.from(map.entries())
      .sort((a, b) => {
        if (a[1].page === null && b[1].page !== null) return -1;
        if (a[1].page !== null && b[1].page === null) return 1;
        return (a[1].page ?? 0) - (b[1].page ?? 0);
      })
      .map(([key, entry]) => {
        const clusters: PageParagraphCluster[] = [];
        const byPara = new Map<number, PageParagraphCluster>();
        let errorCount = 0;
        let warningCount = 0;

        for (const item of entry.items) {
          if (item.severity === 'error') errorCount += 1;
          else warningCount += 1;

          const loc = item.location ?? {};
          const pIdx = typeof loc.paragraph_index === 'number' ? loc.paragraph_index : null;
          if (pIdx !== null) {
            const existing = byPara.get(pIdx);
            if (existing) {
              existing.items.push(item);
              if (!existing.excerpt && loc.excerpt) existing.excerpt = String(loc.excerpt);
              if (!existing.section && loc.section) existing.section = String(loc.section);
              if (
                typeof loc.page_end === 'number' &&
                (existing.pageEnd === null || loc.page_end > existing.pageEnd)
              ) {
                existing.pageEnd = loc.page_end;
              }
              continue;
            }
            const cluster: PageParagraphCluster = {
              key: `${key}-para-${pIdx}`,
              paragraphIndex: pIdx,
              section: loc.section ? String(loc.section) : null,
              excerpt: loc.excerpt ? String(loc.excerpt) : null,
              pageEnd: typeof loc.page_end === 'number' ? loc.page_end : null,
              items: [item],
            };
            byPara.set(pIdx, cluster);
            clusters.push(cluster);
          } else {
            clusters.push({
              key: `${key}-item-${item.id}`,
              paragraphIndex: null,
              section: loc.section ? String(loc.section) : null,
              excerpt: loc.excerpt ? String(loc.excerpt) : null,
              pageEnd: typeof loc.page_end === 'number' ? loc.page_end : null,
              items: [item],
            });
          }
        }

        return {
          key,
          page: entry.page,
          label: entry.page === null ? '文档级 / 全局规范' : `第 ${entry.page} 页`,
          errorCount,
          warningCount,
          totalCount: entry.items.length,
          clusters,
        };
      });
  }, [detail]);

  useEffect(() => {
    if (!detail) return;
    setTargetRuleSetId(detail.rule_set_id);

    const expandAll = detail.violations.length <= 15;
    const initialRules: Record<string, boolean> = {};
    ruleGroups.forEach((group, idx) => {
      initialRules[group.ruleCode] = expandAll || idx < 3;
    });
    setExpandedRuleGroups(initialRules);

    const initialPages: Record<string, boolean> = {};
    pageGroups.forEach((group, idx) => {
      initialPages[group.key] = expandAll || idx < 5;
    });
    setExpandedPageGroups(initialPages);
    setShowAllItems({});
  }, [detail, ruleGroups, pageGroups]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  if (!shouldRender) return null;

  const activeRuleSet = detail ? ruleSets.find((r) => r.id === detail.rule_set_id) : undefined;
  const paperChecklistState = detail ? (checkedManualByPaper[detail.paper_id] ?? {}) : {};

  const toggleManualItem = (index: number) => {
    if (!detail) return;
    setCheckedManualByPaper((prev) => ({
      ...prev,
      [detail.paper_id]: {
        ...(prev[detail.paper_id] ?? {}),
        [index]: !prev[detail.paper_id]?.[index],
      },
    }));
  };

  const handleExpandAll = () => {
    if (viewMode === 'page') {
      const next: Record<string, boolean> = {};
      pageGroups.forEach((g) => {
        next[g.key] = true;
      });
      setExpandedPageGroups(next);
    } else {
      const next: Record<string, boolean> = {};
      ruleGroups.forEach((g) => {
        next[g.ruleCode] = true;
      });
      setExpandedRuleGroups(next);
    }
  };

  const handleCollapseAll = () => {
    if (viewMode === 'page') {
      setExpandedPageGroups({});
    } else {
      setExpandedRuleGroups({});
    }
  };

  return (
    <section
      aria-label="论文检测详情子页面"
      className={`fixed inset-y-0 right-0 left-0 z-30 flex flex-col border-l border-[#E8E6E1] bg-[#FAF9F7] shadow-[-8px_0_28px_rgba(24,24,27,0.08)] transition-transform duration-250 ease-[cubic-bezier(0.16,1,0.3,1)] lg:left-[248px] ${
        visible ? 'translate-x-0' : 'translate-x-full'
      }`}
    >
      {/* Subpage Header */}
      <div className="shrink-0 border-b border-[#E8E6E1] bg-white px-4 py-3.5 sm:px-6">
        <div className="mx-auto w-full max-w-[1120px]">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2.5">
                <button
                  type="button"
                  onClick={onClose}
                  className="inline-flex h-7 shrink-0 items-center gap-1 rounded-md px-2 text-xs font-medium text-[#52525B] transition-colors hover:bg-[#F3F2EE] hover:text-[#18181B]"
                >
                  <ArrowLeft className="h-3.5 w-3.5" />
                  <span>返回列表</span>
                </button>

                <span className="h-4 w-px shrink-0 bg-[#ECEAE5]" aria-hidden="true" />

                <h2 className="min-w-0 truncate text-sm font-semibold text-[#18181B] sm:text-base">
                  {detail ? detail.file_name : '正在加载检测详情...'}
                </h2>
                {detail && <VerdictBadge verdict={detail.verdict} />}
              </div>

              {detail && (
                <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 pl-1 text-xs text-[#71717A]">
                  <span className="uppercase">{detail.file_ext}</span>
                  <span>·</span>
                  <span className="tabular-nums">{formatFileSize(detail.file_size)}</span>
                  <span>·</span>
                  <span className="tabular-nums">
                    合规分 <strong className="text-[#18181B]">{formatScore(detail.score)}</strong>
                  </span>
                  <span>·</span>
                  <span className="tabular-nums">
                    通过 {detail.passed_rules_count} 条 / 跳过 {detail.skipped_rules_count} 条
                  </span>
                  <span>·</span>
                  <span className="tabular-nums">{formatDuration(detail.duration_ms)}</span>
                </div>
              )}
            </div>

            <button
              type="button"
              onClick={onClose}
              aria-label="关闭详情子页面"
              className="shrink-0 rounded-lg p-1.5 text-[#71717A] hover:bg-[#F3F2EE] hover:text-[#18181B]"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Action Bar: Template + Snapshot Recheck + Reparse Recheck + Primary CTA */}
          {detail && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[#E8E6E1] bg-[#FAF9F7] px-3 py-2">
              <div className="text-xs text-[#71717A]">
                当前模板：
                <span className="font-medium text-[#18181B]">
                  {activeRuleSet ? activeRuleSet.name : detail.rule_set_id}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  aria-label="选择重检模板"
                  value={targetRuleSetId}
                  onChange={(e) => setTargetRuleSetId(e.target.value)}
                  disabled={rechecking || ruleSets.length === 0}
                  className="h-8 max-w-[220px] rounded-lg border border-[#E2E0DA] bg-white px-2 text-xs text-[#18181B] focus:border-[#1E3A5F] focus:outline-none"
                >
                  {ruleSets.map((rs) => (
                    <option key={rs.id} value={rs.id}>
                      {rs.name}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  disabled={rechecking || !targetRuleSetId}
                  onClick={() => onRecheck(detail.paper_id, targetRuleSetId, false)}
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#E2E0DA] bg-white px-2.5 text-xs font-medium text-[#18181B] hover:bg-[#F7F7F5] disabled:opacity-55"
                >
                  {rechecking ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-[#1E3A5F]" />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5 text-[#52525B]" />
                  )}
                  <span>免重解析重检</span>
                </button>
                <button
                  type="button"
                  disabled={rechecking || !targetRuleSetId}
                  onClick={() => onRecheck(detail.paper_id, targetRuleSetId, true)}
                  title="从原始文件重新解析并应用最新解析器与规则"
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#C7D6E8] bg-[#EFF4FA] px-2.5 text-xs font-medium text-[#1E3A5F] hover:bg-[#E2ECF7] disabled:opacity-55"
                >
                  {rechecking ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-[#1E3A5F]" />
                  ) : (
                    <RotateCcw className="h-3.5 w-3.5 text-[#1E3A5F]" />
                  )}
                  <span>重新解析并检测</span>
                </button>
                {detail.parse_status === 'success' && (
                  <button
                    type="button"
                    disabled={openingRevision}
                    onClick={() => onOpenRevision(detail.id)}
                    className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#1E3A5F] px-3 text-xs font-semibold text-white hover:bg-[#162C49] disabled:opacity-55"
                  >
                    {openingRevision ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Wand2 className="h-3.5 w-3.5" />
                    )}
                    <span>进入修订工作台</span>
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Scrollable Content */}
      <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6">
        <div className="mx-auto w-full max-w-[1120px] space-y-4">
          {loading && !detail ? (
            <div className="flex flex-col items-center justify-center py-20 text-xs text-[#71717A]">
              <Loader2 className="h-5 w-5 animate-spin text-[#1E3A5F]" />
              <span className="mt-2">正在加载违规明细与格式快照...</span>
            </div>
          ) : detail ? (
            <>
              {/* Parse Error Banner */}
              {detail.parse_status === 'failed' && (
                <div className="rounded-xl border border-[#FDE68A] bg-[#FFFBEB] p-4 text-xs text-[#92400E]">
                  <div className="flex items-center gap-2 font-semibold">
                    <AlertCircle className="h-4 w-4 text-[#B45309]" />
                    <span>文档解析异常，无法执行格式规则检测</span>
                  </div>
                  <p className="mt-1.5 text-[#78350F]">
                    错误信息：{detail.parse_error || '文件已损坏或不是有效的 DOCX/PDF 文档'}
                  </p>
                </div>
              )}

              {/* IR Summary Card */}
              {detail.ir_summary && (
                <div className="rounded-xl border border-[#E8E6E1] bg-white p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-xs font-semibold text-[#18181B]">文档结构与字数快照</h3>
                    <div className="flex items-center gap-2">
                      {detail.file_ext === 'pdf' && (
                        <span
                          className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${
                            detail.ir_summary.is_image_only_pdf
                              ? 'border-[#FECACA] bg-[#FEF2F2] text-[#B91C1C]'
                              : 'border-[#BBF7D0] bg-[#ECFDF5] text-[#15803D]'
                          }`}
                        >
                          {detail.ir_summary.is_image_only_pdf
                            ? '纯扫描图像 PDF'
                            : `文本页占比 ${formatPercent(detail.ir_summary.stats.text_page_ratio)}`}
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={() => setShowCapabilities((prev) => !prev)}
                        className="text-[11px] font-medium text-[#1E3A5F] hover:underline"
                      >
                        {showCapabilities ? '隐藏解析精度' : '查看解析精度'}
                      </button>
                    </div>
                  </div>

                  <div className="mt-3 grid grid-cols-3 divide-y divide-[#ECEAE5] overflow-hidden rounded-lg border border-[#ECEAE5] sm:grid-cols-6 sm:divide-x sm:divide-y-0">
                    {[
                      { label: '总页数', val: `${detail.ir_summary.page_count} 页` },
                      {
                        label: '全文汉字',
                        val: detail.ir_summary.stats.total_chinese_chars.toLocaleString(),
                      },
                      {
                        label: '正文汉字',
                        val: detail.ir_summary.stats.body_chinese_chars.toLocaleString(),
                      },
                      {
                        label: '绪论汉字',
                        val: detail.ir_summary.stats.intro_chinese_chars.toLocaleString(),
                      },
                      { label: '中文摘要', val: `${detail.ir_summary.stats.abstract_cn_chars} 字` },
                      { label: '英文摘要', val: `${detail.ir_summary.stats.abstract_en_words} 词` },
                    ].map((metric) => (
                      <div key={metric.label} className="bg-[#FAF9F7]/60 px-2.5 py-2">
                        <div className="text-[11px] text-[#71717A]">{metric.label}</div>
                        <div className="mt-0.5 text-xs font-semibold tabular-nums text-[#18181B]">
                          {metric.val}
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Section coverage strip */}
                  <div className="mt-3">
                    <div className="mb-1.5 text-[11px] font-medium text-[#71717A]">
                      识别出的文档区块（{detail.ir_summary.sections.length} 个）
                    </div>
                    {detail.ir_summary.sections.length === 0 ? (
                      <span className="text-xs text-[#71717A]">未识别到标准顶层章节</span>
                    ) : (
                      <div className="flex flex-wrap gap-1.5">
                        {detail.ir_summary.sections.map((sec, idx) => (
                          <span
                            key={`${sec.key}-${sec.start_paragraph_index}-${idx}`}
                            title={`${sec.title} · ${sec.chinese_char_count} 汉字`}
                            className="inline-flex items-center gap-1 rounded-md border border-[#E8E6E1] bg-[#FAF9F7] px-2 py-0.5 text-[11px] text-[#18181B]"
                          >
                            <span className="font-medium">{getSectionLabel(sec.key)}</span>
                            {sec.page_start != null && (
                              <span className="tabular-nums text-[#71717A]">P.{sec.page_start}</span>
                            )}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {showCapabilities && (
                    <div className="mt-3 flex flex-wrap gap-1.5 border-t border-[#ECEAE5] pt-3">
                      {Object.entries(detail.ir_summary.capabilities).map(([capKey, supported]) => (
                        <span
                          key={capKey}
                          className={`rounded px-2 py-0.5 text-[11px] ${
                            supported
                              ? 'bg-[#ECFDF5] text-[#15803D]'
                              : 'bg-[#F3F2EE] text-[#52525B]'
                          }`}
                        >
                          {CAPABILITY_LABELS[capKey] ?? capKey}：{supported ? '精确' : '估算/受限'}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Violations List */}
              {detail.parse_status === 'success' && (
                <div className="space-y-2.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-xs font-semibold text-[#18181B]">
                      违规明细（共{' '}
                      <span className="tabular-nums">{detail.violations.length}</span> 处，涉及{' '}
                      <span className="tabular-nums">{ruleGroups.length}</span> 条规则，
                      <span className="tabular-nums">{pageGroups.length}</span> 个位置组）
                    </h3>

                    {detail.violations.length > 0 && (
                      <div className="flex flex-wrap items-center gap-3">
                        <div className="inline-flex rounded-lg border border-[#E8E6E1] bg-[#F3F2EE] p-0.5 text-[11px]">
                          <button
                            type="button"
                            onClick={() => setViewMode('page')}
                            className={`inline-flex items-center gap-1 rounded-md px-2 py-1 font-medium transition-colors ${
                              viewMode === 'page'
                                ? 'bg-white text-[#18181B] shadow-2xs'
                                : 'text-[#52525B] hover:text-[#18181B]'
                            }`}
                          >
                            <FileText className="h-3 w-3" />
                            <span>按页面顺序</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => setViewMode('rule')}
                            className={`inline-flex items-center gap-1 rounded-md px-2 py-1 font-medium transition-colors ${
                              viewMode === 'rule'
                                ? 'bg-white text-[#18181B] shadow-2xs'
                                : 'text-[#52525B] hover:text-[#18181B]'
                            }`}
                          >
                            <Layers className="h-3 w-3" />
                            <span>按规则分组</span>
                          </button>
                        </div>

                        <div className="flex items-center gap-2 text-[11px]">
                          <button
                            type="button"
                            onClick={handleExpandAll}
                            className="text-[#1E3A5F] hover:underline"
                          >
                            全部展开
                          </button>
                          <span className="text-[#D8D5CE]">|</span>
                          <button
                            type="button"
                            onClick={handleCollapseAll}
                            className="text-[#71717A] hover:underline"
                          >
                            全部收起
                          </button>
                        </div>
                      </div>
                    )}
                  </div>

                  {detail.violations.length === 0 ? (
                    <div className="flex items-center gap-3 rounded-xl border border-[#BBF7D0] bg-[#ECFDF5] p-4 text-xs text-[#15803D]">
                      <FileCheck2 className="h-5 w-5 shrink-0" />
                      <div>
                        <div className="font-semibold">全部适用自动检测规则均已通过</div>
                        <div className="mt-0.5 text-[#166534]">
                          未发现任何错误或警告项，仍建议结合下方人工复核清单完成最终形式审查。
                        </div>
                      </div>
                    </div>
                  ) : viewMode === 'page' ? (
                    <div className="divide-y divide-[#ECEAE5] overflow-hidden rounded-xl border border-[#E8E6E1] bg-white">
                      {pageGroups.map((pg) => {
                        const isExpanded = Boolean(expandedPageGroups[pg.key]);
                        const showAll = Boolean(showAllItems[pg.key]);
                        const visibleClusters = showAll ? pg.clusters : pg.clusters.slice(0, 8);

                        return (
                          <div key={pg.key}>
                            <button
                              type="button"
                              onClick={() =>
                                setExpandedPageGroups((prev) => ({
                                  ...prev,
                                  [pg.key]: !prev[pg.key],
                                }))
                              }
                              className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-[#FAF9F7]"
                            >
                              <div className="flex min-w-0 items-center gap-2.5">
                                {isExpanded ? (
                                  <ChevronDown className="h-4 w-4 shrink-0 text-[#71717A]" />
                                ) : (
                                  <ChevronRight className="h-4 w-4 shrink-0 text-[#71717A]" />
                                )}
                                <span className="rounded bg-[#EFF4FA] px-2 py-0.5 text-xs font-semibold tabular-nums text-[#1E3A5F]">
                                  {pg.label}
                                </span>
                                <span className="text-[11px] text-[#71717A]">
                                  {pg.clusters.length} 处位置
                                </span>
                              </div>
                              <div className="flex shrink-0 items-center gap-1.5 text-[11px] tabular-nums">
                                {pg.errorCount > 0 && (
                                  <span className="rounded-full bg-[#FEF2F2] px-2 py-0.5 font-semibold text-[#B91C1C]">
                                    {pg.errorCount} 错误
                                  </span>
                                )}
                                {pg.warningCount > 0 && (
                                  <span className="rounded-full bg-[#FFFBEB] px-2 py-0.5 font-semibold text-[#B45309]">
                                    {pg.warningCount} 警告
                                  </span>
                                )}
                              </div>
                            </button>

                            {isExpanded && (
                              <div className="divide-y divide-[#ECEAE5] border-t border-[#ECEAE5] bg-[#FAF9F7]/40">
                                {visibleClusters.map((cluster) => (
                                  <div key={cluster.key} className="space-y-2.5 px-4 py-3 text-xs">
                                    <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-[#52525B]">
                                      {cluster.paragraphIndex !== null && (
                                        <span className="rounded bg-[#F3F2EE] px-1.5 py-0.5 font-medium tabular-nums text-[#18181B]">
                                          第 {cluster.paragraphIndex + 1} 段
                                        </span>
                                      )}
                                      {pg.page !== null &&
                                        cluster.pageEnd !== null &&
                                        cluster.pageEnd !== pg.page && (
                                          <span className="rounded bg-[#EFF4FA] px-1.5 py-0.5 tabular-nums text-[#1E3A5F]">
                                            跨第 {pg.page}–{cluster.pageEnd} 页
                                          </span>
                                        )}
                                      {cluster.section && (
                                        <span className="rounded bg-[#F3F2EE] px-1.5 py-0.5 text-[#52525B]">
                                          区块：{getSectionLabel(cluster.section)}
                                        </span>
                                      )}
                                      {cluster.items.length > 1 && (
                                        <span className="rounded bg-[#EFF4FA] px-1.5 py-0.5 text-[10px] font-medium text-[#1E3A5F]">
                                          本段命中 {cluster.items.length} 条规则
                                        </span>
                                      )}
                                    </div>

                                    {cluster.excerpt && (
                                      <blockquote className="rounded-md border-l-2 border-[#D8D5CE] bg-white px-2.5 py-1.5 text-[11px] text-[#52525B] break-all">
                                        “{cluster.excerpt}”
                                      </blockquote>
                                    )}

                                    <div className="space-y-2">
                                      {cluster.items.map((item) => {
                                        const isError = item.severity === 'error';
                                        const highlight = item.location?.highlight_excerpt
                                          ? String(item.location.highlight_excerpt)
                                          : null;

                                        return (
                                          <div
                                            key={item.id}
                                            className="rounded-lg border border-[#E8E6E1] bg-white p-2.5 space-y-2"
                                          >
                                            <div className="flex flex-wrap items-center justify-between gap-2">
                                              <div className="flex flex-wrap items-center gap-1.5">
                                                <span
                                                  className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                                                    isError
                                                      ? 'bg-[#FEF2F2] text-[#B91C1C]'
                                                      : 'bg-[#FFFBEB] text-[#B45309]'
                                                  }`}
                                                >
                                                  {isError ? 'ERROR' : 'WARN'}
                                                </span>
                                                <span className="text-xs font-semibold text-[#18181B]">
                                                  {item.rule_name}
                                                </span>
                                                <span className="rounded bg-[#F3F2EE] px-1.5 py-0.5 text-[10px] text-[#52525B]">
                                                  {getCategoryLabel(item.category)}
                                                </span>
                                              </div>
                                              <span className="font-mono text-[10px] text-[#71717A]">
                                                {item.rule_code}
                                              </span>
                                            </div>

                                            {highlight && highlight !== cluster.excerpt && (
                                              <div className="rounded bg-[#FFF7ED] px-2 py-1 text-[11px] text-[#9A3412] break-all">
                                                <strong className="font-medium">异常片段：</strong>
                                                “{highlight}”
                                              </div>
                                            )}

                                            <div className="grid gap-2 sm:grid-cols-2">
                                              <div className="rounded-md border border-[#ECEAE5] bg-[#FAF9F7] px-2.5 py-1.5">
                                                <div className="text-[10px] font-semibold text-[#71717A]">
                                                  规范期望值
                                                </div>
                                                <div className="mt-0.5 text-xs text-[#18181B] break-words">
                                                  {item.expected}
                                                </div>
                                              </div>
                                              <div
                                                className={`rounded-md border px-2.5 py-1.5 ${
                                                  isError
                                                    ? 'border-[#FECACA] bg-[#FEF2F2]/60'
                                                    : 'border-[#FDE68A] bg-[#FFFBEB]/60'
                                                }`}
                                              >
                                                <div
                                                  className={`text-[10px] font-semibold ${
                                                    isError ? 'text-[#B91C1C]' : 'text-[#B45309]'
                                                  }`}
                                                >
                                                  实际检测值
                                                </div>
                                                <div className="mt-0.5 text-xs text-[#18181B] break-words">
                                                  {item.actual}
                                                </div>
                                              </div>
                                            </div>

                                            <p className="text-[11px] text-[#52525B]">
                                              <strong className="font-medium text-[#18181B]">
                                                修改建议：
                                              </strong>
                                              {item.message}
                                            </p>
                                          </div>
                                        );
                                      })}
                                    </div>
                                  </div>
                                ))}

                                {pg.clusters.length > 8 && (
                                  <div className="bg-white px-4 py-2 text-center">
                                    <button
                                      type="button"
                                      onClick={() =>
                                        setShowAllItems((prev) => ({
                                          ...prev,
                                          [pg.key]: !prev[pg.key],
                                        }))
                                      }
                                      className="text-xs font-medium text-[#1E3A5F] hover:underline"
                                    >
                                      {showAll
                                        ? '收起多余位置（仅显示前 8 处）'
                                        : `展开本页全部 ${pg.clusters.length} 处（剩余 ${pg.clusters.length - 8} 处）`}
                                    </button>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="divide-y divide-[#ECEAE5] overflow-hidden rounded-xl border border-[#E8E6E1] bg-white">
                      {ruleGroups.map((group) => {
                        const isExpanded = Boolean(expandedRuleGroups[group.ruleCode]);
                        const showAll = Boolean(showAllItems[group.ruleCode]);
                        const visibleItems = showAll ? group.items : group.items.slice(0, 5);
                        const isError = group.severity === 'error';

                        return (
                          <div key={group.ruleCode}>
                            <button
                              type="button"
                              onClick={() =>
                                setExpandedRuleGroups((prev) => ({
                                  ...prev,
                                  [group.ruleCode]: !prev[group.ruleCode],
                                }))
                              }
                              className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-[#FAF9F7]"
                            >
                              <div className="flex min-w-0 items-center gap-2.5">
                                {isExpanded ? (
                                  <ChevronDown className="h-4 w-4 shrink-0 text-[#71717A]" />
                                ) : (
                                  <ChevronRight className="h-4 w-4 shrink-0 text-[#71717A]" />
                                )}
                                <span
                                  className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                                    isError
                                      ? 'bg-[#FEF2F2] text-[#B91C1C]'
                                      : 'bg-[#FFFBEB] text-[#B45309]'
                                  }`}
                                >
                                  {isError ? 'ERROR' : 'WARN'}
                                </span>
                                <span className="truncate text-xs font-semibold text-[#18181B]">
                                  {group.ruleName}
                                </span>
                                <span className="hidden rounded bg-[#F3F2EE] px-1.5 py-0.5 text-[10px] text-[#52525B] sm:inline-block">
                                  {getCategoryLabel(group.category)}
                                </span>
                              </div>
                              <div className="flex shrink-0 items-center gap-2">
                                <span className="hidden font-mono text-[10px] text-[#71717A] md:inline">
                                  {group.ruleCode}
                                </span>
                                <span className="rounded-full bg-[#F3F2EE] px-2 py-0.5 text-[11px] font-semibold tabular-nums text-[#18181B]">
                                  {group.items.length} 处
                                </span>
                              </div>
                            </button>

                            {isExpanded && (
                              <div className="divide-y divide-[#ECEAE5] border-t border-[#ECEAE5] bg-[#FAF9F7]/40">
                                {visibleItems.map((item) => {
                                  const loc = item.location ?? {};
                                  const itemIsError = item.severity === 'error';
                                  const highlight = loc.highlight_excerpt
                                    ? String(loc.highlight_excerpt)
                                    : null;
                                  return (
                                    <div key={item.id} className="space-y-2 px-4 py-3 text-xs">
                                      <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-[#52525B]">
                                        {loc.page != null && (
                                          <span className="rounded bg-[#EFF4FA] px-1.5 py-0.5 font-medium tabular-nums text-[#1E3A5F]">
                                            {loc.page_end && loc.page_end !== loc.page
                                              ? `第 ${loc.page}–${loc.page_end} 页`
                                              : `第 ${loc.page} 页`}
                                          </span>
                                        )}
                                        {loc.section && (
                                          <span className="rounded bg-[#F3F2EE] px-1.5 py-0.5 text-[#18181B]">
                                            区块：{getSectionLabel(String(loc.section))}
                                          </span>
                                        )}
                                        {loc.paragraph_index != null && (
                                          <span className="rounded bg-[#F3F2EE] px-1.5 py-0.5 tabular-nums text-[#52525B]">
                                            第 {Number(loc.paragraph_index) + 1} 段
                                          </span>
                                        )}
                                      </div>

                                      {loc.excerpt && (
                                        <blockquote className="rounded-md border-l-2 border-[#D8D5CE] bg-white px-2.5 py-1.5 text-[11px] text-[#52525B] break-all">
                                          “{String(loc.excerpt)}”
                                        </blockquote>
                                      )}

                                      {highlight && highlight !== String(loc.excerpt ?? '') && (
                                        <div className="rounded bg-[#FFF7ED] px-2 py-1 text-[11px] text-[#9A3412] break-all">
                                          <strong className="font-medium">异常片段：</strong>“
                                          {highlight}”
                                        </div>
                                      )}

                                      <div className="grid gap-2 sm:grid-cols-2">
                                        <div className="rounded-lg border border-[#E8E6E1] bg-white px-2.5 py-2">
                                          <div className="text-[10px] font-semibold text-[#71717A]">
                                            规范期望值
                                          </div>
                                          <div className="mt-0.5 text-xs text-[#18181B] break-words">
                                            {item.expected}
                                          </div>
                                        </div>
                                        <div
                                          className={`rounded-lg border px-2.5 py-2 ${
                                            itemIsError
                                              ? 'border-[#FECACA] bg-[#FEF2F2]/60'
                                              : 'border-[#FDE68A] bg-[#FFFBEB]/60'
                                          }`}
                                        >
                                          <div
                                            className={`text-[10px] font-semibold ${
                                              itemIsError ? 'text-[#B91C1C]' : 'text-[#B45309]'
                                            }`}
                                          >
                                            实际检测值
                                          </div>
                                          <div className="mt-0.5 text-xs text-[#18181B] break-words">
                                            {item.actual}
                                          </div>
                                        </div>
                                      </div>

                                      <p className="text-[11px] text-[#52525B]">
                                        <strong className="font-medium text-[#18181B]">
                                          修改建议：
                                        </strong>
                                        {item.message}
                                      </p>
                                    </div>
                                  );
                                })}

                                {group.items.length > 5 && (
                                  <div className="bg-white px-4 py-2 text-center">
                                    <button
                                      type="button"
                                      onClick={() =>
                                        setShowAllItems((prev) => ({
                                          ...prev,
                                          [group.ruleCode]: !prev[group.ruleCode],
                                        }))
                                      }
                                      className="text-xs font-medium text-[#1E3A5F] hover:underline"
                                    >
                                      {showAll
                                        ? '收起多余明细（仅显示前 5 条）'
                                        : `展开全部 ${group.items.length} 条明细（剩余 ${group.items.length - 5} 条）`}
                                    </button>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* Manual Checklist Accordion */}
              {detail.manual_checklist.length > 0 && (
                <div className="overflow-hidden rounded-xl border border-[#E8E6E1] bg-white">
                  <button
                    type="button"
                    onClick={() => setChecklistOpen((prev) => !prev)}
                    className="flex w-full items-center justify-between px-4 py-3 text-left text-xs font-semibold text-[#18181B] hover:bg-[#FAF9F7]"
                  >
                    <div className="flex items-center gap-2">
                      <ClipboardCheck className="h-4 w-4 text-[#1E3A5F]" />
                      <span>需人工复核项清单（{detail.manual_checklist.length} 项）</span>
                      <span className="rounded bg-[#F3F2EE] px-1.5 py-0.5 text-[10px] font-normal text-[#71717A]">
                        不触发自动 FAIL
                      </span>
                    </div>
                    {checklistOpen ? (
                      <ChevronDown className="h-4 w-4 text-[#71717A]" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-[#71717A]" />
                    )}
                  </button>

                  {checklistOpen && (
                    <div className="divide-y divide-[#ECEAE5] border-t border-[#ECEAE5] px-4 py-2">
                      {detail.manual_checklist.map((item, idx) => {
                        const checked = Boolean(paperChecklistState[idx]);
                        return (
                          <label
                            key={idx}
                            className="flex cursor-pointer items-start gap-2.5 py-2 text-xs text-[#18181B]"
                          >
                            <button
                              type="button"
                              role="checkbox"
                              aria-checked={checked}
                              onClick={() => toggleManualItem(idx)}
                              className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors ${
                                checked
                                  ? 'border-[#16A34A] bg-[#16A34A] text-white'
                                  : 'border-[#D8D5CE] bg-white'
                              }`}
                            >
                              {checked && <Check className="h-3 w-3" />}
                            </button>
                            <span className={checked ? 'text-[#71717A] line-through' : ''}>
                              {item}
                            </span>
                          </label>
                        );
                      })}
                      <div className="flex items-center gap-1.5 py-2 text-[11px] text-[#71717A]">
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        <span>勾选状态仅保存在当前浏览器会话中，用于辅助人工核查。</span>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <div className="py-20 text-center text-xs text-[#71717A]">未找到该检测记录</div>
          )}
        </div>
      </div>
    </section>
  );
}
