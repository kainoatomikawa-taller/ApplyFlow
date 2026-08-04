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
  // One blank major row to type into, since nearly everyone has exactly one; no
  // minor row, since most people have none and an empty row would read as a
  // question being asked.
  majors: [''],
  minors: [],
  start_date: null,
  end_date: null,
  description: null,
};

/** Common degree names, grouped by level, as `[name, abbreviation]`.
 *
 * The name is what gets stored, and it is typed *verbatim* into employer forms
 * (`profile_field_values._degree` resolves through `_verbatim`). So each value
 * is the clean credential name with no parenthetical; the abbreviation appears
 * only in the dropdown label, to keep the list scannable by the shorthand
 * people actually think in ("BS", "PhD").
 *
 * Not to be confused with `DEGREE_LEVELS` in the Qualifications section. That
 * is the five-member `DegreeLevel` domain enum, used to compare the candidate
 * against a posting's stated requirement. This list is presentation only —
 * `EducationEntry.degree` stays free text in the domain, which is what lets
 * both "Other" and résumé-parsed values through unchanged.
 */
const DEGREE_GROUPS: ReadonlyArray<{
  label: string;
  degrees: ReadonlyArray<readonly [string, string]>;
}> = [
  {
    label: 'Secondary',
    degrees: [
      ['High School Diploma', ''],
      ['GED', ''],
    ],
  },
  {
    label: 'Associate',
    degrees: [
      ['Associate of Arts', 'AA'],
      ['Associate of Science', 'AS'],
      ['Associate of Applied Science', 'AAS'],
    ],
  },
  {
    label: "Bachelor's",
    degrees: [
      ['Bachelor of Arts', 'BA'],
      ['Bachelor of Science', 'BS'],
      ['Bachelor of Business Administration', 'BBA'],
      ['Bachelor of Engineering', 'BEng'],
      ['Bachelor of Fine Arts', 'BFA'],
      ['Bachelor of Science in Nursing', 'BSN'],
    ],
  },
  {
    label: "Master's",
    degrees: [
      ['Master of Arts', 'MA'],
      ['Master of Science', 'MS'],
      ['Master of Business Administration', 'MBA'],
      ['Master of Engineering', 'MEng'],
      ['Master of Fine Arts', 'MFA'],
      ['Master of Public Health', 'MPH'],
      ['Master of Social Work', 'MSW'],
      ['Master of Education', 'MEd'],
    ],
  },
  {
    label: 'Doctoral and professional',
    degrees: [
      ['Doctor of Philosophy', 'PhD'],
      ['Doctor of Medicine', 'MD'],
      ['Juris Doctor', 'JD'],
      ['Doctor of Education', 'EdD'],
      ['Doctor of Dental Surgery', 'DDS'],
      ['Doctor of Veterinary Medicine', 'DVM'],
      ['Doctor of Pharmacy', 'PharmD'],
      ['Doctor of Nursing Practice', 'DNP'],
      ['Doctor of Psychology', 'PsyD'],
    ],
  },
  {
    label: 'Other programs',
    degrees: [
      ['Certificate', ''],
      ['Diploma', ''],
      ['Bootcamp', ''],
      ['Coursework, no degree awarded', ''],
    ],
  },
];

/** Sentinel for the "Other" option. Cannot collide with a real degree name. */
const OTHER = '__other__';

const LISTED_DEGREES: ReadonlySet<string> = new Set(
  DEGREE_GROUPS.flatMap((group) => group.degrees.map(([name]) => name)),
);

const degreeLabel = ([name, abbreviation]: readonly [string, string]) =>
  abbreviation ? `${name} (${abbreviation})` : name;

interface SubjectListProps {
  legend: string;
  addLabel: string;
  placeholder: string;
  values: string[];
  onChange: (values: string[]) => void;
  disabled: boolean;
}

/** A repeatable one-input-per-subject list, for majors and for minors.
 *
 * Rows are kept even when blank, and blanks are dropped server-side — so an
 * empty row is a place to type rather than a value, and the two lists can be
 * edited without the component needing to guess when a row "counts".
 */
function SubjectList({
  legend,
  addLabel,
  placeholder,
  values,
  onChange,
  disabled,
}: SubjectListProps) {
  const replaceAt = (index: number, value: string) =>
    onChange(values.map((existing, at) => (at === index ? value : existing)));

  return (
    <fieldset className="profile-subject-list">
      <legend>{legend}</legend>
      {values.map((value, index) => (
        // Index as key: these rows have no stable identity, and reordering is
        // not offered. Removing a row re-renders the ones after it, which is
        // correct here because their values shift up with them.
        <div className="profile-subject-row" key={index}>
          <input
            placeholder={placeholder}
            value={value}
            onChange={(event) => replaceAt(index, event.target.value)}
          />
          <button
            type="button"
            className="profile-subject-remove"
            aria-label={`Remove ${legend.toLowerCase()} ${index + 1}`}
            disabled={disabled}
            onClick={() => onChange(values.filter((_, at) => at !== index))}
          >
            ×
          </button>
        </div>
      ))}
      <button
        type="button"
        className="profile-subject-add"
        disabled={disabled}
        onClick={() => onChange([...values, ''])}
      >
        {addLabel}
      </button>
    </fieldset>
  );
}

/** Education — same per-entry add/edit/delete shape as work history, and for the
 * same provenance reason. */
export function EducationSection({ profile, onSaved }: Props) {
  const [draft, setDraft] = useState<EducationInput>(EMPTY);
  const [editingId, setEditingId] = useState<string | null>(null);
  // Whether the degree is being typed rather than picked. Tracked separately
  // from the value because "" is a legitimate freeform-in-progress state and is
  // indistinguishable from "nothing picked yet" by value alone.
  const [degreeIsFreeform, setDegreeIsFreeform] = useState(false);
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
      setDegreeIsFreeform(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const startEditing = (entry: ProfileEducationEntry) => {
    setEditingId(entry.id);
    // A stored degree that is not one of the listed names — anything typed as
    // "Other", or parsed off a résumé as "B.Sc. (Hons)" — reopens as freeform
    // with the original text intact. Snapping it to a dropdown entry would
    // rewrite a value the user never touched, and that value is what gets typed
    // onto employer forms.
    setDegreeIsFreeform(!LISTED_DEGREES.has(entry.degree));
    setDraft({
      institution_name: entry.institution_name,
      degree: entry.degree,
      // A stored entry with no majors still gets one row to type into.
      majors: entry.majors.length > 0 ? [...entry.majors] : [''],
      minors: [...entry.minors],
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
              {entry.majors.length > 0 ? (
                <span className="quiet"> · {entry.majors.join(', ')}</span>
              ) : null}
              {entry.minors.length > 0 ? (
                <span className="quiet">
                  {' '}
                  · minor in {entry.minors.join(', ')}
                </span>
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
          <select
            value={degreeIsFreeform ? OTHER : draft.degree}
            onChange={(event) => {
              const picked = event.target.value;
              if (picked === OTHER) {
                setDegreeIsFreeform(true);
                setDraft({ ...draft, degree: '' });
                return;
              }
              setDegreeIsFreeform(false);
              setDraft({ ...draft, degree: picked });
            }}
          >
            <option value="">Select a degree…</option>
            {DEGREE_GROUPS.map((group) => (
              <optgroup key={group.label} label={group.label}>
                {group.degrees.map((degree) => (
                  <option key={degree[0]} value={degree[0]}>
                    {degreeLabel(degree)}
                  </option>
                ))}
              </optgroup>
            ))}
            <option value={OTHER}>Other…</option>
          </select>
        </label>
        {degreeIsFreeform ? (
          <label>
            Degree name
            <input
              autoFocus
              placeholder="e.g. Bachelor of Applied Arts"
              value={draft.degree}
              onChange={(event) => setDraft({ ...draft, degree: event.target.value })}
            />
          </label>
        ) : null}
        <SubjectList
          legend="Major"
          addLabel="+ Add major"
          placeholder="e.g. Computer Science"
          values={draft.majors}
          onChange={(majors) => setDraft({ ...draft, majors })}
          disabled={busy}
        />
        <SubjectList
          legend="Minor"
          addLabel="+ Add minor"
          placeholder="e.g. Economics"
          values={draft.minors}
          onChange={(minors) => setDraft({ ...draft, minors })}
          disabled={busy}
        />
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
          // Institution and degree are the domain's two required fields, and
          // "Other" with nothing typed leaves degree empty. Blocked here so that
          // case reads as an unfinished form rather than arriving as a 400.
          disabled={busy || !draft.institution_name.trim() || !draft.degree.trim()}
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
              setDegreeIsFreeform(false);
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
