import type { JobApplication } from '../types';

interface Props {
  applications: JobApplication[];
  onSubmit: (id: string) => void;
}

export function ApplicationList({ applications, onSubmit }: Props) {
  if (applications.length === 0) {
    return <p>No applications yet.</p>;
  }

  return (
    <div>
      {applications.map((app) => (
        <div className="card" key={app.id}>
          <h3>
            {app.role_title} @ {app.company_name}
          </h3>
          <p>
            <span className="status">{app.status}</span>
            {app.match_score !== null && <> · Match score: {app.match_score}/100</>}
          </p>
          {app.status === 'draft' && (
            <button onClick={() => onSubmit(app.id)}>Submit</button>
          )}
        </div>
      ))}
    </div>
  );
}
