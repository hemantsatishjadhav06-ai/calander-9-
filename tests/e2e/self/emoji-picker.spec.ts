import { expect, test } from '../support/test';

// The idea form's emoji picker (the New post sheet's Save it as an idea; Phase 3 T18, reached from the
// sheet since T19 took the shell's New menu away): its 95 options exist only while it is open.
test('the idea emoji picker renders on demand, searches, inserts and reopens', async ({ page, harness, as, axe }) => {
  await as('owner');
  await page.goto(`/workspace/${harness.ids.workspace_a}/studio/`);
  await expect(page.getByTestId('home-today')).toBeVisible();
  await expect(page.getByTestId('idea-emoji-option')).toHaveCount(0);
  await axe(page, 'Home before opening the idea picker');
  // The shell has no New menu any more (T19): the sheet's button is the way in.
  await expect(page.getByTestId('sidebar-new-toggle')).toHaveCount(0);
  await page.getByTestId('new-post-open').click();
  await expect(page.getByTestId('new-post-team-idea')).toBeFocused();
  await page.getByTestId('new-post-save-idea').click();
  await expect(page.getByRole('dialog', { name: 'New idea' })).toBeVisible();
  // The sheet places the focus in the title asynchronously. Wait for that observable state,
  // otherwise its title focus can steal the keyboard event used by Playwright's fill. Polled by test id,
  // so a miss names what has the focus instead (WebKit once dropped it just after the sheet placed it).
  await expect
    .poll(() => page.evaluate(() => {
      const active = document.activeElement;
      return active?.getAttribute('data-testid') || active?.tagName || 'nothing';
    }))
    .toBe('idea-title');
  await expect(page.getByTestId('idea-emoji-option')).toHaveCount(0);
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
  await axe(page, 'Idea form with the emoji picker open');
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
  await axe(page, 'Idea form after replacing selected text');
  await page.getByTestId('idea-close').click();
  await expect(page.getByTestId('idea-emoji-option')).toHaveCount(0);
});
