// Golden path 5 (docs/specs/01-harness.md): Approve & schedule from the Approvals list; the post
// shows on the Calendar at that time, with the fingerprint the gate stamped.
//
// A fixture makes a post waiting for review with a proposed time three days ahead. The owner
// presses Approve & schedule on its row (Publish → List → Approvals today). In the database: the
// platform post is scheduled at the proposed time, its approved fingerprint is the gate's
// fingerprint of the post, and an "approved" action on the dashboard channel carries that
// fingerprint. On the week view of that date, its chip sits in the cell for the local date and hour.
// An editor sees the row without any approve control, and a direct POST to the approve URL with the
// editor's session is refused with 403 and changes nothing.
import { type BrowserContext } from '@playwright/test';

import { expect, test } from '../support/test';

type ReviewPost = {
  post_id: string;
  platform_posts: { id: string; platform: string; account_id: string }[];
  proposed_publish_at: string;
  local: { date: string; time: string; hour: number };
};

type PublishingPost = {
  post: { id: string; proposed_publish_at: string | null; scheduled_at: string | null } | null;
  platform_posts: {
    id: string;
    status: string;
    scheduled_at: string | null;
    approved_fingerprint: string;
    fingerprint: string;
    approved_by: string | null;
    approved_publish_at: string | null;
  }[];
  actions: {
    action: string;
    channel: string;
    user: string | null;
    platform_post_id: string | null;
    fingerprint: string;
    publish_at: string | null;
  }[];
};

const sameInstant = (a: string | null | undefined, b: string | null | undefined) =>
  !!a && !!b && new Date(a).getTime() === new Date(b).getTime();

/** The calendar week cell's test id for a workspace-local date and HH:MM time. */
const weekCell = (date: string, time: string) => `calendar-week-cell-${date}-${time.replace(':', '')}`;

async function csrfToken(context: BrowserContext): Promise<string> {
  const cookie = (await context.cookies()).find((item) => item.name === 'csrftoken');
  expect(cookie, 'the page set the CSRF cookie').toBeTruthy();
  return cookie!.value;
}

test('owner presses Approve & schedule on the Approvals list, and the post lands on the calendar at its time', async ({
  page,
  as,
  axe,
  harness,
  network,
}) => {
  const since = Date.now() / 1000;
  const { workspace_a: workspace, users } = harness.ids;
  const made = await harness.fixture<ReviewPost>('publishing_review_post', {
    author: 'editor',
    accounts: ['linkedin_company'],
    days_ahead: 3,
    hour: 10,
  });
  const [platformPost] = made.platform_posts;

  await as('owner');
  const response = await page.goto(`/workspace/${workspace}/calendar/?mode=list&tab=approvals`);
  expect(response?.status()).toBe(200);
  const row = page.getByTestId(`approvals-row-${made.post_id}`);
  await expect(row).toBeVisible();
  await axe(page, 'Approvals list (owner)');

  await row.getByTestId('approvals-row-approve-schedule').click();

  // The row leaves the list once the post is scheduled.
  await expect(row).toHaveCount(0);
  await axe(page, 'Approvals list after Approve & schedule (owner)');

  const after = await harness.probe<PublishingPost>('publishing_post', { post_id: made.post_id });
  expect(after.platform_posts).toHaveLength(1);
  const pp = after.platform_posts[0];
  expect(pp.id).toBe(platformPost.id);
  expect(pp.status).toBe('scheduled');
  expect(sameInstant(pp.scheduled_at, made.proposed_publish_at)).toBe(true);
  expect(sameInstant(pp.approved_publish_at, made.proposed_publish_at)).toBe(true);
  expect(pp.approved_fingerprint).toMatch(/^[0-9a-f]{64}$/);
  expect(pp.approved_fingerprint).toBe(pp.fingerprint);
  expect(pp.approved_by).toBe(users.owner.email);

  const approved = after.actions.filter((action) => action.action === 'approved');
  expect(approved).toHaveLength(1);
  expect(approved[0]).toMatchObject({
    channel: 'dashboard',
    user: users.owner.email,
    platform_post_id: pp.id,
    fingerprint: pp.approved_fingerprint,
  });
  expect(sameInstant(approved[0].publish_at, made.proposed_publish_at)).toBe(true);

  // The week of that date: the chip sits in the cell for the local date and hour.
  await page.goto(`/workspace/${workspace}/calendar/?mode=calendar&view=week&date=${made.local.date}`);
  const cell = page.getByTestId(weekCell(made.local.date, made.local.time));
  const chip = cell.getByTestId(`calendar-chip-${pp.id}`);
  await expect(chip).toBeVisible();
  await expect(cell).toHaveAttribute('data-date', made.local.date);
  await expect(cell).toHaveAttribute('data-time', made.local.time);
  await expect(chip).toHaveAttribute('data-platform-post-id', pp.id);
  await expect(page.getByTestId(`calendar-chip-${pp.id}`)).toHaveCount(1);
  await axe(page, 'Calendar week (owner)');

  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});

test('an editor sees no approve control, and a direct approve POST with the editor session is refused', async ({
  page,
  context,
  as,
  axe,
  harness,
}) => {
  const { workspace_a: workspace } = harness.ids;
  const made = await harness.fixture<ReviewPost>('publishing_review_post', {
    author: 'editor',
    accounts: ['linkedin_company'],
    days_ahead: 3,
    hour: 11,
  });

  await as('editor');
  const response = await page.goto(`/workspace/${workspace}/calendar/?mode=list&tab=approvals`);
  expect(response?.status()).toBe(200);
  const row = page.getByTestId(`approvals-row-${made.post_id}`);
  await expect(row).toBeVisible();
  await axe(page, 'Approvals list (editor)');
  await expect(page.getByTestId('approvals-row-approve-schedule')).toHaveCount(0);
  await expect(page.getByTestId('approvals-row-approve')).toHaveCount(0);
  await expect(row.getByTestId('approvals-row-review')).toHaveCount(0);

  const refused = await page.request.post(`/workspace/${workspace}/approvals/${made.post_id}/approve/`, {
    form: { schedule: '1' },
    headers: { 'X-CSRFToken': await csrfToken(context), Referer: page.url() },
  });
  expect(refused.status()).toBe(403);
  // Refused by the permission, not by a missing CSRF token.
  expect(await refused.text()).not.toContain('CSRF verification failed');

  const after = await harness.probe<PublishingPost>('publishing_post', { post_id: made.post_id });
  expect(after.platform_posts.map((pp) => pp.status)).toEqual(['pending_review']);
  expect(after.platform_posts[0].approved_fingerprint).toBe('');
  expect(after.actions.some((action) => action.action === 'approved')).toBe(false);
});
