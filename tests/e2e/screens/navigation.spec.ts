// The navigation (spec D10, R1, R2, R7; docs/specs/02-cut-and-merge.md): six places and the
// Settings gear, the phone bar, the notifications bell and the command palette (Go to).
//
// The places test makes a workspace of its own (team_workspace: no blog switch, so no Blog item,
// whatever other specs leave in the seeded workspace A) and signs its owner in. On desktop the
// sidebar holds Home, Approvals, Calendar, Inbox, Analytics, Activity and the gear, and nothing
// else: the old More disclosure is gone. On a phone the phone bar's Home, Approvals, Calendar and
// Inbox reach their screens, and its More opens the drawer, the same sidebar, where Analytics,
// Activity and the gear are. Each screen is checked by its address, the lit place and, where the
// screen has one, its own hook; axe runs on every screen and on the open drawer.
//
// The bell and Go to appear twice in the page (the sidebar header on desktop, the phone's top bar
// below 1024px); a test takes the one this device shows. The bell's badge counts a fresh person's
// one unread notification, and the bell opens the drawer that lists it; Escape closes it and the
// focus goes back to the bell. Go to opens with its button and with Ctrl/Cmd-K, filters the
// places as you type, opens one with Enter (from the field, or on a link reached with the arrow
// keys), and Escape hands the focus back.
import { settled } from '../support/settled';
import { expectLit, go, isPhone, openMore, phonePlaces } from '../support/nav';
import { expect, test } from '../support/test';

type TeamWorkspace = { workspace_id: string; users: Record<'owner' | 'editor' | 'client', { id: string; email: string }> };

/** Each place, the screen's own path under the workspace, and a hook the screen always renders (if any). */
const PLACES: { key: string; path: string; screen: string | null }[] = [
  { key: 'home', path: 'studio/', screen: 'home-today' },
  { key: 'approvals', path: 'approvals/', screen: 'approvals-list' },
  { key: 'calendar', path: 'calendar/', screen: 'calendar-shell' },
  { key: 'inbox', path: 'inbox/', screen: 'inbox-detail-panel' },
  { key: 'analytics', path: 'analytics/', screen: null },
  { key: 'activity', path: 'studio/activity/', screen: 'activity-board' },
  { key: 'settings', path: 'settings/', screen: 'settings-panel-brand' },
];

test('the six places and the gear lead to their screens; there is no More on the sidebar', async ({
  page,
  as,
  axe,
  harness,
  network,
}) => {
  const since = Date.now() / 1000;
  const made = await harness.fixture<TeamWorkspace>('team_workspace', {});
  const base = `/workspace/${made.workspace_id}/`;
  await as({ email: made.users.owner.email });
  const first = await page.goto(`${base}studio/`);
  expect(first?.status()).toBe(200);

  // The sidebar: the places in order, then the gear, and no other control (no More disclosure).
  const hooks = await page
    .getByTestId('sidebar-nav')
    .evaluate((nav) =>
      [...nav.querySelectorAll('a, button, details, summary')].map(
        (node) => node.getAttribute('data-testid') ?? node.tagName.toLowerCase(),
      ),
    );
  expect(hooks).toEqual(PLACES.map(({ key }) => `nav-${key}`));

  for (const { key, path, screen } of PLACES) {
    const href = await go(page, key);
    expect(href).toBe(`${base}${path}`);
    expect(new URL(page.url()).pathname, `${key} lands on its screen`).toMatch(new RegExp(`^${base}${path}`));
    await expectLit(page, key);
    if (screen) await expect(page.getByTestId(screen), `the ${key} screen`).toBeAttached();
    if (isPhone(page)) {
      // The phone bar is on every one of these screens; More is lit where the bar has no item.
      await expect(page.getByTestId('phone-bar')).toBeVisible();
      for (const place of phonePlaces) {
        const lit = await page.getByTestId(`phone-bar-${place}`).getAttribute('aria-current');
        expect(lit === 'page', `phone bar ${place} lit on ${key}`).toBe(place === key);
      }
    } else {
      await expect(page.getByTestId('phone-bar'), 'no phone bar on desktop').toBeHidden();
    }
    if (key === 'activity') await settled(page.getByTestId('activity-board'), 'the live board');
    await axe(page, `${key} (owner)`);
  }

  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});

test('the phone bar’s More opens the drawer; desktop has no phone bar', async ({ page, as, axe, harness }) => {
  const { workspace_a: workspace } = harness.ids;
  await as('owner');
  await page.goto(`/workspace/${workspace}/calendar/`);
  if (!isPhone(page)) {
    await expect(page.getByTestId('phone-bar')).toBeHidden();
    await expect(page.getByTestId('phone-bar-more')).toBeHidden();
    await expect(page.getByTestId('sidebar-nav'), 'the sidebar is always there on desktop').toBeVisible();
    return;
  }
  const more = page.getByTestId('phone-bar-more');
  await expect(more).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByTestId('sidebar-nav'), 'the drawer starts closed, off the screen').not.toBeInViewport();
  await openMore(page);
  await expect(page.getByTestId('nav-activity')).toBeInViewport();
  await expect(page.getByTestId('nav-settings')).toBeInViewport();
  await axe(page, 'Menu drawer open from More');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('sidebar-nav'), 'Escape closes the drawer').not.toBeInViewport();
  await expect(more).toHaveAttribute('aria-expanded', 'false');
});

test('the notifications bell shows the unread count and opens the drawer', async ({ page, as, axe, harness }) => {
  const member = await harness.fixture<{ email: string }>('workspace_member', { role: 'editor' });
  const notice = await harness.fixture<{ id: string; unread: number }>('unread_notification', {
    email: member.email,
    title: 'E2E: a new person joined the team',
  });
  expect(notice.unread).toBe(1);
  await as({ email: member.email });
  await page.goto(`/workspace/${harness.ids.workspace_a}/studio/`);

  const bell = page.getByTestId('notifications-bell').filter({ visible: true });
  await expect(bell).toHaveCount(1);
  await expect(bell).toHaveAttribute('aria-label', 'Notifications, 1 unread');
  const badge = page.getByTestId('notification-badge').filter({ visible: true });
  await expect(badge).toHaveCount(1);
  await expect(badge).toHaveText('1');

  const loaded = page.waitForResponse(
    (response) => response.request().method() === 'GET' && new URL(response.url()).pathname === '/notifications/drawer/',
  );
  // From the keyboard, so the bell holds the focus before the drawer opens in every engine (WebKit
  // does not focus a button on a tap).
  await bell.focus();
  await page.keyboard.press('Enter');
  expect((await loaded).status()).toBe(200);
  const drawer = page.getByTestId('notifications-drawer');
  await expect(drawer).toBeVisible();
  await expect(drawer.getByTestId(`notifications-item-${notice.id}`)).toBeVisible();
  await settled(drawer, 'the notifications drawer');
  await axe(page, 'Notifications drawer', { include: '[data-testid="notifications-drawer"]' });

  await page.keyboard.press('Escape');
  await expect(drawer).toBeHidden();
  await expect(bell, 'the focus goes back to the bell').toBeFocused();
});

test('Go to opens with its button and Ctrl/Cmd-K, filters, opens a page with Enter, and Escape hands focus back', async ({
  page,
  as,
  axe,
  harness,
}) => {
  const { workspace_a: workspace } = harness.ids;
  await as('owner');
  await page.goto(`/workspace/${workspace}/studio/`);

  const button = page.getByTestId('palette-open').filter({ visible: true });
  await expect(button).toHaveCount(1);
  const dialog = page.getByTestId('palette-dialog');
  const field = page.getByTestId('palette-input');
  await expect(dialog).toBeHidden();

  // The button: the field takes the focus; typing filters the places and the Settings tabs.
  await button.click();
  await expect(dialog).toBeVisible();
  await expect(field).toBeFocused();
  await settled(dialog, 'Go to');
  await axe(page, 'Go to (open)', { include: '[data-testid="palette-dialog"]' });
  await field.fill('appro');
  await expect(page.getByTestId('palette-item-approvals')).toBeVisible();
  await expect(page.getByTestId('palette-item-settings-approvals')).toBeVisible();
  await expect(page.getByTestId('palette-item-home')).toBeHidden();
  await expect(page.getByTestId('palette-item-inbox')).toBeHidden();
  await axe(page, 'Go to (filtered)', { include: '[data-testid="palette-dialog"]' });
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  // From the keyboard, Go to has the focus when the dialog opens, and gets it back on Escape.
  await button.focus();
  await page.keyboard.press('Enter');
  await expect(dialog).toBeVisible();
  await expect(field, 'the field starts empty again').toHaveValue('');
  await expect(field).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(button, 'Escape hands the focus back to Go to').toBeFocused();

  // The keyboard alone: Ctrl/Cmd-K, type, an arrow to the link, Enter.
  await page.keyboard.press('ControlOrMeta+k');
  await expect(dialog).toBeVisible();
  await expect(field).toBeFocused();
  await page.keyboard.type('inbox');
  await expect(page.getByTestId('palette-item-inbox')).toBeVisible();
  await expect(page.getByTestId('palette-item-calendar')).toBeHidden();
  await page.keyboard.press('ArrowDown');
  await expect(page.getByTestId('palette-item-inbox')).toBeFocused();
  await Promise.all([page.waitForURL(`**/workspace/${workspace}/inbox/`), page.keyboard.press('Enter')]);
  await expectLit(page, 'inbox');

  // Enter in the field opens the first match.
  await page.keyboard.press('ControlOrMeta+k');
  await expect(field).toBeFocused();
  await page.keyboard.type('calendar');
  await expect(page.getByTestId('palette-item-calendar')).toBeVisible();
  await Promise.all([page.waitForURL(`**/workspace/${workspace}/calendar/`), page.keyboard.press('Enter')]);
  await expectLit(page, 'calendar');
  await axe(page, 'Calendar, opened from Go to');
});
