import type { ReactNode } from 'react';
import { useState } from 'react';

interface Props {
  title: string;
  /** What this section is for, in the candidate's terms. */
  description?: ReactNode;
  /** Where the data came from: 'user_entered', 'parsed_resume', or null. */
  source?: string | null;
  /** Disabled with this note when the profile does not exist yet. */
  lockedReason?: string | null;
  onSave: () => Promise<void>;
  children: ReactNode;
  saveLabel?: string;
}

/**
 * The shell every profile section shares: a heading, its own Save button, and its
 * own saving/error state.
 *
 * Per-section rather than one Save for the whole page, and that is a privacy
 * decision as much as a UI one — correcting a phone number should not put the
 * candidate's citizenship and demographic answers back on the wire. It also means
 * a failure in one section leaves the others untouched instead of stranding a
 * whole page of edits.
 *
 * The provenance badge is the other reason this is shared. A profile built by
 * parsing a résumé is not the same as one the candidate confirmed — and for work
 * authorization that difference decides whether ApplyFlow may put the answer on a
 * form at all — so every section says which it is rather than leaving the
 * candidate to guess.
 */
export function ProfileSection({
  title,
  description,
  source,
  lockedReason,
  onSave,
  children,
  saveLabel = 'Save',
}: Props) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const save = async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await onSave();
      setSaved(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="card profile-section">
      <header className="profile-section-head">
        <h3>{title}</h3>
        {source ? <ProvenanceBadge source={source} /> : null}
      </header>
      {description ? <p className="quiet">{description}</p> : null}

      {lockedReason ? (
        <p className="quiet profile-locked">{lockedReason}</p>
      ) : (
        <>
          <div className="profile-fields">{children}</div>
          <div className="profile-section-actions">
            <button type="button" onClick={save} disabled={saving}>
              {saving ? 'Saving…' : saveLabel}
            </button>
            {saved ? <span className="quiet">Saved.</span> : null}
          </div>
        </>
      )}

      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}

/**
 * Says whether the candidate stated this themselves or it was read off a résumé.
 *
 * Not decoration. `parsed_resume` data is never asserted to an employer on the
 * candidate's behalf — a model's reading of a résumé is not a declaration anyone
 * made — so this badge is what explains why some answers still get handed back on
 * every application until the candidate confirms them.
 */
function ProvenanceBadge({ source }: { source: string }) {
  const stated = source === 'user_entered' || source === 'answer';
  return (
    <span className={stated ? 'badge badge-stated' : 'badge badge-parsed'}>
      {stated ? 'You entered this' : 'From your résumé'}
    </span>
  );
}
