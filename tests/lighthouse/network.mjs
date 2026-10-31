import http from 'node:http';

import { validateBaseURL } from './budgets.mjs';

// A browser route sees only the first URL in a redirect chain. This local proxy
// confines all browser HTTP traffic, including redirect follow-ups, to the harness.
// It streams response bodies unchanged, retaining production compression sizes.
export async function startLocalProxy(origin, blocked, { maxResponseBytes = 10_000_000, timeoutMs = 15000 } = {}) {
  validateBaseURL(origin);
  const server = http.createServer((req, res) => {
    let target;
    try { target = new URL(req.url); } catch { res.writeHead(400).end(); return; }
    if (target.origin !== origin || target.username || target.password) {
      blocked.push(target.origin);
      res.writeHead(403).end('Only the isolated test server is allowed.');
      return;
    }
    const headers = { ...req.headers, host: target.host };
    delete headers['proxy-connection'];
    delete headers['proxy-authorization'];
    const upstream = http.request(target, { method: req.method, headers }, (response) => {
      const redirect = response.headers.location;
      let redirectOrigin;
      try { redirectOrigin = redirect && new URL(redirect, target).origin; }
      catch { redirectOrigin = 'invalid redirect'; }
      if (redirectOrigin && redirectOrigin !== origin) {
        blocked.push(redirectOrigin);
        response.resume();
        res.writeHead(403).end('External redirects are refused.');
        return;
      }
      res.writeHead(response.statusCode || 502, response.headers);
      let size = 0;
      response.on('data', (chunk) => {
        size += chunk.length;
        if (size > maxResponseBytes) {
          blocked.push('response too large');
          response.destroy();
          res.destroy();
        }
      });
      response.pipe(res);
      response.on('error', () => res.destroy());
    });
    const deadline = setTimeout(() => {
      blocked.push('request timed out');
      upstream.destroy(new Error('Local upstream timed out.'));
    }, timeoutMs);
    upstream.on('close', () => clearTimeout(deadline));
    upstream.on('error', () => { if (!res.headersSent) res.writeHead(502); res.end(); });
    req.on('aborted', () => upstream.destroy());
    req.pipe(upstream);
  });
  server.on('connect', (req, socket) => {
    blocked.push(`CONNECT ${req.url}`);
    socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  return {
    url: `http://127.0.0.1:${server.address().port}`,
    close: () => new Promise((resolve) => { server.closeAllConnections(); server.close(resolve); }),
  };
}
