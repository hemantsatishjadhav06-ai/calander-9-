// Golden path 6 (docs/specs/01-harness.md): request changes with feedback; the revision appears and
// the earlier approval is withdrawn.
//
// On today's UI an approved post is not revisable after a single-stage approval, so this runs on a
// two-stage workspace (internal approval, then the client's) made by a fixture: its owner, a client,
// a LinkedIn account, and a post the team made with the real queue and worker (faked agents), ready
// for approval. The owner approves it on the Approvals list: it goes to the client with the gate's
// fingerprint. The owner then asks for changes from the same row (Review, Request changes, the
// comment, Send back for changes): the fingerprint and the approver are cleared and the feedback is
// stored. On the post page the owner sends it to the team with notes; the worker makes revision 2
// with those notes, back at Ready for approval, with no approval on it, and the page says Revision 2.
import { type Page } from '@playwright/test';

import { expect, test } from '../support/test';

type Person = { id: string; email: string };

type TwoStageBrief = {
  workspace_id: string;
  owner: Person;
  client: Person;
  account: { id: string; platform: string };
  brief_id: string;
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
  brief: { id: string; status: string; stage: string; revision: number; feedback: string; post_id: string | null } | null;
  post: { id: string; proposed_publish_at: string | null; scheduled_at: string | null } | null;
  platform_posts: PlatformPostRow[];
  actions: ActionRow[];
  publish_logs: number;
};

const FEEDBACK = 'Say the site visits run every Saturday, and drop the word luxury.';
const NOTES = 'Lead with the Saturday site visits and mention the free parking.';

/** Poll the post's rows until `ready` says so (the worker runs the team in the background). */
async function stateWhen(
  probe: () => Promise<TwoStageState>,
  ready: (state: TwoStageState) => boolean,
  message: string,
  timeout = 60_000,
): Promise<TwoStageState> {
  let last: TwoStageState | undefined;
  await expect
    .poll(
      async () => {
        last = await probe();
        return ready(last);
      },
      { message, timeout, intervals: [250, 500, 1000] },
    )
    .toBe(true);
  return last!;
}

const statuses = (state: TwoStageState) => state.platform_posts.map((row) => row.status);
const allAre = (state: TwoStageState, status: string) =>
  state.platform_posts.length > 0 && state.platform_posts.every((row) => row.status === status);

async function openApprovals(page: Page, workspace: string) {
  const response = await page.goto(`/workspace/${workspace}/calendar/?mode=list&tab=approvals`);
  expect(response?.status()).toBe(200);
  const row = page.getByTestId('approvals-row');
  await expect(row).toHaveCount(1);
  return row;
}

test('the owner sends an internally approved post back with feedback, and the team makes revision 2 with no approval on it', async ({
  page,
  as,
  axe,
  harness,
  network,
}) => {
  test.setTimeout(180_000);
  const since = Date.now() / 1000;
  const world = await harness.fixture<TwoStageBrief>('two_stage_brief');
  const workspace = world.workspace_id;
  const probe = () => harness.probe<TwoStageState>('two_stage_state', { brief_id: world.brief_id });

  // The team (faked agents, real queue and worker) makes the post and sends it for approval.
  const made = await stateWhen(
    probe,
    (state) => state.brief?.status === 'ready' && allAre(state, 'pending_review'),
    'the team makes the post and sends it for approval',
  );
  expect(made.brief?.revision).toBe(1);
  expect(made.platform_posts).toHaveLength(1);
  expect(made.platform_posts[0].platform).toBe(world.account.platform);
  expect(made.platform_posts[0].approved_fingerprint).toBe('');

  await as({ email: world.owner.email });

  // 1. The owner approves it on the Approvals list: the internal stage, with the fingerprint stamped.
  let row = await openApprovals(page, workspace);
  await axe(page, 'Approvals list, waiting for review (owner, two-stage)');
  await row.getByTestId('approvals-row-approve').click();
  const withClient = await stateWhen(probe, (state) => allAre(state, 'pending_client'), 'the post goes to the client');
  const [approvedRow] = withClient.platform_posts;
  expect(approvedRow.approved_fingerprint).toMatch(/^[0-9a-f]{64}$/);
  expect(approvedRow.approved_fingerprint).toBe(approvedRow.fingerprint);
  expect(approvedRow.approved_by).toBe(world.owner.email);
  expect(approvedRow.scheduled_at).toBeNull();
  const internal = withClient.actions.filter((action) => action.action === 'approved');
  expect(internal).toHaveLength(1);
  expect(internal[0]).toMatchObject({
    channel: 'dashboard',
    user: world.owner.email,
    platform_post_id: approvedRow.id,
    fingerprint: approvedRow.approved_fingerprint,
  });

  // The post page while the client has it: nothing to send back to the team from here.
  const detailUrl = `/workspace/${workspace}/studio/${world.brief_id}/`;
  expect((await page.goto(detailUrl))?.status()).toBe(200);
  await expect(page.getByTestId('studio-detail-revision')).toBeVisible();
  await expect(page.getByTestId('studio-revise-form')).toHaveCount(0);
  await axe(page, 'Post page, with the client (owner)');

  // 2. From the same Approvals row: Review, Request changes, the feedback, Send back for changes.
  row = await openApprovals(page, workspace);
  await axe(page, 'Approvals list, with the client (owner)');
  await row.getByTestId('approvals-row-review').click();
  await row.getByTestId('approvals-row-request-changes').click();
  const comment = row.getByTestId('approvals-row-review-comment');
  await expect(comment).toBeVisible();
  await comment.fill(FEEDBACK);
  await axe(page, 'Approvals list, review panel open (owner)');
  await row.getByTestId('approvals-row-send-back').click();

  const sentBack = await stateWhen(
    probe,
    (state) => allAre(state, 'changes_requested'),
    'the post is sent back for changes',
  );
  for (const platformPost of sentBack.platform_posts) {
    expect(platformPost.approved_fingerprint).toBe('');
    expect(platformPost.approved_by).toBeNull();
    expect(platformPost.approved_at).toBeNull();
  }
  const requested = sentBack.actions.filter((action) => action.action === 'changes_requested');
  expect(requested).toHaveLength(1);
  expect(requested[0]).toMatchObject({ channel: 'dashboard', user: world.owner.email, comment: FEEDBACK });

  // 3. The post page: send it to the team with notes.
  expect((await page.goto(detailUrl))?.status()).toBe(200);
  await axe(page, 'Post page, changes requested (owner)');
  const revise = page.getByTestId('studio-revise-form');
  await expect(revise).toBeVisible();
  await revise.getByRole('textbox', { name: 'What should change?' }).fill(NOTES);

  // Slow the team a little (each agent turn takes 2 s), so the page that shows them at work stays
  // put while axe reads it; it reloads itself once the team is done.
  await harness.fixture('set_agent_delay', { seconds: 2 });
  try {
    await page.getByTestId('studio-revise-send').click();
    // The form posts and comes back to the post page, which now shows the team at work on revision 2.
    await expect(page.getByTestId('studio-detail-revision')).toHaveText(/Revision 2\b/);
    await expect(page).toHaveURL(detailUrl);
    await axe(page, 'Post page, the team at work on revision 2 (owner)');

    const revised = await stateWhen(
      probe,
      (state) => state.brief?.revision === 2 && state.brief.status === 'ready' && allAre(state, 'pending_review'),
      'the team makes revision 2 and sends it for approval',
      120_000,
    );
    expect(revised.brief?.feedback).toBe(NOTES);
    expect(revised.platform_posts.map((row) => row.id)).toEqual([approvedRow.id]);
    for (const platformPost of revised.platform_posts) {
      expect(platformPost.approved_fingerprint).toBe('');
      expect(platformPost.approved_by).toBeNull();
      expect(platformPost.approved_at).toBeNull();
      expect(platformPost.scheduled_at).toBeNull();
      expect(platformPost.published_at).toBeNull();
    }
    // The only approval ever given is the withdrawn internal one; nothing went out.
    expect(revised.actions.filter((action) => action.action === 'approved')).toHaveLength(1);
    expect(revised.publish_logs).toBe(0);
    expect(statuses(revised)).toEqual(['pending_review']);
  } finally {
    await harness.fixture('set_agent_delay', { seconds: 0 });
  }

  // The page refreshes itself when the team is done: Revision 2, ready for approval again.
  await expect(page.getByTestId('studio-revise-form')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('studio-detail-revision')).toHaveText(/Revision 2\b/);
  await axe(page, 'Post page, revision 2 ready for approval (owner)');

  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});
