import type { Locator } from '@playwright/test';

import { updateSnapshotsFor } from '../../../playwright.config';
import { isPhone } from '../support/nav';
import { SCHEMES, forSchemes } from '../support/schemes';
import { settled } from '../support/settled';
import { expect, test } from '../support/test';
import {
  DYNAMIC,
  VISUAL_INSTANT,
  capture,
  freezeClock,
  masksFor,
  prefersReducedMotion,
  schemeOf,
  thawClock,
  visualWorld,
} from '../support/visual';

// The visual harness's own check (spec D9, plan T10). It runs everywhere, on every project, because it
// compares nothing with a committed baseline: it proves that what the baselines rest on holds here.
// A local run never writes a baseline; the visual workspace's Home photographs the same two seconds
// later and with the clock 90 days on (the server's frozen clock and the browser's moved together);
// the elements that print the real date or a time relative to it are there to be masked; a region's
// photograph masks what shows in it and never what the region covers; each scheme of forSchemes
// reaches the page; and a visual world is shown with reduced motion (spec D7 and D9), in either scheme,
// so no baseline photographs a transition.

/** Ninety days after the visual instant, at the same hour of the day. */
const NINETY_DAYS_ON = '2027-04-03T09:00:00+05:30';

/** What the masks cover, element by element: `dynamic` for a data-visual-dynamic element, else its test id. */
async function masked(masks: Locator[]): Promise<string[]> {
  const names: string[] = [];
  for (const mask of masks) {
    names.push(
      ...(await mask.evaluateAll(
        (elements, dynamic) =>
          elements.map((element) =>
            element.matches(dynamic) ? 'dynamic' : ((element as HTMLElement).dataset.testid ?? element.tagName),
          ),
        DYNAMIC,
      )),
    );
  }
  return names;
}

test.afterEach(async ({ harness }) => {
  await thawClock(harness);
});

test('a baseline is written only by the baseline run, never by a local or a compare run', async ({}, testInfo) => {
  const runs: [Record<string, string | undefined>, 'all' | 'none'][] = [
    [{}, 'none'],
    [{ CI: '1' }, 'none'], // CLAUDE.md's local CI=1 runs
    [{ E2E_VISUAL: '1' }, 'none'],
    [{ CI: '1', E2E_VISUAL: '1' }, 'none'], // CI's visual job: compares only
    [{ E2E_UPDATE_BASELINES: '1' }, 'none'],
    [{ CI: '1', E2E_UPDATE_BASELINES: '1' }, 'none'],
    [{ E2E_VISUAL: '1', E2E_UPDATE_BASELINES: '1' }, 'none'], // locally, even with both switches
    [{ CI: '1', E2E_VISUAL: '1', E2E_UPDATE_BASELINES: '1' }, 'all'], // the baseline workflow
  ];
  for (const [env, expected] of runs) {
    expect(updateSnapshotsFor(env), JSON.stringify(env)).toBe(expected);
  }
  expect(testInfo.config.updateSnapshots, 'this run writes no baseline').toBe(updateSnapshotsFor(process.env));
  if (!(process.env.CI && process.env.E2E_UPDATE_BASELINES === '1')) {
    expect(testInfo.config.updateSnapshots).toBe('none');
  }
});

test('the visual Home photographs the same two seconds later and 90 days on', async ({ page, harness, as }) => {
  const world = await visualWorld(page, harness);
  expect(world.instant).toBe(VISUAL_INSTANT);
  const home = `/workspace/${world.workspace_id}/studio/`;

  await as({ email: world.users.owner.email });
  expect((await page.goto(home))?.status()).toBe(200);
  await expect(page.getByTestId('home-today')).toBeVisible();
  expect(await page.evaluate(() => Date.now()), "the browser's clock is frozen with the server's").toBe(
    Date.parse(VISUAL_INSTANT),
  );
  // What prints the real date or a time from it, each marked to be masked: the greeting, today's date,
  // Recent work's "… ago" (three briefs) and the thread's two message times.
  await expect(page.locator(DYNAMIC)).toHaveCount(7);
  await expect(page.getByTestId('home-today').locator(DYNAMIC)).toHaveCount(1);
  await expect(page.getByTestId('home-thread').locator(DYNAMIC)).toHaveCount(2);
  const first = await capture(page);

  await page.waitForTimeout(2_000); // the point of the check: real time passes, the picture does not move
  expect((await capture(page)).equals(first), 'two seconds later, byte for byte').toBe(true);

  await freezeClock(page, harness, NINETY_DAYS_ON);
  await as({ email: world.users.owner.email }); // a session made at the new instant (the old one has expired)
  expect((await page.goto(home))?.status()).toBe(200);
  await expect(page.getByTestId('home-today')).toBeVisible();
  expect(
    (await capture(page)).equals(first),
    'with the clock 90 days on, byte for byte: nothing unmasked follows the clock',
  ).toBe(true);
});

test('a region is masked where something shows in it, never where the region covers it', async ({ page, harness, as }) => {
  const world = await visualWorld(page, harness);
  await as({ email: world.users.owner.email });
  expect((await page.goto(`/workspace/${world.workspace_id}/studio/`))?.status()).toBe(200);
  await expect(page.getByTestId('home-today')).toBeVisible();
  const dynamic = Array<string>(7).fill('dynamic');

  // The whole page: every element that prints the real date.
  expect(await masked(await masksFor(page)), 'the page').toEqual(dynamic);
  // Home's own region: the same seven, all inside it, and on a phone the phone bar that floats over it.
  expect(await masked(await masksFor(page.getByTestId('main-content'))), "Home's region").toEqual(
    isPhone(page) ? [...dynamic, 'phone-bar'] : dynamic,
  );

  // The New post sheet lies over Home's greeting and today's date, and on a phone over the phone bar:
  // none of them shows in the sheet's photograph, so none is masked there (their boxes would paint over
  // the sheet's title, its field and its Send). The sheet prints no date of its own.
  await page.getByTestId('new-post-open').click();
  await expect(page.getByTestId('new-post-team-idea')).toBeFocused();
  const sheet = page.getByTestId('new-post-sheet');
  await settled(sheet, 'the New post sheet');
  expect(await masked(await masksFor(sheet)), 'the sheet').toEqual([]);
});

forSchemes((scheme) => {
  test(`forSchemes shows the page in ${scheme}`, async ({ page }) => {
    expect(SCHEMES).toContain(scheme);
    expect(await schemeOf(page)).toBe(scheme);
  });

  test(`a visual world is shown with reduced motion, in ${scheme}`, async ({ page, harness, as }) => {
    const world = await visualWorld(page, harness);
    await as({ email: world.users.owner.email });
    expect((await page.goto(`/workspace/${world.workspace_id}/studio/`))?.status()).toBe(200);
    await expect(page.getByTestId('home-today')).toBeVisible();
    expect(await prefersReducedMotion(page), 'visualWorld asks for reduced motion').toBe(true);
    expect(await schemeOf(page), 'and keeps the scheme the spec chose').toBe(scheme);
    // The stylesheet's global reduced-motion rule took it: an element given a 300 ms transition (in its
    // own style, which the rule's !important outranks) gets the rule's 0.01 ms instead.
    const milliseconds = await page.evaluate(() => {
      const probe = document.createElement('div');
      probe.style.transition = 'opacity 300ms linear';
      document.body.append(probe);
      const seconds = parseFloat(getComputedStyle(probe).transitionDuration);
      probe.remove();
      return seconds * 1000;
    });
    expect(milliseconds, 'a 300 ms transition runs for 0.01 ms').toBeLessThan(1);
  });
});
