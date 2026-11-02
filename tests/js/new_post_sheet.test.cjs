// The New post sheet's Write it myself address (Phase 3, screen 1, T17): static/js/new-post-sheet.js,
// run in a jsdom page. Open the editor (new-post-self-open) links to composer:compose and binds its href
// to editorUrl(base): the base alone, or the base with scheduled_date, scheduled_time and account, built
// with URLSearchParams, when the sheet was opened with them (a Calendar cell's "+" sends
// new-post:open with {mode: 'self', date, time, account}). Nothing else the opener sends is carried, and
// opening from the New post button afterwards carries nothing. That the cells send those values is
// apps/studio/tests/test_new_post_self.py's; the browser case is T21's.
// Requires the locked development dependencies; this makes no network requests.
// npm ci --ignore-scripts && npm run test:ui
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const script = fs.readFileSync(path.resolve(__dirname, '../../static/js/new-post-sheet.js'), 'utf8');
const BASE = '/workspace/3f1c2a9e-0000-4000-8000-000000000001/compose/';
const ACCOUNT = '9b2f6d7c-1111-4222-8333-444455556666';

/** The sheet's component as Alpine would hold it, in a page with the New post button. */
function sheet() {
  const dom = new JSDOM('<button aria-controls="new-post-sheet" aria-expanded="false">New post</button><div id="root"></div>', {
    runScripts: 'outside-only',
    url: 'https://example.test/workspace/one/calendar/',
  });
  const win = dom.window;
  win.eval(script);
  const component = win.newPostSheet();
  component.$el = win.document.getElementById('root');
  component.$nextTick = (callback) => callback && callback();
  component.init();
  return { win, component };
}

function query(url) {
  const [base, search = ''] = url.split('?');
  return { base, params: [...new URLSearchParams(search)] };
}

test('opened from the New post button, the editor link is the editor alone', () => {
  const { component } = sheet();
  assert.equal(component.editorUrl(BASE), BASE);
  component.open({});
  assert.equal(component.editorUrl(BASE), BASE);
});

test("a cell's date and time are carried as the composer reads them", () => {
  const { component } = sheet();
  component.open({ mode: 'self', date: '2026-11-17', time: '10:00', account: '' });

  assert.equal(component.sheetMode, 'self');
  assert.deepEqual(query(component.editorUrl(BASE)), {
    base: BASE,
    params: [['scheduled_date', '2026-11-17'], ['scheduled_time', '10:00']],
  });
  assert.equal(component.editorUrl(BASE), `${BASE}?scheduled_date=2026-11-17&scheduled_time=10%3A00`);
});

test("a channel slot's account comes first, as the slot's own link has it", () => {
  const { win, component } = sheet();
  win.dispatchEvent(new win.CustomEvent('new-post:open', {
    detail: { mode: 'self', date: '2026-11-17', time: '10:00', account: ACCOUNT },
  }));

  assert.equal(component.sheetOpen, true);
  assert.deepEqual(query(component.editorUrl(BASE)).params, [
    ['account', ACCOUNT],
    ['scheduled_date', '2026-11-17'],
    ['scheduled_time', '10:00'],
  ]);
});

test('only the date, the time and the account are carried, and only those it was given', () => {
  const { component } = sheet();
  component.open({ mode: 'self', date: '2026-11-17', time: '', account: '', caption: 'Hi', next: '/elsewhere/' });
  assert.deepEqual(query(component.editorUrl(BASE)).params, [['scheduled_date', '2026-11-17']]);

  component.sheetContext = { date: '2026-11-17', time: '10:00', account: ACCOUNT, caption: 'Hi', template: '7' };
  assert.deepEqual(
    query(component.editorUrl(BASE)).params.map(([key]) => key),
    ['account', 'scheduled_date', 'scheduled_time'],
  );
});

test('opening from the button after a cell forgets the cell', () => {
  const { component } = sheet();
  component.open({ mode: 'self', date: '2026-11-17', time: '10:00', account: ACCOUNT });
  component.close();
  component.open({});

  assert.equal(component.sheetMode, 'team');
  assert.equal(component.editorUrl(BASE), BASE);
});

test('closing gives focus back to the cell that opened the sheet', () => {
  const { win, component } = sheet();
  const plus = win.document.createElement('a');
  plus.href = `${BASE}?scheduled_date=2026-11-17&scheduled_time=10:00`;
  win.document.body.append(plus);
  component.open({ mode: 'self', date: '2026-11-17', time: '10:00', account: '' }, plus);
  component.close();

  assert.equal(win.document.activeElement, plus);
});

test("a cell's '+' that cannot take focus back (hover-only, hidden again) hands it to the New post button", () => {
  const { win, component } = sheet();
  const plus = win.document.createElement('a'); // no href: like a hidden "+", it cannot be focused
  win.document.body.append(plus);
  component.open({ mode: 'self', date: '2026-11-17', time: '10:00', account: '' }, plus);
  component.close();

  assert.equal(win.document.activeElement, win.document.querySelector('[aria-controls="new-post-sheet"]'));
});

test('values are encoded, never pasted into the address', () => {
  const { component } = sheet();
  component.sheetContext = { date: '2026-11-17&next=/x', time: '10:00#y', account: '' };
  assert.deepEqual(query(component.editorUrl(BASE)).params, [
    ['scheduled_date', '2026-11-17&next=/x'],
    ['scheduled_time', '10:00#y'],
  ]);
  assert.equal(component.editorUrl(BASE).includes('#'), false);
});
