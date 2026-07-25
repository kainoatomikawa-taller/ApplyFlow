import type { FeedbackRating, RankedJob } from '../types';
import { JobMatchCard } from './JobMatchCard';

interface Props {
  jobs: RankedJob[];
  feedbackByJobId: Record<string, FeedbackRating>;
  busyJobIds: Set<string>;
  selectedJobId: string | null;
  onFeedback: (jobPostingId: string, rating: FeedbackRating) => void;
  onTailor: (jobPostingId: string) => void;
}

export function JobMatchList({
  jobs,
  feedbackByJobId,
  busyJobIds,
  selectedJobId,
  onFeedback,
  onTailor,
}: Props) {
  if (jobs.length === 0) {
    return <p>No matched roles yet — check back once new postings are ranked.</p>;
  }

  return (
    <div>
      {jobs.map((job) => (
        <JobMatchCard
          key={job.job_posting.id}
          job={job}
          feedback={feedbackByJobId[job.job_posting.id] ?? null}
          busy={busyJobIds.has(job.job_posting.id)}
          selected={selectedJobId === job.job_posting.id}
          onFeedback={(rating) => onFeedback(job.job_posting.id, rating)}
          onTailor={() => onTailor(job.job_posting.id)}
        />
      ))}
    </div>
  );
}
