import { useEffect, useMemo, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  CopyPlus,
  Loader2,
  Save,
  SlidersHorizontal,
} from 'lucide-react';
import { ApiError, createRuleSet, updateRuleItem } from '../api/client';
import type {
  RuleItemResponse,
  RuleSetDetail,
  RuleSetResponse,
  Severity,
} from '../types/api';
import {
  APPLIES_TO_LABELS,
  CATEGORY_ORDER,
  DEGREE_LABELS,
  getCategoryLabel,
} from '../utils/format';

interface RuleTemplatesViewProps {
  ruleSets: RuleSetResponse[];
  selectedRuleSetId: string;
  onSelectRuleSet: (id: string) => void;
  ruleSetDetail: RuleSetDetail | null;
  loading: boolean;
  onRuleUpdated: (updated: RuleItemResponse) => void;
  onRuleSetCreated: (created: RuleSetDetail) => void;
}

export function RuleTemplatesView({
  ruleSets,
  selectedRuleSetId,
  onSelectRuleSet,
  ruleSetDetail,
  loading,
  onRuleUpdated,
  onRuleSetCreated,
}: RuleTemplatesViewProps) {
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [savingItemId, setSavingItemId] = useState<string | null>(null);
  const [expandedParamsId, setExpandedParamsId] = useState<string | null>(null);
  const [paramDrafts, setParamDrafts] = useState<Record<string, string>>({});
  const [itemErrors, setItemErrors] = useState<Record<string, string>>({});

  // Clone template state
  const [cloneOpen, setCloneOpen] = useState(false);
  const [cloneCode, setCloneCode] = useState('');
  const [cloneVersion, setCloneVersion] = useState('1.0.0');
  const [cloneName, setCloneName] = useState('');
  const [cloneDesc, setCloneDesc] = useState('');
  const [cloning, setCloning] = useState(false);
  const [cloneError, setCloneError] = useState<string | null>(null);

  useEffect(() => {
    if (!ruleSetDetail) return;
    setCategoryFilter('all');
    setItemErrors({});
    setExpandedParamsId(null);
    const nextDrafts: Record<string, string> = {};
    for (const item of ruleSetDetail.rule_items) {
      nextDrafts[item.id] = JSON.stringify(item.params, null, 2);
    }
    setParamDrafts(nextDrafts);
  }, [ruleSetDetail?.id]);

  const categories = useMemo(() => {
    if (!ruleSetDetail) return [];
    const present = new Set(ruleSetDetail.rule_items.map((item) => item.category));
    return CATEGORY_ORDER.filter((c) => present.has(c));
  }, [ruleSetDetail]);

  const visibleItems = useMemo(() => {
    if (!ruleSetDetail) return [];
    if (categoryFilter === 'all') return ruleSetDetail.rule_items;
    return ruleSetDetail.rule_items.filter((item) => item.category === categoryFilter);
  }, [ruleSetDetail, categoryFilter]);

  const openCloneForm = () => {
    if (!ruleSetDetail) return;
    const stamp = Math.floor(Date.now() / 1000)
      .toString()
      .slice(-4);
    setCloneCode(`${ruleSetDetail.code}_custom_${stamp}`);
    setCloneVersion('1.0.0');
    setCloneName(`${ruleSetDetail.name}（自定义）`);
    setCloneDesc(ruleSetDetail.description ?? '');
    setCloneError(null);
    setCloneOpen((prev) => !prev);
  };

  const handleCloneSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!ruleSetDetail || cloning) return;
    if (!cloneCode.trim() || !cloneName.trim()) {
      setCloneError('请填写新模板的编号和名称');
      return;
    }
    setCloning(true);
    setCloneError(null);
    try {
      const created = await createRuleSet({
        code: cloneCode.trim(),
        version: cloneVersion.trim() || '1.0.0',
        name: cloneName.trim(),
        description: cloneDesc.trim() || null,
        degree_level: ruleSetDetail.degree_level,
        source_rule_set_id: ruleSetDetail.id,
      });
      setCloneOpen(false);
      onRuleSetCreated(created);
    } catch (err) {
      setCloneError(err instanceof ApiError ? err.message : '克隆模板失败');
    } finally {
      setCloning(false);
    }
  };

  const handleToggleEnabled = async (item: RuleItemResponse) => {
    setSavingItemId(item.id);
    setItemErrors((prev) => ({ ...prev, [item.id]: '' }));
    try {
      const updated = await updateRuleItem(item.id, { enabled: !item.enabled });
      onRuleUpdated(updated);
    } catch (err) {
      setItemErrors((prev) => ({
        ...prev,
        [item.id]: err instanceof ApiError ? err.message : '更新启用状态失败',
      }));
    } finally {
      setSavingItemId(null);
    }
  };

  const handleChangeSeverity = async (item: RuleItemResponse, severity: Severity) => {
    if (item.severity === severity) return;
    setSavingItemId(item.id);
    setItemErrors((prev) => ({ ...prev, [item.id]: '' }));
    try {
      const updated = await updateRuleItem(item.id, { severity });
      onRuleUpdated(updated);
    } catch (err) {
      setItemErrors((prev) => ({
        ...prev,
        [item.id]: err instanceof ApiError ? err.message : '切换严重级别失败',
      }));
    } finally {
      setSavingItemId(null);
    }
  };

  const handleSaveParams = async (item: RuleItemResponse) => {
    const raw = paramDrafts[item.id] ?? '{}';
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      setItemErrors((prev) => ({ ...prev, [item.id]: 'JSON 语法错误，请检查括号与引号' }));
      return;
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      setItemErrors((prev) => ({ ...prev, [item.id]: '规则参数必须是 JSON 对象' }));
      return;
    }

    setSavingItemId(item.id);
    setItemErrors((prev) => ({ ...prev, [item.id]: '' }));
    try {
      const updated = await updateRuleItem(item.id, {
        params: parsed as Record<string, unknown>,
      });
      setParamDrafts((prev) => ({
        ...prev,
        [item.id]: JSON.stringify(updated.params, null, 2),
      }));
      onRuleUpdated(updated);
    } catch (err) {
      setItemErrors((prev) => ({
        ...prev,
        [item.id]: err instanceof ApiError ? err.message : '保存参数失败',
      }));
    } finally {
      setSavingItemId(null);
    }
  };

  const enabledCount = ruleSetDetail
    ? ruleSetDetail.rule_items.filter((i) => i.enabled).length
    : 0;

  return (
    <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
      {/* Left Master Column: Rule Sets List */}
      <div className="w-full shrink-0 space-y-3 lg:w-[280px]">
        <div className="overflow-hidden rounded-xl border border-[#E8E6E1] bg-white">
          <div className="flex items-center justify-between border-b border-[#ECEAE5] bg-[#FAF9F7] px-3.5 py-2.5">
            <span className="text-xs font-semibold text-[#18181B]">可用规范模板</span>
            <span className="tabular-nums text-[11px] text-[#71717A]">
              {ruleSets.length} 套
            </span>
          </div>
          <div className="divide-y divide-[#ECEAE5]">
            {ruleSets.length === 0 ? (
              <div className="px-4 py-8 text-center text-xs text-[#71717A]">
                正在加载模板...
              </div>
            ) : (
              ruleSets.map((rs) => {
                const active = rs.id === selectedRuleSetId;
                return (
                  <button
                    key={rs.id}
                    type="button"
                    onClick={() => onSelectRuleSet(rs.id)}
                    className={`flex w-full flex-col gap-1 px-3.5 py-3 text-left transition-colors ${
                      active ? 'bg-[#EFF4FA]/70' : 'hover:bg-[#FAF9F7]'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span
                        className={`truncate text-xs font-semibold ${
                          active ? 'text-[#1E3A5F]' : 'text-[#18181B]'
                        }`}
                      >
                        {rs.name}
                      </span>
                      {rs.is_default && (
                        <span className="shrink-0 rounded bg-[#EFF4FA] px-1.5 py-0.5 text-[10px] font-medium text-[#1E3A5F]">
                          默认
                        </span>
                      )}
                    </div>
                    <div className="flex items-center justify-between text-[11px] text-[#71717A]">
                      <span>{DEGREE_LABELS[rs.degree_level]}</span>
                      <span className="tabular-nums">{rs.rule_count} 条规则</span>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>

        <button
          type="button"
          disabled={!ruleSetDetail}
          onClick={openCloneForm}
          className="flex h-9 w-full items-center justify-center gap-1.5 rounded-lg border border-[#E2E0DA] bg-white px-3 text-xs font-medium text-[#18181B] transition-colors hover:bg-[#F7F7F5] disabled:opacity-50"
        >
          <CopyPlus className="h-3.5 w-3.5 text-[#1E3A5F]" />
          <span>克隆当前模板</span>
        </button>
      </div>

      {/* Right Detail Column */}
      <div className="min-w-0 flex-1 space-y-4">
        {/* Clone template inline form */}
        {cloneOpen && ruleSetDetail && (
          <form
            onSubmit={handleCloneSubmit}
            className="space-y-3 rounded-xl border border-[#1E3A5F]/25 bg-[#EFF4FA]/40 p-4 text-xs"
          >
            <div className="font-semibold text-[#18181B]">
              从「{ruleSetDetail.name}」克隆创建自定义模板
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <label className="mb-1 block text-[11px] text-[#52525B]">模板编号 (code)</label>
                <input
                  type="text"
                  required
                  value={cloneCode}
                  onChange={(e) => setCloneCode(e.target.value)}
                  className="h-8 w-full rounded-lg border border-[#E8E6E1] bg-white px-2.5 font-mono text-xs focus:border-[#1E3A5F] focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-[#52525B]">版本号</label>
                <input
                  type="text"
                  required
                  value={cloneVersion}
                  onChange={(e) => setCloneVersion(e.target.value)}
                  className="h-8 w-full rounded-lg border border-[#E8E6E1] bg-white px-2.5 font-mono text-xs focus:border-[#1E3A5F] focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-[#52525B]">模板名称</label>
                <input
                  type="text"
                  required
                  value={cloneName}
                  onChange={(e) => setCloneName(e.target.value)}
                  className="h-8 w-full rounded-lg border border-[#E8E6E1] bg-white px-2.5 text-xs focus:border-[#1E3A5F] focus:outline-none"
                />
              </div>
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-[#52525B]">模板说明（可选）</label>
              <input
                type="text"
                value={cloneDesc}
                onChange={(e) => setCloneDesc(e.target.value)}
                className="h-8 w-full rounded-lg border border-[#E8E6E1] bg-white px-2.5 text-xs focus:border-[#1E3A5F] focus:outline-none"
              />
            </div>
            {cloneError && <div className="text-xs text-[#B91C1C]">{cloneError}</div>}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setCloneOpen(false)}
                className="h-8 rounded-lg border border-[#E2E0DA] bg-white px-3 text-xs font-medium text-[#52525B] hover:text-[#18181B]"
              >
                取消
              </button>
              <button
                type="submit"
                disabled={cloning}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#1E3A5F] px-3 text-xs font-semibold text-white hover:bg-[#162C49] disabled:opacity-55"
              >
                {cloning && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                <span>创建并切换至此模板</span>
              </button>
            </div>
          </form>
        )}

        {/* Selected Template Details & Rule List */}
        {loading && !ruleSetDetail ? (
          <div className="flex flex-col items-center justify-center rounded-xl border border-[#E8E6E1] bg-white py-16 text-xs text-[#71717A]">
            <Loader2 className="h-5 w-5 animate-spin text-[#1E3A5F]" />
            <span className="mt-2">正在加载模板规则列表...</span>
          </div>
        ) : !ruleSetDetail ? (
          <div className="rounded-xl border border-[#E8E6E1] bg-white py-16 text-center text-xs text-[#71717A]">
            请在左侧选择一个规则模板查看详情
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-[#E8E6E1] bg-white">
            {/* Detail Header */}
            <div className="border-b border-[#ECEAE5] px-5 py-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <SlidersHorizontal className="h-4 w-4 text-[#1E3A5F]" />
                  <h2 className="text-sm font-semibold text-[#18181B]">
                    {ruleSetDetail.name}
                  </h2>
                  {ruleSetDetail.is_default && (
                    <span className="rounded bg-[#EFF4FA] px-1.5 py-0.5 text-[10px] font-medium text-[#1E3A5F]">
                      系统默认
                    </span>
                  )}
                </div>
                <div className="text-xs tabular-nums text-[#71717A]">
                  已启用 <strong className="text-[#18181B]">{enabledCount}</strong> /{' '}
                  {ruleSetDetail.rule_items.length} 条
                </div>
              </div>

              <p className="mt-1 text-xs text-[#71717A]">
                <span className="font-mono text-[11px]">{ruleSetDetail.code}</span> · v
                {ruleSetDetail.version} · {DEGREE_LABELS[ruleSetDetail.degree_level]}
                {ruleSetDetail.description ? ` · ${ruleSetDetail.description}` : ''}
              </p>

              {/* Category filter pills */}
              <div className="mt-3 flex flex-wrap gap-1.5">
                <button
                  type="button"
                  onClick={() => setCategoryFilter('all')}
                  className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${
                    categoryFilter === 'all'
                      ? 'bg-[#1E3A5F] text-white'
                      : 'bg-[#F3F2EE] text-[#52525B] hover:text-[#18181B]'
                  }`}
                >
                  全部（{ruleSetDetail.rule_items.length}）
                </button>
                {categories.map((cat) => (
                  <button
                    key={cat}
                    type="button"
                    onClick={() => setCategoryFilter(cat)}
                    className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${
                      categoryFilter === cat
                        ? 'bg-[#1E3A5F] text-white'
                        : 'bg-[#F3F2EE] text-[#52525B] hover:text-[#18181B]'
                    }`}
                  >
                    {getCategoryLabel(cat)}
                  </button>
                ))}
              </div>
            </div>

            {/* Hairline-divided Rules */}
            <div className="divide-y divide-[#ECEAE5]">
              {visibleItems.map((item) => {
                const isSaving = savingItemId === item.id;
                const isParamsOpen = expandedParamsId === item.id;
                const errMsg = itemErrors[item.id];

                return (
                  <div
                    key={item.id}
                    className={`px-5 py-4 transition-opacity ${
                      item.enabled ? '' : 'bg-[#FAF9F7]/60 opacity-70'
                    }`}
                  >
                    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-xs font-semibold text-[#18181B]">
                            {item.name}
                          </span>
                          <span className="rounded bg-[#F3F2EE] px-1.5 py-0.5 text-[10px] font-medium text-[#52525B]">
                            {getCategoryLabel(item.category)}
                          </span>
                          <span className="rounded border border-[#E8E6E1] px-1.5 py-0.5 text-[10px] text-[#71717A]">
                            {APPLIES_TO_LABELS[item.applies_to]}
                          </span>
                          <span className="font-mono text-[10px] text-[#71717A]">
                            {item.rule_code}
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-[#52525B]">{item.description}</p>
                      </div>

                      <div className="flex shrink-0 items-center gap-2.5">
                        {/* Severity segmented control */}
                        <div className="inline-flex rounded-lg border border-[#E8E6E1] bg-[#F7F7F5] p-0.5 text-[11px]">
                          <button
                            type="button"
                            disabled={isSaving}
                            onClick={() => handleChangeSeverity(item, 'error')}
                            className={`rounded-md px-2 py-0.5 font-medium transition-colors ${
                              item.severity === 'error'
                                ? 'bg-[#FEF2F2] text-[#B91C1C] shadow-2xs'
                                : 'text-[#52525B] hover:text-[#18181B]'
                            }`}
                          >
                            error
                          </button>
                          <button
                            type="button"
                            disabled={isSaving}
                            onClick={() => handleChangeSeverity(item, 'warning')}
                            className={`rounded-md px-2 py-0.5 font-medium transition-colors ${
                              item.severity === 'warning'
                                ? 'bg-[#FFFBEB] text-[#B45309] shadow-2xs'
                                : 'text-[#52525B] hover:text-[#18181B]'
                            }`}
                          >
                            warning
                          </button>
                        </div>

                        {/* Enable toggle */}
                        <button
                          type="button"
                          role="switch"
                          aria-checked={item.enabled}
                          aria-label={`启用或停用规则 ${item.name}`}
                          disabled={isSaving}
                          onClick={() => handleToggleEnabled(item)}
                          className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${
                            item.enabled ? 'bg-[#1E3A5F]' : 'bg-[#D8D5CE]'
                          }`}
                        >
                          <span
                            className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                              item.enabled ? 'translate-x-4.5' : 'translate-x-1'
                            }`}
                          />
                        </button>
                      </div>
                    </div>

                    {/* Params editor toggle */}
                    <div className="mt-2.5 flex items-center justify-between">
                      <button
                        type="button"
                        onClick={() =>
                          setExpandedParamsId((prev) => (prev === item.id ? null : item.id))
                        }
                        className="inline-flex items-center gap-1 text-[11px] font-medium text-[#1E3A5F] hover:underline"
                      >
                        {isParamsOpen ? (
                          <ChevronDown className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5" />
                        )}
                        <span>{isParamsOpen ? '收起参数 (JSON)' : '查看 / 编辑参数 (JSON)'}</span>
                      </button>
                      {isSaving && (
                        <span className="inline-flex items-center gap-1 text-[11px] text-[#71717A]">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          保存中...
                        </span>
                      )}
                    </div>

                    {isParamsOpen && (
                      <div className="mt-2.5 space-y-2 rounded-lg border border-[#E8E6E1] bg-[#FAF9F7] p-3">
                        <textarea
                          rows={6}
                          spellCheck={false}
                          value={paramDrafts[item.id] ?? JSON.stringify(item.params, null, 2)}
                          onChange={(e) =>
                            setParamDrafts((prev) => ({ ...prev, [item.id]: e.target.value }))
                          }
                          className="w-full rounded-lg border border-[#E8E6E1] bg-white p-2.5 font-mono text-[11px] leading-relaxed text-[#18181B] focus:border-[#1E3A5F] focus:outline-none"
                        />
                        <div className="flex items-center justify-end gap-2">
                          <button
                            type="button"
                            onClick={() => {
                              setParamDrafts((prev) => ({
                                ...prev,
                                [item.id]: JSON.stringify(item.params, null, 2),
                              }));
                              setItemErrors((prev) => ({ ...prev, [item.id]: '' }));
                            }}
                            className="h-7 rounded-md border border-[#E2E0DA] bg-white px-2.5 text-[11px] text-[#52525B] hover:text-[#18181B]"
                          >
                            还原
                          </button>
                          <button
                            type="button"
                            disabled={isSaving}
                            onClick={() => handleSaveParams(item)}
                            className="inline-flex h-7 items-center gap-1 rounded-md bg-[#1E3A5F] px-2.5 text-[11px] font-medium text-white hover:bg-[#162C49] disabled:opacity-55"
                          >
                            <Save className="h-3 w-3" />
                            <span>保存参数</span>
                          </button>
                        </div>
                      </div>
                    )}

                    {errMsg && <p className="mt-2 text-[11px] text-[#B91C1C]">{errMsg}</p>}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
