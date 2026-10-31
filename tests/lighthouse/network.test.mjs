import assert from 'node:assert/strict';
import http from 'node:http';
import test from 'node:test';
import { gzipSync } from 'node:zlib';

import { startLocalProxy } from './network.mjs';

async function listen(server) {
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  return `http://127.0.0.1:${server.address().port}`;
}

function get(proxy, target, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = http.get(proxy, { path: target, headers }, (res) => {
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('error', reject);
      res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(chunks), headers: res.headers, encoding: res.headers['content-encoding'] }));
    });
    req.on('error', reject);
  });
}

test('proxy streams exact compressed bytes and blocks foreign requests and redirect destinations', async () => {
  const body = gzipSync('function hello() { return "test"; }');
  let outsideHits = 0;
  const outside = http.createServer((_req, res) => { outsideHits++; res.end('must not be reached'); });
  const outsideOrigin = await listen(outside);
  let receivedCookie;
  const upstream = http.createServer((req, res) => {
    receivedCookie = req.headers.cookie;
    if (req.url === '/redirect') { res.writeHead(302, { Location: `${outsideOrigin}/secret` }).end(); return; }
    if (req.url === '/relative') { res.writeHead(302, { Location: '/script.js' }).end(); return; }
    if (req.url === '/invalid') { res.writeHead(302, { Location: 'http://[' }).end(); return; }
    res.writeHead(200, { 'Content-Encoding': 'gzip', 'Content-Length': body.length, 'Content-Security-Policy': "script-src 'self'", 'Cache-Control': 'public, max-age=3600' });
    res.end(body);
  });
  const origin = await listen(upstream);
  const blocked = [];
  const proxy = await startLocalProxy(origin, blocked);
  try {
    const ok = await get(proxy.url, `${origin}/script.js`, { Cookie: 'sessionid=local-test-only' });
    assert.equal(ok.status, 200);
    assert.equal(ok.encoding, 'gzip');
    assert.deepEqual(ok.body, body);
    assert.equal(receivedCookie, 'sessionid=local-test-only');
    assert.equal(ok.headers['content-security-policy'], "script-src 'self'");
    assert.equal(ok.headers['cache-control'], 'public, max-age=3600');
    assert.equal((await get(proxy.url, `${outsideOrigin}/script.js`)).status, 403);
    assert.equal((await get(proxy.url, `${origin}/redirect`)).status, 403);
    assert.equal((await get(proxy.url, `${origin}/relative`)).status, 302);
    assert.equal((await get(proxy.url, `${origin}/invalid`)).status, 403);
    assert.equal((await get(proxy.url, origin.replace('http://', 'http://user:pass@'))).status, 403);
    assert.equal(outsideHits, 0);
    assert.deepEqual(blocked, [outsideOrigin, outsideOrigin, 'invalid redirect', origin]);
    const connectStatus = await new Promise((resolve, reject) => {
      const req = http.request(proxy.url, { method: 'CONNECT', path: 'outside.invalid:443' });
      req.on('connect', (response, socket) => { socket.destroy(); resolve(response.statusCode); });
      req.on('error', reject);
      req.end();
    });
    assert.equal(connectStatus, 403);
  } finally {
    await proxy.close();
    await new Promise((resolve) => upstream.close(resolve));
    await new Promise((resolve) => outside.close(resolve));
  }
});

test('proxy bounds response size and total request duration', async () => {
  const upstream = http.createServer((req, res) => {
    if (req.url === '/stall') return;
    res.end('more than sixteen bytes in this script');
  });
  const origin = await listen(upstream);
  const blocked = [];
  const proxy = await startLocalProxy(origin, blocked, { maxResponseBytes: 16 });
  const timed = await startLocalProxy(origin, blocked, { timeoutMs: 100 });
  try {
    await assert.rejects(get(proxy.url, `${origin}/big`), /aborted|socket hang up/);
    assert.equal((await get(timed.url, `${origin}/stall`)).status, 502);
    assert.ok(blocked.includes('response too large'));
    assert.ok(blocked.includes('request timed out'));
  } finally {
    await proxy.close();
    await timed.close();
    upstream.closeAllConnections();
    await new Promise((resolve) => upstream.close(resolve));
  }
});
