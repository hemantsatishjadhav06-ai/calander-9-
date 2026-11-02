// Screen 1, the New post sheet (docs/specs/03-rebuild-screens.md, "Screen 1"; Phase 3, T21), on the
// three devices. One button, New post, on Home and Calendar (floating above the phone bar on a phone,
// in the page header from 1024 px) opens one sheet with three ways to start a post: Ask the team
// (studio:create), Write it myself (the editor) and Save it as an idea (the Ideas board).
//
// The behavioural cases run in light; the axe cases run in light and dark (forSchemes, spec D10).
// Each case that leaves rows behind makes a workspace of its own (team_workspace), so what the probe
// `new_post_outcome` reads is this test's alone; the switch and the spent month are set with
// `workspace_switches` and `workspace_over_budget`, which refuse the shared workspaces A and B.
//
//   - One tap opens the sheet on a phone, from Home and from Calendar, with the focus in Your idea.
//   - Ask the team lands on the idea's own thread: one conversation, one message of kind create, one
//     chat job and no brief (nothing is made before Go ahead).
//   - Over budget, the sheet's own sentence shows in its error line, no toast shows, nothing is made
//     and what was typed is still there.
//   - Closing and reopening keeps what was typed.
//   - An editor sees the button; a viewer and a plain client do not, and the client's direct POST to
//     studio:create answers 403 and makes nothing.
//   - Write it myself opens the editor (200, its caption field); from a week cell on desktop the sheet
//     opens in Write it myself and the editor link carries that cell's date and time (phones get the
//     cell control in screen 4).
//   - Save it as an idea shows the dialog named "New idea" and saves the idea; with the templates
//     switch it has tags, and with it off there is no tag control.
//   - The foot links reach their pages.
//   - axe with the sheet closed and open in each mode, in both schemes. Home and Calendar are declared
//     dark-ready (T22, apps/common/screens.py); each axe case still declares them through `dark_ready`
//     and clears that after it (back to the code's own set), as self/shortcuts.spec.ts does, so the dark
//     case reads the dark page and the light case the light one whatever the registry holds.
import type { Locator, Page } from '@playwright/test';

import { csrfToken, isPhone } from '../support/nav';
import { forSchemes } from '../support/schemes';
import { settled } from '../support/settled';
import { expect, test } from '../support/test';

type Person = { id: string; email: string };
type TeamWorkspace = { workspace_id: string; users: Record<'owner' | 'editor' | 'client', Person> };
type Outcome = {
  conversations: { id: string; audience: string; created_by: string | null }[];
  messages: Record<string, number>;
  chat_jobs: { id: string; status: string; kind: string; conversation_id: string | null }[];
  briefs: { id: string; status: string; origin: string }[];
  ideas: { id: string; title: string; description: string; group: string | null; tags: string[]; author: string | null }[];
  tags: string[];
};

/** The sheet's own over-budget sentence (apps/studio/views.py `_ALLOWANCE_USED`). */
const ALLOWANCE_USED = "This month's allowance for the team is used up. An owner can raise it in Settings → Autopilot.";
const NOTHING: Outcome = { conversations: [], messages: {}, chat_jobs: [], briefs: [], ideas: [], tags: [] };
const DESKTOP_ONLY = 'desktop-chrome only: the week cell\'s "+" shows on hover, and phones get the cell control in screen 4';

const home = (workspace: string) => `/workspace/${workspace}/studio/`;
const calendar = (workspace: string) => `/workspace/${workspace}/calendar/`;

/** The date `days` from now in the workspace's zone (Asia/Kolkata, as the seed and team_workspace set it). */
function kolkataDate(days: number): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date(Date.now() + days * 86_400_000));
}

/** Home or Calendar has loaded with the New post button ready (closed). */
async function ready(page: Page, path: string): Promise<Locator> {
  const response = await page.goto(path);
  expect(response?.status(), `${path} answers`).toBe(200);
  const button = page.getByTestId('new-post-open');
  await expect(button).toBeVisible();
  await expect(button).toHaveAttribute('aria-expanded', 'false');
  return button;
}

/** One tap on a touch device, a click elsewhere. */
async function press(page: Page, target: Locator): Promise<void> {
  if (isPhone(page)) await target.tap();
  else await target.click();
}

/** Open the sheet with the New post button; it opens on Ask the team with the focus in Your idea. */
async function openSheet(page: Page): Promise<Locator> {
  await press(page, page.getByTestId('new-post-open'));
  const sheet = page.getByRole('dialog', { name: 'New post' });
  await expect(sheet).toBeVisible();
  await expect(page.getByTestId('new-post-open')).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByTestId('new-post-team-idea')).toBeFocused();
  return sheet;
}

/** Whether the sheet is open: its script sets has-sheet on body while it shows. */
function sheetIsOpen(page: Page): Promise<boolean> {
  return page.evaluate(() => document.body.classList.contains('has-sheet'));
}

test('one tap opens the sheet from Home and from Calendar, with the focus in Your idea', async ({ page, as, harness }) => {
  await as('owner');
  for (const path of [home(harness.ids.workspace_a), calendar(harness.ids.workspace_a)]) {
    await ready(page, path);
    expect(await sheetIsOpen(page)).toBe(false);
    await expect(page.getByTestId('new-post-sheet')).toBeHidden();

    await openSheet(page);
    expect(await sheetIsOpen(page)).toBe(true);
    await expect(page.getByTestId('new-post-mode-team')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('new-post-mode-self')).toHaveAttribute('aria-pressed', 'false');
    await expect(page.getByTestId('new-post-team-send')).toBeVisible();
  }
});

test("Ask the team lands on the idea's thread: one conversation, one create message, one chat job, no brief", async ({
  page,
  as,
  harness,
}) => {
  const made = await harness.fixture<TeamWorkspace>('team_workspace', {});
  const workspace = made.workspace_id;
  const idea = `E2E sheet ${Date.now()}: covered parking is ready at the Kokapet site`;
  await as({ email: made.users.editor.email });
  await ready(page, home(workspace));
  const since = Date.now() / 1000;
  await openSheet(page);
  await page.getByTestId('new-post-team-idea').fill(idea);

  const sent = page.waitForResponse(
    (response) => response.request().method() === 'POST' && new URL(response.url()).pathname === `${home(workspace)}new/`,
  );
  await press(page, page.getByTestId('new-post-team-send'));
  expect((await sent).status(), 'studio:create answers the sheet with 204 and HX-Redirect').toBe(204);
  await page.waitForURL((url) => url.pathname === `${home(workspace)}thread/` && url.searchParams.has('c'));
  await expect(page.getByText(idea).first()).toBeVisible();

  const outcome = await harness.probe<Outcome>('new_post_outcome', { workspace_id: workspace, since });
  expect(outcome.conversations.map((row) => [row.audience, row.created_by])).toEqual([['internal', made.users.editor.email]]);
  expect(new URL(page.url()).searchParams.get('c'), "the idea's own thread").toBe(outcome.conversations[0].id);
  expect(outcome.messages.create, 'one message of kind create').toBe(1);
  expect(outcome.chat_jobs.map((job) => [job.kind, job.conversation_id])).toEqual([['create', outcome.conversations[0].id]]);
  expect(outcome.briefs, 'no brief before Go ahead').toEqual([]);

  // The team answers (the fake manager), and still nothing is made: the brief waits for Go ahead.
  await expect
    .poll(
      async () => (await harness.probe<Outcome>('new_post_outcome', { workspace_id: workspace, since })).chat_jobs[0].status,
      { message: 'the chat job has finished', timeout: 30_000 },
    )
    .toBe('done');
  const answered = await harness.probe<Outcome>('new_post_outcome', { workspace_id: workspace, since });
  expect(answered.conversations).toHaveLength(1);
  expect(answered.messages.create).toBe(1);
  expect(answered.chat_jobs).toHaveLength(1);
  expect(answered.briefs, 'no brief before Go ahead').toEqual([]);
});

test("over budget, the sheet's own sentence shows in its error line, no toast, nothing made, the text kept", async ({
  page,
  as,
  harness,
}) => {
  const made = await harness.fixture<TeamWorkspace>('team_workspace', {});
  const workspace = made.workspace_id;
  const spent = await harness.fixture<{ can_spend: boolean }>('workspace_over_budget', { workspace_id: workspace });
  expect(spent.can_spend).toBe(false);
  const idea = `E2E over budget ${Date.now()}: a post about the clubhouse`;
  await as({ email: made.users.owner.email });
  await ready(page, home(workspace));
  const since = Date.now() / 1000;
  await openSheet(page);
  const field = page.getByTestId('new-post-team-idea');
  await field.fill(idea);

  const refused = page.waitForResponse(
    (response) => response.request().method() === 'POST' && new URL(response.url()).pathname === `${home(workspace)}new/`,
  );
  await press(page, page.getByTestId('new-post-team-send'));
  expect((await refused).status()).toBe(400);

  const error = page.getByTestId('new-post-team-error');
  await expect(error).toHaveText(ALLOWANCE_USED);
  await expect(error).toHaveAttribute('role', 'alert');
  await expect(error).toBeVisible();
  await expect(page.getByTestId('error-toast'), 'no toast: the sheet says it').toBeHidden();
  await expect(page.getByRole('dialog', { name: 'New post' })).toBeVisible();
  await expect(field, 'what was typed is still there').toHaveValue(idea);
  expect(new URL(page.url()).pathname, 'still on Home').toBe(home(workspace));
  expect(await harness.probe<Outcome>('new_post_outcome', { workspace_id: workspace, since })).toEqual(NOTHING);
});

test('closing and reopening the sheet keeps what was typed', async ({ page, as, harness }) => {
  await as('owner');
  const button = await ready(page, home(harness.ids.workspace_a));
  const typed = `E2E kept ${Date.now()}`;
  await openSheet(page);
  await page.getByTestId('new-post-team-idea').fill(typed);

  // Escape closes it and gives the focus back to the button.
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('new-post-sheet')).toBeHidden();
  await expect(button).toHaveAttribute('aria-expanded', 'false');
  await expect(button).toBeFocused();
  await openSheet(page);
  await expect(page.getByTestId('new-post-team-idea')).toHaveValue(typed);

  // So does the close button.
  await press(page, page.getByTestId('new-post-close'));
  await expect(page.getByTestId('new-post-sheet')).toBeHidden();
  expect(await sheetIsOpen(page)).toBe(false);
  await openSheet(page);
  await expect(page.getByTestId('new-post-team-idea')).toHaveValue(typed);
});

test('an editor sees New post; a viewer and a plain client do not, and the client’s direct POST answers 403', async ({
  page,
  context,
  as,
  harness,
}) => {
  const made = await harness.fixture<TeamWorkspace>('team_workspace', {});
  const workspace = made.workspace_id;
  const viewer = await harness.fixture<{ email: string }>('workspace_member', { role: 'viewer', workspace_id: workspace });

  await as({ email: made.users.editor.email });
  for (const path of [home(workspace), calendar(workspace)]) {
    await ready(page, path);
    await expect(page.getByTestId('new-post-sheet')).toHaveCount(1);
  }

  await context.clearCookies();
  await as({ email: viewer.email });
  for (const path of [home(workspace), calendar(workspace)]) {
    expect((await page.goto(path))?.status(), `${path} for a viewer`).toBe(200);
    await expect(page.getByTestId('main-content')).toBeVisible();
    await expect(page.getByTestId('new-post-open'), `no New post for a viewer on ${path}`).toHaveCount(0);
    await expect(page.getByTestId('new-post-sheet')).toHaveCount(0);
  }

  await context.clearCookies();
  await as({ email: made.users.client.email });
  expect((await page.goto(home(workspace)))?.status(), 'Home is not for a plain client').toBe(403);
  expect((await page.goto(calendar(workspace)))?.status()).toBe(200);
  await expect(page.getByTestId('main-content')).toBeVisible();
  await expect(page.getByTestId('new-post-open'), 'no New post for a plain client').toHaveCount(0);
  await expect(page.getByTestId('new-post-sheet')).toHaveCount(0);

  const since = Date.now() / 1000;
  const token = await csrfToken(context);
  const asSent: Record<string, string>[] = [{}, { 'HX-Request': 'true' }];
  for (const headers of asSent) {
    const refused = await page.request.post(`${home(workspace)}new/`, {
      form: { idea: 'A client writing to the team’s create address' },
      headers: { 'X-CSRFToken': token, Referer: page.url(), ...headers },
    });
    expect(refused.status(), `the client's direct POST (${Object.keys(headers).join() || 'no HTMX'})`).toBe(403);
    expect(await refused.text()).not.toContain('CSRF verification failed');
  }
  expect(await harness.probe<Outcome>('new_post_outcome', { workspace_id: workspace, since })).toEqual(NOTHING);
});

test('Write it myself opens the editor', async ({ page, as, harness }) => {
  const workspace = harness.ids.workspace_a;
  await as('owner');
  await ready(page, home(workspace));
  await openSheet(page);

  await press(page, page.getByTestId('new-post-mode-self'));
  await expect(page.getByTestId('new-post-mode-self')).toHaveAttribute('aria-pressed', 'true');
  const open = page.getByTestId('new-post-self-open');
  await expect(open).toBeFocused();
  await expect(open).toHaveAttribute('href', `/workspace/${workspace}/compose/`);
  await expect(page.getByTestId('new-post-team-idea')).toBeHidden();

  const editor = page.waitForResponse(
    (response) => response.request().isNavigationRequest() && new URL(response.url()).pathname === `/workspace/${workspace}/compose/`,
  );
  await press(page, open);
  expect((await editor).status(), 'the editor answers 200').toBe(200);
  await expect(page.getByTestId('compose-caption')).toBeVisible();
});

test.describe('from the Calendar (desktop-chrome only: phones get the cell control in screen 4)', () => {
  test.skip(({ isMobile }) => isMobile, DESKTOP_ONLY);

  test("a week cell opens the sheet in Write it myself, and the editor link carries the cell's date and time", async ({
    page,
    as,
    harness,
  }) => {
    // A workspace of its own: no post and no posting slot at 16:00, so the empty cell offers its "+".
    const made = await harness.fixture<TeamWorkspace>('team_workspace', {});
    const workspace = made.workspace_id;
    const date = kolkataDate(3);
    await as({ email: made.users.owner.email });
    await ready(page, `${calendar(workspace)}?mode=calendar&view=week&date=${date}`);
    const cell = page.getByTestId(`calendar-week-cell-${date}-1600`);
    await expect(cell).toBeVisible();
    await expect(cell).toHaveAttribute('data-date', date);
    await expect(cell).toHaveAttribute('data-time', '16:00');

    await cell.hover();
    const plus = cell.getByRole('link', { name: 'Create post' });
    await expect(plus).toBeVisible();
    // Without JavaScript the "+" is still the editor's address with the cell's date and time.
    const plain = new URL((await plus.getAttribute('href'))!, page.url());
    expect(plain.pathname).toBe(`/workspace/${workspace}/compose/`);
    expect(Object.fromEntries(plain.searchParams)).toEqual({ scheduled_date: date, scheduled_time: '16:00' });
    await plus.click();

    await expect(page.getByRole('dialog', { name: 'New post' })).toBeVisible();
    await expect(page.getByTestId('new-post-mode-self')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('new-post-mode-team')).toHaveAttribute('aria-pressed', 'false');
    const open = page.getByTestId('new-post-self-open');
    await expect(open).toBeFocused();
    const href = new URL((await open.getAttribute('href'))!, page.url());
    expect(href.pathname).toBe(`/workspace/${workspace}/compose/`);
    expect(Object.fromEntries(href.searchParams), 'only the cell’s date and time').toEqual({
      scheduled_date: date,
      scheduled_time: '16:00',
    });

    const editor = page.waitForResponse(
      (response) => response.request().isNavigationRequest() && new URL(response.url()).pathname === href.pathname,
    );
    await open.click();
    expect((await editor).status()).toBe(200);
    await expect(page.getByTestId('compose-caption')).toBeVisible();
    expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual({ scheduled_date: date, scheduled_time: '16:00' });
  });
});

test('Save it as an idea saves the idea, with tags while the templates switch is on and no tag control when it is off', async ({
  page,
  as,
  harness,
}) => {
  const made = await harness.fixture<TeamWorkspace>('team_workspace', {});
  const workspace = made.workspace_id;
  const switches = (templates: boolean) =>
    harness.fixture<{ features: Record<string, boolean> }>('workspace_switches', {
      workspace_id: workspace,
      features: { templates },
    });
  expect((await switches(true)).features.templates).toBe(true);
  const title = `E2E idea ${Date.now()}: a site walk on Sunday`;
  const tag = `walk-${Date.now() % 100_000}`;
  await as({ email: made.users.owner.email });
  await ready(page, home(workspace));
  const since = Date.now() / 1000;
  await openSheet(page);

  await press(page, page.getByTestId('new-post-save-idea'));
  await expect(page.getByRole('dialog', { name: 'New idea' })).toBeVisible();
  await expect(page.getByTestId('idea-title')).toBeFocused();
  await page.getByTestId('idea-title').fill(title);
  await page.getByTestId('idea-description').fill('Meet at the site office at 10.');
  await press(page, page.getByTestId('idea-tags-toggle'));
  await page.getByTestId('idea-tag-search').fill(tag);
  await page.getByTestId('idea-tag-search').press('Enter');
  await expect(page.getByTestId('idea-tags').getByText(tag, { exact: true }).first()).toBeVisible();

  const saved = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' && new URL(response.url()).pathname === `/workspace/${workspace}/ideas/create/`,
  );
  await press(page, page.getByTestId('idea-save'));
  expect((await saved).ok(), 'composer:idea_create saved it').toBe(true);
  await expect(page.getByTestId('new-post-sheet'), 'saving closes the sheet').toBeHidden();

  const outcome = await harness.probe<Outcome>('new_post_outcome', { workspace_id: workspace, since });
  expect(outcome.ideas.map((row) => [row.title, row.description, row.tags, row.author])).toEqual([
    [title, 'Meet at the site office at 10.', [tag], made.users.owner.email],
  ]);
  expect(outcome.tags).toEqual([tag]);
  expect(outcome.conversations, 'an idea is a note on the board: nothing else is made').toEqual([]);
  expect(outcome.chat_jobs).toEqual([]);
  expect(outcome.briefs).toEqual([]);

  // Switched off: the idea form has no tag control, and the sheet no Templates or Categories.
  expect((await switches(false)).features.templates).toBe(false);
  await ready(page, home(workspace));
  await openSheet(page);
  await expect(page.getByTestId('new-post-link-templates')).toHaveCount(0);
  await expect(page.getByTestId('new-post-link-categories')).toHaveCount(0);
  await press(page, page.getByTestId('new-post-save-idea'));
  await expect(page.getByRole('dialog', { name: 'New idea' })).toBeVisible();
  await expect(page.getByTestId('idea-title')).toBeVisible();
  await expect(page.getByTestId('idea-tags'), 'no tag control with the switch off').toHaveCount(0);
  await expect(page.getByTestId('idea-tags-toggle')).toHaveCount(0);
});

test('the foot links reach their pages', async ({ page, as, harness }) => {
  const made = await harness.fixture<TeamWorkspace>('team_workspace', {});
  const workspace = made.workspace_id;
  await harness.fixture('workspace_switches', { workspace_id: workspace, features: { templates: true } });
  await as({ email: made.users.owner.email });

  for (const name of ['ideas', 'drafts', 'csv', 'templates', 'categories']) {
    await ready(page, home(workspace));
    await openSheet(page);
    const link = page.getByTestId(`new-post-link-${name}`);
    const target = new URL((await link.getAttribute('href'))!, page.url());
    expect(target.pathname.startsWith(`/workspace/${workspace}/`), `${name} stays in this workspace`).toBe(true);
    const arrived = page.waitForResponse(
      (response) => response.request().isNavigationRequest() && response.url() === target.toString(),
    );
    await press(page, link);
    expect((await arrived).status(), `${name} answers 200`).toBe(200);
    // It lands where it points, with no redirect on the way (the new document has loaded).
    await page.waitForURL(target.toString());
    await expect(page.getByTestId('main-content')).toBeVisible();
  }
});

test.describe('axe', () => {
  test.afterEach(async ({ harness }) => {
    await harness.fixture('dark_ready', { clear: true });
  });

  forSchemes((scheme) => {
    for (const [where, path] of [
      ['Home', home],
      ['Calendar', calendar],
    ] as const) {
      test(`${where} passes axe with the sheet closed and open in each mode (${scheme})`, async ({ page, as, axe, harness }) => {
        // Declared dark-ready since T22; the case declares them for itself too, so the page follows the
        // device's scheme whatever the registry holds.
        await harness.fixture('dark_ready', { add: ['studio:index', 'calendar:calendar'] });
        await as('owner');
        await ready(page, path(harness.ids.workspace_a));
        await expect(page.locator('html')).toHaveAttribute('data-theme', scheme);
        await axe(page, `${where}, the sheet closed (${scheme})`);

        await openSheet(page);
        const sheet = page.getByTestId('new-post-sheet');
        await settled(sheet, 'the New post sheet');
        await axe(page, `${where}, Ask the team (${scheme})`);

        await press(page, page.getByTestId('new-post-mode-self'));
        await expect(page.getByTestId('new-post-self-open')).toBeFocused();
        await settled(sheet, 'Write it myself');
        await axe(page, `${where}, Write it myself (${scheme})`);

        await press(page, page.getByTestId('new-post-mode-team'));
        await press(page, page.getByTestId('new-post-save-idea'));
        await expect(page.getByRole('dialog', { name: 'New idea' })).toBeVisible();
        await expect(page.getByTestId('idea-title')).toBeFocused();
        await settled(sheet, 'the idea form');
        await axe(page, `${where}, Save it as an idea (${scheme})`);
      });
    }
  });
});
