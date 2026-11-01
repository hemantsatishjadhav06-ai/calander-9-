// The Activity hour chart's tooltip reads its colours from the theme (plan T4): the token reader
// window.bbToken (templates/base.html) answers them when the tooltip is drawn, and a theme change
// (bb:themechange on window) draws a visible tooltip again, once.
// Requires the locked development dependencies; this makes no network requests.
// npm ci --ignore-scripts && npm run test:ui
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const source = fs.readFileSync(path.resolve(__dirname, '../../static/js/live_board.js'), 'utf8');

// Token values as the reader returns them. rgb() so jsdom's style.color answers them unchanged.
const LIGHT = { 'ink-300': 'rgb(206, 210, 215)', 'danger-300': 'rgb(254, 166, 156)' };
const DARK = { 'ink-300': 'rgb(145, 150, 157)', 'danger-300': 'rgb(250, 160, 150)' };

const MARKUP = `<div id="team-hour-chart" data-hour-chart tabindex="0" role="img" aria-label="Busiest at 10:00.">
  <svg aria-hidden="true">
    <rect data-bar="0"></rect>
    <rect data-hit="0" data-range="09:00–10:00" data-total="1" data-failed="0" data-top="40"></rect>
    <rect data-bar="1"></rect>
    <rect data-hit="1" data-range="10:00–11:00" data-total="6" data-failed="2" data-top="10"></rect>
  </svg>
  <div class="chart-tip hidden" data-chart-tip aria-hidden="true"></div>
</div>
<p class="sr-only" data-chart-live role="status" aria-live="polite"></p>`;

function board(t, { reader = true } = {}) {
  const dom = new JSDOM(`<!doctype html><html><body>${MARKUP}</body></html>`, { runScripts: 'outside-only' });
  const win = dom.window;
  t.after(() => win.close());
  const reads = [];
  let theme = LIGHT;
  if (reader) {
    win.bbToken = (name) => {
      reads.push(name);
      return theme[name] || '';
    };
  }
  win.eval(source);
  win.document.dispatchEvent(new win.Event('DOMContentLoaded'));
  const query = (selector) => win.document.querySelector(selector);
  const chart = query('[data-hour-chart]');
  const tip = query('[data-chart-tip]');
  return {
    win,
    chart,
    tip,
    reads,
    setTheme(next) { theme = next; },
    hover(index) {
      query(`[data-hit="${index}"]`).dispatchEvent(new win.Event('pointermove', { bubbles: true }));
    },
    themeChange() { win.dispatchEvent(new win.CustomEvent('bb:themechange', { detail: { theme: 'dark' } })); },
    painted() {
      const rows = tip.querySelectorAll(':scope > div');
      const icon = tip.querySelector('svg');
      return { range: rows[1] && rows[1].style.color, icon: icon && icon.getAttribute('stroke') };
    },
    count(name) { return reads.filter((read) => read === name).length; },
  };
}

test('the tooltip writes no colour of its own', () => {
  assert.doesNotMatch(source, /#[0-9a-f]{3,8}\b/i);
  assert.doesNotMatch(source, /\b(?:rgb|hsl|hwb|lab|lch|oklab|oklch)a?\(\s*[-+.\d]/i);
});

test('the tooltip colours come from the token reader when it is drawn', (t) => {
  const b = board(t);
  b.hover(1);
  assert.equal(b.tip.classList.contains('hidden'), false);
  assert.deepEqual(b.painted(), { range: LIGHT['ink-300'], icon: LIGHT['danger-300'] });
  assert.ok(b.count('ink-300') >= 1 && b.count('danger-300') >= 1);
});

test('a theme change draws the visible tooltip again once, in the new colours, without announcing it', (t) => {
  const b = board(t);
  b.chart.focus();
  b.chart.dispatchEvent(new b.win.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
  const region = b.win.document.querySelector('[data-chart-live]');
  assert.equal(region.textContent, '10:00–11:00: 6 turns, 2 stopped');
  region.textContent = '';
  const before = b.count('ink-300');
  b.setTheme(DARK);
  b.themeChange();
  assert.equal(b.count('ink-300') - before, 1, 'one theme change, one drawing');
  assert.deepEqual(b.painted(), { range: DARK['ink-300'], icon: DARK['danger-300'] });
  assert.equal(b.tip.classList.contains('hidden'), false);
  assert.equal(region.textContent, '', 'a repaint is not news for a screen reader');
  assert.equal(b.chart.querySelectorAll('[data-bar="1"][data-active="true"]').length, 1);
  assert.equal(b.win.document.activeElement, b.chart, 'focus stays on the chart');
});

test('the board loaded twice and refreshed still draws once per theme change', (t) => {
  const b = board(t);
  b.win.eval(source);
  b.win.document.dispatchEvent(new b.win.CustomEvent('htmx:afterSettle', { detail: { elt: b.chart } }));
  b.hover(1);
  const before = b.count('ink-300');
  b.setTheme(DARK);
  b.themeChange();
  assert.equal(b.count('ink-300') - before, 1);
});

test('a hidden tooltip is not drawn on a theme change; it reads the new colours when it next shows', (t) => {
  const b = board(t);
  b.setTheme(DARK);
  b.themeChange();
  assert.equal(b.reads.length, 0);
  assert.equal(b.tip.classList.contains('hidden'), true);
  b.hover(1);
  assert.deepEqual(b.painted(), { range: DARK['ink-300'], icon: DARK['danger-300'] });
});

test('without the token reader the tooltip still draws, in the tooltip\'s own text colour', (t) => {
  const b = board(t, { reader: false });
  b.hover(1);
  assert.equal(b.tip.classList.contains('hidden'), false);
  assert.deepEqual(b.painted(), { range: '', icon: 'currentColor' });
});
