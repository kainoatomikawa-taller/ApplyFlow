import { useState } from 'react';
import { getAccessToken, setAccessToken } from '../api/accessToken';

interface Props {
  onChange: () => void;
}

/**
 * Where the API token gets pasted, until a real Supabase sign-in screen
 * replaces it.
 *
 * Every `/api/*` route is behind `get_current_user`, so without a token the
 * app can only show the health banner. A password sign-in form is its own
 * piece of work (Supabase client, session refresh, sign-out); this is the
 * smallest thing that lets the tailoring flow be used and tested end to
 * end, and it writes through the one module the sign-in screen will
 * replace.
 *
 * `type="password"` because a bearer token is a credential — over a
 * shoulder or in a screen share it is a live login.
 */
export function AccessTokenField({ onChange }: Props) {
  const [token, setToken] = useState(getAccessToken);
  const [saved, setSaved] = useState(false);

  const save = () => {
    setAccessToken(token.trim());
    setSaved(true);
    onChange();
  };

  return (
    <div className="card token-field">
      <label htmlFor="access-token">API access token</label>
      <p className="quiet">
        A Supabase access token for the signed-in user. Sent as{' '}
        <code>Authorization: Bearer …</code> on every API call and kept in this browser
        only.
      </p>
      <div className="token-row">
        <input
          id="access-token"
          type="password"
          autoComplete="off"
          placeholder="eyJhbGciOi…"
          value={token}
          onChange={(e) => {
            setToken(e.target.value);
            setSaved(false);
          }}
        />
        <button type="button" onClick={save}>
          {saved ? 'Saved' : 'Use token'}
        </button>
      </div>
    </div>
  );
}
