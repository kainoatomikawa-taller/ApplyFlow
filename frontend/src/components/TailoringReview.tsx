import { useState } from 'react';
import { DocumentReviewPanel } from './DocumentReviewPanel';
import { PortalHandoffPanel } from './PortalHandoffPanel';
import { ReviewAndSubmit } from './ReviewAndSubmit';
import { GapQuestionLoop } from './GapQuestionLoop';
import type { GapOutcome } from './GapQuestionLoop';
import type { RankedJob } from '../types';

interface Props {
  job: RankedJob;
  onClose: () => void;
}

/**
 * The review flow for one job: answer the gap questions, then read, edit,
 * and store the documents that come out of it.
 *
 * Ordered rather than tabbed, because the order is causal — a gap answer
 * becomes an attested fact about the candidate, so an answer given in step
 * one is material the documents in step two can be built from and validated
 * against. Generating first and answering afterwards would produce a
 * thinner document for no reason.
 *
 * The gate is soft on purpose: `canGenerate` opens once the loop reports
 * done, but "Skip to documents" is always there. A candidate with nothing
 * to add to any gap should not have to click through every question to
 * reach the thing they came for.
 *
 * Step three is the portal itself: ApplyFlow reads the application form before
 * touching it, and stops outright at a CAPTCHA, a signature, or a sign-in wall
 * (see `PortalHandoffPanel`). It is not gated behind the documents — a
 * candidate who wants to know up front whether this portal is one they will
 * have to finish by hand should be able to find out first.
 *
 * Step four is where the application actually gets sent, and it is the
 * candidate who sends it (see `ReviewAndSubmit`). Last for a real reason rather
 * than for tidiness: it fills the form from the profile, the gap answers, and
 * the documents produced above, so running it earlier would submit a thinner
 * application than the one the candidate just spent three steps improving.
 */
export function TailoringReview({ job, onClose }: Props) {
  const [outcomes, setOutcomes] = useState<GapOutcome[]>([]);
  const [gapsDone, setGapsDone] = useState(false);

  const answeredGaps = outcomes.filter((o) => o.captured).map((o) => o.gap);
  const showDocuments = gapsDone || job.gaps.length === 0;

  return (
    <section className="tailoring-review">
      <div className="tailoring-header">
        <div>
          <h2>
            Tailoring: {job.job_posting.title} @ {job.job_posting.company}
          </h2>
          <p className="quiet">
            Match score {job.score}/100 · {job.gaps.length} gap
            {job.gaps.length === 1 ? '' : 's'}
          </p>
        </div>
        <button type="button" className="secondary" onClick={onClose}>
          Close
        </button>
      </div>

      <section className="card">
        <h3>
          <span className="step-number">1</span> Fill the gaps
        </h3>
        <GapQuestionLoop
          job={job}
          outcomes={outcomes}
          onResolved={(outcome) => setOutcomes((prev) => [...prev, outcome])}
          onFinished={() => setGapsDone(true)}
        />
        {!showDocuments && (
          <button
            type="button"
            className="link-button"
            onClick={() => setGapsDone(true)}
          >
            Skip to documents
          </button>
        )}
      </section>

      <h3>
        <span className="step-number">2</span> Review the documents
      </h3>
      {showDocuments ? (
        <>
          <DocumentReviewPanel
            job={job}
            kind="tailored_resume"
            title="Tailored résumé"
            answeredGaps={answeredGaps}
          />
          <DocumentReviewPanel
            job={job}
            kind="cover_letter"
            title="Cover letter"
            answeredGaps={answeredGaps}
          />
        </>
      ) : (
        <p className="muted">
          Answer or skip the gap questions above first — your answers become material
          the documents can draw on.
        </p>
      )}

      <h3>
        <span className="step-number">3</span> Check the portal
      </h3>
      <PortalHandoffPanel jobPostingId={job.job_posting.id} />

      {/*
        Fourth, and after the documents, because the fill attaches the stored
        versions of them: running it before they exist would surface the
        résumé and cover-letter fields as "not generated yet" and the
        candidate would have to run it twice.
      */}
      <h3>
        <span className="step-number">4</span> Review &amp; submit
      </h3>
      <ReviewAndSubmit
        jobPostingId={job.job_posting.id}
        jobTitle={job.job_posting.title}
        company={job.job_posting.company}
      />
    </section>
  );
}
