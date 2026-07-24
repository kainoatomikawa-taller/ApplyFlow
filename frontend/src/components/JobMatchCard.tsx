import type { FeedbackRating, RankedJob } from '../types';

interface Props {
  job: RankedJob;
  feedback: FeedbackRating | null;
  busy: boolean;
  onFeedback: (rating: FeedbackRating) => void;
}

function scoreTier(score: number): 'high' | 'medium' | 'low' {
  if (score >= 80) return 'high';
  if (score >= 60) return 'medium';
  return 'low';
}

export function JobMatchCard({ job, feedback, busy, onFeedback }: Props) {
  const { job_posting: posting, score, rationale, gaps } = job;

  return (
    <div className="card job-match-card">
      <div className="job-match-header">
        <div>
          <h3>{posting.title}</h3>
          <p className="job-match-subtitle">
            {posting.company}
            {posting.location && <> · {posting.location}</>}
            {posting.is_remote && posting.location?.toLowerCase() !== 'remote' && (
              <> · Remote</>
            )}
          </p>
        </div>
        <span className={`score-badge score-${scoreTier(score)}`}>{score}/100</span>
      </div>

      <p className="rationale">{rationale}</p>

      {gaps.length > 0 && (
        <div className="gaps">
          <span className="gaps-label">Gaps</span>
          <ul>
            {gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="job-match-footer">
        <a href={posting.apply_url} target="_blank" rel="noreferrer">
          View posting
        </a>
        <div className="feedback-buttons">
          <button
            type="button"
            className={`feedback-btn${feedback === 'thumbs_up' ? ' active' : ''}`}
            disabled={busy}
            aria-pressed={feedback === 'thumbs_up'}
            aria-label="Thumbs up — good match"
            onClick={() => onFeedback('thumbs_up')}
          >
            👍
          </button>
          <button
            type="button"
            className={`feedback-btn${feedback === 'thumbs_down' ? ' active' : ''}`}
            disabled={busy}
            aria-pressed={feedback === 'thumbs_down'}
            aria-label="Thumbs down — poor match"
            onClick={() => onFeedback('thumbs_down')}
          >
            👎
          </button>
        </div>
      </div>
    </div>
  );
}
