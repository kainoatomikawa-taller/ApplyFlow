import type { HardStop, HardStopKind, PortalHandoff } from '../types';

const BOUNDARY_TITLES: Record<HardStopKind, string> = {
  captcha: 'A CAPTCHA',
  electronic_signature: 'An electronic signature',
  account_wall: 'A sign-in or account wall',
};

interface Props {
  handoff: PortalHandoff;
  note: string;
  busy: boolean;
  onNoteChange: (note: string) => void;
  onResolve: (action: 'resume' | 'abandon') => void;
}

/**
 * How a hard-stop hand-off is presented, wherever it appears: what ApplyFlow
 * hit, why it refuses to do it, what the candidate has to do, the evidence for
 * the claim, and the link to the exact page it stopped on.
 *
 * Shared between the portal check and the review screen deliberately. A
 * hand-off that read one way on one screen and another way on the next would
 * undermine the thing it is for — the candidate has to be able to recognize it
 * and know, without relearning, what is being asked of them.
 *
 * Two exits, both real. "I've done it" records the candidate's word for having
 * done the step (the backend re-reads the portal later and stops again if the
 * boundary is still there); "I'll finish this myself" is the honest ending for
 * a portal that will always need an account.
 */
export function HandoffNotice({
  handoff,
  note,
  busy,
  onNoteChange,
  onResolve,
}: Props) {
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
