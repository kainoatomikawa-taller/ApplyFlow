import { useEffect, useState } from 'react';
import { applyFlowApi } from '../api/client';
import { label } from '../labels';
import type { WorkAuthorization } from '../types';

interface Props {
  hasProfile: boolean;
}

const STATUSES = [
  'citizen',
  'permanent_resident',
  'visa_holder',
  'requires_sponsorship',
  'not_authorized',
  'other',
];

/**
 * Work authorization — the section that makes ApplyFlow able to answer the legal
 * questions on an application.
 *
 * This is the data the whole sensitive-field apparatus reads from, and until this
 * form existed there was no way to supply it: the résumé parser deliberately does
 * not produce it (a model's reading of a visa mention is not a declaration anyone
 * made), and there was no endpoint. So every "are you authorized to work?" question
 * was handed back to the candidate on every application, forever.
 *
 * Two things on this form are load-bearing rather than decorative:
 *
 * - **The consent checkbox.** This is special-category data, stored only with an
 *   explicit agreement. It travels in the same request as the answers, so it is one
 *   form and one button — but it is a real box that has to be ticked, not something
 *   inferred from the save happening.
 * - **The attestation note.** A record read off a résumé cannot be put on a form;
 *   only the candidate's own statement can. Saving here makes it theirs, and the
 *   note says so, because otherwise "why is it still asking me this?" has no
 *   visible answer.
 */
export function WorkAuthorizationSection({ hasProfile }: Props) {
  const [record, setRecord] = useState<WorkAuthorization | null>(null);
  const [status, setStatus] = useState('');
  const [citizenship, setCitizenship] = useState('');
  const [visaType, setVisaType] = useState('');
  const [sponsorship, setSponsorship] = useState<string>('');
  const [details, setDetails] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!hasProfile) return;
    applyFlowApi
      .getWorkAuthorization()
      .then((loaded) => {
        setRecord(loaded);
        setStatus(loaded.status ?? '');
        setCitizenship(loaded.citizenship_country ?? '');
        setVisaType(loaded.visa_type ?? '');
        setSponsorship(
          loaded.requires_sponsorship === null
            ? ''
            : String(loaded.requires_sponsorship),
        );
        setDetails(loaded.details ?? '');
        // Pre-ticked for someone who has already agreed, so correcting a visa
        // type does not make them re-affirm.
        setAcknowledged(loaded.consent_granted);
      })
      .catch((caught: unknown) =>
        setError(caught instanceof Error ? caught.message : String(caught)),
      );
  }, [hasProfile]);

  if (!hasProfile) {
    return (
      <section className="card profile-section">
        <h3>Work authorization</h3>
        <p className="quiet profile-locked">Save your name and email first.</p>
      </section>
    );
  }

  const save = async (clearing = false) => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await applyFlowApi.saveWorkAuthorization(
        clearing
          ? { status: null, consent_acknowledged: false }
          : {
              status: status || null,
              citizenship_country: citizenship || null,
              visa_type: visaType || null,
              requires_sponsorship:
                sponsorship === '' ? null : sponsorship === 'true',
              details: details || null,
              consent_acknowledged: acknowledged,
            },
      );
      setRecord(updated);
      setSaved(true);
      if (clearing) {
        setStatus('');
        setCitizenship('');
        setVisaType('');
        setSponsorship('');
        setDetails('');
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card profile-section">
      <h3>Work authorization</h3>
      <p className="quiet">
        The legal questions almost every application asks. Answer them once here and
        ApplyFlow can fill them in exactly — it will never approximate them, and it
        will never guess.
      </p>

      {record?.status && !record.is_candidate_attested ? (
        <p className="quiet">
          What is on file came from your résumé, so it cannot be put on an
          application on your behalf. Confirm it below and it will be.
        </p>
      ) : null}

      <div className="profile-fields">
        <label>
          Status
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">Not stated</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {label(value)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Country of citizenship
          <input
            value={citizenship}
            onChange={(event) => setCitizenship(event.target.value)}
          />
        </label>
        <label>
          Visa type
          <input value={visaType} onChange={(event) => setVisaType(event.target.value)} />
        </label>
        <label>
          Will you require sponsorship?
          <select
            value={sponsorship}
            onChange={(event) => setSponsorship(event.target.value)}
          >
            <option value="">Not stated</option>
            <option value="false">No</option>
            <option value="true">Yes</option>
          </select>
        </label>
        <label>
          Anything else
          <textarea
            value={details}
            onChange={(event) => setDetails(event.target.value)}
            rows={2}
          />
        </label>
      </div>

      <label className="consent-row">
        <input
          type="checkbox"
          checked={acknowledged}
          onChange={(event) => setAcknowledged(event.target.checked)}
        />
        <span>
          I agree to ApplyFlow storing my work authorization and citizenship, and any
          EEO self-identification I choose to provide, so it can complete
          applications for me. I can withdraw this at any time.
        </span>
      </label>

      <div className="profile-section-actions">
        <button type="button" onClick={() => save()} disabled={busy}>
          {busy ? 'Saving…' : 'Save'}
        </button>
        {record?.status ? (
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
