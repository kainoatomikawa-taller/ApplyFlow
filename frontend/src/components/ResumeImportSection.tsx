import { useRef, useState } from 'react';
import { applyFlowApi } from '../api/client';
import type { Profile } from '../types';

interface Props {
  profile: Profile | null;
  onSaved: (profile: Profile) => void;
}

/** What the backend will accept — see `Resume.ALLOWED_CONTENT_TYPES`. */
const ACCEPTED = '.pdf,.docx,.txt';

/**
 * Import a résumé to fill in the profile.
 *
 * Placed first in the editor because it is the fastest way to a populated
 * profile, but it is a shortcut and not a prerequisite: every section below can
 * be filled in by hand, and the contact section alone can bring a profile into
 * existence.
 *
 * Two calls rather than one: the file is stored and its text extracted first
 * (`uploadResume`), then read onto the profile (`parseResume`). Keeping them
 * separate is what lets the second step be re-run, and means a parse that fails
 * has not lost the upload.
 */
export function ResumeImportSection({ profile, onSaved }: Props) {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const importResume = async (file: File) => {
    setBusy(true);
    setError(null);
    setStatus('Uploading and reading the file…');
    try {
      const stored = await applyFlowApi.uploadResume(file);
      setStatus('Pulling out what it states…');
      onSaved(await applyFlowApi.parseResume(stored.id));
      setStatus(`Imported from ${stored.original_filename}. Review it below.`);
    } catch (caught) {
      setStatus(null);
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
      // Cleared so choosing the same file again re-fires onChange, which it
      // otherwise would not — a retry after a failure is the common case.
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  return (
    <section className="card profile-section">
      <h3>Import from a résumé</h3>
      <p className="quiet">
        Upload a PDF, Word document, or text file and ApplyFlow will fill in what
        it can read — name, contact details, links, work history, education, and
        skills. Anything it cannot find is left blank for you to type, and
        everything it does fill in stays editable below.
      </p>
      <p className="quiet">
        {profile
          ? 'Your existing answers are kept: this only fills gaps and adds entries you do not already have, so re-importing is safe.'
          : 'This will create your profile. A résumé is optional — you can also start by filling in the contact section below.'}
      </p>
      <p className="quiet">
        Work authorization and voluntary self-identification are never taken from
        a résumé; those stay yours to state.
      </p>

      <div className="profile-section-actions">
        <input
          ref={fileInput}
          type="file"
          accept={ACCEPTED}
          disabled={busy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void importResume(file);
          }}
        />
      </div>

      {status ? <p className="quiet">{status}</p> : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
