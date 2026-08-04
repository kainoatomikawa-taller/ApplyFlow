import { getAccessToken } from './accessToken';
import type {
  AnswerAction,
  ApplicationAutofillReport,
  ApplicationReview,
  ApplicationSubmissionReceipt,
  CreateApplicationInput,
  DocumentKind,
  FeedbackRating,
  GapResolutionQuestions,
  GuardedDocument,
  HealthStatus,
  JobApplication,
  JobMatchFeedback,
  OpenApplicationReview,
  PortalHandoff,
  PortalHandoffList,
  PortalInspection,
  RankedJob,
  ResolvedGapAnswer,
  StoredApplicationDocument,
  SubmittedApplicationReview,
  TailoredResume,
  TrackedApplication,
  TrackedApplicationList,
  TrackedApplicationStatus,
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

  /**
   * The signed-in candidate's applications.
   *
   * Takes no email: the backend reads it from the bearer token. It used to be
   * sent as `?candidate_email=`, which put the address into access logs,
   * browser history, and any `Referer` a third party received — so the
   * parameter is gone rather than relocated. This is a single-user app, so
   * the token's identity is the only one that was ever correct here.
   */
  listApplications(): Promise<JobApplication[]> {
    return request<JobApplication[]>('/api/applications');
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
   * Fill this posting's application form and open a review over it. Supersedes
   * any review still in progress for the job. A portal with a hard boundary
   * comes back with `review: null` and the hand-off attached — a normal 200,
   * because stopping there is correct.
   */
  openApplicationReview(jobPostingId: string): Promise<OpenApplicationReview> {
    return request<OpenApplicationReview>(
      `/api/job-postings/${jobPostingId}/review`,
      { method: 'POST' },
    );
  },

  /** The review in progress for this posting, if there is one (404 if not). */
  getApplicationReview(jobPostingId: string): Promise<ApplicationReview> {
    return request<ApplicationReview>(`/api/job-postings/${jobPostingId}/review`);
  },

  /**
   * Write an answer, approve the one that is there, or decline the field.
   * Returns the whole review: one decision can change what is blocking submit.
   */
  reviseReviewedAnswer(
    reviewId: string,
    fieldKey: string,
    action: AnswerAction,
    value = '',
  ): Promise<ApplicationReview> {
    return request<ApplicationReview>(
      `/api/application-reviews/${reviewId}/answers/${encodeURIComponent(fieldKey)}`,
      { method: 'POST', body: JSON.stringify({ action, value }) },
    );
  },

  /**
   * The candidate submits. Refused (409) while a blocker stands or if the
   * review was already submitted — ApplyFlow never reaches this on its own.
   */
  submitApplicationReview(
    reviewId: string,
    note = '',
  ): Promise<SubmittedApplicationReview> {
    return request<SubmittedApplicationReview>(
      `/api/application-reviews/${reviewId}/submit`,
      { method: 'POST', body: JSON.stringify({ note }) },
    );
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

  /**
   * One archived snapshot by id, with the exact text that was stored.
   *
   * The tracker's rows carry document *references*; this is how one of them is
   * followed to the content. Always by id — never "the newest document for
   * this job", which is a different and later document whenever the candidate
   * has revised one since applying.
   *
   * A 500 here is meaningful rather than a glitch: the backend re-checks the
   * stored digest before serving, so it refuses a snapshot that no longer
   * matches its own hash instead of presenting altered text as what was sent.
   */
  getApplicationDocument(documentId: string): Promise<StoredApplicationDocument> {
    return request<StoredApplicationDocument>(
      `/api/application-documents/${documentId}`,
    );
  },

  /**
   * The tracker: every application the candidate has sent, most recently
   * applied first, each carrying the exact documents that went out with it.
   *
   * `openOnly` asks the backend which are still live rather than filtering
   * here — which statuses count as open is a domain rule, and a copy of it in
   * this client would be one more place for it to fall out of step.
   */
  listTrackedApplications(
    { openOnly = false, limit = 100 } = {},
  ): Promise<TrackedApplicationList> {
    const query = new URLSearchParams({
      open_only: String(openOnly),
      limit: String(limit),
    });
    return request<TrackedApplicationList>(`/api/tracked-applications?${query}`);
  },

  /** Every application this candidate sent to one posting — normally one. */
  listApplicationsForJob(jobPostingId: string): Promise<TrackedApplicationList> {
    return request<TrackedApplicationList>(
      `/api/tracked-applications/by-job/${jobPostingId}`,
    );
  },

  /** One sent application with its full status history. */
  getTrackedApplication(applicationId: string): Promise<TrackedApplication> {
    return request<TrackedApplication>(
      `/api/tracked-applications/${applicationId}`,
    );
  },

  /**
   * Record what became of one application. Returns the whole updated record,
   * including the next set of `allowed_next_statuses` — the transition just
   * changed which moves are legal, and the caller re-renders from what was
   * stored rather than from what it assumed.
   *
   * `note` is the candidate's own word on why; empty means they did not say,
   * which is not the same as a note saying nothing.
   */
  updateApplicationStatus(
    applicationId: string,
    status: TrackedApplicationStatus,
    note = '',
  ): Promise<TrackedApplication> {
    return request<TrackedApplication>(
      `/api/tracked-applications/${applicationId}/status`,
      { method: 'PATCH', body: JSON.stringify({ status, note }) },
    );
  },
};
