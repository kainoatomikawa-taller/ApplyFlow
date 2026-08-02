import { useState } from 'react';
import { SentDocumentLine } from './SentDocumentLine';
import {
  STATUS_LABELS,
  fileStem,
  formatAge,
  formatDate,
  formatDayCount,
} from './trackerPresentation';
import type { TrackedApplication, TrackedApplicationStatus } from '../types';

interface Props {
  application: TrackedApplication;
  busy: boolean;
  /**
   * Record a move. Resolves true when the backend stored it — the row clears
   * its pending choice on that and keeps it otherwise, so a refused move
   * leaves the candidate's input where they can fix it rather than discarding
   * it under an error message.
   */
  onStatusChange: (
    status: TrackedApplicationStatus,
    note: string,
  ) => Promise<boolean>;
}

/**
 * One sent application: what went out, where it stands, and how it got there.
 *
 * **The status control offers only what the backend will accept.** Its options
 * are `allowed_next_statuses` from the response — the domain's own state
 * machine (`ApplicationStatus.allowed_transitions`) passed through. A dropdown
 * listing every status would offer "back to interviewing" on a rejected
 * application, and the candidate would meet the refusal only after choosing.
 * When the list is empty the application has settled, and the status renders
 * as text rather than as a control that cannot do anything.
 *
 * **A move is confirmed, not fired by the dropdown.** Choosing a status arms
 * the change and reveals a note field; nothing is sent until the candidate
 * presses the button. Two reasons, and the second is the real one: a select
 * that submitted on change makes a mis-click a permanent history entry, and
 * the note has nowhere to be typed. The note matters because the backend
 * stores it against the transition and this screen reads it back — "phone
 * screen booked for the 14th" is the difference between a history a candidate
 * can use and a list of state names.
 */
export function TrackedApplicationRow({ application, busy, onStatusChange }: Props) {
  const [pending, setPending] = useState<TrackedApplicationStatus | ''>('');
  const [note, setNote] = useState('');

  const record = async () => {
    if (pending === '') return;
    if (await onStatusChange(pending, note.trim())) {
      setPending('');
      setNote('');
    }
  };

  const cancel = () => {
    setPending('');
    setNote('');
  };

  const stem = fileStem(application.company_name, application.role_title);
  const hasMoved = application.status_history.length > 1;

  return (
    <li className={`tracked-application ${application.status}`}>
      <div className="tracked-application-header">
        <div>
          <strong>{application.role_title}</strong>
          <span className="quiet"> @ {application.company_name}</span>
          {application.job_location !== null && (
            <span className="quiet"> · {application.job_location}</span>
          )}
        </div>
        <span className="quiet" title={application.applied_at}>
          Applied {formatDate(application.applied_at)} ·{' '}
          {formatAge(application.applied_at)}
        </span>
      </div>

      <div className="tracked-application-status">
        <span className={`pill status-${application.status}`}>
          {STATUS_LABELS[application.status]}
        </span>
        {/* How long it has stood where it stands — the number a candidate
            deciding whether to follow up is actually looking for. */}
        <span className="quiet">
          {application.is_open
            ? `for ${formatDayCount(application.current_status_since)}`
            : `${formatDayCount(application.current_status_since)} ago`}
        </span>
      </div>

      <ul className="sent-documents">
        <SentDocumentLine
          label="Tailored résumé"
          reference={application.resume}
          downloadStem={stem}
        />
        {/* A missing reference and a letter the form never asked for are
            different facts: the first is shown as missing by the line itself,
            the second is simply not part of this application. */}
        {application.cover_letter_document_id !== null && (
          <SentDocumentLine
            label="Cover letter"
            reference={application.cover_letter}
            downloadStem={stem}
          />
        )}
      </ul>

      {hasMoved && (
        <details className="status-history">
          <summary className="quiet">
            {application.status_history.length} status changes
          </summary>
          <ol>
            {application.status_history.map((change) => (
              <li key={`${change.status}-${change.changed_at}`}>
                <span className={`pill status-${change.status}`}>
                  {STATUS_LABELS[change.status]}
                </span>{' '}
                <span className="quiet">{formatDate(change.changed_at)}</span>
                {change.note !== '' && <span> — {change.note}</span>}
              </li>
            ))}
          </ol>
        </details>
      )}

      <div className="tracked-application-update">
        {application.allowed_next_statuses.length > 0 ? (
          <>
            <label className="tracked-application-select">
              <span className="quiet">Update to</span>{' '}
              <select
                value={pending}
                disabled={busy}
                onChange={(event) =>
                  setPending(event.target.value as TrackedApplicationStatus | '')
                }
              >
                <option value="">Choose…</option>
                {application.allowed_next_statuses.map((status) => (
                  <option key={status} value={status}>
                    {STATUS_LABELS[status]}
                  </option>
                ))}
              </select>
            </label>

            {pending !== '' && (
              <div className="status-change-confirm">
                <input
                  value={note}
                  disabled={busy}
                  placeholder="What happened? (optional)"
                  aria-label={`Note for moving to ${STATUS_LABELS[pending]}`}
                  onChange={(event) => setNote(event.target.value)}
                />
                <button type="button" disabled={busy} onClick={() => void record()}>
                  {busy ? 'Recording…' : `Record ${STATUS_LABELS[pending]}`}
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={cancel}
                >
                  Cancel
                </button>
              </div>
            )}
          </>
        ) : (
          <span className="quiet">
            This application has closed — {STATUS_LABELS[application.status]} is
            final.
          </span>
        )}
      </div>
    </li>
  );
}
