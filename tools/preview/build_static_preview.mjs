#!/usr/bin/env node
// Build a static, read-only preview of SM Bean from the e2e harness's demo data (tools/preview/README.md).
//
// Against a running e2e server (python -m tests.e2e.server --reset), it adds demo data through the
// harness's own fixtures and the app's own Home thread, signs in as the seeded owner, crawls the
// app's pages breadth-first (GET only, same origin), then the public pages signed out, and writes
// each page's server HTML with the HTMX fragments those pages ask for, the collected static files,
// the media they show and the few files Netlify reads. Nothing in the output can save anything.
//
//   node tools/preview/build_static_preview.mjs --base-url http://127.0.0.1:8401 \
//     --out <empty folder> --sha <commit> [--app-dir .] [--python .venv/bin/python]
//     [--db-name <the server's DB_NAME>] [--max-pages 500] [--max-fragments 400] [--no-demo-data]
import { spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import process from 'node:process';

const BAR_TEXT = 'Preview with demo data. Nothing you do here is saved.';
const BAR_HEIGHT = 32;
/** Query keys that change what a page shows: their variants get a path of their own. */
const VARIANT_KEYS = ['mode', 'view', 'tab'];
/** At most this many pages of one shape (ids replaced), so a long list of rows cannot flood the crawl. */
const PER_SHAPE = 12;
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;

// ---------------------------------------------------------------------------------------------
// Arguments and Playwright
// ---------------------------------------------------------------------------------------------

function parseArgs(argv) {
  const args = { maxPages: 500, maxFragments: 400, demoData: true, appDir: process.cwd() };
  const names = {
    '--base-url': 'baseUrl',
    '--out': 'out',
    '--sha': 'sha',
    '--app-dir': 'appDir',
    '--python': 'python',
    '--db-name': 'dbName',
    '--max-pages': 'maxPages',
    '--max-fragments': 'maxFragments',
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--no-demo-data') {
      args.demoData = false;
      continue;
    }
    const [flag, inline] = arg.includes('=') ? arg.split(/=(.*)/s, 2) : [arg, undefined];
    const key = names[flag];
    if (!key) throw new Error(`Unknown argument ${arg}.`);
    const value = inline ?? argv[++i];
    if (value === undefined) throw new Error(`${flag} needs a value.`);
    args[key] = key.startsWith('max') ? Number(value) : value;
  }
  for (const required of ['baseUrl', 'out', 'sha']) {
    if (!args[required]) throw new Error(`--${required.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)} is required.`);
  }
  args.appDir = path.resolve(args.appDir);
  args.out = path.resolve(args.out);
  args.python = args.python || process.env.PREVIEW_PYTHON || path.join(args.appDir, '.venv/bin/python');
  args.baseUrl = args.baseUrl.replace(/\/+$/, '');
  args.dbName = args.dbName || process.env.DB_NAME || '';
  return args;
}

function loadPlaywright(appDir) {
  for (const base of [import.meta.url, path.join(process.cwd(), 'noop.js'), path.join(appDir, 'noop.js')]) {
    try {
      return createRequire(base)('@playwright/test');
    } catch {
      // try the next place
    }
  }
  throw new Error('Cannot load @playwright/test: run `npm ci --ignore-scripts` in the repository, or pass --app-dir.');
}

const log = (...parts) => console.log('[preview]', ...parts);

// ---------------------------------------------------------------------------------------------
// The harness: fixtures, probes and demo data
// ---------------------------------------------------------------------------------------------

async function harnessCall(api, method, name, body) {
  const url = `/__e2e__/${method === 'post' ? 'fixture' : 'probe'}/${encodeURIComponent(name)}`;
  const response = method === 'post' ? await api.post(url, { data: body }) : await api.get(url, { params: body });
  if (!response.ok()) throw new Error(`e2e ${name} answered ${response.status()}: ${(await response.text()).slice(0, 300)}`);
  return response.json();
}
const fixture = (api, name, payload = {}) => harnessCall(api, 'post', name, payload);
const probe = (api, name, params = {}) => harnessCall(api, 'get', name, params);

async function until(read, done, what, timeoutMs = 120_000) {
  const start = Date.now();
  let last;
  while (Date.now() - start < timeoutMs) {
    last = await read();
    if (done(last)) return last;
    await new Promise((resolve) => setTimeout(resolve, 750));
  }
  throw new Error(`Timed out waiting until ${what}: ${JSON.stringify(last).slice(0, 400)}`);
}

const DEMO = {
  review: [
    {
      author: 'editor',
      accounts: ['instagram', 'facebook'],
      days_ahead: 2,
      hour: 10,
      caption:
        'Open house this Saturday at the Kokapet site office, 10:00 to 17:00. Walk through the show flat, meet the site engineer and stay for chai. Free parking on visit days.',
    },
    {
      author: 'manager',
      accounts: ['linkedin_company'],
      days_ahead: 4,
      hour: 16,
      caption:
        'Tower B has reached its 14th floor slab, two weeks ahead of the plan we shared in June. Thank you to everyone on site who made it happen.',
    },
  ],
  scheduled: [
    {
      author: 'editor',
      accounts: ['linkedin_company'],
      days_ahead: 1,
      hour: 11,
      caption:
        'The three questions first-time buyers ask us most: how long the loan approval takes, what the maintenance fee covers, and when they can move in. Our sales team answers all three in a short guide, free at the site office.',
    },
    {
      author: 'editor',
      accounts: ['instagram'],
      days_ahead: 3,
      hour: 18,
      caption: 'Golden hour from the clubhouse terrace. The pool deck opens to residents in December.',
    },
    {
      author: 'manager',
      accounts: ['facebook', 'instagram'],
      days_ahead: 6,
      hour: 9,
      caption: 'Site visits continue every Saturday through the festive season. WhatsApp the sales office for the availability list.',
    },
    {
      author: 'editor',
      accounts: ['linkedin_company'],
      days_ahead: 9,
      hour: 12,
      caption: 'Meet the people building Neopolis: Ravi has led our concrete crew for eleven years. This month he trained twelve new apprentices.',
    },
  ],
  goAhead: 'Post about the Saturday site visit on Instagram and LinkedIn, mention free parking on visit days',
  waiting: 'Post about the clubhouse on LinkedIn, mention the pool deck opens to residents in December',
  notification: 'Two posts are waiting for your review',
};

/** Ask the team on Home the way a person does; optionally go ahead and wait for the draft. */
async function askTheTeam(page, api, workspace, body, goAhead) {
  const read = () => probe(api, 'home_request', { workspace_id: workspace, body });
  await page.goto(`/workspace/${workspace}/studio/`);
  const thread = page.getByTestId('home-thread');
  await thread.getByTestId('thread-composer-body').fill(body);
  await thread.getByTestId('thread-composer-send').click();
  const asked = await until(read, (s) => s.reply !== null || ['failed', 'cancelled'].includes(s.ask?.status), 'the manager answers');
  if (!asked.reply) throw new Error(`The manager did not answer: ${JSON.stringify(asked.ask)}`);
  if (!goAhead) return asked;
  await page.goto(`/workspace/${workspace}/studio/`);
  const card = page.getByTestId(`thread-message-${asked.reply.id}`).getByTestId('thread-brief-card');
  await card.getByTestId('thread-brief-go-ahead').click({ timeout: 20_000 });
  return until(read, (s) => ['ready', 'failed'].includes(s.brief?.status), 'the team finishes the draft', 150_000);
}

async function prepareDemoData(api, browserContext, ids, ownerEmail) {
  const workspace = ids.workspace_a;
  const page = await browserContext.newPage();
  try {
    const approvals = await page.request.get(`/workspace/${workspace}/approvals/`, { maxRedirects: 0 });
    if (approvals.status() !== 200) throw new Error(`The owner cannot open Approvals (${approvals.status()}).`);
    if ((await approvals.text()).includes(DEMO.review[0].caption.slice(0, 40))) {
      log('demo data already present; adding nothing');
      return;
    }
    await fixture(api, 'set_agent_delay', { seconds: 0 });
    for (const post of DEMO.review) await fixture(api, 'publishing_review_post', post);
    for (const post of DEMO.scheduled) await fixture(api, 'publishing_scheduled_post', post);
    const draft = await askTheTeam(page, api, workspace, DEMO.goAhead, true);
    log(`the team's draft is ${draft.brief?.status}`);
    await askTheTeam(page, api, workspace, DEMO.waiting, false);
    await fixture(api, 'unread_notification', { email: ownerEmail, title: DEMO.notification });
    log('demo data added');
  } finally {
    await page.close();
  }
}

// ---------------------------------------------------------------------------------------------
// URLs: what to skip, page keys and shapes
// ---------------------------------------------------------------------------------------------

const SKIP_PREFIXES = [
  '/admin',
  '/__e2e__/',
  '/api/',
  '/oauth/',
  '/.well-known/',
  '/portal/',
  '/webhooks/',
  '/static/',
  '/media/',
  '/health/',
  '/accounts/logout',
  '/accounts/google/',
  '/blog/search-console/',
];
/** Anything that deletes, disconnects or leaves, wherever it sits in the path. */
const SKIP_DESTRUCTIVE =
  /(^|\/)(delete|remove|disconnect|revoke|unpair|deactivate|destroy|discard|logout|signout|sign-out|export|download|switch)(\/|$)/i;
/** An action ends the path (`/posts/<id>/approve/`); `publish/queue/` is a list, not an action. */
const SKIP_ACTION =
  /(^|\/)(approve|reject|publish|retry|run|run-now|pause|resume|stop|send|toggle|dismiss|confirm|clone|duplicate|star|restore|sync|mark-all-read|mark_all_read|read|go-ahead)\/?$/i;
const SKIP_ANYWHERE = /(mcp|oauth|callback|authorize|\/connect\/[^/]+|export|download|\.(csv|zip|pdf|ics|xml|json|txt|xlsx)$)/i;

function skipReason(url) {
  const pathname = url.pathname;
  if (SKIP_PREFIXES.some((prefix) => pathname.startsWith(prefix))) return 'excluded section';
  if (SKIP_DESTRUCTIVE.test(pathname) || SKIP_ACTION.test(pathname)) return 'action or destructive path';
  if (SKIP_ANYWHERE.test(pathname)) return 'oauth, export or download';
  if (pathname === '/favicon.ico' || pathname === '/robots.txt' || pathname === '/sitemap.xml') return 'site file';
  return null;
}

function hasVariant(url) {
  return VARIANT_KEYS.some((key) => url.searchParams.get(key));
}

/** A page is its path plus the query keys that change it; every other query key is left out. */
function pageKey(url) {
  const params = new URLSearchParams();
  for (const key of VARIANT_KEYS) {
    const value = url.searchParams.get(key);
    if (value) params.set(key, value);
  }
  const query = params.toString();
  return url.pathname + (query ? `?${query}` : '');
}

function shapeOf(key) {
  return key.replace(UUID, ':id').replace(/\/\d+(?=\/|\?|$)/g, '/:n');
}

const withSlash = (pathname) => (pathname.endsWith('/') ? pathname : `${pathname}/`);
const slug = (text) =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60) || 'x';
const hash8 = (text) => crypto.createHash('sha1').update(text).digest('hex').slice(0, 8);

// ---------------------------------------------------------------------------------------------
// HTML: splitting, tags and attributes
// ---------------------------------------------------------------------------------------------

/** Markup and raw-text parts, so a tag-looking string inside a script or style is never read as a tag. */
function segments(html) {
  const parts = [];
  const re = /<(script|style)\b[^>]*>([\s\S]*?)<\/\1\s*>/gi;
  let last = 0;
  for (let m = re.exec(html); m; m = re.exec(html)) {
    const openEnd = m.index + m[0].indexOf('>') + 1;
    const closeStart = m.index + m[0].lastIndexOf('</');
    parts.push({ markup: true, text: html.slice(last, openEnd) });
    parts.push({ markup: false, kind: m[1].toLowerCase(), text: html.slice(openEnd, closeStart) });
    last = closeStart;
  }
  parts.push({ markup: true, text: html.slice(last) });
  return parts;
}

const TAG = /<([a-zA-Z][\w:-]*)((?:\s+[^\s"'>/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*)\s*(\/?)>/g;
const ATTR = /([^\s"'>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;

function parseAttrs(text) {
  const attrs = [];
  for (let m = ATTR.exec(text); m; m = ATTR.exec(text)) {
    const quote = m[2] !== undefined ? '"' : m[3] !== undefined ? "'" : m[4] !== undefined ? '' : null;
    attrs.push({ name: m[1], lower: m[1].toLowerCase(), value: m[2] ?? m[3] ?? m[4] ?? null, quote, changed: false });
  }
  ATTR.lastIndex = 0;
  return attrs;
}

function serialiseAttrs(attrs) {
  return attrs
    .filter((attr) => !attr.drop)
    .map((attr) => {
      if (attr.value === null) return ` ${attr.name}`;
      const quote = attr.quote === "'" ? "'" : '"';
      const value = attr.quote === '' && !attr.changed ? attr.value : attr.value.replaceAll(quote, quote === '"' ? '&quot;' : '&#x27;');
      return ` ${attr.name}=${quote}${value}${quote}`;
    })
    .join('');
}

const decodeEntities = (text) =>
  text
    .replace(/&quot;/g, '"')
    .replace(/&#x27;|&#39;|&apos;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&#x2F;|&#47;/gi, '/')
    .replace(/&amp;/g, '&');
const encodeAmp = (text) => text.replace(/&/g, '&amp;');

const attr = (attrs, name) => attrs.find((a) => a.lower === name);
const NAVIGABLE = (value) => value && !/^\s*(#|javascript:|mailto:|tel:|data:)/i.test(value);

// ---------------------------------------------------------------------------------------------
// Scrubbing: what must never be published
// ---------------------------------------------------------------------------------------------

const SECRET_LITERALS = [
  'e2e-secret-key-not-for-production',
  'e2e-salt-not-for-production',
  'e2e-placeholder-not-a-credential',
  'e2e-facebook-app-secret',
  'e2e-facebook-app-id',
  'e2e-google-client-id',
  'e2e-x-client-id',
  'e2e-pass-Neopolis-2026',
];
const SECRET_PATTERNS = [/\be2e-token-[\w-]+/g, /\bsk-[A-Za-z0-9_-]{8,}/g, /\bpk_(?:live|test)_\w+/g];
const ABSOLUTE_PATH = /(?<![\w.:/-])\/(?:home|tmp|root|opt|srv|Users|var\/lib)\/[^\s"'<>`)]*/g;
const ALLOWED_EMAIL = /@(?:[\w-]+\.)*(?:e2e\.test|example\.(?:com|org|net))$/i;
const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
/**
 * Real phone numbers that reach the demo data (the faked team's copy quotes the owner's sales line).
 * Each is replaced in every form it is written in (spaced, run together, escaped, URL-encoded, with
 * or without its country code) by zeros, in the text and in the team's graphics, which are drawn
 * again from their scrubbed words; the build fails if any form is left.
 */
const REAL_PHONES = [{ country: '91', national: '9533686567' }];
const PHONE_SEP = String.raw`(?:[\s.()\-]|&nbsp;|&#160;|\\u00a0|%20)`;
/** One pattern for every number, written so that Python's `re` reads it the same way. */
const PHONE_SOURCE = REAL_PHONES.map(
  ({ country, national }) =>
    String.raw`(?<!\d)(?:(?:\+|%2B)?${country}${PHONE_SEP}*)?` + [...national].join(`${PHONE_SEP}*`) + String.raw`(?!\d)`,
).join('|');
const REAL_PHONE = new RegExp(PHONE_SOURCE, 'gi');
const PHONE_PLACEHOLDER = '+91 00000 00000';
/** Anything else written like a phone number: an international number, a tel: link or a wa.me link. */
const PHONE_LIKE = /(?<![\w.])\+\d{1,3}(?:[\s -]?\d){7,12}(?!\d)|tel:\+?\d[\d\s().-]{6,}|wa\.me\/\d{7,}/gi;

function phonePlaceholder(match) {
  const plain = match.replace(/%2B/gi, '+').replace(/&nbsp;|&#160;|\\u00a0|%20/gi, ' ');
  const digits = plain.replace(/\D/g, '');
  const real = REAL_PHONES.find(({ national }) => digits.endsWith(national));
  const withCountry = real && digits.length > real.national.length;
  const spaced = /[^\d+]/.test(plain);
  return (plain.startsWith('+') ? '+' : '') + (withCountry ? `${real.country}${spaced ? ' ' : ''}` : '') + (spaced ? '00000 00000' : '0000000000');
}

const CSRF_VALUES = [
  // <input name="csrfmiddlewaretoken" value="..."> in either order, and JSON or JS that names the token.
  [/(name=["']csrfmiddlewaretoken["'][^>]*?\svalue=["'])[^"']*/gi, '$1preview'],
  [/(\svalue=["'])[^"']*(["'][^>]*?name=["']csrfmiddlewaretoken["'])/gi, '$1preview$2'],
  [/(csrf[\w-]*(?:&quot;|["'])?\s*[:=,]\s*(?:&quot;|["'])?)[A-Za-z0-9]{20,}/gi, '$1preview'],
  [/(name=["']csrf[\w-]*["'][^>]*?\scontent=["'])[^"']*/gi, '$1preview'],
];

function scrubText(text, origin) {
  const host = new URL(origin).host;
  const port = new URL(origin).port;
  let out = text;
  for (const variant of [origin, origin.replace('127.0.0.1', 'localhost'), origin.replace('localhost', '127.0.0.1')]) {
    out = out.replaceAll(variant, '').replaceAll(variant.replaceAll('/', '\\/'), '');
  }
  out = out.replaceAll(host, 'preview').replaceAll(`localhost:${port}`, 'preview');
  for (const [pattern, replacement] of CSRF_VALUES) out = out.replace(pattern, replacement);
  out = out.replace(/\/portal\/[A-Za-z0-9_-]{16,}\//g, '/portal/preview/');
  out = out.replace(/(\snonce=)("[^"]*"|'[^']*')/g, '');
  for (const literal of SECRET_LITERALS) out = out.replaceAll(literal, '[redacted]');
  for (const pattern of SECRET_PATTERNS) out = out.replace(pattern, '[redacted]');
  out = out.replace(ABSOLUTE_PATH, '[path]');
  out = out.replace(EMAIL, (email) => (ALLOWED_EMAIL.test(email) ? email : 'someone@example.com'));
  out = out.replace(REAL_PHONE, phonePlaceholder);
  return out;
}

/** What a scrubbed output may still hold that looks secret; the build fails when anything is found. */
function findLeaks(text, cookies, { strict = true } = {}) {
  const found = [];
  for (const m of text.matchAll(REAL_PHONE)) found.push(`a real phone number (${m[0].length} characters)`);
  if (strict) {
    for (const m of text.matchAll(PHONE_LIKE)) {
      const digits = m[0].replace(/\D/g, '');
      if (!/^\d{1,3}0+$/.test(digits) && !/^0+$/.test(digits)) found.push(`something written like a phone number: ${m[0]}`);
    }
  }
  for (const literal of SECRET_LITERALS) if (text.includes(literal)) found.push(literal);
  for (const pattern of SECRET_PATTERNS) for (const m of text.matchAll(pattern)) found.push(m[0]);
  for (const cookie of cookies) if (cookie && text.includes(cookie)) found.push('a session or CSRF cookie value');
  for (const m of text.matchAll(/csrfmiddlewaretoken["'][^>]*?value=["']([^"']*)/gi)) if (m[1] !== 'preview') found.push(`csrf ${m[1]}`);
  for (const m of text.matchAll(ABSOLUTE_PATH)) found.push(m[0]);
  for (const m of text.matchAll(EMAIL)) if (!ALLOWED_EMAIL.test(m[0])) found.push(m[0]);
  return found;
}

// ---------------------------------------------------------------------------------------------
// Crawling
// ---------------------------------------------------------------------------------------------

class Crawl {
  constructor({ origin, maxPages, maxFragments }) {
    this.origin = origin;
    this.maxPages = maxPages;
    this.maxFragments = maxFragments;
    this.pages = new Map(); // key -> { key, world, body }
    this.fragments = new Map(); // key -> { key, body, soft }
    this.redirects = { public: new Map(), app: new Map() }; // key -> target key
    this.skipped = new Map(); // key -> reason
    this.assets = new Set(); // pictures and files the pages show, by path and query
    this.shapes = new Map();
  }

  resolve(raw, baseKey) {
    if (!raw) return null;
    const value = decodeEntities(raw.trim());
    if (!NAVIGABLE(value)) return null;
    try {
      const url = new URL(value, this.origin + baseKey);
      return url.origin === this.origin ? url : null;
    } catch {
      return null;
    }
  }

  /** Links, fragments, script URLs and media in one document (a page or a fragment). */
  discover(body, baseKey) {
    const found = { pages: new Set(), fragments: new Map(), soft: new Set() };
    for (const part of segments(body)) {
      if (!part.markup) {
        for (const m of part.text.matchAll(/["'`](\/(?:workspace|notifications|members|accounts|organizations|workspaces|onboarding|social-accounts)\/[^"'`\s<>{}$]*)["'`]/g)) {
          found.soft.add(m[1]);
        }
        for (const m of part.text.matchAll(/url\(\s*["']?([^"')]+)["']?\s*\)/g)) this.noteAsset(m[1], baseKey);
        continue;
      }
      for (const m of part.text.matchAll(TAG)) {
        const tag = m[1].toLowerCase();
        const attrs = parseAttrs(m[2]);
        const href = attr(attrs, 'href');
        const hxGet = attr(attrs, 'hx-get');
        const push = attr(attrs, 'hx-push-url');
        if ((tag === 'a' || tag === 'area') && href && NAVIGABLE(decodeEntities(href.value ?? ''))) {
          const url = this.resolve(href.value, baseKey);
          if (url) found.pages.add(url);
        } else if (hxGet?.value) {
          const url = this.resolve(hxGet.value, baseKey);
          if (url) {
            found.fragments.set(url.pathname + url.search, hxHeaders(attrs, this.origin + baseKey));
            if (push?.value === 'true') found.pages.add(url);
          }
        }
        if (push?.value && !['true', 'false'].includes(push.value)) {
          const url = this.resolve(push.value, baseKey);
          if (url) found.pages.add(url);
        }
        for (const a of attrs) {
          if (!a.value) continue;
          if (['src', 'poster', 'data-src'].includes(a.lower) || (tag === 'link' && a.lower === 'href')) this.noteAsset(a.value, baseKey);
          if (a.lower === 'srcset') for (const piece of a.value.split(',')) this.noteAsset(piece.trim().split(/\s+/)[0], baseKey);
          if (a.lower === 'style') for (const u of a.value.matchAll(/url\(\s*(?:&quot;|["'])?([^"')&]+)/g)) this.noteAsset(u[1], baseKey);
          if (a.lower.startsWith('x-') || a.lower.startsWith('data-') || a.lower.startsWith('@') || a.lower.startsWith(':')) {
            for (const s of decodeEntities(a.value).matchAll(/["'`](\/(?:workspace|notifications|members)\/[^"'`\s<>{}$]*)["'`]/g)) found.soft.add(s[1]);
          }
        }
      }
    }
    return found;
  }

  /** Media and the pictures the app renders itself (the brand samples); static files come from collectstatic. */
  noteAsset(raw, baseKey) {
    const url = this.resolve(raw, baseKey);
    if (!url || url.pathname.startsWith('/static/')) return;
    if (url.pathname.startsWith('/media/') || !skipReason(url)) this.assets.add(url.pathname + url.search);
  }

  allowShape(key) {
    const shape = shapeOf(key);
    const count = this.shapes.get(shape) ?? 0;
    if (count >= PER_SHAPE) return false;
    this.shapes.set(shape, count + 1);
    return true;
  }

  async crawlPages(api, world, seeds) {
    const queue = [];
    const seen = new Set();
    const enqueue = (url) => {
      const key = pageKey(url);
      if (seen.has(key) || this.pages.get(key)?.world === world) return;
      seen.add(key);
      const reason = skipReason(url);
      if (reason) {
        this.skipped.set(key, reason);
        return;
      }
      queue.push(key);
    };
    for (const seed of seeds) enqueue(new URL(seed, this.origin));
    const fragmentQueue = new Map();
    const soft = new Set();
    while (queue.length) {
      const key = queue.shift();
      if (this.pages.size >= this.maxPages) {
        this.skipped.set(key, 'page limit');
        continue;
      }
      if (!this.allowShape(key)) {
        this.skipped.set(key, 'enough pages of this shape');
        continue;
      }
      const response = await api.get(this.origin + key, { maxRedirects: 0, failOnStatusCode: false, timeout: 60_000 });
      const status = response.status();
      if ([301, 302, 303, 307, 308].includes(status)) {
        const target = this.resolve(response.headers().location ?? '', key);
        if (target && !target.pathname.startsWith('/accounts/login')) {
          this.redirects[world].set(key, pageKey(target));
          enqueue(target);
        }
        this.skipped.set(key, `redirect ${status}`);
        continue;
      }
      const type = response.headers()['content-type'] ?? '';
      if (status !== 200 || !type.includes('text/html')) {
        this.skipped.set(key, `${status} ${type.split(';')[0]}`);
        continue;
      }
      // A public page someone signed in also reaches keeps its signed-out copy.
      if (this.pages.has(key)) continue;
      const body = await response.text();
      this.pages.set(key, { key, world, body });
      const found = this.discover(body, key);
      for (const url of found.pages) enqueue(url);
      for (const [fragmentKey, headers] of found.fragments) if (!fragmentQueue.has(fragmentKey)) fragmentQueue.set(fragmentKey, headers);
      for (const value of found.soft) soft.add(value);
    }
    return { fragmentQueue, soft };
  }

  async crawlFragments(api, world, fragmentQueue, soft, pageSeeds) {
    const queue = [...fragmentQueue.entries()].map(([key, headers]) => ({ key, headers, soft: false }));
    for (const value of soft) queue.push({ key: value, headers: { 'HX-Request': 'true' }, soft: true });
    const seen = new Set(queue.map((item) => item.key));
    while (queue.length) {
      const { key, headers, soft: isSoft } = queue.shift();
      if (this.fragments.size >= this.maxFragments) break;
      const url = new URL(key, this.origin);
      if (skipReason(url) || this.fragments.has(key)) continue;
      if (isSoft && (this.pages.has(pageKey(url)) || this.pages.has(url.pathname))) continue;
      const response = await api.get(this.origin + key, { headers, maxRedirects: 0, failOnStatusCode: false, timeout: 60_000 });
      const type = response.headers()['content-type'] ?? '';
      if (response.status() !== 200 || !type.includes('text/html')) continue;
      const body = await response.text();
      this.fragments.set(key, { key, body, soft: isSoft, world });
      const found = this.discover(body, key);
      for (const page of found.pages) pageSeeds.add(page.pathname + page.search);
      for (const [next, nextHeaders] of found.fragments) {
        if (!seen.has(next)) {
          seen.add(next);
          queue.push({ key: next, headers: nextHeaders, soft: false });
        }
      }
    }
  }
}

function hxHeaders(attrs, currentUrl) {
  const headers = { 'HX-Request': 'true', 'HX-Current-URL': currentUrl };
  const target = attr(attrs, 'hx-target')?.value;
  const id = attr(attrs, 'id')?.value;
  if (target?.startsWith('#')) headers['HX-Target'] = target.slice(1);
  else if ((!target || target === 'this') && id) headers['HX-Target'] = id;
  if (id) headers['HX-Trigger'] = id;
  return headers;
}

// ---------------------------------------------------------------------------------------------
// Paths and rewriting
// ---------------------------------------------------------------------------------------------

function assignPaths(crawl) {
  const used = new Map();
  const pageLocal = new Map();
  const ordered = [...crawl.pages.keys()].sort((a, b) => Number(a.includes('?')) - Number(b.includes('?')) || a.localeCompare(b));
  for (const key of ordered) {
    const url = new URL(key, crawl.origin);
    let local = withSlash(url.pathname);
    if (hasVariant(url)) {
      const name = slug(VARIANT_KEYS.map((k) => url.searchParams.get(k)).filter(Boolean).join('-'));
      local = `${withSlash(url.pathname)}${name}/`;
      for (let n = 2; used.has(local); n++) local = `${withSlash(url.pathname)}${name}-view${n > 2 ? n : ''}/`;
    }
    if (used.has(local)) continue;
    used.set(local, key);
    pageLocal.set(key, local);
  }
  const fragmentLocal = new Map();
  for (const key of [...crawl.fragments.keys()].sort()) {
    const { soft } = crawl.fragments.get(key);
    const url = new URL(key, crawl.origin);
    let local = withSlash(url.pathname);
    if (used.has(local)) {
      if (soft) {
        crawl.fragments.delete(key);
        continue;
      }
      local = `/_fragments/${slug(url.pathname)}-${hash8(key)}/`;
    }
    used.set(local, key);
    fragmentLocal.set(key, local);
  }
  return { pageLocal, fragmentLocal };
}

class Rewriter {
  constructor(crawl, paths) {
    this.crawl = crawl;
    this.paths = paths;
  }

  /** Where a page link should go: its own saved path, its variant's path, or a redirect's target. */
  pageHref(raw, baseKey, world) {
    const url = this.crawl.resolve(raw, baseKey);
    if (!url) return null;
    // Signed in, a link goes where the server sent the owner ("/" to Home); signed out, only when unsaved.
    let key = pageKey(url);
    for (let hops = 0; hops < 5; hops++) {
      const target = this.crawl.redirects[world].get(key);
      if (!target || (world === 'public' && this.paths.pageLocal.has(key))) break;
      key = target;
    }
    const local = this.paths.pageLocal.get(key);
    if (local && (local !== withSlash(url.pathname) || key !== pageKey(url))) {
      const rest = new URLSearchParams(url.search);
      for (const k of VARIANT_KEYS) rest.delete(k);
      const query = key === pageKey(url) ? rest.toString() : '';
      return local + (query ? `?${query}` : '') + url.hash;
    }
    return url.pathname + url.search + url.hash;
  }

  fragmentHref(raw, baseKey) {
    const url = this.crawl.resolve(raw, baseKey);
    if (!url) return null;
    const local = this.paths.fragmentLocal.get(url.pathname + url.search);
    if (local && local !== withSlash(url.pathname)) return local;
    return url.pathname + url.search + url.hash;
  }

  rewriteTag(tag, attrs, baseKey, world) {
    const href = attr(attrs, 'href');
    const hxGet = attr(attrs, 'hx-get');
    const set = (a, value) => {
      if (value !== null && value !== a.value) {
        a.value = value;
        a.changed = true;
      }
    };
    if ((tag === 'a' || tag === 'area') && href && NAVIGABLE(decodeEntities(href.value ?? ''))) {
      const mapped = this.pageHref(href.value, baseKey, world);
      if (mapped !== null) set(href, encodeAmp(mapped));
      if (hxGet) {
        // A link that HTMX would load in place: in the preview it is a plain link to the saved page.
        for (const a of attrs) {
          if (/^hx-(get|target|swap|push-url|replace-url|select|trigger|indicator|vals|include|sync|params)$/.test(a.lower)) a.drop = true;
        }
      }
      return;
    }
    if (hxGet?.value) {
      const push = attr(attrs, 'hx-push-url');
      if (push?.value === 'true') {
        const url = this.crawl.resolve(hxGet.value, baseKey);
        const local = url && this.paths.pageLocal.get(pageKey(url));
        if (local) set(push, local);
      }
      const mapped = this.fragmentHref(hxGet.value, baseKey);
      if (mapped !== null) set(hxGet, encodeAmp(mapped));
    }
    for (const name of ['hx-push-url', 'hx-replace-url']) {
      const a = attr(attrs, name);
      if (a?.value && !['true', 'false'].includes(a.value) && !a.changed) {
        const mapped = this.pageHref(a.value, baseKey, world);
        if (mapped !== null) set(a, encodeAmp(mapped));
      }
    }
  }

  rewrite(body, baseKey, world, isPage) {
    const out = [];
    for (const part of segments(body)) {
      if (!part.markup) {
        out.push(part.text);
        continue;
      }
      out.push(
        part.text.replace(TAG, (whole, name, attrText, selfClose) => {
          const tag = name.toLowerCase();
          const attrs = parseAttrs(attrText);
          this.rewriteTag(tag, attrs, baseKey, world);
          let result = `<${name}${serialiseAttrs(attrs)}${selfClose ? ' /' : ''}>`;
          if (!attrs.some((a) => a.changed || a.drop)) result = whole;
          if (isPage && tag === 'body') {
            const style = attr(attrs, 'style');
            if (style) {
              style.value = `${style.value.replace(/;?\s*$/, ';')}padding-top:${BAR_HEIGHT}px`;
              style.changed = true;
            } else {
              attrs.push({ name: 'style', lower: 'style', value: `padding-top:${BAR_HEIGHT}px`, quote: '"', changed: true });
            }
            result = `<${name}${serialiseAttrs(attrs)}>${previewBar()}`;
          }
          return result;
        }),
      );
    }
    let html = out.join('');
    if (isPage) html = html.replace(/<\/head>/i, `${previewStyle()}${previewScript()}</head>`);
    return html;
  }
}

function previewBar() {
  return (
    `<div role="note" data-preview-bar style="position:fixed;top:0;left:0;right:0;height:${BAR_HEIGHT}px;z-index:25;` +
    'display:flex;align-items:center;justify-content:center;padding:0 16px;box-sizing:border-box;' +
    "background:#0D4534;color:#FFFFFF;font:500 13px/1.2 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;" +
    'white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' +
    `${BAR_TEXT}</div>`
  );
}

/** The app shell is one screen tall and the public header sticks to the top: both make room for the bar. */
function previewStyle() {
  return (
    `<style data-preview>body>.h-screen{height:calc(100vh - ${BAR_HEIGHT}px)}` +
    `.mk-header{top:${BAR_HEIGHT}px}</style>`
  );
}

// ---------------------------------------------------------------------------------------------
// Output
// ---------------------------------------------------------------------------------------------

function prepareOut(out) {
  if (fs.existsSync(out)) {
    const entries = fs.readdirSync(out);
    if (entries.length && !entries.includes('preview.json')) {
      throw new Error(`${out} is not empty and holds no earlier preview: give an empty or new folder.`);
    }
    fs.rmSync(out, { recursive: true, force: true });
  }
  fs.mkdirSync(out, { recursive: true });
}

function writeFile(out, local, content) {
  const relative = local.replace(/^\/+/, '');
  const file = path.join(out, ...relative.split('/').map((piece) => decodeURIComponent(piece)));
  if (!file.startsWith(out + path.sep)) throw new Error(`Refusing to write outside ${out}: ${local}`);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, content);
  return file;
}

/**
 * `manage.py collectstatic --noinput` with the e2e settings into a temporary STATIC_ROOT inside the
 * app's gitignored e2e_media/ (a two-line settings module that only moves STATIC_ROOT), then a copy.
 */
function collectStatic(args, out) {
  const root = fs.mkdtempSync(path.join(args.appDir, 'e2e_media', 'preview-static-'));
  const staticRoot = path.join(root, 'static');
  fs.writeFileSync(
    path.join(root, 'preview_static_settings.py'),
    `from config.settings.e2e import *  # noqa: F403\n\nSTATIC_ROOT = ${JSON.stringify(staticRoot)}\n`,
  );
  const env = {
    ...process.env,
    DJANGO_SETTINGS_MODULE: 'preview_static_settings',
    PYTHONPATH: [root, args.appDir, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
    E2E_STATIC: '',
  };
  env.DB_NAME = env.DB_NAME || 'brightbean_preview_e2e';
  try {
    const result = spawnSync(args.python, ['manage.py', 'collectstatic', '--noinput', '-v', '0'], {
      cwd: args.appDir,
      env,
      encoding: 'utf8',
    });
    if (result.status !== 0) throw new Error(`collectstatic failed: ${result.stderr || result.stdout || result.error}`);
    fs.cpSync(staticRoot, path.join(out, 'static'), { recursive: true });
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
  const favicon = path.join(out, 'static', 'favicon', 'favicon.ico');
  if (fs.existsSync(favicon)) fs.copyFileSync(favicon, path.join(out, 'favicon.ico'));
}

/**
 * Read-only, in the app's own Python against the server's database: what each /media/ file the pages
 * show may be published as. An upload is kept. A team graphic is the brief's words drawn on a picture,
 * so text scrubbing cannot reach it: the brief's current graphic is drawn again by the app's renderer
 * from its scrubbed design (and its thumbnail made the media library's way), and any earlier team
 * graphic is withheld. A file the database does not know means the wrong database: the build stops.
 */
const MEDIA_REVIEW_PY = String.raw`
import io
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

import django

django.setup()

from django.conf import settings
from django.db import transaction
from django.db.models import Q

from apps.media_library.models import MediaAsset
from apps.media_library.services import generate_image_thumbnail
from apps.studio import design, style
from apps.studio.models import BrandProfile, StudioBrief

request = json.load(sys.stdin)
phone = re.compile(request["pattern"], re.IGNORECASE)
out_dir = Path(request["out_dir"])


def placeholder(match):
    plain = re.sub(r"&nbsp;|&#160;|\\u00a0|%20", " ", re.sub(r"%2B", "+", match.group(0), flags=re.I), flags=re.I)
    digits = re.sub(r"\D", "", plain)
    country = next((p["country"] for p in request["phones"] if digits.endswith(p["national"]) and len(digits) > len(p["national"])), "")
    spaced = bool(re.search(r"[^\d+]", plain))
    prefix = ("+" if plain.startswith("+") else "") + (country + (" " if spaced else "") if country else "")
    return prefix + ("00000 00000" if spaced else "0000000000")


def text_of(value):
    return json.dumps(value, ensure_ascii=False, default=str)


verdicts = {}
with transaction.atomic():
    for path in request["paths"]:
        name = unquote(path[len(settings.MEDIA_URL):]) if path.startswith(settings.MEDIA_URL) else ""
        asset = MediaAsset.objects.filter(Q(file=name) | Q(thumbnail=name)).first() if name else None
        if asset is None:
            verdicts[path] = {"action": "unknown"}
            continue
        if asset.source != "ai-studio":
            verdicts[path] = {"action": "keep"}
            continue
        brief = StudioBrief.objects.filter(graphic=asset).select_related("workspace", "picture").first()
        if brief is None:
            verdicts[path] = {"action": "withhold", "why": "an earlier team graphic"}
            continue
        spec = json.loads(phone.sub(placeholder, text_of(brief.design_spec or {})))
        profile = BrandProfile.objects.get(workspace=brief.workspace)
        look = design.Look.from_profile(profile, style.read_asset(profile.logo) if profile.logo_id else None)
        picture = style.read_asset(brief.picture) if brief.picture_id and spec.get("use_picture") else None
        try:
            content = design.render(spec, look, picture)
        except ValueError:
            content = design.render(spec, look, None)
        if name == asset.thumbnail.name:
            thumb = generate_image_thumbnail(io.BytesIO(content))
            if thumb is None:
                verdicts[path] = {"action": "withhold", "why": "its thumbnail could not be made again"}
                continue
            content = thumb.read()
        target = out_dir / f"{len(verdicts)}.jpg"
        target.write_bytes(content)
        verdicts[path] = {
            "action": "replace",
            "file": str(target),
            "had_phone": bool(phone.search(text_of([brief.design_spec, brief.post_copy]))),
        }
    profiles_with_phone = [
        str(profile.workspace_id)
        for profile in BrandProfile.objects.all()
        if phone.search(text_of({f.attname: getattr(profile, f.attname) for f in profile._meta.concrete_fields}))
    ]
    transaction.set_rollback(True)
print(json.dumps({"verdicts": verdicts, "profiles_with_phone": profiles_with_phone}))
`;

function reviewMedia(args, paths) {
  const root = fs.mkdtempSync(path.join(args.appDir, 'e2e_media', 'preview-media-'));
  const env = {
    ...process.env,
    DJANGO_SETTINGS_MODULE: 'config.settings.e2e',
    PYTHONPATH: [args.appDir, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
    E2E_STATIC: '',
  };
  if (args.dbName) env.DB_NAME = args.dbName;
  const result = spawnSync(args.python, ['-c', MEDIA_REVIEW_PY], {
    cwd: args.appDir,
    env,
    encoding: 'utf8',
    input: JSON.stringify({ paths, pattern: PHONE_SOURCE, phones: REAL_PHONES, out_dir: root }),
    maxBuffer: 16 * 1024 * 1024,
  });
  if (result.status !== 0) {
    fs.rmSync(root, { recursive: true, force: true });
    throw new Error(`The media review failed: ${(result.stderr || result.stdout || String(result.error)).slice(-2000)}`);
  }
  const review = JSON.parse(result.stdout.trim().split('\n').pop());
  const unknown = Object.entries(review.verdicts).filter(([, v]) => v.action === 'unknown').map(([p]) => p);
  if (unknown.length) {
    fs.rmSync(root, { recursive: true, force: true });
    throw new Error(`The database (DB_NAME ${env.DB_NAME ?? 'unset'}) does not know ${unknown.length} media files the pages show, such as ${unknown[0]}: pass the server's --db-name.`);
  }
  return { ...review, cleanup: () => fs.rmSync(root, { recursive: true, force: true }) };
}

/**
 * Cancels every HTMX request other than GET (there is no server to receive it) and says so after
 * something the person did; a request a page sends on its own as it loads is dropped quietly.
 */
function previewScript() {
  return (
    '<script data-preview>(function(){var last=0,box=null,timer=0;' +
    "function mark(){last=Date.now()}['pointerdown','keydown'].forEach(function(t){document.addEventListener(t,mark,true)});" +
    "function ensure(){if(box||!document.body)return box;box=document.createElement('div');box.setAttribute('role','status');box.setAttribute('data-preview-note','');" +
    `box.style.cssText='position:fixed;top:${BAR_HEIGHT + 8}px;left:50%;transform:translateX(-50%);z-index:2147483000;max-width:calc(100% - 32px);` +
    "box-sizing:border-box;padding:8px 12px;border-radius:8px;background:#0E1114;color:#FFFFFF;font:500 13px/1.3 system-ui,-apple-system,\\'Segoe UI\\',Roboto,sans-serif;" +
    "box-shadow:0 4px 16px rgba(14,17,20,.24);pointer-events:none;opacity:0;transition:opacity .15s';document.body.appendChild(box);return box}" +
    "document.addEventListener('DOMContentLoaded',ensure);" +
    "function note(){var b=ensure();if(!b)return;b.textContent='Not saved in the preview';b.style.opacity='1';clearTimeout(timer);" +
    "timer=setTimeout(function(){b.style.opacity='0';b.textContent=''},2600)}" +
    "document.addEventListener('htmx:beforeRequest',function(e){var c=e.detail&&e.detail.requestConfig;var verb=String((c&&c.verb)||'get').toLowerCase();" +
    "if(verb==='get')return;e.preventDefault();if(Date.now()-last<4000)note()})})();</script>"
  );
}

function notFoundPage() {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Not in the preview · SM Bean</title>
</head>
<body style="margin:0;padding-top:${BAR_HEIGHT}px;background:#F6F7F9;color:#0E1114;font:16px/1.5 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif">
${previewBar()}
<main style="max-width:560px;margin:0 auto;padding:64px 16px">
<h1 style="font-size:24px;line-height:32px;margin:0 0 8px">This page is not in the preview</h1>
<p style="margin:0 0 24px;color:#4A515C">The preview holds the main screens with demo data. Sending a form, saving a change or opening a page it did not include ends here.</p>
<p style="margin:0"><a href="/" style="color:#0D4534;font-weight:600">Go to the public home page</a></p>
</main>
</body>
</html>
`;
}

function titleOf(body) {
  const m = body.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  return m ? decodeEntities(m[1].replace(/\s+/g, ' ').trim()) : '';
}

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(full) : [full];
  });
}

// ---------------------------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------------------------

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const { chromium, request } = loadPlaywright(args.appDir);
  const origin = new URL(args.baseUrl).origin;
  prepareOut(args.out);

  const api = await request.newContext({ baseURL: origin });
  const ping = await api.get('/__e2e__/ping');
  if (!ping.ok()) throw new Error(`${origin} is not an e2e server (/__e2e__/ping answered ${ping.status()}).`);
  const { ids } = await ping.json();
  const workspace = ids.workspace_a;
  const owner = await fixture(api, 'session', { role: 'owner' });

  const browser = await chromium.launch();
  const appContext = await browser.newContext({ baseURL: origin });
  await appContext.addCookies([{ name: owner.cookie.name, value: owner.cookie.value, url: origin }]);
  const publicContext = await browser.newContext({ baseURL: origin });
  const cookieValues = [owner.cookie.value];
  try {
    if (args.demoData) await prepareDemoData(api, appContext, ids, owner.user.email);

    const crawl = new Crawl({ origin, maxPages: args.maxPages, maxFragments: args.maxFragments });

    // Signed out first: the public pages own their paths.
    const publicSeeds = ['/', '/how-it-works/', '/request-invite/', '/accounts/login/'];
    const pub = await crawl.crawlPages(publicContext.request, 'public', publicSeeds);
    await crawl.crawlFragments(publicContext.request, 'public', pub.fragmentQueue, pub.soft, new Set());
    log(`public: ${crawl.pages.size} pages`);

    const W = `/workspace/${workspace}`;
    const appSeeds = [
      '/',
      `${W}/studio/`,
      `${W}/approvals/`,
      `${W}/calendar/`,
      ...['month', 'week', 'day'].map((view) => `${W}/calendar/?mode=calendar&view=${view}`),
      ...['queue', 'drafts', 'approvals', 'sent'].map((tab) => `${W}/calendar/?mode=list&tab=${tab}`),
      `${W}/inbox/`,
      `${W}/analytics/`,
      `${W}/studio/activity/`,
      `${W}/settings/`,
      ...['brand', 'accounts', 'team', 'approvals', 'autopilot', 'notifications', 'advanced'].map((tab) => `${W}/settings/?tab=${tab}`),
      `${W}/studio/setup/`,
      `${W}/compose/`,
      `${W}/create/`,
      `${W}/drafts/`,
      `${W}/media/`,
      `${W}/calendar/posting-slots/`,
      '/members/',
      '/accounts/settings/',
      '/accounts/settings/?tab=preferences',
      '/notifications/',
    ];
    const app = await crawl.crawlPages(appContext.request, 'app', appSeeds);
    const morePages = new Set();
    await crawl.crawlFragments(appContext.request, 'app', app.fragmentQueue, app.soft, morePages);
    if (morePages.size) {
      const extra = await crawl.crawlPages(appContext.request, 'app', [...morePages]);
      await crawl.crawlFragments(appContext.request, 'app', extra.fragmentQueue, extra.soft, new Set());
    }
    const csrf = (await appContext.cookies()).find((cookie) => cookie.name === 'csrftoken');
    if (csrf) cookieValues.push(csrf.value);
    log(`all: ${crawl.pages.size} pages, ${crawl.fragments.size} fragments, ${crawl.skipped.size} skipped`);

    const paths = assignPaths(crawl);
    const rewriter = new Rewriter(crawl, paths);
    const written = [];
    for (const [key, page] of crawl.pages) {
      const local = paths.pageLocal.get(key);
      if (!local) continue;
      const html = scrubText(rewriter.rewrite(page.body, key, page.world, true), origin);
      writeFile(args.out, `${local}index.html`, html);
      written.push({ path: local, title: titleOf(html), signed_in: page.world === 'app', source: key.replace(UUID, ':id') });
    }
    for (const [key, fragment] of crawl.fragments) {
      const local = paths.fragmentLocal.get(key);
      if (!local) continue;
      writeFile(args.out, `${local}index.html`, scrubText(rewriter.rewrite(fragment.body, key, fragment.world, false), origin));
    }

    // The pictures the pages show; /media/ files only as the media review allows (see MEDIA_REVIEW_PY).
    const fetched = new Map();
    for (const asset of crawl.assets) {
      const { pathname } = new URL(asset, origin);
      if (fetched.has(pathname) || crawl.pages.has(pathname)) continue;
      const response = await appContext.request.get(origin + asset, { maxRedirects: 0, failOnStatusCode: false });
      const type = response.headers()['content-type'] ?? '';
      if (response.status() !== 200 || type.includes('text/html')) continue;
      const bytes = await response.body();
      if (bytes.length > 10 * 1024 * 1024) continue;
      fetched.set(pathname, bytes);
    }
    const review = reviewMedia(args, [...fetched.keys()].filter((p) => p.startsWith('/media/')));
    const media = { saved: 0, redrawn: 0, withheld: [] };
    try {
      for (const [pathname, original] of fetched) {
        let bytes = original;
        const verdict = review.verdicts[pathname];
        if (verdict?.action === 'withhold' || (!verdict && review.profiles_with_phone.some((id) => pathname.startsWith(`/workspace/${id}/`)))) {
          media.withheld.push(pathname.replace(UUID, ':id'));
          continue;
        }
        if (verdict?.action === 'replace') {
          bytes = fs.readFileSync(verdict.file);
          media.redrawn++;
        }
        try {
          writeFile(args.out, pathname, bytes);
        } catch (error) {
          log(`not saved: ${pathname} (${error.code ?? error.message})`);
          continue;
        }
        media.saved++;
      }
    } finally {
      review.cleanup();
    }
    log(`media: ${media.saved} saved, ${media.redrawn} team graphics drawn again from scrubbed words, ${media.withheld.length} withheld`);

    // The bell asks /notifications/unread-count/ (JSON) every minute: answer with the count the pages show.
    const badges = new Set();
    for (const page of crawl.pages.values()) for (const m of page.body.matchAll(/notificationBadge\((\d+)\)/g)) badges.add(Number(m[1]));
    const unread = await appContext.request.get(`${origin}/notifications/unread-count/`, { maxRedirects: 0, failOnStatusCode: false });
    let unreadCount = unread.ok() ? Number((await unread.json()).count) : null;
    if (badges.size === 1) unreadCount = [...badges][0];
    else if (badges.size > 1) log(`the bell shows ${[...badges].join(', ')} across pages; the count answers ${unreadCount}`);
    if (Number.isInteger(unreadCount)) writeFile(args.out, '/notifications/unread-count/index.html', `${JSON.stringify({ count: unreadCount })}\n`);

    collectStatic(args, args.out);
    writeFile(
      args.out,
      '/_headers',
      '/*\n  X-Robots-Tag: noindex, nofollow\n/notifications/unread-count/\n  Content-Type: application/json; charset=utf-8\n',
    );
    writeFile(args.out, '/robots.txt', 'User-agent: *\nDisallow: /\n');
    writeFile(args.out, '/netlify.toml', '# A static preview: nothing to build.\n[build]\n  publish = "."\n');
    writeFile(args.out, '/404.html', notFoundPage());
    written.sort((a, b) => a.path.localeCompare(b.path));
    const manifest = {
      source_sha: args.sha,
      built_at: new Date().toISOString(),
      note: 'A read-only preview with demo data from the e2e harness. Nothing you do here is saved.',
      workspace: ids.workspace_names?.a ?? null,
      counts: { pages: written.length, fragments: paths.fragmentLocal.size, media: media.saved, media_withheld: media.withheld.length },
      pages: written,
    };
    writeFile(args.out, '/preview.json', `${JSON.stringify(manifest, null, 2)}\n`);

    // Nothing session-like, secret, local or personal may leave this machine. Collected static files
    // are third-party code: an address or a number-like string there is not data.
    const leaks = [];
    for (const file of walk(args.out)) {
      const isText = /\.(html|json|txt|toml|js|css|map|svg|webmanifest)$/.test(file) || file.endsWith('_headers');
      const isStatic = file.includes(`${path.sep}static${path.sep}`);
      // A picture's bytes are read only for text written into it (metadata); a picture's pixels are the media review's.
      const text = fs.readFileSync(file, isText ? 'utf8' : 'latin1');
      const found = isText
        ? findLeaks(text, cookieValues, { strict: !isStatic }).filter((hit) => !(isStatic && hit.includes('@')))
        : [...text.matchAll(REAL_PHONE)].map(() => 'a real phone number in the file');
      for (const hit of found) leaks.push(`${path.relative(args.out, file)}: ${hit}`);
    }
    if (leaks.length) {
      console.error(leaks.slice(0, 50).join('\n'));
      throw new Error(`${leaks.length} secret-looking strings are still in the output.`);
    }

    const bytes = walk(args.out).reduce((sum, file) => sum + fs.statSync(file).size, 0);
    log(`wrote ${written.length} pages, ${paths.fragmentLocal.size} fragments and ${media.saved} media files to ${args.out}`);
    if (media.withheld.length) log('withheld pictures:', media.withheld.join(', '));
    log(`total ${(bytes / 1024 / 1024).toFixed(1)} MB`);
    const reasons = {};
    for (const reason of crawl.skipped.values()) reasons[reason] = (reasons[reason] ?? 0) + 1;
    log('skipped:', JSON.stringify(reasons));
  } finally {
    await browser.close();
    await api.dispose();
  }
}

main().catch((error) => {
  console.error(`[preview] ${error.stack || error}`);
  process.exit(1);
});
