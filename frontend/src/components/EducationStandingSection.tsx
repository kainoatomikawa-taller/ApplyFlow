import { useState } from 'react';
import { applyFlowApi } from '../api/client';
import { label } from '../labels';
import type { Profile } from '../types';

interface Props {
  profile: Profile | null;
  onSaved: (profile: Profile) => void;
}

const ENROLLMENT_STATUSES = ['not_enrolled', 'undergraduate', 'graduate'];
const DEGREE_LEVELS = [
  'high_school',
  'associate',
  'bachelors',
  'masters',
  'doctorate',
];

/**
 * Where the candidate is in their education *now*.
 *
 * Separate from Qualifications, which records the highest degree they have
 * *finished*. The distinction is the whole point: without this section a current
 * undergraduate had no honest answer — "high school" is true and filters out most
 * of the roles they want, and "bachelor's" gets the right roles by claiming a
 * degree they have not completed.
 */
export function EducationStandingSection({ profile, onSaved }: Props) {
  const current = profile?.education_standing;
  const [status, setStatus] = useState(
    current?.is_stated ? current.enrollment_status : '',
  );
  const [degree, setDegree] = useState(current?.degree_in_progress ?? '');
  const [graduation, setGraduation] = useState(
    current?.expected_graduation ?? '',
  );
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!profile) {
    return (
      <section className="card profile-section">
        <h3>Current studies</h3>
        <p className="quiet profile-locked">Save your name and email first.</p>
      </section>
    );
  }

  // The domain refuses "not enrolled" alongside a degree in progress or a
  // graduation date, so the two fields are hidden rather than sent and rejected.
  const enrolled = status === 'undergraduate' || status === 'graduate';

  const save = async () => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      onSaved(
        await applyFlowApi.saveEducationStanding({
          enrollment_status: status || null,
          degree_in_progress: enrolled ? degree || null : null,
          expected_graduation: enrolled ? graduation || null : null,
        }),
      );
      setSaved(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card profile-section">
      <h3>Current studies</h3>
      <p className="quiet">
        What you're studying <em>now</em>. Separate from "highest completed
        degree" above — a degree in progress counts towards a job's degree
        requirement unless that job says you must have already graduated.
      </p>

      <div className="profile-fields">
        <label>
          Currently enrolled
          <select
            value={status}
            disabled={busy}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="">Not stated</option>
            {ENROLLMENT_STATUSES.map((value) => (
              <option key={value} value={value}>
                {value === 'not_enrolled' ? 'No, not studying' : label(value)}
              </option>
            ))}
          </select>
        </label>

        {enrolled ? (
          <>
            <label>
              Degree in progress
              <select
                value={degree}
                disabled={busy}
                onChange={(event) => setDegree(event.target.value)}
              >
                <option value="">Not stated</option>
                {DEGREE_LEVELS.map((value) => (
                  <option key={value} value={value}>
                    {label(value)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Expected graduation
              <input
                type="date"
                value={graduation}
                disabled={busy}
                onChange={(event) => setGraduation(event.target.value)}
              />
            </label>
          </>
        ) : null}
      </div>

      <div className="profile-section-actions">
        <button type="button" onClick={save} disabled={busy}>
          Save current studies
        </button>
        {saved ? <span className="quiet">Saved.</span> : null}
      </div>

      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
