import { useState } from 'react';
import { applyFlowApi } from '../api/client';
import type { Profile } from '../types';
import { ProfileSection } from './ProfileSection';

interface Props {
  profile: Profile | null;
  onSaved: (profile: Profile) => void;
}

/**
 * Name, email, phone, and the two other names a form can ask for.
 *
 * The section that creates the profile. `full_name` and `email` are the only
 * mandatory fields on the whole record, so this is the one part of the editor that
 * works with nothing stored yet — which is what makes a résumé optional rather
 * than the way in. Every other section is locked until this one is saved.
 *
 * The two "other names" carry a meaning worth spelling out on the form, because
 * leaving them blank is an answer rather than a gap:
 *
 * - no middle name means the candidate has none, so forms asking for one are left
 *   blank instead of being handed back on every application;
 * - no preferred name means they go by their legal first name.
 */
export function ContactSection({ profile, onSaved }: Props) {
  const [fullName, setFullName] = useState(profile?.full_name ?? '');
  const [email, setEmail] = useState(profile?.email ?? '');
  const [phone, setPhone] = useState(profile?.phone ?? '');
  const [headline, setHeadline] = useState(profile?.headline ?? '');
  const [location, setLocation] = useState(profile?.location ?? '');
  const [middleName, setMiddleName] = useState(profile?.middle_name ?? '');
  const [preferredName, setPreferredName] = useState(profile?.preferred_name ?? '');

  const save = async () => {
    const saved = await applyFlowApi.saveContactDetails({
      full_name: fullName,
      email,
      phone: phone || null,
      headline: headline || null,
      location: location || null,
      middle_name: middleName || null,
      preferred_name: preferredName || null,
    });
    onSaved(saved);
  };

  return (
    <ProfileSection
      title="Name and contact"
      description={
        profile
          ? 'How employers reach you, and the names that go on an application.'
          : 'Start here. Your name and email are all that is needed to create your profile — everything else unlocks once this is saved.'
      }
      source={profile?.contact_source}
      onSave={save}
      saveLabel={profile ? 'Save' : 'Create profile'}
    >
      <label>
        Full legal name
        <input
          value={fullName}
          onChange={(event) => setFullName(event.target.value)}
          placeholder="Dana Reyes"
        />
      </label>
      <label>
        Email
        <input
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="dana@example.com"
        />
      </label>
      <label>
        Phone
        <input value={phone} onChange={(event) => setPhone(event.target.value)} />
      </label>
      <label>
        Middle name
        <input
          value={middleName}
          onChange={(event) => setMiddleName(event.target.value)}
        />
        <span className="quiet">
          Leave blank if you have none — forms asking for one will be left empty
          rather than asking you every time.
        </span>
      </label>
      <label>
        Preferred name
        <input
          value={preferredName}
          onChange={(event) => setPreferredName(event.target.value)}
        />
        <span className="quiet">
          Leave blank to use your first name.
        </span>
      </label>
      <label>
        Headline
        <input
          value={headline}
          onChange={(event) => setHeadline(event.target.value)}
          placeholder="Backend engineer"
        />
      </label>
      <label>
        Location
        <input
          value={location}
          onChange={(event) => setLocation(event.target.value)}
          placeholder="Austin, TX"
        />
      </label>
    </ProfileSection>
  );
}
