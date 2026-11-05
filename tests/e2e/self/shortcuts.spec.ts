import type { Page } from '@playwright/test';

import { forSchemes } from '../support/schemes';
import { settled } from '../support/settled';
import { expect, test } from '../support/test';

// Keyboard shortcuts (spec D16, Phase 3 T20; static/js/shortcuts.js and the list in base.html). From
// 1024 px: `n` opens the New post sheet on Home and Calendar and goes to Home's #new-post elsewhere,
// `/` opens Go to, `?` opens the list, whose switch turns the single keys off on this device. Each is
// ignored while typing in a field and while a dialog is open; Ctrl-K inside the sheet does nothing.
// The guards case by case (modifiers, widths, blocked storage) are tests/js/shortcuts.test.cjs.
//
// Desktop Chrome only: phones have no keys, and the shortcuts are off below 1024 px.

const DESKTOP_ONLY = 'desktop-chrome only: phones have no keys, and the shortcuts start at 1024 px (D16)';

function home(workspace: string): string {
  return `/workspace/${workspace}/studio/`;
}

/** Home for the owner of the shared workspace, ready for keys. */
async function openHome(page: Page, workspace: string): Promise<void> {
  await page.goto(home(workspace));
  await expect(page.getByTestId('home-today')).toBeVisible();
  await expect(page.getByTestId('new-post-open')).toHaveAttribute('aria-expanded', 'false');
}

/** Whether the New post sheet is open: the sheet sets has-sheet on body as it opens. */
function sheetIsOpen(page: Page): Promise<boolean> {
  return page.evaluate(() => document.body.classList.contains('has-sheet'));
}

test.describe('Keyboard shortcuts (desktop-chrome only: phones have no keys)', () => {
  test.skip(({ isMobile }) => isMobile, DESKTOP_ONLY);

  test('n on Home opens the sheet with the focus in its field, and Escape gives the focus back', async ({ page, harness, as, axe }) => {
    await as('owner');
    await openHome(page, harness.ids.workspace_a);

    await page.keyboard.press('n');
    const sheet = page.getByRole('dialog', { name: 'New post' });
    await expect(sheet).toBeVisible();
    await expect(page.getByTestId('new-post-team-idea')).toBeFocused();
    await expect(page.getByTestId('new-post-team-idea')).toHaveValue('');
    await expect(page.getByTestId('new-post-open')).toHaveAttribute('aria-expanded', 'true');
    await settled(page.getByTestId('new-post-sheet'), 'the New post sheet');
    await axe(page, 'New post opened with n', { include: '[data-testid="new-post-sheet"]' });

    await page.keyboard.press('Escape');
    await expect(sheet).toBeHidden();
    await expect(page.getByTestId('new-post-open')).toBeFocused();
  });

  test("n on Approvals goes to Home's #new-post with the sheet open", async ({ page, harness, as }) => {
    await as('owner');
    await page.goto(`/workspace/${harness.ids.workspace_a}/approvals/`);
    await expect(page.getByTestId('new-post-open')).toHaveCount(0);

    await page.keyboard.press('n');
    await expect(page).toHaveURL(new RegExp(`${home(harness.ids.workspace_a)}#new-post$`));
    await expect(page.getByRole('dialog', { name: 'New post' })).toBeVisible();
    await expect(page.getByTestId('new-post-team-idea')).toBeFocused();
  });

  test('n typed in the thread composer is just a letter', async ({ page, harness, as }) => {
    await as('owner');
    await openHome(page, harness.ids.workspace_a);
    const composer = page.getByTestId('home-thread').getByTestId('thread-composer-body');

    await composer.click();
    await page.keyboard.type('n/?');
    await expect(composer).toHaveValue('n/?');
    expect(await sheetIsOpen(page)).toBe(false);
    await expect(page.getByTestId('palette-dialog')).toBeHidden();
    await expect(page.getByTestId('shortcuts-dialog')).toBeHidden();
  });

  test('? lists the keys, and Escape closes the list', async ({ page, harness, as }) => {
    await as('owner');
    await openHome(page, harness.ids.workspace_a);

    await page.keyboard.press('Shift+Slash');
    const list = page.getByTestId('shortcuts-dialog');
    await expect(list).toBeVisible();
    await expect(page.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeVisible();
    await expect(list.getByTestId('shortcuts-new-post')).toContainText('New post');
    await expect(list.getByTestId('shortcuts-new-post').locator('kbd')).toHaveText(['n']);
    await expect(list.getByTestId('shortcuts-go-to')).toContainText('Go to a page');
    await expect(list.getByTestId('shortcuts-go-to').locator('kbd')).toHaveText(['/', 'Ctrl', 'K']);
    await expect(list.getByTestId('shortcuts-list')).toContainText('Keyboard shortcuts');
    await expect(list.getByTestId('shortcuts-list').locator('kbd')).toHaveText(['?', 'Ctrl', '/']);
    const toggle = page.getByRole('switch', { name: 'Single-key shortcuts' });
    await expect(toggle).toHaveAttribute('data-testid', 'shortcuts-toggle');
    await expect(toggle).toBeChecked();
    // The switch's own target is 44 by 44 px, as large as the other switches', not just its 36 by 20 track.
    const target = await toggle.boundingBox();
    expect(target?.width ?? 0).toBeGreaterThanOrEqual(44);
    expect(target?.height ?? 0).toBeGreaterThanOrEqual(44);
    await expect(list.locator(':focus')).toHaveCount(1);
    // Its trap holds Tab inside, both ways round (the list places the focus itself; the trap only keeps it).
    for (const key of ['Tab', 'Tab', 'Tab', 'Shift+Tab', 'Shift+Tab', 'Shift+Tab']) {
      await page.keyboard.press(key);
      await expect(list.locator(':focus'), `after ${key}`).toHaveCount(1);
    }

    await page.keyboard.press('Escape');
    await expect(list).toBeHidden();
    expect(await sheetIsOpen(page)).toBe(false);
  });

  test('switched off, n does nothing, still after a reload; Ctrl-/ turns them back on', async ({ page, harness, as }) => {
    await as('owner');
    await openHome(page, harness.ids.workspace_a);
    await page.keyboard.press('Shift+Slash');
    const toggle = page.getByTestId('shortcuts-toggle');
    await toggle.click();
    await expect(toggle).not.toBeChecked();
    expect(await page.evaluate(() => localStorage.getItem('shortcuts'))).toBe('off');
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('shortcuts-dialog')).toBeHidden();

    await page.keyboard.press('n');
    await page.keyboard.press('/');
    expect(await sheetIsOpen(page)).toBe(false);
    await expect(page.getByTestId('new-post-sheet')).toBeHidden();
    await expect(page.getByTestId('palette-dialog')).toBeHidden();

    await page.reload();
    await expect(page.getByTestId('home-today')).toBeVisible();
    await page.keyboard.press('n');
    await page.keyboard.press('Shift+Slash');
    expect(await sheetIsOpen(page)).toBe(false);
    await expect(page.getByTestId('new-post-sheet')).toBeHidden();
    await expect(page.getByTestId('shortcuts-dialog')).toBeHidden();

    // The list stays one modifier key away, so the switch can always be turned back on.
    await page.keyboard.press('Control+Slash');
    await expect(page.getByTestId('shortcuts-dialog')).toBeVisible();
    await expect(toggle).not.toBeChecked();
    await toggle.click();
    await expect(toggle).toBeChecked();
    expect(await page.evaluate(() => localStorage.getItem('shortcuts'))).toBeNull();
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('shortcuts-dialog')).toBeHidden();
    await page.keyboard.press('n');
    await expect(page.getByRole('dialog', { name: 'New post' })).toBeVisible();
  });

  // Alpine's focus plugin starts a dialog's trap 15 ms after it opens (x-trap's setTimeout). Real key
  // presses reach that window on a busy runner and not on a fast one, so these two press inside it on
  // purpose, from the page: the list must not depend on its trap having started.
  test('Escape pressed the moment the list opens, before anything had the focus inside it, closes it', async ({ page, harness, as }) => {
    await as('owner');
    await openHome(page, harness.ids.workspace_a);

    await page.evaluate(async () => {
      document.body.dispatchEvent(new KeyboardEvent('keydown', { key: '?', shiftKey: true, bubbles: true, cancelable: true }));
      await new Promise((resolve) => setTimeout(resolve, 1));
      document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    });
    await expect(page.getByTestId('shortcuts-dialog')).toBeHidden();
    await page.keyboard.press('n');
    await expect(page.getByTestId('new-post-team-idea')).toBeFocused();
  });

  test('the list closed the moment it opens leaves no trap behind: Tab still moves through the page', async ({ page, harness, as }) => {
    await as('owner');
    await openHome(page, harness.ids.workspace_a);

    await page.evaluate(async () => {
      document.body.dispatchEvent(new KeyboardEvent('keydown', { key: '/', ctrlKey: true, bubbles: true, cancelable: true }));
      await new Promise((resolve) => setTimeout(resolve, 1));
      (document.querySelector('[data-testid="shortcuts-close"]') as HTMLElement).click();
    });
    await expect(page.getByTestId('shortcuts-dialog')).toBeHidden();
    // Long enough for a trap the plugin started late to be in place.
    await page.waitForTimeout(100);
    const focused: string[] = [];
    for (let i = 0; i < 3; i += 1) {
      await page.keyboard.press('Tab');
      focused.push(await page.evaluate(() => document.activeElement?.outerHTML.slice(0, 80) ?? ''));
    }
    expect(new Set(focused).size, `Tab moved through ${JSON.stringify(focused)}`).toBe(3);
  });

  test('/ opens Go to with nothing typed in it', async ({ page, harness, as }) => {
    await as('owner');
    await openHome(page, harness.ids.workspace_a);

    await page.keyboard.press('/');
    await expect(page.getByTestId('palette-dialog')).toBeVisible();
    await expect(page.getByTestId('palette-input')).toBeFocused();
    await expect(page.getByTestId('palette-input')).toHaveValue('');
  });

  test("on Analytics, whose closed Post details drawer stays in the page, /, ? and n still work", async ({ page, harness, as }) => {
    await as('owner');
    await page.goto(`/workspace/${harness.ids.workspace_a}/analytics/`);
    // The index answers with the first account's page (analytics:account), which holds the drawer.
    await expect(page).toHaveURL(new RegExp(`/workspace/${harness.ids.workspace_a}/analytics/[0-9a-f-]{36}/`));
    const drawer = page.getByRole('dialog', { name: 'Post details', includeHidden: true });
    await expect(drawer).toHaveCount(1);
    await expect(drawer).toHaveAttribute('aria-hidden', 'true');
    await expect(drawer).toBeHidden();

    await page.keyboard.press('/');
    await expect(page.getByTestId('palette-dialog')).toBeVisible();
    await expect(page.getByTestId('palette-input')).toBeFocused();
    await expect(page.getByTestId('palette-input')).toHaveValue('');
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('palette-dialog')).toBeHidden();

    await page.keyboard.press('Shift+Slash');
    await expect(page.getByTestId('shortcuts-dialog')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('shortcuts-dialog')).toBeHidden();

    await page.keyboard.press('n');
    await expect(page).toHaveURL(new RegExp(`${home(harness.ids.workspace_a)}#new-post$`));
    await expect(page.getByRole('dialog', { name: 'New post' })).toBeVisible();
  });

  test('Ctrl-K inside the sheet does nothing', async ({ page, harness, as }) => {
    await as('owner');
    await openHome(page, harness.ids.workspace_a);
    await page.keyboard.press('n');
    const field = page.getByTestId('new-post-team-idea');
    await expect(field).toBeFocused();

    await page.keyboard.press('Control+k');
    await expect(page.getByTestId('palette-dialog')).toBeHidden();
    await expect(field).toBeFocused();
    await expect(field).toHaveValue('');
    expect(await sheetIsOpen(page)).toBe(true);
  });

  test.describe('the list passes axe', () => {
    test.afterEach(async ({ harness }) => {
      await harness.fixture('dark_ready', { clear: true });
    });

    forSchemes((scheme) => {
      test(`the list of keys passes axe (${scheme})`, async ({ page, harness, as, axe }) => {
        // Home is declared dark-ready for this case only, so the dark case reads the list in dark.
        await harness.fixture('dark_ready', { add: ['studio:index'] });
        await as('owner');
        await openHome(page, harness.ids.workspace_a);
        await page.keyboard.press('Shift+Slash');
        const list = page.getByTestId('shortcuts-dialog');
        await settled(list, 'the list of keys');
        await expect(page.locator('html')).toHaveAttribute('data-theme', scheme);
        await axe(page, `Keyboard shortcuts (${scheme})`, { include: '[data-testid="shortcuts-dialog"]' });
      });
    });
  });
});
