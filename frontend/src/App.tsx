import { useCallback, useEffect, useState } from 'react';
import { applyFlowApi } from './api/client';
import { hasAccessToken } from './api/accessToken';
import { AccessTokenField } from './components/AccessTokenField';
import { ApplicationForm } from './components/ApplicationForm';
import { ApplicationList } from './components/ApplicationList';
import { JobMatchList } from './components/JobMatchList';
import { StatusBanner } from './components/StatusBanner';
import { TailoringReview } from './components/TailoringReview';
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
  const [feedbackByJobId, setFeedbackByJobId] = useState<
    Record<string, FeedbackRating>
  >({});
  const [busyJobIds, setBusyJobIds] = useState<Set<string>>(new Set());
  const [tailoringJobId, setTailoringJobId] = useState<string | null>(null);
  // Bumped when the token changes, so the loaders below re-run against it.
  const [authGeneration, setAuthGeneration] = useState(0);

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
    if (!hasAccessToken()) return;
    void load(email);
  }, [email, load, authGeneration]);

  useEffect(() => {
    if (!hasAccessToken()) return;
    void loadMatches();
  }, [loadMatches, authGeneration]);

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

  const tailoringJob =
    matchedJobs.find((job) => job.job_posting.id === tailoringJobId) ?? null;

  return (
    <div className="container">
      <h1>ApplyFlow</h1>
      <p>AI-assisted job application tracking &amp; tailoring.</p>

      <StatusBanner />
      <AccessTokenField onChange={() => setAuthGeneration((n) => n + 1)} />

      {/* The review flow takes over the page while it is open: it is a
          focused task, and the match list behind it is what the candidate
          just chose from. */}
      {tailoringJob !== null ? (
        <TailoringReview job={tailoringJob} onClose={() => setTailoringJobId(null)} />
      ) : (
        <>
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
            selectedJobId={tailoringJobId}
            onFeedback={handleJobFeedback}
            onTailor={setTailoringJobId}
          />
        </>
      )}
    </div>
  );
}
