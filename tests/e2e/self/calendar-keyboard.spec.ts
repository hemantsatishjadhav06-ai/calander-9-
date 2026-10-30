import { expect, test } from '../support/test';
import { settled } from '../support/settled';

test('an empty past calendar week is reachable and scrollable with the keyboard', async ({ page, harness, as, axe }) => {
  const workspace = await harness.fixture<{
    workspace_id: string;
    users: { owner: { email: string } };
  }>('team_workspace', {});
  await as({ email: workspace.users.owner.email });
  await page.goto(`/workspace/${workspace.workspace_id}/calendar/?mode=calendar&view=week&date=2020-01-06`);
  const grid = page.getByTestId('calendar-week-grid');
  await settled(grid, 'the empty past calendar week');
  await expect.poll(() => grid.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
  await axe(page, 'Calendar week without posts or future create controls');

  await expect(grid).toHaveAttribute('role', 'region');
  await expect(grid).toHaveAccessibleName('Calendar week');
  const timezoneToggle = page.getByTestId('ui-select-calendarFilters.tz').getByTestId('ui-select-toggle');
  await timezoneToggle.focus();
  await timezoneToggle.press('Tab');
  await expect(grid).toBeFocused();
  await grid.press('PageDown');
  await expect.poll(() => grid.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);

  if (await grid.evaluate((element) => element.scrollWidth > element.clientWidth)) {
    await grid.press('ArrowRight');
    await expect.poll(() => grid.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
  }
  await axe(page, 'Calendar week after keyboard scrolling');
});
