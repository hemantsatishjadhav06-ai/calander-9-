import type { Page } from '@playwright/test';

import { expect, test } from '../support/test';

// The New post sheet places the focus in a mode's first field once its panel shows (static/js/
// new-post-sheet.js, focusField). Alpine's x-show shows a panel on the next animation frame, and WebKit
// runs focusField's timer before that frame, so on CI's iPhone 13 a switch of mode put the focus on
// Close. Chromium mostly draws the frame first, so here the page holds every frame back until after the
// timers already due, as WebKit orders them, and the sheet must still focus the right field.

/** The focused element's test id, else its tag, so a miss names where the focus went. */
function focused(page: Page): Promise<string> {
  return page.evaluate(() => {
    const active = document.activeElement;
    return active?.getAttribute('data-testid') || active?.tagName || 'nothing';
  });
}

test('with frames drawn after timers, each mode of the sheet puts the focus in its own first field', async ({ page, harness, as }) => {
  await page.addInitScript(() => {
    const frame = window.requestAnimationFrame.bind(window);
    window.requestAnimationFrame = (callback) => window.setTimeout(() => frame(callback), 20) as unknown as number;
  });
  await as('owner');
  await page.goto(`/workspace/${harness.ids.workspace_a}/studio/`);
  await expect(page.getByTestId('home-today')).toBeVisible();

  await page.getByTestId('new-post-open').click();
  await expect.poll(() => focused(page)).toBe('new-post-team-idea');
  await page.getByTestId('new-post-save-idea').click();
  await expect.poll(() => focused(page)).toBe('idea-title');
  await page.getByTestId('idea-close').click();
  await page.getByTestId('new-post-mode-self').click();
  await expect.poll(() => focused(page)).toBe('new-post-self-open');
  await page.getByTestId('new-post-mode-team').click();
  await expect.poll(() => focused(page)).toBe('new-post-team-idea');
});
