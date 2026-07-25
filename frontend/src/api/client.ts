import { getAccessToken } from './accessToken';
import type {
  CreateApplicationInput,
  DocumentKind,
  FeedbackRating,
  GapResolutionQuestions,
  GuardedDocument,
  HealthStatus,
  JobApplication,
  JobMatchFeedback,
  PortalHandoff,
  PortalHandoffList,
  PortalInspection,
  RankedJob,
  ResolvedGapAnswer,
  TailoredResume,
} from '../types';

const BASE_URL = import.meta.env.VITE_API_URL ?? '';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAccessToken();
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    throw new Error(
      `Request failed (${response.status}): ${await errorText(response)}`,
    );
  }
  return (await response.json()) as T;
}

/**
 * FastAPI puts the message in `detail`; anything else (a proxy error page, a
 * crash) is shown as-is rather than as "[object Object]".
 */
async function errorText(response: Response): Promise<string> {
  const body = await response.text();
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    if (typeof parsed.detail === 'string') return parsed.detail;
  } catch {
    // Not JSON — fall through to the raw body.
  }
  return body;
}

export const applyFlowApi = {
  getHealth(): Promise<HealthStatus> {
    return request<HealthStatus>('/health');
  },

  listApplications(email: string): Promise<JobApplication[]> {
    return request<JobApplication[]>(
      `/api/applications?candidate_email=${encodeURIComponent(email)}`,
    );
  },

  createApplication(input: CreateApplicationInput): Promise<JobApplication> {
    return request<JobApplication>('/api/applications', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  submitApplication(id: string): Promise<JobApplication> {
    return request<JobApplication>(`/api/applications/${id}/submit`, {
      method: 'POST',
    });
  },

  analyzeApplication(id: string, resumeText: string): Promise<JobApplication> {
    return request<JobApplication>(`/api/applications/${id}/analyze`, {
      method: 'POST',
      body: JSON.stringify({ resume_text: resumeText }),
    });
  },

  listMatchedJobs(limit = 100): Promise<RankedJob[]> {
    return request<RankedJob[]>(`/api/job-postings/matches?limit=${limit}`);
  },

  submitJobMatchFeedback(
    jobPostingId: string,
    rating: FeedbackRating,
    scoreAtFeedback: number,
  ): Promise<JobMatchFeedback> {
    return request<JobMatchFeedback>(`/api/job-postings/${jobPostingId}/feedback`, {
      method: 'POST',
      body: JSON.stringify({ rating, score_at_feedback: scoreAtFeedback }),
    });
  },

  /**
   * The questions to actually ask for this job's gaps, plus the gaps that
   * were suppressed because a remembered answer already covers them.
   */
  generateGapQuestions(gaps: string[]): Promise<GapResolutionQuestions> {
    return request<GapResolutionQuestions>('/api/gap-resolution/questions', {
      method: 'POST',
      body: JSON.stringify({ gaps }),
    });
  },

  /**
   * Capture one answer. An empty or "nothing to add" answer is a decline:
   * the backend stores nothing and returns `captured: false`.
   */
  resolveGapAnswer(
    gap: string,
    question: string,
    answer: string,
  ): Promise<ResolvedGapAnswer> {
    return request<ResolvedGapAnswer>('/api/gap-resolution/answers', {
      method: 'POST',
      body: JSON.stringify({ gap, question, answer }),
    });
  },

  generateTailoredResume(jobPostingId: string): Promise<TailoredResume> {
    return request<TailoredResume>(
      `/api/job-postings/${jobPostingId}/tailored-resume`,
      { method: 'POST' },
    );
  },

  generateCoverLetter(jobPostingId: string): Promise<GuardedDocument> {
    return request<GuardedDocument>(`/api/job-postings/${jobPostingId}/cover-letter`, {
      method: 'POST',
    });
  },

  /**
   * Open the posting's application portal and report what it presents. A
   * portal with a hard boundary comes back with `is_handed_off: true` and no
   * fields — that is a normal 200, not a failure: ApplyFlow stopped where it
   * should.
   */
  inspectPortal(jobPostingId: string): Promise<PortalInspection> {
    return request<PortalInspection>('/api/portal/inspections', {
      method: 'POST',
      body: JSON.stringify({ job_posting_id: jobPostingId }),
    });
  },

  listPortalHandoffs(openOnly = false, limit = 100): Promise<PortalHandoffList> {
    return request<PortalHandoffList>(
      `/api/portal/handoffs?open_only=${openOnly}&limit=${limit}`,
    );
  },

  /**
   * Tell ApplyFlow the human-only step is done. This records the candidate's
   * word for it — the next inspection is what re-reads the portal, and raises
   * a fresh hand-off if the boundary is still there.
   */
  resumePortalHandoff(handoffId: string, note = ''): Promise<PortalHandoff> {
    return request<PortalHandoff>(`/api/portal/handoffs/${handoffId}/resume`, {
      method: 'POST',
      body: JSON.stringify({ note }),
    });
  },

  /** The candidate is finishing this application themselves. */
  abandonPortalHandoff(handoffId: string, note = ''): Promise<PortalHandoff> {
    return request<PortalHandoff>(`/api/portal/handoffs/${handoffId}/abandon`, {
      method: 'POST',
      body: JSON.stringify({ note }),
    });
  },

  /**
   * Store the candidate's edited text as the next version of this document.
   * The edit goes back through the provenance guard, so the returned
   * document is what survived it — which is not always what was sent.
   */
  reviseDocument(
    jobPostingId: string,
    documentKind: DocumentKind,
    content: string,
  ): Promise<GuardedDocument> {
    return request<GuardedDocument>(
      `/api/job-postings/${jobPostingId}/documents/${documentKind}/revisions`,
      { method: 'POST', body: JSON.stringify({ content }) },
    );
  },
};
