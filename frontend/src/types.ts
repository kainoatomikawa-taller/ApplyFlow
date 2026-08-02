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
  /**
   * Whether this role is one the candidate already applied to. Always false
   * for the default matches call, which suppresses those entries so the list
   * never nudges a re-application — only a caller that opts in
   * (`include_already_applied`) sees them, flagged.
   */
  already_applied: boolean;
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

// ---- Application portals & hand-offs --------------------------------------

/**
 * A boundary ApplyFlow will not cross on an application portal. Not a list of
 * things the automation has not learned yet: each one is a step where the act
 * itself is the point, so it stays a hand-off however capable the app gets.
 */
export type HardStopKind = 'captcha' | 'electronic_signature' | 'account_wall';

export type HandoffStatus = 'awaiting_user' | 'resumed' | 'abandoned';

/**
 * One detected boundary. `evidence` describes the portal's own page — a script
 * it loaded, a phrase it showed, a field it presented — so the candidate can
 * check the claim against the page themselves. It never contains anything
 * about the candidate.
 */
export interface HardStop {
  kind: HardStopKind;
  refusal_reason: string;
  human_action: string;
  evidence: string[];
}

export interface PortalHandoff {
  id: string;
  job_posting_id: string;
  apply_url: string;
  /** Where automation stopped — the URL to open to finish the step. Often not
   *  the apply URL, since portals redirect. */
  paused_url: string;
  status: HandoffStatus;
  is_open: boolean;
  created_at: string;
  last_detected_at: string;
  resolved_at: string | null;
  resolution_note: string;
  hard_stops: HardStop[];
}

/** One question the portal asks. No handle: nothing here can write to a form. */
export interface PortalField {
  label: string;
  kind: string;
  name: string;
  required: boolean;
  human_only_boundary: HardStopKind | null;
}

/**
 * `is_handed_off` is the only thing to branch on. When it is true, `handoff`
 * is set and `fields` is empty — the backend withholds the form rather than
 * merely flagging it, so a paused portal cannot be filled by accident.
 */
export interface PortalInspection {
  job_posting_id: string;
  apply_url: string;
  landed_url: string;
  is_handed_off: boolean;
  handoff: PortalHandoff | null;
  fields: PortalField[];
  /** Set when this check found the boundary gone and closed an open hand-off
   *  on its own evidence. */
  cleared_handoff_id: string | null;
}

export interface PortalHandoffList {
  handoffs: PortalHandoff[];
  open_count: number;
}

// ---- Review & submit ------------------------------------------------------

/** Who is responsible for the answer currently in a field. */
export type AnswerOrigin = 'unanswered' | 'autofilled' | 'candidate' | 'declined';

export type FieldSensitivity = 'legal_attestation' | 'voluntary_self_id';

export type ReviewStatus = 'in_review' | 'submitted_by_user';

/**
 * One question on the filled application. `needs_decision` is true for every
 * sensitive field the candidate has not settled — the backend clears it only
 * on their own action, so a UI can neither skip the decision nor fake it.
 */
export interface ReviewedAnswer {
  key: string;
  label: string;
  widget_kind: string;
  value: string;
  required: boolean;
  origin: AnswerOrigin;
  slot: string | null;
  sensitivity: FieldSensitivity | null;
  is_sensitive: boolean;
  needs_decision: boolean;
  explanation: string;
}

export type SubmissionBlockerKind = 'pending_sensitive_decision' | 'open_hard_stop';

export interface SubmissionBlocker {
  kind: SubmissionBlockerKind;
  detail: string;
  field_key: string | null;
  field_label: string;
}

export interface ApplicationReview {
  id: string;
  job_posting_id: string;
  /** Where the candidate goes to send it. */
  apply_url: string;
  ats_provider: string;
  status: ReviewStatus;
  is_open: boolean;
  created_at: string;
  answers: ReviewedAnswer[];
  blockers: SubmissionBlocker[];
  /** False while anything in `blockers` stands. The submit button binds to it,
   *  and the submit route re-checks the same rule. */
  can_submit: boolean;
  handoff: PortalHandoff | null;
  /** Required fields with no answer — warnings, not blockers, since `required`
   *  is only as trustworthy as the portal's markup. */
  unanswered_required_keys: string[];
  screenshot_captured: boolean;
  submitted_at: string | null;
  submission_note: string;
}

/** `review` is null only when a hard stop blocked the portal — nothing was
 *  filled, and `handoff` says why. */
export interface OpenApplicationReview {
  job_posting_id: string;
  review: ApplicationReview | null;
  handoff: PortalHandoff | null;
  screenshot_base64: string | null;
}

export type AnswerAction = 'set' | 'confirm' | 'decline';

export interface SubmittedApplicationReview {
  review: ApplicationReview;
  apply_url: string;
}
