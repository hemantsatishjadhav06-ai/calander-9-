import type { Page } from '@playwright/test';

import { isPhone } from '../support/nav';
import { settled } from '../support/settled';
import { expect, test } from '../support/test';

// Reduced motion (Phase 3, T9; spec D7 and F5). With `prefers-reduced-motion: reduce`, nothing moves:
// the stylesheet's global rule cuts every animation and transition to 0.01 ms, and each motion class
// a rebuilt screen uses (styles.css: `.motion-rise`, `.motion-sheet-*`, `.motion-fill`, `.motion-snap`)
// has its own reduced form, so it does not run at all. A probe records every CSS animation and
// transition that starts in the document, with the duration the browser computed for it, and any
// animation still running (scripted ones included).
//
// First the probe proves it sees: without reduce, each motion class runs on its token (200 ms, a
// sheet's exit 140 ms), the sheet comes up from the bottom on a phone and in from the right on a
// desktop; with reduce, none of them runs. Then the shell: opening Go to and the notifications drawer
// moves nothing for longer than 0.01 ms. Screens 1 to 3 add their cases here: the New post sheet, a
// new message and the approve fill. apps/common/tests/test_motion.py checks the same in the source.

// `reducedMotion` is a context option, not a test option: `test.use({ reducedMotion })` is ignored.
test.use({ contextOptions: { reducedMotion: 'reduce' } });

/** The global rule's duration: anything longer under reduce is motion that escaped it. */
const REDUCED_MS = 0.01;

type Motion = { kind: 'animation' | 'transition' | 'running'; name: string; ms: number; on: string };

/** Start (or restart) recording what moves in the page. */
async function record(page: Page): Promise<void> {
  await page.evaluate(() => {
    const w = window as unknown as { motionSeen?: Motion[] };
    if (w.motionSeen) {
      w.motionSeen.length = 0;
      return;
    }
    const seen: Motion[] = [];
    w.motionSeen = seen;
    const milliseconds = (list: string, index: number): number => {
      const parts = list.split(',').map((part) => part.trim());
      const value = parts[index % parts.length];
      const ms = value.endsWith('ms') ? parseFloat(value) : parseFloat(value) * 1000;
      return Math.round(ms * 1000) / 1000;
    };
    // A test id, else the id ('#htmx-progress'), else the tag and its first classes.
    const describe = (element: Element): string =>
      element.getAttribute('data-testid') ||
      (element.id
        ? `#${element.id}`
        : `${element.tagName.toLowerCase()}${
            typeof element.className === 'string' && element.className.trim()
              ? `.${element.className.trim().split(/\s+/).slice(0, 3).join('.')}`
              : ''
          }`);
    document.addEventListener(
      'transitionrun',
      (event) => {
        if (!(event.target instanceof Element)) return;
        const style = getComputedStyle(event.target, event.pseudoElement || null);
        const properties = style.transitionProperty.split(',').map((part) => part.trim());
        let index = properties.indexOf(event.propertyName);
        if (index < 0) index = Math.max(properties.indexOf('all'), 0);
        seen.push({ kind: 'transition', name: event.propertyName, ms: milliseconds(style.transitionDuration, index), on: describe(event.target) });
      },
      true,
    );
    document.addEventListener(
      'animationstart',
      (event) => {
        if (!(event.target instanceof Element)) return;
        const style = getComputedStyle(event.target, event.pseudoElement || null);
        const index = Math.max(style.animationName.split(',').map((part) => part.trim()).indexOf(event.animationName), 0);
        seen.push({ kind: 'animation', name: event.animationName, ms: milliseconds(style.animationDuration, index), on: describe(event.target) });
      },
      true,
    );
  });
}

/** What moved since `record`, and every finite animation still running now (a scripted one too). */
async function recorded(page: Page): Promise<Motion[]> {
  return page.evaluate(() => {
    const seen = [...((window as unknown as { motionSeen?: Motion[] }).motionSeen ?? [])];
    for (const animation of document.getAnimations()) {
      if (animation.playState !== 'running') continue;
      const timing = animation.effect?.getComputedTiming();
      const ms = Number(timing?.duration);
      if (!Number.isFinite(Number(timing?.endTime))) continue;
      const target = (animation.effect as KeyframeEffect | null)?.target;
      seen.push({
        kind: 'running',
        name: (animation as Animation & { animationName?: string; transitionProperty?: string }).animationName ??
          (animation as Animation & { transitionProperty?: string }).transitionProperty ??
          'script',
        ms: Math.round(ms * 1000) / 1000,
        on: target ? target.getAttribute('data-testid') || target.tagName.toLowerCase() : 'document',
      });
    }
    return seen;
  });
}

function longerThanReduced(motion: Motion[]): Motion[] {
  return motion.filter((entry) => entry.ms > REDUCED_MS);
}

/**
 * Put one element per motion class on the page and make each move as a screen will: a message
 * arrives (rise), a button fills, a chip snaps back to its place, a sheet enters and another leaves.
 * Returns where the sheet starts from (`.motion-sheet-out`'s offset in px). The elements go after.
 */
async function moveEachMotionClass(page: Page): Promise<{ x: number; y: number }> {
  return page.evaluate(async () => {
    const host = document.createElement('div');
    host.setAttribute('aria-hidden', 'true');
    host.style.cssText = 'position:fixed;left:0;top:0;width:40px;height:40px;pointer-events:none;';
    document.body.append(host);
    const make = (name: string, classes: string): HTMLElement => {
      const element = document.createElement('div');
      element.dataset.testid = `motion-probe-${name}`;
      element.className = classes;
      element.style.cssText = 'position:absolute;inset:0;';
      host.append(element);
      return element;
    };
    const fill = make('fill', 'motion-fill');
    fill.style.backgroundColor = 'rgb(255, 255, 255)';
    const snap = make('snap', 'motion-snap');
    snap.style.transform = 'translateX(24px)';
    const enter = make('sheet-enter', 'motion-sheet-enter motion-sheet-out');
    const leave = make('sheet-leave', 'motion-sheet-leave motion-sheet-in');
    const start = getComputedStyle(enter).transform;
    const from = new DOMMatrixReadOnly(start === 'none' ? '' : start);
    void host.offsetWidth; // the starting styles are computed, so the changes below transition
    fill.style.backgroundColor = 'rgb(17, 86, 65)';
    snap.style.transform = 'none';
    enter.classList.replace('motion-sheet-out', 'motion-sheet-in');
    leave.classList.replace('motion-sheet-in', 'motion-sheet-out');
    make('rise', 'motion-rise');
    await new Promise((resolve) => setTimeout(resolve, 400));
    host.remove();
    return { x: from.m41, y: from.m42 };
  });
}

function probeOnly(motion: Motion[]): Motion[] {
  return motion.filter((entry) => entry.on.startsWith('motion-probe-')).sort((a, b) => a.on.localeCompare(b.on));
}

test('the probe sees each motion class run on its token, and none of them under reduce', async ({ page, as, harness }) => {
  await as('owner');
  await page.goto(`/workspace/${harness.ids.workspace_a}/studio/`);
  await expect(page.getByTestId('main-content')).toBeVisible();

  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await record(page);
  const from = await moveEachMotionClass(page);
  expect(probeOnly(await recorded(page)), 'each motion class runs on --dur-snap, a sheet leaves on --dur-exit').toEqual([
    { kind: 'transition', name: 'background-color', ms: 200, on: 'motion-probe-fill' },
    { kind: 'animation', name: 'motion-rise', ms: 200, on: 'motion-probe-rise' },
    { kind: 'transition', name: 'transform', ms: 200, on: 'motion-probe-sheet-enter' },
    { kind: 'transition', name: 'transform', ms: 140, on: 'motion-probe-sheet-leave' },
    { kind: 'transition', name: 'transform', ms: 200, on: 'motion-probe-snap' },
  ]);
  expect(from, isPhone(page) ? 'the sheet comes up from the bottom' : 'the sheet comes in from the right').toEqual(
    isPhone(page) ? { x: 0, y: 40 } : { x: 40, y: 0 },
  );

  await page.emulateMedia({ reducedMotion: 'reduce' });
  await record(page);
  const still = await moveEachMotionClass(page);
  expect(probeOnly(await recorded(page)), 'under reduce no motion class runs at all').toEqual([]);
  expect(still, 'under reduce the sheet appears in place').toEqual({ x: 0, y: 0 });
});

test('opening Go to moves nothing for longer than 0.01 ms', async ({ page, as, harness }) => {
  await as('owner');
  await page.goto(`/workspace/${harness.ids.workspace_a}/studio/`);
  const button = page.getByTestId('palette-open').filter({ visible: true });
  await expect(button).toHaveCount(1);

  await record(page);
  await button.click();
  const dialog = page.getByTestId('palette-dialog');
  await expect(dialog).toBeVisible();
  await expect(page.getByTestId('palette-input')).toBeFocused();
  const opening = await recorded(page);
  await settled(dialog, 'Go to');

  expect(longerThanReduced([...opening, ...(await recorded(page))]), 'what moved for longer than 0.01 ms').toEqual([]);
});

test('opening the notifications drawer moves nothing for longer than 0.01 ms', async ({ page, as, harness }) => {
  await as('owner');
  await page.goto(`/workspace/${harness.ids.workspace_a}/studio/`);
  const bell = page.getByTestId('notifications-bell').filter({ visible: true });
  await expect(bell).toHaveCount(1);

  await record(page);
  const loaded = page.waitForResponse(
    (response) => response.request().method() === 'GET' && new URL(response.url()).pathname === '/notifications/drawer/',
  );
  await bell.click();
  const drawer = page.getByTestId('notifications-drawer');
  await expect(drawer).toBeVisible();
  const opening = await recorded(page);
  expect((await loaded).status()).toBe(200);
  await expect(page.locator('#notification-drawer-content')).not.toContainText('Loading notifications');
  await settled(drawer, 'the notifications drawer');

  const motion = [...opening, ...(await recorded(page))];
  // The drawer's content loads over HTMX, so the progress bar at the top runs: the probe sees it,
  // cut to the global rule's 0.01 ms (its width does not move at all).
  expect(
    motion.filter((entry) => entry.on === '#htmx-progress'),
    'the progress bar fades in 0.01 ms and its width does not move',
  ).toEqual(expect.arrayContaining([{ kind: 'transition', name: 'opacity', ms: REDUCED_MS, on: '#htmx-progress' }]));
  expect(motion.filter((entry) => entry.on === '#htmx-progress' && entry.name === 'width')).toEqual([]);
  expect(longerThanReduced(motion), 'what moved for longer than 0.01 ms').toEqual([]);
});
