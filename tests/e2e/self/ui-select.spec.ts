import type { Page } from '@playwright/test';
import { expect, test } from '../support/test';
import { settled } from '../support/settled';

async function reloadGrid(page: Page, workspace: string, action: () => Promise<unknown>, check: (url: URL) => boolean) {
  const previous = await page.getByTestId('calendar-week-grid').elementHandle();
  const response = page.waitForResponse((answer) => {
    const url = new URL(answer.url());
    return url.pathname === `/workspace/${workspace}/calendar/` && check(url);
  });
  response.catch(() => undefined);
  await action();
  expect((await response).status(), 'the selected filter reloads the calendar').toBe(200);
  await expect.poll(() => previous!.evaluate((element) => element.isConnected)).toBe(false);
  await settled(page.getByTestId('calendar-week-grid'), 'the filtered calendar week');
}

test('calendar filters mount on demand and retain single and multiple selections across reopen', async ({ page, harness, as, axe }) => {
  await as('owner');
  const workspace = harness.ids.workspace_a;
  await page.goto(`/workspace/${workspace}/calendar/?mode=calendar&view=week`);
  await settled(page.getByTestId('calendar-week-grid'), 'the calendar week');
  const timezone = page.getByTestId('ui-select-calendarFilters.tz');
  const channels = page.getByTestId('ui-select-calendarFilters.channels');
  const options = page.getByTestId(/^ui-select-option-/);
  await expect(options, 'closed filters do not mount their option controls').toHaveCount(0);
  await axe(page, 'Calendar with filters closed');

  const timezoneToggle = timezone.getByTestId('ui-select-toggle');
  await timezoneToggle.focus();
  await timezoneToggle.press('Enter');
  await expect(timezone.getByTestId('ui-select-panel')).toBeVisible();
  await expect(timezone.getByTestId('ui-select-option-UTC')).toBeVisible();
  await axe(page, 'Calendar with the timezone filter open');
  await reloadGrid(page, workspace,
    () => timezone.getByTestId('ui-select-option-UTC').press('Enter'),
    (url) => url.searchParams.get('tz') === 'UTC',
  );
  await expect(timezoneToggle).toContainText('UTC');
  await expect(options).toHaveCount(0);
  await timezoneToggle.click();
  await expect(timezone.getByTestId('ui-select-option-UTC')).toBeVisible();
  await timezoneToggle.press('Escape');
  await expect(options).toHaveCount(0);

  const channelsToggle = channels.getByTestId('ui-select-toggle');
  await channelsToggle.click();
  const account = harness.ids.accounts.linkedin_company.id;
  const checkbox = channels.getByTestId(`ui-select-option-${account}`);
  await expect(checkbox).not.toBeChecked();
  await reloadGrid(page, workspace, () => checkbox.check(),
    (url) => url.searchParams.getAll('channel').includes(account),
  );
  await expect(checkbox).toBeChecked();
  await expect(channelsToggle).toContainText('1 selected');
  await axe(page, 'Calendar with a selected channel');
  await channelsToggle.press('Escape');
  await expect(options).toHaveCount(0);
  await channelsToggle.click();
  await expect(checkbox).toBeChecked();
  await reloadGrid(page, workspace, () => channels.getByTestId('ui-select-clear').click(),
    (url) => !url.searchParams.has('channel'),
  );
  await expect(checkbox).not.toBeChecked();
  await expect(channelsToggle).toContainText('Channels');
  await channelsToggle.press('Escape');
  await expect(options).toHaveCount(0);
  await axe(page, 'Calendar after clearing the channel filter');
});
