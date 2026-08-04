import { useState } from 'react';
import { applyFlowApi } from '../api/client';
import { label } from '../labels';
import type { Profile } from '../types';
import { ProfileSection } from './ProfileSection';

interface Props {
  profile: Profile | null;
  onSaved: (profile: Profile) => void;
}

const CLEARANCE_LEVELS = [
  'public_trust',
  'confidential',
  'secret',
  'top_secret',
  'top_secret_sci',
];

const DEGREE_LEVELS = [
  'high_school',
  'associate',
  'bachelors',
  'masters',
  'doctorate',
];

/**
 * Clearance and highest degree — the two profile fields nothing fills onto a form.
 *
 * They exist for matching: a posting's stated requirements are compared against
 * them to decide whether a job is worth showing at all. Worth saying on the form,
 * because a candidate could reasonably expect them to appear on applications.
 *
 * Leaving either blank means "not stated", never "I have none" — the matching layer
 * is built so a gap in the candidate's own data never disqualifies them, and
 * clearing a value restores that rather than asserting a negative.
 */
export function QualificationsSection({ profile, onSaved }: Props) {
  const current = profile?.qualifications;
  const [clearance, setClearance] = useState(current?.clearance_level ?? '');
  const [degree, setDegree] = useState(current?.highest_degree ?? '');

  const save = async () => {
    onSaved(
      await applyFlowApi.saveQualifications({
        clearance_level: clearance || null,
        highest_degree: degree || null,
      }),
    );
  };

  return (
    <ProfileSection
      title="Qualifications"
      description="Used to decide which jobs are worth showing you. Never filled onto an application. Leaving either blank means “not stated”, which never counts against you."
      lockedReason={profile ? null : 'Save your name and email first.'}
      onSave={save}
    >
      <label>
        Security clearance
        <select
          value={clearance}
          onChange={(event) => setClearance(event.target.value)}
        >
          <option value="">Not stated</option>
          {CLEARANCE_LEVELS.map((level) => (
            <option key={level} value={level}>
              {label(level)}
            </option>
          ))}
        </select>
      </label>
      <label>
        Highest completed degree
        <select value={degree} onChange={(event) => setDegree(event.target.value)}>
          <option value="">Not stated</option>
          {DEGREE_LEVELS.map((level) => (
            <option key={level} value={level}>
              {label(level)}
            </option>
          ))}
        </select>
      </label>
    </ProfileSection>
  );
}
