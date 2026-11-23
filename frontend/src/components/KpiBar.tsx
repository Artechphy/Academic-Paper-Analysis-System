import { Search, X } from 'lucide-react';
import type { BatchDetail, BatchSummary, Verdict } from '../types/api';
import { formatDateTime, formatDuration, formatPercent, formatScore } from '../utils/format';

interface KpiBarProps {
  batches: BatchSummary[];
  selectedBatchId: string;
  onSelectBatch: (batchId: string) => void;
  batchDetail: BatchDetail | null;
  verdictFilter: Verdict | null;
  onVerdictFilterChange: (verdict: Verdict | null) => void;
  searchQuery: string;
  onSearchQueryChange: (q: string) => void;
}

export function KpiBar({
  batches,
  selectedBatchId,
  onSelectBatch,
  batchDetail,
  verdictFilter,
  onVerdictFilterChange,
  searchQuery,
  onSearchQueryChange,
}: KpiBarProps) {
  const total = batchDetail?.total_count ?? 0;
  const passCount = batchDetail?.pass_count ?? 0;
  const failCount = batchDetail?.fail_count ?? 0;
  const errorCount = batchDetail?.error_count ?? 0;

  const cards: Array<{
    key: Verdict | 'all';
    title: string;
    value: number;
    hint: string;
    ringClass: string;
    valueClass: string;
    activeClass: string;
  }> = [
    {
      key: 'all',
      title: '本批总论文数',
      value: total,
      hint: batchDetail ? `通过率 ${formatPercent(batchDetail.pass_rate)}` : '暂无检测批次',
      ringClass: 'border-[#E5E2DC] hover:border-[#C8C3B9]',
      valueClass: 'text-[#1A2332]',
      activeClass: 'ring-2 ring-[#234B7A]/20 border-[#234B7A]',
    },
    {
      key: 'pass',
      title: '格式没问题 (PASS)',
      value: passCount,
      hint: batchDetail?.avg_score != null ? `批次均分 ${formatScore(batchDetail.avg_score)}` : '0 个 error 违规',
      ringClass: 'border-[#E5E2DC] hover:border-[#86EFAC]',
      valueClass: 'text-[#15803D]',
      activeClass: 'ring-2 ring-[#15803D]/20 border-[#15803D] bg-[#ECFDF5]/40',
    },
    {
      key: 'fail',
      title: '格式有问题 (FAIL)',
      value: failCount,
      hint: '存在至少 1 条 error 违规',
      ringClass: 'border-[#E5E2DC] hover:border-[#FCA5A5]',
      valueClass: 'text-[#B91C1C]',
      activeClass: 'ring-2 ring-[#B91C1C]/20 border-[#B91C1C] bg-[#FEF2F2]/40',
    },
    {
      key: 'error',
      title: '解析异常 (ERROR)',
      value: errorCount,
      hint: batchDetail?.avg_duration_ms != null ? `均耗时 ${formatDuration(batchDetail.avg_duration_ms)}` : '文件损坏或无法解析',
      ringClass: 'border-[#E5E2DC] hover:border-[#FCD34D]',
      valueClass: 'text-[#B45309]',
      activeClass: 'ring-2 ring-[#B45309]/20 border-[#B45309] bg-[#FFFBEB]/40',
    },
  ];

  const filterTabs: Array<{ label: string; value: Verdict | null }> = [
    { label: '全部', value: null },
    { label: '有问题', value: 'fail' },
    { label: '合格', value: 'pass' },
    { label: '异常', value: 'error' },
  ];

  return (
    <section aria-label="检测结果总览与筛选" className="space-y-3">
      {/* 4 KPI Cards */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {cards.map((card) => {
          const isSelected =
            (card.key === 'all' && verdictFilter === null) ||
            (card.key !== 'all' && verdictFilter === card.key);
          const nextFilter: Verdict | null =
            card.key === 'all' ? null : verdictFilter === card.key ? null : card.key;

          return (
            <button
              key={card.key}
              type="button"
              onClick={() => onVerdictFilterChange(nextFilter)}
              className={`rounded-xl border bg-white p-4 text-left shadow-[0_1px_2px_rgba(26,35,50,0.04)] transition-all ${
                isSelected ? card.activeClass : card.ringClass
              }`}
            >
              <div className="text-xs font-medium text-[#5A6577]">{card.title}</div>
              <div className={`mt-1.5 text-2xl font-semibold tracking-tight tabular-nums ${card.valueClass}`}>
                {card.value}
              </div>
              <div className="mt-1 text-[11px] text-[#8791A1]">{card.hint}</div>
            </button>
          );
        })}
      </div>

      {/* Toolbar: Batch selector + Verdict pills + Search */}
      <div className="flex flex-col justify-between gap-2.5 rounded-xl border border-[#E5E2DC] bg-white px-4 py-3 shadow-[0_1px_2px_rgba(26,35,50,0.04)] md:flex-row md:items-center">
        <div className="flex flex-wrap items-center gap-2.5">
          <div className="flex items-center gap-2">
            <label htmlFor="batch-select" className="text-xs font-medium text-[#5A6577]">
              历史批次
            </label>
            <select
              id="batch-select"
              value={selectedBatchId}
              onChange={(e) => onSelectBatch(e.target.value)}
              disabled={batches.length === 0}
              className="h-8 max-w-[280px] rounded-lg border border-[#E5E2DC] bg-[#FAF9F6] px-2.5 text-xs font-medium text-[#1A2332] focus:border-[#234B7A] focus:outline-none disabled:opacity-50"
            >
              {batches.length === 0 ? (
                <option value="">暂无检测批次</option>
              ) : (
                batches.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name} · {b.total_count} 篇 ({formatDateTime(b.created_at)})
                  </option>
                ))
              )}
            </select>
          </div>

          <div
            role="group"
            aria-label="结论筛选"
            className="inline-flex rounded-lg border border-[#E5E2DC] bg-[#FAF9F6] p-0.5"
          >
            {filterTabs.map((tab) => {
              const active = verdictFilter === tab.value;
              return (
                <button
                  key={tab.label}
                  type="button"
                  onClick={() => onVerdictFilterChange(tab.value)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    active
                      ? 'bg-white text-[#1A2332] shadow-2xs'
                      : 'text-[#5A6577] hover:text-[#1A2332]'
                  }`}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="relative w-full md:w-64">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-[#8791A1]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchQueryChange(e.target.value)}
            placeholder="按文件名搜索..."
            className="h-8 w-full rounded-lg border border-[#E5E2DC] bg-[#FAF9F6] pr-7 pl-8 text-xs text-[#1A2332] placeholder:text-[#8791A1] focus:border-[#234B7A] focus:bg-white focus:outline-none"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => onSearchQueryChange('')}
              aria-label="清空搜索"
              className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-0.5 text-[#8791A1] hover:text-[#1A2332]"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
