import { API_BASE, apiRequest } from './client';
import type {
  AnnotatedPdfExportResponse,
  AutoFixRequest,
  DocumentSettingsRequest,
  PageMode,
  ParagraphEditRequest,
  ParagraphEditResponse,
  RevisionSessionDetail,
} from '../types/revisions';

export function createOrResumeRevision(
  runId: string,
  forceNew = false,
): Promise<RevisionSessionDetail> {
  const qs = forceNew ? '?force_new=true' : '';
  return apiRequest<RevisionSessionDetail>(`/check-runs/${runId}/revisions${qs}`, {
    method: 'POST',
  });
}

export function getRevisionSession(sessionId: string): Promise<RevisionSessionDetail> {
  return apiRequest<RevisionSessionDetail>(`/revisions/${sessionId}`);
}

export function editRevisionParagraph(
  sessionId: string,
  paragraphIndex: number,
  body: ParagraphEditRequest,
): Promise<ParagraphEditResponse> {
  return apiRequest<ParagraphEditResponse>(
    `/revisions/${sessionId}/paragraphs/${paragraphIndex}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  );
}

export function updateDocumentSettings(
  sessionId: string,
  body: DocumentSettingsRequest,
): Promise<RevisionSessionDetail> {
  return apiRequest<RevisionSessionDetail>(`/revisions/${sessionId}/document-settings`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function autoFixRevision(
  sessionId: string,
  body: AutoFixRequest = {},
): Promise<RevisionSessionDetail> {
  return apiRequest<RevisionSessionDetail>(`/revisions/${sessionId}/auto-fix`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function exportAnnotatedPdf(
  sessionId: string,
  pageMode: PageMode = 'issues_only',
): Promise<AnnotatedPdfExportResponse> {
  return apiRequest<AnnotatedPdfExportResponse>(
    `/revisions/${sessionId}/export/annotated-pdf`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ page_mode: pageMode }),
    },
  );
}

export function getRevisionDownloadUrl(
  sessionId: string,
  kind: 'docx' | 'annotated_pdf',
): string {
  return `${API_BASE}/revisions/${sessionId}/download/${kind}`;
}
