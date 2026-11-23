import { useMemo, useState } from 'react';
import {
  BookOpen,
  CheckCircle2,
  Loader2,
  MapPin,
  Search,
  Sparkles,
  X,
} from 'lucide-react';
import type { RulebookEntry, RuleStatus } from '../types/revisions';
import { getCategoryLabel, SCOPE_LABELS } from '../utils/format';

interface RulebookPanelProps {
  rulebook: RulebookEntry[];
  editable: boolean;
  activeRuleCode: string | null;
  fixingRuleCode: string | null;
  onJumpToParagraph: (paragraphIndex: number, ruleCode: string) => void;
  onSelectRule: (ruleCode: string | null) => void;
  onFixSingleRule: (ruleCode: string) => Promise<void>;
}

export function RulebookPanel({
  rulebook,
  editable,
  activeRuleCode,
  fixingRuleCode,
  onJumpToParagraph,
  onSelectRule,
  onFixSingleRule,
}: RulebookPanelProps) {
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | RuleStatus>('all');

  const counts = useMemo(() => {
    let open = 0;
    let fixed = 0;
    let ignored = 0;
    for (const item of rulebook) {
      if (item.status === 'fixed') fixed += 1;
      else if (item.status === 'ignored') ignored += 1;
      else open += 1;
    }
    return { open, fixed, ignored };
  }, [rulebook]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rulebook.filter((entry) => {
      if (statusFilter !== 'all' && entry.status !== statusFilter) return false;
      if (!q) return true;
      return (
        entry.rule_name.toLowerCase().includes(q) ||
        entry.rule_code.toLowerCase().includes(q) ||
        entry.expected.toLowerCase().includes(q) ||
        entry.guidance.toLowerCase().includes(q) ||
        entry.bubble_note.toLowerCase().includes(q) ||
        getCategoryLabel(entry.category).toLowerCase().includes(q)
      );
    });
  }, [rulebook, query, statusFilter]);

  return (
    <aside
      aria-label="可查规则书"
      className="flex h-full flex-col overflow-hidden rounded-xl border border-[#E5E2DC] bg-white shadow-[0_1px_2px_rgba(26,35,50,0.04)]"
    >
      {/* Header */}
      <div className="border-b border-[#EFECE6] p-3.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <BookOpen className="h-4 w-4 text-[#234B7A]" />
            <h2 className="text-xs font-semibold text-[#1A2332]">可查修订规则书</h2>
          </div>
          <div className="flex items-center gap-1.5 text-[11px] tabular-nums">
            <span className="rounded bg-[#FEF2F2] px-1.5 py-0.5 font-medium text-[#B91C1C]">
              待修 {counts.open}
            </span>
            <span className="rounded bg-[#ECFDF5] px-1.5 py-0.5 font-medium text-[#15803D]">
              已解 {counts.fixed}
            </span>
          </div>
        </div>

        {/* Search */}
        <div className="relative mt-2.5">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-[#8791A1]" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="检索规则名、要求或建议..."
            className="h-8 w-full rounded-lg border border-[#E5E2DC] bg-[#FAF9F6] pr-7 pl-8 text-xs text-[#1A2332] placeholder:text-[#8791A1] focus:border-[#234B7A] focus:bg-white focus:outline-none"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-0.5 text-[#8791A1] hover:text-[#1A2332]"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {/* Filter pills */}
        <div className="mt-2 flex items-center gap-1">
          {[
            { key: 'all' as const, label: `全部 (${rulebook.length})` },
            { key: 'open' as const, label: `待修复 (${counts.open})` },
            { key: 'fixed' as const, label: `已修复 (${counts.fixed})` },
          ].map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setStatusFilter(tab.key)}
              className={`rounded-md px-2 py-1 text-[11px] font-medium transition-colors ${
                statusFilter === tab.key
                  ? 'bg-[#234B7A] text-white'
                  : 'bg-[#FAF9F6] text-[#5A6577] hover:text-[#1A2332]'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Clustered Entries */}
      <div className="flex-1 space-y-2.5 overflow-y-auto p-3">
        {filtered.length === 0 ? (
          <div className="py-10 text-center text-xs text-[#8791A1]">
            {rulebook.length === 0 ? '全部规范已通过，无待修条目' : '没有匹配的规则书条目'}
          </div>
        ) : (
          filtered.map((entry, idx) => {
            const isActive = activeRuleCode === entry.rule_code;
            const isFixed = entry.status === 'fixed';
            const isIgnored = entry.status === 'ignored';
            const isFixing = fixingRuleCode === entry.rule_code;

            // Collect clickable paragraph anchors
            const paraAnchors = entry.representative_anchors.filter(
              (a) => a.paragraph_index !== null,
            );
            const fallbackIndices =
              paraAnchors.length > 0 ? [] : entry.affected_paragraphs.slice(0, 4);

            return (
              <div
                key={`${entry.rule_code}-${idx}`}
                onClick={() =>
                  onSelectRule(isActive ? null : entry.rule_code)
                }
                className={`cursor-pointer rounded-xl border p-3 text-xs transition-all ${
                  isActive
                    ? 'border-[#234B7A] bg-[#EEF3F9]/45 ring-1 ring-[#234B7A]/20'
                    : isFixed
                      ? 'border-[#BBF7D0] bg-[#ECFDF5]/35 hover:border-[#86EFAC]'
                      : 'border-[#E5E2DC] bg-white hover:border-[#C8C3B9]'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                        entry.scope === 'global'
                          ? 'bg-[#EEF3F9] text-[#234B7A]'
                          : entry.scope === 'cluster'
                            ? 'bg-[#F3E8FF] text-[#6B21A8]'
                            : 'bg-[#FAF9F6] text-[#5A6577]'
                      }`}
                    >
                      {SCOPE_LABELS[entry.scope] ?? entry.scope}
                    </span>
                    <span className="font-semibold text-[#1A2332]">{entry.rule_name}</span>
                  </div>

                  {isFixed ? (
                    <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-[#ECFDF5] px-2 py-0.5 text-[10px] font-semibold text-[#15803D]">
                      <CheckCircle2 className="h-3 w-3" />
                      已修复
                    </span>
                  ) : isIgnored ? (
                    <span className="shrink-0 rounded-full bg-[#F3F4F6] px-2 py-0.5 text-[10px] font-medium text-[#6B7280]">
                      已忽略
                    </span>
                  ) : (
                    <span
                      className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold tabular-nums ${
                        entry.severity === 'error'
                          ? 'bg-[#FEF2F2] text-[#B91C1C]'
                          : 'bg-[#FFFBEB] text-[#B45309]'
                      }`}
                    >
                      {entry.total_count} 处
                    </span>
                  )}
                </div>

                <div className="mt-1 flex items-center gap-2 text-[10px] text-[#8791A1]">
                  <span>{getCategoryLabel(entry.category)}</span>
                  <span>·</span>
                  <span className="font-mono">{entry.rule_code}</span>
                  {entry.original_count > entry.total_count && (
                    <>
                      <span>·</span>
                      <span className="tabular-nums text-[#15803D]">
                        原 {entry.original_count} → 剩 {entry.total_count}
                      </span>
                    </>
                  )}
                </div>

                <div className="mt-2 space-y-1 rounded-lg border border-[#EFECE6] bg-[#FAF9F6]/80 p-2 text-[11px]">
                  <div className="text-[#5A6577]">
                    <strong className="font-medium text-[#1A2332]">规范：</strong>
                    {entry.expected}
                  </div>
                  {!isFixed && (
                    <div className="text-[#991B1B]">
                      <strong className="font-medium">现状：</strong>
                      {entry.actual_summary}
                    </div>
                  )}
                  <div className="text-[#234B7A]">
                    <strong className="font-medium">建议：</strong>
                    {entry.bubble_note || entry.guidance}
                  </div>
                </div>

                {/* Clickable paragraph anchors */}
                {(paraAnchors.length > 0 || fallbackIndices.length > 0) && (
                  <div
                    className="mt-2 flex flex-wrap items-center gap-1"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <MapPin className="h-3 w-3 shrink-0 text-[#8791A1]" />
                    {paraAnchors.slice(0, 4).map((anchor, aIdx) => (
                      <button
                        key={`${anchor.paragraph_index}-${aIdx}`}
                        type="button"
                        onClick={() =>
                          onJumpToParagraph(anchor.paragraph_index!, entry.rule_code)
                        }
                        className="rounded border border-[#E5E2DC] bg-[#FAF9F6] px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-[#234B7A] hover:border-[#234B7A] hover:bg-[#EEF3F9]"
                      >
                        第 {anchor.paragraph_index! + 1} 段
                        {anchor.page != null ? ` · P.${anchor.page}` : ''}
                      </button>
                    ))}
                    {fallbackIndices.map((pIdx) => (
                      <button
                        key={pIdx}
                        type="button"
                        onClick={() => onJumpToParagraph(pIdx, entry.rule_code)}
                        className="rounded border border-[#E5E2DC] bg-[#FAF9F6] px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-[#234B7A] hover:border-[#234B7A] hover:bg-[#EEF3F9]"
                      >
                        第 {pIdx + 1} 段
                      </button>
                    ))}
                    {entry.affected_paragraphs.length > 4 && (
                      <span className="text-[10px] text-[#8791A1]">
                        等 {entry.affected_paragraphs.length} 段
                      </span>
                    )}
                  </div>
                )}

                {entry.affected_paragraphs.length === 0 &&
                  entry.affected_pages.length > 0 && (
                    <div className="mt-1.5 text-[10px] tabular-nums text-[#8791A1]">
                      涉及页码：{entry.affected_pages.slice(0, 8).map((p) => `P.${p}`).join('、')}
                      {entry.affected_pages.length > 8 ? ' 等' : ''}
                    </div>
                  )}

                {entry.status === 'open' && entry.can_auto_fix && (
                  <div
                    className="mt-2 flex justify-end"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <button
                      type="button"
                      disabled={Boolean(fixingRuleCode)}
                      onClick={() => void onFixSingleRule(entry.rule_code)}
                      className="inline-flex items-center gap-1 rounded-md border border-[#234B7A]/30 bg-[#EEF3F9] px-2 py-1 text-[11px] font-medium text-[#234B7A] hover:bg-[#234B7A] hover:text-white disabled:opacity-50"
                    >
                      {isFixing ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Sparkles className="h-3 w-3" />
                      )}
                      <span>{editable ? '修复此项' : '生成改写建议'}</span>
                    </button>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
}
