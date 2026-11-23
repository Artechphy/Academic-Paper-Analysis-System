import type {
  BatchDetail,
  BatchSummary,
  CheckRunDetail,
  HealthResponse,
  RuleItemResponse,
  RuleItemUpdate,
  RuleSetCreate,
  RuleSetDetail,
  RuleSetResponse,
  StatsOverview,
  Verdict,
} from '../types/api';

const API_BASE = '/api/v1';

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function extractErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== 'object') return fallback;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (item && typeof item === 'object' && 'msg' in item) {
          const loc = Array.isArray((item as { loc?: unknown }).loc)
            ? ((item as { loc: unknown[] }).loc.slice(1).join('.') || '')
            : '';
          const msg = String((item as { msg: unknown }).msg);
          return loc ? `${loc}: ${msg}` : msg;
        }
        return typeof item === 'string' ? item : '';
      })
      .filter(Boolean);
    if (messages.length > 0) return messages.join('；');
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  if (!response.ok) {
    const fallback = `请求失败（HTTP ${response.status}）`;
    throw new ApiError(response.status, extractErrorMessage(parsed, fallback));
  }
  return parsed as T;
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health');
}

export function listRuleSets(): Promise<RuleSetResponse[]> {
  return request<RuleSetResponse[]>('/rule-sets');
}

export function getRuleSet(ruleSetId: string): Promise<RuleSetDetail> {
  return request<RuleSetDetail>(`/rule-sets/${ruleSetId}`);
}

export function createRuleSet(body: RuleSetCreate): Promise<RuleSetDetail> {
  return request<RuleSetDetail>('/rule-sets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function updateRuleItem(
  ruleItemId: string,
  body: RuleItemUpdate,
): Promise<RuleItemResponse> {
  return request<RuleItemResponse>(`/rule-items/${ruleItemId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function checkBatch(
  files: File[],
  ruleSetId: string,
  batchName?: string,
): Promise<BatchDetail> {
  const form = new FormData();
  for (const file of files) {
    form.append('files', file);
  }
  form.append('rule_set_id', ruleSetId);
  const trimmed = batchName?.trim();
  if (trimmed) {
    form.append('batch_name', trimmed);
  }
  return request<BatchDetail>('/batches/check', {
    method: 'POST',
    body: form,
  });
}

export function listBatches(): Promise<BatchSummary[]> {
  return request<BatchSummary[]>('/batches');
}

export function getBatch(
  batchId: string,
  params?: { verdict?: Verdict | null; q?: string },
): Promise<BatchDetail> {
  const search = new URLSearchParams();
  if (params?.verdict) search.set('verdict', params.verdict);
  if (params?.q?.trim()) search.set('q', params.q.trim());
  const qs = search.toString();
  return request<BatchDetail>(`/batches/${batchId}${qs ? `?${qs}` : ''}`);
}

export function getCheckRun(runId: string): Promise<CheckRunDetail> {
  return request<CheckRunDetail>(`/check-runs/${runId}`);
}

export function recheckPaper(
  paperId: string,
  ruleSetId: string,
): Promise<CheckRunDetail> {
  return request<CheckRunDetail>(`/papers/${paperId}/recheck`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rule_set_id: ruleSetId }),
  });
}

export function getStatsOverview(): Promise<StatsOverview> {
  return request<StatsOverview>('/stats/overview');
}
