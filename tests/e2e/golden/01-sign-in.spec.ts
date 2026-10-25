// Golden path 1: sign in with email, then with Google, and land on Home.
//
// The login form is the real one (rate limited: reset_login_limits first). Google is answered in the
// browser: the app's redirect to Google's authorize page is replaced by the redirect Google would send
// back, to the app's callback with the state the app sent (see routeGoogle), and the server side of
// the exchange returns the profile the test registered for that code (tests/e2e/server/mocks.py). The
// browser never asks any host but the server. The outcome is read from the database: whose session it
// is, and which account and workspace a Google sign-in left behind.
import type { Page } from '@playwright/test';

import type { Harness } from '../support/harness';
import { expect, test } from '../support/test';

type Sessions = { count: number; cookie_name: string };
type SessionUser = { exists: boolean; user: { id: string; email: string } | null };
type GoogleProfile = { code: string; sub: string; email: string };
type Member = { id: string; email: string; role: string };
type Account = {
  users: number;
  id: string;
  email: string;
  name: string;
  tos_accepted: boolean;
  google_uids: string[];
  workspaces: { id: string; name: string; role: string }[];
  organisations: { id: string; role: string; timezone: string }[];
  sessions: number;
};
type GoogleRoute = { authorize: URL[]; hosts: Set<string> };

const LOGIN = '/accounts/login/';
const CALLBACK = '/accounts/google/login/callback/';
/** Below this width the sidebar, and the account menu in it, sits in a drawer behind the menu button. */
const DRAWER_BELOW = 1024;

test.beforeEach(async ({ harness }) => {
  await harness.fixture('reset_login_limits');
});

async function fillLogin(page: Page, email: string, password: string): Promise<void> {
  await page.getByTestId('login-email').getByRole('textbox').fill(email);
  await page.getByTestId('login-password').getByRole('textbox').fill(password);
  await page.getByTestId('login-submit').click();
}

/** Whose session the browser holds, read from the session table; `user` is null when nobody is signed in. */
async function browserSession(page: Page, harness: Harness, cookieName: string): Promise<SessionUser> {
  const key = (await page.context().cookies()).find((cookie) => cookie.name === cookieName)?.value;
  return key ? harness.probe<SessionUser>('session_user', { key }) : { exists: false, user: null };
}

/**
 * Answer "Sign in with Google" the way Google would: straight back to the callback with `code` and
 * the state the app sent.
 *
 * Playwright calls a route handler only for the first URL of a redirect chain, so a route on
 * accounts.google.com never sees the app's 302 there, and the browser would follow it to the real
 * host. The route is on the app's own POST instead: it is sent as is, the 302 it answers is read
 * (Google's authorize URL, with the state), and the browser receives the callback redirect in its
 * place, with the cookies the app set. Every host the browser asks for is recorded, redirects
 * included, so a test can show that nothing but the server was reached.
 */
async function routeGoogle(page: Page, code: string, baseURL: string): Promise<GoogleRoute> {
  const seen: GoogleRoute = { authorize: [], hosts: new Set() };
  page.on('request', (request) => seen.hosts.add(new URL(request.url()).host));
  await page.route(
    (url) => url.pathname === '/accounts/google/login/',
    async (route) => {
      const response = await route.fetch({ maxRedirects: 0 });
      const authorize = new URL(response.headers()['location'] ?? '', baseURL);
      seen.authorize.push(authorize);
      const callback = new URL(CALLBACK, baseURL);
      callback.searchParams.set('code', code);
      callback.searchParams.set('state', authorize.searchParams.get('state') ?? '');
      await route.fulfill({ response, headers: { ...response.headers(), location: callback.toString() } });
    },
  );
  return seen;
}

/** The app sent the browser to Google's authorize page for this site's callback, and no other host was asked. */
function expectOnlyTheServer(seen: GoogleRoute, baseURL: string): void {
  expect(seen.authorize.map((url) => `${url.origin}${url.pathname}`)).toEqual([
    'https://accounts.google.com/o/oauth2/v2/auth',
  ]);
  expect(seen.authorize[0].searchParams.get('redirect_uri')).toBe(new URL(CALLBACK, baseURL).toString());
  expect([...seen.hosts]).toEqual([new URL(baseURL).host]);
}

test('a wrong password stays on the login page with a message and no session', async ({ page, harness, axe }) => {
  const email = harness.ids.users.owner.email;
  const before = await harness.probe<Sessions>('auth_sessions', { email });

  await page.goto(LOGIN);
  await axe(page, 'Sign in');
  await fillLogin(page, email, `${harness.ids.password}-wrong`);

  await expect(page.getByTestId('login-errors').getByRole('alert')).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(LOGIN);
  await axe(page, 'Sign in (wrong password)');
  expect((await browserSession(page, harness, before.cookie_name)).user).toBeNull();
  expect((await harness.probe<Sessions>('auth_sessions', { email })).count).toBe(before.count);
});

for (const role of ['owner', 'editor'] as const) {
  test(`the ${role} signs in with email and lands on Home of workspace A`, async ({ page, harness, axe }) => {
    const { email, id } = harness.ids.users[role];
    const home = `/workspace/${harness.ids.workspace_a}/studio/`;
    const before = await harness.probe<Sessions>('auth_sessions', { email });

    await page.goto(LOGIN);
    await fillLogin(page, email, harness.ids.password);
    await page.waitForURL((url) => url.pathname === home);

    await expect(page.getByRole('region', { name: 'Today' })).toBeVisible();
    await axe(page, `Home (${role}, after sign-in)`);
    expect(await browserSession(page, harness, before.cookie_name)).toEqual({ exists: true, user: { id, email } });
    expect((await harness.probe<Sessions>('auth_sessions', { email })).count).toBe(before.count + 1);
  });
}

test('signing out from the account menu ends the session', async ({ page, harness, as, axe }) => {
  const session = await as('owner');
  const home = `/workspace/${harness.ids.workspace_a}/studio/`;
  const owner = await harness.probe<Account>('user_account', { email: harness.ids.users.owner.email });

  await page.goto(home);
  if ((page.viewportSize()?.width ?? 0) < DRAWER_BELOW) {
    await page.getByRole('button', { name: 'Toggle menu' }).click();
  }
  // The account menu's button is named by the person it belongs to.
  await page.getByRole('button', { name: owner.name }).click();
  await axe(page, 'Account menu');
  await page.getByTestId('account-sign-out').click();
  await page.waitForURL((url) => url.pathname === LOGIN);

  expect(await harness.probe<SessionUser>('session_user', { key: session.cookie.value })).toEqual({
    exists: false,
    user: null,
  });
  await page.goto(home);
  expect(new URL(page.url()).pathname).toBe(LOGIN);
});

test('a new Google user accepts the terms and lands on Home of their own new workspace', async ({
  page,
  harness,
  axe,
  network,
  baseURL,
}, testInfo) => {
  const since = Date.now() / 1000;
  const email = `google-new-${testInfo.project.name}-${Date.now()}@e2e.test`;
  const google = await harness.fixture<GoogleProfile>('google_profile', { email, name: 'Gia Google' });
  const seen = await routeGoogle(page, google.code, String(baseURL));

  await page.goto(LOGIN);
  await page.getByTestId('social-login-google').click();
  await page.waitForURL((url) => url.pathname === '/accounts/accept-terms/');

  // Signed in with a new account, but the terms come first.
  const signedUp = await harness.probe<Account>('user_account', { email });
  expect(signedUp).toMatchObject({ users: 1, tos_accepted: false, google_uids: [google.sub], sessions: 1 });
  await axe(page, 'Accept the terms');

  await page.getByTestId('accept-terms-agree').check();
  await page.getByTestId('accept-terms-continue').click();
  await page.waitForURL(/\/workspace\/[0-9a-f-]{36}\/studio\/$/);

  const account = await harness.probe<Account>('user_account', { email });
  expect(account).toMatchObject({ users: 1, tos_accepted: true, name: 'Gia Google', google_uids: [google.sub] });
  expect(account.workspaces).toHaveLength(1);
  const [workspace] = account.workspaces;
  expect(workspace.role).toBe('owner');
  expect([harness.ids.workspace_a, harness.ids.workspace_b]).not.toContain(workspace.id);
  // The new organisation takes the browser's timezone (the login page sends it).
  expect(account.organisations).toEqual([{ id: expect.any(String), role: 'owner', timezone: harness.ids.timezone }]);
  expect(new URL(page.url()).pathname).toBe(`/workspace/${workspace.id}/studio/`);
  await expect(page.getByRole('region', { name: 'Today' })).toBeVisible();
  await axe(page, 'Home (new Google user)');

  const sessions = await harness.probe<Sessions>('auth_sessions', { email });
  expect(sessions.count).toBe(1);
  expect((await browserSession(page, harness, sessions.cookie_name)).user?.id).toBe(account.id);
  expectOnlyTheServer(seen, String(baseURL));
  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});

test('an existing email signs in with Google straight to Home of workspace A', async ({
  page,
  harness,
  axe,
  network,
  baseURL,
}) => {
  const since = Date.now() / 1000;
  const member = await harness.fixture<Member>('member_of_a', { role: 'editor' });
  const google = await harness.fixture<GoogleProfile>('google_profile', { email: member.email, name: 'Mo Member' });
  const seen = await routeGoogle(page, google.code, String(baseURL));
  const home = `/workspace/${harness.ids.workspace_a}/studio/`;

  await page.goto(LOGIN);
  await axe(page, 'Sign in (Google button)');
  await page.getByTestId('social-login-google').click();
  await page.waitForURL((url) => url.pathname === home);

  await expect(page.getByRole('region', { name: 'Today' })).toBeVisible();
  await axe(page, 'Home (existing person, Google)');
  // The same account, now linked to Google; no new account and no workspace of its own.
  const account = await harness.probe<Account>('user_account', { email: member.email });
  expect(account).toMatchObject({ users: 1, id: member.id, tos_accepted: true, google_uids: [google.sub] });
  expect(account.workspaces).toEqual([
    { id: harness.ids.workspace_a, name: harness.ids.workspace_names.a, role: 'editor' },
  ]);

  const sessions = await harness.probe<Sessions>('auth_sessions', { email: member.email });
  expect(sessions.count).toBe(1);
  expect((await browserSession(page, harness, sessions.cookie_name)).user?.id).toBe(member.id);
  expectOnlyTheServer(seen, String(baseURL));
  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});
