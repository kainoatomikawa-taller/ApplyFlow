import { useCallback, useEffect, useState } from 'react';
import { applyFlowApi } from '../api/client';
import { HandoffNotice } from './HandoffNotice';
import type {
  AnswerOrigin,
  ApplicationReview,
  PortalHandoff,
  ReviewedAnswer,
} from '../types';

interface Props {
  jobPostingId: string;
  jobTitle: string;
  company: string;
}

const ORIGIN_LABELS: Record<AnswerOrigin, string> = {
  autofilled: 'filled by ApplyFlow',
  candidate: 'your answer',
  declined: 'you declined',
  unanswered: 'not answered',
};

/** Widgets that take more than a line, so the editor gives them room. */
const LONG_WIDGETS = new Set(['textarea']);

/**
 * The review-and-submit screen: the filled application, every field editable,
 * and a submit button only the candidate can press.
 *
 * Four things this screen is built around.
 *
 * **Everything is shown, in the portal's own order.** Filled fields, fields
 * ApplyFlow refused to guess at, and the reason for each. A review that showed
 * only the problems would leave the candidate approving an application they
 * never actually read.
 *
 * **Every field is editable.** Including the ones ApplyFlow filled — that is
 * the whole point of a review. An edit is saved explicitly, so what is stored
 * is never ahead of what the candidate has decided.
 *
 * **Sensitive fields cannot be passed over.** Legal declarations and EEO
 * self-identification each need an explicit decision — confirm, change, or
 * decline — and the backend, not this screen, is what enforces it: `can_submit`
 * comes from the server and the submit route re-checks the same rule. Declining
 * is always offered, because a gate with only one way through is coercion.
 *
 * **ApplyFlow does not submit.** It cannot press a portal's submit button (the
 * browser harness exposes no way to), and this screen never implies otherwise.
 * Pressing submit here records the candidate's decision, checks that nothing is
 * unsettled, and then sends them to the portal to complete it — with their
 * approved answers in front of them.
 */
export function ReviewAndSubmit({ jobPostingId, jobTitle, company }: Props) {
  const [review, setReview] = useState<ApplicationReview | null>(null);
  const [handoff, setHandoff] = useState<PortalHandoff | null>(null);
  const [screenshot, setScreenshot] = useState<string | null>(null);
  const [handoffNote, setHandoffNote] = useState('');
  const [submitNote, setSubmitNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const absorb = (next: ApplicationReview) => {
    setReview(next);
    setHandoff(next.handoff);
  };

  // A review already in progress is picked up on mount, so leaving the page
  // and coming back does not lose the decisions already made — least of all
  // the sensitive ones, which nobody should have to make twice.
  const loadExisting = useCallback(async () => {
    try {
      absorb(await applyFlowApi.getApplicationReview(jobPostingId));
    } catch {
      // 404 is the ordinary case: nothing has been filled for this job yet.
    } finally {
      setLoaded(true);
    }
  }, [jobPostingId]);

  useEffect(() => {
    void loadExisting();
  }, [loadExisting]);

  const fill = async () => {
    setBusy(true);
    setError(null);
    try {
      const opened = await applyFlowApi.openApplicationReview(jobPostingId);
      setReview(opened.review);
      setHandoff(opened.handoff ?? opened.review?.handoff ?? null);
      setScreenshot(opened.screenshot_base64);
      setSubmitNote('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setBusy(false);
    }
  };

  const revise = async (
    key: string,
    action: 'set' | 'confirm' | 'decline',
    value = '',
  ) => {
    if (!review) return;
    setBusy(true);
    setError(null);
    try {
      absorb(await applyFlowApi.reviseReviewedAnswer(review.id, key, action, value));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (!review) return;
    setBusy(true);
    setError(null);
    try {
      const submitted = await applyFlowApi.submitApplicationReview(
        review.id,
        submitNote,
      );
      absorb(submitted.review);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setBusy(false);
    }
  };

  const resolveHandoff = async (action: 'resume' | 'abandon') => {
    if (!handoff) return;
    setBusy(true);
    setError(null);
    try {
      setHandoff(
        action === 'resume'
          ? await applyFlowApi.resumePortalHandoff(handoff.id, handoffNote)
          : await applyFlowApi.abandonPortalHandoff(handoff.id, handoffNote),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card review-submit">
      <div className="handoff-header">
        <div>
          <h3>Review &amp; submit</h3>
          <p className="quiet">
            ApplyFlow fills what it can from your record and never sends anything.
            You check it, change anything you like, and submit it yourself.
          </p>
        </div>
        <button type="button" className="secondary" disabled={busy} onClick={fill}>
          {busy ? 'Working…' : review ? 'Fill again' : 'Fill the application'}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {handoff !== null && (
        <HandoffNotice
          handoff={handoff}
          note={handoffNote}
          busy={busy}
          onNoteChange={setHandoffNote}
          onResolve={resolveHandoff}
        />
      )}

      {review === null ? (
        loaded &&
        handoff === null && (
          <p className="muted">
            Nothing filled for {jobTitle} at {company} yet. Filling reads the form
            and writes your answers into it — it never submits.
          </p>
        )
      ) : (
        <ReviewBody
          review={review}
          screenshot={screenshot}
          submitNote={submitNote}
          busy={busy}
          onSubmitNoteChange={setSubmitNote}
          onRevise={revise}
          onSubmit={submit}
        />
      )}
    </section>
  );
}

interface ReviewBodyProps {
  review: ApplicationReview;
  screenshot: string | null;
  submitNote: string;
  busy: boolean;
  onSubmitNoteChange: (note: string) => void;
  onRevise: (key: string, action: 'set' | 'confirm' | 'decline', value?: string) => void;
  onSubmit: () => void;
}

function ReviewBody({
  review,
  screenshot,
  submitNote,
  busy,
  onSubmitNoteChange,
  onRevise,
  onSubmit,
}: ReviewBodyProps) {
  const filled = review.answers.filter((a) => a.origin !== 'unanswered').length;
  const unansweredRequired = new Set(review.unanswered_required_keys);

  if (!review.is_open) {
    return <SubmittedSummary review={review} />;
  }

  return (
    <>
      <p className="quiet">
        {review.answers.length} question{review.answers.length === 1 ? '' : 's'} on
        this {review.ats_provider} form · {filled} answered ·{' '}
        {review.answers.filter((a) => a.is_sensitive).length} sensitive
      </p>

      {review.blockers.length > 0 && (
        <div className="notice notice-warn">
          <strong>Before you can submit:</strong>
          <ul>
            {review.blockers.map((blocker, index) => (
              <li key={`${blocker.kind}-${blocker.field_key ?? index}`}>
                {blocker.detail}
              </li>
            ))}
          </ul>
        </div>
      )}

      {unansweredRequired.size > 0 && (
        <div className="notice notice-info">
          {unansweredRequired.size} field
          {unansweredRequired.size === 1 ? '' : 's'} the portal marks required
          {unansweredRequired.size === 1 ? ' has' : ' have'} no answer yet. That is
          a warning, not a block — ApplyFlow reads "required" from the portal&apos;s
          markup and can be wrong about it.
        </div>
      )}

      <ol className="review-answers">
        {review.answers.map((answer) => (
          <AnswerRow
            key={answer.key}
            answer={answer}
            busy={busy}
            missingRequired={unansweredRequired.has(answer.key)}
            onRevise={onRevise}
          />
        ))}
      </ol>

      {screenshot !== null && (
        <details className="review-proof">
          <summary className="quiet">The filled form, as ApplyFlow left it</summary>
          <img src={`data:image/png;base64,${screenshot}`} alt="The filled form" />
        </details>
      )}

      <div className="review-submit-box">
        <div className="field">
          <label htmlFor={`submit-note-${review.id}`}>
            Note for your own records (optional)
          </label>
          <input
            id={`submit-note-${review.id}`}
            value={submitNote}
            placeholder="e.g. mentioned the referral from Priya"
            onChange={(event) => onSubmitNoteChange(event.target.value)}
          />
        </div>
        <button type="button" disabled={busy || !review.can_submit} onClick={onSubmit}>
          Submit this application
        </button>
        <p className="quiet">
          {review.can_submit
            ? 'This records your submission and takes you to the portal to send it. ApplyFlow does not press submit for you.'
            : 'Settle everything above first — ApplyFlow will not hand over an application with an unanswered legal question.'}
        </p>
      </div>
    </>
  );
}

interface AnswerRowProps {
  answer: ReviewedAnswer;
  busy: boolean;
  missingRequired: boolean;
  onRevise: (key: string, action: 'set' | 'confirm' | 'decline', value?: string) => void;
}

function AnswerRow({ answer, busy, missingRequired, onRevise }: AnswerRowProps) {
  const [draft, setDraft] = useState(answer.value);

  // The stored answer is the source of truth: when it changes underneath (a
  // decline, a save, a re-fill) the editor follows it rather than holding a
  // stale draft the candidate would think was saved.
  useEffect(() => setDraft(answer.value), [answer.value]);

  const dirty = draft !== answer.value;
  const long = LONG_WIDGETS.has(answer.widget_kind);
  const inputId = `answer-${answer.key}`;

  return (
    <li
      className={[
        'review-answer',
        answer.needs_decision ? 'needs-decision' : '',
        answer.is_sensitive ? 'sensitive' : '',
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <label htmlFor={inputId}>
        {answer.label || <span className="quiet">(unlabelled field)</span>}
        {answer.required && <span className="pill pill-warn">required</span>}
        {answer.sensitivity === 'legal_attestation' && (
          <span className="pill pill-warn">legal declaration</span>
        )}
        {answer.sensitivity === 'voluntary_self_id' && (
          <span className="pill pill-warn">voluntary — yours to decide</span>
        )}
        <span className={`pill origin-${answer.origin}`}>
          {ORIGIN_LABELS[answer.origin]}
        </span>
      </label>

      {answer.explanation && <p className="quiet">{answer.explanation}</p>}

      {long ? (
        <textarea
          id={inputId}
          rows={5}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
      ) : (
        <input
          id={inputId}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
      )}

      <div className="review-answer-actions">
        {dirty && (
          <button
            type="button"
            disabled={busy}
            onClick={() => onRevise(answer.key, 'set', draft)}
          >
            Save
          </button>
        )}
        {answer.needs_decision && answer.value !== '' && (
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => onRevise(answer.key, 'confirm')}
          >
            Confirm this answer
          </button>
        )}
        {answer.needs_decision && (
          <button
            type="button"
            className="link-button"
            disabled={busy}
            onClick={() => onRevise(answer.key, 'decline')}
          >
            Leave blank / prefer not to say
          </button>
        )}
        {missingRequired && (
          <span className="quiet">the portal marks this one required</span>
        )}
      </div>
    </li>
  );
}

function SubmittedSummary({ review }: { review: ApplicationReview }) {
  return (
    <>
      <div className="notice notice-ok">
        <strong>You submitted this application.</strong> Recorded{' '}
        {review.submitted_at !== null
          ? new Date(review.submitted_at).toLocaleString()
          : 'just now'}
        . The answers below are what you approved — they are kept as the record
        and can no longer be edited.
      </div>
      <p>
        <a href={review.apply_url} target="_blank" rel="noreferrer">
          Open the portal to send it, if you have not already
        </a>
      </p>
      {review.submission_note && (
        <p className="quiet">Your note: {review.submission_note}</p>
      )}
      <ol className="review-answers submitted">
        {review.answers.map((answer) => (
          <li key={answer.key} className="review-answer">
            <span className="review-answer-label">
              {answer.label || '(unlabelled field)'}
            </span>
            <span className="review-answer-value">
              {answer.value || <span className="quiet">left blank</span>}
            </span>
          </li>
        ))}
      </ol>
    </>
  );
}
