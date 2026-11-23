import { useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
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
  const [targetRuleSetId, setTargetRuleSetId] = useState('');
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});
  const [showAllItems, setShowAllItems] = useState<Record<string, boolean>>({});
  const [showCapabilities, setShowCapabilities] = useState(false);
  const [checklistOpen, setChecklistOpen] = useState(false);
  const [checkedManualByPaper, setCheckedManualByPaper] = useState<
    Record<string, Record<number, boolean>>
  >({});

  useEffect(() => {
    if (!detail) return;
    setTargetRuleSetId(detail.rule_set_id);

    // Group order determines which rules auto-expand
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

  if (!open) return null;

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
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="fixed inset-0 bg-[#1A2332]/35 backdrop-blur-[1px]"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        aria-label="论文检测详情抽屉"
        className="relative z-10 flex h-full w-full max-w-3xl flex-col border-l border-[#E5E2DC] bg-[#FAF9F6] shadow-2xl"
      >
        {/* Header */}
        <div className="border-b border-[#E5E2DC] bg-white px-5 py-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="truncate text-base font-semibold text-[#1A2332]">
                  {detail ? detail.file_name : '正在加载检测详情...'}
                </h2>
                {detail && <VerdictBadge verdict={detail.verdict} />}
              </div>
              {detail && (
                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[#5A6577]">
                  <span className="uppercase">{detail.file_ext}</span>
                  <span>·</span>
                  <span className="tabular-nums">{formatFileSize(detail.file_size)}</span>
                  <span>·</span>
                  <span className="tabular-nums">
                    合规分 <strong className="text-[#1A2332]">{formatScore(detail.score)}</strong>
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
              aria-label="关闭详情抽屉"
              className="rounded-lg p-1.5 text-[#5A6577] hover:bg-[#FAF9F6] hover:text-[#1A2332]"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Inline Recheck Bar */}
          {detail && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[#E5E2DC] bg-[#FAF9F6] px-3 py-2">
              <div className="text-xs text-[#5A6577]">
                当前模板：
                <span className="font-medium text-[#1A2332]">
                  {activeRuleSet ? activeRuleSet.name : detail.rule_set_id}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <select
                  aria-label="选择重检模板"
                  value={targetRuleSetId}
                  onChange={(e) => setTargetRuleSetId(e.target.value)}
                  disabled={rechecking || ruleSets.length === 0}
                  className="h-7 max-w-[220px] rounded-md border border-[#E5E2DC] bg-white px-2 text-xs text-[#1A2332] focus:border-[#234B7A] focus:outline-none"
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
                  className="inline-flex h-7 items-center gap-1.5 rounded-md bg-[#234B7A] px-2.5 text-xs font-medium text-white hover:bg-[#1B3B61] disabled:opacity-55"
                >
                  {rechecking ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5" />
                  )}
                  <span>免重解析重检</span>
                </button>
                {detail.parse_status === 'success' && (
                  <button
                    type="button"
                    disabled={openingRevision}
                    onClick={() => onOpenRevision(detail.id)}
                    className="inline-flex h-7 items-center gap-1.5 rounded-md border border-[#234B7A] bg-white px-2.5 text-xs font-semibold text-[#234B7A] hover:bg-[#EEF3F9] disabled:opacity-55"
                  >
                    {openingRevision ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Wand2 className="h-3.5 w-3.5" />
                    )}
                    <span>调整论文</span>
                  </button>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 space-y-4 overflow-y-auto p-5">
          {loading && !detail ? (
            <div className="flex flex-col items-center justify-center py-16 text-xs text-[#5A6577]">
              <Loader2 className="h-6 w-6 animate-spin text-[#234B7A]" />
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
                <div className="rounded-xl border border-[#E5E2DC] bg-white p-4 shadow-2xs">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-xs font-semibold text-[#1A2332]">文档解析摘要（Format IR 快照）</h3>
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
                        className="text-[11px] font-medium text-[#234B7A] hover:underline"
                      >
                        {showCapabilities ? '隐藏解析精度' : '查看解析精度'}
                      </button>
                    </div>
                  </div>

                  <div className="mt-3 grid grid-cols-3 gap-2.5 sm:grid-cols-6">
                    {[
                      { label: '总页数', val: `${detail.ir_summary.page_count} 页` },
                      { label: '全文汉字', val: detail.ir_summary.stats.total_chinese_chars.toLocaleString() },
                      { label: '正文汉字', val: detail.ir_summary.stats.body_chinese_chars.toLocaleString() },
                      { label: '绪论汉字', val: detail.ir_summary.stats.intro_chinese_chars.toLocaleString() },
                      { label: '中文摘要', val: `${detail.ir_summary.stats.abstract_cn_chars} 字` },
                      { label: '英文摘要', val: `${detail.ir_summary.stats.abstract_en_words} 词` },
                    ].map((metric) => (
                      <div
                        key={metric.label}
                        className="rounded-lg border border-[#EFECE6] bg-[#FAF9F6] px-2.5 py-2"
                      >
                        <div className="text-[11px] text-[#8791A1]">{metric.label}</div>
                        <div className="mt-0.5 text-xs font-semibold tabular-nums text-[#1A2332]">
                          {metric.val}
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Section coverage strip */}
                  <div className="mt-3">
                    <div className="mb-1.5 text-[11px] font-medium text-[#5A6577]">
                      识别出的文档区块（{detail.ir_summary.sections.length} 个）
                    </div>
                    {detail.ir_summary.sections.length === 0 ? (
                      <span className="text-xs text-[#8791A1]">未识别到标准顶层章节</span>
                    ) : (
                      <div className="flex flex-wrap gap-1.5">
                        {detail.ir_summary.sections.map((sec, idx) => (
                          <span
                            key={`${sec.key}-${sec.start_paragraph_index}-${idx}`}
                            title={`${sec.title} · ${sec.chinese_char_count} 汉字`}
                            className="inline-flex items-center gap-1 rounded-md border border-[#E5E2DC] bg-[#FAF9F6] px-2 py-0.5 text-[11px] text-[#1A2332]"
                          >
                            <span className="font-medium">{getSectionLabel(sec.key)}</span>
                            {sec.page_start != null && (
                              <span className="tabular-nums text-[#8791A1]">P.{sec.page_start}</span>
                            )}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {showCapabilities && (
                    <div className="mt-3 flex flex-wrap gap-1.5 border-t border-[#EFECE6] pt-3">
                      {Object.entries(detail.ir_summary.capabilities).map(([capKey, supported]) => (
                        <span
                          key={capKey}
                          className={`rounded px-2 py-0.5 text-[11px] ${
                            supported
                              ? 'bg-[#ECFDF5] text-[#15803D]'
                              : 'bg-[#F3F4F6] text-[#6B7280]'
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
                    <h3 className="text-xs font-semibold text-[#1A2332]">
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
                          className="text-[#234B7A] hover:underline"
                        >
                          全部展开
                        </button>
                        <span className="text-[#D5D0C7]">|</span>
                        <button
                          type="button"
                          onClick={() => setExpandedGroups({})}
                          className="text-[#5A6577] hover:underline"
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
                    groups.map((group) => {
                      const isExpanded = Boolean(expandedGroups[group.ruleCode]);
                      const showAll = Boolean(showAllItems[group.ruleCode]);
                      const visibleItems = showAll ? group.items : group.items.slice(0, 5);
                      const isError = group.severity === 'error';

                      return (
                        <div
                          key={group.ruleCode}
                          className="overflow-hidden rounded-xl border border-[#E5E2DC] bg-white shadow-2xs"
                        >
                          <button
                            type="button"
                            onClick={() =>
                              setExpandedGroups((prev) => ({
                                ...prev,
                                [group.ruleCode]: !prev[group.ruleCode],
                              }))
                            }
                            className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-[#FAF9F6]"
                          >
                            <div className="flex min-w-0 items-center gap-2.5">
                              {isExpanded ? (
                                <ChevronDown className="h-4 w-4 shrink-0 text-[#5A6577]" />
                              ) : (
                                <ChevronRight className="h-4 w-4 shrink-0 text-[#5A6577]" />
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
                              <span className="truncate text-xs font-semibold text-[#1A2332]">
                                {group.ruleName}
                              </span>
                              <span className="hidden rounded bg-[#FAF9F6] px-1.5 py-0.5 text-[10px] text-[#5A6577] sm:inline-block">
                                {getCategoryLabel(group.category)}
                              </span>
                            </div>
                            <div className="flex shrink-0 items-center gap-2">
                              <span className="hidden font-mono text-[10px] text-[#8791A1] md:inline">
                                {group.ruleCode}
                              </span>
                              <span className="rounded-full bg-[#FAF9F6] px-2 py-0.5 text-[11px] font-semibold tabular-nums text-[#1A2332]">
                                {group.items.length} 处
                              </span>
                            </div>
                          </button>

                          {isExpanded && (
                            <div className="divide-y divide-[#EFECE6] border-t border-[#EFECE6]">
                              {visibleItems.map((item) => {
                                const loc = item.location ?? {};
                                return (
                                  <div key={item.id} className="space-y-2 px-4 py-3 text-xs">
                                    {/* Location tags */}
                                    <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-[#5A6577]">
                                      {loc.page != null && (
                                        <span className="rounded bg-[#EEF3F9] px-1.5 py-0.5 font-medium tabular-nums text-[#234B7A]">
                                          第 {loc.page} 页
                                        </span>
                                      )}
                                      {loc.section && (
                                        <span className="rounded bg-[#FAF9F6] px-1.5 py-0.5 text-[#1A2332]">
                                          区块：{getSectionLabel(String(loc.section))}
                                        </span>
                                      )}
                                      {loc.paragraph_index != null && (
                                        <span className="rounded bg-[#FAF9F6] px-1.5 py-0.5 tabular-nums text-[#5A6577]">
                                          第 {Number(loc.paragraph_index) + 1} 段
                                        </span>
                                      )}
                                    </div>

                                    {loc.excerpt && (
                                      <blockquote className="rounded-md border-l-2 border-[#C8C3B9] bg-[#FAF9F6] px-2.5 py-1.5 text-[11px] text-[#5A6577] break-all">
                                        “{String(loc.excerpt)}”
                                      </blockquote>
                                    )}

                                    <div className="grid gap-2 sm:grid-cols-2">
                                      <div className="rounded-lg border border-[#E5E2DC] bg-[#FAF9F6]/70 px-2.5 py-2">
                                        <div className="text-[10px] font-semibold tracking-wide text-[#5A6577]">
                                          规范期望值
                                        </div>
                                        <div className="mt-0.5 text-xs text-[#1A2332] break-words">
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
                                          className={`text-[10px] font-semibold tracking-wide ${
                                            isError ? 'text-[#B91C1C]' : 'text-[#B45309]'
                                          }`}
                                        >
                                          实际检测值
                                        </div>
                                        <div className="mt-0.5 text-xs text-[#1A2332] break-words">
                                          {item.actual}
                                        </div>
                                      </div>
                                    </div>

                                    <p className="text-[11px] text-[#5A6577]">
                                      <strong className="font-medium text-[#1A2332]">修改建议：</strong>
                                      {item.message}
                                    </p>
                                  </div>
                                );
                              })}

                              {group.items.length > 5 && (
                                <div className="bg-[#FAF9F6]/70 px-4 py-2 text-center">
                                  <button
                                    type="button"
                                    onClick={() =>
                                      setShowAllItems((prev) => ({
                                        ...prev,
                                        [group.ruleCode]: !prev[group.ruleCode],
                                      }))
                                    }
                                    className="text-xs font-medium text-[#234B7A] hover:underline"
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
                    })
                  )}
                </div>
              )}

              {/* Manual Checklist Accordion */}
              {detail.manual_checklist.length > 0 && (
                <div className="rounded-xl border border-[#E5E2DC] bg-white shadow-2xs">
                  <button
                    type="button"
                    onClick={() => setChecklistOpen((prev) => !prev)}
                    className="flex w-full items-center justify-between px-4 py-3 text-left text-xs font-semibold text-[#1A2332] hover:bg-[#FAF9F6]"
                  >
                    <div className="flex items-center gap-2">
                      <ClipboardCheck className="h-4 w-4 text-[#234B7A]" />
                      <span>需人工复核项清单（{detail.manual_checklist.length} 项）</span>
                      <span className="rounded bg-[#FAF9F6] px-1.5 py-0.5 text-[10px] font-normal text-[#8791A1]">
                        不触发自动 FAIL
                      </span>
                    </div>
                    {checklistOpen ? (
                      <ChevronDown className="h-4 w-4 text-[#5A6577]" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-[#5A6577]" />
                    )}
                  </button>

                  {checklistOpen && (
                    <div className="divide-y divide-[#EFECE6] border-t border-[#EFECE6] px-4 py-2">
                      {detail.manual_checklist.map((item, idx) => {
                        const checked = Boolean(paperChecklistState[idx]);
                        return (
                          <label
                            key={idx}
                            className="flex cursor-pointer items-start gap-2.5 py-2 text-xs text-[#1A2332]"
                          >
                            <button
                              type="button"
                              role="checkbox"
                              aria-checked={checked}
                              onClick={() => toggleManualItem(idx)}
                              className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors ${
                                checked
                                  ? 'border-[#15803D] bg-[#15803D] text-white'
                                  : 'border-[#C8C3B9] bg-white'
                              }`}
                            >
                              {checked && <Check className="h-3 w-3" />}
                            </button>
                            <span className={checked ? 'text-[#8791A1] line-through' : ''}>
                              {item}
                            </span>
                          </label>
                        );
                      })}
                      <div className="flex items-center gap-1.5 py-2 text-[11px] text-[#8791A1]">
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        <span>勾选状态仅保存在当前浏览器会话中，用于辅助人工核查。</span>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <div className="py-16 text-center text-xs text-[#8791A1]">未找到该检测记录</div>
          )}
        </div>
      </aside>
    </div>
  );
}
