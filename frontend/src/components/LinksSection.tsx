import { useState } from 'react';
import { applyFlowApi } from '../api/client';
import type { Profile } from '../types';
import { ProfileSection } from './ProfileSection';

interface Props {
  profile: Profile | null;
  onSaved: (profile: Profile) => void;
}

/**
 * Portfolio, LinkedIn, and GitHub URLs.
 *
 * The URLs are validated server-side by the `ProfileLinks` value object rather than
 * here — "is that a URL" is a rule about the value, and duplicating it in the form
 * would give two answers that could drift apart.
 */
export function LinksSection({ profile, onSaved }: Props) {
  const links = profile?.links;
  const [portfolio, setPortfolio] = useState(links?.portfolio_url ?? '');
  const [linkedin, setLinkedin] = useState(links?.linkedin_url ?? '');
  const [github, setGithub] = useState(links?.github_url ?? '');

  const save = async () => {
    onSaved(
      await applyFlowApi.saveLinks({
        portfolio_url: portfolio || null,
        linkedin_url: linkedin || null,
        github_url: github || null,
      }),
    );
  };

  return (
    <ProfileSection
      title="Links"
      description="Public profiles you want employers to see."
      source={links?.source}
      lockedReason={profile ? null : 'Save your name and email first.'}
      onSave={save}
    >
      <label>
        Portfolio
        <input
          value={portfolio}
          onChange={(event) => setPortfolio(event.target.value)}
          placeholder="https://…"
        />
      </label>
      <label>
        LinkedIn
        <input
          value={linkedin}
          onChange={(event) => setLinkedin(event.target.value)}
          placeholder="https://www.linkedin.com/in/…"
        />
      </label>
      <label>
        GitHub
        <input
          value={github}
          onChange={(event) => setGithub(event.target.value)}
          placeholder="https://github.com/…"
        />
      </label>
    </ProfileSection>
  );
}
