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
import { type Locator, type Page, type TestInfo } from '@playwright/test';

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

const sameInstant = (a: string | null | undefined, b: string | null | undefined) =>
  !!a && !!b && new Date(a).getTime() === new Date(b).getTime();

const weekCell = (date: string, time: string) => `calendar-week-cell-${date}-${time.replace(':', '')}`;

const pad = (n: number) => String(n).padStart(2, '0');

/** The instant `hours` after `iso` (the target cell is the same day, two hours later). */
const hoursLater = (iso: string, hours: number) => new Date(new Date(iso).getTime() + hours * 3_600_000).toISOString();

const touchProject = (testInfo: TestInfo) => testInfo.project.name !== 'desktop-chrome';

/** Said in every title: which move each project makes. */
const HOW = "(desktop-chrome: the real drag; iphone-13 and pixel-7: the page's drop handler rescheduleChip)";

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

/** Read the post until `ready` holds, and return what was read last. */
async function until(
  harness: { probe: <T>(name: string, params: Record<string, string>) => Promise<T> },
  postId: string,
  ready: (post: PublishingPost) => boolean,
  message: string,
): Promise<PublishingPost> {
  let value: PublishingPost | undefined;
  await expect
    .poll(
      async () => {
        value = await harness.probe<PublishingPost>('publishing_post', { post_id: postId });
        return ready(value);
      },
      { message, timeout: 15_000, intervals: [200, 500, 1_000] },
    )
    .toBe(true);
  return value as PublishingPost;
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
  await axe(page, 'Calendar week before the move (owner)');

  await moveChip(page, testInfo, chip, target, ppId);

  const after = await until(
    harness,
    made.post_id,
    (post) => sameInstant(post.platform_posts[0].scheduled_at, newInstant),
    'the post moved to the new time',
  );
  const pp = after.platform_posts[0];
  expect(pp.status).toBe('scheduled');
  expect(sameInstant(pp.approved_publish_at, newInstant)).toBe(true);
  expect(pp.approved_fingerprint).toBe(approvedFingerprint);
  expect(pp.approved_fingerprint).toBe(pp.fingerprint);
  expect(pp.approved_by).toBe(users.owner.email);

  const timeApproved = after.actions.filter((action) => action.action === 'time_approved');
  expect(timeApproved).toHaveLength(1);
  expect(timeApproved[0]).toMatchObject({ user: users.owner.email, channel: 'dashboard', platform_post_id: ppId });
  expect(sameInstant(timeApproved[0].publish_at, newInstant)).toBe(true);
  expect(after.actions.some((action) => action.action === 'approval_withdrawn')).toBe(false);

  // The grid reloads with the chip in the cell for the new hour.
  await expect(target.getByTestId(`calendar-chip-${ppId}`)).toBeVisible();
  await expect(target).toHaveAttribute('data-time', newTime);
  await expect(page.getByTestId(`calendar-chip-${ppId}`)).toHaveCount(1);
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
  await axe(page, 'Calendar week before the move (editor)');

  await moveChip(page, testInfo, chip, target, ppId);

  const after = await until(
    harness,
    made.post_id,
    (post) => post.platform_posts[0].status === 'pending_review',
    'the approval was withdrawn',
  );
  const pp = after.platform_posts[0];
  expect(sameInstant(pp.scheduled_at, newInstant)).toBe(true);
  expect(pp.approved_fingerprint).toBe('');
  expect(pp.approved_by).toBeNull();
  expect(pp.approved_at).toBeNull();
  expect(pp.approved_publish_at).toBeNull();

  const withdrawn = after.actions.filter((action) => action.action === 'approval_withdrawn');
  expect(withdrawn).toHaveLength(1);
  expect(withdrawn[0]).toMatchObject({ user: users.editor.email, channel: 'dashboard', platform_post_id: ppId });
  expect(after.actions.some((action) => action.action === 'time_approved')).toBe(false);

  await expect(target.getByTestId(`calendar-chip-${ppId}`)).toBeVisible();
  await axe(page, 'Calendar week after the move (editor)');

  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});
