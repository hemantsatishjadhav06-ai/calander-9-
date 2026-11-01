// Moving around the app as a person does, on any of the three devices (tests/e2e/screens/).
//
// Desktop (1024px and wider) shows the sidebar: the places (nav-<key>) and the Settings gear
// (nav-settings). Below 1024px the phone bar (phone-bar-<key>) holds Home, Approvals, Calendar and
// Inbox, and its More opens the menu drawer, which is the same sidebar. apps/common/navigation.py
// builds both.
//
//   await go(page, 'activity');         // click the place's link the way this device shows it
//   expect(phonePlaces).toContain(key);
import { type BrowserContext, type Locator, type Page, expect } from '@playwright/test';

/** The places the phone bar shows itself; every other place is in the drawer behind More. */
export const phonePlaces = ['home', 'approvals', 'calendar', 'inbox'] as const;

/** Below 1024px: the phone bar and the drawer instead of the sidebar. */
export function isPhone(page: Page): boolean {
  return (page.viewportSize()?.width ?? 0) < 1024;
}

/** The link a person taps for *key* here: the phone bar's on a phone when it has one, else the sidebar's. */
export function placeLink(page: Page, key: string): Locator {
  return isPhone(page) && (phonePlaces as readonly string[]).includes(key)
    ? page.getByTestId(`phone-bar-${key}`)
    : page.getByTestId(`nav-${key}`);
}

/** On a phone, open the drawer with the phone bar's More (it is a button, not a page); a no-op when open. */
export async function openMore(page: Page): Promise<void> {
  const more = page.getByTestId('phone-bar-more');
  if ((await more.getAttribute('aria-expanded')) !== 'true') await more.click();
  await expect(more, 'More says the drawer is open').toHaveAttribute('aria-expanded', 'true');
  // The closed drawer is pushed off the left edge (and inert), which counts as visible; open, it is on screen.
  await expect(page.getByTestId('sidebar-nav'), 'the drawer slid in with the places').toBeInViewport();
}

/**
 * Go to *key* ('home', 'approvals', … or 'settings') by tapping its link, and wait until the page it
 * leads to has loaded: the link's address, or below it where that page sends on (Analytics opens
 * its first account). Waiting for the new document, not for a matching address, also covers a tap
 * on the page already shown and a place whose address starts the current one (Home from Activity).
 * Returns the address the link pointed at.
 */
export async function go(page: Page, key: string): Promise<string> {
  if (isPhone(page) && !(phonePlaces as readonly string[]).includes(key)) await openMore(page);
  const link = placeLink(page, key);
  const href = await link.getAttribute('href');
  expect(href, `the ${key} link has an address`).toBeTruthy();
  const arrived = page.waitForEvent('framenavigated', {
    predicate: (frame) => frame === page.mainFrame() && new URL(frame.url()).pathname.startsWith(href!),
  });
  await link.click();
  await arrived;
  await page.waitForLoadState('load');
  return href!;
}

/** The place lit on this page: its link carries aria-current="page" (in the drawer too, closed or not). */
export async function expectLit(page: Page, key: string): Promise<void> {
  await expect(page.getByTestId(`nav-${key}`), `${key} is the lit place`).toHaveAttribute('aria-current', 'page');
  if (isPhone(page) && (phonePlaces as readonly string[]).includes(key)) {
    await expect(page.getByTestId(`phone-bar-${key}`), `${key} is lit in the phone bar`).toHaveAttribute(
      'aria-current',
      'page',
    );
  }
}

/** The CSRF token the page left in its cookie, for a direct POST through page.request. */
export async function csrfToken(context: BrowserContext): Promise<string> {
  const cookie = (await context.cookies()).find((item) => item.name === 'csrftoken');
  expect(cookie, 'the page set the CSRF cookie').toBeTruthy();
  return cookie!.value;
}
