// The browser side of "nothing leaves the machine": every request whose host is not the e2e server
// is aborted and recorded, unless the test routed it first. Page routes (page.route) and context
// routes installed later take precedence over this one, which is how a test answers an outside page
// it opens itself.
//
// Playwright routes only the first request of a redirect chain. A hop the browser makes by following
// a redirect (the app's 302 to an OAuth authorize page) reaches no route, so it cannot be aborted or
// answered: it really goes out. The guard records such a hop to another host in `blocked` as well, so
// a test that checks `network.blocked` fails on it. A test answers the request that would redirect
// instead (tests/e2e/README.md, "Network").
import type { BrowserContext } from '@playwright/test';

export type NetworkGuard = {
  /**
   * Every request to another host, as scheme://host/path (no query string): the ones the guard
   * aborted, and any redirect hop to another host the browser started (no route sees those).
   */
  blocked: string[];
};

export async function guardNetwork(context: BrowserContext, baseURL: string): Promise<NetworkGuard> {
  const server = new URL(baseURL);
  const allowed = new Set([server.host, `localhost:${server.port}`, `127.0.0.1:${server.port}`]);
  const guard: NetworkGuard = { blocked: [] };
  const isOutside = (url: URL) => !((url.protocol === 'http:' || url.protocol === 'https:') && allowed.has(url.host));
  await context.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (!isOutside(url)) {
      await route.fallback();
      return;
    }
    guard.blocked.push(`${url.protocol}//${url.host}${url.pathname}`);
    await route.abort('blockedbyclient');
  });
  context.on('request', (request) => {
    if (request.redirectedFrom() === null) {
      return;
    }
    const url = new URL(request.url());
    if ((url.protocol === 'http:' || url.protocol === 'https:') && isOutside(url)) {
      guard.blocked.push(`${url.protocol}//${url.host}${url.pathname}`);
    }
  });
  return guard;
}
