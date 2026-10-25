// Golden path 11: a member of workspace A is refused every workspace-B URL, and never sees B's data.
//
// The URLs come from the URL resolver (the isolation_urls probe): every pattern that takes a
// workspace_id, filled with B's id and with one row of every kind those URLs name, made in B by the
// isolation_b_objects fixture, so a page added tomorrow is covered without touching this file, and a
// new kind of row shows up below (SAMPLE_PARTS) the day a URL takes one. Each of B's URLs answers 403
// or 404 to every method its view accepts (today the membership middleware answers 403 before any
// view runs; see docs/specs/01-harness.md, path 11), and no answer carries B's name.
//
// Then B's rows under A's own URLs: every one is requested with every method its view accepts, with
// the input each action needs to reach its lookup. For the owner, who may do everything in A, the
// answer is the 404 of the workspace-scoped lookup, or for a few named views the answer that view
// gives for a row A does not have (notFoundAnswers, each read in the view). A role refused first
// answers 403. B's rows are read back to show that nothing moved. Two refusal pages are opened in the
// browser and checked with axe. Requests go through page.request, which carries the browser
// context's session.
import type { APIResponse, Page } from '@playwright/test';

import { expect, test } from '../support/test';

type UrlEntry = {
  name: string;
  route: string;
  path: string;
  objects: string[];
  samples: string[];
  methods: string[] | null;
  resolves_to: string;
};
type Urls = { count: number; urls: UrlEntry[] };
type BObjects = { workspace_id: string; workspace_name: string; objects: Record<string, string> };
type Answer = { status: number; location: string; body: string };
type Rule = (answer: Answer) => string | null;
type Method = 'GET' | 'POST';

const ROLES = ['owner', 'editor', 'client'] as const;
const PARALLEL = 8;

/**
 * The parts of A's URLs that no row of B fills, with the reason. Every other part a workspace URL
 * takes is filled with one of B's rows; a URL that takes a new kind of row fails here until
 * isolation_b_objects makes one (tests/e2e/server/steps/g1.py, _B_ROWS) or it is added, with its
 * reason, after review.
 */
const SAMPLE_PARTS: Record<string, string> = {
  'studio:brand_sample:template': 'a layout name, not a row',
  'telegram:deactivate_chat:chat_id': 'A has no bot, so the view refuses (403) before any lookup',
  'telegram:disconnect_channel:channel_id': 'A has no bot, so the view refuses (403) before any lookup',
};

/** A one-pixel PNG, for the actions that take a file before they look anything up. */
const PNG = Buffer.from(
  '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489' +
    '0000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082',
  'hex',
);

/**
 * What every POST sends: enough of each action's input that it reaches its lookup (a comment body, a
 * file, the confirmations a delivery check asks for). Nothing in it names B, so an answer that echoes
 * the input is never taken for one that shows B.
 */
const FORM = {
  caption: 'Written from A',
  body: 'Written from A',
  action: 'approve',
  status: 'approved',
  confirmed: '1',
  native_post_id: 'e2e-native-from-a',
  reason: 'Checked the account from A',
  file: { name: 'from-a.png', mimeType: 'image/png', buffer: PNG },
};

function status(...allowed: number[]): Rule {
  return (answer) => (allowed.includes(answer.status) ? null : `answered ${answer.status}`);
}

/** 200 with exactly this JSON: an idempotent action's "nothing done" for a row it did not find. */
function json(expected: Record<string, unknown>): Rule {
  return (answer) => {
    let body: unknown;
    try {
      body = JSON.parse(answer.body);
    } catch {
      body = answer.body;
    }
    const same = answer.status === 200 && JSON.stringify(body) === JSON.stringify(expected);
    return same ? null : `answered ${answer.status} ${answer.body.slice(0, 80)}`;
  };
}

/** 200 with nothing in it. */
const empty: Rule = (answer) =>
  answer.status === 200 && answer.body.trim() === '' ? null : `answered ${answer.status} with a body`;

/** A redirect to exactly this path. */
function redirectTo(path: string): Rule {
  return (answer) =>
    answer.status === 302 && answer.location === path ? null : `answered ${answer.status} ${answer.location}`;
}

/** A redirect to a page under this prefix that carries none of B's ids. */
function redirectUnder(prefix: string, ids: string[]): Rule {
  return (answer) => {
    if (answer.status !== 302 || !answer.location.startsWith(prefix)) {
      return `answered ${answer.status} ${answer.location}`;
    }
    return ids.some((id) => answer.location.includes(id)) ? `redirected to B's row: ${answer.location}` : null;
  };
}

function byName(urls: UrlEntry[], names: string[]): UrlEntry[] {
  const found = names.map((name) => urls.find((url) => url.name === name));
  const missing = names.filter((_name, index) => !found[index]);
  expect(missing, 'every named URL still exists').toEqual([]);
  return found as UrlEntry[];
}

/**
 * Object URLs under A that answer a row A does not have with something other than 404, and what
 * they answer instead. Each was read in its view: none of them shows B or acts on B's row (the state
 * check after the sweep is what proves the second).
 */
function notFoundAnswers(a: string, urls: UrlEntry[], ids: string[]): Record<string, Rule> {
  const [home, job] = byName(urls, ['studio:index', 'studio:job']);
  return {
    // Shows A's own preferred account instead.
    'analytics:account': redirectUnder(`/workspace/${a}/analytics/`, ids),
    // Takes the id off this person's own list of pending uploads in the session; never reads the row.
    'composer:remove_pending_media': empty,
    // Unsplash is not set up on the e2e server: 503 before the lookup.
    'composer:unsplash_import_post': status(503),
    // Idempotent on purpose: a slot or queue entry that is not there is "nothing done".
    'calendar:delete_posting_slot': json({ deleted: false }),
    'calendar:update_posting_slot': json({ updated: false }),
    'calendar:queue_entry_remove': json({ removed: false }),
    // The comment and delivery services' scoped lookups answer "not found here" as a bad request.
    'approvals:delete_comment': status(400),
    'studio:publisher_delivery:reconcile_existing': status(400),
    'studio:publisher_delivery:checked_absent': status(400),
    // Says the idea could not be started, on A's Home.
    'studio:workflow_resume': redirectTo(home.path),
    // Says the job could not be changed, on A's page for that job id, which answers 404 (swept too).
    'studio:coworker_job_control': redirectTo(job.path),
  };
}

/** Views that answer people who may not use them with an empty partial, instead of a 403. */
const EMPTY_WHEN_REFUSED = ['blog:team_panel'];

function accepts(url: UrlEntry, method: Method): boolean {
  return url.methods === null || url.methods.includes(method);
}

/** Every URL with every method its view accepts. */
function everyMethod(urls: UrlEntry[]): { url: UrlEntry; method: Method }[] {
  return (['GET', 'POST'] as const).flatMap((method) =>
    urls.filter((url) => accepts(url, method)).map((url) => ({ url, method })),
  );
}

async function csrfToken(page: Page): Promise<string> {
  const token = (await page.context().cookies()).find((cookie) => cookie.name === 'csrftoken')?.value;
  expect(token, 'the page set a CSRF cookie').toBeTruthy();
  return String(token);
}

/** Send every request, a few at a time; list each answer its URL's rule refuses or that carries B's name. */
async function problems(
  requests: { url: UrlEntry; method: Method }[],
  send: (url: UrlEntry, method: Method) => Promise<APIResponse>,
  marker: string,
  rule: (url: UrlEntry) => Rule,
): Promise<string[]> {
  const found: string[] = [];
  for (let start = 0; start < requests.length; start += PARALLEL) {
    await Promise.all(
      requests.slice(start, start + PARALLEL).map(async ({ url, method }) => {
        const response = await send(url, method);
        const answer = {
          status: response.status(),
          location: response.headers()['location'] ?? '',
          body: await response.text(),
        };
        const problem = rule(url)(answer);
        if (problem) {
          found.push(`${method} ${url.name} ${url.path}: ${problem}`);
        }
        if (answer.body.includes(marker)) {
          found.push(`${method} ${url.name} ${url.path}: shows "${marker}"`);
        }
      }),
    );
  }
  return found;
}

for (const role of ROLES) {
  test(`the ${role} of A is refused every workspace-B URL, and B's rows under A's URLs are not found`, async ({
    page,
    harness,
    as,
    axe,
  }) => {
    test.setTimeout(240_000);
    const a = harness.ids.workspace_a;
    const b = await harness.fixture<BObjects>('isolation_b_objects');
    const marker = harness.ids.workspace_names.b.split(' ')[0];
    expect(b.workspace_name).toContain(marker);
    const ids = Object.values(b.objects);
    const { urls } = await harness.probe<Urls>('isolation_urls', { workspace_id: b.workspace_id, ...b.objects });
    expect(urls.length).toBeGreaterThanOrEqual(200);
    expect(urls.every((url) => url.path.includes(b.workspace_id))).toBe(true);

    await as(role);
    await page.goto('/');
    const token = await csrfToken(page);
    const headers = { 'X-CSRFToken': token };
    const send = (url: UrlEntry, method: Method) =>
      method === 'GET'
        ? page.request.get(url.path, { maxRedirects: 0 })
        : page.request.post(url.path, { headers, multipart: FORM, maxRedirects: 0 });
    const before = await harness.probe('isolation_b_state', b.objects);

    // The token passes the CSRF check for a request shaped like the sweep's (the control first).
    const control = await page.request.post(`/notifications/${crypto.randomUUID()}/read/`, {
      headers,
      multipart: FORM,
      maxRedirects: 0,
    });
    expect(control.status(), 'the token passes the CSRF check').not.toBe(403);

    // Every page and action of B, with every method its view accepts: 403 or 404, never B's name.
    const toB = everyMethod(urls);
    expect(toB.filter((request) => request.method === 'POST').length).toBeGreaterThanOrEqual(150);
    expect(await problems(toB, send, marker, () => status(403, 404))).toEqual([]);

    // A's own URLs, with B's rows in them: every part is one of B's rows, but for the reviewed few.
    const underA = await harness.probe<Urls>('isolation_urls', { workspace_id: a, ...b.objects });
    const sampled = underA.urls.flatMap((url) => url.samples.map((part) => `${url.name}:${part}`));
    expect(sampled.sort()).toEqual(Object.keys(SAMPLE_PARTS).sort());
    const objectUrls = underA.urls.filter((url) => url.objects.length > 0);
    expect(objectUrls.length).toBeGreaterThanOrEqual(120);
    const [article, message, idea] = byName(underA.urls, ['blog:detail', 'inbox:message_detail', 'composer:idea_move']);
    expect(article.path, "an article URL carries B's article").toContain(b.objects['blog:post_id']);
    expect(message.path).toContain(b.objects.message_id);
    expect(idea.path).toContain(b.objects.idea_id);

    // The owner reaches every lookup: 404, or the named view's own answer. Another role answers that
    // too, or is refused first: 403 (or 404), or an empty partial where that is how the view refuses.
    const named = notFoundAnswers(a, underA.urls, ids);
    const rule = (url: UrlEntry): Rule => {
      const own = named[url.name] ?? status(404);
      if (role === 'owner') {
        return own;
      }
      return (answer) => {
        const refused = [403, 404].includes(answer.status);
        const emptyRefusal = EMPTY_WHEN_REFUSED.includes(url.name) && empty(answer) === null;
        return refused || emptyRefusal ? null : own(answer);
      };
    };
    // Each action is posted once. The views' rate-limit counters are cleared before and after, so the
    // limited actions are included and nobody's allowance is used up for a later test.
    await harness.fixture('reset_rate_limits');
    try {
      expect(await problems(everyMethod(objectUrls), send, marker, rule)).toEqual([]);
    } finally {
      await harness.fixture('reset_rate_limits');
    }
    expect(await harness.probe('isolation_b_state', b.objects), "B's rows are unchanged").toEqual(before);

    // Two refusals as a person meets them, in the browser.
    const [studio] = byName(urls, ['studio:index']);
    const refused = await page.goto(studio.path);
    expect([403, 404]).toContain(refused?.status());
    await axe(page, `Workspace B refused (${role})`);
    // B's post under A, on a page this role may open: the agency's brief page, or the post's versions.
    const [detail] = byName(underA.urls, [role === 'client' ? 'approvals:version_diff' : 'studio:detail']);
    const missing = await page.goto(detail.path);
    expect(missing?.status()).toBe(404);
    await axe(page, `${detail.name} with B's row under A (${role})`);
  });
}
