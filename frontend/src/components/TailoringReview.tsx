import { useState } from 'react';
import { AutofillReview } from './AutofillReview';
import { DocumentReviewPanel } from './DocumentReviewPanel';
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
        <span className="step-number">3</span> Review and submit
      </h3>
      {/*
        Third, and after the documents, because the autofill attaches the
        stored versions of them: filling before they exist would surface the
        résumé and cover-letter fields as "not generated yet" and the
        candidate would have to run it twice.
      */}
      <AutofillReview job={job} />
    </section>
  );
}
