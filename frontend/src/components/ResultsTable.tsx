import { useEffect, useState } from 'react';
import {
  Check,
  Eye,
  FileWarning,
  Loader2,
  MoreHorizontal,
  RefreshCw,
  Wand2,
} from 'lucide-react';
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
  const [overflowMenu, setOverflowMenu] = useState<{
    runId: string;
    paperId: string;
    currentRuleSetId: string;
    top: number;
    right: number;
  } | null>(null);
  const ruleSetMap = new Map(ruleSets.map((r) => [r.id, r]));

  useEffect(() => {
    if (!overflowMenu) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOverflowMenu(null);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [overflowMenu]);

  if (loading && results.length === 0) {
    return (
      <div className="rounded-xl border border-[#E8E6E1] bg-white p-10 text-center">
        <Loader2 className="mx-auto h-5 w-5 animate-spin text-[#1E3A5F]" />
        <p className="mt-2 text-xs text-[#71717A]">正在加载检测结果...</p>
      </div>
    );
  }

  if (!hasBatch) {
    return (
      <div className="rounded-xl border border-[#E8E6E1] bg-white px-6 py-12 text-center">
        <FileWarning className="mx-auto h-7 w-7 text-[#71717A]" />
        <h2 className="mt-3 text-sm font-semibold text-[#18181B]">请选择或新建检测批次</h2>
        <p className="mt-1 text-xs text-[#71717A]">
          点击右上角「新建检测」上传论文，或在左侧边栏选择历史批次。
        </p>
      </div>
    );
  }

  if (results.length === 0) {
    return (
      <div className="rounded-xl border border-[#E8E6E1] bg-white px-6 py-10 text-center">
        <p className="text-sm font-medium text-[#18181B]">当前筛选条件下没有匹配的论文</p>
        {hasActiveFilters && (
          <button
            type="button"
            onClick={onResetFilters}
            className="mt-3 inline-flex h-8 items-center rounded-lg border border-[#E2E0DA] bg-white px-3 text-xs font-medium text-[#18181B] hover:bg-[#F7F7F5]"
          >
            重置筛选条件
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-[#E8E6E1] bg-white">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-xs">
          <thead>
            <tr className="border-b border-[#ECEAE5] bg-[#FAF9F7] text-[11px] font-medium text-[#71717A]">
              <th className="px-4 py-2.5">论文文件与识别标题</th>
              <th className="px-3 py-2.5 whitespace-nowrap">格式 / 页数</th>
              <th className="px-3 py-2.5 whitespace-nowrap">判定结论</th>
              <th className="px-3 py-2.5 whitespace-nowrap">违规统计</th>
              <th className="px-3 py-2.5 whitespace-nowrap">合规分</th>
              <th className="px-3 py-2.5 whitespace-nowrap">耗时</th>
              <th className="px-4 py-2.5 text-right whitespace-nowrap">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#ECEAE5]">
            {results.map((baseRow) => {
              const override = recheckOverrides[baseRow.paper_id];
              const row = override ?? baseRow;
              const isRechecked = Boolean(override);
              const activeRuleSet = ruleSetMap.get(row.rule_set_id);
              const isRechecking = recheckingPaperId === row.paper_id;
              const isMenuOpen = overflowMenu?.paperId === row.paper_id;

              return (
                <tr
                  key={baseRow.id}
                  onClick={() => onInspectRun(row.id)}
                  className="cursor-pointer transition-colors hover:bg-[#FAF9F7]"
                >
                  <td className="max-w-[360px] px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-medium text-[#18181B]" title={row.file_name}>
                        {row.file_name}
                      </span>
                      {isRechecked && (
                        <span
                          title={activeRuleSet ? `已按「${activeRuleSet.name}」重检` : '已免重解析重检'}
                          className="shrink-0 rounded bg-[#EFF4FA] px-1.5 py-0.5 text-[10px] font-medium text-[#1E3A5F]"
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
                      <p className="mt-0.5 truncate text-[11px] text-[#71717A]" title={row.detected_title}>
                        {row.detected_title}
                      </p>
                    ) : (
                      <p className="mt-0.5 text-[11px] text-[#71717A]">
                        {activeRuleSet ? activeRuleSet.name : '未提取到主标题'}
                      </p>
                    )}
                  </td>

                  <td className="px-3 py-3 whitespace-nowrap">
                    <div className="flex items-center gap-1.5">
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                          row.file_ext === 'docx'
                            ? 'bg-[#EFF4FA] text-[#1E3A5F]'
                            : 'bg-[#FDF2EE] text-[#9A3412]'
                        }`}
                      >
                        {row.file_ext}
                      </span>
                      <span className="tabular-nums text-[#52525B]">
                        {row.page_count != null ? `${row.page_count} 页` : '—'}
                      </span>
                    </div>
                    <div className="mt-0.5 tabular-nums text-[11px] text-[#71717A]">
                      {formatFileSize(row.file_size)}
                    </div>
                  </td>

                  <td className="px-3 py-3 whitespace-nowrap">
                    <VerdictBadge verdict={row.verdict} compact />
                  </td>

                  <td className="px-3 py-3 whitespace-nowrap tabular-nums">
                    {row.parse_status === 'failed' ? (
                      <span className="text-[#71717A]">—</span>
                    ) : (
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`font-medium ${
                            row.error_count > 0 ? 'text-[#B91C1C]' : 'text-[#52525B]'
                          }`}
                        >
                          {row.error_count} 错误
                        </span>
                        <span className="text-[#D8D5CE]">/</span>
                        <span
                          className={
                            row.warning_count > 0 ? 'font-medium text-[#B45309]' : 'text-[#71717A]'
                          }
                        >
                          {row.warning_count} 警告
                        </span>
                      </div>
                    )}
                  </td>

                  <td className="px-3 py-3 whitespace-nowrap tabular-nums">
                    <div className="flex items-center gap-2">
                      <span className="w-10 font-semibold text-[#18181B]">
                        {formatScore(row.score)}
                      </span>
                      <div className="hidden h-1.5 w-14 overflow-hidden rounded-full bg-[#EFECE6] sm:block">
                        <div
                          className={`h-full rounded-full ${
                            row.verdict === 'pass'
                              ? 'bg-[#16A34A]'
                              : row.verdict === 'fail'
                                ? 'bg-[#DC2626]'
                                : 'bg-[#D97706]'
                          }`}
                          style={{ width: `${Math.max(0, Math.min(100, row.score))}%` }}
                        />
                      </div>
                    </div>
                  </td>

                  <td className="px-3 py-3 whitespace-nowrap tabular-nums text-[#71717A]">
                    {formatDuration(row.duration_ms)}
                  </td>

                  <td
                    className="relative px-4 py-3 text-right whitespace-nowrap"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div className="inline-flex items-center justify-end gap-1.5">
                      {row.parse_status === 'success' ? (
                        <button
                          type="button"
                          disabled={openingRevisionRunId === row.id}
                          onClick={() => onOpenRevision(row.id)}
                          className="inline-flex h-7 items-center gap-1 rounded-md border border-[#D7E2EE] bg-[#EFF4FA]/70 px-2.5 text-xs font-medium text-[#1E3A5F] transition-colors hover:border-[#1E3A5F] hover:bg-[#1E3A5F] hover:text-white disabled:opacity-50"
                        >
                          {openingRevisionRunId === row.id ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Wand2 className="h-3.5 w-3.5" />
                          )}
                          <span>进入修订</span>
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => onInspectRun(row.id)}
                          className="inline-flex h-7 items-center gap-1 rounded-md border border-[#E2E0DA] bg-white px-2.5 text-xs font-medium text-[#52525B] hover:bg-[#F7F7F5] hover:text-[#18181B]"
                        >
                          <Eye className="h-3.5 w-3.5" />
                          <span>查看异常</span>
                        </button>
                      )}

                      <button
                        type="button"
                        aria-label="更多操作"
                        aria-expanded={isMenuOpen}
                        disabled={isRechecking}
                        onClick={(e) => {
                          const rect = e.currentTarget.getBoundingClientRect();
                          setOverflowMenu((prev) =>
                            prev?.paperId === row.paper_id
                              ? null
                              : {
                                  runId: row.id,
                                  paperId: row.paper_id,
                                  currentRuleSetId: row.rule_set_id,
                                  top: Math.min(rect.bottom + 6, window.innerHeight - 220),
                                  right: Math.max(12, window.innerWidth - rect.right),
                                },
                          );
                        }}
                        className={`inline-flex h-7 w-7 items-center justify-center rounded-md text-[#52525B] transition-colors hover:bg-[#F3F2EE] hover:text-[#18181B] disabled:opacity-50 ${
                          isMenuOpen ? 'bg-[#F3F2EE] text-[#18181B]' : ''
                        }`}
                      >
                        {isRechecking ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin text-[#1E3A5F]" />
                        ) : (
                          <MoreHorizontal className="h-4 w-4" />
                        )}
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {overflowMenu && (
        <>
          <div
            className="fixed inset-0 z-30"
            onClick={() => setOverflowMenu(null)}
            aria-hidden="true"
          />
          <div
            role="menu"
            style={{ top: overflowMenu.top, right: overflowMenu.right }}
            className="fixed z-40 w-64 rounded-xl border border-[#E8E6E1] bg-white p-1.5 text-left shadow-lg"
          >
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                const targetRunId = overflowMenu.runId;
                setOverflowMenu(null);
                onInspectRun(targetRunId);
              }}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs font-medium text-[#18181B] hover:bg-[#F3F2EE]"
            >
              <Eye className="h-3.5 w-3.5 text-[#52525B]" />
              <span>查看违规详情</span>
            </button>

            <div className="my-1 border-t border-[#ECEAE5]" />

            <div className="flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium text-[#71717A]">
              <RefreshCw className="h-3 w-3" />
              <span>切换模板免重解析重检</span>
            </div>

            {ruleSets.map((rs) => {
              const isCurrent = rs.id === overflowMenu.currentRuleSetId;
              return (
                <button
                  key={rs.id}
                  type="button"
                  role="menuitem"
                  onClick={async () => {
                    const targetPaperId = overflowMenu.paperId;
                    setOverflowMenu(null);
                    await onQuickRecheck(targetPaperId, rs.id);
                  }}
                  className="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs text-[#18181B] hover:bg-[#EFF4FA]"
                >
                  <span className="truncate">{rs.name}</span>
                  {isCurrent && <Check className="ml-2 h-3.5 w-3.5 shrink-0 text-[#1E3A5F]" />}
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
