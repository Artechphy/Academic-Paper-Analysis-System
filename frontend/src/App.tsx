import { useCallback, useEffect, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  Menu,
  Plus,
  RefreshCw,
  X,
} from 'lucide-react';
import {
  ApiError,
  checkBatch,
  getBatch,
  getCheckRun,
  getHealth,
  getRuleSet,
  getStatsOverview,
  listBatches,
  listRuleSets,
  recheckPaper,
} from './api/client';
import { createOrResumeRevision } from './api/revisions';
import { AppSidebar, type ActiveTab } from './components/AppSidebar';
import { BatchOverviewBar } from './components/BatchOverviewBar';
import { ResultsTable } from './components/ResultsTable';
import { RevisionWorkspace } from './components/RevisionWorkspace';
import { RuleTemplatesView } from './components/RuleTemplatesView';
import { StatsView } from './components/StatsView';
import { EmptyBatchCard, UploadModal } from './components/UploadModal';
import { ViolationDrawer } from './components/ViolationDrawer';
import type {
  BatchDetail,
  BatchSummary,
  CheckRunDetail,
  CheckRunSummary,
  HealthResponse,
  RuleItemResponse,
  RuleSetDetail,
  RuleSetResponse,
  StatsOverview,
  Verdict,
} from './types/api';
import type { RevisionSessionDetail } from './types/revisions';
import { formatDateTime } from './utils/format';

interface ToastState {
  kind: 'success' | 'error';
  message: string;
}

function toSummary(detail: CheckRunDetail): CheckRunSummary {
  const { ir_summary: _ir, violations: _v, manual_checklist: _mc, ...summary } = detail;
  return summary;
}

export default function App() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('workbench');
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  // Health
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [checkingHealth, setCheckingHealth] = useState(false);

  // Rule sets & Rule templates view
  const [ruleSets, setRuleSets] = useState<RuleSetResponse[]>([]);
  const [selectedRuleSetId, setSelectedRuleSetId] = useState('');
  const [ruleSetDetail, setRuleSetDetail] = useState<RuleSetDetail | null>(null);
  const [loadingRuleDetail, setLoadingRuleDetail] = useState(false);

  // Batches & results
  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState('');
  const [batchDetail, setBatchDetail] = useState<BatchDetail | null>(null);
  const [loadingBatch, setLoadingBatch] = useState(false);
  const [submittingBatch, setSubmittingBatch] = useState(false);
  const [verdictFilter, setVerdictFilter] = useState<Verdict | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');

  // Recheck & Violation drawer
  const [recheckOverrides, setRecheckOverrides] = useState<Record<string, CheckRunSummary>>({});
  const [recheckingPaperId, setRecheckingPaperId] = useState<string | null>(null);
  const [violationDrawerOpen, setViolationDrawerOpen] = useState(false);
  const [activeCheckRun, setActiveCheckRun] = useState<CheckRunDetail | null>(null);
  const [loadingCheckRun, setLoadingCheckRun] = useState(false);

  // Stats overview
  const [statsOverview, setStatsOverview] = useState<StatsOverview | null>(null);
  const [loadingStats, setLoadingStats] = useState(false);

  // Revision studio
  const [activeRevisionSession, setActiveRevisionSession] =
    useState<RevisionSessionDetail | null>(null);
  const [openingRevisionRunId, setOpeningRevisionRunId] = useState<string | null>(null);

  const showToast = useCallback((kind: 'success' | 'error', message: string) => {
    setToast({ kind, message });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 4500);
    return () => window.clearTimeout(timer);
  }, [toast]);

  // Debounce search input
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(searchQuery), 240);
    return () => window.clearTimeout(timer);
  }, [searchQuery]);

  const refreshHealth = useCallback(async () => {
    setCheckingHealth(true);
    try {
      const data = await getHealth();
      setHealth(data);
      setHealthError(false);
    } catch {
      setHealth(null);
      setHealthError(true);
    } finally {
      setCheckingHealth(false);
    }
  }, []);

  const refreshStats = useCallback(async () => {
    setLoadingStats(true);
    try {
      const data = await getStatsOverview();
      setStatsOverview(data);
    } catch {
      // Keep previous stats if transient failure
    } finally {
      setLoadingStats(false);
    }
  }, []);

  // Initial bootstrap
  useEffect(() => {
    void refreshHealth();
    void refreshStats();

    void (async () => {
      try {
        const [sets, batchList] = await Promise.all([listRuleSets(), listBatches()]);
        setRuleSets(sets);
        const preferred =
          sets.find((s) => s.is_default) ??
          sets.find((s) => s.code === 'fjnu_master_2019') ??
          sets[0];
        if (preferred) setSelectedRuleSetId(preferred.id);

        setBatches(batchList);
        if (batchList.length > 0) {
          setSelectedBatchId(batchList[0].id);
        }
      } catch (err) {
        showToast(
          'error',
          err instanceof ApiError ? err.message : '初始化数据加载失败，请确认后端服务与数据库已启动',
        );
      }
    })();
  }, [refreshHealth, refreshStats, showToast]);

  // Load selected batch when batchId / filters change
  useEffect(() => {
    if (!selectedBatchId) {
      setBatchDetail(null);
      return;
    }
    let cancelled = false;
    setLoadingBatch(true);
    void (async () => {
      try {
        const detail = await getBatch(selectedBatchId, {
          verdict: verdictFilter,
          q: debouncedQuery,
        });
        if (!cancelled) {
          setBatchDetail(detail);
        }
      } catch (err) {
        if (!cancelled) {
          showToast('error', err instanceof ApiError ? err.message : '获取批次详情失败');
        }
      } finally {
        if (!cancelled) setLoadingBatch(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedBatchId, verdictFilter, debouncedQuery, showToast]);

  // Load rule set detail when viewing RuleTemplatesView or switching selected rule set
  useEffect(() => {
    if (activeTab !== 'rules' || !selectedRuleSetId) return;
    let cancelled = false;
    setLoadingRuleDetail(true);
    void (async () => {
      try {
        const detail = await getRuleSet(selectedRuleSetId);
        if (!cancelled) setRuleSetDetail(detail);
      } catch (err) {
        if (!cancelled) {
          showToast('error', err instanceof ApiError ? err.message : '加载规则配置详情失败');
        }
      } finally {
        if (!cancelled) setLoadingRuleDetail(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeTab, selectedRuleSetId, showToast]);

  const handleSelectBatch = (batchId: string) => {
    setViolationDrawerOpen(false);
    setRecheckOverrides({});
    setSelectedBatchId(batchId);
  };

  const handleSubmitBatch = async (files: File[], batchName: string): Promise<boolean> => {
    if (!selectedRuleSetId) return false;
    setSubmittingBatch(true);
    try {
      const created = await checkBatch(files, selectedRuleSetId, batchName);
      setRecheckOverrides({});
      setVerdictFilter(null);
      setSearchQuery('');
      setDebouncedQuery('');
      setBatchDetail(created);
      setSelectedBatchId(created.id);
      setActiveTab('workbench');

      const summary: BatchSummary = {
        id: created.id,
        name: created.name,
        rule_set_id: created.rule_set_id,
        status: created.status,
        created_at: created.created_at,
        completed_at: created.completed_at,
        total_count: created.total_count,
        pass_count: created.pass_count,
        fail_count: created.fail_count,
        error_count: created.error_count,
        pass_rate: created.pass_rate,
        avg_score: created.avg_score,
        avg_duration_ms: created.avg_duration_ms,
      };
      setBatches((prev) => [summary, ...prev.filter((b) => b.id !== created.id)]);
      void refreshStats();
      showToast(
        'success',
        `已完成「${created.name}」检测：共 ${created.total_count} 篇（合格 ${created.pass_count} / 问题 ${created.fail_count} / 异常 ${created.error_count}）`,
      );
      return true;
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : '批量检测失败');
      return false;
    } finally {
      setSubmittingBatch(false);
    }
  };

  const handleInspectRun = async (runId: string) => {
    setViolationDrawerOpen(true);
    setLoadingCheckRun(true);
    try {
      const detail = await getCheckRun(runId);
      setActiveCheckRun(detail);
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : '读取检测详情失败');
      setViolationDrawerOpen(false);
    } finally {
      setLoadingCheckRun(false);
    }
  };

  const handleRecheck = async (paperId: string, ruleSetId: string) => {
    setRecheckingPaperId(paperId);
    try {
      const detail = await recheckPaper(paperId, ruleSetId);
      const summary = toSummary(detail);
      setRecheckOverrides((prev) => ({ ...prev, [paperId]: summary }));
      if (violationDrawerOpen && activeCheckRun?.paper_id === paperId) {
        setActiveCheckRun(detail);
      }
      void refreshStats();
      const targetName = ruleSets.find((r) => r.id === ruleSetId)?.name ?? '目标模板';
      showToast('success', `已基于快照免重解析重检（${targetName}）`);
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : '重检失败');
    } finally {
      setRecheckingPaperId(null);
    }
  };

  const handleRuleUpdated = (updated: RuleItemResponse) => {
    setRuleSetDetail((prev) =>
      prev
        ? {
            ...prev,
            rule_items: prev.rule_items.map((item) =>
              item.id === updated.id ? updated : item,
            ),
          }
        : prev,
    );
    showToast('success', `已保存规则「${updated.name}」配置`);
  };

  const handleRuleSetCreated = (created: RuleSetDetail) => {
    const { manual_checklist: _mc, rule_items: _items, ...summary } = created;
    setRuleSets((prev) => [summary, ...prev]);
    setSelectedRuleSetId(created.id);
    setRuleSetDetail(created);
    showToast('success', `已克隆并切换至模板「${created.name}」`);
  };

  const handleOpenRevision = async (runId: string) => {
    setOpeningRevisionRunId(runId);
    try {
      const session = await createOrResumeRevision(runId);
      setViolationDrawerOpen(false);
      setActiveRevisionSession(session);
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : '打开论文修订工作台失败');
    } finally {
      setOpeningRevisionRunId(null);
    }
  };

  const backendUnavailable = healthError || (health !== null && health.status !== 'ok');
  const activeBatchSummary = batches.find((b) => b.id === selectedBatchId);
  const activeBatchRuleSetName = activeBatchSummary
    ? (ruleSets.find((r) => r.id === activeBatchSummary.rule_set_id)?.name ?? null)
    : null;

  const toastNode = toast && (
    <div
      role="status"
      className={`fixed right-5 bottom-5 z-50 flex max-w-md items-center gap-2.5 rounded-xl border px-4 py-3 text-xs font-medium shadow-lg ${
        toast.kind === 'success'
          ? 'border-[#BBF7D0] bg-[#ECFDF5] text-[#15803D]'
          : 'border-[#FECACA] bg-[#FEF2F2] text-[#B91C1C]'
      }`}
    >
      {toast.kind === 'success' ? (
        <CheckCircle2 className="h-4 w-4 shrink-0" />
      ) : (
        <AlertCircle className="h-4 w-4 shrink-0" />
      )}
      <span className="flex-1">{toast.message}</span>
      <button
        type="button"
        onClick={() => setToast(null)}
        aria-label="关闭通知"
        className="rounded p-0.5 opacity-70 hover:opacity-100"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );

  // Immersive Full-Screen Studio Mode
  if (activeRevisionSession) {
    return (
      <>
        <RevisionWorkspace
          session={activeRevisionSession}
          onSessionChange={setActiveRevisionSession}
          onBack={() => setActiveRevisionSession(null)}
          onNotify={showToast}
        />
        {toastNode}
      </>
    );
  }

  return (
    <div className="flex min-h-screen bg-white text-[#18181B]">
      <AppSidebar
        activeTab={activeTab}
        onTabChange={(tab) => {
          setViolationDrawerOpen(false);
          setActiveTab(tab);
        }}
        batches={batches}
        selectedBatchId={selectedBatchId}
        onSelectBatch={handleSelectBatch}
        health={health}
        healthError={healthError}
        checkingHealth={checkingHealth}
        onRefreshHealth={() => void refreshHealth()}
        mobileOpen={mobileSidebarOpen}
        onCloseMobile={() => setMobileSidebarOpen(false)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Crisp 56px Page Header */}
        <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-[#E8E6E1] bg-white/95 px-4 backdrop-blur-sm sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={() => setMobileSidebarOpen(true)}
              aria-label="打开导航栏"
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[#E8E6E1] text-[#52525B] hover:bg-[#F7F7F5] hover:text-[#18181B] lg:hidden"
            >
              <Menu className="h-4 w-4" />
            </button>

            {activeTab === 'workbench' ? (
              <div className="min-w-0">
                <h1 className="truncate text-sm font-semibold text-[#18181B]">
                  {activeBatchSummary ? activeBatchSummary.name : '检测工作台'}
                </h1>
                {activeBatchSummary && (
                  <p className="truncate text-[11px] text-[#71717A]">
                    {activeBatchRuleSetName ? `${activeBatchRuleSetName} · ` : ''}
                    {formatDateTime(activeBatchSummary.created_at)}
                  </p>
                )}
              </div>
            ) : activeTab === 'rules' ? (
              <div className="min-w-0">
                <h1 className="truncate text-sm font-semibold text-[#18181B]">规则模板配置</h1>
                <p className="truncate text-[11px] text-[#71717A]">
                  管理学位论文格式规则、严重级别与参数阈值
                </p>
              </div>
            ) : (
              <div className="min-w-0">
                <h1 className="truncate text-sm font-semibold text-[#18181B]">统计洞察</h1>
                <p className="truncate text-[11px] text-[#71717A]">
                  跨批次合规趋势与高频格式违规排行
                </p>
              </div>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {activeTab === 'workbench' && (
              <button
                type="button"
                onClick={() => setUploadModalOpen(true)}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#1E3A5F] px-3 text-xs font-semibold text-white transition-colors hover:bg-[#162C49]"
              >
                <Plus className="h-3.5 w-3.5" />
                <span>新建检测</span>
              </button>
            )}

            {activeTab === 'stats' && (
              <button
                type="button"
                onClick={() => void refreshStats()}
                disabled={loadingStats}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#E2E0DA] bg-white px-3 text-xs font-medium text-[#18181B] hover:bg-[#F7F7F5] disabled:opacity-55"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${loadingStats ? 'animate-spin' : ''}`} />
                <span>刷新统计</span>
              </button>
            )}
          </div>
        </header>

        {/* Scrollable Content Workspace */}
        <main className="mx-auto w-full max-w-[1220px] flex-1 space-y-5 px-4 py-5 sm:px-6">
          {backendUnavailable && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#FDE68A] bg-[#FFFBEB] px-4 py-2.5 text-xs text-[#92400E]">
              <span>
                后端 API 或 PostgreSQL 18 尚未连接，请确认服务已在{' '}
                <code className="font-mono">127.0.0.1:8000</code> 运行。
              </span>
              <button
                type="button"
                onClick={() => void refreshHealth()}
                className="font-semibold text-[#B45309] underline underline-offset-2"
              >
                重新检查
              </button>
            </div>
          )}

          {activeTab === 'workbench' ? (
            batches.length === 0 && !loadingBatch ? (
              <EmptyBatchCard onOpenUpload={() => setUploadModalOpen(true)} />
            ) : (
              <>
                <BatchOverviewBar
                  batchDetail={batchDetail}
                  verdictFilter={verdictFilter}
                  onVerdictFilterChange={setVerdictFilter}
                  searchQuery={searchQuery}
                  onSearchQueryChange={setSearchQuery}
                />

                <ResultsTable
                  results={batchDetail?.results ?? []}
                  ruleSets={ruleSets}
                  loading={loadingBatch}
                  hasBatch={Boolean(selectedBatchId)}
                  hasActiveFilters={Boolean(verdictFilter || searchQuery.trim())}
                  recheckOverrides={recheckOverrides}
                  recheckingPaperId={recheckingPaperId}
                  openingRevisionRunId={openingRevisionRunId}
                  onResetFilters={() => {
                    setVerdictFilter(null);
                    setSearchQuery('');
                  }}
                  onInspectRun={(runId) => void handleInspectRun(runId)}
                  onQuickRecheck={handleRecheck}
                  onOpenRevision={(runId) => void handleOpenRevision(runId)}
                />
              </>
            )
          ) : activeTab === 'rules' ? (
            <RuleTemplatesView
              ruleSets={ruleSets}
              selectedRuleSetId={selectedRuleSetId}
              onSelectRuleSet={setSelectedRuleSetId}
              ruleSetDetail={ruleSetDetail}
              loading={loadingRuleDetail}
              onRuleUpdated={handleRuleUpdated}
              onRuleSetCreated={handleRuleSetCreated}
            />
          ) : (
            <StatsView
              overview={statsOverview}
              batches={batches}
              ruleSets={ruleSets}
              loading={loadingStats}
              onOpenBatch={(batchId) => {
                handleSelectBatch(batchId);
                setActiveTab('workbench');
              }}
            />
          )}
        </main>
      </div>

      <UploadModal
        open={uploadModalOpen}
        ruleSets={ruleSets}
        selectedRuleSetId={selectedRuleSetId}
        onSelectRuleSet={setSelectedRuleSetId}
        submitting={submittingBatch}
        disabled={backendUnavailable}
        onClose={() => setUploadModalOpen(false)}
        onSubmitBatch={handleSubmitBatch}
      />

      <ViolationDrawer
        open={violationDrawerOpen}
        loading={loadingCheckRun}
        detail={activeCheckRun}
        ruleSets={ruleSets}
        rechecking={Boolean(
          activeCheckRun && recheckingPaperId === activeCheckRun.paper_id,
        )}
        openingRevision={Boolean(
          activeCheckRun && openingRevisionRunId === activeCheckRun.id,
        )}
        onClose={() => setViolationDrawerOpen(false)}
        onRecheck={handleRecheck}
        onOpenRevision={(runId) => void handleOpenRevision(runId)}
      />

      {toastNode}
    </div>
  );
}
