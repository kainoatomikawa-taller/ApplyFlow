import type { TrackedApplicationStatus } from '../types';

export const STATUS_LABELS: Record<TrackedApplicationStatus, string> = {
  applied: 'Applied',
  interviewing: 'Interviewing',
  offer: 'Offer',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
};

/**
 * Display order only — the lifecycle roughly as it is lived, so the filter
 * chips and the tallies beside them read the same way whatever a given page
 * happens to contain.
 *
 * Deliberately not a transition table. Which moves are legal comes from each
 * row's `allowed_next_statuses`, and a second ordering here that looked like a
 * state machine would eventually be mistaken for one.
 */
export const STATUS_ORDER: readonly TrackedApplicationStatus[] = [
  'applied',
  'interviewing',
  'offer',
  'rejected',
  'withdrawn',
];

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

/** Whole days between `iso` and now, floored. Never negative. */
export function daysSince(iso: string): number {
  const elapsed = Date.now() - new Date(iso).getTime();
  return Math.max(0, Math.floor(elapsed / 86_400_000));
}

/** "today" / "yesterday" / "12 days ago". */
export function formatAge(iso: string): string {
  const days = daysSince(iso);
  if (days === 0) return 'today';
  if (days === 1) return 'yesterday';
  return `${days} days ago`;
}

/**
 * How long something has been the case — "less than a day", "1 day",
 * "12 days". The caller supplies the sentence around it, because "applied 12
 * days ago" and "interviewing for 12 days" are different statements about the
 * same number.
 */
export function formatDayCount(iso: string): string {
  const days = daysSince(iso);
  if (days === 0) return 'less than a day';
  return `${days} day${days === 1 ? '' : 's'}`;
}

/** A filename stem safe to hand to a download attribute. */
export function fileStem(...parts: string[]): string {
  return parts
    .join('-')
    .replace(/[^a-zA-Z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 80);
}
