import { useState } from 'react';
import type { CreateApplicationInput } from '../types';

interface Props {
  onCreate: (input: CreateApplicationInput) => Promise<void>;
}

export function ApplicationForm({ onCreate }: Props) {
  const [form, setForm] = useState<CreateApplicationInput>({
    candidate_email: '',
    company_name: '',
    role_title: '',
    job_description: '',
  });
  const [busy, setBusy] = useState(false);

  const update = (key: keyof CreateApplicationInput, value: string) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await onCreate(form);
      setForm({
        candidate_email: form.candidate_email,
        company_name: '',
        role_title: '',
        job_description: '',
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h2>New Application</h2>
      <div className="field">
        <label>Candidate email</label>
        <input
          type="email"
          required
          value={form.candidate_email}
          onChange={(e) => update('candidate_email', e.target.value)}
        />
      </div>
      <div className="field">
        <label>Company</label>
        <input
          required
          value={form.company_name}
          onChange={(e) => update('company_name', e.target.value)}
        />
      </div>
      <div className="field">
        <label>Role</label>
        <input
          required
          value={form.role_title}
          onChange={(e) => update('role_title', e.target.value)}
        />
      </div>
      <div className="field">
        <label>Job description</label>
        <textarea
          required
          rows={4}
          value={form.job_description}
          onChange={(e) => update('job_description', e.target.value)}
        />
      </div>
      <button type="submit" disabled={busy}>
        {busy ? 'Saving…' : 'Create'}
      </button>
    </form>
  );
}
