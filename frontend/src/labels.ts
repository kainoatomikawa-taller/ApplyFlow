/**
 * Turning stored enum values into something readable.
 *
 * The API speaks the domain's own vocabulary — `top_secret_sci`,
 * `decline_to_self_identify`, `permanent_resident` — because those strings are the
 * contract and translating them server-side would put presentation in the wrong
 * layer. This is where they become sentences a person reads.
 *
 * Its own module rather than a helper exported from a component file: React's fast
 * refresh only works on files that export components alone, and a shared function
 * living beside one would quietly cost every consumer their hot reload.
 */
export function label(value: string): string {
  const spaced = value.split('_').join(' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
