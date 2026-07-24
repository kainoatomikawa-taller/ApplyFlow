export type ApplicationStatus =
  'draft' | 'applied' | 'interviewing' | 'offer' | 'rejected' | 'withdrawn';

export interface JobApplication {
  id: string;
  candidate_email: string;
  company_name: string;
  role_title: string;
  status: ApplicationStatus;
  match_score: number | null;
  tailored_cover_letter: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateApplicationInput {
  candidate_email: string;
  company_name: string;
  role_title: string;
  job_description: string;
}

export interface HealthStatus {
  status: string;
  service: string;
  environment: string;
}

export interface JobPosting {
  id: string;
  source: string;
  company: string;
  title: string;
  apply_url: string;
  location: string | null;
  is_remote: boolean;
  status: string;
  posted_at: string | null;
  created_at: string;
}

export interface RankedJob {
  job_posting: JobPosting;
  score: number;
  rationale: string;
  gaps: string[];
}

export type FeedbackRating = 'thumbs_up' | 'thumbs_down';

export interface JobMatchFeedback {
  id: string;
  user_id: string;
  job_posting_id: string;
  rating: FeedbackRating;
  score_at_feedback: number;
  created_at: string;
}
