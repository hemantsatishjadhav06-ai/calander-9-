// Screen 1's pair (spec D9 and screen 1, plan T14): how a person starts a post, light, at 390 x 844
// and 1440 x 900, for the owner's sign-off. Nothing is compared, masked or committed: the images go to
// test-results/pairs/01-new-post/<side>/ and are attached to the pull request.
//
// Before (main, 045978b): Home; the sidebar's New menu open (on a phone, the drawer first, then New);
// the New idea dialog; Calendar month. After (this branch, once screen 1 is built): Home with the
// New post button; the sheet in Ask the team and in Write it myself; the idea form in the sheet;
// Calendar month with the button. The after side names the hooks screen 1 adds (new-post-open,
// new-post-sheet, new-post-mode-self, new-post-save-idea …), so it fails, writing nothing, until they
// are on the page. The after side also shows each state in dark (`<state>-dark-<project>.png`, T25):
// Home and Calendar are dark-ready since T22; main has no dark, so the before side is light only.
//
//   # before: a server started in a worktree of main (tests/e2e/README.md, Pairs)
//   E2E_PORT=<main's port> PAIR_SIDE=before npm run pairs -- tests/e2e/pairs/01-new-post.pair.ts
//   # after: this branch's server (started for you on E2E_PORT when none is running)
//   E2E_PORT=<this branch's port> npm run pairs -- tests/e2e/pairs/01-new-post.pair.ts
import { type Page, expect } from '@playwright/test';

import { type PairState, pairTests } from './support';

const home = (ws: string) => `/workspace/${ws}/studio/`;
const calendarMonth = (ws: string) => `/workspace/${ws}/calendar/?mode=calendar&view=month`;

// ── Main (045978b): only hooks that exist there ──────────────────────────────────────────────────

/** The sidebar's New menu, open. On a phone the sidebar is the drawer, so it opens first. */
async function openNewMenu(page: Page): Promise<void> {
  const toggle = page.getByTestId('mobile-menu-toggle');
  if (await toggle.isVisible()) {
    await toggle.click();
    await expect(toggle, 'the phone drawer is open').toHaveAttribute('aria-expanded', 'true');
  }
  await page.getByTestId('sidebar-new-toggle').click();
  await expect(page.getByTestId('sidebar-new-toggle'), 'the New menu is open').toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByTestId('sidebar-new-idea')).toBeVisible();
}

/** The New idea dialog, opened from the New menu as a person does (it closes the drawer first). */
async function openIdeaDialog(page: Page): Promise<void> {
  await openNewMenu(page);
  await page.getByTestId('sidebar-new-idea').click();
  await expect(page.getByRole('dialog', { name: 'New idea' })).toBeVisible();
  await expect(page.getByTestId('idea-title')).toBeFocused();
}

const before: PairState[] = [
  { name: 'home', path: home, hook: 'home-today' },
  { name: 'new-menu', path: home, hook: 'home-today', prepare: openNewMenu },
  { name: 'idea-dialog', path: home, hook: 'home-today', prepare: openIdeaDialog },
  { name: 'calendar-month', path: calendarMonth, hook: 'calendar-shell' },
];

// ── This branch: the hooks screen 1 adds (spec, screen 1, "Test ids") ───────────────────────────

/** The sheet, opened by its button, in Ask the team (the default) with focus in the idea. */
async function openSheet(page: Page): Promise<void> {
  await page.getByTestId('new-post-open').click();
  await expect(page.getByTestId('new-post-sheet')).toBeVisible();
  await expect(page.getByRole('dialog', { name: 'New post' })).toBeVisible();
  await expect(page.getByTestId('new-post-team-idea')).toBeFocused();
}

/** The sheet in Write it myself. */
async function openSheetSelf(page: Page): Promise<void> {
  await openSheet(page);
  await page.getByTestId('new-post-mode-self').click();
  await expect(page.getByTestId('new-post-self-open')).toBeVisible();
}

/** The sheet's idea form ("Save it as an idea instead"), its title focused. */
async function openSheetIdea(page: Page): Promise<void> {
  await openSheet(page);
  await page.getByTestId('new-post-save-idea').click();
  await expect(page.getByRole('dialog', { name: 'New idea' })).toBeVisible();
  await expect(page.getByTestId('idea-title')).toBeFocused();
}

const afterLight: PairState[] = [
  { name: 'home', path: home, hook: 'new-post-open' },
  { name: 'sheet-team', path: home, hook: 'new-post-open', prepare: openSheet },
  { name: 'sheet-self', path: home, hook: 'new-post-open', prepare: openSheetSelf },
  { name: 'idea-form', path: home, hook: 'new-post-open', prepare: openSheetIdea },
  { name: 'calendar-month', path: calendarMonth, hook: 'new-post-open' },
];
const after: PairState[] = [
  ...afterLight,
  ...afterLight.map((state): PairState => ({ ...state, name: `${state.name}-dark`, scheme: 'dark' })),
];

pairTests('01-new-post', { before, after });
