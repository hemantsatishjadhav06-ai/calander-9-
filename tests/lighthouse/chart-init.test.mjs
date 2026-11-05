import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const template = await readFile(new URL('../../templates/base.html', import.meta.url), 'utf8');
const start = template.indexOf('function bbInitHeroChart(');
const end = template.indexOf('// Wrap in a no-arg callback', start);
assert.ok(start >= 0 && end > start, 'The actual chart initializer must be tested.');
const script = template.slice(start, end);

test('pages without an analytics canvas schedule no missing-library retries', () => {
  const timers = [];
  const context = { document: { getElementById: () => null }, setTimeout: (...args) => timers.push(args) };
  vm.runInNewContext(script, context);
  context.bbInitHeroChart();
  assert.equal(timers.length, 0);
});

test('the analytics canvas still renders its actual series after scoping the vendor', () => {
  let chart;
  const canvas = {
    dataset: { series: '[3,7]', labels: '["2026-10-25","2026-10-26"]' },
    getContext: () => ({ createLinearGradient: () => ({ addColorStop() {} }) }),
  };
  const context = {
    document: { getElementById: () => canvas }, window: {},
    Chart: class { constructor(_ctx, config) { chart = config; } },
    setTimeout() { throw new Error('The available chart library must not be polled.'); },
  };
  vm.runInNewContext(script, context);
  context.bbInitHeroChart();
  assert.equal(chart.type, 'line');
  assert.deepEqual(Array.from(chart.data.datasets[0].data), [3, 7]);
});

// Dark mode (plan T4): the chart reads its colours from the theme where it draws, never writes one
// of its own, draws its text at the 13 px floor, and draws again when the theme changes.
const styles = await readFile(new URL('../../theme/static_src/src/styles.css', import.meta.url), 'utf8');

/** The Layer 1 scale declared by the first block that opens with `selector {`. */
function layerOne(selector) {
  const open = styles.indexOf(`${selector} {`);
  assert.ok(open >= 0, `styles.css declares ${selector}`);
  const block = styles.slice(open, styles.indexOf('}', open));
  return Object.fromEntries([...block.matchAll(/(--[\w-]+):\s*(#[0-9A-Fa-f]{6})/g)].map((m) => [m[1], m[2]]));
}
const LIGHT = layerOne(':root');
const DARK = layerOne(':root[data-theme="dark"]');

/** A browser stand-in: getComputedStyle answers each custom property as the browser does (a leading space). */
function chartContext(ChartClass, tokens, extra = {}) {
  const stops = [];
  const canvas = {
    dataset: { series: '[3,7]', labels: '["2026-10-25","2026-10-26"]' },
    getContext: () => ({ createLinearGradient: () => ({ addColorStop: (at, colour) => stops.push([at, colour]) }) }),
  };
  const root = {};
  const context = {
    document: { getElementById: (id) => (id === 'analytics-area-chart' ? canvas : null), documentElement: root },
    getComputedStyle: (element) => {
      assert.equal(element, root, 'tokens are read from <html>, where the theme is set');
      return { getPropertyValue: (name) => (name in tokens ? ` ${tokens[name]}` : '') };
    },
    window: {},
    Chart: ChartClass,
    setTimeout() { throw new Error('The available chart library must not be polled.'); },
    ...extra,
  };
  return { context, stops };
}

function drawn(tokens) {
  const built = [];
  class Chart { constructor(_ctx, config) { built.push(config); } }
  Chart.defaults = { font: { size: 12 } };
  const { context, stops } = chartContext(Chart, tokens);
  vm.runInNewContext(script, context);
  context.bbInitHeroChart();
  assert.equal(built.length, 1);
  return { config: built[0], stops };
}

function colours({ config, stops }) {
  const line = config.data.datasets[0];
  return {
    line: line.borderColor,
    point: line.pointHoverBackgroundColor,
    xTicks: config.options.scales.x.ticks.color,
    yTicks: config.options.scales.y.ticks.color,
    grid: config.options.scales.y.grid.color,
    fill: stops,
  };
}

const COLOUR_LITERALS = [
  /#[0-9a-f]{3,8}\b/i,
  /\b(?:rgb|hsl|hwb|lab|lch|oklab|oklch)a?\(\s*[-+.\d]/i,
  /['"](?:black|white|gray|grey|silver|red|green|blue|navy|teal|orange|yellow|purple)['"]/i,
];

test('no colour literal between the chart initializer and its callers: every colour is a token', () => {
  for (const pattern of COLOUR_LITERALS) assert.doesNotMatch(script, pattern);
});

test('in light, the chart draws exactly the colours it drew before dark mode', () => {
  assert.deepEqual(colours(drawn(LIGHT)), {
    line: '#1C1F24',
    point: '#1C1F24',
    xTicks: '#656B73',
    yTicks: '#656B73',
    grid: '#EDEFF2',
    fill: [[0, 'rgba(28,31,36,0.08)'], [1, 'rgba(28,31,36,0)']],
  });
});

test('in dark, the chart draws the dark theme\'s values for the same tokens', () => {
  const dark = colours(drawn(DARK));
  assert.equal(dark.line, DARK['--ink-900']);
  assert.equal(dark.point, DARK['--ink-900']);
  assert.equal(dark.xTicks, DARK['--ink-500']);
  assert.equal(dark.yTicks, DARK['--ink-500']);
  assert.equal(dark.grid, DARK['--ink-100']);
  assert.notEqual(dark.line, LIGHT['--ink-900']);
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(DARK['--ink-900'].slice(i, i + 2), 16));
  assert.deepEqual(dark.fill, [[0, `rgba(${r},${g},${b},0.08)`], [1, `rgba(${r},${g},${b},0)`]]);
});

test('a three-digit token, as the minified stylesheet writes one, fills like its six-digit form', () => {
  // tailwindcss --minify shortens #ffffff to #fff; the chart reads the built stylesheet's value.
  const { stops } = drawn({ ...LIGHT, '--ink-900': '#fff' });
  assert.deepEqual(stops, [[0, 'rgba(255,255,255,0.08)'], [1, 'rgba(255,255,255,0)']]);
});

test('a token that cannot be read leaves the fill transparent instead of breaking the chart', () => {
  const { config, stops } = drawn({});
  assert.equal(config.type, 'line');
  assert.deepEqual(stops, [[0, 'transparent'], [1, 'transparent']]);
});

test('the sliced function sets the font size to 13 or more before the chart is built', () => {
  let sizeWhenBuilt;
  let config;
  class Chart { constructor(_ctx, given) { sizeWhenBuilt = Chart.defaults.font.size; config = given; } }
  Chart.defaults = { font: { size: 12 } }; // the vendored Chart.js 4.4.6 default
  const { context } = chartContext(Chart, LIGHT);
  vm.runInNewContext(script, context);
  context.bbInitHeroChart();
  assert.ok(sizeWhenBuilt >= 13, `the axis and tooltip text are drawn at ${sizeWhenBuilt} px`);
  // Nothing in the chart's own options sets a smaller size for one part.
  const small = [];
  (function walk(value, where) {
    if (!value || typeof value !== 'object') return;
    for (const [key, inner] of Object.entries(value)) {
      if (/font$/i.test(key) && inner && typeof inner === 'object' && typeof inner.size === 'number' && inner.size < 13) {
        small.push(`${where}.${key}`);
      }
      walk(inner, `${where}.${key}`);
    }
  })(config.options, 'options');
  assert.deepEqual(small, []);
});

test('a theme change draws the chart again once, in the new colours, without replaying its entrance', () => {
  // The initializer plus its callers, up to the next helper in the same script block.
  const callers = template.slice(start, template.indexOf('/* flatpickr hides the real input', end));
  assert.ok(callers.includes('// Wrap in a no-arg callback'));
  const built = [];
  let destroyed = 0;
  class Chart {
    constructor(_ctx, config) { built.push(config); }
    destroy() { destroyed += 1; }
  }
  Chart.defaults = { font: { size: 12 } };
  let tokens = LIGHT;
  const listeners = { document: {}, body: {}, window: {} };
  const on = (where) => (name, fn) => { (listeners[where][name] ||= []).push(fn); };
  const { context } = chartContext(Chart, new Proxy({}, {
    has: (_, name) => name in tokens,
    get: (_, name) => tokens[name],
  }));
  context.document.addEventListener = on('document');
  context.document.body = { addEventListener: on('body') };
  context.window.addEventListener = on('window');
  vm.runInNewContext(callers, context);
  const fire = (where, name) => (listeners[where][name] || []).forEach((fn) => fn({}));

  fire('document', 'DOMContentLoaded');
  assert.equal(built.length, 1);
  assert.notEqual(built[0].options.animation, false, 'the first drawing keeps its entrance');

  tokens = DARK;
  fire('window', 'bb:themechange');
  assert.equal(built.length, 2, 'one theme change, one new drawing');
  assert.equal(destroyed, 1, 'the old drawing is released');
  assert.equal(built[1].data.datasets[0].borderColor, DARK['--ink-900']);
  assert.equal(built[1].options.scales.y.grid.color, DARK['--ink-100']);
  assert.equal(built[1].options.animation, false);
  assert.deepEqual(Array.from(built[1].data.datasets[0].data), [3, 7]);
});

test('a theme change on a page without the chart draws nothing', () => {
  const callers = template.slice(start, template.indexOf('/* flatpickr hides the real input', end));
  let built = 0;
  class Chart { constructor() { built += 1; } }
  Chart.defaults = { font: { size: 12 } };
  const listeners = {};
  const { context } = chartContext(Chart, LIGHT);
  context.document.getElementById = () => null;
  context.document.addEventListener = () => {};
  context.document.body = { addEventListener: () => {} };
  context.window.addEventListener = (name, fn) => { (listeners[name] ||= []).push(fn); };
  vm.runInNewContext(callers, context);
  (listeners['bb:themechange'] || []).forEach((fn) => fn({}));
  assert.equal(built, 0);
});
