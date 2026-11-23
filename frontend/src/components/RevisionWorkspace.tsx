import { useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  Columns2,
  Download,
  FileCheck,
  FileDown,
  Loader2,
  MessageSquarePlus,
  Send,
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

  // Document settings strip
  const hasGlobalLayoutIssues = session.rulebook.some(
    (r) =>
      r.status === 'open' &&
      ['FILE_NAME_PATTERN', 'PAGE_SIZE_A4', 'PAGE_MARGINS', 'HEADER_FORMAT'].includes(
        r.rule_code,
      ),
  );
  const [docSettingsOpen, setDocSettingsOpen] = useState(
    session.editable && hasGlobalLayoutIssues,
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

  // Collapsible changes summary
  const [changesExpanded, setChangesExpanded] = useState(false);

  useEffect(() => {
    setTargetFileName(session.target_file_name);
  }, [session.target_file_name]);

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
    <div className="flex h-[calc(100vh-88px)] min-h-[640px] flex-col gap-3">
      {/* Top Sticky Action Bar */}
      <div className="rounded-xl border border-[#E5E2DC] bg-white px-4 py-3 shadow-[0_1px_2px_rgba(26,35,50,0.04)]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 flex-wrap items-center gap-2.5">
            <button
              type="button"
              onClick={onBack}
              className="inline-flex h-8 items-center gap-1 rounded-lg border border-[#E5E2DC] bg-[#FAF9F6] px-2.5 text-xs font-medium text-[#1A2332] hover:bg-[#EFECE6]"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              <span>返回列表</span>
            </button>

            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="max-w-[280px] truncate text-sm font-semibold text-[#1A2332]" title={session.target_file_name}>
                  {session.target_file_name}
                </h2>
                <span className="rounded border border-[#E5E2DC] bg-[#FAF9F6] px-1.5 py-0.5 text-[10px] font-medium text-[#5A6577]">
                  {session.editable ? 'DOCX 在线编校' : 'PDF 只读建议'}
                </span>
                <span className="rounded bg-[#EEF3F9] px-1.5 py-0.5 font-mono text-[10px] font-semibold text-[#234B7A]">
                  v{session.version}
                </span>
                <VerdictBadge verdict={session.verdict} compact />
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] tabular-nums text-[#5A6577]">
                <span>
                  合规分 <strong className="text-[#1A2332]">{formatScore(session.score)}</strong>
                </span>
                <span>·</span>
                <span>
                  错误数{' '}
                  <strong className={session.error_count === 0 ? 'text-[#15803D]' : 'text-[#B91C1C]'}>
                    {session.original_error_count} → {session.error_count}
                  </strong>
                </span>
                {session.changes.length > 0 && (
                  <>
                    <span>·</span>
                    <button
                      type="button"
                      onClick={() => setChangesExpanded((prev) => !prev)}
                      className="font-medium text-[#234B7A] hover:underline"
                    >
                      已修改 {session.changes.length} 段（点击{changesExpanded ? '收起' : '查看对照列表'}）
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* View Mode Toggle */}
            <div className="inline-flex rounded-lg border border-[#E5E2DC] bg-[#FAF9F6] p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setViewMode('single')}
                className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 font-medium transition-colors ${
                  viewMode === 'single'
                    ? 'bg-white text-[#1A2332] shadow-2xs'
                    : 'text-[#5A6577] hover:text-[#1A2332]'
                }`}
              >
                <Square className="h-3 w-3" />
                <span>单栏编校</span>
              </button>
              <button
                type="button"
                onClick={() => setViewMode('dual')}
                className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 font-medium transition-colors ${
                  viewMode === 'dual'
                    ? 'bg-white text-[#1A2332] shadow-2xs'
                    : 'text-[#5A6577] hover:text-[#1A2332]'
                }`}
              >
                <Columns2 className="h-3.5 w-3.5" />
                <span>左右双重对照</span>
              </button>
            </div>

            {session.editable && (
              <button
                type="button"
                onClick={() => setDocSettingsOpen((prev) => !prev)}
                className={`inline-flex h-8 items-center gap-1 rounded-lg border px-2.5 text-xs font-medium transition-colors ${
                  docSettingsOpen
                    ? 'border-[#234B7A] bg-[#EEF3F9] text-[#234B7A]'
                    : 'border-[#E5E2DC] bg-white text-[#5A6577] hover:text-[#1A2332]'
                }`}
              >
                <Settings2 className="h-3.5 w-3.5" />
                <span>页面/文件名</span>
              </button>
            )}

            {/* One-Click Agent Auto-Fix */}
            <button
              type="button"
              disabled={runningAutoFix}
              onClick={() => void handleAutoFix()}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#234B7A] px-3 text-xs font-semibold text-white shadow-xs hover:bg-[#1B3B61] disabled:opacity-55"
            >
              {runningAutoFix ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Sparkles className="h-3.5 w-3.5" />
              )}
              <span>{runningAutoFix ? 'Agent 修复中...' : '一键修改（Agent 修复）'}</span>
            </button>

            {/* Download Revised DOCX */}
            {session.editable && (
              <a
                href={getRevisionDownloadUrl(session.id, 'docx')}
                download={session.target_file_name}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#15803D]/30 bg-[#ECFDF5] px-3 text-xs font-semibold text-[#15803D] hover:bg-[#D1FAE5]"
              >
                <Download className="h-3.5 w-3.5" />
                <span>下载修订 DOCX</span>
              </a>
            )}

            {/* Export LaTeX Bubble PDF */}
            <div className="inline-flex items-center rounded-lg border border-[#E5E2DC] bg-[#FAF9F6] p-0.5">
              <select
                aria-label="批注 PDF 页码模式"
                value={pageMode}
                onChange={(e) => setPageMode(e.target.value as PageMode)}
                className="h-7 bg-transparent px-1.5 text-[11px] font-medium text-[#5A6577] focus:outline-none"
              >
                <option value="issues_only">仅问题页</option>
                <option value="full">完整论文</option>
              </select>
              <button
                type="button"
                disabled={exportingPdf}
                onClick={() => void handleExportPdf()}
                className="inline-flex h-7 items-center gap-1 rounded-md bg-white px-2.5 text-[11px] font-semibold text-[#1A2332] shadow-2xs hover:bg-[#EEF3F9] hover:text-[#234B7A] disabled:opacity-55"
              >
                {exportingPdf ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-[#234B7A]" />
                ) : (
                  <FileDown className="h-3.5 w-3.5 text-[#234B7A]" />
                )}
                <span>{exportingPdf ? 'XeLaTeX 编译中...' : '导出气泡批注 PDF'}</span>
              </button>
              {session.annotated_pdf_ready && (
                <a
                  href={getRevisionDownloadUrl(session.id, 'annotated_pdf')}
                  download
                  title="下载已编译的最新气泡批注 PDF"
                  className="ml-1 inline-flex h-7 items-center gap-1 rounded-md px-2 text-[11px] font-medium text-[#15803D] hover:bg-[#ECFDF5]"
                >
                  <FileCheck className="h-3.5 w-3.5" />
                  <span>下载 PDF</span>
                </a>
              )}
            </div>
          </div>
        </div>

        {/* Collapsible Document-Level Settings Bar */}
        {session.editable && docSettingsOpen && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2.5 rounded-lg border border-[#E5E2DC] bg-[#FAF9F6] px-3 py-2 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <label htmlFor="target-file-name" className="text-[11px] font-medium text-[#5A6577]">
                导出文件名
              </label>
              <input
                id="target-file-name"
                type="text"
                value={targetFileName}
                onChange={(e) => setTargetFileName(e.target.value)}
                placeholder="学号_姓名.docx"
                className="h-7 w-56 rounded-md border border-[#E5E2DC] bg-white px-2 text-xs text-[#1A2332] focus:border-[#234B7A] focus:outline-none"
              />
              <button
                type="button"
                disabled={savingDocSettings}
                onClick={() => void handleDocumentSettings({ target_file_name: targetFileName })}
                className="h-7 rounded-md border border-[#E5E2DC] bg-white px-2.5 text-[11px] font-medium text-[#1A2332] hover:border-[#234B7A] disabled:opacity-50"
              >
                应用文件名
              </button>
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              <button
                type="button"
                disabled={savingDocSettings}
                onClick={() => void handleDocumentSettings({ fix_page_size_a4: true })}
                className="h-7 rounded-md border border-[#E5E2DC] bg-white px-2.5 text-[11px] font-medium text-[#234B7A] hover:bg-[#EEF3F9] disabled:opacity-50"
              >
                一键设 A4
              </button>
              <button
                type="button"
                disabled={savingDocSettings}
                onClick={() => void handleDocumentSettings({ fix_margins: true })}
                className="h-7 rounded-md border border-[#E5E2DC] bg-white px-2.5 text-[11px] font-medium text-[#234B7A] hover:bg-[#EEF3F9] disabled:opacity-50"
              >
                一键规范页边距
              </button>
              <button
                type="button"
                disabled={savingDocSettings}
                onClick={() => void handleDocumentSettings({ fix_headers: true })}
                className="h-7 rounded-md border border-[#E5E2DC] bg-white px-2.5 text-[11px] font-medium text-[#234B7A] hover:bg-[#EEF3F9] disabled:opacity-50"
              >
                一键修页眉与双横线
              </button>
            </div>
          </div>
        )}

        {/* Collapsible Paragraph Diff Summary */}
        {changesExpanded && session.changes.length > 0 && (
          <div className="mt-3 max-h-40 space-y-1.5 overflow-y-auto rounded-lg border border-[#E5E2DC] bg-[#FAF9F6] p-2.5 text-xs">
            {session.changes.map((diff) => (
              <button
                key={diff.paragraph_index}
                type="button"
                onClick={() => {
                  setSelectedParagraphIndex(session.editable ? diff.paragraph_index : null);
                  scrollToParagraph(diff.paragraph_index);
                }}
                className="flex w-full flex-wrap items-center justify-between gap-2 rounded-md border border-[#EFECE6] bg-white px-2.5 py-1.5 text-left hover:border-[#234B7A]"
              >
                <div className="flex items-center gap-2">
                  <span className="rounded bg-[#EEF3F9] px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-[#234B7A]">
                    第 {diff.paragraph_index + 1} 段
                  </span>
                  <span className="font-medium text-[#1A2332]">{diff.summary || '格式/文本已调整'}</span>
                  {diff.style_changes.length > 0 && (
                    <span className="text-[11px] text-[#15803D]">
                      {diff.style_changes.join('；')}
                    </span>
                  )}
                </div>
                {diff.before_text !== diff.after_text && (
                  <span className="max-w-md truncate text-[11px] text-[#5A6577]">
                    “{diff.before_text.slice(0, 28)}” → “{diff.after_text.slice(0, 28)}”
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Main Split Area: Left Rulebook + Right Reader/Dual Comparison */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-12">
        <div className="min-h-0 lg:col-span-4 xl:col-span-3">
          <RulebookPanel
            rulebook={session.rulebook}
            editable={session.editable}
            activeRuleCode={highlightedRuleCode}
            fixingRuleCode={fixingRuleCode}
            onJumpToParagraph={handleJumpToParagraph}
            onSelectRule={setHighlightedRuleCode}
            onFixSingleRule={(ruleCode) => handleAutoFix({ ruleCodes: [ruleCode] })}
          />
        </div>

        <div className="min-h-0 lg:col-span-8 xl:col-span-9">
          {viewMode === 'dual' ? (
            <div className="grid h-full min-h-0 grid-cols-1 gap-3 md:grid-cols-2">
              <DocxReaderEditor
                paneId="left"
                title="原稿对照（只读）"
                subtitle="保留原始文本与格式快照，标出已被修订的段落"
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
                title={session.editable ? '调整后修订稿（可继续微调）' : '建议修订文本对照（只读）'}
                subtitle={
                  session.editable
                    ? 'Agent 修复与手动编辑实时同步 · 点击段落可继续微调并增量重判'
                    : 'PDF 源文件不可原位改写，可查看改写建议或导出 LaTeX 气泡批注 PDF'
                }
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
              title={session.editable ? '论文结构化阅读与原位编校器' : '论文结构化阅读与批注定位（PDF 只读）'}
              subtitle={
                session.editable
                  ? '点击任意段落可直接修改文字与样式，保存即触发「改哪段判哪段」增量重判'
                  : '请使用左侧规则书定位问题，或点击「一键修改」/「导出气泡批注 PDF」获取修改方案'
              }
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
      </div>

      {/* Bottom User Feedback Bar */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const trimmed = instruction.trim();
          if (!trimmed || runningAutoFix) return;
          void handleAutoFix({ instruction: trimmed });
        }}
        className="rounded-xl border border-[#E5E2DC] bg-white px-4 py-2.5 shadow-[0_1px_2px_rgba(26,35,50,0.04)]"
      >
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="flex flex-1 items-center gap-2">
            <MessageSquarePlus className="h-4 w-4 shrink-0 text-[#234B7A]" />
            <input
              type="text"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              disabled={runningAutoFix}
              placeholder="向 Agent 提出调整建议（例如：保留英文引用段字体、关键词保留“高中生”并控制在 15 字内）..."
              className="h-8 w-full rounded-lg border border-[#E5E2DC] bg-[#FAF9F6] px-3 text-xs text-[#1A2332] placeholder:text-[#8791A1] focus:border-[#234B7A] focus:bg-white focus:outline-none disabled:opacity-55"
            />
          </div>
          <div className="flex items-center justify-between gap-2 sm:justify-end">
            {latestAgentFeedback?.summary && (
              <span
                className="hidden max-w-md truncate text-[11px] text-[#5A6577] xl:inline"
                title={latestAgentFeedback.summary}
              >
                最新反馈：{latestAgentFeedback.summary}
              </span>
            )}
            <button
              type="submit"
              disabled={!instruction.trim() || runningAutoFix}
              className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-[#234B7A] bg-white px-3 text-xs font-semibold text-[#234B7A] hover:bg-[#EEF3F9] disabled:cursor-not-allowed disabled:opacity-45"
            >
              {runningAutoFix ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Send className="h-3.5 w-3.5" />
              )}
              <span>提交意见并重新生成</span>
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
