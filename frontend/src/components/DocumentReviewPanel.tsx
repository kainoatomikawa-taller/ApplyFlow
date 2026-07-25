import { useState } from 'react';
import { applyFlowApi } from '../api/client';
import { TailoringSummary } from './TailoringSummary';
import type {
  DocumentKind,
  GuardedDocument,
  ProvenanceViolation,
  RankedJob,
  ResumeExports,
} from '../types';

interface Props {
  job: RankedJob;
  kind: DocumentKind;
  title: string;
  /** Gaps the candidate gave a real answer to, for the tailoring summary. */
  answeredGaps: string[];
}

/** Where the last write came from, so the UI can say which it is showing. */
type Origin = 'generated' | 'revised';

const SOURCE_LABELS: Record<string, string> = {
  parsed_resume: 'Parsed résumé',
  user_entered: 'Entered by you',
  answer: 'Your gap answers',
};

/**
 * Review and edit one generated document, then store the edited version.
 *
 * The editor holds a draft the candidate can change freely; "Save edits"
 * sends it to the revision route, which puts it back through the provenance
 * guard and archives what survived as the next version. So the text shown
 * after a save is the *stored* text, not the submitted text — they differ
 * when the guard removed a claim, and `strippedFromEdit` is how the UI says
 * so instead of silently replacing what was typed.
 */
export function DocumentReviewPanel({ job, kind, title, answeredGaps }: Props) {
  const [document, setDocument] = useState<GuardedDocument | null>(null);
  const [exports, setExports] = useState<ResumeExports | null>(null);
  const [atsViolations, setAtsViolations] = useState<
    { rule: string; detail: string; line_number: number }[]
  >([]);
  const [draft, setDraft] = useState('');
  const [strippedFromEdit, setStrippedFromEdit] = useState<ProvenanceViolation[]>([]);
  const [origin, setOrigin] = useState<Origin>('generated');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const adopt = (next: GuardedDocument, nextOrigin: Origin) => {
    setDocument(next);
    setDraft(next.content);
    setOrigin(nextOrigin);
  };

  const generate = async () => {
    setBusy(true);
    setError(null);
    setStrippedFromEdit([]);
    try {
      if (kind === 'tailored_resume') {
        const result = await applyFlowApi.generateTailoredResume(job.job_posting.id);
        adopt(result.document, 'generated');
        setExports(result.exports);
        setAtsViolations(result.ats_safety_violations);
      } else {
        adopt(await applyFlowApi.generateCoverLetter(job.job_posting.id), 'generated');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const stored = await applyFlowApi.reviseDocument(job.job_posting.id, kind, draft);
      adopt(stored, 'revised');
      setStrippedFromEdit(stored.violations);
      // The stored text is authoritative but no longer the rendered PDF's
      // text, so drop exports rather than offer a download that disagrees
      // with what was saved.
      setExports(null);
      setAtsViolations([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setBusy(false);
    }
  };

  const dirty = document !== null && draft !== document.content;

  if (document === null) {
    return (
      <section className="card document-panel">
        <div className="document-header">
          <h3>{title}</h3>
        </div>
        <p className="muted">
          Not generated yet. Every line is checked against your profile and gap answers
          before it reaches you.
        </p>
        {error && <p className="error">{error}</p>}
        <button type="button" onClick={() => void generate()} disabled={busy}>
          {busy ? 'Generating…' : `Generate ${title.toLowerCase()}`}
        </button>
      </section>
    );
  }

  return (
    <section className="card document-panel">
      <div className="document-header">
        <h3>{title}</h3>
        <span className="pill pill-version">
          {origin === 'revised' ? 'Your edit' : 'Generated'} · version{' '}
          {document.version}
        </span>
      </div>

      <TailoringSummary
        job={job}
        content={document.content}
        backingSources={document.backing_sources}
        answeredGaps={answeredGaps}
      />

      {document.violations.length > 0 && origin === 'generated' && (
        <details className="notice notice-warn">
          <summary>
            {document.violations.length} line
            {document.violations.length === 1 ? '' : 's'} removed — nothing in your
            record backed them
          </summary>
          <ul>
            {document.violations.map((violation) => (
              <li key={violation.line}>
                <code>{violation.line}</code>
                <span className="quiet">
                  {' '}
                  — {violation.unsupported_terms.join(', ')}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {strippedFromEdit.length > 0 && (
        <div className="notice notice-warn">
          <strong>
            {strippedFromEdit.length} line
            {strippedFromEdit.length === 1 ? '' : 's'} of your edit could not be stored
          </strong>{' '}
          — the same check applies to edits as to generated text, and these claims are
          not in your profile or answers. Add the experience to your profile, or answer
          the matching gap question, and try again.
          <ul>
            {strippedFromEdit.map((violation) => (
              <li key={violation.line}>
                <code>{violation.line}</code>
                <span className="quiet">
                  {' '}
                  — {violation.unsupported_terms.join(', ')}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {atsViolations.length > 0 && (
        <div className="notice notice-warn">
          <strong>ATS formatting check found {atsViolations.length} issue(s)</strong>
          <ul>
            {atsViolations.map((violation) => (
              <li key={`${violation.rule}-${violation.line_number}`}>
                line {violation.line_number}: {violation.detail}
              </li>
            ))}
          </ul>
        </div>
      )}

      <label className="section-label" htmlFor={`editor-${kind}`}>
        Review and edit
      </label>
      <textarea
        id={`editor-${kind}`}
        className="document-editor"
        rows={kind === 'tailored_resume' ? 22 : 14}
        value={draft}
        disabled={busy}
        onChange={(e) => setDraft(e.target.value)}
      />

      <div className="document-footer">
        <div className="document-status">
          {dirty ? (
            <span className="pill pill-warn">Unsaved changes</span>
          ) : (
            <span className="pill pill-ok">Stored as version {document.version}</span>
          )}
          <span className="quiet">
            {' '}
            Backed by{' '}
            {document.backing_sources.length === 0
              ? 'nothing on file'
              : document.backing_sources
                  .map((source) => SOURCE_LABELS[source] ?? source)
                  .join(', ')}
          </span>
        </div>
        <div className="document-actions">
          {exports !== null && (
            <a
              className="button-link"
              href={`data:application/pdf;base64,${exports.pdf_base64}`}
              download={`${job.job_posting.company}-${job.job_posting.title}.pdf`.replace(
                /\s+/g,
                '-',
              )}
            >
              Download PDF
            </a>
          )}
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => void generate()}
          >
            Regenerate
          </button>
          <button type="button" disabled={busy || !dirty} onClick={() => void save()}>
            {busy ? 'Saving…' : 'Save edits'}
          </button>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
    </section>
  );
}
