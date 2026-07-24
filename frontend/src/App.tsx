import { useCallback, useEffect, useState } from 'react';
import { applyFlowApi } from './api/client';
import { ApplicationForm } from './components/ApplicationForm';
import { ApplicationList } from './components/ApplicationList';
import { JobMatchList } from './components/JobMatchList';
import { StatusBanner } from './components/StatusBanner';
import type {
  CreateApplicationInput,
  FeedbackRating,
  JobApplication,
  RankedJob,
} from './types';

const DEMO_EMAIL = 'demo@example.com';

export function App() {
  const [applications, setApplications] = useState<JobApplication[]>([]);
  const [email, setEmail] = useState(DEMO_EMAIL);
  const [error, setError] = useState<string | null>(null);

  const [matchedJobs, setMatchedJobs] = useState<RankedJob[]>([]);
  const [matchesError, setMatchesError] = useState<string | null>(null);
  const [feedbackByJobId, setFeedbackByJobId] = useState<Record<string, FeedbackRating>>({});
  const [busyJobIds, setBusyJobIds] = useState<Set<string>>(new Set());

  const load = useCallback(async (candidateEmail: string) => {
    try {
      setError(null);
      const data = await applyFlowApi.listApplications(candidateEmail);
      setApplications(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  }, []);

  const loadMatches = useCallback(async () => {
    try {
      setMatchesError(null);
      const data = await applyFlowApi.listMatchedJobs();
      setMatchedJobs(data);
    } catch (err) {
      setMatchesError(err instanceof Error ? err.message : 'Unknown error');
    }
  }, []);

  useEffect(() => {
    void load(email);
  }, [email, load]);

  useEffect(() => {
    void loadMatches();
  }, [loadMatches]);

  const handleJobFeedback = async (jobPostingId: string, rating: FeedbackRating) => {
    const job = matchedJobs.find((m) => m.job_posting.id === jobPostingId);
    if (!job) return;

    setBusyJobIds((prev) => new Set(prev).add(jobPostingId));
    try {
      await applyFlowApi.submitJobMatchFeedback(jobPostingId, rating, job.score);
      setFeedbackByJobId((prev) => ({ ...prev, [jobPostingId]: rating }));
    } catch (err) {
      setMatchesError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setBusyJobIds((prev) => {
        const next = new Set(prev);
        next.delete(jobPostingId);
        return next;
      });
    }
  };

  const handleCreate = async (input: CreateApplicationInput) => {
    try {
      await applyFlowApi.createApplication(input);
      await load(input.candidate_email);
      setEmail(input.candidate_email);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const handleSubmit = async (id: string) => {
    try {
      await applyFlowApi.submitApplication(id);
      await load(email);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  return (
    <div className="container">
      <h1>ApplyFlow</h1>
      <p>AI-assisted job application tracking &amp; tailoring.</p>

      <StatusBanner />

      <div className="field">
        <label>Viewing applications for</label>
        <input value={email} onChange={(e) => setEmail(e.target.value)} />
      </div>

      {error && <p className="error">{error}</p>}

      <ApplicationForm onCreate={handleCreate} />
      <ApplicationList applications={applications} onSubmit={handleSubmit} />

      <h2>Matched Roles</h2>
      {matchesError && <p className="error">{matchesError}</p>}
      <JobMatchList
        jobs={matchedJobs}
        feedbackByJobId={feedbackByJobId}
        busyJobIds={busyJobIds}
        onFeedback={handleJobFeedback}
      />
    </div>
  );
}
