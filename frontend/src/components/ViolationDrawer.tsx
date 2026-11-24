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
  Loader2,
  RefreshCw,
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
  onRecheck: (paperId: string, ruleSetId: string) => Promise<void>;
  onOpenRevision: (runId: string) => void;
}

interface ViolationGroup {
  ruleCode: string;
  ruleName: string;
  category: string;
  severity: Severity;
  items: ViolationResponse[];
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
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});
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

  useEffect(() => {
    if (!detail) return;
    setTargetRuleSetId(detail.rule_set_id);

    const counts = new Map<string, { severity: Severity; count: number }>();
    for (const v of detail.violations) {
      const existing = counts.get(v.rule_code);
      if (existing) {
        existing.count += 1;
      } else {
        counts.set(v.rule_code, { severity: v.severity, count: 1 });
      }
    }
    const sortedCodes = Array.from(counts.entries())
      .sort((a, b) => {
        if (a[1].severity !== b[1].severity) return a[1].severity === 'error' ? -1 : 1;
        if (a[1].count !== b[1].count) return b[1].count - a[1].count;
        return a[0].localeCompare(b[0]);
      })
      .map(([code]) => code);

    const expandAll = detail.violations.length <= 15;
    const initialExpanded: Record<string, boolean> = {};
    sortedCodes.forEach((code, idx) => {
      initialExpanded[code] = expandAll || idx < 3;
    });
    setExpandedGroups(initialExpanded);
    setShowAllItems({});
  }, [detail]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  const groups = useMemo<ViolationGroup[]>(() => {
    if (!detail) return [];
    const map = new Map<string, ViolationGroup>();
    for (const v of detail.violations) {
      const existing = map.get(v.rule_code);
      if (existing) {
        existing.items.push(v);
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
    return Array.from(map.values()).sort((a, b) => {
      if (a.severity !== b.severity) return a.severity === 'error' ? -1 : 1;
      if (a.items.length !== b.items.length) return b.items.length - a.items.length;
      return a.ruleCode.localeCompare(b.ruleCode);
    });
  }, [detail]);

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

          {/* Action Bar: Secondary Recheck + Single Primary CTA */}
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
                  onClick={() => onRecheck(detail.paper_id, targetRuleSetId)}
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#E2E0DA] bg-white px-2.5 text-xs font-medium text-[#18181B] hover:bg-[#F7F7F5] disabled:opacity-55"
                >
                  {rechecking ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-[#1E3A5F]" />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5 text-[#52525B]" />
                  )}
                  <span>免重解析重检</span>
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
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-semibold text-[#18181B]">
                      违规明细（共{' '}
                      <span className="tabular-nums">{detail.violations.length}</span> 处，涉及{' '}
                      <span className="tabular-nums">{groups.length}</span> 条规则）
                    </h3>
                    {groups.length > 0 && (
                      <div className="flex items-center gap-2 text-[11px]">
                        <button
                          type="button"
                          onClick={() => {
                            const next: Record<string, boolean> = {};
                            groups.forEach((g) => {
                              next[g.ruleCode] = true;
                            });
                            setExpandedGroups(next);
                          }}
                          className="text-[#1E3A5F] hover:underline"
                        >
                          全部展开
                        </button>
                        <span className="text-[#D8D5CE]">|</span>
                        <button
                          type="button"
                          onClick={() => setExpandedGroups({})}
                          className="text-[#71717A] hover:underline"
                        >
                          全部收起
                        </button>
                      </div>
                    )}
                  </div>

                  {groups.length === 0 ? (
                    <div className="flex items-center gap-3 rounded-xl border border-[#BBF7D0] bg-[#ECFDF5] p-4 text-xs text-[#15803D]">
                      <FileCheck2 className="h-5 w-5 shrink-0" />
                      <div>
                        <div className="font-semibold">全部适用自动检测规则均已通过</div>
                        <div className="mt-0.5 text-[#166534]">
                          未发现任何错误或警告项，仍建议结合下方人工复核清单完成最终形式审查。
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="divide-y divide-[#ECEAE5] overflow-hidden rounded-xl border border-[#E8E6E1] bg-white">
                      {groups.map((group) => {
                        const isExpanded = Boolean(expandedGroups[group.ruleCode]);
                        const showAll = Boolean(showAllItems[group.ruleCode]);
                        const visibleItems = showAll ? group.items : group.items.slice(0, 5);
                        const isError = group.severity === 'error';

                        return (
                          <div key={group.ruleCode}>
                            <button
                              type="button"
                              onClick={() =>
                                setExpandedGroups((prev) => ({
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
                                  return (
                                    <div key={item.id} className="space-y-2 px-4 py-3 text-xs">
                                      <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-[#52525B]">
                                        {loc.page != null && (
                                          <span className="rounded bg-[#EFF4FA] px-1.5 py-0.5 font-medium tabular-nums text-[#1E3A5F]">
                                            第 {loc.page} 页
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
                                        <strong className="font-medium text-[#18181B]">修改建议：</strong>
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
