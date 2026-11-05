# End-to-end tests

Playwright specs (TypeScript) that drive a real browser through the product, and the server they run
against (`tests/e2e/server/`, Python). Spec: [`docs/specs/01-harness.md`](../../docs/specs/01-harness.md).

```
tests/e2e/
  server/      python -m tests.e2e.server: web app + worker in one process, fakes, mocks, seed, fixtures
  support/     test.ts (test, expect and the fixtures below), harness.ts, axe.ts, network.ts,
               poll.ts (until: read a probe until the worker is done), settled.ts (wait for a swap or a
               fade to finish), nav.ts (move through the navigation the way each device shows it),
               type.ts (expectReadSize: the computed size of named running text, which each rebuilt
               screen's spec checks), visual.ts (snap: a screen against its baseline; the frozen
               clock and the visual workspace), schemes.ts (forSchemes: a case in light and in dark),
               global-setup.ts (the end-of-run network check)
  self/        the harness's own checks (axe helper, network guard, session fixture, phone bar overlap)
               and Phase 3's foundations: theme.spec.ts (Appearance and the head script),
               foundations.spec.ts (the type floor and the body size on each device) and
               visual-harness.spec.ts (what the baselines rest on: no local writes, a still picture)
  golden/      the golden paths, one file each (NN-name.spec.ts)
  screens/     the screens Phase 2 added or moved, one file each (navigation, approvals, settings,
               activity, switches, marketing); docs/specs/02-cut-and-merge.md D10
  pairs/       Phase 3's before/after pairs and the light diff (playwright.pairs.config.ts; not in the suite)
  visual/      Phase 3's visual specs, compared with their baselines in CI only (Visual baselines, below)
  __screenshots__/   the baselines, <spec path>/<name>-<scheme>-<project>.png, written only by the
               baseline workflow and committed in `visual:` commits
```

## Running

Needs PostgreSQL 16 on `localhost:5432` (`postgres`/`postgres`), the `.venv`, Node 22 and the built CSS
(`theme/static/css/dist/styles.css` is not committed):

```bash
(cd theme/static_src && npm ci && npm run build)
npm ci --ignore-scripts
npx playwright install --with-deps chromium webkit
npm run test:e2e                               # starts the server (--reset) and runs every project
CI=1 npm run test:e2e                          # also use this locally to exercise actual WebKit
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
any settings module but `config.settings.e2e`, any database whose name does not end in `_e2e`, any
`DB_HOST` that is not this machine (loopback or a local socket), and any libpq variable that would
send the connection elsewhere whatever `DB_HOST` says (`PGHOSTADDR`, `PGSERVICE`, or a `PGHOST` off
this machine while `DB_HOST` is empty), before it runs a statement. Two runs at once need their own port and database
(`E2E_PORT=8162 DB_NAME=brightbean_g2_e2e`). No `.env` or `dev.env` is needed.

**iPhone 13.** `CI=1` runs the `iphone-13` project on WebKit; install both browsers and their system
libraries (`npx playwright install --with-deps chromium webkit`) before a gate run. The default
non-CI configuration retains the original Chromium fallback with the iPhone viewport, scale and
touch, and prints that limitation. It is useful for development where WebKit is unavailable but
does not establish WebKit coverage. `CI=1` also refuses to reuse an existing server: use a separate
`E2E_PORT` and `DB_NAME` if another run is active.

**Screens (Phase 2).** `screens/` runs on all three projects like the golden paths. `navigation`:
the six places and the Settings gear reach their screens (the sidebar on desktop, the phone bar and
More's drawer on a phone), there is no *More* disclosure, the bell and Go to work from the keyboard.
`approvals`: Approve & schedule from `/approvals/` goes through the same gate (the fingerprint and
one dashboard action in the database); a viewer reads only; a plain client is refused. `settings`:
the Brand tab saves the brand colour through the brand page's handler, each role sees only its tabs,
the old settings pages answer 301 to their tab. `activity`: the live board and the three presets
for an editor, no routines for a viewer, `/studio/team/` and `/studio/routines/` answer 301.
`switches`: the Blog place and the five extra providers come and go with their switches, the pages
still answer. `marketing`: Home, How it works and Request invite for someone signed out, and one
notification per operator for a sent request. Their fixtures and probe are in
`server/steps/screens.py` (`workspace_member`, `workspace_switches`, `unread_notification`,
`invite_operator`; `invite_requests`), pinned by `tests/test_e2e_steps_screens.py`. A spec that turns
a switch makes its own workspace: `workspace_switches` refuses the seeded A and B, which every spec
shares. The existing golden specs were not edited for Phase 2; every route they use still answers.

**Screens (Phase 3).** `screens/new-post.spec.ts` drives the New post sheet on Home and Calendar on
all three projects: one tap opens it, Ask the team lands on the idea's thread, an over-budget Send
shows the sheet's own sentence and makes nothing, a viewer and a plain client get no button (and the
client's direct POST answers 403), Write it myself opens the editor (from a week cell on desktop only,
with the cell's date and time), Save it as an idea saves with or without tags as the templates
switch says, the foot links reach their pages, and axe runs closed and open in each mode in both
schemes. Its fixture and probe are in `server/steps/p3.py`: `workspace_over_budget` spends this
month's allowance of a workspace the test made (it refuses A and B), and `new_post_outcome`
(`?workspace_id&since=`) reads the conversations, messages by kind, chat jobs, briefs, ideas and tags
made since a moment; both are pinned by `tests/test_e2e_steps_p3.py`. `self/phone-bar-overlap` holds
the floating New post button's place and `self/reduced-motion` the sheet's still entrance.
`screens/dark-shell.spec.ts` (dark, three projects) looks at Home and Calendar declared dark-ready:
axe, the dark canvas and the selection bars on the inverse surface. `self/shortcuts.spec.ts`
(desktop-chrome only, said in its skip: phones have no keys) runs `n`, `/`, `?`, the list and its
switch; `self/sheet-late-frames.spec.ts` holds every animation frame back until after the timers
already due, as WebKit orders them, and the sheet must still put the focus in each mode's first field;
`self/emoji-picker` and `self/phone-menu-focus` reach the idea form through the sheet.

**Screen 1's hooks.** The button: `new-post-open` (Home and Calendar, for whoever may start posts;
`aria-controls="new-post-sheet"`, `aria-expanded` kept current). The sheet: `new-post-sheet` (the
dialog), `new-post-close`, `new-post-mode-team`, `new-post-mode-self` (`aria-pressed`); Ask the team's
`new-post-team` (the form), `new-post-team-idea`, `new-post-team-channels`, `new-post-team-send`,
`new-post-team-error` (`role="alert"`, empty until a refusal) and `new-post-save-idea`; Write it
myself's `new-post-self-open`; the foot links `new-post-link-ideas`, `-drafts`, `-csv`, and
`-templates` and `-categories` with the `templates` switch. The idea form keeps every `idea-*` id
(`idea-title`, `idea-save`, `idea-close`, `idea-emoji-toggle|search|option` …). The sheet's sticky
parts carry `data-sheet-head` and `data-sheet-foot` (and its grabber `data-sheet-grabber`): its script
reads them to keep a focused control clear of both, and a spec may too. The shortcut list:
`shortcuts-dialog`, `shortcuts-close`, `shortcuts-toggle` (the switch), and its rows
`shortcuts-new-post`, `shortcuts-go-to`, `shortcuts-list`. Open the sheet as a person does: a click
on `new-post-open`, or on desktop a Calendar cell's "+" (`calendar-week-cell-<date>-<HHMM>`, hovered:
it sends `new-post:open` with the cell's date and time); only a spec of the route itself dispatches
`new-post:open` by hand (`self/phone-menu-focus`). Wait for the mode's first field to be focused before
typing: the sheet places the focus once the panel shows, a frame or two late on WebKit. **Retired with the New menu (T19):** `sidebar-new-toggle`, `sidebar-new-idea`,
`sidebar-new-ideas`, `sidebar-new-csv`, `sidebar-new-templates` and `sidebar-new-categories`; no
template contains `sidebar-new-` (`apps/common/tests/test_navigation_render.py` fails if one does), and
no golden spec used them.

Phase 1 also checks the manager's approval and the client's request for changes in
`golden/05-06-role-variants.spec.ts`, and foreign IDs in form bodies and query strings in
`golden/11-isolation-inputs.spec.ts`. The existing invariant golden paths are retained unchanged.
Golden path 12 is the single declared pending scenario until Phase 4 (one pending case per device).

**Mock document navigation.** The page fixture waits for the document commit of a local,
explicitly fulfilled HTML POST navigation before a later `page.goto`. WebKit can expose the
response headers before that commit; immediately navigating to a mock OAuth callback otherwise
races the unfinished form navigation. This boundary has a 10-second deadline and propagates
failures. It never retries a navigation and does not change real requests, GETs, XHRs, subframes,
or the external-network guard. A future test that intentionally cancels such a mock navigation
can opt out with `test.use({ mockedNavigationBarrier: false })`. The helper's deterministic
contract tests run in `npm run test:ui`; `self/mock-navigation.spec.ts` verifies ordering and
ordinary failed navigation in each browser. The invariant onboarding golden path stays unchanged.

No browser case is quarantined. The five scenarios that were quarantined while their repairs
were verified run in every suite again: the emoji picker ([issue #18](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/18)),
WebKit onboarding ([issue #19](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/19)),
the owner/editor draft handoff on all three devices ([issue #20](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/20)),
Calendar filter accessibility ([issue #21](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/21))
and Pixel 7 keyboard scroll completion ([issue #22](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/22)).
`docs/specs/CHANGELOG.md` records the consecutive complete runs that cleared them. The original
golden-path assertions are unchanged. Golden path 12 (TOTP) stays declared pending until Phase 4
and is never counted as passing.

Keyboard scrolling uses `support/scroll.ts`: install a bounded native `scrollend` listener,
send one key, then await completion before scrolling on the other axis. The movement assertions
remain separate; starting to move is not evidence that the previous native animation has finished.
The helper neither sleeps nor repeats input, and it removes listeners and timers on completion or failure.

## Dark readiness

A page turns dark only when it is declared in `apps/common/screens.py` (`DARK_READY`). A spec that
needs a dark page before its screen's gate declares it asks the server with the fixture `dark_ready`
(`server/steps/p3.py`, pinned by `tests/test_e2e_steps_p3.py`): `{"add": ["app_name:url_name", …]}`
adds pages for the next request in this process, `{"clear": true}` puts back the code's own set, and
both answer `{"ready": […]}`. Clear it in `test.afterEach`, as `self/theme.spec.ts` does, so no other
spec meets a page it did not declare. The device's scheme is `page.emulateMedia({ colorScheme })`.

## Visual baselines

`visual/` photographs screens and compares each photograph with its baseline under
`__screenshots__/` (`toHaveScreenshot`, at most 0.1 % of the pixels may differ:
`maxDiffPixelRatio` in `playwright.config.ts`). Spec: `docs/specs/03-rebuild-screens.md` D9, plan T10.

- **Where they compare.** Only where `E2E_VISUAL=1`, which only CI's **Visual (Playwright)** job and
  the baseline workflow set. Anywhere else, a local `CI=1` run included, a visual spec skips with
  "baselines are made and compared in CI (D9)": this machine's fonts (Inter here) and its iPhone 13
  (Chromium unless `CI=1`) are not the runner's. The behavioural shards skip them too; the visual
  job runs `tests/e2e/visual` on the three projects. CI's Visual job runs only once a PNG is committed
  under `__screenshots__/` (until the first `visual:` commit it is skipped with a notice), and from
  then on a missing or changed image fails it.
- **Who writes them.** `.github/workflows/visual-baselines.yml`, and nothing else:
  `playwright.config.ts` sets `updateSnapshots` to `all` only when `CI`, `E2E_VISUAL=1` and
  `E2E_UPDATE_BASELINES=1` are all set, and `none` otherwise (never Playwright's default `missing`);
  `snap` refuses a run given `--update-snapshots` by hand. Start it on the branch:

  ```bash
  gh workflow run visual-baselines.yml --ref claude/trusting-dijkstra-m7nul1 -f specs=tests/e2e/visual/shell.spec.ts
  ```

  It uploads the artifact `visual-baselines` (`tests/e2e/__screenshots__/` and the shell pair taken on
  WebKit at 390 px, before (main `045978b`) and after (this branch), which is D3's type pair), then
  commits the changed baselines back to the branch it ran on: one commit, `visual: baselines for
  <specs> (run <id>)`, holding only PNG files under `tests/e2e/__screenshots__/`, and none when
  nothing changed or when any step of the photographing job (the type pair included) failed. Only
  its second job, which runs no project code, holds a write token, and it pushes
  fast-forward only to a branch of this repository: never for a fork's pull request (there, download
  the artifact) and never to the default branch; if the branch moved on meanwhile, nothing is pushed
  and the run says so. A push made with the workflow's token starts no CI run, so the next push
  compares the new baselines: pull the commit (`git pull --ff-only`) before pushing again. Look at
  every image in that commit and put its before/after pair on the pull request. The workflow never
  cancels CI, and its jobs queue rather than cancel, so another label on the pull request cannot cut
  a baseline run short. GitHub offers it for dispatch once it has run: the `visual-baselines` label
  on the pull request runs it once and registers it (if a dispatch is refused, re-label once).
- **Stable by construction.** A spec freezes the clock first, then asks for the visual workspace
  (`visualWorld(page, harness)` does both and turns on reduced motion, D7, so nothing moves in a
  photograph; `snap` refuses a page without it), signs in as one of its people, and clears the clock
  after each test (`test.afterEach(() => thawClock(harness))`):
  - `visual_clock` (`server/steps/visual.py`): `{"at": "2027-01-03T09:00:00+05:30"}` freezes the
    server's clock (`server/clock.py` puts its own `now` in `django.utils.timezone` and in every copy
    of it), so request threads and the worker read the same instant; `{}` puts the real clock back.
    While it is frozen the worker is held between tasks (`worker.hold`): a clock months from the real
    one would make every other spec's rows fall due at once. The three check-ins Home's health reads
    are stamped at the instant (the team reads as online on any real date) and put back on clear.
    `freezeClock` also fixes the browser's clock (`page.clock.setFixedTime`). A session expires 14
    days after it is made, so sign in after setting the clock, and again after moving it.
  - `visual_workspace` (`{}`): workspace `00000000-0000-4000-8000-0000000000c1`, "Riverside Homes", in
    its own organisation "Visual Agency" (Asia/Kolkata); `visual-owner@e2e.test` (Vera, the lead) and
    `visual-editor@e2e.test`; Instagram, LinkedIn company and Facebook; the brand profile; four posts
    proposed in the week of Mon 4 Jan 2027 (`?date=2027-01-04`), two waiting for review and two
    drafts; three briefs (ready, approved, stopped) and the team thread. Every id and time is fixed
    and all before the instant; each call puts the same rows back; A and B are never touched. What
    Home shows of it does not depend on the instant (no proposed time on a brief, nothing finished
    within a day of it, no post within the next 24 hours), so the self spec can move the clock.
  - `data-visual-dynamic` marks, in the templates, what prints today's date or a time relative to now
    (`{% now %}` and `timesince` read the real clock, not the frozen one): Home's greeting and date,
    Recent work's "… ago", the thread's message times and the notifications drawer's "… ago"; each
    screen marks its own. It is the one selector a spec may use that is not a test id, and only to
    mask; `tests/test_e2e_steps_visual.py` pins which elements carry it.
- **snap.** `snap(target, name)` (`support/visual.ts`): a locator (the screen's own region, the
  phone bar masked where it floats over it) or the page (a whole state, the shell included); waits
  until no HTMX request is in flight, the fonts are loaded and the region has settled; masks
  `[data-visual-dynamic]` (in a locator's photograph only what shows in its box, `masksFor`: what the
  region covers, such as Home's greeting and the phone bar under the New post sheet, is never masked
  over it); disables animations and hides the caret; and names the file
  `<name>-<scheme>-<project>.png`. `forSchemes` (`support/schemes.ts`) declares a case once per
  colour scheme, for axe and visual cases only; behavioural flows run in light.
- **The harness's own check.** `self/visual-harness.spec.ts` runs everywhere: no run but the
  baseline workflow's writes a baseline, two masked photographs of the visual Home two seconds apart
  are byte-identical, so are they with the clock 90 days on, the masked elements exist, a region's
  photograph masks what shows in it and not what it covers, and the
  visual world is shown with reduced motion in both schemes (the stylesheet's rule holds the page's
  transitions at 0.01 ms).

The first baseline is `visual/shell.spec.ts`: the shell around the visual workspace's Home, light, on
the three projects. It is committed at the foundations gate; screen 1 (which removes the New menu) and
screen 2 (which rebuilds Home) refresh it in their own `visual:` commits.
`visual/new-post.spec.ts` (screen 1, T24): the New post button at rest on Home and the sheet in Ask the
team, Write it myself and the idea form, each as its own region, in light and dark on the three projects.

## Pairs and the light diff

Phase 3's before/after pairs for the owner and the check that light rendering did not move
(`docs/specs/03-rebuild-screens.md` D9, `docs/specs/phase-3.md` T12). They are not tests of the
product: `playwright.pairs.config.ts` runs only `tests/e2e/pairs/` (the main config never picks those
files up), compares nothing against a baseline and writes only under the gitignored
`test-results/pairs/`. The images go to the owner with the pull request, never into the repository.
Run the main suite after copying them out: its own output folder is `test-results/`, which Playwright
empties on every run.

```
tests/e2e/pairs/
  NN-name.pair.ts   one pair: a `before` block (main's hooks only) and an `after` block (this branch's)
  support.ts        pairTests (a pair file's tests), pairSide, ensurePairData (the same two posts on
                    every server, once), capture, shootState
  diff.ts           npm run pairs:diff
  compare.cjs       PNG reading and the pixel count (tests/js/pairs_compare.test.cjs)
```

The *before* side comes from a worktree of main with its own stylesheet, server, database and port:

```bash
git worktree add ../smbean-main 045978b
cd ../smbean-main && (cd theme/static_src && npm ci && npm run build)    # dist/ is gitignored
DB_NAME=smbean_main_e2e ../calander-9-/.venv/bin/python -m tests.e2e.server --reset --port 8231
# back in this branch:
PAIR_SIDE=before E2E_PORT=8231 npm run pairs -- tests/e2e/pairs/00-shell.pair.ts
E2E_PORT=8221 DB_NAME=smbean_p3_e2e npm run pairs -- tests/e2e/pairs/00-shell.pair.ts
```

`npm run pairs` writes `test-results/pairs/<pair>/<side>/<state>-<project>.png`: the screen at
390 × 844 (`pair-390`, iPhone 13) and 1440 × 900 (`pair-1440`, Desktop Chrome), light, as the device
shows it, with nothing masked: the owner signs the pair off, so Home's greeting, today's date and
every time show as they render (a state fails if its image holds the mask colour). The before side
starts no server (one must be listening on `E2E_PORT`); the after side starts this branch's with
`--reset` when none is. Each state names a `hook`, a test id the page must show: a state whose hook
is missing fails and writes nothing, so an *after* never shows a screen that has not been built yet.
A pair file lists its `before` and `after` states and hands both to `pairTests`. Local pairs use
Chromium and the local `system-ui` (Inter here), so they are not a typeface sign-off; the type pair
comes from WebKit in CI (T10).

`npm run pairs:diff` renders the a11y sweep's eleven pages and the three Lighthouse pages (Home is in
both, so thirteen) at both widths on two servers, each whole page in one image (the viewport grows
until the shell's scroller hides nothing), with the elements that print a time masked by the
config's `pairMasks` (`time`, Home's greeting and date, `timesince`; main has no
`data-visual-dynamic`). Only the diff is masked; the pairs above never are. It fails when a pair
differs in more than 0.1 % of its pixels and lists the page and the ratio;
`test-results/pairs/diff/<project>/` holds both images, a `-diff.png` marking the pixels of a page
over the limit, and `summary.json`. Both servers run with `--no-worker` (the diff refuses a server
whose worker runs: it would change rows between the two renders of a page):

```bash
# in ../smbean-main
DB_NAME=smbean_main_e2e ../calander-9-/.venv/bin/python -m tests.e2e.server --reset --no-worker --port 8231
# in this branch (starts this branch's server with --reset --no-worker when none is on E2E_PORT)
PAIR_BEFORE_PORT=8231 E2E_PORT=8221 DB_NAME=smbean_p3_e2e npm run pairs:diff
```

Two servers of the same commit report 0 differences. Both sides get the same two posts through
`ensurePairData` the first time a pair or the diff meets a server, so start both with `--reset` and
use them only for this.

## What the server does

One process, because the fakes are module attributes shared by the request threads and the worker:

- **Clock** (`clock.py`): real, until a visual spec freezes it with `visual_clock` (Visual baselines,
  above); `django.utils.timezone.now` and every copy of it read the frozen instant then.
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
  analytics sync, health checks), which could only reach the mock's refusal. `hold()` stops it between
  tasks while the clock is frozen; `resume()` lets it go on.
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

Unknown name: 404, whatever the method; a known name with the wrong method: 405. Bad payload: 400
`{"error": ...}`. A fixture body that is not `application/json`: 415. Not loopback, or a request a
browser marks as coming from another site (`Origin` or `Sec-Fetch-Site`): 403. Any settings module but
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
  const since = Date.now() / 1000;                       // this test's window for refused_network
  await as('editor');                                    // or as({ email }); the session cookie, no form
  const brief = await harness.fixture<{ id: string }>('my_fixture', { title: 'x' });
  await page.goto(`/workspace/${harness.ids.workspace_a}/studio/`);
  await axe(page, 'Home (editor)');                      // every screen; axe(page, label, { include: '[role="dialog"]' }) for a dialog
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});
```

## Rules for specs

- **Selectors:** all new tests use `data-testid` only. Never a CSS class, copy text or
  an Alpine attribute. The one exception is `[data-visual-dynamic]`, and only to mask a photograph
  (Visual baselines). Existing invariant golden paths retain their original role selectors under
  the instruction not to edit those tests. A missing hook is added to the template next to the existing attributes:
  `data-testid="<area>-<thing>"`, kebab-case (`approvals-row-approve-schedule`, `home-thread-send`).
  A hook that stands for a record ends in that record's key exactly as it is stored, underscores
  included, so a spec builds it from the data it already has (`home-today-post-<brief id>`,
  `setup-row-creation_mode`, `connect-platform-linkedin_company`).
  Existing `data-*` hooks that pytest asserts stay exactly as they are.
- **A hook shown twice:** a few controls are in the page twice, one copy per width, and only one
  is visible: the bell (`notifications-bell`, `notification-badge`) and Go to (`palette-open`) in
  the sidebar header and again in the phone's top bar, and the portal's navigation
  (`portal-nav-*`). Take the copy this device shows with `.filter({ visible: true })` and expect
  exactly one. The places are not duplicates: the sidebar's `nav-<key>` and the phone bar's
  `phone-bar-<key>` are different hooks, and `support/nav.ts` (`go`, `placeLink`, `openMore`,
  `expectLit`) picks the one a person would tap. On a phone the closed drawer is off screen but
  counts as visible, so open it with `openMore` before using a `nav-<key>` link there.
- **Sign-in:** only golden path 1 posts the login form (10 posts a minute per address; call
  `reset_login_limits` first). Everything else signs in with `as(...)`.
- **Axe** on every screen a test reaches and on each dialog it opens; it fails on serious or critical
  violations with the rule, impact, element and help page. It waits for running transitions first
  (up to 3 s), so a menu that fades in is checked at its final colours. Fix the template, not the check.
  axe counts opacity in colour contrast, so after an htmx swap, a toast or a dialog that fades in, a
  test can also `await settled(locator, 'what')` (`support/settled.ts`): the element and its
  ancestors fully opaque and no finite animation still running.
- **After an action, wait for its answer:** register `page.waitForResponse(...)` before the click or
  drop, check its status, then probe once. A view that writes in several statements answers only
  when all are done; polling a probe can catch the first write alone.
- **Outcomes in the database:** assert through probes, not only on the page.
- **Network:** every browser request to another host is aborted (`network.blocked` lists them). A
  route only ever sees the first URL of a redirect chain, so a server redirect to another host would
  be followed for real: such a request is recorded in `network.escaped` and fails the test at its end
  (`support/test.ts`). WebKit also refuses `route.fulfill` with a 3xx status. So a test that needs an
  outside page (an OAuth authorize URL) routes the app's own request that answers the 302 instead:
  `route.fetch({ maxRedirects: 0 })` sends it through the browser context (its cookies land in the
  browser), the authorize URL and its `state` are read from the `location`, and the route answers
  with a plain 200 page; the test then reaches the app's callback with the `code` and the `state`
  (`routeGoogle` in `golden/01-sign-in.spec.ts`, the X connection in `golden/02-onboarding.spec.ts`).
  On the server side, a test probes `refused_network` with `since` set to its own start, never the
  server's whole lifetime (a server kept running between runs remembers earlier ones). The whole run
  is checked once at its end (`support/global-setup.ts`): anything the server tried to reach outside
  the machine during the run fails it, with the host and where in the server it was tried.
- **No retries, no `test.skip`/`test.fixme` to make a path green;** each test makes its own rows.
  A genuinely flaky test is quarantined with a tracking issue, not retried in CI. Gate evidence
  reports quarantined, failing and unrun cases separately from passes.
