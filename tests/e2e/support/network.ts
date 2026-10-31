// The browser side of "nothing leaves the machine": every request whose host is not the e2e server
// is aborted and recorded, unless the test routed it first. Page routes (page.route) and context
// routes installed later take precedence over this one.
//
// Playwright calls a route handler only for the first URL of a redirect chain, so no route, this one
// included, sees where a redirect goes: when the server answers with a 302 to another host, the
// browser follows it for real. Those requests are recorded as `escaped`, and the test fails at its
// end (support/test.ts). A test that needs an outside page (an OAuth authorize URL) therefore routes
// the app's own URL that answers the 302, as routeGoogle in tests/e2e/golden/01-sign-in.spec.ts does.
import type { BrowserContext } from '@playwright/test';

export type NetworkGuard = {
  /** Every aborted request, as scheme://host/path (no query string). */
  blocked: string[];
  /** Every redirect the browser followed to a host other than the server; it was sent, not aborted. */
  escaped: string[];
};

export async function guardNetwork(context: BrowserContext, baseURL: string): Promise<NetworkGuard> {
  const server = new URL(baseURL);
  const allowed = new Set([server.host, `localhost:${server.port}`, `127.0.0.1:${server.port}`]);
  const isServer = (url: URL) => (url.protocol === 'http:' || url.protocol === 'https:') && allowed.has(url.host);
  const guard: NetworkGuard = { blocked: [], escaped: [] };
  await context.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (isServer(url)) {
      await route.fallback();
      return;
    }
    guard.blocked.push(`${url.protocol}//${url.host}${url.pathname}`);
    await route.abort('blockedbyclient');
  });
  context.on('request', (request) => {
    const url = new URL(request.url());
    if (request.redirectedFrom() && !isServer(url)) {
      guard.escaped.push(`${url.protocol}//${url.host}${url.pathname}`);
    }
  });
  return guard;
}
