import { useState } from 'react';
import { applyFlowApi } from '../api/client';
import type {
  ApplicationAutofillReport,
  ApplicationSubmissionReceipt,
  AutofilledField,
  RankedJob,
} from '../types';

interface Props {
  job: RankedJob;
}

/** What each outcome means, in the candidate's terms rather than the API's. */
const OUTCOME_LABELS: Record<AutofilledField['outcome'], string> = {
  filled: 'Filled',
  attached: 'Attached',
  surfaced: 'Needs you',
  not_accepted: 'Form refused it',
  failed: 'Could not fill',
};

/**
 * Why a field was left alone. Phrased as what the candidate can do about
 * it, because "unrecognized" and "no_profile_data" call for completely
 * different actions and a UI that showed the raw code would leave them to
 * guess which.
 */
const REASON_LABELS: Record<string, string> = {
  unrecognized: "This is the company's own question — yours to answer.",
  no_profile_data: 'Your profile has nothing for this field yet.',
  requires_candidate_answer:
    'Voluntary self-identification. ApplyFlow never answers this for you — disclosing is your decision on every application.',
  sensitive_data_not_attested:
    'This answer is on file but you did not state it yourself. Confirm it on your profile and it can be filled next time.',
  sensitive_answer_not_derivable:
    'Your record does not settle this legal question exactly, and an approximate answer is not acceptable here.',
  requires_candidate_signature:
    'This is where you sign. Nobody can sign for you, so it stays empty.',
  unsupported_field_kind: 'This widget cannot take the data ApplyFlow has.',
  document_not_generated: 'Generate this document above first, then autofill again.',
  value_too_long: 'The value is longer than this field accepts.',
};

const SENSITIVITY_LABELS: Record<string, string> = {
  legal_attestation: 'Legal declaration',
  voluntary_self_id: 'Voluntary self-ID',
};

/** Whether this field is still waiting for the candidate to type something. */
function needsAnAnswer(field: AutofilledField): boolean {
  return field.outcome !== 'filled' && field.outcome !== 'attached';
}

/**
 * Fill this job's application form, review it, and submit it.
 *
 * The screen is the human half of "nothing is submitted unattended". The
 * backend enforces the gates — it refuses to press Submit while a legal
 * answer is unconfirmed or a required question is blank — and this screen's
 * job is to make those gates answerable rather than to re-implement them.
 * Both lists come from the API (`fields_awaiting_confirmation`,
 * `unanswered_required_fields`), so what the Submit button waits for is
 * exactly what the backend waits for; a UI computing them itself would
 * eventually offer a button that cannot work.
 *
 * Three things it deliberately shows in full:
 *
 * - **every field, in page order**, filled or not, because a list of five
 *   orphaned questions is much harder to answer than the form they came
 *   from — and a field quietly dropped from the report reads as approval;
 * - **the values that were written**, since reviewing an application you
 *   cannot see is not reviewing it;
 * - **the screenshot**, which is the only evidence here that does not come
 *   from the same code that filled the form.
 */
export function AutofillReview({ job }: Props) {
  const [report, setReport] = useState<ApplicationAutofillReport | null>(null);
  const [receipt, setReceipt] = useState<ApplicationSubmissionReceipt | null>(null);
  const [confirmed, setConfirmed] = useState<string[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reviewId = report?.review_session_id ?? null;
  const awaitingConfirmation = report?.fields_awaiting_confirmation ?? [];
  const unanswered = report?.unanswered_required_fields ?? [];
  const allConfirmed = awaitingConfirmation.every((id) => confirmed.includes(id));
  const canSubmit =
    report !== null &&
    reviewId !== null &&
    report.can_be_submitted_here &&
    allConfirmed &&
    unanswered.length === 0 &&
    receipt === null;

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setBusy(false);
    }
  };

  const autofill = () =>
    run(async () => {
      setReceipt(null);
      setConfirmed([]);
      setDrafts({});
      setReport(await applyFlowApi.autofillApplication(job.job_posting.id));
    });

  const answer = (fieldId: string) =>
    run(async () => {
      if (reviewId === null) return;
      const value = (drafts[fieldId] ?? '').trim();
      if (!value) return;
      setReport(await applyFlowApi.answerAutofillField(reviewId, fieldId, value));
      setDrafts((prev) => ({ ...prev, [fieldId]: '' }));
    });

  const submit = () =>
    run(async () => {
      if (reviewId === null) return;
      setReceipt(await applyFlowApi.submitAutofilledApplication(reviewId, confirmed));
      setReport((prev) => (prev ? { ...prev, review_session_id: null } : prev));
    });

  const discard = () =>
    run(async () => {
      if (reviewId === null) return;
      await applyFlowApi.discardAutofillReview(reviewId);
      setReport(null);
      setConfirmed([]);
    });

  const toggleConfirmation = (fieldId: string) =>
    setConfirmed((prev) =>
      prev.includes(fieldId) ? prev.filter((id) => id !== fieldId) : [...prev, fieldId],
    );

  return (
    <section className="card autofill-review">
      <div className="document-header">
        <h3>Apply</h3>
        <div className="document-actions">
          <button type="button" onClick={autofill} disabled={busy}>
            {report ? 'Fill again' : 'Fill this application'}
          </button>
          {reviewId && receipt === null && (
            <button
              type="button"
              className="secondary"
              onClick={discard}
              disabled={busy}
            >
              Discard
            </button>
          )}
        </div>
      </div>

      <p className="quiet">
        ApplyFlow opens {job.job_posting.company}&apos;s form in a browser and fills
        what it can from your profile and the documents above. It never sends anything —
        you review it here and press Submit.
      </p>

      {error && <p className="error">{error}</p>}

      {report?.boundaries.map((boundary) => (
        <div className="notice notice-warn" key={boundary.kind}>
          <strong>
            {boundary.stopped_autofill
              ? 'Nothing was filled'
              : 'You will need to finish this one yourself'}
          </strong>
          <p>{boundary.instruction}</p>
          <p className="quiet">What ApplyFlow saw: {boundary.evidence}</p>
          <p>
            <a href={report.apply_url} target="_blank" rel="noreferrer">
              Open the application form
            </a>
          </p>
        </div>
      ))}

      {report && report.fields.length > 0 && (
        <>
          <p className="section-label">
            The form, as it now stands ({report.ats_provider})
          </p>
          <ul className="autofill-fields">
            {report.fields.map((field) => (
              <li key={field.field_id} className={`autofill-field ${field.outcome}`}>
                <div className="autofill-field-header">
                  <span className="autofill-label">
                    {field.label || <em>unlabelled field</em>}
                    {field.required && <span className="required-mark"> *</span>}
                  </span>
                  <span
                    className={`pill ${needsAnAnswer(field) ? 'pill-warn' : 'pill-ok'}`}
                  >
                    {OUTCOME_LABELS[field.outcome]}
                  </span>
                  {field.sensitivity && (
                    <span className="pill pill-warn">
                      {SENSITIVITY_LABELS[field.sensitivity] ?? field.sensitivity}
                    </span>
                  )}
                  {field.is_derived && (
                    <span
                      className="pill pill-warn"
                      title="Worked out from your record rather than read from it"
                    >
                      Derived — check it
                    </span>
                  )}
                  {field.answered_by_candidate && (
                    <span className="pill pill-ok">Your answer</span>
                  )}
                </div>

                {field.value && <p className="autofill-value">{field.value}</p>}
                {field.reason && (
                  <p className="quiet">{REASON_LABELS[field.reason] ?? field.reason}</p>
                )}
                {field.detail && <p className="quiet">{field.detail}</p>}

                {needsAnAnswer(field) && reviewId && receipt === null && (
                  <div className="autofill-answer">
                    <label
                      htmlFor={`answer-${field.field_id}`}
                      className="visually-hidden"
                    >
                      Your answer for {field.label}
                    </label>
                    <textarea
                      id={`answer-${field.field_id}`}
                      rows={2}
                      value={drafts[field.field_id] ?? ''}
                      placeholder="Type your answer to put it on the form"
                      onChange={(event) =>
                        setDrafts((prev) => ({
                          ...prev,
                          [field.field_id]: event.target.value,
                        }))
                      }
                    />
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy || !(drafts[field.field_id] ?? '').trim()}
                      onClick={() => answer(field.field_id)}
                    >
                      Put this on the form
                    </button>
                  </div>
                )}

                {field.requires_confirmation && receipt === null && (
                  <label className="autofill-confirm">
                    <input
                      type="checkbox"
                      checked={confirmed.includes(field.field_id)}
                      onChange={() => toggleConfirmation(field.field_id)}
                    />
                    I have read this answer and it is correct
                  </label>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      {report?.screenshot_png_base64 && (
        <details className="autofill-proof">
          <summary>See the filled form</summary>
          <img
            src={`data:image/png;base64,${report.screenshot_png_base64}`}
            alt="The application form as ApplyFlow filled it"
          />
        </details>
      )}

      {report && receipt === null && (
        <div className="autofill-submit">
          <button type="button" onClick={submit} disabled={busy || !canSubmit}>
            Submit this application
          </button>
          {!canSubmit && (
            <p className="quiet">
              {!report.can_be_submitted_here
                ? 'This one has to be finished on the portal itself — see above.'
                : unanswered.length > 0
                  ? `${unanswered.length} required question${
                      unanswered.length === 1 ? '' : 's'
                    } still to answer.`
                  : 'Confirm the answers marked as legal declarations first.'}
            </p>
          )}
        </div>
      )}

      {receipt && (
        <div
          className={`notice ${receipt.is_confirmed_sent ? 'notice-ok' : 'notice-warn'}`}
        >
          <strong>
            {receipt.is_confirmed_sent
              ? 'Application submitted'
              : 'Submitted, but the portal asked for something else'}
          </strong>
          <p>
            Pressed &ldquo;{receipt.pressed_control}&rdquo; on{' '}
            {new Date(receipt.submitted_at).toLocaleString()}.
          </p>
          {receipt.confirmation_excerpt && (
            <p className="quiet">{receipt.confirmation_excerpt}</p>
          )}
          {receipt.outstanding_boundaries.map((boundary) => (
            <p key={boundary.kind}>{boundary.instruction}</p>
          ))}
          <p>
            <a href={receipt.final_url} target="_blank" rel="noreferrer">
              Open where the portal left off
            </a>
          </p>
          {receipt.screenshot_png_base64 && (
            <details className="autofill-proof">
              <summary>See what the portal said back</summary>
              <img
                src={`data:image/png;base64,${receipt.screenshot_png_base64}`}
                alt="The page the portal answered the submission with"
              />
            </details>
          )}
        </div>
      )}
    </section>
  );
}
