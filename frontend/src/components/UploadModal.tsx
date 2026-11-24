import { useEffect, useRef, useState, type DragEvent } from 'react';
import {
  FileText,
  Loader2,
  Play,
  Trash2,
  UploadCloud,
  X,
} from 'lucide-react';
import type { RuleSetResponse } from '../types/api';
import { DEGREE_LABELS, formatFileSize } from '../utils/format';

interface UploadModalProps {
  open: boolean;
  ruleSets: RuleSetResponse[];
  selectedRuleSetId: string;
  onSelectRuleSet: (id: string) => void;
  submitting: boolean;
  disabled: boolean;
  onClose: () => void;
  onSubmitBatch: (files: File[], batchName: string) => Promise<boolean>;
}

const ACCEPTED_EXTS = ['.docx', '.pdf'];

function isSupportedFile(file: File): boolean {
  const lower = file.name.toLowerCase();
  return ACCEPTED_EXTS.some((ext) => lower.endsWith(ext));
}

export function UploadModal({
  open,
  ruleSets,
  selectedRuleSetId,
  onSelectRuleSet,
  submitting,
  disabled,
  onClose,
  onSubmitBatch,
}: UploadModalProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [stagedFiles, setStagedFiles] = useState<File[]>([]);
  const [batchName, setBatchName] = useState('');
  const [isDragging, setIsDragging] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !submitting) onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, submitting, onClose]);

  if (!open) return null;

  const appendFiles = (incoming: FileList | File[]) => {
    const valid: File[] = [];
    const rejected: string[] = [];
    for (const file of Array.from(incoming)) {
      if (isSupportedFile(file)) {
        valid.push(file);
      } else {
        rejected.push(file.name);
      }
    }
    if (rejected.length > 0) {
      setLocalError(`已跳过不支持的文件（仅支持 .docx / .pdf）：${rejected.join('、')}`);
    } else {
      setLocalError(null);
    }
    if (valid.length > 0) {
      setStagedFiles((prev) => {
        const seen = new Set(prev.map((f) => `${f.name}:${f.size}:${f.lastModified}`));
        const next = [...prev];
        for (const f of valid) {
          const key = `${f.name}:${f.size}:${f.lastModified}`;
          if (!seen.has(key)) {
            seen.add(key);
            next.push(f);
          }
        }
        return next;
      });
    }
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
    if (event.dataTransfer.files.length > 0) {
      appendFiles(event.dataTransfer.files);
    }
  };

  const handleRemove = (index: number) => {
    setStagedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleClear = () => {
    setStagedFiles([]);
    setLocalError(null);
  };

  const handleRun = async () => {
    if (stagedFiles.length === 0 || submitting || disabled || !selectedRuleSetId) return;
    setLocalError(null);
    const ok = await onSubmitBatch(stagedFiles, batchName);
    if (ok) {
      setStagedFiles([]);
      setBatchName('');
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="新建批量检测"
    >
      <div
        className="fixed inset-0 bg-[#18181B]/35 backdrop-blur-[1px]"
        onClick={() => {
          if (!submitting) onClose();
        }}
        aria-hidden="true"
      />

      <div className="relative z-10 flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden rounded-xl border border-[#E8E6E1] bg-white shadow-2xl">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-[#ECEAE5] px-5 py-3.5">
          <div>
            <h2 className="text-sm font-semibold text-[#18181B]">新建批量格式检测</h2>
            <p className="mt-0.5 text-xs text-[#71717A]">
              上传 .docx 或 .pdf 论文，按所选规范模板批量解析并生成定位报告
            </p>
          </div>
          <button
            type="button"
            disabled={submitting}
            onClick={onClose}
            aria-label="关闭弹窗"
            className="rounded-lg p-1.5 text-[#71717A] hover:bg-[#F3F2EE] hover:text-[#18181B] disabled:opacity-40"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="flex-1 space-y-4 overflow-y-auto p-5">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label
                htmlFor="modal-rule-set"
                className="mb-1.5 block text-xs font-medium text-[#52525B]"
              >
                检测规则模板
              </label>
              <select
                id="modal-rule-set"
                value={selectedRuleSetId}
                onChange={(e) => onSelectRuleSet(e.target.value)}
                disabled={submitting || ruleSets.length === 0}
                className="h-9 w-full rounded-lg border border-[#E8E6E1] bg-white px-2.5 text-xs font-medium text-[#18181B] focus:border-[#1E3A5F] focus:outline-none disabled:opacity-50"
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
            </div>

            <div>
              <label
                htmlFor="modal-batch-name"
                className="mb-1.5 block text-xs font-medium text-[#52525B]"
              >
                批次名称（可选）
              </label>
              <input
                id="modal-batch-name"
                type="text"
                maxLength={128}
                value={batchName}
                onChange={(e) => setBatchName(e.target.value)}
                disabled={submitting}
                placeholder="留空默认「批量检测」"
                className="h-9 w-full rounded-lg border border-[#E8E6E1] bg-white px-3 text-xs text-[#18181B] placeholder:text-[#71717A] focus:border-[#1E3A5F] focus:outline-none disabled:bg-[#F7F7F5]"
              />
            </div>
          </div>

          {/* Single clean Dropzone */}
          <div
            role="button"
            tabIndex={0}
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                inputRef.current?.click();
              }
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed px-5 py-7 text-center transition-colors ${
              isDragging
                ? 'border-[#1E3A5F] bg-[#EFF4FA]/70'
                : 'border-[#D8D5CE] bg-[#FAF9F7] hover:border-[#1E3A5F]/50 hover:bg-[#F3F2EE]/60'
            }`}
          >
            <input
              ref={inputRef}
              type="file"
              multiple
              accept=".docx,.pdf"
              className="hidden"
              onChange={(e) => {
                if (e.target.files) appendFiles(e.target.files);
                e.target.value = '';
              }}
            />
            <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-[#E8E6E1] bg-white text-[#1E3A5F] shadow-2xs">
              <UploadCloud className="h-5 w-5" />
            </div>
            <p className="mt-3 text-xs font-medium text-[#18181B]">
              拖拽论文文件到此处，或<span className="text-[#1E3A5F] underline underline-offset-4">点击选择文件</span>
            </p>
            <p className="mt-1 text-[11px] text-[#71717A]">
              支持批量上传 <span className="font-medium text-[#52525B]">.docx</span>（OOXML 精确解析）与{' '}
              <span className="font-medium text-[#52525B]">.pdf</span>（版面与字体层解析）
            </p>
          </div>

          {localError && (
            <div className="flex items-center justify-between rounded-lg border border-[#FDE68A] bg-[#FFFBEB] px-3 py-2 text-xs text-[#B45309]">
              <span>{localError}</span>
              <button
                type="button"
                onClick={() => setLocalError(null)}
                className="ml-2 rounded p-0.5 hover:bg-[#FDE68A]/40"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )}

          {stagedFiles.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-[#52525B]">
                  待检测队列（<span className="tabular-nums font-semibold text-[#18181B]">{stagedFiles.length}</span> 篇）
                </span>
                <button
                  type="button"
                  onClick={handleClear}
                  disabled={submitting}
                  className="inline-flex items-center gap-1 text-[11px] text-[#71717A] hover:text-[#B91C1C] disabled:opacity-50"
                >
                  <Trash2 className="h-3 w-3" />
                  <span>清空</span>
                </button>
              </div>

              <div className="max-h-44 divide-y divide-[#ECEAE5] overflow-y-auto rounded-lg border border-[#E8E6E1] bg-white">
                {stagedFiles.map((file, idx) => {
                  const isDocx = file.name.toLowerCase().endsWith('.docx');
                  return (
                    <div
                      key={`${file.name}-${file.size}-${idx}`}
                      className="flex items-center justify-between gap-2 px-3 py-2 text-xs"
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <FileText className="h-3.5 w-3.5 shrink-0 text-[#71717A]" />
                        <span
                          className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                            isDocx
                              ? 'bg-[#EFF4FA] text-[#1E3A5F]'
                              : 'bg-[#FDF2EE] text-[#9A3412]'
                          }`}
                        >
                          {isDocx ? 'DOCX' : 'PDF'}
                        </span>
                        <span className="truncate font-medium text-[#18181B]" title={file.name}>
                          {file.name}
                        </span>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <span className="tabular-nums text-[11px] text-[#71717A]">
                          {formatFileSize(file.size)}
                        </span>
                        <button
                          type="button"
                          onClick={() => handleRemove(idx)}
                          disabled={submitting}
                          aria-label={`移除 ${file.name}`}
                          className="rounded p-0.5 text-[#71717A] hover:bg-[#F3F2EE] hover:text-[#18181B] disabled:opacity-40"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-[#ECEAE5] bg-[#FAF9F7] px-5 py-3">
          <button
            type="button"
            disabled={submitting}
            onClick={onClose}
            className="inline-flex h-8 items-center rounded-lg border border-[#E2E0DA] bg-white px-3 text-xs font-medium text-[#52525B] hover:bg-[#F7F7F5] hover:text-[#18181B] disabled:opacity-50"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleRun}
            disabled={stagedFiles.length === 0 || submitting || disabled || !selectedRuleSetId}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#1E3A5F] px-3.5 text-xs font-semibold text-white transition-colors hover:bg-[#162C49] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>正在解析检测（{stagedFiles.length} 篇）...</span>
              </>
            ) : (
              <>
                <Play className="h-3.5 w-3.5 fill-current" />
                <span>开始批量检测{stagedFiles.length > 0 ? `（${stagedFiles.length} 篇）` : ''}</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

interface EmptyBatchCardProps {
  onOpenUpload: () => void;
}

export function EmptyBatchCard({ onOpenUpload }: EmptyBatchCardProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-[#D8D5CE] bg-[#FAF9F7] px-6 py-16 text-center">
      <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-[#E8E6E1] bg-white text-[#1E3A5F] shadow-2xs">
        <UploadCloud className="h-5 w-5" />
      </div>
      <h2 className="mt-3.5 text-sm font-semibold text-[#18181B]">暂无检测批次记录</h2>
      <p className="mt-1 max-w-md text-xs text-[#71717A]">
        上传 .docx 或 .pdf 学位论文，系统将自动解析版面与格式结构，生成逐条可定位的违规报告与在线修订工作台。
      </p>
      <button
        type="button"
        onClick={onOpenUpload}
        className="mt-4 inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#1E3A5F] px-3.5 text-xs font-semibold text-white hover:bg-[#162C49]"
      >
        <UploadCloud className="h-3.5 w-3.5" />
        <span>上传首批论文</span>
      </button>
    </div>
  );
}
