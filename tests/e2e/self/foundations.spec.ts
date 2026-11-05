import type { Locator, Page } from '@playwright/test';

import type { Harness } from '../support/harness';
import { isPhone } from '../support/nav';
import { expect, test } from '../support/test';
import { expectReadSize, readSize } from '../support/type';

// Type and layout foundations (Phase 3, T6 and T7; spec D3, D4, F2 and F3). The body token is 16 px on
// the phones and 15 px on a desktop at 1440 x 900 (`--read-size` in styles.css); page titles and card
// titles use the system font's display cut at 700; nothing a person reads on Home, Approvals and the
// Calendar computes under 13 px; at 390 px none of those pages, the Calendar's month and list both, is
// wider than the screen; and a card (`.ui-card`) is padded 20 px below 1024 px and 24 px from 1024 px.
// The source guards (apps/common/tests/test_type_floor.py, test_spacing_grid.py) cover the templates
// and styles.css; this measures what the browser actually renders, the shell included.

const PHONE_WIDTH = 390;
const DESKTOP = { width: 1440, height: 900 };
const FLOOR = 13;
const WIDE = 1024;

type Place = { name: string; path: (workspace: string) => string; ready: string };

const PLACES: Place[] = [
  { name: 'Home', path: (w) => `/workspace/${w}/studio/`, ready: 'home-today' },
  { name: 'Approvals', path: (w) => `/workspace/${w}/approvals/`, ready: 'approvals-list' },
  { name: 'Calendar month', path: (w) => `/workspace/${w}/calendar/?mode=calendar&view=month`, ready: 'calendar-shell' },
  { name: 'Calendar list', path: (w) => `/workspace/${w}/calendar/?mode=list&tab=queue`, ready: 'publish-tab-queue' },
];

/** A post waiting for review (an Approvals row and Home's Today) and a scheduled one (the Calendar). */
async function somethingToShow(harness: Harness): Promise<void> {
  await harness.fixture('publishing_review_post', { author: 'editor', accounts: ['linkedin_company'], days_ahead: 3, hour: 10 });
  await harness.fixture('publishing_scheduled_post', { author: 'editor', approver: 'owner', days_ahead: 2 });
}

async function open(page: Page, harness: Harness, place: Place): Promise<void> {
  const response = await page.goto(place.path(harness.ids.workspace_a));
  expect(response?.status(), `${place.name} answers`).toBe(200);
  await expect(page.getByTestId(place.ready), `${place.name} is shown`).toBeVisible();
}

/** Each visible element that holds its own words and computes under the floor: "tag.class 'words' 12px". */
async function underTheFloor(page: Page, floor: number): Promise<string[]> {
  return page.evaluate((min) => {
    const found: string[] = [];
    for (const element of Array.from(document.body.querySelectorAll<HTMLElement>('*'))) {
      const words = Array.from(element.childNodes)
        .filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => node.textContent ?? '')
        .join(' ')
        .trim();
      if (!words || ['SCRIPT', 'STYLE', 'TEMPLATE', 'NOSCRIPT'].includes(element.tagName)) continue;
      if (!element.checkVisibility({ checkOpacity: false, checkVisibilityCSS: true })) continue;
      const size = parseFloat(getComputedStyle(element).fontSize);
      if (size < min) {
        const name = `${element.tagName.toLowerCase()}${element.className && typeof element.className === 'string' ? `.${element.className.trim().split(/\s+/).slice(0, 4).join('.')}` : ''}`;
        found.push(`${name} '${words.slice(0, 40)}' ${size}px`);
      }
    }
    return found;
  }, floor);
}

test('the body reads at 16 px on a phone and 15 px on a desktop at 1440 x 900', async ({ page, harness, as }) => {
  if (!isPhone(page)) await page.setViewportSize(DESKTOP);
  await as('owner');
  await open(page, harness, PLACES[0]);

  const width = await page.evaluate(() => window.innerWidth);
  const body = await page.locator('body').evaluate((element) => {
    const style = getComputedStyle(element);
    return { size: parseFloat(style.fontSize), leading: parseFloat(style.lineHeight) };
  });
  expect(body.size, `the body token at ${width}px`).toBe(isPhone(page) ? 16 : 15);
  expect(readSize(width)).toBe(body.size);
  expect(body.leading, `the body's leading at ${width}px`).toBeCloseTo(isPhone(page) ? 24 : 22, 1);
  await expectReadSize(page.locator('body'), 'the body');
});

test('page and card titles use the display cut at 700', async ({ page, harness, as }) => {
  if (!isPhone(page)) await page.setViewportSize(DESKTOP);
  await as('owner');
  await open(page, harness, PLACES[0]);

  for (const [what, heading] of [
    ['the page title', page.getByRole('heading', { level: 1 })],
    ["Today's card title", page.getByTestId('home-today').getByRole('heading', { level: 2 })],
  ] as const) {
    const style = await heading.evaluate((element) => {
      const computed = getComputedStyle(element);
      return { family: computed.fontFamily, weight: computed.fontWeight };
    });
    expect(style.weight, `${what} is 700`).toBe('700');
    expect(style.family, `${what} is in the display stack`).toContain('Segoe UI Variable Display');
    expect(style.family.startsWith('system-ui'), `${what} starts with the system font: ${style.family}`).toBe(true);
  }
});

test('nothing a person reads on Home, Approvals and the Calendar is under 13 px', async ({ page, harness, as }) => {
  if (!isPhone(page)) await page.setViewportSize(DESKTOP);
  await somethingToShow(harness);
  await as('owner');
  for (const place of PLACES) {
    await open(page, harness, place);
    expect(await underTheFloor(page, FLOOR), `${place.name}: text under ${FLOOR}px`).toEqual([]);
  }
});

test('at 390 px Home, Approvals and the Calendar month and list are no wider than the screen', async ({ page, harness, as }) => {
  await page.setViewportSize({ width: PHONE_WIDTH, height: page.viewportSize()?.height ?? 844 });
  await somethingToShow(harness);
  await as('owner');
  for (const place of PLACES) {
    await open(page, harness, place);
    const sizes = await page.evaluate(() => {
      const main = document.getElementById('main-content');
      return {
        inner: window.innerWidth,
        page: document.documentElement.scrollWidth,
        main: main ? main.scrollWidth - main.clientWidth : 0,
      };
    });
    expect(sizes.inner, 'the viewport is 390 px').toBe(PHONE_WIDTH);
    expect(sizes.page, `${place.name}: the page is no wider than the screen`).toBeLessThanOrEqual(sizes.inner);
    expect(sizes.main, `${place.name}: the main column does not scroll sideways`).toBeLessThanOrEqual(0);
  }
});

/** A card's padding, top, right, bottom and left, in px. */
async function padding(card: Locator): Promise<number[]> {
  return card.evaluate((element) => {
    const style = getComputedStyle(element);
    return [style.paddingTop, style.paddingRight, style.paddingBottom, style.paddingLeft].map(parseFloat);
  });
}

test('a card is padded 20 px below 1024 px and 24 px from 1024 px', async ({ page, harness, as }) => {
  await as('owner');
  await open(page, harness, PLACES[0]);

  // Today's card and the conversation's card (home-thread holds it; the wrapper is not a card itself).
  const cards: [string, Locator][] = [
    ["Today's card", page.getByTestId('home-today')],
    ["the conversation's card", page.getByTestId('home-thread').locator(':scope > .ui-card')],
  ];
  const widths = isPhone(page) ? [PHONE_WIDTH] : [PHONE_WIDTH, WIDE - 1, WIDE, DESKTOP.width];
  for (const width of widths) {
    await page.setViewportSize({ width, height: width >= WIDE ? DESKTOP.height : (page.viewportSize()?.height ?? 844) });
    const expected = width >= WIDE ? 24 : 20;
    for (const [what, card] of cards) {
      await expect(card, `${what} is a .ui-card`).toHaveClass(/(^|\s)ui-card(\s|$)/);
      expect(await padding(card), `${what}'s padding at ${width}px`).toEqual([expected, expected, expected, expected]);
    }
  }
});
