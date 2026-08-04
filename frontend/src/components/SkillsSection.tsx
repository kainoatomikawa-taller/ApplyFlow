import { useState } from 'react';
import { applyFlowApi } from '../api/client';
import { label } from '../labels';
import type { Profile, SkillInput } from '../types';

interface Props {
  profile: Profile | null;
  onSaved: (profile: Profile) => void;
}

const PROFICIENCY_LEVELS = ['beginner', 'intermediate', 'advanced', 'expert'];

const EMPTY: SkillInput = { name: '', proficiency: null, years_of_experience: null };

/**
 * Skills. Names are unique per profile, case-insensitively — renaming one onto
 * another's name is refused by the server with a 409, which surfaces here as the
 * error message rather than silently merging the two.
 */
export function SkillsSection({ profile, onSaved }: Props) {
  const [draft, setDraft] = useState<SkillInput>(EMPTY);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!profile) {
    return (
      <section className="card profile-section">
        <h3>Skills</h3>
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

  return (
    <section className="card profile-section">
      <h3>Skills</h3>

      <ul className="profile-entries">
        {profile.skills.map((skill) => (
          <li key={skill.id}>
            <div>
              <strong>{skill.name}</strong>
              {skill.proficiency ? (
                <span className="quiet"> · {label(skill.proficiency)}</span>
              ) : null}
              {skill.years_of_experience !== null ? (
                <span className="quiet"> · {skill.years_of_experience}y</span>
              ) : null}
            </div>
            <div className="profile-entry-actions">
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setEditingId(skill.id);
                  setDraft({
                    name: skill.name,
                    proficiency: skill.proficiency,
                    years_of_experience: skill.years_of_experience,
                  });
                }}
              >
                Edit
              </button>
              <button
                type="button"
                onClick={() => run(() => applyFlowApi.removeSkill(skill.id))}
                disabled={busy}
              >
                Delete
              </button>
            </div>
          </li>
        ))}
        {profile.skills.length === 0 ? (
          <li className="quiet">No skills on file yet.</li>
        ) : null}
      </ul>

      <div className="profile-fields">
        <label>
          Skill
          <input
            value={draft.name}
            onChange={(event) => setDraft({ ...draft, name: event.target.value })}
          />
        </label>
        <label>
          Proficiency
          <select
            value={draft.proficiency ?? ''}
            onChange={(event) =>
              setDraft({ ...draft, proficiency: event.target.value || null })
            }
          >
            <option value="">Not stated</option>
            {PROFICIENCY_LEVELS.map((level) => (
              <option key={level} value={level}>
                {label(level)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Years of experience
          <input
            type="number"
            min={0}
            value={draft.years_of_experience ?? ''}
            onChange={(event) =>
              setDraft({
                ...draft,
                years_of_experience: event.target.value
                  ? Number(event.target.value)
                  : null,
              })
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
                ? applyFlowApi.updateSkill(editingId, draft)
                : applyFlowApi.addSkill(draft),
            )
          }
        >
          {editingId ? 'Save changes' : 'Add skill'}
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
