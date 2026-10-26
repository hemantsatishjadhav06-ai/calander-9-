// Authenticated, local-only Lighthouse CI without @lhci/cli's vulnerable dependency tree.
// Start the e2e server with --reset --no-worker --static manifest, then:
//   LIGHTHOUSE_BASE_URL=http://127.0.0.1:8151 node tests/lighthouse/run.mjs
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

import lighthouse from 'lighthouse';
import { chromium, request } from '@playwright/test';

import { evaluate, interactionSummary, measurements, validateBaseURL, validateConfig } from './budgets.mjs';
import { startLocalProxy } from './network.mjs';
import { withCleanAuditTabs, withCpuSlowdown } from './lifecycle.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const config = JSON.parse(await readFile(path.join(root, '.lighthouserc.json'), 'utf8'));
validateConfig(config);
const origin = validateBaseURL(process.env.LIGHTHOUSE_BASE_URL || 'http://127.0.0.1:8151');
const runId = new Date().toISOString().replaceAll(':', '-');
const output = path.resolve(process.env.LIGHTHOUSE_OUTPUT_DIR || path.join(root, '.lighthouseci', runId));
await mkdir(output, { recursive: true });
const summary = { runId, origin, lighthouseVersion: null, browserVersion: null, measurement: config.smbean.interactionMeasurement, status: 'running', pages: [] };
const profile = await mkdtemp(path.join(os.tmpdir(), 'smbean-lighthouse-'));
let context;
let api;
let sessionSecret;
let proxy;
const blocked = [];

async function save(name, content) {
  if (sessionSecret && content.includes(sessionSecret)) throw new Error('Refusing to save a report containing the session cookie.');
  await writeFile(path.join(output, name), content);
}

async function fixture(name, data) {
  const response = await api.post(`/__e2e__/fixture/${name}`, { data });
  if (!response.ok()) throw new Error(`E2E fixture ${name} answered ${response.status()}.`);
  return response.json();
}

async function checkPage(page, target, testId) {
  const response = await page.goto(target, { waitUntil: 'load' });
  if (!response?.ok() || page.url() !== target) throw new Error('The authenticated target failed or redirected.');
  await page.getByTestId(testId).waitFor({ state: 'visible' });
}

function compressedScript(url) {
  // Node fetch transparently decodes gzip; use raw HTTP to measure what a gzip client receives.
  if (new URL(url).origin !== origin) throw new Error('Script escaped the local server.');
  return new Promise((resolve, reject) => {
    const req = http.get(url, { headers: { 'Accept-Encoding': 'gzip' }, timeout: 15000 }, (res) => {
      if (res.statusCode !== 200) { res.resume(); reject(new Error(`Script answered ${res.statusCode}.`)); return; }
      const chunks = [];
      let size = 0;
      res.on('data', (chunk) => {
        size += chunk.length;
        if (size > 5_000_000) { res.destroy(); reject(new Error('Script response exceeds 5 MB.')); }
        else chunks.push(chunk);
      });
      res.on('error', reject);
      res.on('end', () => {
        const bytes = Buffer.concat(chunks);
        const encoding = res.headers['content-encoding'];
        if (encoding && encoding !== 'gzip') { reject(new Error(`Unexpected script encoding: ${encoding}`)); return; }
        // Count gzip bytes even for small files WhiteNoise intentionally sends without compression.
        resolve(encoding === 'gzip' ? bytes.length : gzipSync(bytes).length);
      });
    });
    req.on('timeout', () => req.destroy(new Error('Script request timed out.')));
    req.on('error', reject);
  });
}

async function gzipBytes(lhr, page) {
  const scripts = [...new Set(lhr.audits['network-requests'].details.items.filter((item) => item.resourceType === 'Script').map((item) => item.url))];
  if (!scripts.length) throw new Error('No script resources were measured.');
  let bytes = 0;
  for (const url of scripts) bytes += await compressedScript(url);
  // Inline application code is still JavaScript, even though its bytes travel in the HTML.
  const inline = await page.evaluate(() => [...document.scripts].filter((script) => !script.src).map((script) => script.textContent || '').join('\n'));
  return bytes + gzipSync(inline).length;
}

async function measureInteractions(page, name, reviewId) {
  const cdp = await context.newCDPSession(page);
  return withCpuSlowdown(cdp, async () => {
    await page.evaluate(() => {
      if (!PerformanceObserver.supportedEntryTypes.includes('event') || !performance.eventCounts) throw new Error('Event Timing is unavailable.');
      window.__smbeanTiming = { entries: [], before: (performance.eventCounts.get('click') || 0) + (performance.eventCounts.get('keydown') || 0) };
      window.__smbeanTiming.observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (entry.interactionId) window.__smbeanTiming.entries.push({ interactionId: entry.interactionId, duration: entry.duration, name: entry.name, target: entry.target?.getAttribute?.('data-testid') });
        }
      });
      window.__smbeanTiming.observer.observe({ type: 'event', buffered: false, durationThreshold: 16 });
    });
    if (name === 'home') {
      const composer = page.getByTestId('thread-composer-body');
      await composer.click();
      await composer.pressSequentially('Plan next week', { delay: 40 });
      await composer.press('ControlOrMeta+A');
      await composer.press('Backspace');
    } else if (name === 'approvals') {
      const details = page.getByTestId(`approvals-row-${reviewId}`).getByTestId('approvals-row-details');
      await details.click();
      await details.click();
    } else {
      const listResponse = page.waitForResponse((response) => response.url().includes('_switch_mode=1'));
      await page.getByTestId('calendar-mode-list').click();
      if (!(await listResponse).ok()) throw new Error('Calendar list switch failed.');
      const calendarResponse = page.waitForResponse((response) => response.url().includes('_switch_mode=1'));
      await page.getByTestId('calendar-mode-calendar').click();
      if (!(await calendarResponse).ok()) throw new Error('Calendar mode switch failed.');
      await page.getByTestId('calendar-shell').waitFor();
    }
    // The picker now initializes only when opened. Include that first opening in
    // the interaction budget so load-time work cannot simply be moved out of sight.
    if (await page.getByTestId('mobile-menu-toggle').isVisible()) await page.getByTestId('mobile-menu-toggle').click();
    await page.getByTestId('sidebar-new-toggle').click();
    await page.getByTestId('sidebar-new-idea').click();
    await page.getByTestId('idea-emoji-toggle').click();
    await page.getByTestId('idea-emoji-option').first().waitFor();
    await page.getByTestId('idea-emoji-search').pressSequentially('sparkles', { delay: 40 });
    await page.getByTestId('idea-emoji-option').click();
    await page.getByTestId('idea-close').click();
    // Event Timing is delivered after the next paint, not synchronously at click resolution.
    await page.waitForTimeout(250);
    const measurement = await page.evaluate(() => {
      const state = window.__smbeanTiming;
      state.entries.push(...state.observer.takeRecords().filter((entry) => entry.interactionId).map((entry) => ({ interactionId: entry.interactionId, duration: entry.duration, name: entry.name, target: entry.target?.getAttribute?.('data-testid') })));
      state.observer.disconnect();
      const count = (performance.eventCounts.get('click') || 0) + (performance.eventCounts.get('keydown') || 0) - state.before;
      return { interactionCount: count, entries: state.entries };
    });
    return interactionSummary(measurement.entries, measurement.interactionCount);
  });
}

try {
  api = await request.newContext({ baseURL: origin, timeout: 15000, maxRedirects: 0 });
  const ping = await api.get('/__e2e__/ping');
  if (!ping.ok() || !(await ping.json()).ok) throw new Error('Start the isolated e2e server with --reset --no-worker --static manifest first.');
  const session = await fixture('session', { role: 'owner' });
  sessionSecret = session.cookie.value;
  const review = await fixture('publishing_review_post', { caption: 'Lighthouse review fixture: site visits this Saturday.' });
  await fixture('publishing_scheduled_post', { caption: 'Lighthouse calendar fixture: site visits this Saturday.', days_ahead: 1 });
  proxy = await startLocalProxy(origin, blocked);
  context = await chromium.launchPersistentContext(profile, {
    headless: true, viewport: { width: 412, height: 823 }, deviceScaleFactor: 1.75, isMobile: true, hasTouch: true,
    args: ['--remote-debugging-port=0', '--disable-background-networking', `--proxy-server=${proxy.url}`, '--proxy-bypass-list=<-loopback>'],
    serviceWorkers: 'block',
  });
  await context.addCookies([{ ...session.cookie, url: origin }]);
  await context.route('**/*', (route) => {
    const url = new URL(route.request().url());
    if (url.origin === origin || ['data:', 'blob:'].includes(url.protocol)) return route.continue();
    blocked.push(url.origin);
    return route.abort('blockedbyclient');
  });
  const port = Number((await readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]);
  summary.browserVersion = context.browser()?.version() || 'Chromium';
  const pages = [
    { name: 'home', testId: 'home-today' },
    { name: 'approvals', testId: 'approvals-list' },
    { name: 'calendar', testId: 'calendar-shell' },
  ];
  for (let index = 0; index < pages.length; index++) {
    const { name, testId } = pages[index];
    const target = new URL(config.ci.collect.url[index], origin).href;
    const result = { name, path: config.ci.collect.url[index], runs: [] };
    summary.pages.push(result);
    for (let run = 1; run <= config.ci.collect.numberOfRuns; run++) {
      const page = await context.newPage();
      try {
        await checkPage(page, target, testId);
        const cache = await context.newCDPSession(page);
        await cache.send('Network.clearBrowserCache');
        await cache.detach();
        const openPagesBeforeAudit = context.pages().length;
        const audit = await withCleanAuditTabs(context, () => lighthouse(target, {
          ...config.ci.collect.settings, port, output: ['html', 'json'], logLevel: 'error', disableStorageReset: true,
        }));
        const openPagesAfterAudit = context.pages().length;
        if (!audit) throw new Error('Lighthouse returned no report.');
        summary.lighthouseVersion = audit.lhr.lighthouseVersion;
        await save(`${name}-${run}.html`, audit.report[0]);
        await save(`${name}-${run}.json`, audit.report[1]);
        await checkPage(page, target, testId);
        const scripts = await gzipBytes(audit.lhr, page);
        const interaction = await measureInteractions(page, name, review.post_id);
        const values = measurements(audit.lhr, interaction, scripts);
        result.runs.push({ run, values, interaction, openPagesBeforeAudit, openPagesAfterAudit, cpuThrottlingReset: true });
        console.log(`${name} ${run}/3: performance=${Math.round(values.performance * 100)}, LCP=${Math.round(values.lcp)}ms, CLS=${values.cls.toFixed(3)}, TBT(diagnostic)=${Math.round(values.tbt)}ms, lab INP<=${values.inp}ms, JS gzip=${values.gzipBytes}B`);
      } finally { await page.close(); }
    }
    Object.assign(result, evaluate(result.runs.map((run) => run.values), config));
  }
  const network = await api.get('/__e2e__/probe/refused_network');
  if (!network.ok() || (await network.json()).hosts.length || blocked.length) throw new Error('The performance run attempted an external request.');
  summary.status = summary.pages.every((page) => page.passed) ? 'passed' : 'failed';
  console.table(summary.pages.map(({ name, passed, medians }) => ({ page: name, passed, ...medians })));
  console.log('INP is a lab Event Timing upper bound for the documented inputs, not field p75 Core Web Vitals. No budgets are warnings.');
  if (summary.status !== 'passed') process.exitCode = 1;
} catch (error) {
  summary.status = 'failed';
  summary.error = String(error.message).replaceAll(sessionSecret || '\0', '[session]');
  console.error(summary.error);
  process.exitCode = 1;
} finally {
  if (context) await context.close();
  if (proxy) await proxy.close();
  if (api) await api.dispose();
  await rm(profile, { recursive: true, force: true });
  await save('summary.json', JSON.stringify(summary, null, 2));
  console.log(`Lighthouse reports: ${path.relative(root, output)}`);
}
