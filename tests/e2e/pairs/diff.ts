// pairs:diff, the light diff (plan T12; T3's acceptance): the a11y sweep's eleven pages and the three
// Lighthouse pages, at 390 and 1440 px, light, rendered on main's server and on this branch's with
// the same data, each whole page in one image with the time-printing elements masked. Fails when any
// pair differs by more than 0.1 % of its pixels, listing the page and the ratio.
//
//   # main's server, from a worktree of 045978b (tests/e2e/README.md, Pairs and the light diff)
//   DB_NAME=smbean_main_e2e ../calander-9-/.venv/bin/python -m tests.e2e.server --reset --no-worker --port 8231
//   # then, from this branch (its server starts on E2E_PORT when none is listening there)
//   PAIR_BEFORE_PORT=8231 E2E_PORT=8221 DB_NAME=smbean_p3_e2e npm run pairs:diff
//
// Writes test-results/pairs/diff/<project>/<page>-{before,after}.png, <page>-diff.png for a pair
// over the limit (the differing pixels in red) and summary.json. Uses only hooks main has.
import fs from 'node:fs';
import path from 'node:path';

import { type APIRequest, type APIRequestContext, type Browser, type BrowserContext, expect, test } from '@playwright/test';

import { PAIRS_DIR, pairDevices } from '../../../playwright.pairs.config';
import { Harness } from '../support/harness';
import { guardNetwork, type NetworkGuard } from '../support/network';
import { DIFF_LIMIT, decodePng, diffImages, encodePng } from './compare.cjs';
import { capture, ensurePairData } from './support';

type DiffPage = { name: string; path: (workspace: string) => string };

/** The a11y sweep's pages (apps/common/tests/test_a11y_sweep.py, `_pages`), then Lighthouse's. */
const DIFF_PAGES: readonly DiffPage[] = [
  { name: 'calendar', path: (ws) => `/workspace/${ws}/calendar/` },
  { name: 'compose', path: (ws) => `/workspace/${ws}/compose/` },
  { name: 'create', path: (ws) => `/workspace/${ws}/create/` },
  { name: 'categories', path: (ws) => `/workspace/${ws}/categories/` },
  { name: 'inbox', path: (ws) => `/workspace/${ws}/inbox/` },
  { name: 'saved-replies', path: (ws) => `/workspace/${ws}/inbox/saved-replies/` },
  { name: 'media', path: (ws) => `/workspace/${ws}/media/` },
  { name: 'members', path: () => '/members/' },
  // The sweep's "agency" page is Home, which is also Lighthouse's first page.
  { name: 'home', path: (ws) => `/workspace/${ws}/studio/` },
  { name: 'activity', path: (ws) => `/workspace/${ws}/studio/activity/` },
  { name: 'brand', path: (ws) => `/workspace/${ws}/studio/brand/` },
  // .lighthouserc.json's other two.
  { name: 'approvals', path: (ws) => `/workspace/${ws}/approvals/` },
  { name: 'calendar-month', path: (ws) => `/workspace/${ws}/calendar/?mode=calendar&view=month` },
];

/** The shell's own test id, on every page that extends base.html on main and on this branch. */
const HOOK = 'main-content';

type Side = {
  name: 'before' | 'after';
  baseURL: string;
  api: APIRequestContext;
  harness: Harness;
  context: BrowserContext;
  guard: NetworkGuard;
  since: number;
};

function beforeURL(): string {
  const port = Number(process.env.PAIR_BEFORE_PORT);
  if (!Number.isInteger(port) || port <= 0) {
    throw new Error(
      'Set PAIR_BEFORE_PORT to the port of a server started from a worktree of main ' +
        '(tests/e2e/README.md, Pairs and the light diff).',
    );
  }
  return `http://127.0.0.1:${port}`;
}

async function openSide(
  name: Side['name'],
  baseURL: string,
  browser: Browser,
  request: APIRequest,
  device: (typeof pairDevices)[keyof typeof pairDevices],
): Promise<Side> {
  const api = await request.newContext({ baseURL });
  const harness = await Harness.connect(api);
  const worker = await harness.probe<{ alive: boolean }>('worker');
  expect(
    worker.alive,
    `the ${name} server runs its worker, which changes rows between the two renders of a page; ` +
      'start it with --no-worker',
  ).toBe(false);
  const context = await browser.newContext({
    ...device,
    baseURL,
    colorScheme: 'light',
    timezoneId: 'Asia/Kolkata',
    serviceWorkers: 'block',
  });
  const guard = await guardNetwork(context, baseURL);
  const session = await harness.fixture<{ cookie: { name: string; value: string } }>('session', { role: 'owner' });
  await context.addCookies([{ ...session.cookie, url: baseURL, httpOnly: true, sameSite: 'Lax' }]);
  return { name, baseURL, api, harness, context, guard, since: Date.now() / 1000 };
}

/** The hosts the server refused while this side was open; its browser and request contexts close either way. */
async function closeSide(side: Side): Promise<string[]> {
  try {
    const refused = await side.harness.probe<{ hosts: string[] }>('refused_network', { since: side.since });
    return refused.hosts;
  } finally {
    await side.context.close();
    await side.api.dispose();
  }
}

test('light rendering: before against after', async ({ browser, playwright, baseURL }, testInfo) => {
  test.setTimeout(10 * 60_000);
  const device = pairDevices[testInfo.project.name as keyof typeof pairDevices];
  expect(device, `no device for project ${testInfo.project.name}`).toBeTruthy();
  const out = path.join(PAIRS_DIR, 'diff', testInfo.project.name);
  const results: { page: string; path: string; ratio: number; pixels: number; size: string }[] = [];
  const before = await openSide('before', beforeURL(), browser, playwright.request, device);
  const sides: Side[] = [before];
  let closed: PromiseSettledResult<string[]>[] = [];
  try {
    const after = await openSide('after', String(baseURL), browser, playwright.request, device);
    sides.push(after);
    expect(before.baseURL, 'the before and after servers are two servers').not.toBe(after.baseURL);
    expect(before.harness.ids.workspace_a, 'both servers hold the same seeded workspace').toBe(after.harness.ids.workspace_a);

    fs.rmSync(out, { recursive: true, force: true });
    fs.mkdirSync(out, { recursive: true });

    const pages = { before: await before.context.newPage(), after: await after.context.newPage() };
    await ensurePairData(pages.before, before.harness);
    await ensurePairData(pages.after, after.harness);
    const workspace = after.harness.ids.workspace_a;

    // The whole page in one image, the time-printing elements masked (the diff only; never a pair).
    const shot = { hook: HOOK, scale: 'css', grow: true, mask: true } as const;
    for (const page of DIFF_PAGES) {
      const url = page.path(workspace);
      const images = {
        before: await capture(pages.before, url, { ...shot, what: `before ${page.name}` }),
        after: await capture(pages.after, url, { ...shot, what: `after ${page.name}` }),
      };
      // Each side's viewport grew to its own page; the next page starts from the device's again.
      await pages.before.setViewportSize(device.viewport);
      await pages.after.setViewportSize(device.viewport);
      fs.writeFileSync(path.join(out, `${page.name}-before.png`), images.before);
      fs.writeFileSync(path.join(out, `${page.name}-after.png`), images.after);
      const result = diffImages(decodePng(images.before), decodePng(images.after), { image: true });
      if (result.ratio > DIFF_LIMIT && result.image) {
        fs.writeFileSync(path.join(out, `${page.name}-diff.png`), encodePng(result.image));
      }
      results.push({ page: page.name, path: url, ratio: result.ratio, pixels: result.pixels, size: `${result.width}x${result.height}` });
    }
  } finally {
    // Every side that opened closes, even when a page failed, so no browser or request context outlives
    // the run. A failure here never hides the page's own error; the checks below read what it found.
    closed = await Promise.allSettled(sides.map(closeSide));
  }
  for (const [index, side] of sides.entries()) {
    const refused = closed[index];
    if (refused.status === 'rejected') throw refused.reason;
    expect(refused.value, `the ${side.name} server tried to reach outside the machine`).toEqual([]);
    expect(side.guard.blocked, `the ${side.name} pages asked for something off the server`).toEqual([]);
  }

  fs.writeFileSync(path.join(out, 'summary.json'), `${JSON.stringify({ limit: DIFF_LIMIT, results }, null, 2)}\n`);
  const percent = (ratio: number) => `${(ratio * 100).toFixed(3)} %`;
  const lines = results.map((row) => `${row.page.padEnd(15)} ${percent(row.ratio).padStart(9)}  ${row.pixels} px of ${row.size}`);
  console.log(`[${testInfo.project.name}] light diff, before against after (limit ${percent(DIFF_LIMIT)}):\n${lines.join('\n')}`);
  const over = results.filter((row) => row.ratio > DIFF_LIMIT).map((row) => `${row.page} (${row.path}): ${percent(row.ratio)}`);
  expect(over, `pages over ${percent(DIFF_LIMIT)} at ${testInfo.project.name}; see ${path.relative(process.cwd(), out)}`).toEqual([]);
});
