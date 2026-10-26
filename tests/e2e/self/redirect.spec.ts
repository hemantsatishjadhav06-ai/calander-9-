// Playwright routes only the first request of a redirect chain, so the guard's route never sees a
// hop the browser makes by following a redirect to another host: that request really goes out. The
// guard lists it in network.blocked all the same, so a test that checks network.blocked fails on it.
// Both servers here are tiny ones on loopback, on ports that are not the e2e server's, so nothing
// leaves the machine; the first is routed on to the network by the test, as an OAuth spec might.
import http from 'node:http';
import type { AddressInfo } from 'node:net';

import { expect, test } from '../support/test';

async function listen(handler: http.RequestListener): Promise<{ server: http.Server; origin: string }> {
  const server = http.createServer(handler);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  return { server, origin: `http://127.0.0.1:${(server.address() as AddressInfo).port}` };
}

test('a redirect hop to another host, which no route sees, is listed as blocked', async ({ page, network }) => {
  const reached: string[] = [];
  const elsewhere = await listen((request, response) => {
    reached.push(request.url ?? '');
    response.writeHead(200, { 'content-type': 'text/html' }).end('<!doctype html><title>Elsewhere</title>');
  });
  const redirector = await listen((_request, response) => {
    response.writeHead(302, { location: `${elsewhere.origin}/after-the-hop?code=e2e` }).end();
  });
  try {
    await page.route(`${redirector.origin}/**`, (route) => route.continue());

    await page.goto(`${redirector.origin}/start`).catch(() => null);

    // The hop was not aborted (it reached the other server), and the guard lists it.
    expect(reached).toEqual(['/after-the-hop?code=e2e']);
    expect(network.blocked).toEqual([`${elsewhere.origin}/after-the-hop`]);
  } finally {
    redirector.server.close();
    elsewhere.server.close();
  }
});
