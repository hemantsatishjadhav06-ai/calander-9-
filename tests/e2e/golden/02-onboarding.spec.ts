// Golden path 2 (docs/specs/01-harness.md): onboarding. There is no onboarding wizard yet (Phase 3
// builds it), so this test walks today's equivalent, page by page, as the owner of a fresh workspace
// (its own organisation, no accounts, no lead): the brand page, connecting one account (X: the app's
// redirect to X's authorize page is read and checked, and the browser goes to the app's callback as X
// would send it; the server's mock answers the token exchange and the profile), Set up's Use me as
// lead, and a first idea on Home with Go ahead. Each step is checked in the database. Rewritten
// against the wizard in Phase 3.
import { until } from '../support/poll';
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
  confirm: { status: string; kind: string; facts_confirmed: boolean } | null;
  brief: { id: string; status: string; origin: string; platforms: string[]; requested_by: string | null } | null;
};

/** A job that will not finish: the wait ends at once and the assertion after it names the state. */
const stopped = (status: string | undefined) => status === 'failed' || status === 'cancelled';

// The team is slowed for Go ahead below. A teardown hook runs even when the test times out (a
// `finally` in the test body would not), so the shared server never keeps the delay.
test.afterEach(async ({ harness }) => {
  await harness.fixture('set_agent_delay', { seconds: 0 });
});

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

  // 1. Brand: the owner names the brand and saves it. The save answers with a redirect to the brand
  //    page, and the page it loads shows the saved name.
  const brandName = `Lakeview Homes ${tag}`;
  const brandPath = `/workspace/${workspaceId}/studio/brand/`;
  await page.goto(brandPath);
  await axe(page, 'Brand profile (fresh workspace)');
  const brandField = page.getByRole('textbox', { name: 'Brand name' });
  await brandField.fill(brandName);
  const saved = page.waitForResponse((r) => r.request().method() === 'POST' && new URL(r.url()).pathname === brandPath);
  const reloaded = page.waitForEvent('framenavigated', (frame) => frame === page.mainFrame());
  await page.getByTestId('brand-save').click();
  const savedResponse = await saved;
  expect(savedResponse.status()).toBe(302);
  expect(new URL(savedResponse.headers()['location'] ?? '', baseURL).pathname).toBe(brandPath);
  await reloaded;
  await page.waitForLoadState('load');
  expect((await read()).brand_name).toBe(brandName);
  await expect(brandField).toHaveValue(brandName);
  await axe(page, 'Brand profile, saved');

  // 2. Connect one account: Set up's Connect, then X.
  await page.goto(`/workspace/${workspaceId}/studio/setup/`);
  await axe(page, 'Set up (fresh workspace)');
  await expect(page.getByTestId('setup-row-accounts')).toHaveAttribute('data-setup-state', 'todo');
  await page.getByTestId('setup-action-accounts').click();
  const connectPath = `/social-accounts/${workspaceId}/connect/`;
  await page.waitForURL((url) => url.pathname === connectPath);
  await axe(page, 'Connect a platform');

  // The app answers Connect with a redirect to X's authorize page. A browser following it would leave
  // the machine, and no route sees a redirect hop (the network guard lists it as blocked). WebKit
  // also refuses to fulfil a request with a 3xx. So the app's own answer is read here, unfollowed,
  // and checked, and the browser is given a plain page in its place. route.fetch goes through the
  // browser context's own request context, so any cookie the app set is kept.
  const authorizations: URL[] = [];
  await page.route(`${baseURL}${connectPath}`, async (route) => {
    if (route.request().method() !== 'POST') {
      await route.fallback();
      return;
    }
    const response = await route.fetch({ maxRedirects: 0 });
    authorizations.push(new URL(response.headers()['location'] ?? '', baseURL));
    await route.fulfill({
      status: 200,
      contentType: 'text/html',
      body: '<!doctype html><html lang="en"><title>On to X</title></html>',
    });
  });
  const answered = page.waitForResponse((r) => r.request().method() === 'POST' && new URL(r.url()).pathname === connectPath);
  await page.getByTestId('connect-platform-x').click();
  expect((await answered).status()).toBe(200);
  expect(authorizations).toHaveLength(1);
  const authorize = authorizations[0] as URL;
  expect(`${authorize.origin}${authorize.pathname}`).toBe('https://x.com/i/oauth2/authorize');
  expect(authorize.searchParams.get('redirect_uri')).toBe(`${baseURL}/social-accounts/callback/x/`);
  expect(authorize.searchParams.get('state')).toMatch(/\S/);
  expect(authorize.searchParams.get('code_challenge_method')).toBe('S256');

  // X sends the browser back to the app's callback with a code and the state the app signed.
  const state = authorize.searchParams.get('state') ?? '';
  await page.goto(`/social-accounts/callback/x/?code=e2e&state=${encodeURIComponent(state)}`);
  await page.waitForURL((url) => url.pathname === `/workspace/${workspaceId}/calendar/`);
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
  const asked = await until(
    request,
    (s) => stopped(s.ask?.status) || (s.ask?.status === 'done' && s.reply !== null),
    'the account manager answers with a brief',
  );
  expect(asked.ask?.status).toBe('done');
  expect(asked.ask).toMatchObject({ awaiting_confirmation: true, accounts: ['x'] });
  const card = thread.getByTestId(`thread-message-${asked.reply?.id}`).getByTestId('thread-brief-card');
  await expect(card).toBeVisible({ timeout: 20_000 });
  await axe(page, 'Home with the first brief');

  await harness.fixture('set_agent_delay', { seconds: 2 });
  await card.getByTestId('thread-brief-go-ahead').click();
  const started = await until(request, (s) => s.brief !== null || stopped(s.confirm?.status), 'Go ahead starts the first post');
  expect(started.confirm).toMatchObject({ kind: 'confirm_brief', facts_confirmed: true });
  expect(started.brief).toMatchObject({ origin: 'chat', platforms: ['x'], requested_by: session.user.email });
  expect(['queued', 'working']).toContain(started.brief?.status);
  const onboarded = await read();
  expect(onboarded.briefs).toHaveLength(1);
  expect(['queued', 'working']).toContain(onboarded.briefs[0]?.status);
  await expect(card.getByTestId('thread-brief-go-ahead')).toHaveCount(0);
  await axe(page, 'Home with the first post under way');

  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});
