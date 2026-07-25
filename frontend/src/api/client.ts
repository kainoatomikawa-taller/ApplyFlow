import { getAccessToken } from './accessToken';
import type {
  ApplicationAutofillReport,
  ApplicationSubmissionReceipt,
  CreateApplicationInput,
  DocumentKind,
  FeedbackRating,
  GapResolutionQuestions,
  GuardedDocument,
  HealthStatus,
  JobApplication,
  JobMatchFeedback,
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
    // The autofill routes refuse with an object detail, because a hand-off
    // carries boundaries and a blocked submission carries the field names
    // the candidate has to deal with. The message is the readable half.
    if (parsed.detail && typeof parsed.detail === 'object') {
      const message = (parsed.detail as { message?: unknown }).message;
      if (typeof message === 'string') return message;
    }
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
   * Fill this posting's application form in a real browser and park it for
   * review. Never submits: sending is a separate call the candidate makes
   * (`submitAutofilledApplication`).
   */
  autofillApplication(jobPostingId: string): Promise<ApplicationAutofillReport> {
    return request<ApplicationAutofillReport>(
      `/api/job-postings/${jobPostingId}/autofill`,
      { method: 'POST' },
    );
  },

  /**
   * Write the candidate's own answer into one field of the parked form —
   * the company's screening questions, and EEO self-identification, which
   * reaches a form through this call or not at all. Returns the whole
   * updated report, since an answer can clear the last thing blocking
   * submission.
   */
  answerAutofillField(
    reviewSessionId: string,
    fieldId: string,
    value: string,
  ): Promise<ApplicationAutofillReport> {
    return request<ApplicationAutofillReport>(
      `/api/autofill-sessions/${reviewSessionId}/fields/${fieldId}`,
      { method: 'POST', body: JSON.stringify({ value }) },
    );
  },

  /**
   * Send the reviewed application. `confirmedFieldIds` are the sensitive
   * values the candidate has looked at and approved; the backend refuses
   * the submission without them, so this is never defaulted here.
   */
  submitAutofilledApplication(
    reviewSessionId: string,
    confirmedFieldIds: string[],
    submitControlLabel?: string,
  ): Promise<ApplicationSubmissionReceipt> {
    return request<ApplicationSubmissionReceipt>(
      `/api/autofill-sessions/${reviewSessionId}/submit`,
      {
        method: 'POST',
        body: JSON.stringify({
          confirmed_field_ids: confirmedFieldIds,
          submit_control_label: submitControlLabel ?? null,
        }),
      },
    );
  },

  /** Abandon a parked review without sending it, closing its browser. */
  async discardAutofillReview(reviewSessionId: string): Promise<void> {
    const token = getAccessToken();
    const response = await fetch(
      `${BASE_URL}/api/autofill-sessions/${reviewSessionId}`,
      {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      },
    );
    if (!response.ok) {
      throw new Error(
        `Request failed (${response.status}): ${await errorText(response)}`,
      );
    }
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
