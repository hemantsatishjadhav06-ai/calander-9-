// Golden path 3 (docs/specs/01-harness.md): ask the team for a post from Home.
//
// Every test runs in a workspace of its own (the team_workspace fixture: an owner, an editor and a
// client, Instagram and LinkedIn, the brand profile, verified facts, the agency settings), so nothing
// another test leaves behind can reach its Today card.
//
// The request names Instagram and LinkedIn and a key message. The account manager answers with the
// brief card, which lists both channels and the message; Go ahead starts the post, and the
// in-process worker runs every stage with the faked team. The draft comes back Ready for approval,
// its platform posts pending review, and Home lists it under Today's Waiting for you. An editor can
// ask and go ahead but sees no approve control, and the approve address refuses them. A client is
// refused Home and the team's thread both when signed in through the portal link (the portal
// session's own fence) and with a password (the agency pages' own check for clients).
import type { APIResponse, Page } from '@playwright/test';

import type { Harness } from '../support/harness';
import { until } from '../support/poll';
import { expect, type SessionResult, test } from '../support/test';

type Person = { id: string; email: string };

type TeamWorkspace = {
  workspace_id: string;
  workspace_name: string;
  users: Record<'owner' | 'editor' | 'client', Person>;
};

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

/** A job that will not finish: the wait ends at once and the assertion after it names the state. */
const stopped = (status: string | undefined) => status === 'failed' || status === 'cancelled';

/**
 * POST a form the way the page's own forms do, with the CSRF token the browser holds, and return the
 * answer itself (a redirect is not followed). Each refusal below is paired with a request of the same
 * kind, with the same token, that is taken, so a 403 is the refusal under test and never a CSRF failure.
 */
async function postForm(page: Page, path: string, form: Record<string, string>): Promise<APIResponse> {
  const csrf = (await page.context().cookies()).find((cookie) => cookie.name === 'csrftoken')?.value ?? '';
  expect(csrf, 'the browser holds a CSRF token').toMatch(/\S/);
  return page.request.post(path, {
    form: { ...form, csrfmiddlewaretoken: csrf },
    headers: { 'X-CSRFToken': csrf, Referer: page.url() },
    maxRedirects: 0,
  });
}

const sortedPosts = (posts: HomeRequest['platform_posts']) => [...posts].sort((a, b) => a.platform.localeCompare(b.platform));

const PENDING_REVIEW = [
  { platform: 'instagram', status: 'pending_review' },
  { platform: 'linkedin_company', status: 'pending_review' },
];

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
    await harness.fixture('set_agent_delay', { seconds: 0 });
    const team = await harness.fixture<TeamWorkspace>('team_workspace', {});
    const workspaceId = team.workspace_id;
    const home = `/workspace/${workspaceId}/studio/`;
    const session = await as({ email: team.users[role].email });
    const tag = `${testInfo.project.name}-${role}-${Date.now().toString(36)}`;
    const request = `Post about the Kokapet site visit ${tag} on Instagram and LinkedIn, mention free parking on visit days`;
    const read = () => harness.probe<HomeRequest>('home_request', { workspace_id: workspaceId, body: request });

    await page.goto(home);
    await axe(page, `Home (${role})`);
    const thread = page.getByTestId('home-thread');
    await thread.getByTestId('thread-composer-body').fill(request);
    await thread.getByTestId('thread-composer-send').click();

    // The account manager answers with the brief: both channels and the key message, waiting for Go ahead.
    const asked = await until(
      read,
      (s) => stopped(s.ask?.status) || (s.ask?.status === 'done' && s.reply !== null),
      'the account manager answers with a brief',
    );
    expect(asked.ask?.status).toBe('done');
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
    const started = await until(read, (s) => s.brief !== null || stopped(s.confirm?.status), 'Go ahead starts the post');
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
    expect(sortedPosts(finished.platform_posts)).toEqual(PENDING_REVIEW);

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

    if (role === 'editor') {
      // Nor does the address behind that button take it from an editor. The token is good (a message
      // to the team's thread, sent the same way, is taken); the approve is refused, and the draft
      // still waits for review with its platform posts.
      const thanks = `Thanks, team ${tag}`;
      const taken = await postForm(page, `${home}thread/send/`, { body: thanks });
      expect(taken.status()).toBe(302);
      const thanked = await harness.probe<HomeRequest>('home_request', { workspace_id: workspaceId, body: thanks });
      expect(thanked.message).toMatchObject({ author: session.user.email });

      const approve = await postForm(page, `${home}${finished.brief?.id}/approve/`, { mode: 'proposed' });
      expect(approve.status()).toBe(403);
      const after = await read();
      expect(after.brief).toMatchObject({ status: 'ready', proposed_publish_at: finished.brief?.proposed_publish_at });
      expect(sortedPosts(after.platform_posts)).toEqual(PENDING_REVIEW);
    }

    expect(network.blocked).toEqual([]);
    expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
  });
}

/**
 * The client's message to the team's thread is refused and nothing is stored; then the same request,
 * with the same token, from the workspace's editor is taken and stored.
 */
async function expectThreadRefusedToClient(
  page: Page,
  harness: Harness,
  as: (who: { email: string }) => Promise<SessionResult>,
  team: TeamWorkspace,
  body: string,
) {
  const home = `/workspace/${team.workspace_id}/studio/`;
  const refused = await postForm(page, `${home}thread/send/`, { body, kind: 'question' });
  expect(refused.status()).toBe(403);
  const stored = await harness.probe<HomeRequest>('home_request', { workspace_id: team.workspace_id, body });
  expect(stored.message).toBeNull();

  await as({ email: team.users.editor.email });
  const control = `${body} (from the editor)`;
  const taken = await postForm(page, `${home}thread/send/`, { body: control, kind: 'question' });
  expect(taken.status()).toBe(302);
  const kept = await harness.probe<HomeRequest>('home_request', { workspace_id: team.workspace_id, body: control });
  expect(kept.message).toMatchObject({ author: team.users.editor.email, author_kind: 'staff' });
}

test('a client signed in through the portal link is refused Home and the team thread', async ({
  page,
  harness,
  as,
  axe,
  network,
}, testInfo) => {
  const since = Date.now() / 1000;
  const team = await harness.fixture<TeamWorkspace>('team_workspace', {});
  const home = `/workspace/${team.workspace_id}/studio/`;
  const link = await harness.fixture<{ url: string }>('magic_link', {
    email: team.users.client.email,
    workspace_id: team.workspace_id,
  });

  await page.goto(link.url);
  await axe(page, 'Portal sign-in (client)');
  await page.getByRole('button', { name: 'Continue to portal' }).click();
  await page.waitForURL((url) => url.pathname === '/portal/');
  await axe(page, 'Portal (client)');

  const response = await page.goto(home);
  expect(response?.status()).toBe(403);
  await expect(page.getByTestId('home-thread')).toHaveCount(0);
  await axe(page, 'Home refused (client, portal link)');

  const body = `A client asks the team for a post ${testInfo.project.name}-portal-${Date.now().toString(36)}`;
  await expectThreadRefusedToClient(page, harness, as, team, body);

  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});

test('a client signed in with a password is refused Home and the team thread by the agency pages themselves', async ({
  page,
  harness,
  as,
  axe,
  network,
}, testInfo) => {
  const since = Date.now() / 1000;
  const team = await harness.fixture<TeamWorkspace>('team_workspace', {});
  const home = `/workspace/${team.workspace_id}/studio/`;
  await as({ email: team.users.client.email });

  // A client with a password session lands where clients may look, the calendar, not on Home.
  await page.goto('/');
  await page.waitForURL((url) => url.pathname === `/workspace/${team.workspace_id}/calendar/`);
  await axe(page, 'Calendar (client)');

  // Home refuses them at Home's own address with a 403, not by sending them to the portal.
  const response = await page.goto(home);
  expect(response?.status()).toBe(403);
  expect(new URL(page.url()).pathname).toBe(home);
  await expect(page.getByTestId('home-thread')).toHaveCount(0);
  await axe(page, 'Home refused (client, password)');

  const body = `A client asks the team for a post ${testInfo.project.name}-password-${Date.now().toString(36)}`;
  await expectThreadRefusedToClient(page, harness, as, team, body);

  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});
