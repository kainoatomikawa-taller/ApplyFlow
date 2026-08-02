import { STATUS_LABELS, STATUS_ORDER } from './trackerPresentation';
import type { TrackedApplicationStatus } from '../types';

/** What the list is narrowed to. `open` is "still live", from each row's own
 *  `is_open`; the rest are single statuses. */
export type TrackerFilter = 'all' | 'open' | TrackedApplicationStatus;

/** Most recently applied, or most recently moved. */
export type TrackerSort = 'applied' | 'updated';

interface Props {
  filter: TrackerFilter;
  onFilterChange: (filter: TrackerFilter) => void;
  sort: TrackerSort;
  onSortChange: (sort: TrackerSort) => void;
  query: string;
  onQueryChange: (query: string) => void;
  total: number;
  openCount: number;
  countsByStatus: Record<TrackedApplicationStatus, number>;
  /** How many rows survive the current filter and search, for the summary. */
  shownCount: number;
}

/**
 * The tracker's filter bar: how a candidate with sixty applications finds the
 * three they care about right now.
 *
 * **Every chip carries its count, and a status with none is not offered.** A
 * chip that leads to an empty list is a dead end the candidate has to click to
 * discover; the counts turn the same row of controls into the summary of where
 * everything stands, which is most of what "scannable" means here.
 *
 * **"Open" is the backend's answer, not a rule restated.** It selects on the
 * `is_open` flag each row carries, which the use case derives from
 * `ApplicationStatus.is_terminal`. Listing the statuses this UI thinks are
 * live would be a second definition of "open" free to drift from the domain's.
 */
export function TrackerFilters({
  filter,
  onFilterChange,
  sort,
  onSortChange,
  query,
  onQueryChange,
  total,
  openCount,
  countsByStatus,
  shownCount,
}: Props) {
  const chips: { value: TrackerFilter; label: string; count: number }[] = [
    { value: 'all', label: 'All', count: total },
    { value: 'open', label: 'Still live', count: openCount },
    ...STATUS_ORDER.filter((status) => countsByStatus[status] > 0).map((status) => ({
      value: status,
      label: STATUS_LABELS[status],
      count: countsByStatus[status],
    })),
  ];

  return (
    <div className="tracker-filters">
      <div className="tracker-chips" role="group" aria-label="Filter applications">
        {chips.map((chip) => (
          <button
            key={chip.value}
            type="button"
            className={`tracker-chip${filter === chip.value ? ' active' : ''}`}
            aria-pressed={filter === chip.value}
            onClick={() => onFilterChange(chip.value)}
          >
            {chip.label} <span className="tracker-chip-count">{chip.count}</span>
          </button>
        ))}
      </div>

      <div className="tracker-controls">
        <input
          type="search"
          className="tracker-search"
          value={query}
          placeholder="Filter by company, role, or location"
          aria-label="Filter by company, role, or location"
          onChange={(event) => onQueryChange(event.target.value)}
        />
        <label className="tracker-sort">
          <span className="quiet">Sort</span>{' '}
          <select
            value={sort}
            onChange={(event) => onSortChange(event.target.value as TrackerSort)}
          >
            <option value="applied">Recently applied</option>
            <option value="updated">Recently updated</option>
          </select>
        </label>
      </div>

      {/* Said out loud, because a filtered list of 3 out of 47 otherwise looks
          like a candidate who has barely applied to anything. */}
      <p className="quiet tracker-summary">
        Showing {shownCount} of {total}
        {shownCount !== total && (
          <>
            {' '}
            <button
              type="button"
              className="link-button"
              onClick={() => {
                onFilterChange('all');
                onQueryChange('');
              }}
            >
              Clear filters
            </button>
          </>
        )}
      </p>
    </div>
  );
}
