import { useState } from 'react';
import { applyFlowApi } from '../api/client';
import type { Profile } from '../types';
import { ProfileSection } from './ProfileSection';

interface Props {
  profile: Profile | null;
  onSaved: (profile: Profile) => void;
}

/**
 * Postal address — five of the fields an application form fills straight from the
 * profile.
 *
 * A full replacement of the section: clearing every box and saving deletes the
 * address, which is how the candidate removes it.
 */
export function AddressSection({ profile, onSaved }: Props) {
  const address = profile?.address;
  const [street, setStreet] = useState(address?.street_address ?? '');
  const [city, setCity] = useState(address?.city ?? '');
  const [region, setRegion] = useState(address?.state_or_region ?? '');
  const [postalCode, setPostalCode] = useState(address?.postal_code ?? '');
  const [country, setCountry] = useState(address?.country ?? '');

  const save = async () => {
    onSaved(
      await applyFlowApi.saveAddress({
        street_address: street || null,
        city: city || null,
        state_or_region: region || null,
        postal_code: postalCode || null,
        country: country || null,
      }),
    );
  };

  return (
    <ProfileSection
      title="Address"
      description="Clear every field and save to remove your address."
      source={address?.source}
      lockedReason={profile ? null : 'Save your name and email first.'}
      onSave={save}
    >
      <label>
        Street address
        <input value={street} onChange={(event) => setStreet(event.target.value)} />
      </label>
      <label>
        City
        <input value={city} onChange={(event) => setCity(event.target.value)} />
      </label>
      <label>
        State or region
        <input value={region} onChange={(event) => setRegion(event.target.value)} />
      </label>
      <label>
        Postal code
        <input
          value={postalCode}
          onChange={(event) => setPostalCode(event.target.value)}
        />
      </label>
      <label>
        Country
        <input value={country} onChange={(event) => setCountry(event.target.value)} />
      </label>
    </ProfileSection>
  );
}
