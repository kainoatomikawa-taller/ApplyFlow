import type {
  CreateApplicationInput,
  FeedbackRating,
  HealthStatus,
  JobApplication,
  JobMatchFeedback,
  RankedJob,
} from '../types';

const BASE_URL = import.meta.env.VITE_API_URL ?? '';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Request failed (${response.status}): ${detail}`);
  }
  return (await response.json()) as T;
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
};
