// Golden path 7 (docs/specs/01-harness.md): drag a scheduled post to another hour on the Calendar.
// An approver's drag approves the new time; a staff member's drag sends the post back for review.
//
// A fixture makes a post approved by the owner in the dashboard and scheduled at its approved time.
// On the week view, the owner moves it two hours later: it stays scheduled, the approved time is
// the new one, and a "time_approved" action is recorded. An editor moving their own scheduled post
// withdraws the approval: back to pending_review, the approval cleared, and an
// "approval_withdrawn" action by the editor.
//
// Desktop Chrome drives the real drag (SortableJS, native HTML5 drag and drop). The two touch
// projects call the page's own drop handler, rescheduleChip(platformPostId, newDatetime), with the
// target cell's date and time, exactly as the drop does; the test title says which one ran.
//
// The database is read once, after the reschedule request has answered: the view moves the time,
// then re-checks the approval and writes its audit row, each in its own statement, and answers only
// when all of them are done. The grid is checked after the reload that follows has replaced it.
import { type Locator, type Page, type Response, type TestInfo } from '@playwright/test';

import { settled } from '../support/settled';
import { expect, test } from '../support/test';

type ScheduledPost = {
  post_id: string;
  platform_posts: { id: string; platform: string; account_id: string }[];
  proposed_publish_at: string;
  scheduled_at: string;
  local: { date: string; time: string; hour: number };
};

type PublishingPost = {
  platform_posts: {
    id: string;
    status: string;
    scheduled_at: string | null;
    approved_fingerprint: string;
    fingerprint: string;
    approved_by: string | null;
    approved_at: string | null;
    approved_publish_at: string | null;
  }[];
  actions: {
    action: string;
    channel: string;
    user: string | null;
    platform_post_id: string | null;
    fingerprint: string;
    publish_at: string | null;
  }[];
};

/** The same instant in one spelling (UTC ISO), so a mismatch prints both times. */
const instant = (value: string | null | undefined) => (value ? new Date(value).toISOString() : value);

const weekCell = (date: string, time: string) => `calendar-week-cell-${date}-${time.replace(':', '')}`;

const pad = (n: number) => String(n).padStart(2, '0');

/** The instant `hours` after `iso` (the target cell is the same day, two hours later). */
const hoursLater = (iso: string, hours: number) => new Date(new Date(iso).getTime() + hours * 3_600_000).toISOString();

const touchProject = (testInfo: TestInfo) => testInfo.project.name !== 'desktop-chrome';

/** Said in every title: which move each project makes. */
const HOW = "(desktop-chrome: the real drag; iphone-13 and pixel-7: the page's drop handler rescheduleChip)";

/**
 * The reschedule POST the drop sends and the week-grid reload that follows it. Registered before the
 * move, so neither response can be missed.
 */
function watchMove(page: Page, workspace: string): { saved: Promise<Response>; reloaded: Promise<Response> } {
  const calendar = `/workspace/${workspace}/calendar/`;
  const saved = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' && new URL(response.url()).pathname === `${calendar}reschedule/`,
  );
  const reloaded = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      response.request().method() === 'GET' && url.pathname === calendar && url.searchParams.get('view') === 'week'
    );
  });
  // Both are awaited below; a test that fails first must not also report them as unhandled.
  saved.catch(() => undefined);
  reloaded.catch(() => undefined);
  return { saved, reloaded };
}

/**
 * Move the chip into the target cell: the real drag on Desktop Chrome; on the touch projects, the
 * handler the drop calls (calendarApp's rescheduleChip), given the target cell's date and time the
 * way onEnd builds them.
 */
async function moveChip(page: Page, testInfo: TestInfo, chip: Locator, target: Locator, platformPostId: string) {
  testInfo.annotations.push({
    type: 'move',
    description: touchProject(testInfo)
      ? `${testInfo.project.name}: called rescheduleChip, the handler the drop calls`
      : `${testInfo.project.name}: dragged the chip with the mouse`,
  });
  if (!touchProject(testInfo)) {
    await chip.scrollIntoViewIfNeeded();
    await chip.dragTo(target);
    return;
  }
  const date = await target.getAttribute('data-date');
  const time = await target.getAttribute('data-time');
  expect(date && time, 'the target cell names its date and time').toBeTruthy();
  await page.getByTestId('calendar-shell').evaluate(
    (shell, [id, when]) => {
      type CalendarApp = { rescheduleChip: (platformPostId: string, newDatetime: string) => void };
      const alpine = (window as unknown as { Alpine: { $data: (el: Element) => CalendarApp } }).Alpine;
      // Called as a method of the component, as onEnd calls this.rescheduleChip(...): it reloads the grid.
      alpine.$data(shell).rescheduleChip(id, when);
    },
    [platformPostId, `${date}T${time}:00`],
  );
}

/**
 * Move the chip and wait for the whole round trip: the reschedule answered 204 (sent after the
 * approval re-check and its audit row), then the reload replaced the week grid the move started on.
 */
async function moveAndReload(
  page: Page,
  testInfo: TestInfo,
  workspace: string,
  move: { chip: Locator; target: Locator; platformPostId: string },
): Promise<void> {
  const grid = await page.getByTestId('calendar-week-grid').elementHandle();
  const { saved, reloaded } = watchMove(page, workspace);

  await moveChip(page, testInfo, move.chip, move.target, move.platformPostId);

  const answer = await saved;
  const refusal = answer.status() === 204 ? '' : await answer.text().catch(() => '');
  expect(answer.status(), `the reschedule answered ${answer.status()} ${refusal}`).toBe(204);
  expect((await reloaded).status(), 'the week grid reloaded').toBe(200);
  await expect
    .poll(() => grid.evaluate((element) => element.isConnected), { message: 'the reload replaced the week grid' })
    .toBe(false);
}

test(`owner moves a scheduled post two hours later ${HOW}: still scheduled, the new time approved`, async ({
  page,
  as,
  axe,
  harness,
  network,
}, testInfo) => {
  const since = Date.now() / 1000;
  const { workspace_a: workspace, users } = harness.ids;
  const made = await harness.fixture<ScheduledPost>('publishing_scheduled_post', {
    author: 'owner',
    accounts: ['linkedin_company'],
    days_ahead: 4,
    hour: 13,
  });
  const ppId = made.platform_posts[0].id;
  const newTime = `${pad(made.local.hour + 2)}:00`;
  const newInstant = hoursLater(made.scheduled_at, 2);

  const before = await harness.probe<PublishingPost>('publishing_post', { post_id: made.post_id });
  const approvedFingerprint = before.platform_posts[0].approved_fingerprint;
  expect(before.platform_posts[0].status).toBe('scheduled');
  expect(approvedFingerprint).toBe(before.platform_posts[0].fingerprint);

  await as('owner');
  await page.goto(`/workspace/${workspace}/calendar/?mode=calendar&view=week&date=${made.local.date}`);
  const source = page.getByTestId(weekCell(made.local.date, made.local.time));
  const target = page.getByTestId(weekCell(made.local.date, newTime));
  const chip = source.getByTestId(`calendar-chip-${ppId}`);
  await expect(chip).toBeVisible();
  await settled(page.getByTestId('calendar-week-grid'), 'the week grid');
  await axe(page, 'Calendar week before the move (owner)');

  await moveAndReload(page, testInfo, workspace, { chip, target, platformPostId: ppId });

  const after = await harness.probe<PublishingPost>('publishing_post', { post_id: made.post_id });
  const pp = after.platform_posts[0];
  expect(pp).toMatchObject({
    status: 'scheduled',
    approved_fingerprint: approvedFingerprint,
    fingerprint: approvedFingerprint,
    approved_by: users.owner.email,
  });
  expect(instant(pp.scheduled_at), 'scheduled_at is the new time').toBe(newInstant);
  expect(instant(pp.approved_publish_at), 'approved_publish_at is the new time').toBe(newInstant);

  const timeApproved = after.actions.filter((action) => action.action === 'time_approved');
  expect(timeApproved, JSON.stringify(after.actions)).toHaveLength(1);
  expect(timeApproved[0]).toMatchObject({ user: users.owner.email, channel: 'dashboard', platform_post_id: ppId });
  expect(instant(timeApproved[0].publish_at), 'the time_approved action names the new time').toBe(newInstant);
  expect(after.actions.map((action) => action.action)).not.toContain('approval_withdrawn');

  // The reloaded grid has the chip in the cell for the new hour, and only there.
  await expect(target.getByTestId(`calendar-chip-${ppId}`)).toBeVisible();
  await expect(target).toHaveAttribute('data-time', newTime);
  await expect(source.getByTestId(`calendar-chip-${ppId}`)).toHaveCount(0);
  await expect(page.getByTestId(`calendar-chip-${ppId}`)).toHaveCount(1);
  await settled(page.getByTestId('calendar-week-grid'), 'the reloaded week grid');
  await axe(page, 'Calendar week after the move (owner)');

  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});

test(`editor moves their own scheduled post ${HOW}: the approval is withdrawn and it goes back for review`, async ({
  page,
  as,
  axe,
  harness,
  network,
}, testInfo) => {
  const since = Date.now() / 1000;
  const { workspace_a: workspace, users } = harness.ids;
  const made = await harness.fixture<ScheduledPost>('publishing_scheduled_post', {
    author: 'editor',
    accounts: ['linkedin_company'],
    days_ahead: 4,
    hour: 16,
  });
  const ppId = made.platform_posts[0].id;
  const newTime = `${pad(made.local.hour + 2)}:00`;
  const newInstant = hoursLater(made.scheduled_at, 2);

  await as('editor');
  await page.goto(`/workspace/${workspace}/calendar/?mode=calendar&view=week&date=${made.local.date}`);
  const source = page.getByTestId(weekCell(made.local.date, made.local.time));
  const target = page.getByTestId(weekCell(made.local.date, newTime));
  const chip = source.getByTestId(`calendar-chip-${ppId}`);
  await expect(chip).toBeVisible();
  await settled(page.getByTestId('calendar-week-grid'), 'the week grid');
  await axe(page, 'Calendar week before the move (editor)');

  await moveAndReload(page, testInfo, workspace, { chip, target, platformPostId: ppId });

  const after = await harness.probe<PublishingPost>('publishing_post', { post_id: made.post_id });
  const pp = after.platform_posts[0];
  expect(pp).toMatchObject({
    status: 'pending_review',
    approved_fingerprint: '',
    approved_by: null,
    approved_at: null,
    approved_publish_at: null,
  });
  expect(instant(pp.scheduled_at), 'scheduled_at is the new time').toBe(newInstant);

  const withdrawn = after.actions.filter((action) => action.action === 'approval_withdrawn');
  expect(withdrawn, JSON.stringify(after.actions)).toHaveLength(1);
  expect(withdrawn[0]).toMatchObject({ user: users.editor.email, channel: 'dashboard', platform_post_id: ppId });
  expect(after.actions.map((action) => action.action)).not.toContain('time_approved');

  // The reloaded grid has the chip in the cell for the new hour, and only there.
  await expect(target.getByTestId(`calendar-chip-${ppId}`)).toBeVisible();
  await expect(source.getByTestId(`calendar-chip-${ppId}`)).toHaveCount(0);
  await expect(page.getByTestId(`calendar-chip-${ppId}`)).toHaveCount(1);
  await settled(page.getByTestId('calendar-week-grid'), 'the reloaded week grid');
  await axe(page, 'Calendar week after the move (editor)');

  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});
