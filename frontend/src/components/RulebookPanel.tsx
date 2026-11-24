import { useMemo, useState } from 'react';
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  History,
  Loader2,
  MapPin,
  Search,
  Send,
  ShieldAlert,
  Sparkles,
  X,
} from 'lucide-react';
import type {
  ParagraphDiff,
  RevisionFeedbackItem,
  RulebookEntry,
  RuleStatus,
} from '../types/revisions';
import { getCategoryLabel, SCOPE_LABELS } from '../utils/format';

interface RulebookPanelProps {
  rulebook: RulebookEntry[];
  changes: ParagraphDiff[];
  editable: boolean;
  activeRuleCode: string | null;
  fixingRuleCode: string | null;
  instruction: string;
  runningAutoFix: boolean;
  latestAgentFeedback?: RevisionFeedbackItem;
  onInstructionChange: (value: string) => void;
  onSubmitInstruction: (instruction: string) => void;
  onJumpToParagraph: (paragraphIndex: number, ruleCode: string) => void;
  onJumpToChange: (paragraphIndex: number) => void;
  onSelectRule: (ruleCode: string | null) => void;
  onFixSingleRule: (ruleCode: string) => Promise<void>;
}

type DockTab = 'review' | 'changes';

export function RulebookPanel({
  rulebook,
  changes,
  editable,
  activeRuleCode,
  fixingRuleCode,
  instruction,
  runningAutoFix,
  latestAgentFeedback,
  onInstructionChange,
  onSubmitInstruction,
  onJumpToParagraph,
  onJumpToChange,
  onSelectRule,
  onFixSingleRule,
}: RulebookPanelProps) {
  const [dockTab, setDockTab] = useState<DockTab>('review');
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

  const progressPct =
    rulebook.length > 0 ? Math.round((counts.fixed / rulebook.length) * 100) : 100;

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
      aria-label="规范审查与 AI 修订助手"
      className="flex h-full min-h-0 flex-col bg-white"
    >
      {/* Top Tab Header */}
      <div className="shrink-0 border-b border-[#ECEAE5] px-3 pt-2.5 pb-2">
        <div className="grid grid-cols-2 rounded-lg border border-[#E8E6E1] bg-[#F7F7F5] p-0.5 text-xs">
          <button
            type="button"
            onClick={() => setDockTab('review')}
            className={`inline-flex items-center justify-center gap-1.5 rounded-md py-1.5 font-medium transition-colors ${
              dockTab === 'review'
                ? 'bg-white text-[#18181B] shadow-2xs'
                : 'text-[#52525B] hover:text-[#18181B]'
            }`}
          >
            <ShieldAlert className="h-3.5 w-3.5 text-[#1E3A5F]" />
            <span>规范审查</span>
            <span className="rounded-full bg-[#FEF2F2] px-1.5 py-0.2 text-[10px] font-semibold tabular-nums text-[#B91C1C]">
              {counts.open}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setDockTab('changes')}
            className={`inline-flex items-center justify-center gap-1.5 rounded-md py-1.5 font-medium transition-colors ${
              dockTab === 'changes'
                ? 'bg-white text-[#18181B] shadow-2xs'
                : 'text-[#52525B] hover:text-[#18181B]'
            }`}
          >
            <History className="h-3.5 w-3.5 text-[#52525B]" />
            <span>修改记录</span>
            <span className="rounded-full bg-[#F3F2EE] px-1.5 py-0.2 text-[10px] font-semibold tabular-nums text-[#52525B]">
              {changes.length}
            </span>
          </button>
        </div>

        {dockTab === 'review' && (
          <div className="mt-2.5 space-y-2">
            {/* Slim resolution progress bar */}
            <div className="flex items-center justify-between text-[11px] tabular-nums text-[#71717A]">
              <span>
                已解 <strong className="text-[#15803D]">{counts.fixed}</strong> / {rulebook.length} 项
              </span>
              <span>{progressPct}%</span>
            </div>
            <div className="h-1 w-full overflow-hidden rounded-full bg-[#F3F2EE]">
              <div
                className="h-full rounded-full bg-[#16A34A] transition-all"
                style={{ width: `${progressPct}%` }}
              />
            </div>

            {/* Search */}
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-[#71717A]" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜索规则名、要求或建议..."
                className="h-8 w-full rounded-lg border border-[#E8E6E1] bg-[#FAF9F7] pr-7 pl-8 text-xs text-[#18181B] placeholder:text-[#71717A] focus:border-[#1E3A5F] focus:bg-white focus:outline-none"
              />
              {query && (
                <button
                  type="button"
                  onClick={() => setQuery('')}
                  aria-label="清空规则检索"
                  className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-0.5 text-[#71717A] hover:text-[#18181B]"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>

            {/* Filter pills */}
            <div className="flex items-center gap-1">
              {[
                { key: 'all' as const, label: `全部 (${rulebook.length})` },
                { key: 'open' as const, label: `待修 (${counts.open})` },
                { key: 'fixed' as const, label: `已解 (${counts.fixed})` },
              ].map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setStatusFilter(tab.key)}
                  className={`rounded-md px-2 py-1 text-[11px] font-medium transition-colors ${
                    statusFilter === tab.key
                      ? 'bg-[#1E3A5F] text-white'
                      : 'bg-[#F3F2EE] text-[#52525B] hover:text-[#18181B]'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Scrollable Body */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {dockTab === 'review' ? (
          filtered.length === 0 ? (
            <div className="px-4 py-12 text-center text-xs text-[#71717A]">
              {rulebook.length === 0 ? '全部规范已通过，无待修条目' : '没有匹配的规则书条目'}
            </div>
          ) : (
            <div className="divide-y divide-[#ECEAE5]">
              {filtered.map((entry, idx) => {
                const isActive = activeRuleCode === entry.rule_code;
                const isFixed = entry.status === 'fixed';
                const isIgnored = entry.status === 'ignored';
                const isFixing = fixingRuleCode === entry.rule_code;

                const paraAnchors = entry.representative_anchors.filter(
                  (a) => a.paragraph_index !== null,
                );
                const fallbackIndices =
                  paraAnchors.length > 0 ? [] : entry.affected_paragraphs.slice(0, 4);

                return (
                  <div
                    key={`${entry.rule_code}-${idx}`}
                    className={`transition-colors ${
                      isActive
                        ? 'bg-[#EFF4FA]/65'
                        : isFixed
                          ? 'bg-[#ECFDF5]/25 hover:bg-[#ECFDF5]/45'
                          : 'hover:bg-[#FAF9F7]'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => onSelectRule(isActive ? null : entry.rule_code)}
                      className="flex w-full items-start justify-between gap-2 px-3.5 py-3 text-left"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          {isActive ? (
                            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-[#1E3A5F]" />
                          ) : (
                            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[#71717A]" />
                          )}
                          <span className="truncate text-xs font-semibold text-[#18181B]">
                            {entry.rule_name}
                          </span>
                        </div>
                        <p className="mt-1 truncate pl-5 text-[11px] text-[#71717A]">
                          {isFixed ? entry.expected : entry.actual_summary || entry.expected}
                        </p>
                      </div>

                      <div className="shrink-0 pl-1">
                        {isFixed ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-[#ECFDF5] px-2 py-0.5 text-[10px] font-semibold text-[#15803D]">
                            <CheckCircle2 className="h-3 w-3" />
                            已解
                          </span>
                        ) : isIgnored ? (
                          <span className="rounded-full bg-[#F3F2EE] px-2 py-0.5 text-[10px] font-medium text-[#71717A]">
                            忽略
                          </span>
                        ) : (
                          <span
                            className={`rounded-full px-2 py-0.5 text-[10px] font-semibold tabular-nums ${
                              entry.severity === 'error'
                                ? 'bg-[#FEF2F2] text-[#B91C1C]'
                                : 'bg-[#FFFBEB] text-[#B45309]'
                            }`}
                          >
                            {entry.total_count} 处
                          </span>
                        )}
                      </div>
                    </button>

                    {/* Expanded Detail Section */}
                    {isActive && (
                      <div className="space-y-2.5 px-3.5 pb-3.5 pl-8 text-[11px]">
                        <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-[#71717A]">
                          <span className="rounded bg-[#F3F2EE] px-1.5 py-0.5 text-[#52525B]">
                            {SCOPE_LABELS[entry.scope] ?? entry.scope}
                          </span>
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

                        <div className="space-y-1.5 text-[#52525B]">
                          <div>
                            <strong className="font-medium text-[#18181B]">规范：</strong>
                            {entry.expected}
                          </div>
                          {!isFixed && (
                            <div className="text-[#991B1B]">
                              <strong className="font-medium">现状：</strong>
                              {entry.actual_summary}
                            </div>
                          )}
                          <div className="text-[#1E3A5F]">
                            <strong className="font-medium">建议：</strong>
                            {entry.bubble_note || entry.guidance}
                          </div>
                        </div>

                        {(paraAnchors.length > 0 || fallbackIndices.length > 0) && (
                          <div className="flex flex-wrap items-center gap-1">
                            <MapPin className="h-3 w-3 shrink-0 text-[#71717A]" />
                            {paraAnchors.slice(0, 4).map((anchor, aIdx) => (
                              <button
                                key={`${anchor.paragraph_index}-${aIdx}`}
                                type="button"
                                onClick={() =>
                                  onJumpToParagraph(anchor.paragraph_index!, entry.rule_code)
                                }
                                className="rounded border border-[#E2E0DA] bg-white px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-[#1E3A5F] hover:border-[#1E3A5F] hover:bg-[#EFF4FA]"
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
                                className="rounded border border-[#E2E0DA] bg-white px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-[#1E3A5F] hover:border-[#1E3A5F] hover:bg-[#EFF4FA]"
                              >
                                第 {pIdx + 1} 段
                              </button>
                            ))}
                            {entry.affected_paragraphs.length > 4 && (
                              <span className="text-[10px] text-[#71717A]">
                                等 {entry.affected_paragraphs.length} 段
                              </span>
                            )}
                          </div>
                        )}

                        {entry.affected_paragraphs.length === 0 &&
                          entry.affected_pages.length > 0 && (
                            <div className="text-[10px] tabular-nums text-[#71717A]">
                              涉及页码：{entry.affected_pages.slice(0, 8).map((p) => `P.${p}`).join('、')}
                              {entry.affected_pages.length > 8 ? ' 等' : ''}
                            </div>
                          )}

                        {entry.status === 'open' && entry.can_auto_fix && (
                          <div className="pt-0.5">
                            <button
                              type="button"
                              disabled={Boolean(fixingRuleCode) || runningAutoFix}
                              onClick={() => void onFixSingleRule(entry.rule_code)}
                              className="inline-flex h-7 items-center gap-1 rounded-md border border-[#D7E2EE] bg-[#EFF4FA] px-2.5 text-[11px] font-medium text-[#1E3A5F] transition-colors hover:bg-[#1E3A5F] hover:text-white disabled:opacity-50"
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
                    )}
                  </div>
                );
              })}
            </div>
          )
        ) : changes.length === 0 ? (
          <div className="px-4 py-12 text-center text-xs text-[#71717A]">
            尚无段落修改记录。点击某段正文即可手工编校，或使用顶部「一键修复」。
          </div>
        ) : (
          <div className="divide-y divide-[#ECEAE5]">
            {changes.map((diff) => (
              <button
                key={diff.paragraph_index}
                type="button"
                onClick={() => onJumpToChange(diff.paragraph_index)}
                className="flex w-full flex-col gap-1.5 px-3.5 py-3 text-left transition-colors hover:bg-[#FAF9F7]"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex min-w-0 flex-1 items-start gap-1.5">
                    <span className="shrink-0 whitespace-nowrap rounded bg-[#EFF4FA] px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-[#1E3A5F]">
                      第 {diff.paragraph_index + 1} 段
                    </span>
                    <span className="line-clamp-2 text-xs font-medium text-[#18181B]">
                      {diff.summary || '格式/文本已调整'}
                    </span>
                  </div>
                  <span className="shrink-0 whitespace-nowrap rounded bg-[#ECFDF5] px-1.5 py-0.5 text-[10px] font-medium text-[#15803D]">
                    {diff.source === 'llm'
                      ? 'LLM'
                      : diff.source === 'rule'
                        ? '规则'
                        : '手动'}
                  </span>
                </div>

                {diff.style_changes.length > 0 && (
                  <div className="text-[11px] text-[#15803D]">
                    {diff.style_changes.join('；')}
                  </div>
                )}

                {diff.before_text !== diff.after_text && (
                  <div className="line-clamp-2 text-[11px] text-[#71717A]">
                    “{diff.before_text.slice(0, 32)}” → “{diff.after_text.slice(0, 32)}”
                  </div>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Bottom Docked AI Revision Assistant */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const trimmed = instruction.trim();
          if (!trimmed || runningAutoFix) return;
          onSubmitInstruction(trimmed);
        }}
        className="shrink-0 border-t border-[#E8E6E1] bg-[#FAF9F7] p-3"
      >
        <div className="mb-1.5 flex items-center justify-between gap-2">
          <span className="shrink-0 text-[11px] font-semibold text-[#18181B]">AI 修订指令</span>
          {latestAgentFeedback?.summary && (
            <span
              className="min-w-0 truncate text-[10px] text-[#71717A]"
              title={latestAgentFeedback.summary}
            >
              最新：{latestAgentFeedback.summary}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <input
            type="text"
            value={instruction}
            onChange={(e) => onInstructionChange(e.target.value)}
            disabled={runningAutoFix}
            placeholder="例如：关键词保留“高中生”并精简到 15 字内..."
            className="h-8 min-w-0 flex-1 rounded-lg border border-[#E8E6E1] bg-white px-2.5 text-xs text-[#18181B] placeholder:text-[#71717A] focus:border-[#1E3A5F] focus:outline-none disabled:opacity-55"
          />
          <button
            type="submit"
            disabled={!instruction.trim() || runningAutoFix}
            aria-label="发送修订指令"
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-[#1E3A5F] bg-white text-[#1E3A5F] transition-colors hover:bg-[#1E3A5F] hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            {runningAutoFix ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Send className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
      </form>
    </aside>
  );
}
