// Visual baselines (spec D9, plan T10): photograph a screen and compare it with the committed baseline.
//
//   const world = await visualWorld(page, harness);        // freeze the clock, then the visual workspace
//   await as({ email: world.users.owner.email });
//   await page.goto(`/workspace/${world.workspace_id}/studio/`);
//   await snap(page.getByTestId('home-today'), 'home-today');   // or snap(page, 'home') for a whole state
//   // test.afterEach: await thawClock(harness);
//
// A baseline only holds if the page cannot move under it. The server's clock is frozen at
// VISUAL_INSTANT (the `visual_clock` fixture, tests/e2e/server/steps/visual.py) and the browser's with
// page.clock; the visual workspace is put back to the same rows on every call; what still prints the
// real date or a time relative to it carries `data-visual-dynamic` in the template and is masked
// here, and so is the phone bar when a locator's box reaches under it.
//
// Comparing is switched on by E2E_VISUAL=1, which only CI's visual job and the baseline workflow set.
// Not by CI: CLAUDE.md documents local `CI=1` runs, and a local machine's fonts are not the runner's,
// so anywhere else snap() skips its test with VISUAL_SKIP_REASON. Baselines are written only by the
// baseline workflow (CI, E2E_VISUAL=1 and E2E_UPDATE_BASELINES=1 together, playwright.config.ts).
import type { Locator, Page } from '@playwright/test';

import { updateSnapshotsFor } from '../../../playwright.config';
import type { Harness } from './harness';
import { settled } from './settled';
import { expect, test } from './test';

/** Where the visual specs freeze the clock: Sun 3 Jan 2027 09:00 in the visual workspace's time zone. */
export const VISUAL_INSTANT = '2027-01-03T09:00:00+05:30';

export const VISUAL_SKIP_REASON = 'baselines are made and compared in CI (D9)';

/** The one selector a spec may use that is not a test id: for masking only, never to find or click. */
export const DYNAMIC = '[data-visual-dynamic]';

/** Shell parts that float over a screen's own region (test ids), masked in a locator's photograph. */
const FLOATING_SHELL = ['phone-bar'] as const;

type Env = Record<string, string | undefined>;

/** Whether a run with this environment compares baselines (only CI's visual jobs set E2E_VISUAL=1). */
export function comparesBaselines(env: Env = process.env): boolean {
  return env.E2E_VISUAL === '1';
}

/** Whether a run with this environment writes baselines: the baseline workflow, and nothing else. */
export function writesBaselines(env: Env = process.env): boolean {
  return updateSnapshotsFor(env) === 'all';
}

/** For a visual spec file: skip every test in it, with the reason, unless this run compares. */
export function visualSpecsOnly(): void {
  test.skip(!comparesBaselines(), VISUAL_SKIP_REASON);
}

export type VisualWorld = {
  workspace_id: string;
  organisation_id: string;
  workspace_name: string;
  timezone: string;
  instant: string;
  week: string;
  users: Record<'owner' | 'editor', { id: string; email: string }>;
  accounts: Record<'instagram' | 'linkedin_company' | 'facebook', { id: string; name: string }>;
  posts: { id: string; at: string; platform_posts: { id: string; platform: string; status: string }[] }[];
  briefs: { id: string; status: string; title: string }[];
  conversation: { id: string; messages: string[] };
};

/** Freeze the server's clock (and hold its worker) and the browser's at `at`. Clear with thawClock. */
export async function freezeClock(page: Page, harness: Harness, at: string = VISUAL_INSTANT): Promise<void> {
  const answer = await harness.fixture<{ frozen: boolean; now: string }>('visual_clock', { at });
  expect(answer.frozen, 'the server froze its clock').toBe(true);
  await page.clock.setFixedTime(new Date(at));
}

/** The real clock again, on the server; its worker goes on. Call it after each visual test. */
export async function thawClock(harness: Harness): Promise<void> {
  await harness.fixture('visual_clock', {});
}

/** The clock frozen first, then the visual workspace put back: its rows are made while nothing else runs. */
export async function visualWorld(page: Page, harness: Harness, at: string = VISUAL_INSTANT): Promise<VisualWorld> {
  await freezeClock(page, harness, at);
  return harness.fixture<VisualWorld>('visual_workspace', {});
}

/** The colour scheme the page is shown in (`test.use({ colorScheme })` or page.emulateMedia). */
export async function schemeOf(page: Page): Promise<'light' | 'dark'> {
  return page.evaluate(() => (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
}

function isPage(target: Locator | Page): target is Page {
  return typeof (target as Page).goto === 'function';
}

async function nextFrames(page: Page): Promise<void> {
  await page.evaluate(() => new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
}

/** No request in flight (htmx's own class marks one), every font loaded, nothing fading in or moving. */
async function atRest(page: Page, target: Locator | Page): Promise<void> {
  await page.waitForLoadState('networkidle');
  await expect
    .poll(() => page.evaluate(() => document.querySelectorAll('.htmx-request').length), { message: 'HTMX requests finished' })
    .toBe(0);
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  const region = isPage(target)
    ? (await page.getByTestId('main-content').count()) > 0
      ? page.getByTestId('main-content')
      : page.locator('body')
    : target;
  await settled(region, 'the photographed region');
  await nextFrames(page);
}

function masks(page: Page, target: Locator | Page): Locator[] {
  const found = [page.locator(DYNAMIC)];
  if (!isPage(target)) found.push(...FLOATING_SHELL.map((id) => page.getByTestId(id)));
  return found;
}

const SHOT = { animations: 'disabled', caret: 'hide' } as const;

/**
 * The photograph a baseline is compared with, without comparing: the page (its viewport) or a
 * locator's box, at rest, with the dynamic elements masked. The harness's own check uses it.
 */
export async function capture(target: Locator | Page): Promise<Buffer> {
  const page = isPage(target) ? target : target.page();
  await atRest(page, target);
  const options = { ...SHOT, mask: masks(page, target) };
  return isPage(target) ? target.screenshot(options) : target.screenshot(options);
}

/**
 * Compare `target` with its baseline, `<name>-<scheme>-<project>.png` under tests/e2e/__screenshots__/.
 * Skips the test with VISUAL_SKIP_REASON unless E2E_VISUAL=1, and refuses a run that would write a
 * baseline outside the baseline workflow (`--update-snapshots` given by hand).
 */
export async function snap(target: Locator | Page, name: string): Promise<void> {
  test.skip(!comparesBaselines(), VISUAL_SKIP_REASON);
  const mode = test.info().config.updateSnapshots;
  if (mode !== 'none' && !writesBaselines()) {
    throw new Error(
      `This run would write baselines (updateSnapshots: ${mode}). Only the baseline workflow writes them ` +
        '(.github/workflows/visual-baselines.yml); a screenshot update needs a `visual:` commit (CLAUDE.md).',
    );
  }
  const page = isPage(target) ? target : target.page();
  await atRest(page, target);
  const file = `${name}-${await schemeOf(page)}.png`;
  const options = { ...SHOT, mask: masks(page, target) };
  if (isPage(target)) await expect(target).toHaveScreenshot(file, options);
  else await expect(target).toHaveScreenshot(file, options);
}
