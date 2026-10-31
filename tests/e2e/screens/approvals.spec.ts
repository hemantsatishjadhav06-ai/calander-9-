// Approvals (spec D3, R3; docs/specs/02-cut-and-merge.md): /workspace/<id>/approvals/ is the
// Approvals list on a screen of its own, through the same gate.
//
// A fixture makes a post waiting for review with a proposed time. The owner opens Approvals from
// the navigation (the sidebar on desktop, the phone bar on a phone) and presses Approve & schedule
// on its row. In the database: the platform post is scheduled at the proposed time, its approved
// fingerprint is the gate's fingerprint of the post, and one "approved" action on the dashboard
// channel carries it; the list reloads (the same HTMX endpoint as the Calendar's tab) without the
// row. A viewer sees the row with no control to approve, review or select it, and a direct approve
// POST with the viewer's session is refused and changes nothing. A plain client is refused the
// screen (they approve in the client portal).
import { type Page, type Response } from '@playwright/test';

import { csrfToken, expectLit, go } from '../support/nav';
import { settled } from '../support/settled';
import { expect, test } from '../support/test';

type ReviewPost = {
  post_id: string;
  platform_posts: { id: string; platform: string; account_id: string }[];
  proposed_publish_at: string;
};

type PublishingPost = {
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

/** The approve POST for one post and the list reload its answer triggers (registered before the click). */
function watchApprove(page: Page, workspace: string, postId: string): { approved: Promise<Response>; reloaded: Promise<Response> } {
  const approved = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      new URL(response.url()).pathname === `/workspace/${workspace}/approvals/${postId}/approve/`,
  );
  const reloaded = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      new URL(response.url()).pathname === `/workspace/${workspace}/calendar/publish/approvals/`,
  );
  approved.catch(() => undefined);
  reloaded.catch(() => undefined);
  return { approved, reloaded };
}

test('the owner opens Approvals from the navigation and approves & schedules a post through the gate', async ({
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
    days_ahead: 4,
    hour: 9,
  });

  await as('owner');
  await page.goto(`/workspace/${workspace}/studio/`);
  const href = await go(page, 'approvals');
  expect(href).toBe(`/workspace/${workspace}/approvals/`);
  expect(new URL(page.url()).pathname).toBe(href);
  await expectLit(page, 'approvals');
  // The count of posts waiting is part of the item's name.
  await expect(page.getByTestId('nav-approvals')).toHaveAttribute('aria-label', /^Approvals, \d+ waiting$/);

  const list = page.getByTestId('approvals-list');
  const row = list.getByTestId(`approvals-row-${made.post_id}`);
  await expect(row).toBeVisible();
  await settled(list, 'the Approvals list');
  await axe(page, 'Approvals (owner)');

  const shown = await list.elementHandle();
  const { approved: answered, reloaded } = watchApprove(page, workspace, made.post_id);
  await row.getByTestId('approvals-row-approve-schedule').click();
  const answer = await answered;
  const refusal = answer.status() === 204 ? '' : await answer.text().catch(() => '');
  expect(answer.status(), `Approve & schedule answered ${answer.status()} ${refusal}`).toBe(204);

  const after = await harness.probe<PublishingPost>('publishing_post', { post_id: made.post_id });
  expect(after.platform_posts).toHaveLength(1);
  const pp = after.platform_posts[0];
  expect(pp.id).toBe(made.platform_posts[0].id);
  expect(pp.status).toBe('scheduled');
  expect(sameInstant(pp.scheduled_at, made.proposed_publish_at)).toBe(true);
  expect(sameInstant(pp.approved_publish_at, made.proposed_publish_at)).toBe(true);
  expect(pp.approved_fingerprint).toMatch(/^[0-9a-f]{64}$/);
  expect(pp.approved_fingerprint, 'the gate stamped the fingerprint of this exact post').toBe(pp.fingerprint);
  expect(pp.approved_by).toBe(users.owner.email);
  const approvedActions = after.actions.filter((action) => action.action === 'approved');
  expect(approvedActions).toHaveLength(1);
  expect(approvedActions[0]).toMatchObject({
    channel: 'dashboard',
    user: users.owner.email,
    platform_post_id: pp.id,
    fingerprint: pp.approved_fingerprint,
  });

  // The screen reloads its list without the row once the post is scheduled.
  expect((await reloaded).status(), 'the Approvals list reloaded').toBe(200);
  await expect
    .poll(() => shown!.evaluate((element) => element.isConnected), { message: 'the reload replaced the list' })
    .toBe(false);
  await expect(list).toBeVisible();
  await expect(row).toHaveCount(0);
  await settled(list, 'the reloaded Approvals list');
  await axe(page, 'Approvals after Approve & schedule (owner)');

  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});

test('a viewer sees Approvals read-only, and a direct approve POST is refused', async ({
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
    days_ahead: 4,
    hour: 12,
  });
  const viewer = await harness.fixture<{ email: string }>('workspace_member', { role: 'viewer' });

  await as({ email: viewer.email });
  await page.goto(`/workspace/${workspace}/calendar/`);
  await go(page, 'approvals');
  await expectLit(page, 'approvals');
  const list = page.getByTestId('approvals-list');
  const row = list.getByTestId(`approvals-row-${made.post_id}`);
  await expect(row).toBeVisible();
  await settled(list, 'the Approvals list');
  await axe(page, 'Approvals (viewer)');
  for (const control of [
    'approvals-row-approve-schedule',
    'approvals-row-approve',
    'approvals-row-review',
    'approvals-row-request-changes',
    'approvals-row-select',
  ]) {
    await expect(row.getByTestId(control), `no ${control} for a viewer`).toHaveCount(0);
  }
  await expect(page.getByTestId('approvals-bulk-bar')).toHaveCount(0);

  const refused = await page.request.post(`/workspace/${workspace}/approvals/${made.post_id}/approve/`, {
    form: { schedule: '1' },
    headers: { 'X-CSRFToken': await csrfToken(context), Referer: page.url() },
  });
  expect(refused.status()).toBe(403);
  expect(await refused.text()).not.toContain('CSRF verification failed');

  const after = await harness.probe<PublishingPost>('publishing_post', { post_id: made.post_id });
  expect(after.platform_posts.map((pp) => pp.status)).toEqual(['pending_review']);
  expect(after.platform_posts[0].approved_fingerprint).toBe('');
  expect(after.actions.some((action) => action.action === 'approved')).toBe(false);
});

test('a plain client is refused Approvals', async ({ page, as, axe, harness }) => {
  await as('client');
  const response = await page.goto(`/workspace/${harness.ids.workspace_a}/approvals/`);
  expect(response?.status()).toBe(403);
  await axe(page, 'Approvals refused (client)');
});
