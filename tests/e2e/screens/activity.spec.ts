// Activity (spec D4, R4; docs/specs/02-cut-and-merge.md): /workspace/<id>/studio/activity/ shows the
// team at work (the live board) and, for people who may create posts, the routines with the three
// presets. A viewer sees the board and no routines section.
//
// The editor opens Activity from the navigation (the sidebar on desktop, the drawer behind More on
// a phone). Nothing is added: a preset taken in the seeded workspace would run on its schedule.
// The old /studio/team/ and /studio/routines/ answer a 301 here.
import { expectLit, go } from '../support/nav';
import { settled } from '../support/settled';
import { expect, test } from '../support/test';

/** apps/studio/routines.SUGGESTIONS, in order. */
const PRESETS = ['morning', 'monday', 'replies'];

test('an editor sees the live board and the routine presets on Activity', async ({ page, as, axe, harness, network }) => {
  const since = Date.now() / 1000;
  const { workspace_a: workspace } = harness.ids;
  await as('editor');
  await page.goto(`/workspace/${workspace}/studio/`);
  const href = await go(page, 'activity');
  expect(href).toBe(`/workspace/${workspace}/studio/activity/`);
  expect(new URL(page.url()).pathname).toBe(href);
  await expectLit(page, 'activity');

  const board = page.getByTestId('activity-board');
  await expect(board).toBeVisible();
  // The board refreshes itself while the page is open.
  await expect(board).toHaveAttribute('hx-trigger', /^every \d+s /);
  const routines = page.getByTestId('activity-routines');
  await expect(routines).toBeVisible();
  for (const key of PRESETS) await expect(routines.getByTestId(`routine-preset-${key}`)).toBeVisible();
  await settled(board, 'the live board');
  await axe(page, 'Activity (editor)');

  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});

test('a viewer sees the board and no routines section', async ({ page, as, axe, harness }) => {
  const { workspace_a: workspace } = harness.ids;
  const viewer = await harness.fixture<{ email: string }>('workspace_member', { role: 'viewer' });
  await as({ email: viewer.email });
  await page.goto(`/workspace/${workspace}/calendar/`);
  await go(page, 'activity');
  await expectLit(page, 'activity');

  await expect(page.getByTestId('activity-board')).toBeVisible();
  await expect(page.getByTestId('activity-routines')).toHaveCount(0);
  for (const key of PRESETS) await expect(page.getByTestId(`routine-preset-${key}`)).toHaveCount(0);
  await settled(page.getByTestId('activity-board'), 'the live board');
  await axe(page, 'Activity (viewer)');
});

test('the old Team and Routines pages land on Activity', async ({ page, as, axe, harness }) => {
  const { workspace_a: workspace } = harness.ids;
  await as('editor');
  const activity = `/workspace/${workspace}/studio/activity/`;
  for (const from of [`/workspace/${workspace}/studio/team/`, `/workspace/${workspace}/studio/routines/`]) {
    const response = await page.goto(from);
    expect(response?.status()).toBe(200);
    const first = response!.request().redirectedFrom();
    expect(first, `${from} redirected`).not.toBeNull();
    expect((await first!.response())?.status(), `${from} moved for good`).toBe(301);
    expect(new URL(page.url()).pathname).toBe(activity);
    await expect(page.getByTestId('activity-board')).toBeVisible();
    await settled(page.getByTestId('activity-board'), 'the live board');
    await axe(page, `Activity, from ${from} (editor)`);
  }
  // Routines lands on its section.
  expect(new URL(page.url()).hash).toBe('#routines');
  await expect(page.getByTestId('activity-routines')).toBeInViewport();
});
