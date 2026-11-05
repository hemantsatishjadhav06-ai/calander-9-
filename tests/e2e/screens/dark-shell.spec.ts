// Home and Calendar in dark (Phase 3, T22; spec D2): the two pages screen 1's sheet lives on are
// declared dark-ready (apps/common/screens.py DARK_READY), so a dark device paints them dark from the
// first request. This spec is what declares them safe to: on the three devices, in dark,
//
//   - Home with waiting items, a brief card and a receipt (a workspace of its own, team_workspace, and
//     a request followed through the faked team with the home_request probe, as golden 3 does);
//   - Calendar's month, week and day, its four list tabs and the event form;
//   - posts selected in each selection bar: calendar-bulk-bar in the calendar view and
//     approvals-bulk-bar in the Approvals list tab;
//
// each passes axe (0 serious or critical), the canvas is the dark ink-50, and each selection bar's
// computed background is the inverse surface (still dark) with its labels, its icon and its divider
// readable on it. The Approvals list tab's selected filter chip stands 3:1 off the page and its words
// read on it (the owner's choice at T22: ink-900 with on-fill text, which a dark card does not swallow,
// where the inverse surface sat 1.32:1 on a card and 1.41:1 on the canvas). Approvals (/approvals/)
// shares the list partial but stays light until screen 3, so it is not visited here. The behavioural
// flows stay in the light specs (spec D10); this one only looks.
import type { Locator, Page } from '@playwright/test';

import { until } from '../support/poll';
import { settled } from '../support/settled';
import { expect, test } from '../support/test';

test.use({ colorScheme: 'dark' });

type Person = { id: string; email: string };
type TeamWorkspace = { workspace_id: string; users: Record<'owner' | 'editor' | 'client', Person> };
type HomeRequest = {
  ask: { status: string } | null;
  reply: { id: string; action: string } | null;
  confirm: { status: string } | null;
  brief: { id: string; status: string } | null;
};
type MadePost = { post_id: string; platform_posts: { id: string }[]; local: { date: string } };
type VisualWorld = { workspace_id: string; users: Record<'owner' | 'editor', Person> };
/** sRGB bytes and alpha, as a canvas reads a computed colour. */
type Rgba = [number, number, number, number];
/** A colour drawn (fg) and what is painted under it (bg), both opaque. */
type Painted = { what: string; fg: Rgba; bg: Rgba };

/** styles.css's dark --ink-50 (#0C0F13), the canvas in dark. */
const DARK_INK_50 = 'rgb(12, 15, 19)';
/** Under this a surface is dark: the bars' inverse surface, ink-900 #1C1F24 in their light scope, is 0.014. */
const DARK_LUMINANCE = 0.05;

const stopped = (status: string | undefined) => status === 'failed' || status === 'cancelled';

/** WCAG 2.x relative luminance of an opaque sRGB colour. */
function luminance([r, g, b]: Rgba): number {
  const channel = (value: number) => {
    const c = value / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** WCAG 2.x contrast ratio, to two decimals. */
function contrast(a: Rgba, b: Rgba): number {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return Math.round(((high + 0.05) / (low + 0.05)) * 100) / 100;
}

/** The page is dark: <html> says so, and the body and main paint the dark ink-50. */
async function expectDarkCanvas(page: Page, where: string): Promise<void> {
  await expect(page.locator('html'), `${where}: declared dark-ready`).toHaveAttribute('data-theme-ready', '');
  await expect(page.locator('html'), `${where}: the dark device's scheme`).toHaveAttribute('data-theme', 'dark');
  const painted = await page.getByTestId('main-content').evaluate((main) => {
    const probe = document.createElement('div');
    probe.style.background = 'var(--ink-50)';
    document.body.append(probe);
    const ink50 = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return { ink50, body: getComputedStyle(document.body).backgroundColor, main: getComputedStyle(main).backgroundColor };
  });
  expect(painted, `${where}: the canvas is the dark ink-50`).toEqual({
    ink50: DARK_INK_50,
    body: DARK_INK_50,
    main: DARK_INK_50,
  });
}

type BarReading = {
  /** The bar's surface (itself or its first descendant with an opaque fill), as computed. */
  background: string;
  /** What var(--surface-inverse) paints there. */
  inverse: string;
  surface: Rgba;
  /** Every element with words of its own (the count, the actions). */
  labels: Painted[];
  /** Every icon, in its control's colour. */
  icons: Painted[];
  /** Every divider: an aria-hidden element with a translucent fill and nothing in it, blended. */
  dividers: Painted[];
};

/** Read a selection bar as it is painted (each colour composited over what is under it). */
async function readBar(bar: Locator): Promise<BarReading> {
  return bar.evaluate((root) => {
    type Colour = [number, number, number, number];
    // A computed colour may be rgb(), oklab() or color() (a translucent utility is a color-mix);
    // a 1-pixel canvas reads any of them as sRGB bytes.
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 1;
    const context = canvas.getContext('2d', { willReadFrequently: true })!;
    const parse = (value: string): Colour => {
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = value;
      context.fillRect(0, 0, 1, 1);
      const [r, g, b, a] = context.getImageData(0, 0, 1, 1).data;
      return [r, g, b, a / 255];
    };
    const over = (top: Colour, under: Colour): Colour => {
      const a = top[3];
      return [top[0] * a + under[0] * (1 - a), top[1] * a + under[1] * (1 - a), top[2] * a + under[2] * (1 - a), 1];
    };
    const fill = (element: Element) => parse(getComputedStyle(element).backgroundColor);
    const elements = [root, ...Array.from(root.querySelectorAll('*'))].filter((el) => el.getClientRects().length > 0);
    const surface = elements.find((element) => fill(element)[3] === 1);
    if (!surface) throw new Error('the selection bar paints no opaque surface');
    const base = fill(surface);
    // What is painted behind an element: the surface, then every fill from it down to the element.
    const behind = (element: Element): Colour => {
      const chain: Element[] = [];
      for (let node: Element | null = element; node && node !== surface; node = node.parentElement) chain.unshift(node);
      return chain.reduce((colour, node) => (fill(node)[3] > 0 ? over(fill(node), colour) : colour), base);
    };
    const probe = document.createElement('div');
    probe.style.background = 'var(--surface-inverse)';
    surface.append(probe);
    const inverse = getComputedStyle(probe).backgroundColor;
    probe.remove();

    const labels: { what: string; fg: Colour; bg: Colour }[] = [];
    const icons: { what: string; fg: Colour; bg: Colour }[] = [];
    const dividers: { what: string; fg: Colour; bg: Colour }[] = [];
    for (const element of elements) {
      const own = Array.from(element.childNodes)
        .filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => node.textContent ?? '')
        .join('')
        .trim();
      if (own) labels.push({ what: own, fg: parse(getComputedStyle(element).color), bg: behind(element) });
      if (element.tagName.toLowerCase() === 'svg') {
        const control = element.closest('button');
        const what = control?.getAttribute('aria-label') ?? control?.textContent?.trim() ?? 'an icon';
        icons.push({ what, fg: parse(getComputedStyle(element).color), bg: behind(element.parentElement!) });
      }
      const tint = fill(element);
      if (element.getAttribute('aria-hidden') === 'true' && !element.children.length && !own && tint[3] > 0 && tint[3] < 1) {
        const under = behind(element.parentElement!);
        dividers.push({ what: 'the divider', fg: over(tint, under), bg: under });
      }
    }
    return { background: getComputedStyle(surface).backgroundColor, inverse, surface: base, labels, icons, dividers };
  });
}

/** The bar is the inverse surface, still dark, and what it says and shows reads on it. */
async function expectInverseBar(bar: Locator, what: string): Promise<void> {
  await settled(bar, what);
  const reading = await readBar(bar);
  expect(reading.background, `${what}: its background is the inverse surface`).toBe(reading.inverse);
  expect(luminance(reading.surface), `${what}: the inverse surface stays dark (${reading.background})`).toBeLessThan(
    DARK_LUMINANCE,
  );
  expect(
    reading.labels.map((label) => label.what),
    `${what}: its count and its actions`,
  ).toEqual(expect.arrayContaining([expect.stringMatching(/^\d+ selected$/)]));
  for (const label of reading.labels) {
    expect(contrast(label.fg, label.bg), `${what}: "${label.what}" reads 4.5:1 on the bar`).toBeGreaterThanOrEqual(4.5);
  }
  expect(reading.icons.length, `${what}: the clear icon`).toBeGreaterThan(0);
  for (const icon of reading.icons) {
    expect(contrast(icon.fg, icon.bg), `${what}: the ${icon.what} icon shows 3:1 on the bar`).toBeGreaterThanOrEqual(3);
  }
  expect(reading.dividers.length, `${what}: the divider after the count`).toBe(1);
  const [divider] = reading.dividers;
  expect(contrast(divider.fg, divider.bg), `${what}: the divider stays visible on the bar`).toBeGreaterThanOrEqual(1.5);
}

/**
 * The selected filter chip (aria-pressed) as painted: its fill and what it sits on, its words and its
 * count. Its selected state is its fill, so the fill stands 3:1 off the page (WCAG 1.4.11), and its
 * words read 4.5:1 on it.
 */
async function expectSelectedChip(chips: Locator, what: string): Promise<void> {
  const chip = chips.getByRole('button', { pressed: true });
  await expect(chip, `${what}: one chip is selected`).toHaveCount(1);
  const painted = await chip.evaluate((element) => {
    type Colour = [number, number, number, number];
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 1;
    const context = canvas.getContext('2d', { willReadFrequently: true })!;
    const parse = (value: string): Colour => {
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = value;
      context.fillRect(0, 0, 1, 1);
      const [r, g, b, a] = context.getImageData(0, 0, 1, 1).data;
      return [r, g, b, a / 255];
    };
    const over = (top: Colour, under: Colour): Colour => {
      const a = top[3];
      return [top[0] * a + under[0] * (1 - a), top[1] * a + under[1] * (1 - a), top[2] * a + under[2] * (1 - a), 1];
    };
    const ancestors: Element[] = [];
    for (let node = element.parentElement; node; node = node.parentElement) ancestors.unshift(node);
    const white: Colour = [255, 255, 255, 1];
    const page = ancestors.reduce((colour, node) => over(parse(getComputedStyle(node).backgroundColor), colour), white);
    const fill = over(parse(getComputedStyle(element).backgroundColor), page);
    const count = element.querySelector('span');
    return {
      page,
      fill,
      label: parse(getComputedStyle(element).color),
      count: count ? parse(getComputedStyle(count).color) : null,
    };
  });
  const standing = contrast(painted.fill, painted.page);
  expect(standing, `${what}: the selected chip stands 3:1 off the page`).toBeGreaterThanOrEqual(3);
  expect(contrast(painted.label, painted.fill), `${what}: its label reads 4.5:1 on it`).toBeGreaterThanOrEqual(4.5);
  expect(painted.count, `${what}: its count`).not.toBeNull();
  expect(contrast(painted.count!, painted.fill), `${what}: its count reads 4.5:1 on it`).toBeGreaterThanOrEqual(4.5);
}

/** Calendar in calendar mode, on *view*, on the day of *date*, with its grid settled. */
async function openView(page: Page, workspace: string, view: 'month' | 'week' | 'day', date: string): Promise<void> {
  const response = await page.goto(`/workspace/${workspace}/calendar/?mode=calendar&view=${view}&date=${date}`);
  expect(response?.status(), `Calendar ${view} answers`).toBe(200);
  await settled(page.getByTestId('calendar-shell'), `the ${view} view`);
}

/** Calendar in list mode on *tab*, with the page settled. */
async function openTab(page: Page, workspace: string, tab: 'queue' | 'drafts' | 'approvals' | 'sent'): Promise<void> {
  const response = await page.goto(`/workspace/${workspace}/calendar/?mode=list&tab=${tab}`);
  expect(response?.status(), `Calendar's ${tab} tab answers`).toBe(200);
  await expect(page.getByTestId(`publish-tab-${tab}`)).toHaveAttribute('aria-current', 'true');
  await settled(page.getByTestId('main-content'), `the ${tab} tab`);
}

/** Show or hide the event form (the page has no opener for it today: the shell's own flag shows it). */
async function eventForm(page: Page, shown: boolean): Promise<void> {
  await page.getByTestId('calendar-shell').evaluate((shell, value) => {
    const alpine = (window as unknown as { Alpine: { $data: (el: Element) => { showEventForm: boolean } } }).Alpine;
    alpine.$data(shell).showEventForm = value;
  }, shown);
}

test('Home in dark: waiting items, a brief card and a receipt pass axe on the dark canvas', async ({
  page,
  as,
  axe,
  harness,
}, testInfo) => {
  test.setTimeout(240_000);
  await harness.fixture('set_agent_delay', { seconds: 0 });
  const team = await harness.fixture<TeamWorkspace>('team_workspace', {});
  const home = `/workspace/${team.workspace_id}/studio/`;
  await as({ email: team.users.owner.email });
  const tag = `${testInfo.project.name}-${Date.now().toString(36)}`;
  const request = `Post about the Kokapet site visit ${tag} on Instagram and LinkedIn, mention free parking on visit days`;
  const read = () => harness.probe<HomeRequest>('home_request', { workspace_id: team.workspace_id, body: request });

  expect((await page.goto(home))?.status()).toBe(200);
  await expectDarkCanvas(page, 'Home');
  await axe(page, 'Home (dark)');

  // A request in the thread; the manager answers with the brief card.
  const thread = page.getByTestId('home-thread');
  await thread.getByTestId('thread-composer-body').fill(request);
  await thread.getByTestId('thread-composer-send').click();
  const asked = await until(
    read,
    (s) => stopped(s.ask?.status) || (s.ask?.status === 'done' && s.reply !== null),
    'the manager answers with a brief',
  );
  expect(asked.reply).toMatchObject({ action: 'new_post' });
  const card = thread.getByTestId(`thread-message-${asked.reply?.id}`).getByTestId('thread-brief-card');
  await expect(card).toBeVisible({ timeout: 20_000 });
  await settled(card, 'the brief card');
  await axe(page, 'Home with the brief card waiting for Go ahead (dark)');

  // Go ahead: the faked team makes the draft, which waits for review with its posting status.
  await card.getByTestId('thread-brief-go-ahead').click();
  const finished = await until(
    read,
    (s) => s.brief?.status === 'ready' || s.brief?.status === 'failed' || stopped(s.confirm?.status),
    'the team finishes the draft',
    150_000,
  );
  expect(finished.brief?.status).toBe('ready');

  expect((await page.goto(home))?.status()).toBe(200);
  await expectDarkCanvas(page, 'Home with the draft');
  const waiting = page.getByTestId('home-today').getByTestId('home-today-waiting');
  await expect(waiting.getByTestId(`home-today-post-${finished.brief?.id}`), 'Today: the draft waits').toBeVisible();
  await expect(page.getByTestId('home-thread').getByTestId('thread-brief-card').first(), 'the brief card').toBeVisible();
  const receipt = page.getByTestId('home-thread').locator('[data-publication-receipt]').first();
  await expect(receipt, "the draft's posting status (its receipt)").toBeVisible({ timeout: 20_000 });
  await settled(page.getByTestId('home-thread'), 'the thread');
  await axe(page, 'Home with waiting items, a brief card and a receipt (dark)');
});

test('Calendar in dark: month, week and day, the event form, and the selection bar in the calendar view', async ({
  page,
  as,
  axe,
  harness,
}) => {
  const workspace = harness.ids.workspace_a;
  const scheduled = await harness.fixture<MadePost>('publishing_scheduled_post', {
    author: 'editor',
    approver: 'owner',
    days_ahead: 2,
  });
  await harness.fixture<MadePost>('publishing_review_post', { author: 'editor', days_ahead: 2, hour: 15 });
  const chip = scheduled.platform_posts[0].id;
  await as('owner');

  for (const view of ['month', 'week', 'day'] as const) {
    await openView(page, workspace, view, scheduled.local.date);
    await expectDarkCanvas(page, `Calendar ${view}`);
    await expect(page.getByTestId(`calendar-chip-${chip}`), `the scheduled post on the ${view}`).toBeVisible();
    await axe(page, `Calendar ${view} (dark)`);
  }

  await openView(page, workspace, 'week', scheduled.local.date);
  await eventForm(page, true);
  const form = page.getByRole('heading', { name: 'Add an event' });
  await expect(form).toBeVisible();
  await settled(form, 'the event form');
  await axe(page, 'Calendar with the event form (dark)');
  await eventForm(page, false);

  // A post selected on the grid: the selection bar is the inverse surface, dark, and reads on it.
  await page.getByTestId(`calendar-select-${chip}`).click();
  const bulk = page.getByTestId('calendar-bulk-bar');
  await expectInverseBar(bulk, 'calendar-bulk-bar');
  await axe(page, 'Calendar week with a post selected (dark)');
  await page.getByTestId(`calendar-select-${chip}`).click();
  await expect(bulk).toBeHidden();
});

test('Calendar in dark: the four list tabs, and the selection bar in the Approvals list tab', async ({
  page,
  as,
  axe,
  harness,
}) => {
  const workspace = harness.ids.workspace_a;
  await harness.fixture<MadePost>('publishing_scheduled_post', { author: 'editor', approver: 'owner', days_ahead: 3 });
  const review = await harness.fixture<MadePost>('publishing_review_post', { author: 'editor', days_ahead: 3 });
  await as('owner');

  for (const tab of ['queue', 'drafts', 'approvals', 'sent'] as const) {
    await openTab(page, workspace, tab);
    await expectDarkCanvas(page, `Calendar's ${tab} tab`);
    await axe(page, `Calendar's ${tab} tab (dark)`);
  }

  // The Approvals list tab: its selected filter chip, then a post selected and its own selection bar.
  await openTab(page, workspace, 'approvals');
  const list = page.getByTestId('approvals-list');
  await expectSelectedChip(list.getByRole('group', { name: 'Filter by status' }), "the Approvals tab's filters");
  const row = list.getByTestId(`approvals-row-${review.post_id}`);
  await row.getByTestId('approvals-row-select').check();
  const bulk = page.getByTestId('approvals-bulk-bar');
  await expectInverseBar(bulk, 'approvals-bulk-bar');
  await axe(page, "Calendar's approvals tab with a post selected (dark)");
  await row.getByTestId('approvals-row-select').uncheck();
  await expect(bulk).toBeHidden();
});

test('Calendar in dark: drafts in their list tab pass axe', async ({ page, as, axe, harness }) => {
  // Workspace A holds no drafts of its own; the visual workspace keeps two (tests/e2e/server/steps/visual.py).
  const world = await harness.fixture<VisualWorld>('visual_workspace', {});
  await as({ email: world.users.owner.email });
  await openTab(page, world.workspace_id, 'drafts');
  await expectDarkCanvas(page, "Calendar's drafts tab");
  const rows = page.getByTestId('main-content').locator('[data-testid^="calendar-select-"]');
  await expect(rows.first(), 'a draft row').toBeVisible();
  await axe(page, "Calendar's drafts tab with drafts (dark)");
});
