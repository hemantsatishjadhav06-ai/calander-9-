// Nothing leaves the machine from the browser either: every request to a host other than the e2e
// server is aborted, unless the test routed it first (the OAuth authorize pages), and the server's
// own guard has refused nothing.
import { expect, test } from '../support/test';

test('a navigation to a host other than the server is aborted', async ({ page, network, browserName }) => {
  const failure = await page.goto('https://outside.e2e.invalid/landing?ref=e2e').then(
    () => null,
    (error: Error) => error,
  );

  // Each engine words an aborted navigation its own way (WebKit reports a cancellation), so the
  // check is that it failed and that the guard was the one that stopped it.
  expect(failure).toBeInstanceOf(Error);
  if (browserName === 'chromium') {
    expect(failure?.message).toMatch(/ERR_BLOCKED_BY_CLIENT/);
  }
  expect(network.blocked).toContain('https://outside.e2e.invalid/landing');
});

test("a page's request for an outside asset is aborted", async ({ page, network }) => {
  await page.setContent('<!doctype html><title>Asset</title><img src="https://cdn.e2e.invalid/pixel.png" alt="">');

  await expect.poll(() => network.blocked).toContain('https://cdn.e2e.invalid/pixel.png');
});

test('a route the test installs for an authorize page is answered instead', async ({ page, network }) => {
  await page.route('https://accounts.google.com/**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/html',
      body: '<!doctype html><html lang="en"><title>Routed</title><h1>Routed by the test</h1></html>',
    }),
  );

  await page.goto('https://accounts.google.com/o/oauth2/v2/auth?state=e2e');

  await expect(page.getByRole('heading', { name: 'Routed by the test' })).toBeVisible();
  expect(network.blocked).toEqual([]);
});

test('the server answers the harness ping with the seeded ids', async ({ harness, request }) => {
  expect(harness.ids.workspace_a).toBe('00000000-0000-4000-8000-00000000000a');
  expect(harness.ids.workspace_b).toBe('00000000-0000-4000-8000-00000000000b');

  const ping = await request.get('/__e2e__/ping');
  expect(ping.status()).toBe(200);
  expect(await ping.json()).toMatchObject({ ok: true, ids: { workspace_a: harness.ids.workspace_a } });
});

test("the server's socket guard and provider mock have refused nothing", async ({ harness }) => {
  const refused = await harness.probe<{ hosts: string[] }>('refused_network');

  expect(refused.hosts).toEqual([]);
});
