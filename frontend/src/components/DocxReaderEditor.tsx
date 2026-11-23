import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Edit3,
  FileImage,
  Loader2,
  RotateCcw,
  Table2,
  X,
} from 'lucide-react';
import type { ViolationResponse } from '../types/api';
import type {
  Alignment,
  ParagraphDiff,
  ParagraphEditRequest,
  ParagraphIR,
} from '../types/revisions';
import { getAlignmentLabel, getFontLabel, getSectionLabel } from '../utils/format';

interface DocxReaderEditorProps {
  paneId: string;
  title: string;
  subtitle?: string;
  paragraphs: ParagraphIR[];
  violationsByParagraph: Map<number, ViolationResponse[]>;
  diffMap?: Map<number, ParagraphDiff>;
  modifiedSet?: Set<number>;
  editable: boolean;
  selectedParagraphIndex: number | null;
  highlightedRuleCode: string | null;
  savingParagraphIndex: number | null;
  focusTarget?: { paragraphIndex: number; seq: number } | null;
  lastResolvedBanner?: {
    paragraphIndex: number;
    resolvedCount: number;
    remainingCount: number;
  } | null;
  onSelectParagraph: (index: number | null) => void;
  onSaveParagraph?: (index: number, payload: ParagraphEditRequest) => Promise<void>;
  onRevertParagraph?: (index: number) => Promise<void>;
}

const CHUNK_SIZE = 80;

const FONT_OPTIONS = [
  { value: '', label: '保持原字体' },
  { value: 'simsun', label: '宋体 (SimSun)' },
  { value: 'simhei', label: '黑体 (SimHei)' },
  { value: 'times_new_roman', label: 'Times New Roman' },
  { value: 'microsoft_yahei', label: '微软雅黑' },
];

const SIZE_PRESETS = [
  { value: '22', label: '二号 (22pt)' },
  { value: '18', label: '小二号 (18pt)' },
  { value: '15', label: '小三号 (15pt)' },
  { value: '14', label: '四号 (14pt)' },
  { value: '12', label: '小四号 (12pt)' },
  { value: '10.5', label: '五号 (10.5pt)' },
];

function visualClassForParagraph(p: ParagraphIR): string {
  const alignClass =
    p.alignment === 'center'
      ? 'text-center'
      : p.alignment === 'right'
        ? 'text-right'
        : p.alignment === 'justify'
          ? 'text-justify'
          : 'text-left';

  let roleClass = 'text-[13px] leading-relaxed text-[#1A2332]';
  if (p.role === 'cover_title') {
    roleClass = 'text-lg font-semibold leading-snug text-[#1A2332]';
  } else if (p.role === 'section_heading' || p.role === 'chapter_heading') {
    roleClass = 'text-base font-semibold leading-snug text-[#1A2332] pt-2';
  } else if (p.role === 'section_l2_heading') {
    roleClass = 'text-[15px] font-semibold leading-snug text-[#1A2332] pt-1';
  } else if (p.role === 'section_l3_heading' || p.role === 'section_l4_heading') {
    roleClass = 'text-[14px] font-semibold leading-snug text-[#1A2332]';
  } else if (p.role === 'reference_entry' || p.role === 'toc_entry') {
    roleClass = 'text-xs leading-relaxed text-[#334155]';
  }

  const fontClass =
    p.font_name === 'simhei'
      ? 'font-sans'
      : p.font_name === 'times_new_roman'
        ? 'font-serif'
        : '';

  return `${alignClass} ${roleClass} ${fontClass} ${p.bold ? 'font-bold' : ''}`;
}

export function DocxReaderEditor({
  paneId,
  title,
  subtitle,
  paragraphs,
  violationsByParagraph,
  diffMap,
  modifiedSet,
  editable,
  selectedParagraphIndex,
  highlightedRuleCode,
  savingParagraphIndex,
  focusTarget,
  lastResolvedBanner,
  onSelectParagraph,
  onSaveParagraph,
  onRevertParagraph,
}: DocxReaderEditorProps) {
  const [onlyRelevant, setOnlyRelevant] = useState(false);
  const [currentChunk, setCurrentChunk] = useState(0);
  const scrolledSeqRef = useRef<number | null>(null);

  // Local editing draft for the currently selected paragraph
  const [draftText, setDraftText] = useState('');
  const [draftFont, setDraftFont] = useState('');
  const [draftSize, setDraftSize] = useState('');
  const [draftBold, setDraftBold] = useState<'' | 'true' | 'false'>('');
  const [draftAlignment, setDraftAlignment] = useState<'' | Alignment>('');
  const [draftSpacing, setDraftSpacing] = useState('');

  const selectedParagraph = useMemo(
    () => paragraphs.find((p) => p.index === selectedParagraphIndex) ?? null,
    [paragraphs, selectedParagraphIndex],
  );

  useEffect(() => {
    if (!selectedParagraph) return;
    setDraftText(selectedParagraph.text);
    setDraftFont(selectedParagraph.font_name ?? '');
    setDraftSize(
      selectedParagraph.font_size_pt != null ? String(selectedParagraph.font_size_pt) : '',
    );
    setDraftBold(
      selectedParagraph.bold === null ? '' : selectedParagraph.bold ? 'true' : 'false',
    );
    setDraftAlignment(selectedParagraph.alignment ?? '');
    setDraftSpacing(
      selectedParagraph.line_spacing_pt != null
        ? String(Number(selectedParagraph.line_spacing_pt.toFixed(2)))
        : '',
    );
  }, [selectedParagraph]);

  const visibleParagraphs = useMemo(() => {
    if (!onlyRelevant) return paragraphs;
    return paragraphs.filter((p) => {
      if (p.index === selectedParagraphIndex) return true;
      if ((violationsByParagraph.get(p.index)?.length ?? 0) > 0) return true;
      if (diffMap?.has(p.index) || modifiedSet?.has(p.index)) return true;
      return false;
    });
  }, [paragraphs, onlyRelevant, selectedParagraphIndex, violationsByParagraph, diffMap, modifiedSet]);

  const totalChunks = Math.max(1, Math.ceil(visibleParagraphs.length / CHUNK_SIZE));
  const safeChunk = Math.min(currentChunk, totalChunks - 1);

  const pagedParagraphs = useMemo(() => {
    if (visibleParagraphs.length <= CHUNK_SIZE) return visibleParagraphs;
    const start = safeChunk * CHUNK_SIZE;
    return visibleParagraphs.slice(start, start + CHUNK_SIZE);
  }, [visibleParagraphs, safeChunk]);

  useEffect(() => {
    setCurrentChunk(0);
  }, [onlyRelevant, paragraphs.length]);

  useEffect(() => {
    if (!focusTarget) return;
    let list = visibleParagraphs;
    let pos = list.findIndex((p) => p.index === focusTarget.paragraphIndex);
    if (pos === -1 && onlyRelevant) {
      setOnlyRelevant(false);
      list = paragraphs;
      pos = list.findIndex((p) => p.index === focusTarget.paragraphIndex);
    }
    if (pos >= 0) {
      setCurrentChunk(Math.floor(pos / CHUNK_SIZE));
    }
  }, [focusTarget, visibleParagraphs, onlyRelevant, paragraphs]);

  useEffect(() => {
    if (!focusTarget || scrolledSeqRef.current === focusTarget.seq) return;
    const existsInPage = pagedParagraphs.some(
      (p) => p.index === focusTarget.paragraphIndex,
    );
    if (!existsInPage) return;
    scrolledSeqRef.current = focusTarget.seq;
    window.requestAnimationFrame(() => {
      const el = document.querySelector(
        `[data-pane="${paneId}"][data-para-index="${focusTarget.paragraphIndex}"]`,
      );
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    });
  }, [focusTarget, pagedParagraphs, paneId]);

  const handleSave = async (p: ParagraphIR) => {
    if (!onSaveParagraph) return;
    const payload: ParagraphEditRequest = {};
    if (!(p.has_image && !p.text.trim()) && draftText !== p.text) {
      payload.text = draftText;
    }
    if (draftFont && draftFont !== (p.font_name ?? '')) {
      payload.font_name = draftFont;
    }
    const parsedSize = Number(draftSize);
    if (draftSize && Number.isFinite(parsedSize) && parsedSize !== p.font_size_pt) {
      payload.font_size_pt = parsedSize;
    }
    if (draftBold !== '') {
      const nextBold = draftBold === 'true';
      if (nextBold !== p.bold) payload.bold = nextBold;
    }
    if (draftAlignment && draftAlignment !== p.alignment) {
      payload.alignment = draftAlignment;
    }
    const parsedSpacing = Number(draftSpacing);
    if (
      draftSpacing &&
      Number.isFinite(parsedSpacing) &&
      parsedSpacing !== p.line_spacing_pt
    ) {
      payload.line_spacing_pt = parsedSpacing;
    }

    if (Object.keys(payload).length === 0) {
      onSelectParagraph(null);
      return;
    }
    await onSaveParagraph(p.index, payload);
  };

  return (
    <section className="flex h-full flex-col overflow-hidden rounded-xl border border-[#E5E2DC] bg-white shadow-[0_1px_2px_rgba(26,35,50,0.04)]">
      {/* Reader Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#EFECE6] bg-[#FAF9F6] px-4 py-2.5">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-xs font-semibold text-[#1A2332]">{title}</h3>
            {editable ? (
              <span className="rounded bg-[#ECFDF5] px-1.5 py-0.5 text-[10px] font-medium text-[#15803D]">
                点击段落可编辑 · 改哪段判哪段
              </span>
            ) : (
              <span className="rounded bg-[#F3F4F6] px-1.5 py-0.5 text-[10px] font-medium text-[#5A6577]">
                只读对照
              </span>
            )}
          </div>
          {subtitle && <p className="mt-0.5 text-[11px] text-[#5A6577]">{subtitle}</p>}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {totalChunks > 1 && (
            <div className="flex items-center gap-1 rounded-md border border-[#E5E2DC] bg-white px-1.5 py-0.5 text-[11px] tabular-nums text-[#5A6577]">
              <button
                type="button"
                disabled={safeChunk === 0}
                onClick={() => setCurrentChunk((c) => Math.max(0, c - 1))}
                aria-label="上一屏"
                className="rounded p-0.5 hover:bg-[#FAF9F6] disabled:opacity-35"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>
              <span>
                第 {safeChunk * CHUNK_SIZE + 1}–
                {Math.min((safeChunk + 1) * CHUNK_SIZE, visibleParagraphs.length)} /{' '}
                {visibleParagraphs.length} 段（{safeChunk + 1}/{totalChunks}）
              </span>
              <button
                type="button"
                disabled={safeChunk >= totalChunks - 1}
                onClick={() => setCurrentChunk((c) => Math.min(totalChunks - 1, c + 1))}
                aria-label="下一屏"
                className="rounded p-0.5 hover:bg-[#FAF9F6] disabled:opacity-35"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
          <button
            type="button"
            onClick={() => setOnlyRelevant((prev) => !prev)}
            className={`rounded-md border px-2 py-1 text-[11px] font-medium transition-colors ${
              onlyRelevant
                ? 'border-[#234B7A] bg-[#EEF3F9] text-[#234B7A]'
                : 'border-[#E5E2DC] bg-white text-[#5A6577] hover:text-[#1A2332]'
            }`}
          >
            {onlyRelevant ? `仅看问题/变更段 (${visibleParagraphs.length})` : `全文 (${paragraphs.length} 段)`}
          </button>
        </div>
      </div>

      {/* Paper Canvas */}
      <div className="flex-1 overflow-y-auto bg-[#F4F2EC]/70 p-4 sm:p-5">
        <div className="mx-auto max-w-[780px] space-y-2 rounded-xl border border-[#E5E2DC] bg-white p-5 shadow-xs sm:p-7">
          {pagedParagraphs.length === 0 ? (
            <div className="py-12 text-center text-xs text-[#8791A1]">
              当前筛选视图下没有需要关注的段落
            </div>
          ) : (
            pagedParagraphs.map((p, idx) => {
              const prevPage = idx > 0 ? pagedParagraphs[idx - 1].page_no : null;
              const showPageBreak = p.page_no != null && p.page_no !== prevPage;
              const pViolations = violationsByParagraph.get(p.index) ?? [];
              const diff = diffMap?.get(p.index);
              const isModified = Boolean(modifiedSet?.has(p.index) || diff);
              const isSelected = selectedParagraphIndex === p.index;
              const isSaving = savingParagraphIndex === p.index;
              const matchesRule =
                Boolean(highlightedRuleCode) &&
                pViolations.some((v) => v.rule_code === highlightedRuleCode);
              const showResolved =
                lastResolvedBanner?.paragraphIndex === p.index &&
                lastResolvedBanner.resolvedCount > 0;

              if (p.object_kind === 'table') {
                return (
                  <div
                    key={p.index}
                    data-pane={paneId}
                    data-para-index={p.index}
                    className="my-2 flex items-center gap-2 rounded-lg border border-dashed border-[#D5D0C7] bg-[#FAF9F6] px-3 py-1.5 text-[11px] text-[#5A6577]"
                  >
                    <Table2 className="h-3.5 w-3.5 text-[#234B7A]" />
                    <span>表格区域（下方缩进段落为表格单元格内容，可点击编辑）</span>
                  </div>
                );
              }

              const hasErrors = pViolations.some((v) => v.severity === 'error');
              const hasWarnings = pViolations.length > 0 && !hasErrors;
              const canEditThis = editable && !isSaving;

              return (
                <div key={p.index}>
                  {showPageBreak && (
                    <div className="my-3 flex items-center gap-2 text-[10px] font-medium text-[#8791A1]">
                      <div className="h-px flex-1 bg-[#EFECE6]" />
                      <span className="tabular-nums">第 {p.page_no} 页</span>
                      <div className="h-px flex-1 bg-[#EFECE6]" />
                    </div>
                  )}

                  <div
                    data-pane={paneId}
                    data-para-index={p.index}
                    onClick={() => {
                      if (canEditThis && !isSelected) onSelectParagraph(p.index);
                    }}
                    className={`group relative rounded-lg border px-3 py-2 transition-all ${
                      p.in_table ? 'ml-4 border-l-2 border-l-[#CBD5E1]' : ''
                    } ${
                      isSelected
                        ? 'border-[#234B7A] bg-[#EEF3F9]/40 ring-2 ring-[#234B7A]/15'
                        : matchesRule
                          ? 'border-[#B91C1C] bg-[#FEF2F2]/60 ring-2 ring-[#B91C1C]/15'
                          : hasErrors
                            ? 'border-[#FECACA] bg-[#FEF2F2]/35 hover:border-[#FCA5A5]'
                            : hasWarnings
                              ? 'border-[#FDE68A] bg-[#FFFBEB]/40 hover:border-[#FCD34D]'
                              : diff
                                ? 'border-[#BBF7D0] bg-[#ECFDF5]/40'
                                : 'border-transparent hover:border-[#E5E2DC] hover:bg-[#FAF9F6]/60'
                    } ${canEditThis && !isSelected ? 'cursor-pointer' : ''}`}
                  >
                    {/* Metadata bar */}
                    <div className="mb-1 flex flex-wrap items-center justify-between gap-1.5 text-[10px] text-[#8791A1]">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="tabular-nums font-medium">#{p.index + 1}</span>
                        {p.section_key && (
                          <span className="rounded bg-[#FAF9F6] px-1.5 py-0.5 text-[#5A6577]">
                            {getSectionLabel(p.section_key)}
                          </span>
                        )}
                        <span className="tabular-nums">
                          {getFontLabel(p.font_name)} ·{' '}
                          {p.font_size_pt != null ? `${p.font_size_pt}pt` : '字号未知'} ·{' '}
                          {getAlignmentLabel(p.alignment)}
                          {p.line_spacing_pt != null
                            ? ` · 行距 ${Number(p.line_spacing_pt.toFixed(1))}pt`
                            : ''}
                        </span>
                      </div>

                      <div className="flex items-center gap-1.5">
                        {diff && (
                          <span className="rounded bg-[#ECFDF5] px-1.5 py-0.5 font-medium text-[#15803D]">
                            {diff.source === 'llm'
                              ? 'LLM 改写'
                              : diff.source === 'rule'
                                ? '规则修复'
                                : '手动已改'}
                          </span>
                        )}
                        {!diff && isModified && (
                          <span className="rounded bg-[#EEF3F9] px-1.5 py-0.5 font-medium text-[#234B7A]">
                            已改动
                          </span>
                        )}
                        {canEditThis && !isSelected && (
                          <span className="hidden items-center gap-0.5 text-[#234B7A] group-hover:inline-flex">
                            <Edit3 className="h-3 w-3" />
                            <span>编辑</span>
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Paragraph content or inline editor */}
                    {isSelected && editable ? (
                      <div
                        className="mt-1.5 space-y-2.5 rounded-lg border border-[#234B7A]/30 bg-white p-3 shadow-xs"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {p.has_image && !p.text.trim() ? (
                          <div className="flex items-center gap-2 rounded bg-[#FAF9F6] px-2.5 py-2 text-xs text-[#5A6577]">
                            <FileImage className="h-4 w-4 text-[#234B7A]" />
                            <span>该段包含嵌入式图片，仅可调整段落排版样式（对齐/行距）</span>
                          </div>
                        ) : (
                          <textarea
                            rows={Math.min(8, Math.max(2, Math.ceil(draftText.length / 42)))}
                            value={draftText}
                            onChange={(e) => setDraftText(e.target.value)}
                            onKeyDown={(e) => {
                              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                                e.preventDefault();
                                void handleSave(p);
                              } else if (e.key === 'Escape') {
                                onSelectParagraph(null);
                              }
                            }}
                            className="w-full rounded-md border border-[#D5D0C7] bg-[#FAF9F6] p-2 text-xs leading-relaxed text-[#1A2332] focus:border-[#234B7A] focus:bg-white focus:outline-none"
                          />
                        )}

                        {/* Style controls */}
                        <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-5">
                          <div>
                            <label className="mb-0.5 block text-[10px] text-[#5A6577]">字体</label>
                            <select
                              value={draftFont}
                              onChange={(e) => setDraftFont(e.target.value)}
                              className="h-7 w-full rounded border border-[#E5E2DC] bg-white px-1.5 text-[11px] focus:border-[#234B7A] focus:outline-none"
                            >
                              {FONT_OPTIONS.map((opt) => (
                                <option key={opt.value} value={opt.value}>
                                  {opt.label}
                                </option>
                              ))}
                            </select>
                          </div>

                          <div>
                            <label className="mb-0.5 block text-[10px] text-[#5A6577]">字号 (pt)</label>
                            <div className="flex gap-1">
                              <select
                                value={
                                  SIZE_PRESETS.some((s) => Number(s.value) === Number(draftSize))
                                    ? String(Number(draftSize))
                                    : ''
                                }
                                onChange={(e) => {
                                  if (e.target.value) setDraftSize(e.target.value);
                                }}
                                className="h-7 w-full rounded border border-[#E5E2DC] bg-white px-1 text-[11px] focus:border-[#234B7A] focus:outline-none"
                              >
                                <option value="">自定义</option>
                                {SIZE_PRESETS.map((s) => (
                                  <option key={s.value} value={s.value}>
                                    {s.label}
                                  </option>
                                ))}
                              </select>
                              <input
                                type="number"
                                step="0.5"
                                min="5"
                                max="72"
                                value={draftSize}
                                onChange={(e) => setDraftSize(e.target.value)}
                                className="h-7 w-14 rounded border border-[#E5E2DC] bg-white px-1.5 tabular-nums text-[11px] focus:border-[#234B7A] focus:outline-none"
                              />
                            </div>
                          </div>

                          <div>
                            <label className="mb-0.5 block text-[10px] text-[#5A6577]">粗细</label>
                            <select
                              value={draftBold}
                              onChange={(e) =>
                                setDraftBold(e.target.value as '' | 'true' | 'false')
                              }
                              className="h-7 w-full rounded border border-[#E5E2DC] bg-white px-1.5 text-[11px] focus:border-[#234B7A] focus:outline-none"
                            >
                              <option value="">保持原状</option>
                              <option value="true">加粗</option>
                              <option value="false">常规（不加粗）</option>
                            </select>
                          </div>

                          <div>
                            <label className="mb-0.5 block text-[10px] text-[#5A6577]">对齐</label>
                            <select
                              value={draftAlignment}
                              onChange={(e) =>
                                setDraftAlignment(e.target.value as '' | Alignment)
                              }
                              className="h-7 w-full rounded border border-[#E5E2DC] bg-white px-1.5 text-[11px] focus:border-[#234B7A] focus:outline-none"
                            >
                              <option value="">保持原对齐</option>
                              <option value="left">左对齐</option>
                              <option value="center">居中</option>
                              <option value="right">右对齐</option>
                              <option value="justify">两端对齐</option>
                            </select>
                          </div>

                          <div>
                            <label className="mb-0.5 block text-[10px] text-[#5A6577]">行距 (pt)</label>
                            <input
                              type="number"
                              step="0.5"
                              min="10"
                              max="100"
                              value={draftSpacing}
                              onChange={(e) => setDraftSpacing(e.target.value)}
                              placeholder="如 22"
                              className="h-7 w-full rounded border border-[#E5E2DC] bg-white px-2 tabular-nums text-[11px] focus:border-[#234B7A] focus:outline-none"
                            />
                          </div>
                        </div>

                        <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
                          <div>
                            {isModified && onRevertParagraph && (
                              <button
                                type="button"
                                disabled={isSaving}
                                onClick={() => void onRevertParagraph(p.index)}
                                className="inline-flex h-7 items-center gap-1 rounded-md border border-[#E5E2DC] bg-white px-2.5 text-[11px] font-medium text-[#5A6577] hover:text-[#B91C1C] disabled:opacity-50"
                              >
                                <RotateCcw className="h-3 w-3" />
                                <span>撤销还原原稿</span>
                              </button>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              disabled={isSaving}
                              onClick={() => onSelectParagraph(null)}
                              className="inline-flex h-7 items-center gap-1 rounded-md border border-[#E5E2DC] bg-white px-2.5 text-[11px] text-[#5A6577] hover:text-[#1A2332]"
                            >
                              <X className="h-3 w-3" />
                              <span>取消</span>
                            </button>
                            <button
                              type="button"
                              disabled={isSaving}
                              onClick={() => void handleSave(p)}
                              className="inline-flex h-7 items-center gap-1 rounded-md bg-[#234B7A] px-3 text-[11px] font-semibold text-white hover:bg-[#1B3B61] disabled:opacity-55"
                            >
                              {isSaving ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : (
                                <Check className="h-3 w-3" />
                              )}
                              <span>保存并重判</span>
                            </button>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className={visualClassForParagraph(p)}>
                        {p.has_image && (
                          <span className="mr-1.5 inline-flex items-center gap-1 rounded bg-[#EEF3F9] px-1.5 py-0.5 text-[10px] font-medium text-[#234B7A]">
                            <FileImage className="h-3 w-3" />
                            插图
                          </span>
                        )}
                        {p.object_kind === 'formula' && (
                          <span className="mr-1.5 inline-flex items-center rounded bg-[#F3F4F6] px-1.5 py-0.5 text-[10px] font-medium text-[#4B5563]">
                            公式
                          </span>
                        )}
                        <span className="whitespace-pre-wrap break-words">
                          {p.text || (p.has_image ? '' : '（空段落）')}
                        </span>
                      </div>
                    )}

                    {/* Style changes summary on diff */}
                    {diff && diff.style_changes.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {diff.style_changes.map((sc, sIdx) => (
                          <span
                            key={sIdx}
                            className="rounded border border-[#BBF7D0] bg-[#ECFDF5] px-1.5 py-0.5 text-[10px] text-[#15803D]"
                          >
                            {sc}
                          </span>
                        ))}
                      </div>
                    )}

                    {/* Live resolution flash banner */}
                    {showResolved && (
                      <div className="mt-2 flex items-center gap-1.5 rounded-md border border-[#BBF7D0] bg-[#ECFDF5] px-2.5 py-1.5 text-[11px] font-medium text-[#15803D]">
                        <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                        <span>
                          增量重判完成：已消除 {lastResolvedBanner.resolvedCount} 处违规
                          {lastResolvedBanner.remainingCount === 0
                            ? '，本段现已完全合规！'
                            : `（本段仍余 ${lastResolvedBanner.remainingCount} 处）`}
                        </span>
                      </div>
                    )}

                    {/* Inline error bubbles */}
                    {pViolations.length > 0 && (
                      <div className="mt-2 space-y-1">
                        {pViolations.slice(0, 3).map((v) => (
                          <div
                            key={v.id}
                            className={`rounded-md border px-2.5 py-1.5 text-[11px] ${
                              v.severity === 'error'
                                ? 'border-[#FECACA] bg-[#FEF2F2] text-[#991B1B]'
                                : 'border-[#FDE68A] bg-[#FFFBEB] text-[#92400E]'
                            }`}
                          >
                            <div className="flex flex-wrap items-center justify-between gap-1 font-semibold">
                              <span>{v.rule_name}</span>
                              <span className="font-mono text-[10px] opacity-75">{v.rule_code}</span>
                            </div>
                            <div className="mt-0.5 text-[10px] opacity-90">
                              期望：{v.expected} ｜ 实际：{v.actual}
                            </div>
                          </div>
                        ))}
                        {pViolations.length > 3 && (
                          <div className="text-[10px] text-[#B91C1C]">
                            本段另有 {pViolations.length - 3} 条提示，请查看左侧规则书
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })
          )}
          {totalChunks > 1 && (
            <div className="mt-4 flex items-center justify-between border-t border-[#EFECE6] pt-3 text-xs text-[#5A6577]">
              <button
                type="button"
                disabled={safeChunk === 0}
                onClick={() => setCurrentChunk((c) => Math.max(0, c - 1))}
                className="inline-flex h-7 items-center gap-1 rounded-md border border-[#E5E2DC] bg-[#FAF9F6] px-2.5 text-[11px] font-medium hover:bg-[#EFECE6] disabled:opacity-40"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
                <span>上一屏</span>
              </button>
              <span className="tabular-nums text-[11px]">
                第 {safeChunk + 1} / {totalChunks} 屏（第 {safeChunk * CHUNK_SIZE + 1}–
                {Math.min((safeChunk + 1) * CHUNK_SIZE, visibleParagraphs.length)} 段，共{' '}
                {visibleParagraphs.length} 段）
              </span>
              <button
                type="button"
                disabled={safeChunk >= totalChunks - 1}
                onClick={() => setCurrentChunk((c) => Math.min(totalChunks - 1, c + 1))}
                className="inline-flex h-7 items-center gap-1 rounded-md border border-[#E5E2DC] bg-[#FAF9F6] px-2.5 text-[11px] font-medium hover:bg-[#EFECE6] disabled:opacity-40"
              >
                <span>下一屏</span>
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
