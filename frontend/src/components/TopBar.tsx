import {
  BarChart3,
  BookOpenCheck,
  FileSearch,
  RefreshCw,
  SlidersHorizontal,
} from 'lucide-react';
import type { HealthResponse, RuleSetResponse } from '../types/api';
import { DEGREE_LABELS } from '../utils/format';

export type ActiveTab = 'workbench' | 'stats';

interface TopBarProps {
  activeTab: ActiveTab;
  onTabChange: (tab: ActiveTab) => void;
  ruleSets: RuleSetResponse[];
  selectedRuleSetId: string;
  onSelectRuleSet: (id: string) => void;
  onOpenRuleConfig: () => void;
  health: HealthResponse | null;
  healthError: boolean;
  checkingHealth: boolean;
  onRefreshHealth: () => void;
}

export function TopBar({
  activeTab,
  onTabChange,
  ruleSets,
  selectedRuleSetId,
  onSelectRuleSet,
  onOpenRuleConfig,
  health,
  healthError,
  checkingHealth,
  onRefreshHealth,
}: TopBarProps) {
  const isConnected = !healthError && health?.status === 'ok' && health?.database === 'connected';
  const isDbDown = !healthError && health && health.database !== 'connected';

  const healthBadge = isConnected
    ? {
        label: 'PG18 已连接',
        classes: 'border-[#BBF7D0] bg-[#ECFDF5] text-[#15803D]',
        dot: 'bg-[#15803D]',
      }
    : isDbDown
      ? {
          label: '数据库未就绪',
          classes: 'border-[#FDE68A] bg-[#FFFBEB] text-[#B45309]',
          dot: 'bg-[#B45309]',
        }
      : {
          label: '后端未连接',
          classes: 'border-[#FECACA] bg-[#FEF2F2] text-[#B91C1C]',
          dot: 'bg-[#B91C1C]',
        };

  return (
    <header className="sticky top-0 z-30 border-b border-[#E5E2DC] bg-white/95 backdrop-blur-sm">
      <div className="mx-auto flex max-w-[1380px] flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#234B7A] text-white shadow-xs">
            <BookOpenCheck className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-semibold tracking-tight text-[#1A2332]">
                论文格式合规分析系统
              </h1>
              <span className="hidden rounded border border-[#E5E2DC] bg-[#FAF9F6] px-1.5 py-0.5 text-[11px] font-medium text-[#5A6577] sm:inline-block">
                师大研〔2019〕7号
              </span>
            </div>
            <p className="text-xs text-[#5A6577]">
              批量结构解析 · 规范定位校对 · 规则动态调参
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          {/* View tabs */}
          <nav
            aria-label="主视图切换"
            className="inline-flex rounded-lg border border-[#E5E2DC] bg-[#FAF9F6] p-0.5"
          >
            <button
              type="button"
              onClick={() => onTabChange('workbench')}
              className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                activeTab === 'workbench'
                  ? 'bg-white text-[#1A2332] shadow-xs'
                  : 'text-[#5A6577] hover:text-[#1A2332]'
              }`}
            >
              <FileSearch className="h-3.5 w-3.5" />
              <span>检测工作台</span>
            </button>
            <button
              type="button"
              onClick={() => onTabChange('stats')}
              className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                activeTab === 'stats'
                  ? 'bg-white text-[#1A2332] shadow-xs'
                  : 'text-[#5A6577] hover:text-[#1A2332]'
              }`}
            >
              <BarChart3 className="h-3.5 w-3.5" />
              <span>统计洞察</span>
            </button>
          </nav>

          {/* Rule set selector */}
          <div className="flex items-center gap-1.5">
            <label htmlFor="active-rule-set" className="sr-only">
              当前规则模板
            </label>
            <select
              id="active-rule-set"
              value={selectedRuleSetId}
              onChange={(e) => onSelectRuleSet(e.target.value)}
              disabled={ruleSets.length === 0}
              className="h-8 max-w-[260px] rounded-lg border border-[#E5E2DC] bg-white px-2.5 text-xs font-medium text-[#1A2332] shadow-2xs transition-colors hover:border-[#C8C3B9] focus:border-[#234B7A] focus:outline-none disabled:opacity-50"
            >
              {ruleSets.length === 0 ? (
                <option value="">正在加载规则模板...</option>
              ) : (
                ruleSets.map((rs) => (
                  <option key={rs.id} value={rs.id}>
                    {rs.name}（{DEGREE_LABELS[rs.degree_level]} · {rs.rule_count}条）
                    {rs.is_default ? ' [默认]' : ''}
                  </option>
                ))
              )}
            </select>

            <button
              type="button"
              onClick={onOpenRuleConfig}
              disabled={!selectedRuleSetId}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#E5E2DC] bg-white px-3 text-xs font-medium text-[#1A2332] shadow-2xs transition-colors hover:border-[#234B7A]/40 hover:bg-[#FAF9F6] disabled:cursor-not-allowed disabled:opacity-50"
            >
              <SlidersHorizontal className="h-3.5 w-3.5 text-[#234B7A]" />
              <span>规则配置</span>
            </button>
          </div>

          {/* Health status pill */}
          <button
            type="button"
            onClick={onRefreshHealth}
            title="点击重新检测后端与数据库连接状态"
            className={`inline-flex h-8 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-opacity hover:opacity-85 ${healthBadge.classes}`}
          >
            <span className={`h-2 w-2 rounded-full ${healthBadge.dot}`} />
            <span>{healthBadge.label}</span>
            <RefreshCw className={`h-3 w-3 ${checkingHealth ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>
    </header>
  );
}
