// What the pair specs and the light diff share (plan T12): the side, the data both servers get, one
// way to bring a page to rest and photograph it, and the tests a pair file declares.
import fs from 'node:fs';
import path from 'node:path';

import { type Page, type TestInfo, expect } from '@playwright/test';

import { PAIRS_DIR, pairMasks, pairRun } from '../../../playwright.pairs.config';
import type { Harness } from '../support/harness';
import type { Scheme } from '../support/schemes';
import { settled } from '../support/settled';
import { test } from '../support/test';
import { decodePng } from './compare.cjs';

export type PairSide = 'before' | 'after';

/** One state of a pair: where it is, the test id that proves it is the right screen, how to reach it. */
export type PairState = {
  name: string;
  path: (workspace: string) => string;
  /** A test id the state must show. Until it is on the page, the state fails and writes nothing. */
  hook: string;
  /** Steps after the page is at rest (open a menu, a dialog) before the photograph. */
  prepare?: (page: Page) => Promise<void>;
  /**
   * The device's colour scheme, from the first request on; light when left out (the config's). A dark
   * state's name ends in `-dark`, so its image never takes a light one's place. Only a page declared
   * dark-ready (apps/common/screens.py DARK_READY) turns dark, so a dark state belongs to an after side.
   */
  scheme?: Scheme;
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

/**
 * The colour the diff paints a masked element in (Playwright's default, named so a pair can check it
 * has none: the owner's pair shows every element, D9).
 */
const MASK_RGB = [255, 0, 255] as const;
const MASK_COLOR = `rgb(${MASK_RGB.join(', ')})`;

/** How many pixels of a photograph are the mask colour. */
function maskedPixels(png: Buffer): number {
  const { data } = decodePng(png);
  let count = 0;
  for (let i = 0; i < data.length; i += 4) {
    if (data[i] === MASK_RGB[0] && data[i + 1] === MASK_RGB[1] && data[i + 2] === MASK_RGB[2]) count++;
  }
  return count;
}

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
 * Open `url`, require its hook, bring it to rest and photograph it: the screen as the device shows it,
 * or (`grow`) the whole page. `mask` paints the config's time-printing elements (`pairMasks`) over,
 * for the diff only; the owner's pair is never masked. Fails, writing nothing, when the page
 * redirects, answers an error or lacks its hook.
 */
export async function capture(
  page: Page,
  url: string,
  options: {
    hook: string;
    what: string;
    prepare?: (page: Page) => Promise<void>;
    scale: 'css' | 'device';
    grow: boolean;
    mask: boolean;
  },
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
    mask: options.mask ? pairMasks.map((selector) => page.locator(selector)) : [],
    maskColor: MASK_COLOR,
  });
}

/**
 * Photograph one state of a pair, the screen at the device's size (390 x 844, 1440 x 900, D9) with
 * nothing masked, to test-results/pairs/<pair>/<side>/<state>-<project>.png.
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
    mask: false,
  });
  expect(maskedPixels(image), `${what}: the owner sees the whole screen, nothing masked`).toBe(0);
  const file = path.join(PAIRS_DIR, pair, side, `${state.name}-${testInfo.project.name}.png`);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, image);
  return file;
}

/**
 * The tests of one pair file: a test per state of the side this run takes (`PAIR_SIDE`), each signing
 * in as the owner, making sure of the pair data and photographing the state. The two lists stay
 * apart because a screen's after names hooks main does not have.
 */
export function pairTests(pair: string, states: Readonly<Record<PairSide, readonly PairState[]>>): void {
  const side = pairSide();
  test.describe(side === 'before' ? 'before: main' : 'after: this branch', () => {
    for (const state of states[side]) {
      const scheme = state.scheme ?? 'light';
      if ((scheme === 'dark') !== state.name.endsWith('-dark')) {
        throw new Error(`${pair} ${state.name}: a dark state's name ends in -dark, and only a dark state's does`);
      }
      test.describe(`${scheme} scheme`, () => {
        test.use({ colorScheme: scheme });
        test(state.name, async ({ page, as, harness }, testInfo) => {
          await as('owner');
          await ensurePairData(page, harness);
          await shootState(page, testInfo, { pair, side, state, workspace: harness.ids.workspace_a });
        });
      });
    }
  });
}
