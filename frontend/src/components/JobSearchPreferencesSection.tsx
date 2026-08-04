import { useState } from 'react';
import { applyFlowApi } from '../api/client';
import { label } from '../labels';
import type { Profile } from '../types';

interface Props {
  profile: Profile | null;
  onSaved: (profile: Profile) => void;
}

const EMPLOYMENT_TYPES = [
  'internship',
  'co_op',
  'new_grad',
  'full_time',
  'part_time',
  'contract',
];

const SEASONS = ['spring', 'summer', 'fall', 'winter'];

/** Grouped only for scanning — the backend treats them as one flat set. */
const FUNCTION_GROUPS: { label: string; functions: string[] }[] = [
  {
    label: 'Engineering & data',
    functions: [
      'software_engineering',
      'data_analytics',
      'data_science',
      'hardware_engineering',
      'research',
    ],
  },
  {
    label: 'Product & design',
    functions: ['product_management', 'design'],
  },
  {
    label: 'Finance',
    functions: [
      'quantitative_finance',
      'investment_banking',
      'finance_accounting',
    ],
  },
  {
    label: 'Business',
    functions: [
      'consulting',
      'marketing',
      'sales',
      'operations',
      'human_resources',
      'legal',
    ],
  },
];

/** Years offered for a term. Terms are advertised well ahead, so this runs from
 *  last year (postings linger) to three years out. */
function termYears(): number[] {
  const current = new Date().getFullYear();
  return [current - 1, current, current + 1, current + 2, current + 3];
}

interface DraftTerm {
  season: string;
  /** Empty string means "any year of this season". */
  year: string;
}

/**
 * What kinds of role and which terms to show — the only section here that
 * records a *want* rather than a fact about the candidate.
 *
 * Both lists are opt-in and both default to empty, which means "show me
 * everything". That is stated on the form because the opposite reading —
 * "nothing selected, so nothing matches" — is the natural one and would be
 * wrong.
 */
export function JobSearchPreferencesSection({ profile, onSaved }: Props) {
  const current = profile?.job_search_preferences;
  const [types, setTypes] = useState<string[]>(current?.employment_types ?? []);
  const [functions, setFunctions] = useState<string[]>(
    current?.functions ?? [],
  );
  const [terms, setTerms] = useState<DraftTerm[]>(
    (current?.terms ?? []).map((term) => ({
      season: term.season,
      year: term.year === null ? '' : String(term.year),
    })),
  );
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!profile) {
    return (
      <section className="card profile-section">
        <h3>What you're looking for</h3>
        <p className="quiet profile-locked">Save your name and email first.</p>
      </section>
    );
  }

  const toggleFunction = (value: string) =>
    setFunctions((existing) =>
      existing.includes(value)
        ? existing.filter((item) => item !== value)
        : [...existing, value],
    );

  const toggleType = (value: string) =>
    setTypes((existing) =>
      existing.includes(value)
        ? existing.filter((item) => item !== value)
        : [...existing, value],
    );

  const save = async () => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      onSaved(
        await applyFlowApi.saveJobSearchPreferences({
          employment_types: types,
          functions,
          // A blank year is sent as null, meaning any year of that season —
          // not dropped, because the season alone is a real preference.
          terms: terms
            .filter((term) => term.season)
            .map((term) => ({
              season: term.season,
              year: term.year ? Number(term.year) : null,
            })),
        }),
      );
      setSaved(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const nothingSelected =
    types.length === 0 && terms.length === 0 && functions.length === 0;

  return (
    <section className="card profile-section">
      <h3>What you're looking for</h3>
      <p className="quiet">
        Used to decide which jobs you're shown — never written onto an
        application. Leave a section empty to see everything.
      </p>

      <fieldset className="profile-subject-list">
        <legend>Kind of role</legend>
        {EMPLOYMENT_TYPES.map((value) => (
          <label key={value} className="profile-checkbox-row">
            <input
              type="checkbox"
              checked={types.includes(value)}
              disabled={busy}
              onChange={() => toggleType(value)}
            />
            {label(value)}
          </label>
        ))}
      </fieldset>

      <fieldset className="profile-subject-list">
        <legend>Kind of work</legend>
        <p className="quiet">
          What you want to do — not the employer's industry. A software role at a
          hedge fund is software engineering, not quant finance.
        </p>
        {FUNCTION_GROUPS.map((group) => (
          <div key={group.label}>
            <span className="section-label">{group.label}</span>
            {group.functions.map((value) => (
              <label key={value} className="profile-checkbox-row">
                <input
                  type="checkbox"
                  checked={functions.includes(value)}
                  disabled={busy}
                  onChange={() => toggleFunction(value)}
                />
                {label(value)}
              </label>
            ))}
          </div>
        ))}
      </fieldset>

      <fieldset className="profile-subject-list">
        <legend>Terms</legend>
        <p className="quiet">
          For internships and co-ops. Leave the year as "any" to see every year
          of that season.
        </p>
        {terms.map((term, index) => (
          // Index as key: these rows have no stable identity and are not
          // reordered.
          <div className="profile-subject-row" key={index}>
            <select
              value={term.season}
              disabled={busy}
              onChange={(event) =>
                setTerms(
                  terms.map((existing, at) =>
                    at === index
                      ? { ...existing, season: event.target.value }
                      : existing,
                  ),
                )
              }
            >
              {SEASONS.map((season) => (
                <option key={season} value={season}>
                  {label(season)}
                </option>
              ))}
            </select>
            <select
              value={term.year}
              disabled={busy}
              onChange={(event) =>
                setTerms(
                  terms.map((existing, at) =>
                    at === index
                      ? { ...existing, year: event.target.value }
                      : existing,
                  ),
                )
              }
            >
              <option value="">any year</option>
              {termYears().map((year) => (
                <option key={year} value={String(year)}>
                  {year}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="profile-subject-remove"
              aria-label={`Remove term ${index + 1}`}
              disabled={busy}
              onClick={() => setTerms(terms.filter((_, at) => at !== index))}
            >
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          className="profile-subject-add"
          disabled={busy}
          onClick={() => setTerms([...terms, { season: 'summer', year: '' }])}
        >
          + Add term
        </button>
      </fieldset>

      <div className="profile-section-actions">
        <button type="button" onClick={save} disabled={busy}>
          Save preferences
        </button>
        {saved ? <span className="quiet">Saved.</span> : null}
      </div>

      {nothingSelected ? (
        <p className="quiet">
          Nothing selected, so every kind of role, every function and every
          term will be shown.
        </p>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
