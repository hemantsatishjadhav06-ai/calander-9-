# End-to-end tests

Playwright specs (TypeScript) that drive a real browser through the product, and the server they run
against (`tests/e2e/server/`, Python). Spec: [`docs/specs/01-harness.md`](../../docs/specs/01-harness.md).

```
tests/e2e/
  server/      python -m tests.e2e.server: web app + worker in one process, fakes, mocks, seed, fixtures
  support/     test.ts (test, expect and the fixtures below), harness.ts, axe.ts, network.ts
  self/        the harness's own checks (axe helper, network guard, session fixture)
  golden/      the golden paths, one file each (NN-name.spec.ts)
  __screenshots__/   toHaveScreenshot baselines (none yet; Phase 3 takes them per screen)
```

## Running

Needs PostgreSQL 16 on `localhost:5432` (`postgres`/`postgres`), the `.venv`, Node 22 and the built CSS
(`theme/static/css/dist/styles.css` is not committed):

```bash
(cd theme/static_src && npm ci && npm run build)
npm ci --ignore-scripts
npx playwright install chromium webkit         # here: export PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
npm run test:e2e                               # starts the server (--reset) and runs every project
npx playwright test tests/e2e/self --project=pixel-7
```

`playwright.config.ts` starts `python -m tests.e2e.server --reset --port $E2E_PORT` (the `.venv`
Python, or `E2E_PYTHON`) and waits for `/health/`. Outside CI it reuses a server already listening on
that port, so you can keep one running in another terminal:

```bash
.venv/bin/python -m tests.e2e.server --reset            # drop, migrate and seed brightbean_e2e, then serve :8150
.venv/bin/python -m tests.e2e.server --port 8160        # serve the existing database
.venv/bin/python -m tests.e2e.server --reset --no-worker --static manifest   # for Lighthouse
```

Environment: `E2E_PORT` (default 8150) and `DB_NAME` (default `brightbean_e2e`). The server refuses
any settings module but `config.settings.e2e` and any database whose name does not end in `_e2e`,
before it runs a statement. Two runs at once need their own port and database
(`E2E_PORT=8162 DB_NAME=brightbean_g2_e2e`). No `.env` or `dev.env` is needed.

**iPhone 13.** CI runs the `iphone-13` project on WebKit. WebKit cannot be downloaded in the agents'
sandbox (the Playwright CDN is refused), so a local run uses Chromium with the iPhone 13 viewport,
scale and touch, and prints one line saying so.

## What the server does

One process, because the fakes are module attributes shared by the request threads and the worker:

- **Fakes** (`fakes.py`): the creative team is the suite's `FakeTeam`; the account manager reads the
  request and answers `ChatAnswer` (new post with the channels and the key message named, routine,
  change, plain answer); every other agent turn gets a schema-valid answer; the model clients, web
  research and the source fetcher refuse. The real queue and worker run every stage.
- **Mocks** (`mocks.py`): every `httpx` client goes through a `MockTransport` that answers the X token
  exchange and `/2/users/me`, and a Facebook comment reply; everything else is refused and recorded.
  Google sign-in is answered by the authorization `code` (`mocks.register_google_profile`).
- **Socket guard** (`netguard.py`): loopback to the database and the server only; every other
  connection and name lookup is refused and recorded.
- **Worker** (`worker.py`): `run_worker`'s loop in a thread, without the platform polls (inbox sync,
  analytics sync, health checks), which could only reach the mock's refusal.
- **Seed** (`seed.py`): workspace A `00000000-0000-4000-8000-00000000000a` ("Neopolis", Asia/Kolkata,
  internal approval in the dashboard) with `owner@`, `manager@`, `editor@` and `client@e2e.test`,
  connected LinkedIn company, Instagram and Facebook accounts, brand profile, verified facts, agency
  settings (owner as lead, autopilot off, the brief shown first) and a library image; workspace B
  `…0b` ("Bayside Holdings") in its own organisation with `owner-b@e2e.test`.

## Fixtures and probes

A test never runs code on the server. It calls named, typed steps:

| HTTP | Answer |
|---|---|
| `GET /__e2e__/ping` | `{"ok": true, "ids": {...}}` (the seed's ids; 503 before `--reset`) |
| `POST /__e2e__/fixture/<name>` with a JSON object | the fixture's JSON; creates fresh rows for one test |
| `GET /__e2e__/probe/<name>?k=v` | the probe's JSON; reads the rows a test asserts on |

Unknown name: 404. Bad payload: 400 `{"error": ...}`. Not loopback: 403. Any settings module but
`config.settings.e2e`: 404, and `config/urls.py` never mounts them (only `tests/e2e/server/urls.py`).

A step is `(payload: dict[str, Any]) -> dict[str, Any]`, registered with `@fixture(name)` or
`@probe(name)` from `tests/e2e/server/registry.py`, in a module under `tests/e2e/server/steps/`. Every
module there is imported automatically, so a group adds `steps/<area>.py` and touches no shared list.
Raise `registry.PayloadError` for a bad payload. Fixtures run in a transaction. Built-ins
(`steps/core.py`): fixtures `session` (`{"role"}` or `{"email"}` → session cookie),
`reset_login_limits`, `set_agent_delay` (`{"seconds"}`), `magic_link` (`{"email", "workspace_id"}` →
`{"url"}`); probes `refused_network` (`?since=<epoch>`) and `worker`.

In a spec, import from `../support/test`:

```ts
import { expect, test } from '../support/test';

test('…', async ({ page, harness, as, axe, network }) => {
  await as('editor');                                    // or as({ email }); the session cookie, no form
  const brief = await harness.fixture<{ id: string }>('my_fixture', { title: 'x' });
  await page.goto(`/workspace/${harness.ids.workspace_a}/studio/`);
  await axe(page, 'Home (editor)');                      // every screen; axe(page, label, { include: '[role="dialog"]' }) for a dialog
  expect((await harness.probe<{ hosts: string[] }>('refused_network')).hosts).toEqual([]);
});
```

## Rules for specs

- **Selectors:** `data-testid` or `getByRole` with an accessible name. Never a CSS class, copy text or
  an Alpine attribute. A missing hook is added to the template next to the existing attributes:
  `data-testid="<area>-<thing>"`, kebab-case (`approvals-row-approve-schedule`, `home-thread-send`).
  Existing `data-*` hooks that pytest asserts stay exactly as they are.
- **Sign-in:** only golden path 1 posts the login form (10 posts a minute per address; call
  `reset_login_limits` first). Everything else signs in with `as(...)`.
- **Axe** on every screen a test reaches and on each dialog it opens; it fails on serious or critical
  violations with the rule, impact, element and help page. Fix the template, not the check.
- **Outcomes in the database:** assert through probes, not only on the page.
- **Network:** every browser request to another host is aborted (`network.blocked` lists them). A
  test that needs an outside page (an OAuth authorize URL) installs `page.route(...)` first, which
  takes precedence, and answers it with a redirect to the app's callback.
- **No retries, no `test.skip`/`test.fixme` to make a path green;** each test makes its own rows.
