const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { test } = require('node:test');
const { installMockNavigationBarrier } = require('../e2e/support/mock-navigation.cjs');

const ORIGIN = 'http://127.0.0.1:8150';
const turn = () => new Promise((resolve) => setImmediate(resolve));

class PageDouble extends EventEmitter {
  constructor() {
    super();
    this.frameURL = `${ORIGIN}/start`;
    this.frame = { url: () => this.frameURL };
    this.handlers = [];
    this.gotoCalls = [];
  }
  mainFrame() { return this.frame; }
  async route(pattern, handler, options) { this.handlers.push({ pattern, handler, options }); }
  async unroute(pattern, handler) {
    this.handlers = this.handlers.filter((entry) => entry.pattern !== pattern || (handler && entry.handler !== handler));
  }
  async goto(url) {
    this.gotoCalls.push(url);
    if (this.gotoError) throw this.gotoError;
    return { url };
  }
  commit(url = `${ORIGIN}/mock`) {
    this.frameURL = url;
    this.emit('framenavigated', this.frame);
  }
  async dispatch({ method = 'POST', navigation = true, frame = this.frame, url = `${ORIGIN}/mock`, fulfillError } = {}) {
    const request = { method: () => method, isNavigationRequest: () => navigation, frame: () => frame, url: () => url,
      failure: () => ({ errorText: 'synthetic connection failure' }) };
    const route = { request: () => request, fulfill: async (options) => {
      route.fulfilled = options;
      if (fulfillError) throw fulfillError;
    }, fallback: async () => { route.fellBack = true; } };
    await this.handlers[0].handler(route, request);
    return { request, route };
  }
}

async function setup({ timeoutMs = 250, contentType = 'text/html' } = {}) {
  const page = new PageDouble();
  const barrier = installMockNavigationBarrier(page, ORIGIN, { timeoutMs });
  const handler = async (route) => route.fulfill({ status: 200, contentType, body: '<title>Mock provider</title>' });
  await page.route('**/mock', handler, { times: 1 });
  return { page, barrier, handler };
}

test('callback navigation cannot overtake the mocked POST document commit', async () => {
  const { page, barrier } = await setup();
  await page.dispatch();
  const callback = page.goto('/callback');
  await turn();
  assert.deepEqual(page.gotoCalls, [], 'response headers alone do not mean the document committed');
  page.commit();
  assert.deepEqual(await callback, { url: '/callback' });
  assert.deepEqual(page.gotoCalls, ['/callback']);
  await barrier.dispose();
});

test('a commit already delivered does not add a sleep or require another event', async () => {
  const { page, barrier } = await setup();
  await page.dispatch();
  page.commit();
  assert.deepEqual(await page.goto('/callback'), { url: '/callback' });
  await barrier.dispose();
});

test('a failed mock POST remains a failure when it happens before callback navigation', async () => {
  const { page, barrier } = await setup();
  const { request } = await page.dispatch();
  page.emit('requestfailed', request);
  await assert.rejects(page.goto('/callback'), /synthetic connection failure/);
  assert.deepEqual(page.gotoCalls, [], 'the callback is never attempted after the failed POST');
  await barrier.dispose();
});

test('a mock POST that never commits times out and is never retried', async () => {
  const { page, barrier } = await setup({ timeoutMs: 20 });
  await page.dispatch();
  await assert.rejects(page.goto('/callback'), /did not commit within 20 ms/);
  assert.deepEqual(page.gotoCalls, []);
  await barrier.dispose();
});

test('GET, XHR, subframe and foreign-origin requests keep normal navigation semantics', async () => {
  for (const request of [{ method: 'GET' }, { navigation: false }, { frame: {} }, { url: 'https://outside.invalid/mock' }]) {
    const { page, barrier } = await setup();
    await page.dispatch(request);
    assert.deepEqual(await page.goto('/callback'), { url: '/callback' });
    await barrier.dispose();
  }
  const { page, barrier } = await setup({ contentType: 'application/json' });
  await page.dispatch();
  assert.deepEqual(await page.goto('/callback'), { url: '/callback' });
  await barrier.dispose();
});

test('normal goto errors propagate unchanged with exactly one attempt', async () => {
  const { page, barrier } = await setup();
  const error = new Error('ordinary navigation failed');
  page.gotoError = error;
  await assert.rejects(page.goto('/broken'), (actual) => actual === error);
  assert.deepEqual(page.gotoCalls, ['/broken']);
  await barrier.dispose();
});

test('fulfill with default options retains the native API behavior', async () => {
  const page = new PageDouble();
  const barrier = installMockNavigationBarrier(page, ORIGIN);
  await page.route('**/mock', (route) => route.fulfill());
  await page.dispatch();
  assert.deepEqual(await page.goto('/callback'), { url: '/callback' });
  await barrier.dispose();
});

test('native fulfillment errors propagate and prevent the callback from being attempted', async () => {
  const { page, barrier } = await setup();
  const error = new Error('native fulfillment failed');
  await assert.rejects(page.dispatch({ fulfillError: error }), (actual) => actual === error);
  await assert.rejects(page.goto('/callback'), (actual) => actual === error);
  assert.deepEqual(page.gotoCalls, []);
  await barrier.dispose();
});

test('route handler arguments, options and unroute by original handler remain intact', async () => {
  const { page, barrier, handler } = await setup();
  assert.deepEqual(page.handlers[0].options, { times: 1 });
  await page.unroute('**/mock', handler);
  assert.deepEqual(page.handlers, []);
  await barrier.dispose();
});

test('teardown observes an unconsumed mock failure and restores page methods and listeners', async () => {
  const page = new PageDouble();
  const original = { goto: page.goto, route: page.route, unroute: page.unroute };
  const barrier = installMockNavigationBarrier(page, ORIGIN, { timeoutMs: 250 });
  await page.route('**/mock', (route) => route.fulfill({ contentType: 'text/html', body: 'mock' }));
  const { request } = await page.dispatch();
  page.emit('requestfailed', request);
  await assert.rejects(barrier.dispose(), /synthetic connection failure/);
  assert.equal(page.goto, original.goto);
  assert.equal(page.route, original.route);
  assert.equal(page.unroute, original.unroute);
  assert.equal(page.listenerCount('framenavigated'), 0);
  assert.equal(page.listenerCount('requestfailed'), 0);
});
