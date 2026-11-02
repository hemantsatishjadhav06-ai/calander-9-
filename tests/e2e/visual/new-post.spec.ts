import type { Locator, Page } from '@playwright/test';

import type { Harness } from '../support/harness';
import { isPhone } from '../support/nav';
import { type Scheme, forSchemes } from '../support/schemes';
import { settled } from '../support/settled';
import { expect, test } from '../support/test';
import { snap, thawClock, visualSpecsOnly, visualWorld } from '../support/visual';

// Screen 1's baselines (spec D9, plan T24): the New post sheet on the visual workspace's Home, in light
// and in dark (Home is declared dark-ready, T22), on the three projects, with the clock frozen and
// reduced motion (visualWorld). Four states, each its own test, so a missing or changed image names
// its state and one state's failure never hides another's:
//
//   - `home-trigger`: Home at rest, the sheet closed, photographed as the New post button's own region
//     (new-post-open): floating above the phone bar on a phone, in the page header from 1024 px.
//   - `sheet-team`: the sheet as the button opens it, in Ask the team, with the focus in Your idea.
//   - `sheet-self`: Write it myself, with the focus on Open the editor.
//   - `sheet-idea`: Save it as an idea's form ("New idea"), with the focus in the title.
//
// Each is screen 1's own region (spec D9), so the shell is not in it and what the sheet covers is not
// masked over it (support/visual.ts masksFor): the sheet states are the sheet (new-post-sheet: the
// bottom sheet on a phone, the drawer from 1024 px), never the Home behind the scrim. Home's own
// content is screen 2's, and shell.spec.ts photographs the whole page. Home at rest is the button and
// not Home's region (main-content) because Today's date prints the real date (`{% now %}`): its mask is
// as wide as the date's words, and on iPhone 13 a "Wed 30 Sep" against a "Sun 3 Jan" moves that region
// past the 0.1 % a baseline allows. Neither the button's photograph nor the sheet's moves with it.
// Each state waits for the field its mode focuses (the sheet places it once the mode's panel shows)
// and for the sheet to settle; snap waits for the rest.
//
// Compared only where E2E_VISUAL=1 (CI's visual job and the baseline workflow); skipped elsewhere. The
// baseline workflow writes the files, `<state>-<scheme>-<project>.png`, in a `visual:` commit.

visualSpecsOnly();

test.afterEach(async ({ harness }) => {
  await thawClock(harness);
});

/** One tap on a touch device, a click elsewhere. */
async function press(page: Page, target: Locator): Promise<void> {
  if (isPhone(page)) await target.tap();
  else await target.click();
}

/** The visual workspace's Home as its owner, in `scheme`, with the New post button ready (closed). */
async function home(page: Page, harness: Harness, as: (who: { email: string }) => Promise<unknown>, scheme: Scheme) {
  const world = await visualWorld(page, harness);
  await as({ email: world.users.owner.email });
  expect((await page.goto(`/workspace/${world.workspace_id}/studio/`))?.status()).toBe(200);
  // Home is declared dark-ready, so the dark case photographs the dark page, not the light one.
  await expect(page.locator('html')).toHaveAttribute('data-theme', scheme);
  await expect(page.getByTestId('home-today')).toBeVisible();
  const button = page.getByTestId('new-post-open');
  await expect(button).toBeVisible();
  await expect(button).toHaveAttribute('aria-expanded', 'false');
  return button;
}

/** Open the sheet with the New post button: Ask the team, the focus in Your idea, the sheet still. */
async function openSheet(page: Page, button: Locator): Promise<Locator> {
  await press(page, button);
  const sheet = page.getByTestId('new-post-sheet');
  await expect(page.getByRole('dialog', { name: 'New post' })).toBeVisible();
  await expect(button).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByTestId('new-post-mode-team')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('new-post-team-idea')).toBeFocused();
  await settled(sheet, 'the New post sheet');
  return sheet;
}

forSchemes((scheme) => {
  test(`Home at rest with the New post button (${scheme})`, async ({ page, harness, as }) => {
    const button = await home(page, harness, as, scheme);
    await expect(page.getByTestId('new-post-sheet')).toBeHidden();
    await snap(button, 'home-trigger');
  });

  test(`the sheet in Ask the team (${scheme})`, async ({ page, harness, as }) => {
    const sheet = await openSheet(page, await home(page, harness, as, scheme));
    await expect(page.getByTestId('new-post-team-send')).toBeVisible();
    await snap(sheet, 'sheet-team');
  });

  test(`the sheet in Write it myself (${scheme})`, async ({ page, harness, as }) => {
    const sheet = await openSheet(page, await home(page, harness, as, scheme));
    await press(page, page.getByTestId('new-post-mode-self'));
    await expect(page.getByTestId('new-post-mode-self')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('new-post-self-open')).toBeFocused();
    await settled(sheet, 'Write it myself');
    await snap(sheet, 'sheet-self');
  });

  test(`the sheet's idea form, Save it as an idea (${scheme})`, async ({ page, harness, as }) => {
    const sheet = await openSheet(page, await home(page, harness, as, scheme));
    await press(page, page.getByTestId('new-post-save-idea'));
    await expect(page.getByRole('dialog', { name: 'New idea' })).toBeVisible();
    await expect(page.getByTestId('idea-title')).toBeFocused();
    await expect(page.getByTestId('idea-close')).toBeVisible();
    await settled(sheet, 'the idea form');
    await snap(sheet, 'sheet-idea');
  });
});
