# Phase 1 plan — the test harness

Spec: [`01-harness.md`](01-harness.md) requirements R1–R12. Plan: [`docs/BETA_PLAN.md`](../BETA_PLAN.md)
section 6, Phase 1, and section 7. Gate: CI green with all new jobs; 12 e2e tests pass on the old UI.

Every task that changes behaviour starts with a failing test (`test-driven-development`): write
it, run it, see it fail for the right reason, then make it pass. An e2e spec is the red test for the
`data-testid` hooks and fixtures it needs. Invariant tests are never edited; if a template change
breaks `test_a11y_sweep.py` or another invariant test, the template change is wrong.

## Task 0 — Documentation discovery (done)

Four read-only passes (harness, CI, flows, performance) read the code, the CI file, the prototype
harness and a verified Playwright/Lighthouse probe. Their reports, with file and line sources, are
kept outside the repository; the facts this plan relies on are below.

**Allowed APIs and patterns (copy these):**

| Need | Copy from |
|---|---|
| The faked creative team | `apps/studio/tests/conftest.py:215-276` `FakeTeam` (import it; `fake_team` at 279-289 also stubs `pipeline.enqueue` at 287: **do not** copy that line, the e2e worker must run the queue) |
| A fake account manager answering `ChatAnswer` | `apps/studio/tests/test_guided_chat.py:54-88` `GuidedManager`; the prototype's rule-based `SmartManager` (routine, revise, new post with channels and key message) |
| Source evidence fake | `apps/studio/tests/test_guided_chat.py:98-125` `source_collector` |
| The provider refusals pytest applies | `conftest.py:43-79` (model client, second provider's client, source fetcher) |
| Worker loop | `apps/common/management/commands/run_worker.py:44-52, 86-95`; `apps/common/background.py` `worker_process_lock` (161-197), `reclaim_stale_locks` (272-296), `ensure_recurring_tasks` (258-269), `worker_lease_checks` |
| Settings shape for a test-only module | `config/settings/test.py:3-4` (setdefault secret and salt), 36-64 (local-memory cache, local storage), 66-75 (database from `DB_NAME`) |
| Users that land on the seeded workspace | `apps/approvals/test_gate.py:30-62` (`_user`: delete the auto-created organisation; set `tos_accepted_at`); `apps/accounts/signals.py:139-146` creates "My Workspace" on every new user |
| Two workspaces and an outsider | `apps/common/management/commands/live_verify.py:578-647` (`_workflow_fixture`, isolation check 637-647) |
| Gate functions to assert against | `apps/approvals/gate.py:135` `fingerprint(pp)`, 398 `revalidate_post`, 429 `_approve_time`, 441 `_withdraw`; `apps/approvals/actor.py:57-64` `acting_as` |
| Google sign-in mocked on the server | `apps/accounts/tests/test_google_signin.py:47-61` `_google_returns` (patch `OAuth2Client.get_access_token` and `GoogleOAuth2Adapter.complete_login`), 64-81 (form action and `state`) |
| Provider HTTP mocked | `tests/providers/test_x.py:53-60` (`httpx.Client` given `transport=httpx.MockTransport(handler)`); entry point `providers/base.py:364-417` `_request`; X endpoints `providers/x.py:52-54` (`AUTH_URL`, `TOKEN_URL`, `API_BASE`), `exchange_code` 356, `get_profile` 413 (`/users/me`) |
| A comment arriving | `apps/inbox/tests/test_webhooks.py:44-45` `_sign_body` (HMAC-SHA256 of the body with the Facebook app secret), 209-243 (payload shape); handler `apps/inbox/webhooks.py:283-340` |
| Calendar drag | `templates/calendar/calendar.html:500-583` (`initCalendarDnD`, `rescheduleChip(platformPostId, newDatetime)`); endpoint `apps/calendar/views.py:1145-1235` `reschedule_post` |
| Playwright projects | the probe config: `{...devices['iPhone 13'], ...(process.env.CI ? {} : {browserName: 'chromium'})}`; Desktop Chrome and Pixel 7 as is |
| Axe | `new AxeBuilder({ page }).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']).analyze()` |
| Lighthouse budgets | assertion keys verified against the LHCI source: `categories:performance` minScore, `largest-contentful-paint`, `cumulative-layout-shift`, `total-blocking-time` maxNumericValue, `resource-summary:script:size` (reads `transferSize`) |
| CI Postgres | `.github/workflows/ci.yml:112-118` (the runner's own PostgreSQL 16) |

**Versions (pinned exactly):** `@playwright/test` 1.56.1 and `playwright-core` 1.56.1 (via
`overrides`, so `@axe-core/playwright` does not pull a second copy); `@axe-core/playwright` 4.13.0;
`lighthouse` 13.5.0. Audited together: 0 vulnerabilities. Python: `pip-audit` 2.10.1 in CI only;
`pip-tools` 7.6.2 in a throwaway virtualenv to regenerate the lock.

**Facts that shape the design:**

- Workspace URLs answer **403** to non-members (`apps/members/middleware.py:105-134`), not 404.
- Login posts are limited to 10 a minute per address (`apps/accounts/middleware.py:14-25`, not a
  setting): only path 1 posts the form; everything else signs in with a session fixture.
- `theme/static/css/dist/styles.css` is not committed: build it before any e2e or Lighthouse run.
- WebKit cannot be downloaded here (the Playwright CDN is refused by the network policy); Chromium
  1194 is in `/opt/pw-browsers`.
- The prototype's `seed.py` source is gone; the seed is written fresh from the description in the
  harness report.
- Home loads about 143 KB of gzipped JavaScript (Chart.js 70 KB and SortableJS 15 KB on every page,
  used on one page each); the 150 KB script budget is close.

**Anti-patterns:**

- An endpoint that runs code sent by the test (the prototype's `/__e2e__/eval`). Named, typed
  fixtures and probes only.
- Mounting anything under `/__e2e__/` from `config/urls.py`, or answering it from a non-loopback
  address or under any settings module but `config.settings.e2e`.
- Dropping a database whose name does not end in `_e2e`.
- Selectors by CSS class, copy text or Alpine attribute in `tests/e2e/` (`data-testid` or
  `getByRole` with an accessible name only).
- `test.skip`/`test.fixme` to make a failing path green. The only declared pending test is path 12,
  because the feature does not exist.
- Retries in CI to hide flakiness (`retries: 0`). A flaky test is quarantined the same day with an
  issue.
- Editing an existing pytest test that pins an invariant (for example the 403 tests).
- `@lhci/cli` (brings 13 high-severity advisories); a GitHub Action referenced by tag instead of SHA.

## Task 1 — Dependencies and audits (R10 audit part, R12)

Files: `requirements.txt`, `requirements.lock`, `config/settings/base.py` (`LOCALE_PATHS`),
`locale/.gitkeep`, `.github/workflows/ci.yml`.

1. Red: `pip-audit -r requirements.lock --disable-pip --require-hashes` reports 38 known
   vulnerabilities (Pillow 12.3.0, certifi 2026.7.22); `python manage.py compilemessages` raises
   `CommandError` (no `msgfmt`; then no locale directory).
2. Green: `Pillow>=13.0,<14.0`; regenerate the lock with the command in the lock's header plus
   `--upgrade-package pillow --upgrade-package certifi` (pip-tools 7.6.2, Python 3.12, throwaway
   virtualenv). Only Pillow 13.0.0 and certifi 2026.10.23 may change; anything else changing is a
   stop. Bring the local `.venv` to the lock. `LOCALE_PATHS = [BASE_DIR / "locale"]` and
   `locale/.gitkeep`.
3. CI: a **Dependency audit** job (setup-python 3.12; `pip install pip-audit==2.10.1`;
   `pip-audit -r requirements.lock --disable-pip --require-hashes --progress-spinner off`;
   setup-node 22; `npm audit --audit-level=high` in the root and in `theme/static_src`). In the
   **Test (pytest)** job, after the install: `sudo apt-get install -y --no-install-recommends
   gettext` and `python manage.py compilemessages --ignore=.venv --ignore=node_modules`.
4. Verify: pip-audit 0; both npm audits 0 high; the full pytest suite on the new lock (Pillow is
   imported in 32 files); `makemigrations --check`.

## Task 2 — The e2e server (R1–R4)

Files: `config/settings/e2e.py`; package `tests/e2e/server/` (`__init__.py`, `__main__.py`,
`guard.py`, `netguard.py`, `fakes.py`, `mocks.py`, `worker.py`, `seed.py`, `registry.py`,
`views.py`, `urls.py`, `steps/__init__.py`); `tests/e2e/__init__.py`; pytest tests in
`tests/test_e2e_server.py`.

1. Red (pytest, `config.settings.test`): the `/__e2e__/` paths 404 under the test settings;
   `guard.assert_e2e_database("brightbean_test")` raises and `"brightbean_e2e"` passes;
   `guard.assert_e2e_settings()` raises under the test settings; the views refuse a non-loopback
   `REMOTE_ADDR` (403) when the e2e URL conf is used; `netguard` refuses a connection to a
   non-loopback address and records it; `seed.run()` builds the world (below) with the fixed
   workspace UUIDs, users that land on workspace A, and no "My Workspace"; a registered fixture and
   probe are callable by name and an unknown name is a 404; no module in `tests/e2e/server/` calls
   `exec` or `eval`.
2. Green:
   - `config/settings/e2e.py`: set the environment the base settings read (placeholder provider,
     Google client id and secret, X client id and secret, Facebook app secret, `SIGNUP_MODE=open`)
     **before** `from .base import *`; then `DEBUG=False`, `ALLOWED_HOSTS` loopback,
     `CSP_REPORT_ONLY=False`, rate limits on, local storage under a gitignored `e2e_media/`,
     local-memory cache and mail, MD5 hasher, the database from `DB_NAME` (default
     `brightbean_e2e`), `ROOT_URLCONF = "tests.e2e.server.urls"` (includes `config.urls` and the
     harness views), `PUBLISHER_HEARTBEAT_MAX_AGE = 30`, `APP_URL` from `E2E_BASE_URL`; with
     `E2E_STATIC=manifest`, the compressed manifest static storage and `STATIC_ROOT` for Lighthouse.
   - `__main__.py`: `python -m tests.e2e.server [--reset] [--port N] [--no-worker] [--static manifest]`;
     guards, then `--reset` drops and creates the database (guarded), `migrate`, installs fakes,
     mocks and the net guard, seeds, starts the worker thread, then `runserver` on
     `127.0.0.1:PORT` without the reloader (`--nostatic` when the manifest storage is on).
   - `fakes.py`: `FakeTeam` onto `apps.studio.agents` and `apps.studio.roles.creative`; the account
     manager fake; the generic schema-valid `run_agent`; `llm.research` refused; the source
     collector fake; model and second-provider clients refused; a per-turn delay (default 0).
   - `mocks.py`: `httpx.Client` given a `MockTransport` that answers X token and `/users/me`, the
     Facebook comment reply, and refuses everything else (recorded); the Google patch keyed by the
     authorization `code`.
   - `seed.py`: organisation "E2E Agency" (Asia/Kolkata); workspace A
     `00000000-0000-4000-8000-00000000000a` ("Neopolis", `required_internal`, dashboard approval
     required); workspace B `…0b` in another organisation with its own owner; users
     `owner@e2e.test`, `manager@e2e.test`, `editor@e2e.test` (staff who cannot approve) and
     `client@e2e.test` (portal); connected LinkedIn company, Instagram and Facebook accounts on A;
     brand profile, verified facts, agency settings (owner lead, autopilot off, confirm mode); one
     library image. Returns the ids.
   - `registry.py`: `@fixture(name)` and `@probe(name)` decorators; `steps/__init__.py` imports every
     module in `steps/` (so groups add files without touching a shared list). Built-in: fixture
     `session` (role or email → session cookie, created server-side), `reset_login_limits`,
     `set_agent_delay`, `magic_link`; probe `refused_network`.
   - `views.py`/`urls.py`: `GET /__e2e__/ping`, `POST /__e2e__/fixture/<name>`,
     `GET /__e2e__/probe/<name>`; JSON in and out; loopback only; CSRF-exempt.
3. Verify: the pytest tests above; `ruff`, `ruff format`, `mypy` on `tests/`; the server starts with
   `--reset` and `/health/` and `/__e2e__/ping` answer.

## Task 3 — Playwright and the axe helper (R5, R7)

Files: `package.json`, `package-lock.json`, `playwright.config.ts` (repository root),
`tests/e2e/support/{harness.ts,test.ts,axe.ts,network.ts}`, `tests/e2e/self/*.spec.ts`,
`tests/e2e/__screenshots__/.gitkeep`, `.gitignore` (`test-results/`, `playwright-report/`,
`.lighthouseci/`, `e2e_media/`).

1. Red: `tests/e2e/self/axe.spec.ts` (a page with an unlabelled input fails the helper; a clean page
   passes); `tests/e2e/self/network.spec.ts` (a request to an outside host is aborted; the harness
   ping answers); `tests/e2e/self/session.spec.ts` (a session fixture opens Home of workspace A for
   the owner on all three projects).
2. Green: exact devDependencies and `overrides`; script `test:e2e` (`playwright test`);
   the config (`testDir: tests/e2e`, one worker, `retries: 0`, `webServer` running
   `.venv/bin/python -m tests.e2e.server --reset --port $E2E_PORT` and waiting for `/health/`,
   `reuseExistingServer` outside CI, `baseURL`, `trace: 'retain-on-failure'`, screenshot folder and
   0.1 % threshold, the three projects, `timezoneId: 'Asia/Kolkata'`); `test.ts` extends `test` with
   `harness` (fixture/probe calls), `as(role)` (adds the session cookie) and `axe(page, label)`;
   `network.ts` aborts every request whose host is not the server, except the routes a test installs
   for the OAuth authorize URLs.
3. Verify: the three self specs pass on all three projects; locally the iPhone 13 project prints that
   it ran on Chromium.

## Task 4 — Golden paths (R6, R8), five groups

Each group: write the spec files first and run them (red: a missing `data-testid`, fixture or probe);
add the `data-testid` hooks to the templates (additive; keep every existing attribute); add the
group's fixtures and probes in `tests/e2e/server/steps/<group>.py`; run until green on all three
projects; run the pytest tests of every app whose templates changed; `axe` on every screen reached;
fix any serious or critical axe finding in the template with the axe check as its red test. Each
group runs its own server: `E2E_PORT` and `DB_NAME` unique to the group (`brightbean_g<N>_e2e`).

Template ownership, so groups do not edit the same file: G1 login, social buttons, accept terms,
`base.html` sign-out; G2 `studio/index.html` and the thread partials, `studio/setup.html`,
`studio/brand_profile.html` (including the colour inputs and sample image G5 uses),
`social_accounts/connect.html`; G3 `composer/*`, `approvals/partials/_approval_row.html` (all its
buttons, including *Request changes* and *Send back for changes*, which G4 uses), `calendar/*`;
G4 `studio/detail.html`, `client_portal/*`; G5 `inbox/*`, `organizations/settings.html`.

- **G1 — paths 1 and 11** (`01-sign-in.spec.ts`, `11-isolation.spec.ts`). Path 1: wrong password,
  owner and editor sign-in (the form; call `reset_login_limits` first), Google new and existing user
  (route `https://accounts.google.com/**` to a 302 to the callback with the request's `state`).
  Path 11: as owner, editor and client of A, every workspace-B page and action URL answers 403 or
  404 and the body never contains B's name; B's object ids under A's URLs answer 404.
- **G2 — paths 3 and 2** (`03-ask-the-team.spec.ts`, `02-onboarding.spec.ts`). Path 3: Home →
  message → brief card (channels, key message) → *Go ahead* → worker → *Waiting for you*; DB states;
  editor sees no approve control; client refused. Path 2: brand page save → connect X (route the
  authorize URL to the callback; the mock answers token and profile) → Set up *Use me as lead* →
  Home idea → *Go ahead* → brief queued or working.
- **G3 — paths 4, 5 and 7** (`04-compose.spec.ts`, `05-approve-and-schedule.spec.ts`,
  `07-calendar-drag.spec.ts`). Path 7 drives the real drag on Desktop Chrome and calls
  `rescheduleChip` on the touch projects, saying so in the test title.
- **G4 — paths 6 and 8** (`06-request-changes.spec.ts`, `08-client-portal.spec.ts`), each with a
  two-stage workspace created by a fixture.
- **G5 — paths 9, 10 and 12** (`09-inbox.spec.ts`, `10-brand-and-timezone.spec.ts`,
  `12-two-factor.spec.ts`). Path 9 posts the signed webhook from the test. Path 10 uses a fixture
  workspace with a blank timezone in its own organisation. Path 12 is `test.fixme` with the steps
  written out and the reason "TOTP 2FA ships in Phase 4".

Verify per group: `npx playwright test tests/e2e/golden/<files>` green on three projects; the
probe `refused_network` lists no platform, model or Telegram host; `grep` finds no class, text or
Alpine selector in the group's specs.

## Task 5 — Lighthouse (R9)

Files: `.lighthouserc.json`, `tests/lighthouse/run.mjs`, possibly `templates/base.html` and the
analytics and calendar templates (only if a budget forces it).

1. Red: the runner against the e2e server started with `--static manifest --no-worker` reports each
   URL's median performance, LCP, CLS, TBT and script bytes against the budgets.
2. Green: if a budget fails, first the fixes that change nothing a person sees (Chart.js only where
   the analytics chart is, SortableJS only on the calendar; each move checked with the paths that
   use them and the pages' pytest tests). A budget still failing is set to `warn` for that URL only,
   with the reason in the CHANGELOG.
3. Verify: three runs, median; the printed table; reports written under `.lighthouseci/`
   (gitignored).

## Task 6 — CI jobs (R10, R11)

Files: `.github/workflows/ci.yml`.

- **E2E (Playwright)**: the PostgreSQL step; Python and the lock; Node 22 and `npm ci
  --ignore-scripts`; the CSS build; `npx playwright install --with-deps chromium webkit`;
  `CI=1 npm run test:e2e`.
- **Lighthouse CI**: the PostgreSQL step; Python, Node, CSS build; start the server with
  `--reset --no-worker --static manifest` in the background; wait for `/health/`;
  `node tests/lighthouse/run.mjs`.
- Pinned actions only (the SHAs already in the file). Timeouts: e2e 20 min, Lighthouse 15 min.
- R11: the CHANGELOG lists every job name for the owner's ruleset, with the steps from the CI report.

## Task 7 — P1 items

- CSP header test in `apps/common/tests/` (enforced CSP; `script-src` without `'unsafe-inline'`).
- The client variant of path 6 and the manager variant of path 5.

## Task 8 — Docs

`CLAUDE.md` (*Run and test*: the e2e and Lighthouse commands; the module map: `tests/e2e/`),
`CONTRIBUTING.md` (how to run the e2e suite), `docs/specs/CHANGELOG.md` (the Phase 0 release and the
Phase 1 entry with the gate).

## Task 9 — Verification and the gate

- `ruff check .`, `ruff format --check .`, `mypy apps/ config/ providers/ tests/ --ignore-missing-imports`,
  `makemigrations --check --dry-run`, `npm run test:ui`, `tools/recolor.py --check`.
- The full pytest suite (section 7 rule).
- `npm run test:e2e` three times in a row on all three projects: no failure in any run.
- The Lighthouse runner; `pip-audit`; both `npm audit`s; `compilemessages` (in CI if `gettext`
  cannot be installed here).
- Grep guards: no `/__e2e__` in `config/`; no `exec(`/`eval(` in `tests/e2e/server/`; no class, text
  or Alpine selectors in `tests/e2e/golden/`; `test.fixme` only in `12-two-factor.spec.ts`.
- `engineering:code-review` and `requesting-code-review` on the diff; `verification-before-completion`.
- Push, open the pull request, drive CI green; run the gate exactly as written and paste the results
  into the CHANGELOG.
