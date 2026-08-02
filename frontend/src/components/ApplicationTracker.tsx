import { useCallback, useEffect, useMemo, useState } from 'react';
import { applyFlowApi } from '../api/client';
import { TrackedApplicationRow } from './TrackedApplicationRow';
import { TrackerFilters } from './TrackerFilters';
import { STATUS_ORDER } from './trackerPresentation';
import type { TrackerFilter, TrackerSort } from './TrackerFilters';
import type { TrackedApplication, TrackedApplicationStatus } from '../types';

interface Props {
  /** Bumped by the parent when the access token changes, so the feed reloads. */
  authGeneration?: number;
}

/** One page of the candidate's history. The backend caps this at 500. */
const PAGE_LIMIT = 100;

/**
 * The tracker: every application the candidate has sent, what went out with
 * it, where it stands, and how it got there.
 *
 * **One unfiltered read, narrowed here.** The list route can filter by status
 * and by "open only", and this screen deliberately does not use either. The
 * filter bar shows a count against every status, and those counts only exist
 * if the client holds the whole page — asking the backend per chip would mean
 * either a request per click or counts that describe a set the candidate
 * cannot see. What is narrowed here is narrowed on values the backend already
 * decided and sent per row (`status`, `is_open`), so no rule is being
 * reimplemented; the domain still owns which statuses exist and which of them
 * count as live.
 *
 * **The page bound is stated, not hidden.** Only the most recent
 * {@link PAGE_LIMIT} applications are read, and when the page comes back full
 * the screen says so rather than letting the counts read as a complete
 * history.
 *
 * **A change re-renders from what was stored.** The PATCH returns the whole
 * updated record — status, `is_open`, `current_status_since`, the grown
 * history, and the next set of legal moves — and that is what replaces the
 * row. Patching locally would show the candidate's intent rather than the
 * stored outcome, which is the same mistake as a UI that computes its own
 * gates.
 */
export function ApplicationTracker({ authGeneration = 0 }: Props) {
  const [applications, setApplications] = useState<TrackedApplication[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());

  const [filter, setFilter] = useState<TrackerFilter>('all');
  const [sort, setSort] = useState<TrackerSort>('applied');
  const [query, setQuery] = useState('');

  const load = useCallback(async () => {
    try {
      setError(null);
      const feed = await applyFlowApi.listTrackedApplications({ limit: PAGE_LIMIT });
      setApplications(feed.applications);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, authGeneration]);

  const changeStatus = async (
    application: TrackedApplication,
    status: TrackedApplicationStatus,
    note: string,
  ): Promise<boolean> => {
    setBusyIds((prev) => new Set(prev).add(application.id));
    setError(null);
    try {
      const updated = await applyFlowApi.updateApplicationStatus(
        application.id,
        status,
        note,
      );
      // Replaced wholesale with what came back — see the component docstring.
      setApplications((prev) =>
        prev.map((row) => (row.id === updated.id ? updated : row)),
      );
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      return false;
    } finally {
      setBusyIds((prev) => {
        const next = new Set(prev);
        next.delete(application.id);
        return next;
      });
    }
  };

  /**
   * Counted from the rows rather than read from the response's `open_count`.
   * Not a disagreement with the backend: that field is the number of open
   * applications *in the response*, and this read is unfiltered, so the two
   * are the same set. Counting `is_open` — the flag the domain decided and
   * sent — keeps the header true after a status change closes an application,
   * where a number carried over from the last read would be stale.
   */
  const openCount = useMemo(
    () => applications.filter((application) => application.is_open).length,
    [applications],
  );

  const countsByStatus = useMemo(() => {
    const counts = Object.fromEntries(
      STATUS_ORDER.map((status) => [status, 0]),
    ) as Record<TrackedApplicationStatus, number>;
    for (const application of applications) counts[application.status] += 1;
    return counts;
  }, [applications]);

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matchesQuery = (application: TrackedApplication) =>
      needle === '' ||
      [application.company_name, application.role_title, application.job_location ?? '']
        .join(' ')
        .toLowerCase()
        .includes(needle);
    const matchesFilter = (application: TrackedApplication) => {
      if (filter === 'all') return true;
      if (filter === 'open') return application.is_open;
      return application.status === filter;
    };

    // Sorted on parsed instants rather than on the strings, which would order
    // correctly only as long as every timestamp came back in the same offset.
    const field = sort === 'applied' ? 'applied_at' : 'current_status_since';
    return applications
      .filter((application) => matchesFilter(application) && matchesQuery(application))
      .sort((left, right) => Date.parse(right[field]) - Date.parse(left[field]));
  }, [applications, filter, query, sort]);

  if (loaded && applications.length === 0) {
    return (
      <section className="card">
        <h2>Applications sent</h2>
        {/* A failed read is not evidence of an empty history, so it never
            gets to claim one. */}
        {error !== null ? (
          <p className="error">{error}</p>
        ) : (
          <p className="quiet">
            Nothing sent yet. An application appears here the moment you submit
            one — you never add it by hand.
          </p>
        )}
      </section>
    );
  }

  return (
    <section className="card">
      <div className="tracker-header">
        <h2>Applications sent</h2>
        <span className="quiet">
          {openCount} still live of {applications.length}
        </span>
      </div>

      {error !== null && <p className="error">{error}</p>}

      <TrackerFilters
        filter={filter}
        onFilterChange={setFilter}
        sort={sort}
        onSortChange={setSort}
        query={query}
        onQueryChange={setQuery}
        total={applications.length}
        openCount={openCount}
        countsByStatus={countsByStatus}
        shownCount={shown.length}
      />

      {applications.length === PAGE_LIMIT && (
        <p className="quiet">
          Showing your {PAGE_LIMIT} most recent applications — older ones are
          not counted above.
        </p>
      )}

      {shown.length === 0 ? (
        <p className="quiet">
          No application matches this filter. Every one you have sent is still
          on file.
        </p>
      ) : (
        <ul className="tracked-applications">
          {shown.map((application) => (
            <TrackedApplicationRow
              key={application.id}
              application={application}
              busy={busyIds.has(application.id)}
              onStatusChange={(status, note) =>
                changeStatus(application, status, note)
              }
            />
          ))}
        </ul>
      )}
    </section>
  );
}
