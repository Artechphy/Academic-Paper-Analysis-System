import { useRef, useState, type DragEvent } from 'react';
import {
  FileText,
  Loader2,
  Play,
  Trash2,
  UploadCloud,
  X,
} from 'lucide-react';
import type { RuleSetResponse } from '../types/api';
import { formatFileSize } from '../utils/format';

interface UploadZoneProps {
  selectedRuleSet: RuleSetResponse | undefined;
  submitting: boolean;
  disabled: boolean;
  onSubmitBatch: (files: File[], batchName: string) => Promise<boolean>;
}

const ACCEPTED_EXTS = ['.docx', '.pdf'];

function isSupportedFile(file: File): boolean {
  const lower = file.name.toLowerCase();
  return ACCEPTED_EXTS.some((ext) => lower.endsWith(ext));
}

export function UploadZone({
  selectedRuleSet,
  submitting,
  disabled,
  onSubmitBatch,
}: UploadZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [stagedFiles, setStagedFiles] = useState<File[]>([]);
  const [batchName, setBatchName] = useState('');
  const [isDragging, setIsDragging] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

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
      setLocalError(`已跳过不支持的文件格式（仅支持 .docx / .pdf）：${rejected.join('、')}`);
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
    if (stagedFiles.length === 0 || submitting || disabled) return;
    setLocalError(null);
    const ok = await onSubmitBatch(stagedFiles, batchName);
    if (ok) {
      setStagedFiles([]);
      setBatchName('');
    }
  };

  return (
    <section
      aria-label="批量论文上传区"
      className="rounded-xl border border-[#E5E2DC] bg-white p-4 shadow-[0_1px_2px_rgba(26,35,50,0.04)] sm:p-5"
    >
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        className={`relative flex flex-col items-center justify-between gap-4 rounded-lg border-2 border-dashed px-5 py-5 transition-colors sm:flex-row ${
          isDragging
            ? 'border-[#234B7A] bg-[#EEF3F9]/70'
            : 'border-[#D9D5CC] bg-[#FAF9F6]/70 hover:border-[#B9B2A6]'
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

        <div className="flex items-center gap-3.5">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-[#E5E2DC] bg-white text-[#234B7A] shadow-2xs">
            <UploadCloud className="h-5 w-5" />
          </div>
          <div>
            <p className="text-sm font-medium text-[#1A2332]">
              拖拽论文文件到此处，或{' '}
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                className="font-semibold text-[#234B7A] underline decoration-[#234B7A]/40 underline-offset-4 hover:text-[#1B3B61]"
              >
                选择多个文件
              </button>
            </p>
            <p className="mt-0.5 text-xs text-[#5A6577]">
              同时支持 <span className="font-medium text-[#1A2332]">.docx</span>（OOXML 高精度解析）与{' '}
              <span className="font-medium text-[#1A2332]">.pdf</span>（版面/字体/扫描层检测），提交后同步入库并生成可定位违规报告
            </p>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#E5E2DC] bg-white px-3.5 text-xs font-medium text-[#1A2332] shadow-2xs transition-colors hover:bg-[#FAF9F6]"
          >
            添加论文
          </button>
        </div>
      </div>

      {localError && (
        <div className="mt-3 flex items-center justify-between rounded-lg border border-[#FDE68A] bg-[#FFFBEB] px-3 py-2 text-xs text-[#B45309]">
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
        <div className="mt-4 space-y-3 border-t border-[#EFECE6] pt-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-medium text-[#5A6577]">
              待检测队列（<span className="tabular-nums font-semibold text-[#1A2332]">{stagedFiles.length}</span> 篇）
            </span>
            <button
              type="button"
              onClick={handleClear}
              disabled={submitting}
              className="inline-flex items-center gap-1 text-xs text-[#5A6577] hover:text-[#B91C1C] disabled:opacity-50"
            >
              <Trash2 className="h-3.5 w-3.5" />
              <span>清空队列</span>
            </button>
          </div>

          <div className="flex max-h-36 flex-wrap gap-2 overflow-y-auto pr-1">
            {stagedFiles.map((file, idx) => {
              const isDocx = file.name.toLowerCase().endsWith('.docx');
              return (
                <div
                  key={`${file.name}-${file.size}-${idx}`}
                  className="inline-flex max-w-full items-center gap-2 rounded-lg border border-[#E5E2DC] bg-[#FAF9F6] px-2.5 py-1.5 text-xs"
                >
                  <FileText className="h-3.5 w-3.5 shrink-0 text-[#5A6577]" />
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                      isDocx
                        ? 'bg-[#EEF3F9] text-[#234B7A]'
                        : 'bg-[#FDF2EE] text-[#9A3412]'
                    }`}
                  >
                    {isDocx ? 'DOCX' : 'PDF'}
                  </span>
                  <span className="max-w-[220px] truncate font-medium text-[#1A2332]" title={file.name}>
                    {file.name}
                  </span>
                  <span className="tabular-nums text-[#8791A1]">{formatFileSize(file.size)}</span>
                  <button
                    type="button"
                    onClick={() => handleRemove(idx)}
                    disabled={submitting}
                    aria-label={`移除 ${file.name}`}
                    className="rounded p-0.5 text-[#8791A1] hover:bg-[#E5E2DC]/60 hover:text-[#1A2332] disabled:opacity-40"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              );
            })}
          </div>

          <div className="flex flex-col items-stretch justify-between gap-3 pt-1 sm:flex-row sm:items-center">
            <div className="flex flex-1 items-center gap-2">
              <label htmlFor="batch-name-input" className="shrink-0 text-xs font-medium text-[#5A6577]">
                批次名称
              </label>
              <input
                id="batch-name-input"
                type="text"
                maxLength={128}
                value={batchName}
                onChange={(e) => setBatchName(e.target.value)}
                disabled={submitting}
                placeholder="可选，留空默认「批量检测」"
                className="h-9 w-full max-w-xs rounded-lg border border-[#E5E2DC] bg-white px-3 text-xs text-[#1A2332] placeholder:text-[#8791A1] focus:border-[#234B7A] focus:outline-none disabled:bg-[#FAF9F6]"
              />
              {selectedRuleSet && (
                <span className="hidden text-xs text-[#5A6577] lg:inline">
                  将使用模板：<strong className="font-medium text-[#1A2332]">{selectedRuleSet.name}</strong>
                </span>
              )}
            </div>

            <button
              type="button"
              onClick={handleRun}
              disabled={submitting || disabled || !selectedRuleSet}
              className="inline-flex h-9 items-center justify-center gap-2 rounded-lg bg-[#234B7A] px-4 text-xs font-semibold text-white shadow-xs transition-colors hover:bg-[#1B3B61] disabled:cursor-not-allowed disabled:opacity-55"
            >
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>正在解析与执行规则（{stagedFiles.length} 篇）...</span>
                </>
              ) : (
                <>
                  <Play className="h-3.5 w-3.5 fill-current" />
                  <span>开始批量检测（{stagedFiles.length} 篇）</span>
                </>
              )}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
