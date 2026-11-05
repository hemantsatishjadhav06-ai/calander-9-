import type { Locator, Page } from '@playwright/test';

import { settled } from '../support/settled';
import { expect, test } from '../support/test';

// Below 1024px the phone bar (base.html) is fixed along the bottom of the screen. Whatever else a page
// floats along the bottom (the error toast, the approval toasts, the bulk-selection bars, the media
// page's Folders button, the blog form's Save bar) sits clear above it: the bar stays visible and
// nothing covers it or hides under it. Desktop has no bar and keeps its places (24px from the bottom).
// The post page and the composer have no phone bar (their own bar takes the bottom); see
// apps/common/tests/test_navigation_render.py.
//
// New post (screen 1, spec D5; components/primary_action.html) floats above the phone bar on Home and
// Calendar on a phone and sits in the page header's slot from 1024 px. The toasts ride above it (the
// page sets has-fab on body, which lifts them, styles.css), and it hides while posts are selected, so
// it never covers a toast or a selection bar.

const DESKTOP_GAP = 24;

function isPhone(page: Page): boolean {
  return (page.viewportSize()?.width ?? 0) < 1024;
}

async function box(locator: Locator, what: string) {
  const found = await locator.boundingBox();
  expect(found, `${what} has a box on screen`).not.toBeNull();
  return found!;
}

/** On a phone: *element* ends above the phone bar and the bar is visible. On desktop: no bar. */
async function clearOfTheBar(page: Page, element: Locator, what: string): Promise<number> {
  const bar = page.getByTestId('phone-bar');
  await expect(element, `${what} is shown`).toBeVisible();
  const own = await box(element, what);
  const height = page.viewportSize()!.height;
  if (!isPhone(page)) {
    await expect(bar, 'no phone bar on desktop').toBeHidden();
    return height - (own.y + own.height);
  }
  await expect(bar, 'the phone bar is visible').toBeVisible();
  const edge = await box(bar, 'the phone bar');
  expect(edge.y + edge.height, 'the phone bar sits on the bottom edge').toBeCloseTo(height, 0);
  expect(own.y + own.height, `${what} ends above the phone bar (top at ${edge.y}px)`).toBeLessThanOrEqual(edge.y);
  return height - (own.y + own.height);
}

async function above(lower: Locator, upper: Locator, what: string) {
  const low = await box(lower, 'the lower element');
  const up = await box(upper, 'the upper element');
  expect(up.y + up.height, what).toBeLessThanOrEqual(low.y);
}

async function errorToast(page: Page) {
  // What base.html's htmx:responseError handler dispatches when a request fails.
  await page.evaluate(() =>
    window.dispatchEvent(new CustomEvent('htmx-error', { detail: { message: 'Something went wrong. Please try again.' } })),
  );
  const toast = page.getByTestId('error-toast');
  await settled(toast, 'the error toast');
  return toast;
}

async function approvalToast(page: Page) {
  // What an approval action's HX-Trigger (or bbFailureToast) dispatches: approvals/partials/_toasts.html.
  await page.evaluate(() =>
    document.body.dispatchEvent(new CustomEvent('showToast', { detail: { tone: 'error', title: 'Could not move these posts.' } })),
  );
  const host = page.getByTestId('toast-host');
  await settled(host, 'the approval toast');
  return host;
}

/**
 * New post in its place: on a phone it floats (fixed) and ends above the phone bar; on desktop it is in
 * the flow of the page header's slot, near the top of the page. Either way it is the slot's button.
 */
async function newPostInItsPlace(page: Page): Promise<Locator> {
  const button = page.getByTestId('new-post-open');
  await expect(button, 'New post is shown').toBeVisible();
  await expect(page.locator('[data-primary-slot="header"]').getByTestId('new-post-open'), 'the header slot holds New post').toHaveCount(1);
  const position = await button.evaluate((element) => getComputedStyle(element).position);
  if (isPhone(page)) {
    expect(position, 'New post floats on a phone').toBe('fixed');
    await clearOfTheBar(page, button, 'New post');
  } else {
    expect(position, 'New post sits in the header from 1024px').toBe('static');
    const own = await box(button, 'New post');
    expect(own.y + own.height, 'New post is at the top of the page, in its header').toBeLessThanOrEqual(page.viewportSize()!.height / 3);
  }
  return button;
}

/** Two elements on screen that do not cover each other. */
async function apart(first: Locator, second: Locator, what: string) {
  const a = await box(first, 'the first element');
  const b = await box(second, 'the second element');
  const overlap = a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
  expect(overlap, what).toBe(false);
}

/** A toast never covers New post: above it on a phone (both float there), clear of it on desktop. */
async function rideAbove(page: Page, button: Locator, toast: Locator, what: string) {
  if (isPhone(page)) await above(button, toast, `${what} ends above New post`);
  else await apart(button, toast, `${what} and New post do not cover each other`);
}

async function dismissErrorToast(page: Page) {
  const toast = page.getByTestId('error-toast');
  await toast.getByRole('button', { name: 'Dismiss' }).click();
  await expect(toast).toBeHidden();
}

test('Home: New post floats above the phone bar (in the header on desktop) and the error toast rides above it', async ({
  page,
  harness,
  as,
  axe,
}) => {
  await as('owner');
  await page.goto(`/workspace/${harness.ids.workspace_a}/studio/`);
  await expect(page.getByTestId('home-today')).toBeVisible();
  const button = await newPostInItsPlace(page);

  const toast = await errorToast(page);
  await clearOfTheBar(page, toast, 'the error toast');
  await rideAbove(page, button, toast, 'the error toast');
  await expect(button, 'New post stays shown under a toast').toBeVisible();
  await axe(page, 'Home with New post and the error toast');
});

test('Calendar: the toasts ride above New post, and New post hides while posts are selected', async ({
  page,
  harness,
  as,
  axe,
}) => {
  const made = await harness.fixture<{ platform_posts: { id: string }[] }>('publishing_scheduled_post', {
    author: 'editor',
    approver: 'owner',
    days_ahead: 3,
  });
  await as('owner');
  await page.goto(`/workspace/${harness.ids.workspace_a}/calendar/?mode=list&tab=queue`);
  const select = page.getByTestId(`calendar-select-${made.platform_posts[0].id}`);
  await expect(select).toBeVisible();
  const button = await newPostInItsPlace(page);

  const error = await errorToast(page);
  await clearOfTheBar(page, error, 'the error toast');
  await rideAbove(page, button, error, 'the error toast');
  await dismissErrorToast(page);

  const approval = await approvalToast(page);
  await clearOfTheBar(page, approval, 'the approval toast');
  await rideAbove(page, button, approval, 'the approval toast');
  await axe(page, 'Calendar list with New post and a toast');
  await page.getByTestId('toast-host').evaluate((host) => host.replaceChildren());

  // Posts selected: the selection bar takes the bottom and New post steps aside until they are not.
  await select.click();
  const bulk = page.getByTestId('calendar-bulk-bar');
  await settled(bulk, 'the selection bar');
  await expect(button, 'New post hides while posts are selected').toBeHidden();
  await select.click();
  await expect(bulk).toBeHidden();
  await expect(button, 'New post is back once nothing is selected').toBeVisible();
  await newPostInItsPlace(page);
});

test('Home: the error toast sits above the phone bar', async ({ page, harness, as, axe }) => {
  await as('owner');
  await page.goto(`/workspace/${harness.ids.workspace_a}/studio/`);
  await expect(page.getByTestId('home-today')).toBeVisible();

  const gap = await clearOfTheBar(page, await errorToast(page), 'the error toast');
  if (!isPhone(page)) expect(gap, 'desktop keeps the toast 24px from the bottom').toBeCloseTo(DESKTOP_GAP, 0);
  await axe(page, 'Home with the error toast');
});

test('Calendar list: the selection bar and a toast sit above the phone bar', async ({ page, harness, as, axe }) => {
  const made = await harness.fixture<{ platform_posts: { id: string }[] }>('publishing_scheduled_post', {
    author: 'editor',
    approver: 'owner',
    days_ahead: 2,
  });
  await as('owner');
  await page.goto(`/workspace/${harness.ids.workspace_a}/calendar/?mode=list&tab=queue`);
  await page.getByTestId(`calendar-select-${made.platform_posts[0].id}`).click();

  const bulk = page.getByTestId('calendar-bulk-bar');
  await settled(bulk, 'the selection bar');
  const gap = await clearOfTheBar(page, bulk, 'the selection bar');
  if (!isPhone(page)) expect(gap, 'desktop keeps the selection bar 24px from the bottom').toBeCloseTo(DESKTOP_GAP, 0);

  // A toast while posts are selected rises above the selection bar too.
  const toast = await approvalToast(page);
  await clearOfTheBar(page, toast, 'the approval toast');
  await above(bulk, toast, 'the approval toast ends above the selection bar');
  await axe(page, 'Calendar list with a selection and a toast');

  await page.getByTestId(`calendar-select-${made.platform_posts[0].id}`).click();
  await expect(bulk).toBeHidden();
});

test('Approvals: the selection bar and a toast sit above the phone bar', async ({ page, harness, as, axe }) => {
  const made = await harness.fixture<{ post_id: string }>('publishing_review_post', { author: 'editor' });
  await as('owner');
  await page.goto(`/workspace/${harness.ids.workspace_a}/approvals/`);
  const row = page.getByTestId('approvals-list').getByTestId(`approvals-row-${made.post_id}`);
  await row.getByTestId('approvals-row-select').check();

  const bulk = page.getByTestId('approvals-bulk-bar');
  await settled(bulk, 'the selection bar');
  const gap = await clearOfTheBar(page, bulk, 'the selection bar');
  if (!isPhone(page)) expect(gap, 'desktop keeps the selection bar 24px from the bottom').toBeCloseTo(DESKTOP_GAP, 0);

  // A toast while posts are selected rises above the selection bar too.
  const lifted = await approvalToast(page);
  await clearOfTheBar(page, lifted, 'the approval toast');
  await above(bulk, lifted, 'the approval toast ends above the selection bar');
  await axe(page, 'Approvals with a selection and a toast');
  await page.getByTestId('toast-host').evaluate((host) => host.replaceChildren());

  await row.getByTestId('approvals-row-select').uncheck();
  await expect(bulk).toBeHidden();
  const toastGap = await clearOfTheBar(page, await approvalToast(page), 'the approval toast');
  if (!isPhone(page)) expect(toastGap, 'desktop keeps the toast 24px from the bottom').toBeCloseTo(DESKTOP_GAP, 0);
  await axe(page, 'Approvals with a toast');
});

test('the page keeps the phone bar’s height clear when it scrolls a control into view (WCAG 2.4.11)', async ({
  page,
  harness,
  as,
  axe,
}) => {
  await as('owner');
  await page.goto(`/workspace/${harness.ids.workspace_a}/settings/?tab=advanced`);
  await expect(page.getByTestId('settings-panel-advanced')).toBeVisible();
  await axe(page, 'Settings: Advanced (owner)');
  // Both scrollers: main (when a page runs over, as the calendar does) and the content inside it.
  // scroll-padding-bottom is what keeps a control focused from the keyboard out from under the bar.
  const padding: number[] = [];
  for (const testid of ['main-content', 'page-scroller']) {
    const scroller = page.getByTestId(testid);
    await expect(scroller, `${testid} is on the page`).toHaveCount(1);
    padding.push(await scroller.evaluate((element) => parseFloat(getComputedStyle(element).scrollPaddingBottom) || 0));
  }
  if (!isPhone(page)) {
    await expect(page.getByTestId('phone-bar'), 'no phone bar on desktop').toBeHidden();
    expect(padding, 'desktop scrolls as before').toEqual([0, 0]);
    return;
  }
  const bar = await box(page.getByTestId('phone-bar'), 'the phone bar');
  for (const value of padding) {
    expect(value, `the scroller keeps the phone bar’s ${bar.height}px clear`).toBeGreaterThanOrEqual(bar.height - 0.5);
  }
});

test('Media: the Folders button sits above the phone bar', async ({ page, harness, as, axe }) => {
  await as('owner');
  await page.goto(`/workspace/${harness.ids.workspace_a}/media/`);
  await axe(page, 'Media library');
  const folders = page.getByTestId('media-folders-toggle');
  if (!isPhone(page)) {
    await expect(folders, 'the Folders button is for phones only').toBeHidden();
    return;
  }
  await clearOfTheBar(page, folders, 'the Folders button');
});

test('Blog: the form’s Save bar sits above the phone bar', async ({ page, harness, as, axe }) => {
  await harness.fixture('blog_site', {});
  await as('owner');
  await page.goto(`/workspace/${harness.ids.workspace_a}/blog/new/`);
  const actions = page.getByTestId('blog-form-actions');
  // Sticky at the bottom of the screen while the form runs past it.
  await clearOfTheBar(page, actions, 'the Save bar');
  await axe(page, 'New blog post');
});
