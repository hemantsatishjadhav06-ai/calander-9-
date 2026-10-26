// Phase 1's missing role variants. The existing invariant golden paths stay unchanged.
// Each action is driven through the real screen and checked against the canonical database probe.
import { settled } from '../support/settled';
import { expect, test } from '../support/test';

type ReviewPost = {
  post_id: string;
  platform_posts: { id: string }[];
  proposed_publish_at: string;
  local: { date: string; time: string };
};

type PostState = {
  brief?: { id: string; status: string; revision: number; feedback: string; post_id: string | null } | null;
  platform_posts: {
    id: string;
    status: string;
    scheduled_at: string | null;
    published_at: string | null;
    approved_fingerprint: string;
    fingerprint: string;
    approved_by: string | null;
    approved_at: string | null;
    approved_publish_at: string | null;
  }[];
  actions: {
    action: string;
    channel: string;
    user: string | null;
    platform_post_id: string | null;
    fingerprint: string;
    comment: string;
  }[];
  publish_logs?: number;
};

test('path 5: a manager approves and schedules the exact post and time from the Approvals list', async ({
  page, as, axe, harness, network,
}) => {
  const since = Date.now() / 1000;
  const workspace = harness.ids.workspace_a;
  const made = await harness.fixture<ReviewPost>('publishing_review_post', {
    author: 'editor', accounts: ['linkedin_company'], days_ahead: 4, hour: 14,
  });
  await as('manager');
  expect((await page.goto(`/workspace/${workspace}/calendar/?mode=list&tab=approvals`))?.status()).toBe(200);
  const list = page.getByTestId('approvals-list');
  const row = list.getByTestId(`approvals-row-${made.post_id}`);
  await expect(row).toBeVisible();
  await settled(list, 'manager Approvals list');
  await axe(page, 'Approvals list (manager)');

  const answer = page.waitForResponse((response) =>
    response.request().method() === 'POST' &&
    new URL(response.url()).pathname === `/workspace/${workspace}/approvals/${made.post_id}/approve/`,
  );
  await row.getByTestId('approvals-row-approve-schedule').click();
  expect((await answer).status()).toBe(204);
  const state = await harness.probe<PostState>('publishing_post', { post_id: made.post_id });
  expect(state.platform_posts).toHaveLength(1);
  const [post] = state.platform_posts;
  expect(post.id).toBe(made.platform_posts[0].id);
  expect(post.status).toBe('scheduled');
  expect(new Date(post.scheduled_at!).getTime()).toBe(new Date(made.proposed_publish_at).getTime());
  expect(new Date(post.approved_publish_at!).getTime()).toBe(new Date(made.proposed_publish_at).getTime());
  expect(post.approved_by).toBe(harness.ids.users.manager.email);
  expect(post.approved_fingerprint).toMatch(/^[0-9a-f]{64}$/);
  expect(post.approved_fingerprint).toBe(post.fingerprint);
  expect(state.actions.filter((action) => action.action === 'approved')).toEqual([
    expect.objectContaining({
      channel: 'dashboard', user: harness.ids.users.manager.email,
      platform_post_id: post.id, fingerprint: post.approved_fingerprint,
    }),
  ]);

  await page.goto(`/workspace/${workspace}/calendar/?mode=calendar&view=week&date=${made.local.date}`);
  const cell = page.getByTestId(`calendar-week-cell-${made.local.date}-${made.local.time.replace(':', '')}`);
  await expect(cell.getByTestId(`calendar-chip-${post.id}`)).toBeVisible();
  await settled(page.getByTestId('calendar-week-grid'), 'manager Calendar week');
  await axe(page, 'Calendar after manager approval');
  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});

test('path 6: a client requests changes in the portal, withdrawing approval before the team returns revision 2', async ({
  page, context, as, axe, harness, network,
}) => {
  test.setTimeout(180_000);
  const since = Date.now() / 1000;
  const feedback = 'Lead with the Saturday site visit and mention free parking.';
  const world = await harness.fixture<{
    workspace_id: string; brief_id: string; owner: { email: string }; client: { email: string };
  }>('two_stage_brief');
  const read = () => harness.probe<PostState>('two_stage_state', { brief_id: world.brief_id });
  await expect.poll(async () => {
    const state = await read();
    return state.brief?.status === 'ready' && state.platform_posts.length === 1 &&
      state.platform_posts[0].status === 'pending_review';
  }, { timeout: 60_000, message: 'the team sends the first version for internal review' }).toBe(true);
  const initial = await read();
  const postId = initial.brief!.post_id!;
  const workspace = world.workspace_id;
  await as({ email: world.owner.email });
  expect((await page.goto(`/workspace/${workspace}/calendar/?mode=list&tab=approvals`))?.status()).toBe(200);
  const row = page.getByTestId(`approvals-row-${postId}`);
  await expect(row).toBeVisible();
  await axe(page, 'Internal approval before client changes');
  const approved = page.waitForResponse((response) =>
    response.request().method() === 'POST' &&
    new URL(response.url()).pathname === `/workspace/${workspace}/approvals/${postId}/approve/`,
  );
  await row.getByTestId('approvals-row-approve').click();
  expect((await approved).status()).toBe(204);
  const waiting = await read();
  expect(waiting.platform_posts[0]).toMatchObject({ status: 'pending_client', approved_by: world.owner.email });
  expect(waiting.platform_posts[0].approved_fingerprint).toMatch(/^[0-9a-f]{64}$/);
  expect(waiting.platform_posts[0].approved_fingerprint).toBe(waiting.platform_posts[0].fingerprint);

  await context.clearCookies();
  const { url } = await harness.fixture<{ url: string }>('magic_link', {
    email: world.client.email, workspace_id: workspace,
  });
  expect((await page.goto(url))?.status()).toBe(200);
  await axe(page, 'Magic link before requesting changes');
  await page.getByTestId('portal-continue').click();
  await expect(page).toHaveURL(/\/portal\/$/);
  await axe(page, 'Client home before requesting changes');
  await page.getByTestId('portal-nav-approvals').filter({ visible: true }).click();
  await expect(page).toHaveURL(/\/portal\/approvals\/$/);
  const card = page.getByTestId('portal-approvals-pending').getByTestId('portal-card');
  await expect(card).toHaveCount(1);
  await axe(page, 'Client approvals before requesting changes');
  await expect(card.getByTestId('portal-card-request-changes')).toBeVisible();
  await card.getByTestId('portal-card-request-changes').click();
  await card.getByTestId('portal-card-comment').fill(feedback);
  await axe(page, 'Client change request form');
  const sent = page.waitForResponse((response) =>
    response.request().method() === 'POST' &&
    new URL(response.url()).pathname === `/portal/approvals/${postId}/ask/`,
  );
  await card.getByTestId('portal-card-send-changes').click();
  const response = await sent;
  expect(response.status()).toBe(200);
  expect(await response.text()).toContain(feedback);

  const withdrawn = await read();
  expect(withdrawn.actions.filter((action) => action.action === 'changes_requested')).toEqual([
    expect.objectContaining({ channel: 'portal', user: world.client.email, comment: feedback }),
  ]);
  for (const post of withdrawn.platform_posts) {
    expect(post.approved_fingerprint).toBe('');
    expect(post.approved_by).toBeNull();
    expect(post.approved_at).toBeNull();
    expect(post.approved_publish_at).toBeNull();
    expect(post.scheduled_at).toBeNull();
    expect(post.published_at).toBeNull();
  }

  await expect.poll(async () => {
    const state = await read();
    return state.brief?.revision === 2 && state.brief.status === 'ready' &&
      state.platform_posts.length === 1 && state.platform_posts[0].status === 'pending_review';
  }, { timeout: 90_000, message: 'the real worker returns the client-requested revision for internal review' }).toBe(true);
  const revised = await read();
  expect(revised.brief!.feedback).toContain(feedback);
  expect(revised.platform_posts.map((post) => post.id)).toEqual(initial.platform_posts.map((post) => post.id));
  expect(revised.platform_posts[0]).toMatchObject({
    status: 'pending_review', approved_fingerprint: '', approved_by: null, approved_at: null,
    scheduled_at: null, published_at: null, approved_publish_at: null,
  });
  expect(revised.actions.filter((action) => action.action === 'approved')).toHaveLength(1);
  expect(revised.publish_logs).toBe(0);

  // The new version is visible to the agency for a new internal decision, not approved by the client.
  await context.clearCookies();
  await as({ email: world.owner.email });
  await page.goto(`/workspace/${workspace}/studio/${world.brief_id}/`);
  await expect(page.getByTestId('studio-detail-revision')).toHaveText(/Revision 2\b/);
  await expect(page.getByTestId('studio-detail-notes')).toContainText(feedback);
  await expect(page.getByTestId('studio-revise-form')).toBeVisible();
  await axe(page, 'Client-requested revision returned for internal review');
  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});
