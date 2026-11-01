// What the pair specs and the light diff share (plan T12): the side, the data both servers get, and
// one way to bring a page to rest and photograph it.
import fs from 'node:fs';
import path from 'node:path';

import { type Page, type TestInfo, expect } from '@playwright/test';

import { PAIRS_DIR, pairMasks, pairRun } from '../../../playwright.pairs.config';
import type { Harness } from '../support/harness';
import { settled } from '../support/settled';

export type PairSide = 'before' | 'after';

/** One state of a pair: where it is, the test id that proves it is the right screen, how to reach it. */
export type PairState = {
  name: string;
  path: (workspace: string) => string;
  /** A test id the state must show. Until it is on the page, the state fails and writes nothing. */
  hook: string;
  /** Steps after the page is at rest (open a menu, a dialog) before the photograph. */
  prepare?: (page: Page) => Promise<void>;
};

/** The side a pair spec takes: `PAIR_SIDE=before` for main's server, otherwise this branch's. */
export function pairSide(): PairSide {
  if (pairRun === 'diff') throw new Error('A pair spec runs with `npm run pairs`, not `pairs:diff`.');
  return pairRun;
}

/** The captions of the two posts every pair and the diff show; used to find them again. */
export const PAIR_DATA = {
  review: 'Pair fixture: the Saturday site visit, for review.',
  scheduled: 'Pair fixture: the Saturday site visit, on the calendar.',
} as const;

/**
 * The same two posts on whichever server `page` and `harness` talk to, once: a post waiting for
 * review and one approved and scheduled, through the publishing fixtures main already has (the
 * Lighthouse runner uses them). A second run finds them on the Approvals page and adds nothing, so
 * both servers of a pair or of the diff hold the same rows however often it runs.
 */
export async function ensurePairData(page: Page, harness: Harness): Promise<void> {
  const workspace = harness.ids.workspace_a;
  const approvals = await page.request.get(`/workspace/${workspace}/approvals/`, { maxRedirects: 0 });
  expect(approvals.status(), 'the owner opens Approvals to look for the pair data').toBe(200);
  if ((await approvals.text()).includes(PAIR_DATA.review)) return;
  await harness.fixture('publishing_review_post', { caption: PAIR_DATA.review });
  await harness.fixture('publishing_scheduled_post', { caption: PAIR_DATA.scheduled, days_ahead: 1 });
}

const MAX_HEIGHT = 8000;

async function nextFrames(page: Page): Promise<void> {
  await page.evaluate(() => new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
}

/** No HTMX request in flight, every font loaded, nothing still fading in or moving. */
async function atRest(page: Page, hook: string, what: string): Promise<void> {
  await page.waitForLoadState('networkidle');
  await expect.poll(() => page.locator('.htmx-request').count(), { message: `${what}: HTMX requests finished` }).toBe(0);
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  await settled(page.getByTestId(hook).first(), what);
  await nextFrames(page);
}

/**
 * The app's content scrolls inside the shell (`#main-content` and the scroller in it), not the
 * document, so a full-page screenshot would hold one screen. For the diff, grow the viewport until no
 * scroller that can grow hides anything (at most 8,000 px): one image then holds the whole page as it
 * lays out at this width. A scroller whose height does not follow the viewport (a `max-h-*` list, a
 * fixed height) keeps its own scrolling: once a step leaves it hiding as much as before, it no longer
 * counts, and a step that uncovered nothing anywhere is undone.
 */
async function growToContent(page: Page): Promise<void> {
  // What each scroller hides, keyed by its place in the document (the DOM does not change meanwhile).
  const hidden = () =>
    page.evaluate(() => {
      const found: Record<string, number> = {};
      const root = document.scrollingElement;
      if (root && root.scrollHeight > root.clientHeight) found.document = root.scrollHeight - root.clientHeight;
      document.querySelectorAll('*').forEach((element, index) => {
        if (element.scrollHeight <= element.clientHeight || element.getClientRects().length === 0) return;
        if (/(auto|scroll)/.test(getComputedStyle(element).overflowY)) found[index] = element.scrollHeight - element.clientHeight;
      });
      return found;
    });
  const fixed = new Set<string>();
  const most = (found: Record<string, number>) =>
    Math.max(0, ...Object.entries(found).filter(([key]) => !fixed.has(key)).map(([, value]) => value));
  let found = await hidden();
  for (let step = 0; step < 6 && most(found) > 0; step++) {
    const size = page.viewportSize();
    if (!size || size.height >= MAX_HEIGHT) return;
    await page.setViewportSize({ width: size.width, height: Math.min(MAX_HEIGHT, size.height + most(found)) });
    await nextFrames(page);
    const now = await hidden();
    const counted = Object.keys(found).filter((key) => !fixed.has(key));
    const stuck = counted.filter((key) => (now[key] ?? 0) >= found[key]);
    stuck.forEach((key) => fixed.add(key));
    if (stuck.length === counted.length) {
      // No scroller uncovered anything: the step only made room nothing used.
      await page.setViewportSize(size);
      await nextFrames(page);
      found = await hidden();
    } else {
      found = now;
    }
  }
}

/**
 * Open `url`, require its hook, bring it to rest and photograph it with the time-printing elements
 * masked: the screen as the device shows it, or (`grow`) the whole page. Fails, writing nothing, when
 * the page redirects, answers an error or lacks its hook.
 */
export async function capture(
  page: Page,
  url: string,
  options: { hook: string; what: string; prepare?: (page: Page) => Promise<void>; scale: 'css' | 'device'; grow: boolean },
): Promise<Buffer> {
  const { hook, what } = options;
  const response = await page.goto(url);
  expect(response?.status(), `${what}: ${url} answers 200`).toBe(200);
  const asked = new URL(url, page.url());
  const landed = new URL(page.url());
  expect(`${landed.pathname}${landed.search}`, `${what}: no redirect`).toBe(`${asked.pathname}${asked.search}`);
  await expect(
    page.getByTestId(hook).first(),
    `${what}: the page has no data-testid="${hook}". Is this the server for this side, and has the screen ` +
      'that adds the hook been built yet?',
  ).toBeVisible();
  await atRest(page, hook, what);
  if (options.prepare) {
    await options.prepare(page);
    await atRest(page, hook, what);
  }
  if (options.grow) {
    await growToContent(page);
    await atRest(page, hook, what);
  }
  return page.screenshot({
    animations: 'disabled',
    caret: 'hide',
    scale: options.scale,
    mask: pairMasks.map((selector) => page.locator(selector)),
  });
}

/**
 * Photograph one state of a pair, the screen at the device's size (390 x 844, 1440 x 900, D9), to
 * test-results/pairs/<pair>/<side>/<state>-<project>.png.
 */
export async function shootState(
  page: Page,
  testInfo: TestInfo,
  { pair, side, state, workspace }: { pair: string; side: PairSide; state: PairState; workspace: string },
): Promise<string> {
  const what = `${pair} ${side} ${state.name} (${testInfo.project.name})`;
  const image = await capture(page, state.path(workspace), {
    hook: state.hook,
    what,
    prepare: state.prepare,
    scale: 'device',
    grow: false,
  });
  const file = path.join(PAIRS_DIR, pair, side, `${state.name}-${testInfo.project.name}.png`);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, image);
  return file;
}
