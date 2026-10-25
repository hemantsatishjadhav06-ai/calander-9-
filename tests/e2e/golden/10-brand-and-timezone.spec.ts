// Golden path 10 (docs/specs/01-harness.md): change the brand colour and the timezone; the preview
// and the calendar reflect both.
//
// A fixture makes a workspace with a blank timezone in its own organisation (default Asia/Dubai),
// with a fresh owner and a fresh editor, and a post the owner approved in the dashboard and that is
// scheduled three days ahead at 10:00 Dubai time. As the owner: on the brand page, change the
// primary colour and save; the colour is stored, and the sample image's address (its ?v=) and its
// bytes change. In the organisation settings, change the default timezone to Asia/Tokyo and save;
// the workspace has no timezone of its own, so the calendar's week view moves the scheduled chip
// from the 10:00 Dubai cell to the 15:00 Tokyo cell, while the post stays scheduled at the same
// instant with its approval intact. The editor of that workspace sees the brand page read-only and a
// direct save is refused; the organisation settings refuse the editor too.
//
// No screen sets a workspace's own timezone today, so the organisation default is the one a person
// can change. The calendar shows no brand colour today (only the cross-workspace calendar shows a
// workspace dot); Phase 3 decides whether it should (spec, open questions).
import { type BrowserContext, type Page } from '@playwright/test';

import { expect, test } from '../support/test';

const FIRST_TIMEZONE = 'Asia/Dubai';
const NEW_TIMEZONE = 'Asia/Tokyo';
const NEW_PRIMARY = '#1f6b4f';

type Local = { date: string; time: string };

type BrandWorkspace = {
  workspace_id: string;
  organisation_id: string;
  owner: { id: string; email: string };
  editor: { id: string; email: string };
  post_id: string;
  platform_post_id: string;
  scheduled_at: string;
  local_before: Local;
  local_after: Local;
};

type BrandState = {
  brand: { primary_color: string; accent_color: string; updated_at: string };
  workspace: { timezone: string; effective_timezone: string };
  organisation: { default_timezone: string };
  platform_posts: {
    id: string;
    status: string;
    scheduled_at: string | null;
    approved_fingerprint: string;
    fingerprint: string;
    approved_publish_at: string | null;
  }[];
};

const sameInstant = (a: string | null | undefined, b: string | null | undefined) =>
  !!a && !!b && new Date(a).getTime() === new Date(b).getTime();

/** The calendar week cell's test id for a workspace-local date and HH:MM time. */
const weekCell = (local: Local) => `calendar-week-cell-${local.date}-${local.time.replace(':', '')}`;

async function csrfToken(context: BrowserContext): Promise<string> {
  const cookie = (await context.cookies()).find((item) => item.name === 'csrftoken');
  expect(cookie, 'the page set the CSRF cookie').toBeTruthy();
  return cookie!.value;
}

/** The first sample image's address and the bytes it serves. */
async function sample(page: Page): Promise<{ src: string; version: string; bytes: Buffer }> {
  const src = await page.getByTestId('brand-sample-image').first().getAttribute('src');
  expect(src, 'the sample image has an address').toBeTruthy();
  const url = new URL(src!, page.url());
  const response = await page.request.get(url.toString());
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toBe('image/jpeg');
  return { src: src!, version: url.searchParams.get('v') ?? '', bytes: await response.body() };
}

async function expectChipIn(page: Page, workspace: string, local: Local, platformPostId: string): Promise<void> {
  await page.goto(`/workspace/${workspace}/calendar/?mode=calendar&view=week&date=${local.date}`);
  const cell = page.getByTestId(weekCell(local));
  await expect(cell.getByTestId(`calendar-chip-${platformPostId}`)).toBeVisible();
  await expect(page.getByTestId(`calendar-chip-${platformPostId}`)).toHaveCount(1);
}

test('owner changes the brand colour and the organisation timezone; the sample and the calendar follow', async ({
  page,
  as,
  axe,
  harness,
  network,
}) => {
  test.info().annotations.push({
    type: 'note',
    description: 'The calendar shows no brand colour today; Phase 3 decides whether it should.',
  });
  const since = Date.now() / 1000;
  const made = await harness.fixture<BrandWorkspace>('brand_timezone_workspace', {
    timezone: FIRST_TIMEZONE,
    then_timezone: NEW_TIMEZONE,
    days_ahead: 3,
    hour: 10,
  });
  const workspace = made.workspace_id;
  const state = () => harness.probe<BrandState>('brand_timezone_state', { workspace_id: workspace });
  const before = await state();
  expect(before.workspace).toEqual({ timezone: '', effective_timezone: FIRST_TIMEZONE });
  expect(before.platform_posts.map((pp) => pp.status)).toEqual(['scheduled']);
  expect(before.brand.primary_color).not.toBe(NEW_PRIMARY.toUpperCase());

  await as({ email: made.owner.email });

  // Brand page: change the primary colour and save.
  const response = await page.goto(`/workspace/${workspace}/studio/brand/`);
  expect(response?.status()).toBe(200);
  await axe(page, 'Brand profile (owner)');
  const first = await sample(page);
  await page.getByTestId('brand-primary-color').fill(NEW_PRIMARY);
  await page.getByTestId('brand-save').click();
  await expect.poll(async () => (await state()).brand.primary_color).toBe(NEW_PRIMARY.toUpperCase());
  await expect(page.getByTestId('brand-primary-color')).toHaveValue(NEW_PRIMARY);
  await axe(page, 'Brand profile saved (owner)');

  // The sample image is drawn again in the new colour: a new address and different bytes.
  const second = await sample(page);
  expect(second.version).not.toBe(first.version);
  expect(second.src).not.toBe(first.src);
  expect(second.bytes.equals(first.bytes)).toBe(false);

  // Before the timezone changes, the chip sits in the 10:00 Dubai cell.
  await expectChipIn(page, workspace, made.local_before, made.platform_post_id);
  await axe(page, `Calendar week in ${FIRST_TIMEZONE} (owner)`);

  // Organisation settings: change the default timezone and save.
  const settings = await page.goto('/organizations/settings/');
  expect(settings?.status()).toBe(200);
  await axe(page, 'Organisation settings (owner)');
  await page.getByTestId('org-settings-timezone').selectOption(NEW_TIMEZONE);
  await page.getByTestId('org-settings-timezone-save').click();
  await expect.poll(async () => (await state()).organisation.default_timezone).toBe(NEW_TIMEZONE);
  await expect(page.getByTestId('org-settings-timezone')).toHaveValue(NEW_TIMEZONE);
  await axe(page, 'Organisation settings saved (owner)');

  const after = await state();
  expect(after.workspace).toEqual({ timezone: '', effective_timezone: NEW_TIMEZONE });
  // The same instant, still scheduled, the approval untouched: only the local wall time moved.
  expect(after.platform_posts).toHaveLength(1);
  const [pp] = after.platform_posts;
  expect(pp.status).toBe('scheduled');
  expect(sameInstant(pp.scheduled_at, made.scheduled_at)).toBe(true);
  expect(sameInstant(pp.approved_publish_at, made.scheduled_at)).toBe(true);
  expect(pp.approved_fingerprint).toBe(pp.fingerprint);

  // The week view now shows the chip in the 15:00 Tokyo cell, and not in the old one.
  await expectChipIn(page, workspace, made.local_after, made.platform_post_id);
  await expect(page.getByTestId(weekCell(made.local_before)).getByTestId(`calendar-chip-${made.platform_post_id}`)).toHaveCount(0);
  await axe(page, `Calendar week in ${NEW_TIMEZONE} (owner)`);

  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});

test('the editor sees the brand page read-only, and a direct save or timezone change is refused', async ({
  page,
  context,
  as,
  axe,
  harness,
}) => {
  const made = await harness.fixture<BrandWorkspace>('brand_timezone_workspace', {
    timezone: FIRST_TIMEZONE,
    then_timezone: NEW_TIMEZONE,
    days_ahead: 3,
    hour: 10,
  });
  const workspace = made.workspace_id;
  const state = () => harness.probe<BrandState>('brand_timezone_state', { workspace_id: workspace });
  const before = await state();

  await as({ email: made.editor.email });
  const response = await page.goto(`/workspace/${workspace}/studio/brand/`);
  expect(response?.status()).toBe(200);
  await axe(page, 'Brand profile (editor)');
  await expect(page.getByTestId('brand-primary-color')).toBeDisabled();
  await expect(page.getByTestId('brand-accent-color')).toBeDisabled();
  await expect(page.getByTestId('brand-save')).toHaveCount(0);

  const refused = await page.request.post(`/workspace/${workspace}/studio/brand/`, {
    form: { primary_color: NEW_PRIMARY, accent_color: before.brand.accent_color },
    headers: { 'X-CSRFToken': await csrfToken(context), Referer: page.url() },
  });
  expect(refused.status()).toBe(403);
  // Refused by the permission, not by a missing CSRF token.
  expect(await refused.text()).not.toContain('CSRF verification failed');

  const settings = await page.goto('/organizations/settings/');
  expect(settings?.status()).toBe(403);
  await axe(page, 'Organisation settings refused (editor)');
  const timezone = await page.request.post('/organizations/settings/', {
    form: { action: 'update_timezone', timezone: NEW_TIMEZONE },
    headers: { 'X-CSRFToken': await csrfToken(context), Referer: page.url() },
  });
  expect(timezone.status()).toBe(403);
  expect(await timezone.text()).not.toContain('CSRF verification failed');

  const after = await state();
  expect(after.brand.primary_color).toBe(before.brand.primary_color);
  expect(after.brand.updated_at).toBe(before.brand.updated_at);
  expect(after.organisation.default_timezone).toBe(FIRST_TIMEZONE);
  expect(after.workspace.effective_timezone).toBe(FIRST_TIMEZONE);
});
