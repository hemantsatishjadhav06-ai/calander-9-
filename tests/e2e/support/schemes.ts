// Light and dark (spec D2 and D10): a screen's axe and visual cases run in both colour schemes; its
// behavioural flows run in light only (the browser's default here), so the E2E job's time does not
// double.
//
//   forSchemes((scheme) => {
//     test(`Home passes axe (${scheme})`, async ({ page, axe }) => { … });
//   });
//
// Each scheme is its own `test.describe` with `test.use({ colorScheme })`, so the device reports that
// scheme from the first request on (the head script reads it before the first paint). A page turns dark
// only when its screen has declared it (apps/common/screens.py DARK_READY); until then the dark case
// photographs the light page, which is what a person with a dark device sees there.
import { test } from './test';

export const SCHEMES = ['light', 'dark'] as const;
export type Scheme = (typeof SCHEMES)[number];

/** Declare `body`'s tests once per colour scheme, each in a describe named for its scheme. */
export function forSchemes(body: (scheme: Scheme) => void): void {
  for (const scheme of SCHEMES) {
    test.describe(`${scheme} scheme`, () => {
      test.use({ colorScheme: scheme });
      body(scheme);
    });
  }
}
