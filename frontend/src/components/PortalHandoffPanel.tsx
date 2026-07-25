import { useState } from 'react';
import { applyFlowApi } from '../api/client';
import type { HardStop, HardStopKind, PortalHandoff, PortalInspection } from '../types';

interface Props {
  jobPostingId: string;
}

const BOUNDARY_TITLES: Record<HardStopKind, string> = {
  captcha: 'A CAPTCHA',
  electronic_signature: 'An electronic signature',
  account_wall: 'A sign-in or account wall',
};

/**
 * The hand-off surface: check what the application portal is presenting, and
 * — when it presents something only a person may do — say so plainly and get
 * out of the way.
 *
 * Three things this panel is deliberate about.
 *
 * **It shows the evidence.** A hand-off interrupts what the candidate asked
 * for, so "we stopped, trust us" is not good enough: they get the lines the
 * backend matched on the portal's own page and a link to open that page
 * themselves, and can judge whether ApplyFlow read it correctly.
 *
 * **It offers two exits, not one.** "I've done it" and "I'll finish this
 * myself" are both real answers. An account wall on a portal that requires a
 * real account may never become automatable, and a panel that only allowed
 * "continue" would leave that hand-off open forever.
 *
 * **It does not claim the wall fell.** Continuing records the candidate's
 * word for having done the step — the backend re-reads the portal on the next
 * check and raises a fresh hand-off if the boundary is still there. Saying
 * "verified" here would be a claim nobody made.
 */
export function PortalHandoffPanel({ jobPostingId }: Props) {
  const [inspection, setInspection] = useState<PortalInspection | null>(null);
  const [handoff, setHandoff] = useState<PortalHandoff | null>(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const check = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await applyFlowApi.inspectPortal(jobPostingId);
      setInspection(result);
      setHandoff(result.handoff);
      setNote('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setBusy(false);
    }
  };

  const resolve = async (action: 'resume' | 'abandon') => {
    if (!handoff) return;
    setBusy(true);
    setError(null);
    try {
      const resolved =
        action === 'resume'
          ? await applyFlowApi.resumePortalHandoff(handoff.id, note)
          : await applyFlowApi.abandonPortalHandoff(handoff.id, note);
      setHandoff(resolved);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card handoff-panel">
      <div className="handoff-header">
        <div>
          <h3>The application portal</h3>
          <p className="quiet">
            ApplyFlow reads the form before touching it. If the portal asks for
            something only you can do, it stops there.
          </p>
        </div>
        <button type="button" className="secondary" disabled={busy} onClick={check}>
          {busy ? 'Checking…' : inspection ? 'Check again' : 'Check the portal'}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {handoff !== null ? (
        <HandoffCard
          handoff={handoff}
          note={note}
          busy={busy}
          onNoteChange={setNote}
          onResolve={resolve}
        />
      ) : (
        inspection !== null && <CleanPortal inspection={inspection} />
      )}

      {inspection === null && !busy && (
        <p className="muted">
          Not checked yet. Nothing is filled in or submitted by checking — the form
          is only read.
        </p>
      )}
    </section>
  );
}

function CleanPortal({ inspection }: { inspection: PortalInspection }) {
  const required = inspection.fields.filter((field) => field.required).length;

  return (
    <>
      {inspection.cleared_handoff_id !== null && (
        <div className="notice notice-ok">
          The boundary that was blocking this portal is gone, so the earlier
          hand-off is closed. Nothing is waiting on you here any more.
        </div>
      )}
      <div className="notice notice-info">
        No hard boundary on this form: {inspection.fields.length} question
        {inspection.fields.length === 1 ? '' : 's'}
        {required > 0 && <> ({required} marked required)</>}.
      </div>
      {inspection.fields.length > 0 && (
        <ul className="portal-fields">
          {inspection.fields.map((field, index) => (
            <li key={`${field.name}-${index}`}>
              {field.label || <span className="quiet">(unlabelled)</span>}
              {field.required && <span className="pill pill-warn">required</span>}
              {field.human_only_boundary !== null && (
                <span className="pill pill-warn">yours to fill</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {inspection.landed_url !== inspection.apply_url && (
        <p className="quiet">
          The apply link redirected to <code>{inspection.landed_url}</code>.
        </p>
      )}
    </>
  );
}

interface HandoffCardProps {
  handoff: PortalHandoff;
  note: string;
  busy: boolean;
  onNoteChange: (note: string) => void;
  onResolve: (action: 'resume' | 'abandon') => void;
}

function HandoffCard({
  handoff,
  note,
  busy,
  onNoteChange,
  onResolve,
}: HandoffCardProps) {
  if (!handoff.is_open) {
    return (
      <div className="notice notice-ok">
        {handoff.status === 'resumed' ? (
          <>
            Thanks — noted that you handled this. ApplyFlow will read the portal
            again next time it works on this application, and will stop again if the
            boundary is still there.
          </>
        ) : (
          <>
            Left with you. ApplyFlow is not going to work this portal, so nothing
            here is waiting on you.
          </>
        )}
        {handoff.resolution_note && (
          <p className="quiet">Your note: {handoff.resolution_note}</p>
        )}
      </div>
    );
  }

  return (
    <div className="handoff-open">
      <div className="notice notice-warn">
        <strong>Over to you.</strong> ApplyFlow stopped on this portal and has
        filled in nothing.
      </div>

      {handoff.hard_stops.map((stop) => (
        <BoundaryDetail key={stop.kind} stop={stop} />
      ))}

      <p>
        <a href={handoff.paused_url} target="_blank" rel="noreferrer">
          Open the portal where ApplyFlow stopped
        </a>
      </p>

      <div className="field">
        <label htmlFor={`handoff-note-${handoff.id}`}>
          Anything worth remembering? (optional)
        </label>
        <input
          id={`handoff-note-${handoff.id}`}
          value={note}
          placeholder="e.g. created the account with my personal email"
          onChange={(event) => onNoteChange(event.target.value)}
        />
      </div>

      <div className="handoff-actions">
        <button type="button" disabled={busy} onClick={() => onResolve('resume')}>
          I&apos;ve done it — continue
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => onResolve('abandon')}
        >
          I&apos;ll finish this one myself
        </button>
      </div>
    </div>
  );
}

function BoundaryDetail({ stop }: { stop: HardStop }) {
  return (
    <div className="handoff-boundary">
      <h4>{BOUNDARY_TITLES[stop.kind]}</h4>
      <p>{stop.refusal_reason}</p>
      <p>
        <strong>What to do:</strong> {stop.human_action}
      </p>
      <details>
        <summary className="quiet">Why ApplyFlow thinks so</summary>
        <ul>
          {stop.evidence.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}
