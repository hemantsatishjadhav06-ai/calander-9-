// The browser side of "nothing leaves the machine": every request whose host is not the e2e server
// is aborted and recorded, unless the test routed it first. Page routes (page.route) and context
// routes installed later take precedence over this one, which is how a test answers the OAuth
// authorize pages with a redirect to the app's callback.
import type { BrowserContext } from '@playwright/test';

export type NetworkGuard = {
  /** Every aborted request, as scheme://host/path (no query string). */
  blocked: string[];
};

export async function guardNetwork(context: BrowserContext, baseURL: string): Promise<NetworkGuard> {
  const server = new URL(baseURL);
  const allowed = new Set([server.host, `localhost:${server.port}`, `127.0.0.1:${server.port}`]);
  const guard: NetworkGuard = { blocked: [] };
  await context.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if ((url.protocol === 'http:' || url.protocol === 'https:') && allowed.has(url.host)) {
      await route.fallback();
      return;
    }
    guard.blocked.push(`${url.protocol}//${url.host}${url.pathname}`);
    await route.abort('blockedbyclient');
  });
  return guard;
}
