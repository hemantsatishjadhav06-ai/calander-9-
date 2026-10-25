// Golden path 2 (docs/specs/01-harness.md): onboarding. There is no onboarding wizard yet (Phase 3
// builds it), so this test walks today's equivalent, page by page, as the owner of a fresh workspace
// (its own organisation, no accounts, no lead): the brand page, connecting one account (X: the hop to
// its authorize page is answered with the redirect to the app's callback that X would give, and the
// server's mock answers the token exchange and the profile), Set up's Use me as lead, and a first
// idea on Home with Go ahead. Each step is checked in the database. Rewritten against the wizard in
// Phase 3.
import { expect, test } from '../support/test';

type FreshWorkspace = {
  workspace_id: string;
  organisation_id: string;
  workspace_name: string;
  owner: { id: string; email: string };
};

type OnboardingState = {
  brand_name: string | null;
  accounts: { platform: string; platform_id: string; status: string; name: string }[];
  lead: string | null;
  briefs: { id: string; status: string; origin: string; platforms: string[]; requested_by: string | null }[];
};

type HomeRequest = {
  ask: { status: string; awaiting_confirmation: boolean; accounts: string[] } | null;
  reply: { id: string; action: string } | null;
  confirm: { kind: string; facts_confirmed: boolean } | null;
  brief: { id: string; status: string; origin: string; platforms: string[]; requested_by: string | null } | null;
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

test("owner onboards a fresh workspace on today's pages, the equivalent of the onboarding wizard: brand, one account, the lead, a first post under way", async ({
  page,
  as,
  axe,
  harness,
  network,
  baseURL,
}, testInfo) => {
  test.setTimeout(150_000);
  const since = Date.now() / 1000;
  await harness.fixture('set_agent_delay', { seconds: 0 });
  const fresh = await harness.fixture<FreshWorkspace>('onboarding_workspace', {});
  const workspaceId = fresh.workspace_id;
  const read = () => harness.probe<OnboardingState>('onboarding_state', { workspace_id: workspaceId });
  expect(await read()).toMatchObject({ accounts: [], lead: null, briefs: [] });
  const session = await as({ email: fresh.owner.email });
  const tag = `${testInfo.project.name}-${Date.now().toString(36)}`;
  // Every request the browser even starts, redirect hops included (routes never see those), stays here.
  const server = new URL(String(baseURL)).host;
  const offMachine: string[] = [];
  page.context().on('request', (request) => {
    const url = new URL(request.url());
    if ((url.protocol === 'http:' || url.protocol === 'https:') && url.host !== server) {
      offMachine.push(`${url.origin}${url.pathname}`);
    }
  });

  // 1. Brand: the owner names the brand and saves it.
  const brandName = `Lakeview Homes ${tag}`;
  await page.goto(`/workspace/${workspaceId}/studio/brand/`);
  await axe(page, 'Brand profile (fresh workspace)');
  const brandField = page.getByTestId('brand-name-field').getByRole('textbox');
  await brandField.fill(brandName);
  await page.getByTestId('brand-save').click();
  await until(read, (s) => s.brand_name === brandName, 'the brand name is saved');
  await expect(brandField).toHaveValue(brandName);
  await axe(page, 'Brand profile, saved');

  // 2. Connect one account: Set up's Connect, then X. The app answers Connect with a redirect to X's
  //    authorize page; X would answer with a redirect to the app's callback carrying the state the
  //    app signed, and the server's mock answers the token exchange and the profile.
  await page.goto(`/workspace/${workspaceId}/studio/setup/`);
  await axe(page, 'Set up (fresh workspace)');
  await expect(page.getByTestId('setup-row-accounts')).toHaveAttribute('data-setup-state', 'todo');
  await page.getByTestId('setup-action-accounts').click();
  await page.waitForURL((url) => url.pathname === `/social-accounts/${workspaceId}/connect/`);
  await axe(page, 'Connect a platform');

  // Playwright routes only the first request of a redirect chain: the browser would follow the app's
  // redirect to x.com unrouted and try to leave the machine. So the hop is answered where the browser
  // would leave: the app's own response is read (its redirect not followed) and checked, and the
  // browser gets what X's authorize page answers instead, a redirect to the app's callback.
  const authorizations: URL[] = [];
  await page.route(`${baseURL}/social-accounts/${workspaceId}/connect/`, async (route) => {
    if (route.request().method() !== 'POST') {
      await route.fallback();
      return;
    }
    const response = await route.fetch({ maxRedirects: 0 });
    const asked = new URL(response.headers()['location'] ?? '', baseURL);
    authorizations.push(asked);
    const state = asked.searchParams.get('state') ?? '';
    await route.fulfill({
      response,
      headers: {
        ...response.headers(),
        location: `${baseURL}/social-accounts/callback/x/?code=e2e&state=${encodeURIComponent(state)}`,
      },
    });
  });
  await page.getByTestId('connect-platform-x').click();
  await page.waitForURL((url) => url.pathname === `/workspace/${workspaceId}/calendar/`);
  expect(authorizations).toHaveLength(1);
  expect(`${authorizations[0]?.origin}${authorizations[0]?.pathname}`).toBe('https://x.com/i/oauth2/authorize');
  expect(authorizations[0]?.searchParams.get('redirect_uri')).toBe(`${baseURL}/social-accounts/callback/x/`);
  expect(authorizations[0]?.searchParams.get('state')).not.toBe('');
  expect(authorizations[0]?.searchParams.get('code_challenge_method')).toBe('S256');
  expect((await read()).accounts).toEqual([
    { platform: 'x', platform_id: '4400000001', status: 'connected', name: 'Neopolis E2E' },
  ]);
  await axe(page, 'Calendar after connecting X');

  // 3. Choose the approver: Set up's Use me as lead.
  await page.goto(`/workspace/${workspaceId}/studio/setup/`);
  await expect(page.getByTestId('setup-row-accounts')).toHaveAttribute('data-setup-state', 'done');
  await expect(page.getByTestId('setup-row-approvers')).toHaveAttribute('data-setup-state', 'todo');
  await page.getByTestId('setup-action-approvers').click();
  await until(read, (s) => s.lead === session.user.email, 'the owner is the lead');
  await expect(page.getByTestId('setup-row-approvers')).toHaveAttribute('data-setup-state', 'done');
  await axe(page, 'Set up with the lead chosen');

  // 4. The first post: an idea on Home, the brief card, Go ahead. The team is slowed a little so the
  //    post is seen queued or at work, not already finished.
  await page.goto(`/workspace/${workspaceId}/studio/`);
  await axe(page, 'Home (fresh workspace)');
  const idea = `A post about the first open house at Lakeview ${tag} this Saturday`;
  const request = () => harness.probe<HomeRequest>('home_request', { workspace_id: workspaceId, body: idea });
  const thread = page.getByTestId('home-thread');
  await thread.getByTestId('thread-composer-body').fill(idea);
  await thread.getByTestId('thread-composer-send').click();
  const asked = await until(request, (s) => s.ask?.status === 'done' && s.reply !== null, 'the account manager answers with a brief');
  expect(asked.ask).toMatchObject({ awaiting_confirmation: true, accounts: ['x'] });
  const card = thread.getByTestId(`thread-message-${asked.reply?.id}`).getByTestId('thread-brief-card');
  await expect(card).toBeVisible({ timeout: 20_000 });
  await axe(page, 'Home with the first brief');

  await harness.fixture('set_agent_delay', { seconds: 2 });
  try {
    await card.getByTestId('thread-brief-go-ahead').click();
    const started = await until(request, (s) => s.brief !== null, 'Go ahead starts the first post');
    expect(started.confirm).toMatchObject({ kind: 'confirm_brief', facts_confirmed: true });
    expect(started.brief).toMatchObject({ origin: 'chat', platforms: ['x'], requested_by: session.user.email });
    expect(['queued', 'working']).toContain(started.brief?.status);
    const onboarded = await read();
    expect(onboarded.briefs).toHaveLength(1);
    expect(['queued', 'working']).toContain(onboarded.briefs[0]?.status);
    await expect(card.getByTestId('thread-brief-go-ahead')).toHaveCount(0);
    await axe(page, 'Home with the first post under way');
  } finally {
    await harness.fixture('set_agent_delay', { seconds: 0 });
  }

  expect(offMachine).toEqual([]);
  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});
