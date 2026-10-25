// Golden path 11: a member of workspace A is refused every workspace-B URL, and never sees B's data.
//
// The URLs come from the URL resolver (the isolation_urls probe): every pattern that takes a
// workspace_id, filled with B's id and with rows the test makes in B, so a page added tomorrow is
// covered without touching this file. Each answers 403 or 404 (today the membership middleware
// answers 403 before any view runs; see docs/specs/01-harness.md, path 11), and no answer carries
// B's name. A sample of actions is posted with a valid CSRF token, and B's rows are read back to
// show nothing moved. B's object ids under A's own URLs answer 404 (or 403 where the role may not
// open that area at all), and nothing under A that takes one of them shows B. Two refusal pages are
// opened in the browser and checked with axe. Requests go through page.request, which carries the
// browser context's session cookie.
import type { APIResponse, Page } from '@playwright/test';

import { expect, test } from '../support/test';

type UrlEntry = { name: string; route: string; path: string; objects: string[]; resolves_to: string };
type Urls = { count: number; urls: UrlEntry[] };
type BObjects = {
  workspace_id: string;
  workspace_name: string;
  account_id: string;
  post_id: string;
  platform_post_id: string;
  brief_id: string;
  idea_id: string;
};

const ROLES = ['owner', 'editor', 'client'] as const;
const REFUSED = [403, 404];
const PARALLEL = 8;

/** Actions posted to workspace B with a valid CSRF token: approving, scheduling, editing, deleting, settings. */
const POST_ACTIONS = [
  'approvals:approve',
  'approvals:request_changes',
  'approvals:reject',
  'approvals:add_comment',
  'approvals:bulk_action',
  'calendar:reschedule',
  'calendar:bulk_platform_action',
  'composer:save_post_edit',
  'composer:transition_platform_post',
  'composer:post_delete',
  'composer:clone_post',
  'composer:idea_delete',
  'studio:approve',
  'studio:request_changes',
  'studio:discard',
  'studio:thread_start',
  'studio:create',
  'studio:brand',
  'studio:setup_lead',
  'social_accounts:disconnect',
  'social_accounts:remove',
  'workspaces:settings',
  'workspaces:approvals_settings',
  'client_portal_admin:invite_client',
  'media_library:upload',
  'telegram:connect',
];

/**
 * Pages that read one of B's rows by id under A's own URL: 404, as for a row that is not there. A client
 * of A may not open the composer or the agency at all, so for them the first two answer 403 first.
 */
const OBJECT_PAGES_UNDER_A = [
  'composer:compose_edit',
  'studio:detail',
  'approvals:version_diff',
  'analytics:post_detail',
];

/**
 * Actions on one of B's rows under A's own URL (none of them rate limited, so the run uses up no one's
 * allowance). The owner may do every one of them in A, so for the owner the answer must be the 404 of
 * the scoped lookup; the editor and the client may be refused for their role first (403).
 */
const OBJECT_ACTIONS_UNDER_A = [
  'approvals:approve',
  'approvals:request_changes',
  'approvals:reject',
  'approvals:add_comment',
  'composer:save_post_edit',
  'composer:transition_platform_post',
  'composer:post_delete',
  'composer:clone_post',
  'composer:idea_delete',
  'studio:approve',
  'studio:discard',
  'social_accounts:disconnect',
  'social_accounts:remove',
];

function objectsOf(b: BObjects): Record<string, string> {
  return {
    account_id: b.account_id,
    post_id: b.post_id,
    platform_post_id: b.platform_post_id,
    brief_id: b.brief_id,
    idea_id: b.idea_id,
  };
}

function byName(urls: UrlEntry[], names: string[]): UrlEntry[] {
  const found = names.map((name) => urls.find((url) => url.name === name));
  const missing = names.filter((_name, index) => !found[index]);
  expect(missing, 'every named URL still exists').toEqual([]);
  return found as UrlEntry[];
}

async function csrfToken(page: Page): Promise<string> {
  const token = (await page.context().cookies()).find((cookie) => cookie.name === 'csrftoken')?.value;
  expect(token, 'the page set a CSRF cookie').toBeTruthy();
  return String(token);
}

type Check = (response: APIResponse, body: string) => string | null;

/** Answers 403 or 404 (or only the statuses given). */
function status(...allowed: number[]): Check {
  const expected = allowed.length ? allowed : REFUSED;
  return (response) => (expected.includes(response.status()) ? null : `answered ${response.status()}`);
}

/**
 * Shows nothing of B, whatever it answers: no success with a body (an empty partial is how some HTMX
 * views answer people who may not use them), no redirect towards B's workspace or rows, no server error.
 * Views that check their input (400) or their own configuration (503) before the lookup pass.
 */
function showsNothingOf(ids: string[]): Check {
  return (response, body) => {
    const code = response.status();
    const location = response.headers()['location'] ?? '';
    if (code >= 200 && code < 300 && body.trim() !== '') return `answered ${code} with a body`;
    if (code >= 300 && code < 400 && ids.some((id) => location.includes(id))) return `redirected to ${location}`;
    if (code === 500) return 'answered 500';
    return null;
  };
}

/** Send every request, a few at a time; list each answer that fails the check or carries B's name. */
async function problems(
  urls: UrlEntry[],
  send: (url: UrlEntry) => Promise<APIResponse>,
  marker: string,
  check: Check,
): Promise<string[]> {
  const found: string[] = [];
  for (let start = 0; start < urls.length; start += PARALLEL) {
    await Promise.all(
      urls.slice(start, start + PARALLEL).map(async (url) => {
        const response = await send(url);
        const body = await response.text();
        const problem = check(response, body);
        if (problem) {
          found.push(`${url.name} ${url.path}: ${problem}`);
        }
        if (body.includes(marker)) {
          found.push(`${url.name} ${url.path}: shows "${marker}"`);
        }
      }),
    );
  }
  return found;
}

for (const role of ROLES) {
  test(`the ${role} of A is refused every workspace-B page and action and never sees B`, async ({
    page,
    harness,
    as,
    axe,
  }) => {
    test.setTimeout(120_000);
    const b = await harness.fixture<BObjects>('isolation_b_objects');
    const marker = harness.ids.workspace_names.b.split(' ')[0];
    expect(b.workspace_name).toContain(marker);
    const objects = objectsOf(b);
    const { urls } = await harness.probe<Urls>('isolation_urls', { workspace_id: b.workspace_id, ...objects });
    expect(urls.length).toBeGreaterThanOrEqual(200);
    expect(urls.every((url) => url.path.includes(b.workspace_id))).toBe(true);

    await as(role);
    await page.goto('/');
    const token = await csrfToken(page);
    const get = (url: UrlEntry) => page.request.get(url.path, { maxRedirects: 0 });
    const headers = { 'X-CSRFToken': token };
    const form = { ...objects, caption: `${marker} from A`, action: 'approve', status: 'approved' };
    const post = (url: UrlEntry) => page.request.post(url.path, { headers, form, maxRedirects: 0 });
    const before = await harness.probe('isolation_b_state', objects);

    // Every page and action of B, read: 403 or 404, never B's name.
    expect(await problems(urls, get, marker, status())).toEqual([]);

    // A sample of B's actions, posted with a token that passes the CSRF check (the control first).
    const control = await page.request.post(`/notifications/${crypto.randomUUID()}/read/`, {
      headers,
      form: {},
      maxRedirects: 0,
    });
    expect(control.status(), 'the token passes the CSRF check').not.toBe(403);
    expect(await problems(byName(urls, POST_ACTIONS), post, marker, status())).toEqual([]);

    // B's rows under A's own URLs: the pages and the actions answer 404 (or 403 for a role refused
    // first), and nothing under A that takes one of B's ids shows anything of B.
    const underA = await harness.probe<Urls>('isolation_urls', { workspace_id: harness.ids.workspace_a, ...objects });
    const objectUrls = underA.urls.filter((url) => url.objects.length > 0);
    expect(objectUrls.length).toBeGreaterThanOrEqual(50);
    const refusedFirst = role === 'client' ? status(403, 404) : status(404);
    expect(await problems(byName(underA.urls, OBJECT_PAGES_UNDER_A), get, marker, refusedFirst)).toEqual([]);
    const lookup = role === 'owner' ? status(404) : status(403, 404);
    expect(await problems(byName(underA.urls, OBJECT_ACTIONS_UNDER_A), post, marker, lookup)).toEqual([]);
    expect(await problems(objectUrls, get, marker, showsNothingOf(Object.values(objects)))).toEqual([]);
    expect(await harness.probe('isolation_b_state', objects), "B's rows are unchanged").toEqual(before);

    // Two refusals as a person meets them, in the browser.
    const [studio] = byName(urls, ['studio:index']);
    const refused = await page.goto(studio.path);
    expect(REFUSED).toContain(refused?.status());
    await axe(page, `Workspace B refused (${role})`);
    // B's post under A, on a page this role may open: the agency's brief page, or the post's versions.
    const [detail] = byName(underA.urls, [role === 'client' ? 'approvals:version_diff' : 'studio:detail']);
    const missing = await page.goto(detail.path);
    expect(missing?.status()).toBe(404);
    await axe(page, `${detail.name} with B's row under A (${role})`);
  });
}
