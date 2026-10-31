// WebKit can deliver a fulfilled form response before committing its document. A subsequent
// explicit goto must wait for that mock document, or the old commit can cancel the new navigation.
// Only local, mocked HTML POST documents are serialized. Real navigation and network guards stay
// untouched; no request is retried and every failure or missing commit remains an error.
exports.installMockNavigationBarrier = function installMockNavigationBarrier(page, baseURL, { timeoutMs = 10_000 } = {}) {
  const origin = new URL(baseURL).origin;
  const original = { route: page.route, unroute: page.unroute, goto: page.goto };
  const handlers = new Map();
  const pending = new Set();
  const withoutHash = (value) => { const url = new URL(value); url.hash = ''; return url.href; };
  const header = (headers, name) => Object.entries(headers || {}).find(([key]) => key.toLowerCase() === name)?.[1];

  function observe(request) {
    const record = { state: 'pending' };
    let resolve, reject;
    record.promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    // Keep early failures for goto/teardown while preventing an unhandled rejection between them.
    record.promise.catch(() => {});
    const cleanup = () => {
      clearTimeout(timer);
      page.off('framenavigated', committed);
      page.off('requestfailed', failed);
    };
    const settle = (error) => {
      if (record.state !== 'pending') return;
      record.state = error ? 'failed' : 'committed';
      cleanup();
      if (error) reject(error);
      else { pending.delete(record); resolve(); }
    };
    const committed = (frame) => {
      if (frame === page.mainFrame() && withoutHash(frame.url()) === withoutHash(request.url())) settle();
    };
    const failed = (candidate) => {
      if (candidate === request) settle(new Error(`Mocked POST navigation failed: ${request.failure()?.errorText || 'unknown failure'}`));
    };
    const timer = setTimeout(() => settle(new Error(
      `Mocked POST document did not commit within ${timeoutMs} ms: ${new URL(request.url()).pathname}`,
    )), timeoutMs);
    record.fail = settle;
    record.cleanup = cleanup;
    pending.add(record);
    page.on('framenavigated', committed);
    page.on('requestfailed', failed);
    return record;
  }

  function wrapRoute(route) {
    return new Proxy(route, {
      get(target, key) {
        if (key === 'fulfill') return async (options = {}) => {
          const request = target.request();
          const status = options.status ?? options.response?.status() ?? 200;
          const contentType = options.contentType || header(options.headers, 'content-type') || header(options.response?.headers(), 'content-type') || '';
          const eligible = request.method() === 'POST' && request.isNavigationRequest() && request.frame() === page.mainFrame()
            && new URL(request.url()).origin === origin && status >= 200 && status < 300 && status !== 204 && status !== 205
            && /^(text\/html|application\/xhtml\+xml)(;|$)/i.test(contentType);
          const record = eligible ? observe(request) : null;
          try { return await target.fulfill(options); }
          catch (error) { record?.fail(error); throw error; }
        };
        const value = Reflect.get(target, key, target);
        return typeof value === 'function' ? value.bind(target) : value;
      },
    });
  }

  page.route = async (pattern, handler, options) => {
    if (!handlers.has(handler)) handlers.set(handler, (route, request) => handler(wrapRoute(route), request));
    return original.route.call(page, pattern, handlers.get(handler), options);
  };
  page.unroute = async (pattern, handler) => original.unroute.call(page, pattern, handler ? handlers.get(handler) || handler : undefined);
  page.goto = async (...args) => {
    const waiting = [...pending];
    try { await Promise.all(waiting.map((record) => record.promise)); }
    finally { for (const record of waiting) if (record.state !== 'pending') pending.delete(record); }
    return original.goto.apply(page, args);
  };
  return {
    async dispose() {
      try { await Promise.all([...pending].map((record) => record.promise)); }
      finally {
        for (const record of pending) record.cleanup();
        pending.clear();
        handlers.clear();
        Object.assign(page, original);
      }
    },
  };
};
