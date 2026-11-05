// The single-key shortcuts (spec D16, Phase 3 T20): static/js/shortcuts.js, run in a jsdom page.
// From 1024 px, `n` opens the New post sheet where its trigger is and otherwise goes to Home's
// #new-post for someone who may start posts (the page names the address in data-new-post-url);
// `/` opens Go to; `?` opens the list of shortcuts. Each is ignored in a text field, a select or an
// editable region, with a modifier (Shift only makes `?`, and is allowed there and on `/`), while a
// dialog is open, below 1024 px, and when single keys are off (localStorage.shortcuts = 'off', the
// list's switch). Ctrl/Cmd-/ opens the list in every case but an open dialog and a narrow screen, so
// the switch can always be turned back on. The browser cases are tests/e2e/self/shortcuts.spec.ts.
// Requires the locked development dependencies; this makes no network requests.
// npm ci --ignore-scripts && npm run test:ui
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const script = fs.readFileSync(path.resolve(__dirname, '../../static/js/shortcuts.js'), 'utf8');
const HOME = '/workspace/3f1c2a9e-0000-4000-8000-000000000001/studio/#new-post';
const EVENTS = ['new-post:open', 'open-palette', 'open-shortcuts'];

/**
 * A workspace page with the script loaded. `trigger`: the New post button is on it (Home, Calendar);
 * `newPost`: the address `n` goes to elsewhere ('' for someone who may not start posts); `width`: the
 * window's width; `stored`: localStorage.shortcuts before the script runs; `storageThrows`: reading
 * localStorage throws (blocked site data). A tiny layout: an element shows unless it or an ancestor
 * is hidden or display: none.
 */
function page({ trigger = false, newPost = HOME, width = 1280, stored, storageThrows = false, body = '' } = {}) {
  const list = `<div data-shortcuts${newPost ? ` data-new-post-url="${newPost}"` : ''}></div>`;
  const button = trigger ? '<button aria-controls="new-post-sheet" aria-expanded="false">New post</button>' : '';
  const dom = new JSDOM(`<!doctype html><body>${button}${body}${list}</body>`, {
    runScripts: 'outside-only',
    url: 'https://example.test/workspace/3f1c2a9e-0000-4000-8000-000000000001/approvals/',
  });
  const win = dom.window;
  win.HTMLElement.prototype.getClientRects = function getClientRects() {
    return this.closest('[hidden], [style*="display: none"]') ? [] : [{ width: 1, height: 1 }];
  };
  win.matchMedia = (query) => ({ media: query, matches: width >= 1024, addEventListener() {}, removeEventListener() {} });
  if (storageThrows) {
    Object.defineProperty(win, 'localStorage', {
      configurable: true,
      get() { throw new win.DOMException('The operation is insecure.', 'SecurityError'); },
    });
  } else if (stored !== undefined) {
    win.localStorage.setItem('shortcuts', stored);
  }
  const fired = [];
  EVENTS.forEach((name) => win.addEventListener(name, () => fired.push(name)));
  win.eval(script);
  const went = [];
  win.bbShortcuts.navigate = (url) => went.push(url);
  return { win, doc: win.document, fired, went };
}

/** Press `key` on `target` (the body by default); returns the keydown event. */
function press(win, key, options = {}, target = win.document.body) {
  const event = new win.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...options });
  target.dispatchEvent(event);
  return event;
}

// ── The three keys ────────────────────────────────────────────────────────────────────────────

test('n opens the New post sheet where its trigger is, and nothing is typed', () => {
  const { win, fired, went } = page({ trigger: true });
  const event = press(win, 'n');
  assert.deepEqual(fired, ['new-post:open']);
  assert.deepEqual(went, []);
  assert.equal(event.defaultPrevented, true);
});

test("n elsewhere goes to Home's #new-post for someone who may start posts", () => {
  const { win, fired, went } = page({ trigger: false });
  press(win, 'n');
  assert.deepEqual(fired, []);
  assert.deepEqual(went, [HOME]);
});

test('n does nothing for someone who may not start posts', () => {
  const { win, fired, went } = page({ trigger: false, newPost: '' });
  const event = press(win, 'n');
  assert.deepEqual(fired, []);
  assert.deepEqual(went, []);
  assert.equal(event.defaultPrevented, false);
});

test('n with Caps Lock on (N without Shift) is still n', () => {
  const { win, fired } = page({ trigger: true });
  press(win, 'N');
  assert.deepEqual(fired, ['new-post:open']);
});

test('/ opens Go to, and the slash is not typed', () => {
  const { win, fired } = page();
  const event = press(win, '/');
  assert.deepEqual(fired, ['open-palette']);
  assert.equal(event.defaultPrevented, true);
});

test('? opens the list, with Shift (how it is typed) or without', () => {
  const { win, fired } = page();
  press(win, '?', { shiftKey: true });
  press(win, '?');
  assert.deepEqual(fired, ['open-shortcuts', 'open-shortcuts']);
});

test('a focused button or link does not stop a shortcut', () => {
  const { win, doc, fired } = page({ trigger: true, body: '<a href="/x/" id="link">Calendar</a><input type="checkbox" id="box">' });
  press(win, 'n', {}, doc.getElementById('link'));
  press(win, '/', {}, doc.querySelector('[aria-controls="new-post-sheet"]'));
  press(win, '?', { shiftKey: true }, doc.getElementById('box'));
  assert.deepEqual(fired, ['new-post:open', 'open-palette', 'open-shortcuts']);
});

// ── Ignored ───────────────────────────────────────────────────────────────────────────────────

const FIELDS = {
  'a text field': '<input type="text" id="field">',
  'a field with no type': '<input id="field">',
  'a search field': '<input type="search" id="field">',
  'an email field': '<input type="email" id="field">',
  'a number field': '<input type="number" id="field">',
  'a text area': '<textarea id="field"></textarea>',
  'a select': '<select id="field"><option>One</option></select>',
  'an editable region': '<div contenteditable="true"><p id="field">Words</p></div>',
  'an editable region (empty attribute)': '<div contenteditable id="field"></div>',
  'a textbox role': '<div role="textbox" tabindex="0" id="field"></div>',
};

for (const [what, html] of Object.entries(FIELDS)) {
  test(`ignored in ${what}: the key is typed`, () => {
    const { win, doc, fired, went } = page({ trigger: true, body: html });
    const field = doc.getElementById('field');
    for (const [key, options] of [['n', {}], ['/', {}], ['?', { shiftKey: true }]]) {
      const event = press(win, key, options, field);
      assert.equal(event.defaultPrevented, false, `${key} in ${what}`);
    }
    assert.deepEqual(fired, []);
    assert.deepEqual(went, []);
  });
}

test('ignored when the focus is in a field even if the key reaches the page from elsewhere', () => {
  const { win, doc, fired } = page({ trigger: true, body: '<textarea id="field"></textarea>' });
  doc.getElementById('field').focus();
  press(win, 'n');
  assert.deepEqual(fired, []);
});

test('ignored with Ctrl, Alt or Meta; Shift-N is not n', () => {
  const { win, fired, went } = page({ trigger: true });
  for (const modifier of ['ctrlKey', 'altKey', 'metaKey']) {
    press(win, 'n', { [modifier]: true });
    press(win, '/', { [modifier]: true });
  }
  press(win, 'N', { shiftKey: true });
  // Ctrl-/ and Cmd-/ open the list (below); they never open Go to.
  assert.deepEqual(fired.filter((name) => name !== 'open-shortcuts'), [], 'n and / with a modifier do nothing');
  assert.deepEqual(went, []);
});

test('? with Ctrl, Alt or Meta does nothing', () => {
  const { win, fired } = page();
  press(win, '?', { ctrlKey: true, shiftKey: true });
  press(win, '?', { altKey: true, shiftKey: true });
  press(win, '?', { metaKey: true, shiftKey: true });
  assert.deepEqual(fired, []);
});

test('ignored while a dialog is open; a hidden one does not count', () => {
  const open = page({ trigger: true, body: '<div role="dialog" aria-modal="true" aria-label="Notifications"></div>' });
  press(open.win, 'n');
  press(open.win, '/');
  press(open.win, '?', { shiftKey: true });
  press(open.win, '/', { ctrlKey: true });
  assert.deepEqual(open.fired, []);

  const native = page({ trigger: true, body: '<dialog open aria-label="Confirm"></dialog>' });
  press(native.win, 'n');
  assert.deepEqual(native.fired, []);

  const hidden = page({
    trigger: true,
    body: '<div style="display: none;"><div role="dialog" aria-modal="true" aria-label="Go to"></div></div>'
      + '<div role="dialog" aria-modal="true" aria-label="New post" style="display: none;"></div>',
  });
  press(hidden.win, 'n');
  assert.deepEqual(hidden.fired, ['new-post:open']);
});

/** A drawer that stays in the page while closed, as Analytics' Post details does: it keeps its box
 * (slid out of view) and is hidden by visibility: hidden and aria-hidden="true" instead. */
function drawer(open) {
  return '<style>.drawer { visibility: hidden; transform: translateX(100%); }'
    + ' .drawer.open { visibility: visible; transform: none; }</style>'
    + `<div class="drawer${open ? ' open' : ''}" role="dialog" aria-modal="true" aria-label="Post details"`
    + ` aria-hidden="${open ? 'false' : 'true'}"></div>`;
}

test('a closed drawer that keeps its box does not count: the keys work beside it', () => {
  const closed = page({ trigger: false, body: drawer(false) });
  press(closed.win, 'n');
  press(closed.win, '/');
  press(closed.win, '?', { shiftKey: true });
  press(closed.win, '/', { ctrlKey: true });
  assert.deepEqual(closed.fired, ['open-palette', 'open-shortcuts', 'open-shortcuts']);
  assert.deepEqual(closed.went, [HOME]);

  const open = page({ trigger: false, body: drawer(true) });
  press(open.win, 'n');
  press(open.win, '/');
  press(open.win, '?', { shiftKey: true });
  assert.deepEqual(open.fired, [], 'the same drawer open blocks every key');
  assert.deepEqual(open.went, []);
});

test('a dialog hidden by visibility: hidden, aria-hidden="true" or inert does not count', () => {
  const hidden = [
    '<div role="dialog" aria-modal="true" aria-label="Post details" aria-hidden="true" style="visibility: hidden;"></div>',
    '<div role="dialog" aria-modal="true" aria-label="Post details" style="visibility: hidden;"></div>',
    '<div style="visibility: hidden;"><div role="dialog" aria-modal="true" aria-label="Go to"></div></div>',
    '<div role="dialog" aria-modal="true" aria-label="Post details" aria-hidden="true"></div>',
    '<div aria-hidden="true"><div role="dialog" aria-modal="true" aria-label="Go to"></div></div>',
    '<div inert><div role="dialog" aria-modal="true" aria-label="Go to"></div></div>',
  ];
  for (const body of hidden) {
    const { win, fired } = page({ trigger: true, body });
    press(win, 'n');
    assert.deepEqual(fired, ['new-post:open'], body);
  }

  const shown = [
    '<div role="dialog" aria-modal="true" aria-label="Post details" aria-hidden="false"></div>',
    '<div style="visibility: hidden;"><div role="dialog" aria-modal="true" aria-label="Go to" style="visibility: visible;"></div></div>',
  ];
  for (const body of shown) {
    const { win, fired } = page({ trigger: true, body });
    press(win, 'n');
    assert.deepEqual(fired, [], body);
  }
});

test('ignored below 1024 px', () => {
  const { win, fired, went } = page({ trigger: true, width: 1023 });
  press(win, 'n');
  press(win, '/');
  press(win, '?', { shiftKey: true });
  press(win, '/', { ctrlKey: true });
  assert.deepEqual(fired, []);
  assert.deepEqual(went, []);
});

test('ignored when single keys are off on this device', () => {
  const { win, fired, went } = page({ trigger: false, stored: 'off' });
  press(win, 'n');
  press(win, '/');
  press(win, '?', { shiftKey: true });
  assert.deepEqual(fired, []);
  assert.deepEqual(went, []);
});

test('auto-repeat, a key another handler took and a key still being composed are ignored', () => {
  const { win, doc, fired } = page({ trigger: true });
  press(win, 'n', { repeat: true });
  press(win, '/', { isComposing: true });
  doc.body.addEventListener('keydown', (event) => event.preventDefault(), { capture: true, once: true });
  press(win, '?', { shiftKey: true });
  assert.deepEqual(fired, []);
});

// ── Ctrl/Cmd-/ and the switch ────────────────────────────────────────────────────────────────

test('Ctrl-/ or Cmd-/ opens the list, also with single keys off and in a field', () => {
  const { win, doc, fired } = page({ stored: 'off', body: '<textarea id="field"></textarea>' });
  const event = press(win, '/', { ctrlKey: true });
  press(win, '/', { metaKey: true }, doc.getElementById('field'));
  assert.deepEqual(fired, ['open-shortcuts', 'open-shortcuts']);
  assert.equal(event.defaultPrevented, true);
});

/** The list's Alpine component as Alpine holds it. */
function list(win) {
  const component = win.shortcutsList();
  component.$nextTick = (callback) => callback && callback();
  return component;
}

test('the switch shows the device setting, turns single keys off and on again, and is kept', () => {
  const { win, fired } = page({ trigger: true });
  const component = list(win);
  component.show();
  assert.equal(component.open, true);
  assert.equal(component.enabled, true);

  component.setEnabled(false);
  assert.equal(component.enabled, false);
  assert.equal(win.localStorage.getItem('shortcuts'), 'off');
  assert.equal(win.bbShortcuts.isOn(), false);
  press(win, 'n');
  assert.deepEqual(fired, []);

  component.close();
  component.show();
  assert.equal(component.enabled, false, 'the list reads the setting each time it opens');

  component.setEnabled(true);
  assert.equal(win.localStorage.getItem('shortcuts'), null);
  press(win, 'n');
  assert.deepEqual(fired, ['new-post:open']);
});

test('a setting made in another tab shows the next time the list opens', () => {
  const { win } = page();
  const component = list(win);
  component.show();
  component.close();
  win.localStorage.setItem('shortcuts', 'off');
  component.show();
  assert.equal(component.enabled, false);
});

test('blocked storage: the keys work, and the switch still turns them off for this page', () => {
  const { win, fired } = page({ trigger: true, storageThrows: true });
  press(win, 'n');
  assert.deepEqual(fired, ['new-post:open']);

  const component = list(win);
  component.show();
  assert.equal(component.enabled, true);
  assert.doesNotThrow(() => component.setEnabled(false));
  assert.equal(component.enabled, false);
  press(win, 'n');
  assert.deepEqual(fired, ['new-post:open']);
});

test('closing the list gives focus back to what had it', () => {
  const { win, doc } = page({ body: '<a href="/x/" id="link">Calendar</a>' });
  const link = doc.getElementById('link');
  link.focus();
  const component = list(win);
  component.show();
  doc.body.focus();
  component.close();
  assert.equal(component.open, false);
  assert.equal(doc.activeElement, link);
});

/** Move the list's timers on by `ms` (jsdom's timers run on Node's, which the test mocks). */
function later(t, ms) {
  t.mock.timers.tick(ms);
}

/** Let the microtasks queued so far run (show() queues the trap's marker in one, after Alpine's flush). */
function settle() {
  return new Promise((resolve) => queueMicrotask(resolve));
}

/** The list's component with its markup: the dialog and its close button, as base.html gives them. */
function listWithMarkup(win) {
  const doc = win.document;
  const dialog = doc.createElement('div');
  dialog.setAttribute('role', 'dialog');
  const close = doc.createElement('button');
  close.textContent = 'Close';
  dialog.appendChild(close);
  doc.body.appendChild(dialog);
  const component = list(win);
  component.$refs = { dialog, close };
  return { component, dialog, close };
}

test('opening the list puts the focus on its close button itself, not through its trap', () => {
  const { win, doc } = page();
  const { component, close } = listWithMarkup(win);
  component.show();
  assert.equal(doc.activeElement, close);
});

test('closing the list before the plugin has started its trap lets the trap go only once it has', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { win } = page();
  const { component } = listWithMarkup(win);
  component.show();
  await settle();
  assert.equal(component.trapped, true);
  later(t, 1);
  component.close();
  assert.equal(component.open, false, 'the list closes at once');
  assert.equal(component.trapped, true, 'its trap is kept until the plugin has started it');
  later(t, 30);
  assert.equal(component.trapped, false);
});

test('closing the list after the plugin has started its trap lets the trap go at once', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { win } = page();
  const { component } = listWithMarkup(win);
  component.show();
  await settle();
  later(t, 100);
  component.close();
  assert.equal(component.trapped, false);
});

test('opened again before a held trap is let go, the list keeps it', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { win } = page();
  const { component } = listWithMarkup(win);
  component.show();
  await settle();
  component.close();
  component.show();
  await settle();
  later(t, 100);
  assert.equal(component.open, true);
  assert.equal(component.trapped, true);
});

test("the list waits for the focus plugin's own trap delay", () => {
  // x-trap starts its trap in setTimeout(() => trap.activate(), N): the list's marker must wait as long.
  const plugin = fs.readFileSync(path.resolve(__dirname, '../../static/js/vendor/alpine-focus.min.js'), 'utf8');
  const delays = [...plugin.matchAll(/setTimeout\(\(\)=>\{\w+\.activate\(\)\},(\d+)\)/g)].map((match) => Number(match[1]));
  assert.equal(delays.length, 1, 'the plugin starts its trap in exactly one timer');
  const { win } = page();
  assert.equal(win.bbShortcuts.pluginTrapDelayMs, delays[0]);
});
