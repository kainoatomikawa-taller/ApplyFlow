import { useState } from 'react';
import { applyFlowApi } from '../api/client';
import type { SentDocument, StoredApplicationDocument } from '../types';

interface Props {
  label: string;
  /**
   * The reference frozen onto the application at send time, or null when the
   * stored reference no longer resolves.
   */
  reference: SentDocument | null;
  /** Stem for the download filename — "Globex-Senior-Platform-Engineer". */
  downloadStem: string;
}

/**
 * One document as it went out with an application, and — on request — the
 * exact text of it.
 *
 * **Named first, read on demand.** The line always shows what the reference
 * says: which document, which version, and the digest of the bytes that were
 * archived. The text is fetched only when the candidate opens it, by id, from
 * `GET /api/application-documents/{id}`. That is not laziness for its own
 * sake: the list route deliberately carries no document text, so opening
 * thirty rows worth of resumes is a thing the API will not do in one call and
 * should not be faked by a client that asks thirty times on load.
 *
 * **By id, never "the latest for this job".** A candidate who revised their
 * resume after applying has a newer version stored against the same posting.
 * Reading that would show a document the employer never received — the exact
 * failure the snapshot-by-id design exists to prevent, and it would be
 * undone here rather than in the backend.
 *
 * **The digest is checked, not just displayed.** The backend verifies a
 * snapshot against its own hash before serving it. What this component adds
 * is the other half: the returned digest is compared against the one the
 * *application* froze at send time, and on a mismatch the text is withheld
 * rather than shown under a claim it cannot support. The two can only differ
 * if the reference resolved to something other than the archived snapshot,
 * which is precisely the case where "this is what was sent" must not appear
 * above a document body.
 */
export function SentDocumentLine({ label, reference, downloadStem }: Props) {
  const [snapshot, setSnapshot] = useState<StoredApplicationDocument | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (reference === null) {
    return (
      <li className="sent-document missing">
        <span className="sent-document-label">{label}</span>
        <span className="quiet">not on file</span>
      </li>
    );
  }

  const toggle = async () => {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    // Archived text never changes, so one fetch per document is enough —
    // re-reading on every open would be a request that cannot return
    // anything different.
    if (snapshot !== null) return;
    setBusy(true);
    setError(null);
    try {
      setSnapshot(await applyFlowApi.getApplicationDocument(reference.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      setOpen(false);
    } finally {
      setBusy(false);
    }
  };

  const mismatched =
    snapshot !== null && snapshot.content_sha256 !== reference.content_sha256;

  return (
    <li className="sent-document">
      <div className="sent-document-line">
        <span className="sent-document-label">
          {label} <span className="pill pill-version">v{reference.version}</span>
        </span>
        <code className="sent-document-digest" title={reference.content_sha256}>
          {reference.content_sha256.slice(0, 12)}
        </code>
        <button
          type="button"
          className="link-button"
          disabled={busy}
          aria-expanded={open}
          onClick={() => void toggle()}
        >
          {busy ? 'Opening…' : open ? 'Hide' : 'View what was sent'}
        </button>
      </div>

      {error !== null && <p className="error">{error}</p>}

      {open && mismatched && (
        <p className="error">
          The stored snapshot no longer matches the digest this application
          recorded, so its text is not shown — it cannot be presented as what
          the employer received.
        </p>
      )}

      {open && snapshot !== null && !mismatched && (
        <div className="sent-document-body">
          <p className="quiet sent-document-meta">
            Archived {new Date(snapshot.created_at).toLocaleString()} · version{' '}
            {snapshot.version} · sha256 <code>{snapshot.content_sha256}</code>
          </p>
          <pre className="sent-document-content">{snapshot.content}</pre>
          <a
            className="link-button"
            href={`data:text/plain;charset=utf-8,${encodeURIComponent(snapshot.content)}`}
            download={`${downloadStem}-${snapshot.document_kind}-v${snapshot.version}.txt`}
          >
            Download this exact text
          </a>
        </div>
      )}
    </li>
  );
}
