import { Search, X } from 'lucide-react';
import type { BatchDetail, Verdict } from '../types/api';
import { formatDuration, formatPercent, formatScore } from '../utils/format';

interface BatchOverviewBarProps {
  batchDetail: BatchDetail | null;
  verdictFilter: Verdict | null;
  onVerdictFilterChange: (verdict: Verdict | null) => void;
  searchQuery: string;
  onSearchQueryChange: (q: string) => void;
}

export function BatchOverviewBar({
  batchDetail,
  verdictFilter,
  onVerdictFilterChange,
  searchQuery,
  onSearchQueryChange,
}: BatchOverviewBarProps) {
  const total = batchDetail?.total_count ?? 0;
  const passCount = batchDetail?.pass_count ?? 0;
  const failCount = batchDetail?.fail_count ?? 0;
  const errorCount = batchDetail?.error_count ?? 0;

  const segments: Array<{
    key: Verdict | 'all';
    label: string;
    value: number;
    dotClass: string;
    activeTextClass: string;
    activeBarClass: string;
  }> = [
    {
      key: 'all',
      label: '全部论文',
      value: total,
      dotClass: 'bg-[#1E3A5F]',
      activeTextClass: 'text-[#1E3A5F]',
      activeBarClass: 'bg-[#1E3A5F]',
    },
    {
      key: 'pass',
      label: '格式合格',
      value: passCount,
      dotClass: 'bg-[#16A34A]',
      activeTextClass: 'text-[#15803D]',
      activeBarClass: 'bg-[#16A34A]',
    },
    {
      key: 'fail',
      label: '格式有问题',
      value: failCount,
      dotClass: 'bg-[#DC2626]',
      activeTextClass: 'text-[#B91C1C]',
      activeBarClass: 'bg-[#DC2626]',
    },
    {
      key: 'error',
      label: '解析异常',
      value: errorCount,
      dotClass: 'bg-[#D97706]',
      activeTextClass: 'text-[#B45309]',
      activeBarClass: 'bg-[#D97706]',
    },
  ];

  return (
    <section aria-label="批次结果总览与筛选" className="space-y-2.5">
      {/* Unified Hairline Metric Filter Strip */}
      <div className="grid grid-cols-2 divide-y divide-[#ECEAE5] overflow-hidden rounded-xl border border-[#E8E6E1] bg-white sm:grid-cols-4 sm:divide-x sm:divide-y-0">
        {segments.map((seg) => {
          const isSelected =
            (seg.key === 'all' && verdictFilter === null) ||
            (seg.key !== 'all' && verdictFilter === seg.key);
          const nextFilter: Verdict | null =
            seg.key === 'all' ? null : verdictFilter === seg.key ? null : seg.key;

          return (
            <button
              key={seg.key}
              type="button"
              onClick={() => onVerdictFilterChange(nextFilter)}
              className={`relative flex items-center justify-between px-4 py-3 text-left transition-colors ${
                isSelected ? 'bg-[#FAF9F7]' : 'bg-white hover:bg-[#FAF9F7]/60'
              }`}
            >
              <div>
                <div className="flex items-center gap-1.5 text-xs font-medium text-[#52525B]">
                  <span className={`h-1.5 w-1.5 rounded-full ${seg.dotClass}`} />
                  <span>{seg.label}</span>
                </div>
                <div
                  className={`mt-1 text-xl font-semibold tracking-tight tabular-nums ${
                    isSelected ? seg.activeTextClass : 'text-[#18181B]'
                  }`}
                >
                  {seg.value}
                </div>
              </div>

              {isSelected && (
                <span
                  aria-hidden="true"
                  className={`absolute right-0 bottom-0 left-0 h-0.5 ${seg.activeBarClass}`}
                />
              )}
            </button>
          );
        })}
      </div>

      {/* Slim Utility Row: Batch Meta + Search */}
      <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs tabular-nums text-[#71717A]">
          <span>
            通过率{' '}
            <strong className="font-medium text-[#18181B]">
              {formatPercent(batchDetail?.pass_rate)}
            </strong>
          </span>
          <span>
            批次均分{' '}
            <strong className="font-medium text-[#18181B]">
              {formatScore(batchDetail?.avg_score)}
            </strong>
          </span>
          <span>
            平均耗时{' '}
            <strong className="font-medium text-[#18181B]">
              {formatDuration(batchDetail?.avg_duration_ms)}
            </strong>
          </span>
        </div>

        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-[#71717A]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchQueryChange(e.target.value)}
            placeholder="按文件名搜索..."
            className="h-8 w-full rounded-lg border border-[#E8E6E1] bg-white pr-7 pl-8 text-xs text-[#18181B] placeholder:text-[#71717A] focus:border-[#1E3A5F] focus:outline-none"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => onSearchQueryChange('')}
              aria-label="清空搜索"
              className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-0.5 text-[#71717A] hover:text-[#18181B]"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
