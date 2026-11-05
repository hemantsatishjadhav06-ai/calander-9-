import type { Locator, Page } from '@playwright/test';

import type { Harness } from '../support/harness';
import { expect, test } from '../support/test';

// Appearance and the head script (Phase 3, T5; spec D2). The Account page is declared dark-ready for
// each test through the harness (`dark_ready`, tests/e2e/server/steps/p3.py) and cleared after it, so
// no other spec ever meets a dark page. A declared page follows a dark device and the person's
// choice in the account menu (System, Light, Dark, kept on this device); choosing repaints without a
// navigation; a page not declared stays light whatever is chosen; and without JavaScript the
// stylesheet's media block still paints a declared page dark on a dark device.

const ACCOUNT = '/accounts/settings/';
const ACCOUNT_NAME = 'accounts:settings';
const NOTE = 'This page stays light for now.';

type Ready = { ready: string[] };
type Account = { name: string };

async function declare(harness: Harness): Promise<Ready> {
  return harness.fixture<Ready>('dark_ready', { add: [ACCOUNT_NAME] });
}

test.afterEach(async ({ harness }) => {
  await harness.fixture<Ready>('dark_ready', { clear: true });
});

function html(page: Page): Locator {
  return page.locator('html');
}

/** WCAG relative luminance of the page's canvas (main's background): near 0 is dark, near 1 light. */
async function canvasLuminance(page: Page): Promise<number> {
  const color = await page.getByTestId('main-content').evaluate((main) => getComputedStyle(main).backgroundColor);
  const channels = color.match(/[\d.]+/g)?.slice(0, 3).map(Number);
  expect(channels, `a colour I can read: ${color}`).toHaveLength(3);
  const [r, g, b] = channels!.map((value) => {
    const c = value / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

async function expectDark(page: Page): Promise<void> {
  await expect.poll(() => canvasLuminance(page), { message: 'the canvas is dark' }).toBeLessThan(0.1);
}

async function expectLight(page: Page): Promise<void> {
  await expect.poll(() => canvasLuminance(page), { message: 'the canvas is light' }).toBeGreaterThan(0.8);
}

/** Open the account menu as a person does: on a narrow screen it sits in the menu drawer. */
async function openAccountMenu(page: Page, harness: Harness): Promise<void> {
  const drawer = page.getByTestId('mobile-menu-toggle');
  if (await drawer.isVisible()) {
    await drawer.click();
    await expect(drawer).toHaveAttribute('aria-expanded', 'true');
  }
  const owner = await harness.probe<Account>('user_account', { email: harness.ids.users.owner.email });
  // The account menu's button is named by the person it belongs to.
  await page.getByRole('button', { name: owner.name }).click();
  await expect(page.getByRole('group', { name: 'Appearance' })).toBeVisible();
}

test('a dark device paints a declared page dark', async ({ page, harness, as }) => {
  expect((await declare(harness)).ready).toContain(ACCOUNT_NAME);
  await page.emulateMedia({ colorScheme: 'dark' });
  await as('owner');

  await page.goto(ACCOUNT);
  await expect(html(page)).toHaveAttribute('data-theme-ready', '');
  await expect(html(page)).toHaveAttribute('data-theme', 'dark');
  await expectDark(page);

  await openAccountMenu(page, harness);
  await expect(page.getByTestId('account-appearance-system')).toBeChecked();
  await expect(page.getByText(NOTE)).toHaveCount(0);
});

test('choosing Light repaints without a navigation and survives a reload', async ({ page, harness, as }) => {
  await declare(harness);
  await page.emulateMedia({ colorScheme: 'dark' });
  await as('owner');
  await page.goto(ACCOUNT);
  await expectDark(page);

  // Marks on this document: a navigation would wipe them.
  await page.evaluate(() => {
    const w = window as unknown as { themeEvents: unknown[] };
    w.themeEvents = [];
    window.addEventListener('bb:themechange', (event) => w.themeEvents.push((event as CustomEvent).detail));
  });
  await openAccountMenu(page, harness);
  await page.getByTestId('account-appearance-light').check();

  await expect(html(page)).toHaveAttribute('data-theme', 'light');
  await expectLight(page);
  expect(
    await page.evaluate(() => (window as unknown as { themeEvents?: unknown[] }).themeEvents),
    'the same document, told once',
  ).toEqual([{ theme: 'light', preference: 'light' }]);
  expect(await page.evaluate(() => localStorage.getItem('theme'))).toBe('light');

  await page.reload();
  await expect(html(page)).toHaveAttribute('data-theme', 'light');
  await expectLight(page);
  await openAccountMenu(page, harness);
  await expect(page.getByTestId('account-appearance-light')).toBeChecked();

  // Back to System: the dark device decides again.
  await page.getByTestId('account-appearance-system').check();
  await expect(html(page)).toHaveAttribute('data-theme', 'dark');
  await expectDark(page);
});

test('a page not declared stays light with Dark chosen, and says so', async ({ page, harness, as, axe }) => {
  const { ready } = await harness.fixture<Ready>('dark_ready', { clear: true });
  // This case needs one page the code has not declared; when the Account page is, pick another.
  expect(ready, 'the Account page is not declared by the registry').not.toContain(ACCOUNT_NAME);
  await page.emulateMedia({ colorScheme: 'dark' });
  await as('owner');
  await page.goto(ACCOUNT);
  await expect(html(page)).not.toHaveAttribute('data-theme-ready');

  await openAccountMenu(page, harness);
  await page.getByTestId('account-appearance-dark').check();
  await expect(page.getByTestId('account-appearance-dark')).toBeChecked();
  await expect(page.getByText(NOTE)).toBeVisible();
  await expect(html(page)).not.toHaveAttribute('data-theme');
  await expectLight(page);
  await axe(page, 'Account menu with Appearance');

  // The choice is kept: once the page is declared, it opens dark, even on a light device.
  await declare(harness);
  await page.emulateMedia({ colorScheme: 'light' });
  await page.reload();
  await expect(html(page)).toHaveAttribute('data-theme', 'dark');
  await expectDark(page);
});

test.describe('without JavaScript', () => {
  test.use({ javaScriptEnabled: false });

  test('a dark device still paints a declared page dark, through the stylesheet alone', async ({ page, harness, as }) => {
    await declare(harness);
    await page.emulateMedia({ colorScheme: 'dark' });
    await as('owner');
    await page.goto(ACCOUNT);

    await expect(html(page)).toHaveAttribute('data-theme-ready', '');
    await expect(html(page), 'no script ran').not.toHaveAttribute('data-theme');
    await expectDark(page);
  });
});
