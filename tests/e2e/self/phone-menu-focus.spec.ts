import { expect, test } from '../support/test';

// On a phone the sidebar is a modal drawer with its own focus trap. Opening New idea from it must
// close the drawer, or the drawer's trap pulls focus back from the dialog's title. Closing the
// drawer itself still hands focus back to the menu button.

test('New idea from the menu closes the menu and puts the cursor in the title', async ({ page, harness, as, axe }) => {
  await as('owner');
  await page.goto(`/workspace/${harness.ids.workspace_a}/studio/`);
  await expect(page.getByTestId('home-today')).toBeVisible();
  const toggle = page.getByTestId('mobile-menu-toggle');
  const phone = await toggle.isVisible();
  if (phone) await toggle.click();
  await page.getByTestId('sidebar-new-toggle').click();
  await page.getByTestId('sidebar-new-idea').click();

  if (phone) await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByTestId('idea-title')).toBeFocused();
  // The dialog's own trap starts a moment later; the cursor must still be in the title after it.
  await expect(page.getByRole('dialog', { name: 'New idea' })).toBeVisible();
  await page.keyboard.type('Launch week');
  await expect(page.getByTestId('idea-title')).toHaveValue('Launch week');
  await axe(page, 'New idea opened from the menu');
});

test('closing the phone menu with Escape returns focus to the menu button', async ({ page, harness, as }) => {
  await as('owner');
  await page.goto(`/workspace/${harness.ids.workspace_a}/studio/`);
  await expect(page.getByTestId('home-today')).toBeVisible();
  const toggle = page.getByTestId('mobile-menu-toggle');
  test.skip(!(await toggle.isVisible()), 'The menu is a drawer only on a phone.');
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByRole('dialog', { name: 'Menu' })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.getElementById('app-sidebar')?.contains(document.activeElement))).toBe(true);
  await page.keyboard.press('Escape');
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(toggle).toBeFocused();
});
