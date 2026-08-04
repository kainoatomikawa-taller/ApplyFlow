import { useEffect, useState } from 'react';
import { applyFlowApi } from '../api/client';
import { label } from '../labels';
import type { EeoSelfIdentification } from '../types';

interface Props {
  hasProfile: boolean;
}

const CATEGORIES = {
  gender_identity: ['male', 'female', 'non_binary', 'decline_to_self_identify'],
  race_ethnicity: [
    'hispanic_or_latino',
    'white',
    'black_or_african_american',
    'native_hawaiian_or_pacific_islander',
    'asian',
    'american_indian_or_alaska_native',
    'two_or_more_races',
    'decline_to_self_identify',
  ],
  veteran_status: [
    'protected_veteran',
    'not_a_protected_veteran',
    'decline_to_self_identify',
  ],
  disability_status: ['has_disability', 'no_disability', 'decline_to_self_identify'],
} as const;

type Category = keyof typeof CATEGORIES;

const TITLES: Record<Category, string> = {
  gender_identity: 'Gender identity',
  race_ethnicity: 'Race or ethnicity',
  veteran_status: 'Veteran status',
  disability_status: 'Disability status',
};

/**
 * Voluntary EEO self-identification.
 *
 * Its own component in its own file, deliberately, and it must stay that way: a
 * static guard in the backend restricts which modules may read this record at all,
 * on the rule that nothing on the way to an application form may touch it. Keeping
 * this form separate is the frontend half of the same discipline — nothing that
 * fills a form imports it.
 *
 * The most important thing on the screen is the sentence saying ApplyFlow will
 * never fill these answers in. That refusal is unconditional in the backend, and a
 * candidate storing this data deserves to know that storing it does not mean
 * disclosing it: whether to answer these questions stays a decision they make per
 * application.
 */
export function EeoSection({ hasProfile }: Props) {
  const [record, setRecord] = useState<EeoSelfIdentification | null>(null);
  const [answers, setAnswers] = useState<Record<Category, string>>({
    gender_identity: '',
    race_ethnicity: '',
    veteran_status: '',
    disability_status: '',
  });
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!hasProfile) return;
    applyFlowApi
      .getEeoSelfIdentification()
      .then((loaded) => {
        setRecord(loaded);
        setAnswers({
          gender_identity: loaded.gender_identity ?? '',
          race_ethnicity: loaded.race_ethnicity ?? '',
          veteran_status: loaded.veteran_status ?? '',
          disability_status: loaded.disability_status ?? '',
        });
        setAcknowledged(loaded.consent_granted);
      })
      .catch((caught: unknown) =>
        setError(caught instanceof Error ? caught.message : String(caught)),
      );
  }, [hasProfile]);

  if (!hasProfile) {
    return (
      <section className="card profile-section">
        <h3>Voluntary self-identification</h3>
        <p className="quiet profile-locked">Save your name and email first.</p>
      </section>
    );
  }

  const save = async (clearing = false) => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await applyFlowApi.saveEeoSelfIdentification(
        clearing
          ? { consent_acknowledged: false }
          : {
              gender_identity: answers.gender_identity || null,
              race_ethnicity: answers.race_ethnicity || null,
              veteran_status: answers.veteran_status || null,
              disability_status: answers.disability_status || null,
              consent_acknowledged: acknowledged,
            },
      );
      setRecord(updated);
      setSaved(true);
      if (clearing) {
        setAnswers({
          gender_identity: '',
          race_ethnicity: '',
          veteran_status: '',
          disability_status: '',
        });
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card profile-section">
      <h3>Voluntary self-identification</h3>
      <p className="quiet">
        <strong>ApplyFlow will never fill these answers in for you.</strong> Whether
        to answer them is your decision on each individual application. Storing them
        here only means you can see and change what is on file — it does not disclose
        anything to any employer.
      </p>
      <p className="quiet">Every question is optional, and you can leave any blank.</p>

      <div className="profile-fields">
        {(Object.keys(CATEGORIES) as Category[]).map((category) => (
          <label key={category}>
            {TITLES[category]}
            <select
              value={answers[category]}
              onChange={(event) =>
                setAnswers({ ...answers, [category]: event.target.value })
              }
            >
              <option value="">Not answered</option>
              {CATEGORIES[category].map((value) => (
                <option key={value} value={value}>
                  {label(value)}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>

      <label className="consent-row">
        <input
          type="checkbox"
          checked={acknowledged}
          onChange={(event) => setAcknowledged(event.target.checked)}
        />
        <span>
          I agree to ApplyFlow storing these answers. I understand they will never be
          submitted on my behalf, and I can delete them at any time.
        </span>
      </label>

      <div className="profile-section-actions">
        <button type="button" onClick={() => save()} disabled={busy}>
          {busy ? 'Saving…' : 'Save'}
        </button>
        {record?.source ? (
          <button type="button" onClick={() => save(true)} disabled={busy}>
            Delete what is stored
          </button>
        ) : null}
        {saved ? <span className="quiet">Saved.</span> : null}
      </div>

      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
