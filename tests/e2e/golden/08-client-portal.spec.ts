// Golden path 8 (docs/specs/01-harness.md): the client signs off in the portal through a magic link;
// that completes the client stage, and nothing is scheduled or published.
//
// A fixture makes a two-stage workspace (internal approval, then the client's) with its owner, a
// client and a LinkedIn account, and a post the owner has already approved internally through the
// real approvals service (acting as the owner in the dashboard), so it waits for the client with the
// gate's fingerprint. The client opens a fresh magic link, presses Continue to portal, opens
// Approvals and presses Approve. In the database: the post is approved, never scheduled or published;
// the internal fingerprint is unchanged; an "approved" action by the client on the portal channel;
// no publish log; the link was used once. The portal session is refused the agency pages.
import { expect, test } from '../support/test';

type Person = { id: string; email: string };

type ClientStagePost = {
  workspace_id: string;
  workspace_name: string;
  owner: Person;
  client: Person;
  account: { id: string; platform: string };
  post_id: string;
  platform_posts: { id: string; status: string; approved_fingerprint: string }[];
};

type PlatformPostRow = {
  id: string;
  platform: string;
  status: string;
  approved_fingerprint: string;
  fingerprint: string;
  approved_by: string | null;
  approved_at: string | null;
  scheduled_at: string | null;
  published_at: string | null;
};

type ActionRow = {
  action: string;
  channel: string;
  user: string | null;
  platform_post_id: string | null;
  fingerprint: string;
  comment: string;
};

type TwoStageState = {
  post: { id: string; proposed_publish_at: string | null; scheduled_at: string | null } | null;
  platform_posts: PlatformPostRow[];
  actions: ActionRow[];
  publish_logs: number;
};

type MagicLinkState = { exists: boolean; is_consumed: boolean; last_used_at: string | null; email: string | null };

type WorkerStatus = { alive: boolean; ran: number; idle_polls: number; error: string; paused: boolean };

/** Everything the client's sign-off must leave alone or leave behind, checked after it and at the end. */
function expectClientStageOnly(state: TwoStageState, made: ClientStagePost) {
  expect(state.platform_posts.map((row) => row.id)).toEqual(made.platform_posts.map((row) => row.id));
  for (const [index, row] of state.platform_posts.entries()) {
    expect(row.status).toBe('approved');
    expect(row.scheduled_at).toBeNull();
    expect(row.published_at).toBeNull();
    // The internal approval's fingerprint is the one that stays, and it still matches the content.
    expect(row.approved_fingerprint).toBe(made.platform_posts[index].approved_fingerprint);
    expect(row.approved_fingerprint).toBe(row.fingerprint);
    expect(row.approved_by).toBe(made.owner.email);
  }
  expect(state.post?.scheduled_at ?? null).toBeNull();
  const approvals = state.actions.filter((action) => action.action === 'approved');
  expect(approvals.map((action) => [action.user, action.channel])).toEqual([
    [made.owner.email, 'dashboard'],
    [made.client.email, 'portal'],
  ]);
  expect(state.actions.some((action) => ['time_approved', 'publish_blocked'].includes(action.action))).toBe(false);
  expect(state.publish_logs).toBe(0);
}

test('a client signs off in the portal through a magic link: approved for the client stage, never scheduled or published', async ({
  page,
  axe,
  harness,
  network,
}) => {
  const since = Date.now() / 1000;
  const made = await harness.fixture<ClientStagePost>('client_stage_post');
  for (const row of made.platform_posts) {
    expect(row.status).toBe('pending_client');
    expect(row.approved_fingerprint).toMatch(/^[0-9a-f]{64}$/);
  }
  const probe = () => harness.probe<TwoStageState>('two_stage_state', { post_id: made.post_id });

  const { url } = await harness.fixture<{ url: string }>('magic_link', {
    email: made.client.email,
    workspace_id: made.workspace_id,
  });
  const token = url.split('/').filter(Boolean).pop()!;

  // The link asks for one press first (mail scanners that open it cannot use it up).
  expect((await page.goto(url))?.status()).toBe(200);
  await axe(page, 'Magic link: continue to the portal');
  expect((await harness.probe<MagicLinkState>('magic_link_state', { token })).is_consumed).toBe(false);
  await page.getByTestId('portal-continue').click();
  await expect(page).toHaveURL(/\/portal\/$/);
  const used = await harness.probe<MagicLinkState>('magic_link_state', { token });
  expect(used).toMatchObject({ exists: true, is_consumed: true, email: made.client.email });
  await axe(page, 'Portal home (client)');

  // Approvals: the post waits for the client.
  await page.getByTestId('portal-nav-approvals').filter({ visible: true }).click();
  await expect(page).toHaveURL(/\/portal\/approvals\/$/);
  const pending = page.getByTestId('portal-approvals-pending');
  const card = pending.getByTestId('portal-card');
  // The workspace is this test's own, so its one post is the only card.
  await expect(card).toHaveCount(1);
  await axe(page, 'Portal approvals, waiting for the client');

  await card.getByTestId('portal-card-approve').click();

  let after: TwoStageState | undefined;
  await expect
    .poll(
      async () => {
        after = await probe();
        return after.platform_posts.every((row) => row.status !== 'pending_client');
      },
      { message: 'the client sign-off is stored', timeout: 15_000 },
    )
    .toBe(true);
  expectClientStageOnly(after!, made);
  // The worker's count of polls that found nothing due, read once the sign-off is stored.
  const atSignOff = await harness.probe<WorkerStatus>('worker');
  expect(atSignOff).toMatchObject({ alive: true, paused: false, error: '' });

  // The list refreshes: nothing waits for the client, and the post is under Decided without Approve.
  await expect(page.getByTestId('portal-approvals-pending')).toHaveCount(0);
  const decided = page.getByTestId('portal-approvals-decided').getByTestId('portal-card');
  await expect(decided).toHaveCount(1);
  await expect(decided.getByTestId('portal-card-approve')).toHaveCount(0);
  await axe(page, 'Portal approvals, signed off');

  // The portal session is for the portal only: the agency pages refuse it.
  const studio = await page.goto(`/workspace/${made.workspace_id}/studio/`);
  expect([403, 404]).toContain(studio?.status());
  await axe(page, 'Agency page refused to the portal session');

  // Still approved and nothing more once the worker has run everything the sign-off made due. Two
  // more idle polls than at the sign-off: the first may have started before the sign-off was stored,
  // the second started after it, so any task the sign-off queued has run by then.
  await expect
    .poll(async () => (await harness.probe<WorkerStatus>('worker')).idle_polls, {
      message: 'the worker runs what the sign-off made due and finds nothing more',
      timeout: 30_000,
    })
    .toBeGreaterThanOrEqual(atSignOff.idle_polls + 2);
  expect(await harness.probe<WorkerStatus>('worker')).toMatchObject({ alive: true, error: '' });
  expectClientStageOnly(await probe(), made);

  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});
