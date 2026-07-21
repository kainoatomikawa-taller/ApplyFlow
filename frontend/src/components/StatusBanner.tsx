import { useEffect, useState } from 'react';
import { applyFlowApi } from '../api/client';
import type { HealthStatus } from '../types';

/**
 * The web shell's "hello world" screen: proves the frontend can reach the
 * API and shows which environment (via the backend's config layer) it's
 * pointed at, driven by VITE_API_URL (see frontend/.env.example).
 */
export function StatusBanner() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    applyFlowApi
      .getHealth()
      .then(setHealth)
      .catch((err) =>
        setError(err instanceof Error ? err.message : 'Unknown error'),
      );
  }, []);

  if (error) {
    return <p className="error">Hello world — could not reach the API: {error}</p>;
  }

  if (!health) {
    return <p className="card">Hello world — checking API status…</p>;
  }

  return (
    <p className="card">
      Hello world from {health.service} — API is {health.status}{' '}
      <span className="status">{health.environment}</span>
    </p>
  );
}
