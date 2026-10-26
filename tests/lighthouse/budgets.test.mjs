import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { evaluate, interactionSummary, measurements, median, validateBaseURL, validateConfig } from './budgets.mjs';

const config = JSON.parse(await readFile(new URL('../../.lighthouserc.json', import.meta.url), 'utf8'));
const lhr = (score = 0.95) => ({
  requestedUrl: 'http://127.0.0.1:8151/workspace/a/studio/',
  finalDisplayedUrl: 'http://127.0.0.1:8151/workspace/a/studio/',
  categories: { performance: { score } },
  audits: {
    'largest-contentful-paint': { numericValue: 2000 },
    'cumulative-layout-shift': { numericValue: 0.05 },
    'total-blocking-time': { numericValue: 100 },
    'resource-summary': { details: { items: [{ resourceType: 'script', transferSize: 100000 }] } },
  },
});
const sample = (score = 0.95) => measurements(lhr(score), { inpUpperBoundMs: 120, interactionCount: 3 }, 110000);

test('configuration enforces the exact section 5 budgets with three mobile runs', () => {
  validateConfig(config);
  assert.equal(config.ci.collect.numberOfRuns, 3);
  assert.equal(config.ci.collect.settings.formFactor, 'mobile');
  assert.equal(config.ci.collect.url.length, 3);
  assert.deepEqual(config.ci.assert.assertions['categories:performance'], ['error', { minScore: 0.9 }]);
  assert.deepEqual(config.ci.assert.assertions['largest-contentful-paint'], ['error', { maxNumericValue: 2500 }]);
  assert.deepEqual(config.ci.assert.assertions['cumulative-layout-shift'], ['error', { maxNumericValue: 0.1 }]);
  assert.deepEqual(config.ci.assert.assertions['resource-summary:script:size'], ['error', { maxNumericValue: 150000 }]);
  assert.equal(config.smbean.interactionToNextPaintMaxMs, 200);
  assert.equal(config.smbean.javascriptGzipMaxBytes, 150000);
});

test('cannot turn a budget into a warning or silently omit it', () => {
  const warned = structuredClone(config);
  warned.ci.assert.assertions['categories:performance'][0] = 'warn';
  assert.throws(() => validateConfig(warned), /error/);
  const omitted = structuredClone(config);
  delete omitted.ci.assert.assertions['largest-contentful-paint'];
  assert.throws(() => validateConfig(omitted), /largest-contentful-paint/);
});

test('medians use all three runs rather than picking the best score', () => {
  assert.equal(median([3, 1, 2]), 2);
  assert.equal(evaluate([sample(0.89), sample(0.91), sample(0.88)], config).passed, false);
  assert.equal(evaluate([sample(0.90), sample(0.91), sample(0.89)], config).passed, true);
  assert.throws(() => evaluate([sample(), sample()], config), /three/);
});

test('every independent budget can fail even when performance passes', () => {
  for (const [key, badValue] of Object.entries({ lcp: 2501, cls: 0.101, scriptBytes: 150001, gzipBytes: 150001, inp: 201 })) {
    const bad = { ...sample(), [key]: badValue };
    const result = evaluate([bad, bad, bad], config);
    assert.equal(result.passed, false, key);
    assert.ok(result.failures.some((failure) => failure.metric === key), key);
  }
});

test('measured INP is the section 5 gate; TBT stays an independent diagnostic, never a substitute', () => {
  const goodInput = { ...sample(), tbt: 900, inp: 120 };
  const result = evaluate([goodInput, goodInput, goodInput], config);
  assert.equal(result.passed, true);
  assert.equal(result.medians.tbt, 900, 'Keep the diagnostic value visible.');
  const slowInput = { ...sample(), tbt: 0, inp: 201 };
  const failed = evaluate([slowInput, slowInput, slowInput], config);
  assert.equal(failed.passed, false);
  assert.deepEqual(failed.failures.map((failure) => failure.metric), ['inp']);
});

test('missing metrics, unmeasured interactions and runtime errors fail closed', () => {
  const missing = lhr();
  delete missing.audits['largest-contentful-paint'];
  assert.throws(() => measurements(missing, { inpUpperBoundMs: 10, interactionCount: 1 }, 50), /largest-contentful-paint/);
  assert.throws(() => measurements(lhr(), { inpUpperBoundMs: 0, interactionCount: 0 }, 50), /interaction/);
  assert.throws(() => measurements({ ...lhr(), runtimeError: { code: 'NO_FCP' } }, {}, 50), /NO_FCP/);
  assert.throws(() => median([1, Number.NaN, 3]), /finite/);
  assert.throws(() => evaluate([{}, {}, {}], config), /finite/);
  assert.throws(() => evaluate([sample(), {}, sample()], config), /finite/);
});

test('lab interaction bounds allow for Event Timing quantization and never invent zero', () => {
  assert.equal(interactionSummary([], 2).inpUpperBoundMs, 24);
  assert.equal(interactionSummary([{ duration: 200, interactionId: 1 }], 2).inpUpperBoundMs, 208);
  assert.throws(() => interactionSummary([], 0), /interaction/);
  assert.throws(() => interactionSummary([{ duration: NaN }], 1), /finite/);
});

test('a successful login page cannot stand in for the authenticated target', () => {
  const redirected = { ...lhr(), finalDisplayedUrl: 'http://127.0.0.1:8151/accounts/login/' };
  assert.throws(() => measurements(redirected, { inpUpperBoundMs: 10, interactionCount: 1 }, 50), /redirect/);
});

test('runner refuses remote targets and URLs carrying credentials or a path', () => {
  assert.equal(validateBaseURL('http://127.0.0.1:8151'), 'http://127.0.0.1:8151');
  for (const url of ['https://production.example', 'http://localhost:8151', 'http://user:pass@127.0.0.1:8151', 'http://127.0.0.1:8151/foo']) {
    assert.throws(() => validateBaseURL(url), /loopback origin/);
  }
});
