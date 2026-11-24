import { useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  ChevronDown,
  Columns2,
  Download,
  FileCheck,
  FileDown,
  Loader2,
  Settings2,
  Sparkles,
  Square,
} from 'lucide-react';
import {
  autoFixRevision,
  editRevisionParagraph,
  exportAnnotatedPdf,
  getRevisionDownloadUrl,
  updateDocumentSettings,
} from '../api/revisions';
import { ApiError } from '../api/client';
import type { ViolationResponse } from '../types/api';
import type {
  PageMode,
  ParagraphDiff,
  ParagraphEditRequest,
  RevisionSessionDetail,
} from '../types/revisions';
import { formatScore } from '../utils/format';
import { DocxReaderEditor } from './DocxReaderEditor';
import { RulebookPanel } from './RulebookPanel';
import { VerdictBadge } from './VerdictBadge';

interface RevisionWorkspaceProps {
  session: RevisionSessionDetail;
  onSessionChange: (updated: RevisionSessionDetail) => void;
  onBack: () => void;
  onNotify: (kind: 'success' | 'error', message: string) => void;
}

function buildViolationMap(violations: ViolationResponse[]): Map<number, ViolationResponse[]> {
  const map = new Map<number, ViolationResponse[]>();
  for (const v of violations) {
    const indices = new Set<number>();
    const loc = v.location ?? {};
    if (typeof loc.paragraph_index === 'number') {
      indices.add(loc.paragraph_index);
    }
    if (Array.isArray(loc.paragraph_indices)) {
      for (const idx of loc.paragraph_indices) {
        if (typeof idx === 'number') indices.add(idx);
      }
    }
    for (const idx of indices) {
      const list = map.get(idx);
      if (list) list.push(v);
      else map.set(idx, [v]);
    }
  }
  return map;
}

function triggerFileDownload(url: string) {
  const link = document.createElement('a');
  link.href = url;
  link.download = '';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

export function RevisionWorkspace({
  session,
  onSessionChange,
  onBack,
  onNotify,
}: RevisionWorkspaceProps) {
  const [viewMode, setViewMode] = useState<'single' | 'dual'>(
    session.comparison_ready ? 'dual' : 'single',
  );
  const [selectedParagraphIndex, setSelectedParagraphIndex] = useState<number | null>(null);
  const [highlightedRuleCode, setHighlightedRuleCode] = useState<string | null>(null);
  const [savingParagraphIndex, setSavingParagraphIndex] = useState<number | null>(null);
  const [lastResolvedBanner, setLastResolvedBanner] = useState<{
    paragraphIndex: number;
    resolvedCount: number;
    remainingCount: number;
  } | null>(null);

  // Header Popovers
  const [activePopover, setActivePopover] = useState<'settings' | 'export' | null>(null);

  const hasGlobalLayoutIssues = session.rulebook.some(
    (r) =>
      r.status === 'open' &&
      ['FILE_NAME_PATTERN', 'PAGE_SIZE_A4', 'PAGE_MARGINS', 'HEADER_FORMAT'].includes(
        r.rule_code,
      ),
  );
  const [targetFileName, setTargetFileName] = useState(session.target_file_name);
  const [savingDocSettings, setSavingDocSettings] = useState(false);

  // Auto-fix & feedback
  const [runningAutoFix, setRunningAutoFix] = useState(false);
  const [fixingRuleCode, setFixingRuleCode] = useState<string | null>(null);
  const [instruction, setInstruction] = useState('');

  // Export LaTeX bubble PDF
  const [pageMode, setPageMode] = useState<PageMode>('issues_only');
  const [exportingPdf, setExportingPdf] = useState(false);

  useEffect(() => {
    setTargetFileName(session.target_file_name);
  }, [session.target_file_name]);

  useEffect(() => {
    if (!activePopover) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setActivePopover(null);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [activePopover]);

  const violationsByParagraph = useMemo(
    () => buildViolationMap(session.violations),
    [session.violations],
  );

  const diffMap = useMemo(() => {
    const map = new Map<number, ParagraphDiff>();
    for (const diff of session.changes) {
      map.set(diff.paragraph_index, diff);
    }
    return map;
  }, [session.changes]);

  const modifiedSet = useMemo(
    () => new Set(session.modified_paragraphs),
    [session.modified_paragraphs],
  );

  const [focusTarget, setFocusTarget] = useState<{
    paragraphIndex: number;
    seq: number;
  } | null>(null);

  const scrollToParagraph = (paragraphIndex: number) => {
    setFocusTarget((prev) => ({
      paragraphIndex,
      seq: (prev?.seq ?? 0) + 1,
    }));
  };

  const handleJumpToParagraph = (paragraphIndex: number, ruleCode: string) => {
    setHighlightedRuleCode(ruleCode);
    setSelectedParagraphIndex(session.editable ? paragraphIndex : null);
    scrollToParagraph(paragraphIndex);
  };

  const handleJumpToChange = (paragraphIndex: number) => {
    setSelectedParagraphIndex(session.editable ? paragraphIndex : null);
    scrollToParagraph(paragraphIndex);
  };

  const handleSaveParagraph = async (index: number, payload: ParagraphEditRequest) => {
    setSavingParagraphIndex(index);
    try {
      const res = await editRevisionParagraph(session.id, index, payload);
      const nextParagraphs = session.current_paragraphs.map((p) =>
        p.index === index ? res.paragraph : p,
      );
      const filteredViolations = session.violations.filter((v) => {
        const loc = v.location ?? {};
        const matchesSingle = loc.paragraph_index === index;
        const matchesList =
          Array.isArray(loc.paragraph_indices) && loc.paragraph_indices.includes(index);
        return !matchesSingle && !matchesList;
      });

      onSessionChange({
        ...session,
        current_paragraphs: nextParagraphs,
        violations: [...filteredViolations, ...res.paragraph_violations],
        verdict: res.verdict,
        score: res.score,
        error_count: res.error_count,
        warning_count: res.warning_count,
        rulebook: res.rulebook,
        changes: res.changes,
        modified_paragraphs: res.modified_paragraphs,
        version: res.version,
        annotated_pdf_ready: false,
        annotated_page_mode: null,
      });

      setLastResolvedBanner({
        paragraphIndex: index,
        resolvedCount: res.resolved_count,
        remainingCount: res.remaining_count,
      });
      setSelectedParagraphIndex(null);
      if (res.resolved_count > 0) {
        onNotify('success', `第 ${index + 1} 段增量重判完成：已消除 ${res.resolved_count} 处错误`);
      } else {
        onNotify('success', `已更新第 ${index + 1} 段（当前得分 ${formatScore(res.score)}）`);
      }
    } catch (err) {
      onNotify('error', err instanceof ApiError ? err.message : '保存段落并重判失败');
    } finally {
      setSavingParagraphIndex(null);
    }
  };

  const handleRevertParagraph = async (index: number) => {
    await handleSaveParagraph(index, { revert: true });
  };

  const handleDocumentSettings = async (patch: {
    target_file_name?: string;
    fix_page_size_a4?: boolean;
    fix_margins?: boolean;
    fix_headers?: boolean;
  }) => {
    setSavingDocSettings(true);
    try {
      const updated = await updateDocumentSettings(session.id, patch);
      onSessionChange(updated);
      onNotify('success', '已更新文档级页面/文件名规范并重新判定');
    } catch (err) {
      onNotify('error', err instanceof ApiError ? err.message : '更新文档设置失败');
    } finally {
      setSavingDocSettings(false);
    }
  };

  const handleAutoFix = async (options?: {
    instruction?: string;
    ruleCodes?: string[];
  }) => {
    setRunningAutoFix(true);
    if (options?.ruleCodes?.length === 1) {
      setFixingRuleCode(options.ruleCodes[0]);
    }
    try {
      const updated = await autoFixRevision(session.id, {
        instruction: options?.instruction ?? null,
        rule_codes: options?.ruleCodes ?? null,
      });
      onSessionChange(updated);
      if (updated.comparison_ready) {
        setViewMode('dual');
      }
      if (options?.instruction) {
        setInstruction('');
      }
      setLastResolvedBanner(null);
      const fixedDelta = Math.max(0, session.error_count - updated.error_count);
      onNotify(
        'success',
        updated.editable
          ? `Agent 修复完成（v${updated.version}）：错误 ${session.error_count} → ${updated.error_count}${fixedDelta > 0 ? `，共消除 ${fixedDelta} 处` : ''}`
          : `已生成修订建议与文本对照（v${updated.version}）`,
      );
    } catch (err) {
      onNotify('error', err instanceof ApiError ? err.message : '一键修订执行失败');
    } finally {
      setRunningAutoFix(false);
      setFixingRuleCode(null);
    }
  };

  const handleExportPdf = async () => {
    setExportingPdf(true);
    try {
      const res = await exportAnnotatedPdf(session.id, pageMode);
      onSessionChange({
        ...session,
        annotated_pdf_ready: res.annotated_pdf_ready,
        annotated_page_mode: res.page_mode,
      });
      triggerFileDownload(res.download_url);
      onNotify(
        'success',
        `LaTeX 气泡批注 PDF 编译完成（共 ${res.page_count} 页），已开始下载`,
      );
    } catch (err) {
      onNotify('error', err instanceof ApiError ? err.message : '导出 LaTeX 气泡批注 PDF 失败');
    } finally {
      setExportingPdf(false);
    }
  };

  const latestAgentFeedback = [...session.feedbacks]
    .reverse()
    .find((fb) => fb.author === 'agent');

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-[#F5F5F2] text-[#18181B]">
      {/* Strict Single-Row 52px Studio Header */}
      <header className="relative z-30 flex h-[52px] shrink-0 items-center justify-between gap-3 border-b border-[#E8E6E1] bg-white px-4">
        {/* Left: Back + Doc Identity + Score/Error Delta */}
        <div className="flex min-w-0 items-center gap-2.5">
          <button
            type="button"
            onClick={onBack}
            className="inline-flex h-7 shrink-0 items-center gap-1 rounded-md px-2 text-xs font-medium text-[#52525B] transition-colors hover:bg-[#F3F2EE] hover:text-[#18181B]"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            <span>返回</span>
          </button>

          <div className="h-4 w-px shrink-0 bg-[#ECEAE5]" />

          <h1
            className="max-w-[180px] truncate text-xs font-semibold text-[#18181B] sm:max-w-[260px]"
            title={session.target_file_name}
          >
            {session.target_file_name}
          </h1>

          <span className="hidden rounded bg-[#EFF4FA] px-1.5 py-0.5 font-mono text-[10px] font-semibold text-[#1E3A5F] sm:inline-block">
            v{session.version}
          </span>

          <VerdictBadge verdict={session.verdict} compact />

          <div className="hidden items-center gap-1.5 text-[11px] tabular-nums text-[#71717A] md:flex">
            <span>{formatScore(session.score)} 分</span>
            <span>·</span>
            <span className={session.error_count === 0 ? 'text-[#15803D]' : 'text-[#B91C1C]'}>
              {session.original_error_count}→{session.error_count} 错误
            </span>
          </div>
        </div>

        {/* Center: 2-Way Segmented Mode Toggle */}
        <div className="hidden rounded-lg border border-[#E8E6E1] bg-[#F7F7F5] p-0.5 text-xs md:inline-flex">
          <button
            type="button"
            onClick={() => setViewMode('single')}
            className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${
              viewMode === 'single'
                ? 'bg-white text-[#18181B] shadow-2xs'
                : 'text-[#52525B] hover:text-[#18181B]'
            }`}
          >
            <Square className="h-3 w-3" />
            <span>编校</span>
          </button>
          <button
            type="button"
            onClick={() => setViewMode('dual')}
            className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${
              viewMode === 'dual'
                ? 'bg-white text-[#18181B] shadow-2xs'
                : 'text-[#52525B] hover:text-[#18181B]'
            }`}
          >
            <Columns2 className="h-3 w-3" />
            <span>对照</span>
          </button>
        </div>

        {/* Right: Max 3 Controls (Page Settings Popover + Single Primary CTA + Export Popover) */}
        <div className="flex shrink-0 items-center gap-2">
          {session.editable && (
            <div className="relative">
              <button
                type="button"
                onClick={() =>
                  setActivePopover((prev) => (prev === 'settings' ? null : 'settings'))
                }
                className={`relative inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition-colors ${
                  activePopover === 'settings'
                    ? 'border-[#1E3A5F] bg-[#EFF4FA] text-[#1E3A5F]'
                    : 'border-[#E2E0DA] bg-white text-[#18181B] hover:bg-[#F7F7F5]'
                }`}
              >
                <Settings2 className="h-3.5 w-3.5 text-[#52525B]" />
                <span className="hidden sm:inline">页面设置</span>
                {hasGlobalLayoutIssues && (
                  <span
                    aria-label="存在全局页面或文件名问题"
                    className="h-1.5 w-1.5 rounded-full bg-[#DC2626]"
                  />
                )}
              </button>

              {activePopover === 'settings' && (
                <>
                  <div
                    className="fixed inset-0 z-30"
                    onClick={() => setActivePopover(null)}
                    aria-hidden="true"
                  />
                  <div className="absolute top-10 right-0 z-40 w-80 rounded-xl border border-[#E8E6E1] bg-white p-3.5 shadow-xl">
                    <div className="text-xs font-semibold text-[#18181B]">文档级页面与文件名规范</div>
                    <p className="mt-0.5 text-[11px] text-[#71717A]">
                      修改后立即写回 DOCX 并触发全篇重判
                    </p>

                    <div className="mt-3 space-y-2.5">
                      <div>
                        <label
                          htmlFor="popover-target-file-name"
                          className="mb-1 block text-[11px] font-medium text-[#52525B]"
                        >
                          导出文件名
                        </label>
                        <div className="flex gap-1.5">
                          <input
                            id="popover-target-file-name"
                            type="text"
                            value={targetFileName}
                            onChange={(e) => setTargetFileName(e.target.value)}
                            placeholder="学号_姓名.docx"
                            className="h-8 min-w-0 flex-1 rounded-lg border border-[#E8E6E1] bg-[#FAF9F7] px-2.5 text-xs text-[#18181B] focus:border-[#1E3A5F] focus:bg-white focus:outline-none"
                          />
                          <button
                            type="button"
                            disabled={savingDocSettings}
                            onClick={() =>
                              void handleDocumentSettings({ target_file_name: targetFileName })
                            }
                            className="h-8 shrink-0 rounded-lg border border-[#E2E0DA] bg-white px-2.5 text-[11px] font-medium text-[#18181B] hover:bg-[#F7F7F5] disabled:opacity-50"
                          >
                            应用
                          </button>
                        </div>
                      </div>

                      <div className="space-y-1.5 border-t border-[#ECEAE5] pt-2.5">
                        <button
                          type="button"
                          disabled={savingDocSettings}
                          onClick={() => void handleDocumentSettings({ fix_page_size_a4: true })}
                          className="flex h-8 w-full items-center justify-between rounded-lg border border-[#E8E6E1] bg-[#FAF9F7] px-3 text-xs font-medium text-[#18181B] hover:border-[#1E3A5F]/40 hover:bg-[#EFF4FA]/60 disabled:opacity-50"
                        >
                          <span>设为标准 A4 纸张</span>
                          <span className="text-[10px] text-[#1E3A5F]">应用</span>
                        </button>
                        <button
                          type="button"
                          disabled={savingDocSettings}
                          onClick={() => void handleDocumentSettings({ fix_margins: true })}
                          className="flex h-8 w-full items-center justify-between rounded-lg border border-[#E8E6E1] bg-[#FAF9F7] px-3 text-xs font-medium text-[#18181B] hover:border-[#1E3A5F]/40 hover:bg-[#EFF4FA]/60 disabled:opacity-50"
                        >
                          <span>一键规范页面边距</span>
                          <span className="text-[10px] text-[#1E3A5F]">应用</span>
                        </button>
                        <button
                          type="button"
                          disabled={savingDocSettings}
                          onClick={() => void handleDocumentSettings({ fix_headers: true })}
                          className="flex h-8 w-full items-center justify-between rounded-lg border border-[#E8E6E1] bg-[#FAF9F7] px-3 text-xs font-medium text-[#18181B] hover:border-[#1E3A5F]/40 hover:bg-[#EFF4FA]/60 disabled:opacity-50"
                        >
                          <span>一键修复页眉与双横线</span>
                          <span className="text-[10px] text-[#1E3A5F]">应用</span>
                        </button>
                      </div>
                    </div>
                  </div>
                </>
              )}
            </div>
          )}

          {/* Single Primary CTA */}
          <button
            type="button"
            disabled={runningAutoFix}
            onClick={() => void handleAutoFix()}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#1E3A5F] px-3 text-xs font-semibold text-white transition-colors hover:bg-[#162C49] disabled:opacity-55"
          >
            {runningAutoFix ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            <span>{runningAutoFix ? '修复中...' : '一键修复'}</span>
          </button>

          {/* Unified Export Popover */}
          <div className="relative">
            <button
              type="button"
              onClick={() =>
                setActivePopover((prev) => (prev === 'export' ? null : 'export'))
              }
              className={`inline-flex h-8 items-center gap-1 rounded-lg border px-2.5 text-xs font-medium transition-colors ${
                activePopover === 'export'
                  ? 'border-[#1E3A5F] bg-[#EFF4FA] text-[#1E3A5F]'
                  : 'border-[#E2E0DA] bg-white text-[#18181B] hover:bg-[#F7F7F5]'
              }`}
            >
              <span>导出</span>
              <ChevronDown className="h-3.5 w-3.5 text-[#71717A]" />
            </button>

            {activePopover === 'export' && (
              <>
                <div
                  className="fixed inset-0 z-30"
                  onClick={() => setActivePopover(null)}
                  aria-hidden="true"
                />
                <div className="absolute top-10 right-0 z-40 w-72 rounded-xl border border-[#E8E6E1] bg-white p-3 shadow-xl">
                  {session.editable && (
                    <div className="border-b border-[#ECEAE5] pb-2.5">
                      <div className="mb-1.5 text-[11px] font-medium text-[#71717A]">
                        修订文档下载
                      </div>
                      <a
                        href={getRevisionDownloadUrl(session.id, 'docx')}
                        download={session.target_file_name}
                        onClick={() => setActivePopover(null)}
                        className="flex h-8 w-full items-center justify-center gap-1.5 rounded-lg border border-[#BBF7D0] bg-[#ECFDF5] px-3 text-xs font-semibold text-[#15803D] hover:bg-[#D1FAE5]"
                      >
                        <Download className="h-3.5 w-3.5" />
                        <span>下载修订 DOCX</span>
                      </a>
                    </div>
                  )}

                  <div className={session.editable ? 'pt-2.5' : ''}>
                    <div className="text-[11px] font-medium text-[#71717A]">
                      LaTeX 气泡批注 PDF
                    </div>
                    <div className="mt-1.5 grid grid-cols-2 rounded-lg border border-[#E8E6E1] bg-[#F7F7F5] p-0.5 text-[11px]">
                      <button
                        type="button"
                        onClick={() => setPageMode('issues_only')}
                        className={`rounded-md py-1 font-medium transition-colors ${
                          pageMode === 'issues_only'
                            ? 'bg-white text-[#18181B] shadow-2xs'
                            : 'text-[#52525B] hover:text-[#18181B]'
                        }`}
                      >
                        仅问题页
                      </button>
                      <button
                        type="button"
                        onClick={() => setPageMode('full')}
                        className={`rounded-md py-1 font-medium transition-colors ${
                          pageMode === 'full'
                            ? 'bg-white text-[#18181B] shadow-2xs'
                            : 'text-[#52525B] hover:text-[#18181B]'
                        }`}
                      >
                        完整论文
                      </button>
                    </div>

                    <button
                      type="button"
                      disabled={exportingPdf}
                      onClick={() => void handleExportPdf()}
                      className="mt-2 flex h-8 w-full items-center justify-center gap-1.5 rounded-lg border border-[#E2E0DA] bg-white px-3 text-xs font-semibold text-[#18181B] hover:bg-[#F7F7F5] disabled:opacity-55"
                    >
                      {exportingPdf ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-[#1E3A5F]" />
                      ) : (
                        <FileDown className="h-3.5 w-3.5 text-[#1E3A5F]" />
                      )}
                      <span>{exportingPdf ? 'XeLaTeX 编译中...' : '编译并导出 PDF'}</span>
                    </button>

                    {session.annotated_pdf_ready && (
                      <a
                        href={getRevisionDownloadUrl(session.id, 'annotated_pdf')}
                        download
                        onClick={() => setActivePopover(null)}
                        className="mt-1.5 flex h-7 w-full items-center justify-center gap-1 rounded-md text-[11px] font-medium text-[#15803D] hover:bg-[#ECFDF5]"
                      >
                        <FileCheck className="h-3.5 w-3.5" />
                        <span>下载最新已编译 PDF</span>
                      </a>
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Main Split Area: Paper Canvas (Left) + Unified Review & AI Dock (Right) */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row">
        <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
          {viewMode === 'dual' ? (
            <div className="grid h-full min-h-0 grid-cols-1 divide-y divide-[#E8E6E1] xl:grid-cols-2 xl:divide-x xl:divide-y-0">
              <DocxReaderEditor
                paneId="left"
                title="原稿快照"
                paragraphs={session.original_paragraphs}
                violationsByParagraph={new Map()}
                diffMap={diffMap}
                modifiedSet={modifiedSet}
                editable={false}
                selectedParagraphIndex={null}
                highlightedRuleCode={highlightedRuleCode}
                savingParagraphIndex={null}
                focusTarget={focusTarget}
                onSelectParagraph={() => {}}
              />
              <DocxReaderEditor
                paneId="right"
                title={session.editable ? '修订稿' : '改写建议对照'}
                paragraphs={session.current_paragraphs}
                violationsByParagraph={violationsByParagraph}
                diffMap={diffMap}
                modifiedSet={modifiedSet}
                editable={session.editable}
                selectedParagraphIndex={selectedParagraphIndex}
                highlightedRuleCode={highlightedRuleCode}
                savingParagraphIndex={savingParagraphIndex}
                focusTarget={focusTarget}
                lastResolvedBanner={lastResolvedBanner}
                onSelectParagraph={setSelectedParagraphIndex}
                onSaveParagraph={handleSaveParagraph}
                onRevertParagraph={handleRevertParagraph}
              />
            </div>
          ) : (
            <DocxReaderEditor
              paneId="single"
              title={session.editable ? '论文编校画布' : '论文结构化阅读'}
              paragraphs={session.current_paragraphs}
              violationsByParagraph={violationsByParagraph}
              diffMap={diffMap}
              modifiedSet={modifiedSet}
              editable={session.editable}
              selectedParagraphIndex={selectedParagraphIndex}
              highlightedRuleCode={highlightedRuleCode}
              savingParagraphIndex={savingParagraphIndex}
              focusTarget={focusTarget}
              lastResolvedBanner={lastResolvedBanner}
              onSelectParagraph={setSelectedParagraphIndex}
              onSaveParagraph={handleSaveParagraph}
              onRevertParagraph={handleRevertParagraph}
            />
          )}
        </div>

        {/* Unified Right Review & AI Assistant Dock */}
        <div className="h-[340px] shrink-0 border-t border-[#E8E6E1] lg:h-full lg:w-[360px] lg:border-t-0 lg:border-l xl:w-[390px]">
          <RulebookPanel
            rulebook={session.rulebook}
            changes={session.changes}
            editable={session.editable}
            activeRuleCode={highlightedRuleCode}
            fixingRuleCode={fixingRuleCode}
            instruction={instruction}
            runningAutoFix={runningAutoFix}
            latestAgentFeedback={latestAgentFeedback}
            onInstructionChange={setInstruction}
            onSubmitInstruction={(text) => void handleAutoFix({ instruction: text })}
            onJumpToParagraph={handleJumpToParagraph}
            onJumpToChange={handleJumpToChange}
            onSelectRule={setHighlightedRuleCode}
            onFixSingleRule={(ruleCode) => handleAutoFix({ ruleCodes: [ruleCode] })}
          />
        </div>
      </div>
    </div>
  );
}
