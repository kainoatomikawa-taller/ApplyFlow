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

/**
 * What the employer asked for, as the backend extracted it from the
 * posting. Drives the "what was tailored for this job" panel — it is the
 * only place the UI can say which of the job's own asks a document speaks
 * to. Never evidence about the candidate (see `ProvenanceGuard`): the UI
 * reports coverage, it never claims a requirement as experience.
 */
export interface JobRequirements {
  degree_level: string | null;
  degree_required: boolean | null;
  clearance_level: string | null;
  clearance_required: boolean | null;
  remote_type: string | null;
  work_authorization: string | null;
  min_years_experience: number | null;
  max_years_experience: number | null;
  locations: string[];
  required_skills: string[];
  preferred_skills: string[];
  preferences: string[];
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
  requirements: JobRequirements | null;
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

// ---- Gap resolution -------------------------------------------------------

export interface GapResolutionQuestion {
  gap: string;
  question: string;
}

/**
 * A gap the backend did not ask about, because an answer the candidate gave
 * on an earlier application already covers it. Deliberately carries no
 * answer text — only the pointer and the score that justified the match
 * (see `AlreadyAnsweredGapResponse`), so the UI can say "already answered"
 * without redisplaying sensitive stored answers.
 */
export interface AlreadyAnsweredGap {
  gap: string;
  answer_memory_id: string;
  similarity_score: number;
}

export interface GapResolutionQuestions {
  questions: GapResolutionQuestion[];
  already_answered: AlreadyAnsweredGap[];
}

/**
 * `captured: false` is a decline, not a failure — the candidate had nothing
 * to add and the gap was cleanly omitted with nothing stored (see
 * `GapAnswerPolicy`).
 */
export interface ResolvedGapAnswer {
  gap: string;
  captured: boolean;
  answer_memory_id: string | null;
}

// ---- Generated documents --------------------------------------------------

export type DocumentKind = 'tailored_resume' | 'cover_letter';

/** One line the provenance guard removed, and the terms nothing backed. */
export interface ProvenanceViolation {
  line: string;
  unsupported_terms: string[];
}

export interface GuardedDocument {
  document_id: string;
  job_posting_id: string;
  document_kind: DocumentKind;
  content: string;
  version: number;
  backing_sources: string[];
  violations: ProvenanceViolation[];
}

export interface ResumeSection {
  heading: string;
  lines: string[];
}

export interface AtsSafetyViolation {
  rule: string;
  detail: string;
  line: string;
  line_number: number;
}

export interface ResumeExports {
  text: string;
  pdf_base64: string;
  pdf_byte_size: number;
  contact_lines: string[];
  sections: ResumeSection[];
}

export interface TailoredResume {
  document: GuardedDocument;
  exports: ResumeExports;
  ats_safety_violations: AtsSafetyViolation[];
}

/**
 * A check on the application page that only the candidate can pass: a
 * sign-in wall, a CAPTCHA, or a request for their signature.
 *
 * `instruction` is what to show them — it says what to do next, not merely
 * what went wrong. `evidence` is what the backend actually saw, so a
 * hand-off is checkable rather than an assertion. The two flags are
 * different consequences and must not be collapsed: `stopped_autofill`
 * means nothing was filled at all, while `blocks_submission` means the
 * form was filled but cannot be sent from here.
 */
export interface ApplicationBoundary {
  kind: 'login' | 'captcha' | 'signature';
  evidence: string;
  instruction: string;
  stopped_autofill: boolean;
  blocks_submission: boolean;
}

/**
 * One field on the application form and what became of it.
 *
 * `is_sensitive` / `sensitivity` / `requires_confirmation` are sent by the
 * backend precisely so this UI never infers sensitivity from a field's
 * name — an inference that, gone wrong, renders a visa declaration as an
 * ordinary text box.
 */
export interface AutofilledField {
  field_id: string;
  label: string;
  kind: string;
  required: boolean;
  outcome: 'filled' | 'attached' | 'surfaced' | 'not_accepted' | 'failed';
  slot: string | null;
  value: string | null;
  is_derived: boolean;
  reason: string | null;
  detail: string | null;
  is_sensitive: boolean;
  sensitivity: 'legal_attestation' | 'voluntary_self_id' | null;
  requires_confirmation: boolean;
  answered_by_candidate: boolean;
}

/** A filled application form, as the review screen receives it. */
export interface ApplicationAutofillReport {
  job_posting_id: string;
  apply_url: string;
  ats_provider: string;
  fields: AutofilledField[];
  screenshot_png_base64: string | null;
  boundaries: ApplicationBoundary[];
  review_session_id: string | null;
  review_expires_at: string | null;
  requires_handoff: boolean;
  can_be_submitted_here: boolean;
  /** The submission gates, named by the backend rather than re-derived here. */
  fields_awaiting_confirmation: string[];
  unanswered_required_fields: string[];
}

/**
 * What happened when the application was sent. `is_confirmed_sent` is the
 * field to trust: the button was pressed either way, and only the absence
 * of a post-press boundary means the portal took the application.
 */
export interface ApplicationSubmissionReceipt {
  job_posting_id: string;
  submitted_at: string;
  pressed_control: string;
  final_url: string;
  confirmation_excerpt: string;
  screenshot_png_base64: string | null;
  outstanding_boundaries: ApplicationBoundary[];
  is_confirmed_sent: boolean;
}
