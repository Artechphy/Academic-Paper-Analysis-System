import { useEffect, useMemo, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  CopyPlus,
  Loader2,
  Save,
  SlidersHorizontal,
  X,
} from 'lucide-react';
import { ApiError, createRuleSet, updateRuleItem } from '../api/client';
import type { RuleItemResponse, RuleSetDetail, Severity } from '../types/api';
import {
  APPLIES_TO_LABELS,
  CATEGORY_ORDER,
  DEGREE_LABELS,
  getCategoryLabel,
} from '../utils/format';

interface RuleConfigDrawerProps {
  open: boolean;
  loading: boolean;
  ruleSet: RuleSetDetail | null;
  onClose: () => void;
  onRuleUpdated: (updated: RuleItemResponse) => void;
  onRuleSetCreated: (created: RuleSetDetail) => void;
}

export function RuleConfigDrawer({
  open,
  loading,
  ruleSet,
  onClose,
  onRuleUpdated,
  onRuleSetCreated,
}: RuleConfigDrawerProps) {
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
    if (!ruleSet) return;
    setCategoryFilter('all');
    setItemErrors({});
    setExpandedParamsId(null);
    const nextDrafts: Record<string, string> = {};
    for (const item of ruleSet.rule_items) {
      nextDrafts[item.id] = JSON.stringify(item.params, null, 2);
    }
    setParamDrafts(nextDrafts);
  }, [ruleSet?.id]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  const categories = useMemo(() => {
    if (!ruleSet) return [];
    const present = new Set(ruleSet.rule_items.map((item) => item.category));
    return CATEGORY_ORDER.filter((c) => present.has(c));
  }, [ruleSet]);

  const visibleItems = useMemo(() => {
    if (!ruleSet) return [];
    if (categoryFilter === 'all') return ruleSet.rule_items;
    return ruleSet.rule_items.filter((item) => item.category === categoryFilter);
  }, [ruleSet, categoryFilter]);

  if (!open) return null;

  const openCloneForm = () => {
    if (!ruleSet) return;
    const stamp = Math.floor(Date.now() / 1000)
      .toString()
      .slice(-4);
    setCloneCode(`${ruleSet.code}_custom_${stamp}`);
    setCloneVersion('1.0.0');
    setCloneName(`${ruleSet.name}（自定义）`);
    setCloneDesc(ruleSet.description ?? '');
    setCloneError(null);
    setCloneOpen((prev) => !prev);
  };

  const handleCloneSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!ruleSet || cloning) return;
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
        degree_level: ruleSet.degree_level,
        source_rule_set_id: ruleSet.id,
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

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="fixed inset-0 bg-[#1A2332]/35 backdrop-blur-[1px]"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        aria-label="规则模板配置抽屉"
        className="relative z-10 flex h-full w-full max-w-3xl flex-col border-l border-[#E5E2DC] bg-[#FAF9F6] shadow-2xl"
      >
        {/* Header */}
        <div className="border-b border-[#E5E2DC] bg-white px-5 py-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <SlidersHorizontal className="h-4 w-4 text-[#234B7A]" />
                <h2 className="truncate text-base font-semibold text-[#1A2332]">
                  {ruleSet ? ruleSet.name : '规则配置'}
                </h2>
                {ruleSet?.is_default && (
                  <span className="rounded bg-[#EEF3F9] px-1.5 py-0.5 text-[10px] font-semibold text-[#234B7A]">
                    系统默认
                  </span>
                )}
              </div>
              {ruleSet && (
                <p className="mt-1 text-xs text-[#5A6577]">
                  <span className="font-mono text-[11px]">{ruleSet.code}</span> · v{ruleSet.version} ·{' '}
                  {DEGREE_LABELS[ruleSet.degree_level]} · 共 {ruleSet.rule_items.length} 条规则（已启用{' '}
                  {ruleSet.rule_items.filter((i) => i.enabled).length} 条）
                </p>
              )}
            </div>
            <div className="flex items-center gap-2">
              {ruleSet && (
                <button
                  type="button"
                  onClick={openCloneForm}
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#E5E2DC] bg-[#FAF9F6] px-2.5 text-xs font-medium text-[#1A2332] hover:border-[#234B7A]/40 hover:bg-[#EEF3F9]"
                >
                  <CopyPlus className="h-3.5 w-3.5 text-[#234B7A]" />
                  <span>克隆模板</span>
                </button>
              )}
              <button
                type="button"
                onClick={onClose}
                aria-label="关闭规则配置抽屉"
                className="rounded-lg p-1.5 text-[#5A6577] hover:bg-[#FAF9F6] hover:text-[#1A2332]"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
          </div>

          {/* Clone template inline form */}
          {cloneOpen && ruleSet && (
            <form
              onSubmit={handleCloneSubmit}
              className="mt-3 space-y-2.5 rounded-xl border border-[#234B7A]/25 bg-[#EEF3F9]/50 p-3.5 text-xs"
            >
              <div className="font-semibold text-[#1A2332]">
                从「{ruleSet.name}」克隆创建自定义规则模板
              </div>
              <div className="grid gap-2 sm:grid-cols-3">
                <div>
                  <label className="mb-1 block text-[11px] text-[#5A6577]">模板编号 (code)</label>
                  <input
                    type="text"
                    required
                    value={cloneCode}
                    onChange={(e) => setCloneCode(e.target.value)}
                    className="h-8 w-full rounded-md border border-[#E5E2DC] bg-white px-2.5 font-mono text-xs focus:border-[#234B7A] focus:outline-none"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-[#5A6577]">版本号</label>
                  <input
                    type="text"
                    required
                    value={cloneVersion}
                    onChange={(e) => setCloneVersion(e.target.value)}
                    className="h-8 w-full rounded-md border border-[#E5E2DC] bg-white px-2.5 font-mono text-xs focus:border-[#234B7A] focus:outline-none"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-[#5A6577]">模板名称</label>
                  <input
                    type="text"
                    required
                    value={cloneName}
                    onChange={(e) => setCloneName(e.target.value)}
                    className="h-8 w-full rounded-md border border-[#E5E2DC] bg-white px-2.5 text-xs focus:border-[#234B7A] focus:outline-none"
                  />
                </div>
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-[#5A6577]">模板说明（可选）</label>
                <input
                  type="text"
                  value={cloneDesc}
                  onChange={(e) => setCloneDesc(e.target.value)}
                  className="h-8 w-full rounded-md border border-[#E5E2DC] bg-white px-2.5 text-xs focus:border-[#234B7A] focus:outline-none"
                />
              </div>
              {cloneError && <div className="text-xs text-[#B91C1C]">{cloneError}</div>}
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setCloneOpen(false)}
                  className="h-7 rounded-md border border-[#E5E2DC] bg-white px-3 text-xs text-[#5A6577] hover:text-[#1A2332]"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={cloning}
                  className="inline-flex h-7 items-center gap-1.5 rounded-md bg-[#234B7A] px-3 text-xs font-medium text-white hover:bg-[#1B3B61] disabled:opacity-55"
                >
                  {cloning && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  <span>创建并切换至此模板</span>
                </button>
              </div>
            </form>
          )}

          {/* Category filter bar */}
          {ruleSet && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              <button
                type="button"
                onClick={() => setCategoryFilter('all')}
                className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
                  categoryFilter === 'all'
                    ? 'bg-[#234B7A] text-white'
                    : 'bg-[#FAF9F6] text-[#5A6577] hover:text-[#1A2332]'
                }`}
              >
                全部（{ruleSet.rule_items.length}）
              </button>
              {categories.map((cat) => (
                <button
                  key={cat}
                  type="button"
                  onClick={() => setCategoryFilter(cat)}
                  className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
                    categoryFilter === cat
                      ? 'bg-[#234B7A] text-white'
                      : 'bg-[#FAF9F6] text-[#5A6577] hover:text-[#1A2332]'
                  }`}
                >
                  {getCategoryLabel(cat)}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Rule items list */}
        <div className="flex-1 space-y-2.5 overflow-y-auto p-5">
          {loading && !ruleSet ? (
            <div className="flex flex-col items-center justify-center py-16 text-xs text-[#5A6577]">
              <Loader2 className="h-6 w-6 animate-spin text-[#234B7A]" />
              <span className="mt-2">正在加载模板规则列表...</span>
            </div>
          ) : (
            visibleItems.map((item) => {
              const isSaving = savingItemId === item.id;
              const isParamsOpen = expandedParamsId === item.id;
              const errMsg = itemErrors[item.id];

              return (
                <div
                  key={item.id}
                  className={`rounded-xl border bg-white p-4 shadow-2xs transition-opacity ${
                    item.enabled ? 'border-[#E5E2DC]' : 'border-[#E5E2DC]/70 opacity-75'
                  }`}
                >
                  <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs font-semibold text-[#1A2332]">{item.name}</span>
                        <span className="rounded bg-[#FAF9F6] px-1.5 py-0.5 text-[10px] text-[#5A6577]">
                          {getCategoryLabel(item.category)}
                        </span>
                        <span className="rounded border border-[#E5E2DC] px-1.5 py-0.5 text-[10px] text-[#5A6577]">
                          {APPLIES_TO_LABELS[item.applies_to]}
                        </span>
                        <span className="font-mono text-[10px] text-[#8791A1]">{item.rule_code}</span>
                      </div>
                      <p className="mt-1 text-xs text-[#5A6577]">{item.description}</p>
                    </div>

                    <div className="flex shrink-0 items-center gap-2">
                      {/* Severity segmented control */}
                      <div className="inline-flex rounded-lg border border-[#E5E2DC] bg-[#FAF9F6] p-0.5 text-[11px]">
                        <button
                          type="button"
                          disabled={isSaving}
                          onClick={() => handleChangeSeverity(item, 'error')}
                          className={`rounded-md px-2 py-0.5 font-medium transition-colors ${
                            item.severity === 'error'
                              ? 'bg-[#FEF2F2] text-[#B91C1C] shadow-2xs'
                              : 'text-[#5A6577] hover:text-[#1A2332]'
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
                              : 'text-[#5A6577] hover:text-[#1A2332]'
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
                          item.enabled ? 'bg-[#234B7A]' : 'bg-[#D5D0C7]'
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
                  <div className="mt-2.5 flex items-center justify-between border-t border-[#EFECE6] pt-2">
                    <button
                      type="button"
                      onClick={() => setExpandedParamsId((prev) => (prev === item.id ? null : item.id))}
                      className="inline-flex items-center gap-1 text-[11px] font-medium text-[#234B7A] hover:underline"
                    >
                      {isParamsOpen ? (
                        <ChevronDown className="h-3.5 w-3.5" />
                      ) : (
                        <ChevronRight className="h-3.5 w-3.5" />
                      )}
                      <span>{isParamsOpen ? '收起参数配置 (JSON)' : '查看 / 编辑参数 (JSON)'}</span>
                    </button>
                    {isSaving && (
                      <span className="inline-flex items-center gap-1 text-[11px] text-[#5A6577]">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        保存中...
                      </span>
                    )}
                  </div>

                  {isParamsOpen && (
                    <div className="mt-2 space-y-2">
                      <textarea
                        rows={6}
                        spellCheck={false}
                        value={paramDrafts[item.id] ?? JSON.stringify(item.params, null, 2)}
                        onChange={(e) =>
                          setParamDrafts((prev) => ({ ...prev, [item.id]: e.target.value }))
                        }
                        className="w-full rounded-lg border border-[#E5E2DC] bg-[#FAF9F6] p-2.5 font-mono text-[11px] leading-relaxed text-[#1A2332] focus:border-[#234B7A] focus:bg-white focus:outline-none"
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
                          className="h-7 rounded-md border border-[#E5E2DC] bg-white px-2.5 text-[11px] text-[#5A6577] hover:text-[#1A2332]"
                        >
                          还原
                        </button>
                        <button
                          type="button"
                          disabled={isSaving}
                          onClick={() => handleSaveParams(item)}
                          className="inline-flex h-7 items-center gap-1 rounded-md bg-[#234B7A] px-2.5 text-[11px] font-medium text-white hover:bg-[#1B3B61] disabled:opacity-55"
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
            })
          )}
        </div>
      </aside>
    </div>
  );
}
