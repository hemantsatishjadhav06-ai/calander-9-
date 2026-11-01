// The Appearance head script (plan T5; spec D2), run as base.html and the portal's base run it: the
// partial templates/components/theme_script.html, pasted into a nonce'd <script> in <head>, evaluated
// here in a jsdom page before anything else. The preference (System, Light or Dark) lives in
// localStorage.theme; data-theme lands on <html> only when the page is declared dark-ready
// (data-theme-ready); System follows the device; bb:themechange fires on window when the page's
// theme changes. That the stylesheet paints it is the browser spec's (tests/e2e/self/theme.spec.ts).
// Requires the locked development dependencies; this makes no network requests.
// npm ci --ignore-scripts && npm run test:ui
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const source = fs.readFileSync(path.resolve(__dirname, '../../templates/components/theme_script.html'), 'utf8');

/** A device whose colour scheme a test can flip, as matchMedia('(prefers-color-scheme: dark)') reports it. */
function device(dark) {
  const listeners = [];
  const media = {
    media: '(prefers-color-scheme: dark)',
    matches: dark,
    addEventListener(type, fn) { if (type === 'change') listeners.push(fn); },
    removeEventListener() {},
    addListener(fn) { listeners.push(fn); },
    removeListener() {},
  };
  return {
    media,
    flip(next) {
      media.matches = next;
      listeners.forEach((fn) => fn({ matches: next, media: media.media }));
    },
  };
}

/**
 * A page that runs the head script: `ready` puts data-theme-ready on <html>; `dark` is the device;
 * `stored` is localStorage.theme before the script runs; `storage: 'throws'` makes reading
 * localStorage throw (blocked storage, as some private modes and policies do).
 */
function page(t, { ready = true, dark = false, stored = null, storage = 'works' } = {}) {
  const html = `<!doctype html><html lang="en"${ready ? ' data-theme-ready' : ''}><head></head><body></body></html>`;
  const dom = new JSDOM(html, { url: 'http://127.0.0.1/', runScripts: 'outside-only' });
  const win = dom.window;
  t.after(() => win.close());
  if (stored !== null) win.localStorage.setItem('theme', stored);
  if (storage === 'throws') {
    Object.defineProperty(win, 'localStorage', { configurable: true, get() { throw new win.DOMException('Blocked', 'SecurityError'); } });
  }
  const screen = device(dark);
  win.matchMedia = (query) => {
    assert.equal(query, '(prefers-color-scheme: dark)');
    return screen.media;
  };
  const events = [];
  // The page's objects belong to its own realm: copy each detail into a plain one to compare.
  win.addEventListener('bb:themechange', (event) => events.push({ ...event.detail }));
  win.eval(source);
  const root = win.document.documentElement;
  return {
    win,
    events,
    screen,
    theme: () => root.getAttribute('data-theme'),
    has: () => root.hasAttribute('data-theme'),
    otherTab(value) {
      // What another tab's choice looks like here: the stored value changes, then a storage event.
      if (value === null) win.localStorage.removeItem('theme'); else win.localStorage.setItem('theme', value);
      win.dispatchEvent(new win.StorageEvent('storage', { key: 'theme', newValue: value, storageArea: win.localStorage }));
    },
  };
}

test('the partial is plain JavaScript that defines window.bbTheme', () => {
  assert.doesNotMatch(source, /{%|{{|{#/);
  assert.doesNotMatch(source, /<\/?script/i);
  assert.match(source, /window\.bbTheme\s*=/);
});

test('a page not declared ready gets no data-theme, whatever the choice and the device', (t) => {
  for (const stored of [null, 'system', 'light', 'dark']) {
    for (const dark of [false, true]) {
      const p = page(t, { ready: false, dark, stored });
      assert.equal(p.has(), false, `stored=${stored} dark=${dark}`);
      assert.equal(p.win.bbTheme.theme(), 'light');
    }
  }
});

test('an undeclared page stays light when Dark is chosen, and nothing redraws', (t) => {
  const p = page(t, { ready: false, dark: true });
  p.win.bbTheme.set('dark');
  assert.equal(p.has(), false);
  assert.equal(p.win.bbTheme.preference(), 'dark');
  assert.equal(p.win.localStorage.getItem('theme'), 'dark');
  assert.deepEqual(p.events, []);
});

test('System is the default, and it follows the device', (t) => {
  assert.equal(page(t, { dark: false }).theme(), 'light');
  const p = page(t, { dark: true });
  assert.equal(p.win.bbTheme.preference(), 'system');
  assert.equal(p.theme(), 'dark');
  assert.deepEqual(p.events, [], 'the first paint is not a change');
});

test('a choice wins over the device: Light on a dark device is light, Dark on a light one is dark', (t) => {
  assert.equal(page(t, { dark: true, stored: 'light' }).theme(), 'light');
  assert.equal(page(t, { dark: false, stored: 'dark' }).theme(), 'dark');
});

test('storage that throws reads as System', (t) => {
  const dark = page(t, { dark: true, storage: 'throws' });
  assert.equal(dark.win.bbTheme.preference(), 'system');
  assert.equal(dark.theme(), 'dark');
  assert.equal(page(t, { dark: false, storage: 'throws' }).theme(), 'light');
});

test('a stored value that is not a choice reads as System', (t) => {
  const p = page(t, { dark: true, stored: 'sepia' });
  assert.equal(p.win.bbTheme.preference(), 'system');
  assert.equal(p.theme(), 'dark');
});

test('choosing repaints at once, keeps the choice on the device and fires bb:themechange once', (t) => {
  const p = page(t, { dark: true });
  p.win.bbTheme.set('light');
  assert.equal(p.theme(), 'light');
  assert.equal(p.win.localStorage.getItem('theme'), 'light');
  assert.deepEqual(p.events, [{ theme: 'light', preference: 'light' }]);

  p.win.bbTheme.set('system');
  assert.equal(p.theme(), 'dark');
  assert.equal(p.win.localStorage.getItem('theme'), 'system');
  assert.deepEqual(p.events.at(-1), { theme: 'dark', preference: 'system' });
  assert.equal(p.events.length, 2);
});

test('a choice that changes nothing on screen fires nothing', (t) => {
  const p = page(t, { dark: true });
  p.win.bbTheme.set('dark');
  assert.equal(p.theme(), 'dark');
  assert.equal(p.win.bbTheme.preference(), 'dark');
  assert.deepEqual(p.events, []);
});

test('an unknown choice is refused and changes nothing', (t) => {
  const p = page(t, { dark: false, stored: 'light' });
  p.win.bbTheme.set('sepia');
  assert.equal(p.win.bbTheme.preference(), 'light');
  assert.equal(p.win.localStorage.getItem('theme'), 'light');
  assert.equal(p.theme(), 'light');
  assert.deepEqual(p.events, []);
});

test('when storage throws, a choice still applies to this page', (t) => {
  const p = page(t, { dark: true, storage: 'throws' });
  p.win.bbTheme.set('light');
  assert.equal(p.win.bbTheme.preference(), 'light');
  assert.equal(p.theme(), 'light');
  assert.deepEqual(p.events, [{ theme: 'light', preference: 'light' }]);
});

test('System follows the device as it changes; a fixed choice does not', (t) => {
  const p = page(t, { dark: false });
  p.screen.flip(true);
  assert.equal(p.theme(), 'dark');
  assert.deepEqual(p.events, [{ theme: 'dark', preference: 'system' }]);

  const fixed = page(t, { dark: false, stored: 'light' });
  fixed.screen.flip(true);
  assert.equal(fixed.theme(), 'light');
  assert.deepEqual(fixed.events, []);
});

test('a choice made in another tab arrives through the storage event', (t) => {
  const p = page(t, { dark: false });
  p.otherTab('dark');
  assert.equal(p.win.bbTheme.preference(), 'dark');
  assert.equal(p.theme(), 'dark');
  assert.deepEqual(p.events, [{ theme: 'dark', preference: 'dark' }]);

  p.otherTab(null);
  assert.equal(p.win.bbTheme.preference(), 'system');
  assert.equal(p.theme(), 'light');

  // Another key changing leaves the theme alone.
  p.win.localStorage.setItem('theme', 'dark');
  p.win.dispatchEvent(new p.win.StorageEvent('storage', { key: 'sidebarCollapsed', newValue: 'true' }));
  assert.equal(p.win.bbTheme.preference(), 'system');
  assert.equal(p.theme(), 'light');
});
