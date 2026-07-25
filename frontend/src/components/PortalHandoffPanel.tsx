import { useState } from 'react';
import { applyFlowApi } from '../api/client';
import { HandoffNotice } from './HandoffNotice';
import type { PortalHandoff, PortalInspection } from '../types';

interface Props {
  jobPostingId: string;
}

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
        <HandoffNotice
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
