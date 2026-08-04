import { useState } from 'react';
import { applyFlowApi } from '../api/client';
import type { Profile, ProfileWorkHistoryEntry, WorkHistoryInput } from '../types';

interface Props {
  profile: Profile | null;
  onSaved: (profile: Profile) => void;
}

const EMPTY: WorkHistoryInput = {
  company_name: '',
  job_title: '',
  start_date: '',
  end_date: null,
  location: null,
  description: null,
};

/**
 * Employment history — add, edit, and delete one job at a time.
 *
 * Per entry rather than re-submitting the whole list, and that is a data decision
 * rather than a UI preference: rewriting the list would re-stamp every job as
 * something the candidate typed, including the ones a résumé parser produced and
 * they never touched. Editing one job touches one job's provenance.
 *
 * Delete matters more than it looks. Until this existed, parsing was the only way
 * history got onto a profile and it could only append — so a mis-parsed job, or a
 * duplicate from uploading the same résumé twice, was permanent. (The parser now
 * skips jobs it already has, but the button is the backstop for everything else.)
 */
export function WorkHistorySection({ profile, onSaved }: Props) {
  const [draft, setDraft] = useState<WorkHistoryInput>(EMPTY);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!profile) {
    return (
      <section className="card profile-section">
        <h3>Work history</h3>
        <p className="quiet profile-locked">Save your name and email first.</p>
      </section>
    );
  }

  const run = async (action: () => Promise<Profile>) => {
    setBusy(true);
    setError(null);
    try {
      onSaved(await action());
      setDraft(EMPTY);
      setEditingId(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const startEditing = (entry: ProfileWorkHistoryEntry) => {
    setEditingId(entry.id);
    setDraft({
      company_name: entry.company_name,
      job_title: entry.job_title,
      start_date: entry.start_date,
      end_date: entry.end_date,
      location: entry.location,
      description: entry.description,
    });
  };

  const submit = () =>
    run(() =>
      editingId
        ? applyFlowApi.updateWorkHistory(editingId, draft)
        : applyFlowApi.addWorkHistory(draft),
    );

  return (
    <section className="card profile-section">
      <h3>Work history</h3>
      <p className="quiet">
        Add jobs by hand, upload a résumé, or both — uploading will not duplicate
        anything already listed here.
      </p>

      <ul className="profile-entries">
        {profile.work_history.map((entry) => (
          <li key={entry.id}>
            <div>
              <strong>{entry.job_title}</strong> · {entry.company_name}
              <span className="quiet">
                {' '}
                {entry.start_date} – {entry.end_date ?? 'present'}
              </span>
            </div>
            <div className="profile-entry-actions">
              <button type="button" onClick={() => startEditing(entry)} disabled={busy}>
                Edit
              </button>
              <button
                type="button"
                onClick={() => run(() => applyFlowApi.removeWorkHistory(entry.id))}
                disabled={busy}
              >
                Delete
              </button>
            </div>
          </li>
        ))}
        {profile.work_history.length === 0 ? (
          <li className="quiet">No jobs on file yet.</li>
        ) : null}
      </ul>

      <div className="profile-fields">
        <label>
          Company
          <input
            value={draft.company_name}
            onChange={(event) =>
              setDraft({ ...draft, company_name: event.target.value })
            }
          />
        </label>
        <label>
          Job title
          <input
            value={draft.job_title}
            onChange={(event) => setDraft({ ...draft, job_title: event.target.value })}
          />
        </label>
        <label>
          Start date
          <input
            type="date"
            value={draft.start_date}
            onChange={(event) => setDraft({ ...draft, start_date: event.target.value })}
          />
        </label>
        <label>
          End date
          <input
            type="date"
            value={draft.end_date ?? ''}
            onChange={(event) =>
              setDraft({ ...draft, end_date: event.target.value || null })
            }
          />
          <span className="quiet">Leave blank if this is your current job.</span>
        </label>
        <label>
          Location
          <input
            value={draft.location ?? ''}
            onChange={(event) =>
              setDraft({ ...draft, location: event.target.value || null })
            }
          />
        </label>
        <label>
          What you did
          <textarea
            value={draft.description ?? ''}
            onChange={(event) =>
              setDraft({ ...draft, description: event.target.value || null })
            }
            rows={3}
          />
        </label>
      </div>

      <div className="profile-section-actions">
        <button type="button" onClick={submit} disabled={busy}>
          {editingId ? 'Save changes' : 'Add job'}
        </button>
        {editingId ? (
          <button
            type="button"
            onClick={() => {
              setEditingId(null);
              setDraft(EMPTY);
            }}
            disabled={busy}
          >
            Cancel
          </button>
        ) : null}
      </div>

      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
