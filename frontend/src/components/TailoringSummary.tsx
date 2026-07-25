import type { RankedJob } from '../types';

interface Props {
  job: RankedJob;
  content: string;
  backingSources: string[];
  answeredGaps: string[];
}

/** One of the job's own asks, and whether this document speaks to it. */
interface Coverage {
  requirement: string;
  weight: 'required' | 'preferred';
  covered: boolean;
}

/**
 * Whether `content` speaks to `requirement`.
 *
 * Word-level rather than substring, so "Go" does not match "Django" and
 * "R" does not match "React". A multi-word requirement counts as covered
 * when every one of its words appears — loose enough for "Kubernetes
 * (EKS)" to match a résumé's "Kubernetes", strict enough that "distributed
 * systems" needs both words.
 *
 * This is a display heuristic and nothing more: it reports what the
 * document happens to mention. It never decides what a document may say —
 * that is `ProvenanceGuard`'s job, on the server, against the candidate's
 * attested facts rather than the employer's wish list.
 */
function mentions(content: string, requirement: string): boolean {
  const haystack = new Set(content.toLowerCase().match(/[a-z0-9+#]+/g) ?? []);
  const needles = requirement.toLowerCase().match(/[a-z0-9+#]+/g) ?? [];
  return needles.length > 0 && needles.every((word) => haystack.has(word));
}

const SOURCE_LABELS: Record<string, string> = {
  parsed_resume: 'your parsed résumé',
  user_entered: 'details you entered',
  answer: 'answers you gave',
};

/**
 * What was tailored for this job, and on what basis.
 *
 * Three distinct claims, kept separate because they answer different
 * questions: which of the posting's stated requirements this document
 * addresses, which of the match's gaps the candidate filled in during the
 * question loop, and which of their own data the surviving content traces
 * back to. "Not mentioned" is shown as plainly as "covered" — a tailoring
 * summary that only listed hits would read as a score, and the useful
 * signal here is the miss.
 */
export function TailoringSummary({
  job,
  content,
  backingSources,
  answeredGaps,
}: Props) {
  const requirements = job.job_posting.requirements;
  const coverage: Coverage[] = [
    ...(requirements?.required_skills ?? []).map((requirement) => ({
      requirement,
      weight: 'required' as const,
      covered: mentions(content, requirement),
    })),
    ...(requirements?.preferred_skills ?? []).map((requirement) => ({
      requirement,
      weight: 'preferred' as const,
      covered: mentions(content, requirement),
    })),
  ];
  const coveredCount = coverage.filter((item) => item.covered).length;

  return (
    <div className="tailoring-summary">
      <span className="section-label">
        Tailored for {job.job_posting.title} at {job.job_posting.company}
      </span>

      {coverage.length > 0 ? (
        <>
          <p className="quiet">
            {coveredCount} of {coverage.length} listed skills appear in this document.
          </p>
          <ul className="coverage-list">
            {coverage.map((item) => (
              <li
                key={`${item.weight}-${item.requirement}`}
                className={item.covered ? 'covered' : 'uncovered'}
              >
                <span className="coverage-mark" aria-hidden="true">
                  {item.covered ? '✓' : '—'}
                </span>
                <span>{item.requirement}</span>
                <span className="quiet"> ({item.weight})</span>
                <span className="visually-hidden">
                  {item.covered ? ' — mentioned' : ' — not mentioned'}
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="quiet">
          This posting lists no extracted skills, so there is nothing to check coverage
          against.
        </p>
      )}

      {answeredGaps.length > 0 && (
        <p className="quiet">
          Drawing on {answeredGaps.length} gap answer
          {answeredGaps.length === 1 ? '' : 's'} you gave: {answeredGaps.join('; ')}.
        </p>
      )}

      <p className="quiet">
        Every surviving line traces back to{' '}
        {backingSources.length === 0
          ? 'nothing on file'
          : backingSources
              .map((source) => SOURCE_LABELS[source] ?? source)
              .join(' and ')}
        .
      </p>
    </div>
  );
}
