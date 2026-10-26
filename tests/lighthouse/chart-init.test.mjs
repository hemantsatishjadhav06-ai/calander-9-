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
