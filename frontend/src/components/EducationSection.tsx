import { useState } from 'react';
import { applyFlowApi } from '../api/client';
import type { EducationInput, Profile, ProfileEducationEntry } from '../types';

interface Props {
  profile: Profile | null;
  onSaved: (profile: Profile) => void;
}

const EMPTY: EducationInput = {
  institution_name: '',
  degree: '',
  field_of_study: null,
  start_date: null,
  end_date: null,
  description: null,
};

/** Education — same per-entry add/edit/delete shape as work history, and for the
 * same provenance reason. */
export function EducationSection({ profile, onSaved }: Props) {
  const [draft, setDraft] = useState<EducationInput>(EMPTY);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!profile) {
    return (
      <section className="card profile-section">
        <h3>Education</h3>
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

  const startEditing = (entry: ProfileEducationEntry) => {
    setEditingId(entry.id);
    setDraft({
      institution_name: entry.institution_name,
      degree: entry.degree,
      field_of_study: entry.field_of_study,
      start_date: entry.start_date,
      end_date: entry.end_date,
      description: entry.description,
    });
  };

  return (
    <section className="card profile-section">
      <h3>Education</h3>

      <ul className="profile-entries">
        {profile.education.map((entry) => (
          <li key={entry.id}>
            <div>
              <strong>{entry.degree}</strong> · {entry.institution_name}
              {entry.field_of_study ? (
                <span className="quiet"> ({entry.field_of_study})</span>
              ) : null}
            </div>
            <div className="profile-entry-actions">
              <button type="button" onClick={() => startEditing(entry)} disabled={busy}>
                Edit
              </button>
              <button
                type="button"
                onClick={() => run(() => applyFlowApi.removeEducation(entry.id))}
                disabled={busy}
              >
                Delete
              </button>
            </div>
          </li>
        ))}
        {profile.education.length === 0 ? (
          <li className="quiet">Nothing on file yet.</li>
        ) : null}
      </ul>

      <div className="profile-fields">
        <label>
          Institution
          <input
            value={draft.institution_name}
            onChange={(event) =>
              setDraft({ ...draft, institution_name: event.target.value })
            }
          />
        </label>
        <label>
          Degree
          <input
            value={draft.degree}
            onChange={(event) => setDraft({ ...draft, degree: event.target.value })}
          />
        </label>
        <label>
          Field of study
          <input
            value={draft.field_of_study ?? ''}
            onChange={(event) =>
              setDraft({ ...draft, field_of_study: event.target.value || null })
            }
          />
        </label>
        <label>
          Start date
          <input
            type="date"
            value={draft.start_date ?? ''}
            onChange={(event) =>
              setDraft({ ...draft, start_date: event.target.value || null })
            }
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
        </label>
      </div>

      <div className="profile-section-actions">
        <button
          type="button"
          disabled={busy}
          onClick={() =>
            run(() =>
              editingId
                ? applyFlowApi.updateEducation(editingId, draft)
                : applyFlowApi.addEducation(draft),
            )
          }
        >
          {editingId ? 'Save changes' : 'Add qualification'}
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
