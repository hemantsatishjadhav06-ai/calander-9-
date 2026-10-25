// Golden path 9 (docs/specs/01-harness.md): a comment arrives in the Inbox; assign it, reply, mark
// it done.
//
// The comment arrives the real way: the test posts a Facebook feed webhook to /webhooks/facebook/,
// signed with HMAC-SHA256 (X-Hub-Signature-256) using the placeholder Facebook app secret that
// config/settings/e2e.py sets, for the seeded Facebook page of workspace A. Then, as the owner and
// as the editor: open the Inbox, open the message, assign it to the manager, send a reply (the
// server's mock transport answers the Facebook comment reply, tests/e2e/server/mocks.py) and set
// the status to Resolved. Each step is checked in the database through the probes in
// tests/e2e/server/steps/g5.py. A client of the workspace is refused the Inbox, the message and a
// direct reply POST, and nothing reaches the platform.
import { createHmac, randomBytes } from 'node:crypto';

import { type BrowserContext, type Page } from '@playwright/test';

import { expect, test } from '../support/test';

/** The placeholder app secret config/settings/e2e.py sets (E2E_FACEBOOK_APP_SECRET); not a credential. */
const FACEBOOK_APP_SECRET = 'e2e-facebook-app-secret';

type InboxReplyRow = {
  id: string;
  status: string;
  body: string;
  author: string | null;
  platform_reply_id: string;
  sent_at: string | null;
};

type InboxState = {
  message: {
    id: string;
    workspace_id: string;
    account_id: string;
    message_type: string;
    status: string;
    body: string;
    sender_name: string;
    assigned_to: string | null;
  } | null;
  replies: InboxReplyRow[];
  /** email -> how many "new inbox message" notifications that person got for this message */
  notifications: Record<string, number>;
};

type PlatformCalls = { calls: { method: string; host: string; url: string }[] };

type Comment = { commentId: string; message: string; sender: string };

function newComment(label: string): Comment {
  const tag = randomBytes(4).toString('hex');
  return {
    commentId: `e2e-${label}-${tag}`,
    message: `Is parking free at the Kokapet site office on Saturday? (${tag})`,
    sender: 'Ravi Kumar',
  };
}

/** Post the comment the way Meta does: a signed `feed` change for the seeded Facebook page. */
async function deliverComment(page: Page, pageId: string, comment: Comment): Promise<void> {
  const postId = `${pageId}_e2e-post-${comment.commentId}`;
  const now = Math.floor(Date.now() / 1000);
  const body = JSON.stringify({
    object: 'page',
    entry: [
      {
        id: pageId,
        time: now,
        changes: [
          {
            field: 'feed',
            value: {
              item: 'comment',
              verb: 'add',
              comment_id: comment.commentId,
              post_id: postId,
              parent_id: postId,
              message: comment.message,
              from: { id: `e2e-fb-user-${comment.commentId}`, name: comment.sender },
              created_time: now,
            },
          },
        ],
      },
    ],
  });
  const signature = `sha256=${createHmac('sha256', FACEBOOK_APP_SECRET).update(body).digest('hex')}`;
  const response = await page.request.post('/webhooks/facebook/', {
    data: body,
    headers: { 'Content-Type': 'application/json', 'X-Hub-Signature-256': signature },
  });
  expect(response.status(), 'the signed webhook is accepted').toBe(200);
}

async function csrfToken(context: BrowserContext): Promise<string> {
  const cookie = (await context.cookies()).find((item) => item.name === 'csrftoken');
  expect(cookie, 'the page set the CSRF cookie').toBeTruthy();
  return cookie!.value;
}

for (const role of ['owner', 'editor'] as const) {
  test(`${role}: a signed Facebook comment arrives; assign it to the manager, reply, and mark it resolved`, async ({
    page,
    as,
    axe,
    harness,
    network,
  }) => {
    const since = Date.now() / 1000;
    const { workspace_a: workspace, accounts, users } = harness.ids;
    const comment = newComment(role);
    const reply = `Yes, parking is free on Saturday. See you at the site office from 10:00. (${comment.commentId})`;
    const probe = () => harness.probe<InboxState>('inbox_message', { comment_id: comment.commentId });

    // The comment arrives through the webhook, as an unread, unassigned comment on the Facebook page.
    await deliverComment(page, accounts.facebook.platform_id, comment);
    const arrived = await probe();
    expect(arrived.message).toMatchObject({
      workspace_id: workspace,
      account_id: accounts.facebook.id,
      message_type: 'comment',
      status: 'unread',
      body: comment.message,
      sender_name: comment.sender,
      assigned_to: null,
    });
    expect(arrived.replies).toEqual([]);
    const messageId = arrived.message!.id;
    const toldOnArrival = arrived.notifications[users.manager.email] ?? 0;

    // The Inbox lists it; opening it shows the message and marks it read.
    await as(role);
    const response = await page.goto(`/workspace/${workspace}/inbox/`);
    expect(response?.status()).toBe(200);
    const row = page.getByTestId(`inbox-row-${messageId}`);
    await expect(row).toBeVisible();
    await axe(page, `Inbox (${role})`);

    // A pointer opens the row (its text bubbles to the row's handler; the stretched button is the keyboard's way in).
    await row.click();
    const panel = page.getByTestId('inbox-detail-panel');
    await expect(panel.getByTestId(`inbox-message-${messageId}`)).toBeVisible();
    await expect.poll(async () => (await probe()).message?.status).toBe('open');
    await axe(page, `Inbox message open (${role})`);

    // Assign it to the manager.
    await panel.getByTestId('inbox-assign-toggle').click();
    const manager = panel.getByTestId(`inbox-assignee-${users.manager.id}`);
    await expect(manager).toBeVisible();
    await axe(page, `Inbox assign menu (${role})`);
    await manager.click();
    await expect.poll(async () => (await probe()).message?.assigned_to).toBe(users.manager.email);
    // The panel is drawn again with the manager marked as the assignee.
    await expect(panel.getByTestId(`inbox-assignee-${users.manager.id}`).getByTestId('inbox-assignee-current')).toHaveCount(1);
    expect((await probe()).notifications[users.manager.email], 'the manager is told about the assignment').toBe(
      toldOnArrival + 1,
    );

    // Send a reply: the platform call is answered by the mock, and the reply is recorded as sent.
    const body = panel.getByTestId('inbox-reply-body');
    await body.fill(reply);
    await panel.getByTestId('inbox-reply-send').click();
    await expect.poll(async () => (await probe()).replies.map((item) => item.status)).toEqual(['sent']);
    const [sent] = (await probe()).replies;
    expect(sent).toMatchObject({
      status: 'sent',
      body: reply,
      author: users[role].email,
      platform_reply_id: `e2e-reply-${comment.commentId}`,
    });
    expect(sent.sent_at).toBeTruthy();
    await expect(panel.getByTestId(`inbox-thread-reply-${sent.id}`)).toBeVisible();
    await expect(body).toHaveValue('');
    const calls = await harness.probe<PlatformCalls>('inbox_platform_calls', { since });
    expect(calls.calls).toEqual([
      expect.objectContaining({ method: 'POST', host: 'graph.facebook.com', url: expect.stringContaining(`/${comment.commentId}/comments`) }),
    ]);
    await axe(page, `Inbox reply sent (${role})`);

    // Mark it done.
    await panel.getByTestId('inbox-status-toggle').click();
    const resolved = panel.getByTestId('inbox-status-resolved');
    await expect(resolved).toBeVisible();
    await axe(page, `Inbox status menu (${role})`);
    await resolved.click();
    await expect.poll(async () => (await probe()).message?.status).toBe('resolved');
    await expect(panel.getByTestId('inbox-status-resolved').getByTestId('inbox-status-current')).toHaveCount(1);
    const done = await probe();
    expect(done.message?.assigned_to).toBe(users.manager.email);
    expect(done.replies).toHaveLength(1);
    await axe(page, `Inbox message resolved (${role})`);

    expect(network.blocked).toEqual([]);
    expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
  });
}

test('a client of the workspace is refused the Inbox, the message and a direct reply', async ({
  page,
  context,
  as,
  axe,
  harness,
  network,
}) => {
  const since = Date.now() / 1000;
  const { workspace_a: workspace, accounts } = harness.ids;
  const comment = newComment('client');
  await deliverComment(page, accounts.facebook.platform_id, comment);
  const arrived = await harness.probe<InboxState>('inbox_message', { comment_id: comment.commentId });
  const messageId = arrived.message!.id;

  await as('client');
  // The client's own landing (the workspace calendar) first: the screen a client does reach.
  const landing = await page.goto('/');
  expect(landing?.status()).toBe(200);
  expect(new URL(page.url()).pathname).toBe(`/workspace/${workspace}/calendar/`);
  await axe(page, 'Landing (client)');

  const inbox = await page.goto(`/workspace/${workspace}/inbox/`);
  expect(inbox?.status()).toBe(403);
  await expect(page.getByTestId(`inbox-row-${messageId}`)).toHaveCount(0);
  await axe(page, 'Inbox refused (client)');

  const detail = await page.request.get(`/workspace/${workspace}/inbox/${messageId}/`);
  expect(detail.status()).toBe(403);
  expect(await detail.text()).not.toContain(comment.message);

  const refused = await page.request.post(`/workspace/${workspace}/inbox/${messageId}/reply/`, {
    form: { body: 'A client must not answer from the team inbox.' },
    headers: { 'X-CSRFToken': await csrfToken(context), Referer: page.url() },
  });
  expect(refused.status()).toBe(403);
  // Refused by the permission, not by a missing CSRF token.
  expect(await refused.text()).not.toContain('CSRF verification failed');

  const after = await harness.probe<InboxState>('inbox_message', { comment_id: comment.commentId });
  expect(after.message?.status).toBe('unread');
  expect(after.replies).toEqual([]);
  expect((await harness.probe<PlatformCalls>('inbox_platform_calls', { since })).calls).toEqual([]);
  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});
