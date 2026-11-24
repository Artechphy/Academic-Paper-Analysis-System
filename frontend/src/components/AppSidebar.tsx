import {
  BarChart3,
  BookOpenCheck,
  FileSearch,
  FolderClock,
  RefreshCw,
  SlidersHorizontal,
  X,
} from 'lucide-react';
import type { BatchSummary, HealthResponse } from '../types/api';
import { formatDateTime } from '../utils/format';

export type ActiveTab = 'workbench' | 'rules' | 'stats';

interface AppSidebarProps {
  activeTab: ActiveTab;
  onTabChange: (tab: ActiveTab) => void;
  batches: BatchSummary[];
  selectedBatchId: string;
  onSelectBatch: (batchId: string) => void;
  health: HealthResponse | null;
  healthError: boolean;
  checkingHealth: boolean;
  onRefreshHealth: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

export function AppSidebar({
  activeTab,
  onTabChange,
  batches,
  selectedBatchId,
  onSelectBatch,
  health,
  healthError,
  checkingHealth,
  onRefreshHealth,
  mobileOpen,
  onCloseMobile,
}: AppSidebarProps) {
  const isConnected =
    !healthError && health?.status === 'ok' && health?.database === 'connected';
  const isDbDown = !healthError && health && health.database !== 'connected';

  const healthMeta = isConnected
    ? {
        label: 'PG18 正常',
        dot: 'bg-[#16A34A]',
        text: 'text-[#52525B]',
      }
    : isDbDown
      ? {
          label: '数据库未就绪',
          dot: 'bg-[#D97706]',
          text: 'text-[#B45309]',
        }
      : {
          label: '后端离线',
          dot: 'bg-[#DC2626]',
          text: 'text-[#B91C1C]',
        };

  const navItems: Array<{
    key: ActiveTab;
    label: string;
    icon: typeof FileSearch;
  }> = [
    { key: 'workbench', label: '检测工作台', icon: FileSearch },
    { key: 'rules', label: '规则模板', icon: SlidersHorizontal },
    { key: 'stats', label: '统计洞察', icon: BarChart3 },
  ];

  const handleNavClick = (tab: ActiveTab) => {
    onTabChange(tab);
    onCloseMobile();
  };

  const handleBatchClick = (batchId: string) => {
    onSelectBatch(batchId);
    onTabChange('workbench');
    onCloseMobile();
  };

  const sidebarBody = (
    <div className="flex h-full w-[248px] flex-col border-r border-[#E8E6E1] bg-[#F7F7F5]">
      {/* Brand header */}
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-[#ECEAE5] px-4">
        <div className="flex min-w-0 items-center gap-2.5">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[#1E3A5F] text-white">
            <BookOpenCheck className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <div className="truncate text-[13px] font-semibold tracking-tight text-[#18181B]">
              论文编校台
            </div>
            <div className="truncate text-[11px] text-[#71717A]">师大研〔2019〕7号</div>
          </div>
        </div>
        <button
          type="button"
          onClick={onCloseMobile}
          aria-label="关闭导航栏"
          className="rounded-md p-1 text-[#71717A] hover:bg-[#ECEAE5] hover:text-[#18181B] lg:hidden"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Primary navigation */}
      <nav aria-label="主导航" className="shrink-0 space-y-0.5 px-2.5 pt-3 pb-2">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = activeTab === item.key;
          return (
            <button
              key={item.key}
              type="button"
              onClick={() => handleNavClick(item.key)}
              className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium transition-colors ${
                active
                  ? 'bg-white text-[#18181B] shadow-2xs ring-1 ring-[#E8E6E1]'
                  : 'text-[#52525B] hover:bg-[#EFECE6] hover:text-[#18181B]'
              }`}
            >
              <Icon
                className={`h-4 w-4 shrink-0 ${active ? 'text-[#1E3A5F]' : 'text-[#71717A]'}`}
              />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Historical Batches */}
      <div className="flex min-h-0 flex-1 flex-col border-t border-[#ECEAE5] pt-3">
        <div className="flex items-center justify-between px-4 pb-2">
          <div className="flex items-center gap-1.5 text-[11px] font-medium text-[#71717A]">
            <FolderClock className="h-3.5 w-3.5" />
            <span>历史批次</span>
          </div>
          <span className="tabular-nums text-[11px] text-[#71717A]">{batches.length}</span>
        </div>

        <div className="flex-1 space-y-0.5 overflow-y-auto px-2.5 pb-3">
          {batches.length === 0 ? (
            <div className="px-2 py-6 text-center text-[11px] text-[#71717A]">
              暂无检测记录
            </div>
          ) : (
            batches.map((b) => {
              const isSelected = activeTab === 'workbench' && b.id === selectedBatchId;
              const statusDot =
                b.error_count > 0
                  ? 'bg-[#D97706]'
                  : b.fail_count > 0
                    ? 'bg-[#DC2626]'
                    : 'bg-[#16A34A]';

              return (
                <button
                  key={b.id}
                  type="button"
                  onClick={() => handleBatchClick(b.id)}
                  className={`group flex w-full flex-col rounded-lg px-2.5 py-2 text-left transition-colors ${
                    isSelected
                      ? 'bg-white ring-1 ring-[#E8E6E1] shadow-2xs'
                      : 'hover:bg-[#EFECE6]/80'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusDot}`} />
                      <span
                        className={`truncate text-xs ${
                          isSelected
                            ? 'font-semibold text-[#18181B]'
                            : 'font-medium text-[#52525B] group-hover:text-[#18181B]'
                        }`}
                        title={b.name}
                      >
                        {b.name}
                      </span>
                    </div>
                    <span className="shrink-0 tabular-nums text-[11px] text-[#71717A]">
                      {b.total_count} 篇
                    </span>
                  </div>
                  <div className="mt-1 flex items-center justify-between pl-3.5 text-[10px] tabular-nums text-[#71717A]">
                    <span>{formatDateTime(b.created_at)}</span>
                    <span>
                      {b.pass_count}/{b.total_count} 合格
                    </span>
                  </div>
                </button>
              );
            })
          )}
        </div>
      </div>

      {/* Quiet Health Indicator Footer */}
      <div className="shrink-0 border-t border-[#ECEAE5] p-2.5">
        <button
          type="button"
          onClick={onRefreshHealth}
          title="点击刷新服务与数据库连接状态"
          className="group flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-xs transition-colors hover:bg-[#EFECE6]"
        >
          <span className={`flex items-center gap-2 font-medium ${healthMeta.text}`}>
            <span className={`h-2 w-2 rounded-full ${healthMeta.dot}`} />
            <span>{healthMeta.label}</span>
          </span>
          <RefreshCw
            className={`h-3 w-3 text-[#71717A] transition-opacity ${
              checkingHealth ? 'animate-spin opacity-100' : 'opacity-0 group-hover:opacity-100'
            }`}
          />
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop fixed rail */}
      <aside className="hidden lg:block lg:h-screen lg:sticky lg:top-0 lg:shrink-0">
        {sidebarBody}
      </aside>

      {/* Mobile slide-over */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 flex lg:hidden">
          <div
            className="fixed inset-0 bg-[#18181B]/30 backdrop-blur-[1px]"
            onClick={onCloseMobile}
            aria-hidden="true"
          />
          <aside className="relative z-10 h-full shadow-xl">{sidebarBody}</aside>
        </div>
      )}
    </>
  );
}
