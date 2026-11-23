import { useState } from 'react';
import { Eye, FileWarning, Loader2, RefreshCw, Wand2 } from 'lucide-react';
import type { CheckRunSummary, RuleSetResponse } from '../types/api';
import { formatDuration, formatFileSize, formatScore } from '../utils/format';
import { VerdictBadge } from './VerdictBadge';

interface ResultsTableProps {
  results: CheckRunSummary[];
  ruleSets: RuleSetResponse[];
  loading: boolean;
  hasBatch: boolean;
  hasActiveFilters: boolean;
  recheckOverrides: Record<string, CheckRunSummary>;
  recheckingPaperId: string | null;
  openingRevisionRunId: string | null;
  onResetFilters: () => void;
  onInspectRun: (runId: string) => void;
  onQuickRecheck: (paperId: string, ruleSetId: string) => Promise<void>;
  onOpenRevision: (runId: string) => void;
}

export function ResultsTable({
  results,
  ruleSets,
  loading,
  hasBatch,
  hasActiveFilters,
  recheckOverrides,
  recheckingPaperId,
  openingRevisionRunId,
  onResetFilters,
  onInspectRun,
  onQuickRecheck,
  onOpenRevision,
}: ResultsTableProps) {
  const [recheckMenu, setRecheckMenu] = useState<{
    paperId: string;
    currentRuleSetId: string;
    top: number;
    right: number;
  } | null>(null);
  const ruleSetMap = new Map(ruleSets.map((r) => [r.id, r]));

  if (loading && results.length === 0) {
    return (
      <div className="rounded-xl border border-[#E5E2DC] bg-white p-8 text-center shadow-[0_1px_2px_rgba(26,35,50,0.04)]">
        <Loader2 className="mx-auto h-6 w-6 animate-spin text-[#234B7A]" />
        <p className="mt-2 text-xs text-[#5A6577]">正在加载检测结果...</p>
      </div>
    );
  }

  if (!hasBatch) {
    return (
      <div className="rounded-xl border border-[#E5E2DC] bg-white px-6 py-12 text-center shadow-[0_1px_2px_rgba(26,35,50,0.04)]">
        <FileWarning className="mx-auto h-8 w-8 text-[#8791A1]" />
        <h2 className="mt-3 text-sm font-semibold text-[#1A2332]">暂无检测批次记录</h2>
        <p className="mt-1 text-xs text-[#5A6577]">
          请在上方上传区拖入或选择 `.docx` / `.pdf` 论文文件，点击「开始批量检测」后即可查看每篇论文的合规结论与定位明细。
        </p>
      </div>
    );
  }

  if (results.length === 0) {
    return (
      <div className="rounded-xl border border-[#E5E2DC] bg-white px-6 py-10 text-center shadow-[0_1px_2px_rgba(26,35,50,0.04)]">
        <p className="text-sm font-medium text-[#1A2332]">当前筛选条件下没有匹配的论文</p>
        {hasActiveFilters && (
          <button
            type="button"
            onClick={onResetFilters}
            className="mt-3 inline-flex h-8 items-center rounded-lg border border-[#E5E2DC] bg-[#FAF9F6] px-3 text-xs font-medium text-[#1A2332] hover:bg-[#EFECE6]"
          >
            重置筛选条件
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-[#E5E2DC] bg-white shadow-[0_1px_2px_rgba(26,35,50,0.04)]">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-xs">
          <thead>
            <tr className="border-b border-[#E5E2DC] bg-[#FAF9F6] text-[11px] font-semibold tracking-wide text-[#5A6577]">
              <th className="px-4 py-3">论文文件与识别标题</th>
              <th className="px-3 py-3 whitespace-nowrap">格式 / 页数</th>
              <th className="px-3 py-3 whitespace-nowrap">判定结论</th>
              <th className="px-3 py-3 whitespace-nowrap">违规统计</th>
              <th className="px-3 py-3 whitespace-nowrap">合规分</th>
              <th className="px-3 py-3 whitespace-nowrap">耗时</th>
              <th className="px-4 py-3 text-right whitespace-nowrap">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#EFECE6]">
            {results.map((baseRow) => {
              const override = recheckOverrides[baseRow.paper_id];
              const row = override ?? baseRow;
              const isRechecked = Boolean(override);
              const activeRuleSet = ruleSetMap.get(row.rule_set_id);
              const isRechecking = recheckingPaperId === row.paper_id;

              return (
                <tr
                  key={baseRow.id}
                  onClick={() => onInspectRun(row.id)}
                  className="cursor-pointer transition-colors hover:bg-[#FAF9F6]/80"
                >
                  <td className="max-w-[360px] px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-medium text-[#1A2332]" title={row.file_name}>
                        {row.file_name}
                      </span>
                      {isRechecked && (
                        <span
                          title={activeRuleSet ? `已按「${activeRuleSet.name}」重检` : '已免重解析重检'}
                          className="shrink-0 rounded bg-[#EEF3F9] px-1.5 py-0.5 text-[10px] font-medium text-[#234B7A]"
                        >
                          已重检
                        </span>
                      )}
                    </div>
                    {row.parse_status === 'failed' ? (
                      <p className="mt-0.5 truncate text-[11px] text-[#B45309]" title={row.parse_error ?? ''}>
                        {row.parse_error || '文件解析失败'}
                      </p>
                    ) : row.detected_title ? (
                      <p className="mt-0.5 truncate text-[11px] text-[#5A6577]" title={row.detected_title}>
                        {row.detected_title}
                      </p>
                    ) : (
                      <p className="mt-0.5 text-[11px] text-[#8791A1]">
                        {activeRuleSet ? activeRuleSet.name : '未提取到主标题'}
                      </p>
                    )}
                  </td>

                  <td className="px-3 py-3 whitespace-nowrap">
                    <div className="flex items-center gap-1.5">
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                          row.file_ext === 'docx'
                            ? 'bg-[#EEF3F9] text-[#234B7A]'
                            : 'bg-[#FDF2EE] text-[#9A3412]'
                        }`}
                      >
                        {row.file_ext}
                      </span>
                      <span className="tabular-nums text-[#5A6577]">
                        {row.page_count != null ? `${row.page_count} 页` : '—'}
                      </span>
                    </div>
                    <div className="mt-0.5 tabular-nums text-[11px] text-[#8791A1]">
                      {formatFileSize(row.file_size)}
                    </div>
                  </td>

                  <td className="px-3 py-3 whitespace-nowrap">
                    <VerdictBadge verdict={row.verdict} compact />
                  </td>

                  <td className="px-3 py-3 whitespace-nowrap tabular-nums">
                    {row.parse_status === 'failed' ? (
                      <span className="text-[#8791A1]">—</span>
                    ) : (
                      <div className="flex items-center gap-2">
                        <span
                          className={`font-medium ${
                            row.error_count > 0 ? 'text-[#B91C1C]' : 'text-[#5A6577]'
                          }`}
                        >
                          {row.error_count} 错误
                        </span>
                        <span className="text-[#D5D0C7]">/</span>
                        <span
                          className={
                            row.warning_count > 0 ? 'font-medium text-[#B45309]' : 'text-[#8791A1]'
                          }
                        >
                          {row.warning_count} 警告
                        </span>
                      </div>
                    )}
                  </td>

                  <td className="px-3 py-3 whitespace-nowrap tabular-nums">
                    <div className="flex items-center gap-2">
                      <span className="w-10 font-semibold text-[#1A2332]">
                        {formatScore(row.score)}
                      </span>
                      <div className="hidden h-1.5 w-14 overflow-hidden rounded-full bg-[#EFECE6] sm:block">
                        <div
                          className={`h-full rounded-full ${
                            row.verdict === 'pass'
                              ? 'bg-[#15803D]'
                              : row.verdict === 'fail'
                                ? 'bg-[#B91C1C]'
                                : 'bg-[#B45309]'
                          }`}
                          style={{ width: `${Math.max(0, Math.min(100, row.score))}%` }}
                        />
                      </div>
                    </div>
                  </td>

                  <td className="px-3 py-3 whitespace-nowrap tabular-nums text-[#5A6577]">
                    {formatDuration(row.duration_ms)}
                  </td>

                  <td
                    className="relative px-4 py-3 text-right whitespace-nowrap"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div className="inline-flex items-center justify-end gap-1.5">
                      {row.parse_status === 'success' && (
                        <button
                          type="button"
                          disabled={openingRevisionRunId === row.id}
                          onClick={() => onOpenRevision(row.id)}
                          className="inline-flex h-7 items-center gap-1 rounded-md bg-[#234B7A] px-2.5 text-xs font-medium text-white hover:bg-[#1B3B61] disabled:opacity-55"
                        >
                          {openingRevisionRunId === row.id ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Wand2 className="h-3.5 w-3.5" />
                          )}
                          <span>调整论文</span>
                        </button>
                      )}

                      <button
                        type="button"
                        onClick={() => onInspectRun(row.id)}
                        className="inline-flex h-7 items-center gap-1 rounded-md border border-[#E5E2DC] bg-white px-2.5 text-xs font-medium text-[#1A2332] hover:border-[#234B7A]/40 hover:bg-[#FAF9F6]"
                      >
                        <Eye className="h-3.5 w-3.5 text-[#234B7A]" />
                        <span>详情</span>
                      </button>

                      <button
                        type="button"
                        disabled={isRechecking || ruleSets.length === 0}
                        onClick={(e) => {
                          const rect = e.currentTarget.getBoundingClientRect();
                          setRecheckMenu((prev) =>
                            prev?.paperId === row.paper_id
                              ? null
                              : {
                                  paperId: row.paper_id,
                                  currentRuleSetId: row.rule_set_id,
                                  top: rect.bottom + 6,
                                  right: window.innerWidth - rect.right,
                                },
                          );
                        }}
                        className="inline-flex h-7 items-center gap-1 rounded-md border border-[#E5E2DC] bg-[#FAF9F6] px-2.5 text-xs font-medium text-[#5A6577] hover:border-[#C8C3B9] hover:text-[#1A2332] disabled:opacity-50"
                      >
                        {isRechecking ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin text-[#234B7A]" />
                        ) : (
                          <RefreshCw className="h-3.5 w-3.5" />
                        )}
                        <span>重检</span>
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {recheckMenu && (
        <>
          <div
            className="fixed inset-0 z-30"
            onClick={() => setRecheckMenu(null)}
            aria-hidden="true"
          />
          <div
            style={{ top: recheckMenu.top, right: recheckMenu.right }}
            className="fixed z-40 w-64 rounded-lg border border-[#E5E2DC] bg-white p-1.5 text-left shadow-lg"
          >
            <div className="px-2 py-1 text-[11px] font-medium text-[#8791A1]">
              选择模板免重解析重检
            </div>
            {ruleSets.map((rs) => (
              <button
                key={rs.id}
                type="button"
                onClick={async () => {
                  const targetPaperId = recheckMenu.paperId;
                  setRecheckMenu(null);
                  await onQuickRecheck(targetPaperId, rs.id);
                }}
                className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-xs text-[#1A2332] hover:bg-[#EEF3F9]"
              >
                <span className="truncate">{rs.name}</span>
                {rs.id === recheckMenu.currentRuleSetId && (
                  <span className="ml-2 shrink-0 text-[10px] text-[#234B7A]">当前</span>
                )}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
