// Golden path 3 (docs/specs/01-harness.md): ask the team for a post from Home.
//
// The request names Instagram and LinkedIn and a key message. The account manager answers with the
// brief card, which lists both channels and the message; Go ahead starts the post, and the
// in-process worker runs every stage with the faked team. The draft comes back Ready for approval,
// its platform posts pending review, and Home lists it under Today's Waiting for you. An editor can
// ask and go ahead but sees no approve control; a client, signed in through the portal link, is
// refused Home and cannot write in the team's thread.
import { expect, test } from '../support/test';

type HomeRequest = {
  message: { id: string; author: string | null; author_kind: string } | null;
  ask: {
    id: string;
    status: string;
    awaiting_confirmation: boolean;
    topic: string;
    key_message: string;
    channels: string[];
    accounts: string[];
  } | null;
  reply: { id: string; action: string; action_status: string } | null;
  confirm: { id: string; status: string; kind: string; facts_confirmed: boolean } | null;
  brief: {
    id: string;
    status: string;
    stage: string;
    origin: string;
    platforms: string[];
    requested_by: string | null;
    proposed_publish_at: string | null;
  } | null;
  platform_posts: { platform: string; status: string }[];
};

/** Read until `ready` holds (or the timeout ends the test), and return what was read last. */
async function until<T>(read: () => Promise<T>, ready: (value: T) => boolean, message: string, timeout = 60_000): Promise<T> {
  let value: T | undefined;
  await expect
    .poll(
      async () => {
        value = await read();
        return ready(value);
      },
      { message, timeout, intervals: [250, 500, 1_000] },
    )
    .toBe(true);
  return value as T;
}

for (const role of ['owner', 'editor'] as const) {
  test(`${role} asks the team for a post on Home, goes ahead on the brief, and the draft waits for review`, async ({
    page,
    as,
    axe,
    harness,
    network,
  }, testInfo) => {
    test.setTimeout(180_000);
    const since = Date.now() / 1000;
    const workspaceId = harness.ids.workspace_a;
    const home = `/workspace/${workspaceId}/studio/`;
    await harness.fixture('set_agent_delay', { seconds: 0 });
    // Today shows the first three drafts waiting; drafts earlier tests left must not push this one off.
    await harness.fixture('discard_open_briefs', { workspace_id: workspaceId });
    const session = await as(role);
    const tag = `${testInfo.project.name}-${role}-${Date.now().toString(36)}`;
    const request = `Post about the Kokapet site visit ${tag} on Instagram and LinkedIn, mention free parking on visit days`;
    const read = () => harness.probe<HomeRequest>('home_request', { workspace_id: workspaceId, body: request });

    await page.goto(home);
    await axe(page, `Home (${role})`);
    const thread = page.getByTestId('home-thread');
    await thread.getByTestId('thread-composer-body').fill(request);
    await thread.getByTestId('thread-composer-send').click();

    // The account manager answers with the brief: both channels and the key message, waiting for Go ahead.
    const asked = await until(read, (s) => s.ask?.status === 'done' && s.reply !== null, 'the account manager answers with a brief');
    expect(asked.message).toMatchObject({ author: session.user.email, author_kind: 'staff' });
    expect(asked.ask).toMatchObject({
      awaiting_confirmation: true,
      key_message: 'Free parking on visit days',
      accounts: ['instagram', 'linkedin_company'],
    });
    expect(asked.ask?.channels).toEqual(expect.arrayContaining(['instagram', 'linkedin_company']));
    expect(asked.reply).toMatchObject({ action: 'new_post' });

    const card = thread.getByTestId(`thread-message-${asked.reply?.id}`).getByTestId('thread-brief-card');
    await expect(card).toBeVisible({ timeout: 20_000 });
    await expect(card.getByTestId('thread-brief-channels')).toContainText('Instagram');
    await expect(card.getByTestId('thread-brief-channels')).toContainText('LinkedIn');
    await expect(card.getByTestId('thread-brief-key-message')).toHaveText('Free parking on visit days');
    await axe(page, `Home with the brief card (${role})`);

    // Go ahead: the brief and its facts are confirmed, and the team starts the post.
    await card.getByTestId('thread-brief-go-ahead').click();
    const started = await until(read, (s) => s.brief !== null, 'Go ahead starts the post');
    expect(started.confirm).toMatchObject({ kind: 'confirm_brief', facts_confirmed: true });
    expect(started.brief).toMatchObject({
      origin: 'chat',
      requested_by: session.user.email,
      platforms: ['instagram', 'linkedin_company'],
    });
    await expect(card.getByTestId('thread-brief-go-ahead')).toHaveCount(0);

    // The worker runs every stage with the faked team; the draft comes back for review, not scheduled.
    const finished = await until(
      read,
      (s) => s.brief?.status === 'ready' || s.brief?.status === 'failed',
      'the worker finishes the draft',
      120_000,
    );
    expect(finished.brief?.status).toBe('ready');
    expect(finished.brief?.proposed_publish_at).not.toBeNull();
    expect([...finished.platform_posts].sort((a, b) => a.platform.localeCompare(b.platform))).toEqual([
      { platform: 'instagram', status: 'pending_review' },
      { platform: 'linkedin_company', status: 'pending_review' },
    ]);

    // Home: Today lists the draft under Waiting for you; only an approver is offered Approve & schedule.
    await page.goto(home);
    const today = page.getByTestId('home-today');
    const item = today.getByTestId('home-today-waiting').getByTestId(`home-today-post-${finished.brief?.id}`);
    await expect(item).toBeVisible();
    await expect(item.getByTestId('home-today-review')).toBeVisible();
    if (role === 'owner') {
      await expect(item.getByTestId('home-today-approve-schedule')).toBeVisible();
    } else {
      await expect(today.getByTestId('home-today-approve-schedule')).toHaveCount(0);
    }
    await axe(page, `Home with the draft waiting (${role})`);

    expect(network.blocked).toEqual([]);
    expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
  });
}

test('a client signed in through the portal link is refused Home and the team thread', async ({
  page,
  harness,
  axe,
  network,
}, testInfo) => {
  const since = Date.now() / 1000;
  const workspaceId = harness.ids.workspace_a;
  const link = await harness.fixture<{ url: string }>('magic_link', {
    email: harness.ids.users.client.email,
    workspace_id: workspaceId,
  });

  await page.goto(link.url);
  await axe(page, 'Portal sign-in (client)');
  await page.getByRole('button', { name: 'Continue to portal' }).click();
  await page.waitForURL((url) => url.pathname === '/portal/');
  await axe(page, 'Portal (client)');

  const response = await page.goto(`/workspace/${workspaceId}/studio/`);
  expect(response?.status()).toBe(403);
  await expect(page.getByTestId('home-thread')).toHaveCount(0);
  await axe(page, 'Home refused (client)');

  // Writing in the team's thread is refused too, with a valid CSRF token, and nothing is stored.
  const body = `A client asks the team for a post ${testInfo.project.name}-${Date.now().toString(36)}`;
  const csrf = (await page.context().cookies()).find((cookie) => cookie.name === 'csrftoken')?.value ?? '';
  expect(csrf).not.toBe('');
  const posted = await page.request.post(`/workspace/${workspaceId}/studio/thread/send/`, {
    form: { body, kind: 'question', csrfmiddlewaretoken: csrf },
    headers: { 'X-CSRFToken': csrf, Referer: page.url() },
  });
  expect(posted.status()).toBe(403);
  const stored = await harness.probe<HomeRequest>('home_request', { workspace_id: workspaceId, body });
  expect(stored.message).toBeNull();

  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});
