import { useCallback, useEffect, useState } from 'react';
import { applyFlowApi } from './api/client';
import { ApplicationForm } from './components/ApplicationForm';
import { ApplicationList } from './components/ApplicationList';
import type { CreateApplicationInput, JobApplication } from './types';

const DEMO_EMAIL = 'demo@example.com';

export function App() {
  const [applications, setApplications] = useState<JobApplication[]>([]);
  const [email, setEmail] = useState(DEMO_EMAIL);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (candidateEmail: string) => {
    try {
      setError(null);
      const data = await applyFlowApi.listApplications(candidateEmail);
      setApplications(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  }, []);

  useEffect(() => {
    void load(email);
  }, [email, load]);

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

      <div className="field">
        <label>Viewing applications for</label>
        <input value={email} onChange={(e) => setEmail(e.target.value)} />
      </div>

      {error && <p className="error">{error}</p>}

      <ApplicationForm onCreate={handleCreate} />
      <ApplicationList applications={applications} onSubmit={handleSubmit} />
    </div>
  );
}
