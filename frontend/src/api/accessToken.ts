/**
 * Where the API bearer token lives on the client.
 *
 * Every `/api/*` route is behind `get_current_user`, which wants a Supabase
 * access token as `Authorization: Bearer <token>`. Until the app grows a
 * real Supabase sign-in screen, the token is pasted in once and kept in
 * `localStorage` so a reload doesn't log you out — same storage Supabase's
 * own JS client uses for its session, and the same trust boundary: this is
 * a single-user app whose token is already scoped to that one user.
 *
 * Kept behind these three functions rather than read inline so the sign-in
 * screen, when it arrives, has exactly one place to write to.
 */

const STORAGE_KEY = 'applyflow.accessToken';

export function getAccessToken(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? '';
  } catch {
    // Private-browsing modes can throw on storage access. An unauthenticated
    // client is a better outcome than a blank screen.
    return '';
  }
}

export function setAccessToken(token: string): void {
  try {
    if (token) {
      window.localStorage.setItem(STORAGE_KEY, token);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // Ignore — the token stays in component state for this session.
  }
}

export function hasAccessToken(): boolean {
  return getAccessToken().length > 0;
}
