import { useEffect, useState } from 'react';
import { applyFlowApi } from '../api/client';
import type { Profile } from '../types';
import { AddressSection } from './AddressSection';
import { ContactSection } from './ContactSection';
import { EducationSection } from './EducationSection';
import { EeoSection } from './EeoSection';
import { LinksSection } from './LinksSection';
import { JobSearchPreferencesSection } from './JobSearchPreferencesSection';
import { QualificationsSection } from './QualificationsSection';
import { ResumeImportSection } from './ResumeImportSection';
import { SkillsSection } from './SkillsSection';
import { WorkAuthorizationSection } from './WorkAuthorizationSection';
import { WorkHistorySection } from './WorkHistorySection';

/**
 * The profile: everything ApplyFlow needs in order to fill an application.
 *
 * A host, not a form. Each section owns its own fields, its own Save button and its
 * own error state, so a failure in one leaves the rest of the page alone — and so
 * correcting a phone number does not put citizenship and demographic answers back
 * on the wire.
 *
 * Order matters on a first visit. Contact comes first because it is the only section
 * that can create a profile (`full_name` and `email` are the record's only mandatory
 * fields), and the others stay locked until it is saved. That is what makes a résumé
 * a shortcut rather than a prerequisite.
 *
 * A 404 from the read is the normal state for a new account, not an error — it means
 * "no profile yet", which is exactly what the contact section is for.
 */
export function ProfileEditor() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    applyFlowApi
      .getProfile()
      .then(setProfile)
      .catch((caught: unknown) => {
        const message = caught instanceof Error ? caught.message : String(caught);
        // A missing profile is a state, not a failure. Anything else is worth
        // showing, because it means the request itself went wrong.
        if (!message.includes('404')) setError(message);
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="quiet">Loading your profile…</p>;

  return (
    <div className="profile-editor">
      <p className="quiet">
        {profile
          ? 'Everything here is used to fill in applications. Each section saves on its own.'
          : 'You do not have a profile yet. Start with your name and email — you do not need a résumé.'}
      </p>
      {error ? <p className="error">{error}</p> : null}

      <ResumeImportSection profile={profile} onSaved={setProfile} />
      <ContactSection profile={profile} onSaved={setProfile} />
      <AddressSection profile={profile} onSaved={setProfile} />
      <LinksSection profile={profile} onSaved={setProfile} />
      <WorkHistorySection profile={profile} onSaved={setProfile} />
      <EducationSection profile={profile} onSaved={setProfile} />
      <SkillsSection profile={profile} onSaved={setProfile} />
      <QualificationsSection profile={profile} onSaved={setProfile} />
      <JobSearchPreferencesSection profile={profile} onSaved={setProfile} />
      <WorkAuthorizationSection hasProfile={profile !== null} />
      <EeoSection hasProfile={profile !== null} />
    </div>
  );
}
