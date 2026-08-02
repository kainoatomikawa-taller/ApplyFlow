import { useCallback, useEffect, useState } from 'react';
import { applyFlowApi } from '../api/client';
import type { SentDocument, TrackedApplication, TrackedApplicationStatus } from '../types';

interface Props {
  /** Bumped by the parent when the access token changes, so the feed reloads. */
  authGeneration?: number;
}

const STATUS_LABELS: Record<TrackedApplicationStatus, string> = {
  applied: 'Applied',
  interviewing: 'Interviewing',
  offer: 'Offer',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

/**
 * One document reference, shown as what it is rather than as a link to
 * something regenerated.
 *
 * The short digest is the point of this line. "Tailored résumé v2" is only a
 * label; the digest is what makes the claim checkable — it identifies the
 * exact bytes that were archived, so a candidate reading their tracker can
 * tell that the document on screen is the one the employer received and not a
 * later revision that happens to share a name.
 */
function SentDocumentLine({ label, document }: { label: string; document: SentDocument | null }) {
  if (document === null) {
    return (
      <li className="sent-document missing">
        <span className="sent-document-label">{label}</span>
        <span className="quiet">not on file</span>
      </li>
    );
  }
  return (
    <li className="sent-document">
      <span className="sent-document-label">
        {label} <span className="pill">v{document.version}</span>
      </span>
      <code className="sent-document-digest" title={document.content_sha256}>
        {document.content_sha256.slice(0, 12)}
      </code>
    </li>
  );
}

/**
 * The tracker: every application the candidate has sent, what went out with
 * it, and where it stands.
 *
 * **The status control offers only what the backend will accept.** Its
 * options are `allowed_next_statuses` from the response — the domain's own
 * state machine (`ApplicationStatus.allowed_transitions`), passed through. A
 * dropdown that listed every status would offer "back to interviewing" on a
 * rejected application, and the candidate would meet the refusal only after
 * choosing. When the list is empty the application has settled, and the
 * status renders as text rather than as a control that cannot do anything.
 *
 * **A change re-renders from what was stored.** The PATCH returns the whole
 * updated record, including the next set of choices, and that is what
 * replaces the row. Patching the row locally would mean the screen showed the
 * candidate's intent rather than the stored outcome — which is the same
 * mistake as a UI that computes its own gates.
 *
 * **What was sent is shown by reference, never re-rendered.** Each row names
 * the archived snapshots by version and digest and does not fetch their text:
 * a tracker exists to say what the employer received, and the closest thing
 * to proof this screen can offer is the digest of the bytes that were stored
 * at send time.
 */
export function ApplicationTracker({ authGeneration = 0 }: Props) {
  const [applications, setApplications] = useState<TrackedApplication[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    try {
      setError(null);
      setApplications(await applyFlowApi.listTrackedApplications());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, authGeneration]);

  const changeStatus = async (
    application: TrackedApplication,
    status: TrackedApplicationStatus,
  ) => {
    setBusyIds((prev) => new Set(prev).add(application.id));
    setError(null);
    try {
      const updated = await applyFlowApi.updateApplicationStatus(application.id, status);
      // Replaced wholesale with what came back — see the component docstring.
      setApplications((prev) =>
        prev.map((row) => (row.id === updated.id ? updated : row)),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setBusyIds((prev) => {
        const next = new Set(prev);
        next.delete(application.id);
        return next;
      });
    }
  };

  if (loaded && applications.length === 0 && error === null) {
    return (
      <section className="card">
        <h2>Applications sent</h2>
        <p className="quiet">
          Nothing sent yet. An application appears here the moment you submit
          one — you never add it by hand.
        </p>
      </section>
    );
  }

  return (
    <section className="card">
      <h2>Applications sent</h2>
      {error && <p className="error">{error}</p>}

      <ul className="tracked-applications">
        {applications.map((application) => {
          const busy = busyIds.has(application.id);
          return (
            <li key={application.id} className={`tracked-application ${application.status}`}>
              <div className="tracked-application-header">
                <div>
                  <strong>{application.role_title}</strong>
                  <span className="quiet"> @ {application.company_name}</span>
                  {application.job_location && (
                    <span className="quiet"> · {application.job_location}</span>
                  )}
                </div>
                <span className="quiet">Applied {formatDate(application.applied_at)}</span>
              </div>

              <ul className="sent-documents">
                <SentDocumentLine label="Tailored résumé" document={application.resume} />
                {application.cover_letter && (
                  <SentDocumentLine
                    label="Cover letter"
                    document={application.cover_letter}
                  />
                )}
              </ul>

              <div className="tracked-application-status">
                <span className={`pill status-${application.status}`}>
                  {STATUS_LABELS[application.status]}
                </span>
                {application.allowed_next_statuses.length > 0 ? (
                  <label>
                    <span className="quiet">Update to</span>{' '}
                    <select
                      value=""
                      disabled={busy}
                      onChange={(event) => {
                        const next = event.target.value as TrackedApplicationStatus;
                        if (next) void changeStatus(application, next);
                      }}
                    >
                      <option value="">Choose…</option>
                      {application.allowed_next_statuses.map((status) => (
                        <option key={status} value={status}>
                          {STATUS_LABELS[status]}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <span className="quiet">This application has closed.</span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
