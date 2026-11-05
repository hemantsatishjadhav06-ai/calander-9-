import { type Page } from '@playwright/test';

import { expect, test } from '../support/test';

// On a phone the sidebar is a modal drawer with its own focus trap. Opening the idea form from it must
// close the drawer, or the drawer's trap pulls focus back from the title (#18). The shell's New menu
// that did this went with Phase 3 T19; the New post sheet keeps the promise for every way it is opened
// while the drawer is open: new-post:open (what the button and a Calendar cell send) and
// #new-post.

async function openTheDrawer(page: Page) {
  const toggle = page.getByTestId('mobile-menu-toggle');
  const phone = await toggle.isVisible();
  if (phone) {
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  }
  return { toggle, phone };
}

test('the idea form opened over the menu closes the menu and puts the cursor in the title', async ({ page, harness, as, axe }) => {
  await as('owner');
  await page.goto(`/workspace/${harness.ids.workspace_a}/studio/`);
  await expect(page.getByTestId('home-today')).toBeVisible();
  const { toggle, phone } = await openTheDrawer(page);
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('new-post:open', { detail: { mode: 'idea' } })));

  if (phone) await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByTestId('idea-title')).toBeFocused();
  // The sheet's own trap starts a moment later; the cursor must still be in the title after it.
  await expect(page.getByRole('dialog', { name: 'New idea' })).toBeVisible();
  await page.keyboard.type('Launch week');
  await expect(page.getByTestId('idea-title')).toHaveValue('Launch week');
  await axe(page, 'New idea opened over the menu');
});

test('#new-post over the menu closes the menu and puts the cursor in the idea', async ({ page, harness, as }) => {
  await as('owner');
  await page.goto(`/workspace/${harness.ids.workspace_a}/studio/`);
  await expect(page.getByTestId('home-today')).toBeVisible();
  const { toggle, phone } = await openTheDrawer(page);
  await page.evaluate(() => { window.location.hash = '#new-post'; });

  if (phone) await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByRole('dialog', { name: 'New post' })).toBeVisible();
  await expect(page.getByTestId('new-post-team-idea')).toBeFocused();
  await page.keyboard.type('Launch week');
  await expect(page.getByTestId('new-post-team-idea')).toHaveValue('Launch week');
});
