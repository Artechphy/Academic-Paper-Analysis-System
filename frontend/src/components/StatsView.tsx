import { ArrowUpRight, BarChart3, Loader2, RefreshCw } from 'lucide-react';
import type { BatchSummary, RuleSetResponse, StatsOverview } from '../types/api';
import {
  formatDateTime,
  formatDuration,
  formatPercent,
  formatScore,
  getCategoryLabel,
} from '../utils/format';

interface StatsViewProps {
  overview: StatsOverview | null;
  batches: BatchSummary[];
  ruleSets: RuleSetResponse[];
  loading: boolean;
  onRefresh: () => void;
  onOpenBatch: (batchId: string) => void;
}

export function StatsView({
  overview,
  batches,
  ruleSets,
  loading,
  onRefresh,
  onOpenBatch,
}: StatsViewProps) {
  const ruleSetMap = new Map(ruleSets.map((r) => [r.id, r.name]));
  const maxViolations = Math.max(
    1,
    ...(overview?.top_violations.map((v) => v.violation_count) ?? [1]),
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-[#1A2332]">数据库聚合统计洞察</h2>
          <p className="text-xs text-[#5A6577]">
            数据实时来自 PostgreSQL 分析视图 <code className="font-mono text-[11px]">v_rule_violation_stats</code> 与{' '}
            <code className="font-mono text-[11px]">v_batch_summary</code>
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#E5E2DC] bg-white px-3 text-xs font-medium text-[#1A2332] shadow-2xs hover:bg-[#FAF9F6] disabled:opacity-55"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>刷新统计</span>
        </button>
      </div>

      {/* Overview KPI strip */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {[
          { label: '累计检测篇次', val: overview?.total_count ?? 0, color: 'text-[#1A2332]' },
          { label: '累计合格 (PASS)', val: overview?.pass_count ?? 0, color: 'text-[#15803D]' },
          { label: '累计有问题 (FAIL)', val: overview?.fail_count ?? 0, color: 'text-[#B91C1C]' },
          { label: '累计异常 (ERROR)', val: overview?.error_count ?? 0, color: 'text-[#B45309]' },
          {
            label: '总体合格率',
            val: formatPercent(overview?.pass_rate),
            color: 'text-[#234B7A]',
          },
        ].map((card) => (
          <div
            key={card.label}
            className="rounded-xl border border-[#E5E2DC] bg-white p-4 shadow-[0_1px_2px_rgba(26,35,50,0.04)]"
          >
            <div className="text-xs text-[#5A6577]">{card.label}</div>
            <div className={`mt-1.5 text-2xl font-semibold tabular-nums ${card.color}`}>
              {card.val}
            </div>
          </div>
        ))}
      </div>

      {/* Top 10 Violations */}
      <section className="rounded-xl border border-[#E5E2DC] bg-white p-5 shadow-[0_1px_2px_rgba(26,35,50,0.04)]">
        <div className="mb-4 flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-[#234B7A]" />
          <h3 className="text-sm font-semibold text-[#1A2332]">高频格式违规规则 TOP 10</h3>
        </div>

        {loading && !overview ? (
          <div className="flex items-center justify-center py-10 text-xs text-[#5A6577]">
            <Loader2 className="mr-2 h-4 w-4 animate-spin text-[#234B7A]" />
            正在读取统计视图...
          </div>
        ) : !overview || overview.top_violations.length === 0 ? (
          <div className="py-10 text-center text-xs text-[#8791A1]">
            暂无违规统计数据，请先在工作台上传论文完成一次批量检测。
          </div>
        ) : (
          <div className="space-y-3">
            {overview.top_violations.map((item) => {
              const barPct = Math.max(4, Math.round((item.violation_count / maxViolations) * 100));
              return (
                <div key={item.rule_code} className="space-y-1">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-[#FAF9F6] text-[11px] font-semibold tabular-nums text-[#5A6577]">
                        {item.violation_rank}
                      </span>
                      <span className="font-medium text-[#1A2332]">{item.rule_name}</span>
                      <span className="rounded bg-[#FAF9F6] px-1.5 py-0.5 text-[10px] text-[#5A6577]">
                        {getCategoryLabel(item.category)}
                      </span>
                      <span className="hidden font-mono text-[10px] text-[#8791A1] sm:inline">
                        {item.rule_code}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 tabular-nums text-[11px] text-[#5A6577]">
                      <span>影响 {item.affected_paper_count} 篇</span>
                      <span>占比 {formatPercent(item.violation_ratio)}</span>
                      <strong className="text-xs text-[#1A2332]">{item.violation_count} 次</strong>
                    </div>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-[#FAF9F6]">
                    <div
                      className="h-full rounded-full bg-[#234B7A]/85 transition-all"
                      style={{ width: `${barPct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Historical Batches Summary */}
      <section className="overflow-hidden rounded-xl border border-[#E5E2DC] bg-white shadow-[0_1px_2px_rgba(26,35,50,0.04)]">
        <div className="border-b border-[#EFECE6] px-5 py-3.5">
          <h3 className="text-sm font-semibold text-[#1A2332]">历史检测批次汇总</h3>
        </div>
        {batches.length === 0 ? (
          <div className="px-5 py-8 text-center text-xs text-[#8791A1]">暂无历史检测批次</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-xs">
              <thead>
                <tr className="border-b border-[#E5E2DC] bg-[#FAF9F6] text-[11px] font-semibold text-[#5A6577]">
                  <th className="px-4 py-2.5">批次名称</th>
                  <th className="px-3 py-2.5">使用规则模板</th>
                  <th className="px-3 py-2.5">总数 / 合格 / 问题 / 异常</th>
                  <th className="px-3 py-2.5">通过率</th>
                  <th className="px-3 py-2.5">平均分</th>
                  <th className="px-3 py-2.5">均耗时</th>
                  <th className="px-3 py-2.5">检测时间</th>
                  <th className="px-4 py-2.5 text-right">跳转</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#EFECE6]">
                {batches.map((b) => (
                  <tr
                    key={b.id}
                    onClick={() => onOpenBatch(b.id)}
                    className="cursor-pointer hover:bg-[#FAF9F6]"
                  >
                    <td className="px-4 py-2.5 font-medium text-[#1A2332]">{b.name}</td>
                    <td className="px-3 py-2.5 text-[#5A6577]">
                      {ruleSetMap.get(b.rule_set_id) ?? b.rule_set_id}
                    </td>
                    <td className="px-3 py-2.5 tabular-nums">
                      <span className="font-medium text-[#1A2332]">{b.total_count}</span>
                      <span className="mx-1 text-[#D5D0C7]">/</span>
                      <span className="text-[#15803D]">{b.pass_count}</span>
                      <span className="mx-1 text-[#D5D0C7]">/</span>
                      <span className="text-[#B91C1C]">{b.fail_count}</span>
                      <span className="mx-1 text-[#D5D0C7]">/</span>
                      <span className="text-[#B45309]">{b.error_count}</span>
                    </td>
                    <td className="px-3 py-2.5 tabular-nums font-medium text-[#1A2332]">
                      {formatPercent(b.pass_rate)}
                    </td>
                    <td className="px-3 py-2.5 tabular-nums text-[#5A6577]">
                      {formatScore(b.avg_score)}
                    </td>
                    <td className="px-3 py-2.5 tabular-nums text-[#5A6577]">
                      {formatDuration(b.avg_duration_ms)}
                    </td>
                    <td className="px-3 py-2.5 tabular-nums text-[#8791A1]">
                      {formatDateTime(b.created_at)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <span className="inline-flex items-center gap-0.5 font-medium text-[#234B7A]">
                        查看 <ArrowUpRight className="h-3.5 w-3.5" />
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
