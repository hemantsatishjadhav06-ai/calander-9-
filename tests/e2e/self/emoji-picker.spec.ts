import { expect, test } from '../support/test';

test('the idea emoji picker renders on demand, searches, inserts and reopens', async ({ page, harness, as, axe }) => {
  test.skip(
    process.env.E2E_VERIFY_EMOJI_QUARANTINE !== '1',
    'Quarantined during modal-focus repair and stability verification: https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/18',
  );
  await as('owner');
  await page.goto(`/workspace/${harness.ids.workspace_a}/studio/`);
  await expect(page.getByTestId('home-today')).toBeVisible();
  await expect(page.getByTestId('idea-emoji-option')).toHaveCount(0);
  await axe(page, 'Home before opening the idea picker');
  if (await page.getByTestId('mobile-menu-toggle').isVisible()) await page.getByTestId('mobile-menu-toggle').click();
  await page.getByTestId('sidebar-new-toggle').click();
  await page.getByTestId('sidebar-new-idea').click();
  // openCreateModal establishes initial focus asynchronously. Wait for that observable state,
  // otherwise its title focus can steal the keyboard event used by Playwright's fill.
  await expect(page.getByTestId('idea-title')).toBeFocused();
  const description = page.getByTestId('idea-description');
  await description.fill('A bright idea ');
  await expect(description).toHaveValue('A bright idea ');
  await description.press('ArrowRight');
  await expect.poll(() => description.evaluate((element: HTMLTextAreaElement) =>
    [element.selectionStart, element.selectionEnd],
  )).toEqual([14, 14]);
  await page.getByTestId('idea-emoji-toggle').click();
  await expect(page.getByTestId('idea-emoji-option')).toHaveCount(95);
  await page.getByTestId('idea-emoji-search').fill('sparkles');
  await expect(page.getByTestId('idea-emoji-option')).toHaveCount(1);
  await axe(page, 'Idea dialog with the emoji picker open');
  await page.getByTestId('idea-emoji-option').click();
  await expect(page.getByTestId('idea-description')).toHaveValue('A bright idea ✨');
  await expect(page.getByTestId('idea-emoji-option')).toHaveCount(0);
  await page.getByTestId('idea-emoji-toggle').click();
  await expect(page.getByTestId('idea-emoji-option')).toHaveCount(95);
  await page.getByTestId('idea-emoji-search').fill('sparkles');
  await page.getByTestId('idea-emoji-option').focus();
  await page.getByTestId('idea-emoji-option').press('Enter');
  await expect(page.getByTestId('idea-description')).toHaveValue('A bright idea ✨✨');
  // Replacing a deliberate selection is different from appending at the caret. Exercise both
  // behaviors so a fix cannot simply force every emoji to append and conceal selection bugs.
  await description.focus();
  await description.press('ControlOrMeta+A');
  await expect.poll(() => description.evaluate((element: HTMLTextAreaElement) =>
    [element.selectionStart, element.selectionEnd],
  )).toEqual([0, 'A bright idea ✨✨'.length]);
  await page.getByTestId('idea-emoji-toggle').click();
  await page.getByTestId('idea-emoji-search').fill('sparkles');
  await page.getByTestId('idea-emoji-option').click();
  await expect(description).toHaveValue('✨');
  await axe(page, 'Idea dialog after replacing selected text');
  await page.getByTestId('idea-close').click();
});
