# Phase 3 plan — rebuild the nine screens

Executes [`03-rebuild-screens.md`](03-rebuild-screens.md) (decisions D1–D16, foundations F1–F7,
screens 1–11, R1–R2) on top of [`00-cut.md`](00-cut.md) and [`02-cut-and-merge.md`](02-cut-and-merge.md).
Skills: `impeccable` (load first, every screen), `frontend-design` (named by `BETA_PLAN.md` for every
Phase 3 screen), `design-is` (the audit at each screen's end), `make-plan` → `do`,
`test-driven-development` inside each task, `engineering:code-review` and `requesting-code-review`
before each gate, `verification-before-completion` for each gate. `frontend-design` is not installed in
this environment (it is not in the session's skill list on 1 Nov 2026). Until it is, its part (shaping
the screen at 390 px before code: layout, hierarchy, type, colour, motion) is done by `impeccable`'s
shape step at each screen's Start task, and the changelog entry says so; if the skill becomes
available, it is loaded beside `impeccable` from the next screen on.

**How this plan is used.** Part A (foundations) and Part B (screen 1, the New post sheet) are written
as tasks. Part C outlines screens 2–11. When the owner signs off a screen's pair, the next screen's
outline is expanded into tasks in this file, in a `docs:` commit, from a fresh read of the files it
cites, before any of its code is written. No screen starts before the sign-off of the one before it
(D1). One branch (`claude/trusting-dijkstra-m7nul1`), one draft PR; nothing is merged or released
until the owner authorises it.

## Phase 0 — Documentation discovery (done)

Four read-only surveys of main `045978b` on 1 Nov 2026 (design system, creation paths, tests, the
eleven screens) produced the facts in the spec and the ones below. Their reports are kept outside the
repository. **Every task starts by re-reading the files it cites and confirming each line before it
edits**: the surveys are snapshots and line numbers drift.

### Facts this plan relies on

- **Colour.** The scale utilities are declared `@theme inline` (`theme/static_src/src/styles.css:76-101`),
  so every `bg-ink-*`, `text-brand-*` and `ring-success-*` reads its Layer 1 variable where it is used:
  redefining Layer 1 under a dark theme flips their 3,424 uses without edits. These do not follow:
  `bg-white` (208, plus 34 with opacity), `text-white` (99; 54 class strings pair it with a dark fill),
  the scrims `bg-ink-950/35…/75` (about 36), `outline-white` 12, `border-white` 6, `ring-white` 1,
  `bg-black` 10. styles.css also writes colours outside Layer 1: `#fff` at 404, 407, 461, 535, 638,
  701, 748, 763, 847, 848, 859, 942, 982, 1013; `rgb(14 17 20 / …)` fills at 381, 478, 717, 760-761,
  768, 864; shadows at 126-130 and 255-264; `--surface-sticky` (209), `--overlay` (210),
  `--primary-halo` (189), `--text-inverse` (224), `--color-illustration-card` (230); the pulse keyframes
  `rgb(3 90 123)` (138-140, 1072); data-URI chevrons `%23656B73` (664, 791); the error halo (521).
  Chart.js colours are literal in `templates/base.html:1173, 1229, 1233` and
  `static/js/live_board.js:183, 228`. The semantic utilities (`bg-surface`, `text-fg` …, styles.css
  102-116) are used 0 times. There is no dark mode anywhere (no `prefers-color-scheme`, `data-theme`
  or `dark:`). `tools/recolor.py --check` passes today and does not read styles.css. The palette lock
  writes `--color-white: #fff` and `--color-black: #000` (styles.css:37-38) and must keep them; the
  shadows are written `rgba(14, 17, 20, …)` (126-130); `--primary-rgb: 17, 86, 65` (190) has no user in
  templates or `static/js`. Solid `bg-ink-800|900|950` fills appear 39 times in 25 templates, among
  them the two selection bars (`calendar.html:314-325`, `calendar/partials/publish_approvals.html:60-69`),
  whose children write `text-white`, `bg-white/20` and `hover:bg-white/10` in their own class strings.
  The composer's previews use `bg-white` as the platform's canvas (`composer/partials/preview_panel.html:22,
  65, 144, 223`) and `bg-white/90` carousel buttons (91, 95, 177, 181).
- **Type.** `--text-caption` 12 px and `--text-micro` 11 px (styles.css:160-161); Tailwind's
  `text-xs` (12 px) has 425 uses; 623 template uses in 151 files are under 13 px, plus 26 inline sizes
  and 17 rules in styles.css (392, 399, 552, 623, 644, 817, 828, 845, 851, 902, 920, 977, 1012, 1013,
  1020, 1024, 1025). `<body>` sets no size (`base.html:237`). The one font file
  (`static/fonts/inter-latin-normal.woff2`) is unreferenced; CSP `font-src 'self'`
  (`config/settings/base.py:476`). recolor's classifier marks a template with `<html>` and no
  `styles.css` as not loading tokens (`tools/recolor.py:652-653`), so a guard built on it skips the
  standalone pages: `members/accept_invite.html` sets `font-size: 12px` at 41, 54 and 90. The vendored
  Chart.js 4.4.6 (`static/js/vendor/chart.umd.js`) defaults to 12 px and `bbInitHeroChart` sets no
  font size (`base.html:1211-1235`); `live_board.js`'s hour chart and tip are DOM elements, not
  Chart.js. Running text sets its own size: thread messages `text-body-lg` (15 px,
  `thread_messages.html:39, 75, 80, 86`), draft captions `text-sm` (`thread_draft.html:11`).
- **Spacing.** `.ui-card` is 16 px below 640 px and 20 px above (styles.css:809-811), the reverse of the
  target; 42 % of spacing utilities sit on the 8 px grid.
- **Motion.** Tokens at styles.css:275-282; one global reduced-motion rule (1042-1053) covers every page
  that loads the stylesheet; seven template-local `@keyframes` and six local reduced-motion blocks.
- **Creation.** The sidebar New menu and its idea and tag dialogs are `base.html:454-731`, with
  `window.ideaModalHelpers` and `sidebarNewMenu()` at `:1291-1611`, shown to anyone in a workspace
  (`:455`). `sidebar_context` queries idea columns and tags on every render, fragments included
  (`apps/common/context_processors.py:115-123`). `studio:create` (`apps/studio/views.py:240-293`)
  answers not-configured and over-budget with a message and a redirect, and a form or chat error with
  a 400 re-render of `studio/index.html` that never shows the form. No template renders `BriefForm`.
  Home's thread posts to `studio:thread_start` with `kind=question`.
- **HTMX.** htmx 2's default `responseHandling` does not swap 4xx. `base.html:311-330` turns any
  `htmx:responseError` into the error toast, except for an element with `data-no-error-toast`, and
  writes the response's plain text into the container a form names with `data-inline-error`.
  `request.htmx` is available (`apps/studio/views_chat.py:64`); `HttpResponse(status=204,
  headers={"HX-Redirect": url})` is the codebase's redirect (`apps/composer/views.py:2785`).
- **Overlays above the phone bar.** `ABOVE_THE_BAR = bottom-[calc(4.5rem+env(safe-area-inset-bottom))]`
  with `lg:bottom-6` (`apps/common/tests/test_navigation_render.py:540-555`). Toasts already rise above
  the selection bars through a body class (`calendar.html:291-293`,
  `approvals/partials/_toasts.html:32-36`).
- **Harness.** `playwright.config.ts` has the screenshot path template and `maxDiffPixelRatio: 0.001`,
  no `colorScheme`, no `reducedMotion`, no `updateSnapshots`; `iphone-13` is WebKit only with `CI=1`.
  CI triggers only on push to main and pull requests (`.github/workflows/ci.yml:3-6`), and its
  concurrency group cancels an in-progress run for the same ref (`:13-16`). The E2E job's limit is
  35 minutes (`ci.yml:289`, raised from 20 in Phase 2 for about 225 cases); `playwright.config.ts`
  runs one worker (`workers: 1`, `fullyParallel: false`: one server, one database); a complete local
  run took 22.9 minutes (`CHANGELOG.md:56`). The harness has no clock control (no freeze, `page.clock`
  or `setSystemTime` under `tests/e2e`); fixtures use `timezone.now()`; the e2e worker keeps the
  publish loop and drops only `PLATFORM_POLLS` (`tests/e2e/server/worker.py:25`). Local iPhone 13 runs
  use Chromium (`playwright.config.ts:46`), and `fc-match system-ui` gives Inter here.
  `theme/static/css/dist/` is gitignored (`.gitignore:215`), so a fresh worktree has no stylesheet until
  C5 runs in it. `workspace_switches`
  refuses the shared workspaces A and B (`tests/e2e/server/steps/screens.py:74-91`). Lighthouse's three
  targets and their interactions are hard-coded in `tests/lighthouse/run.mjs:87-153, 184-188`; the
  New → Idea → emoji interaction runs on all three (`:134-142`).
- **Pinned tests.** `test_a11y_sweep.py` renders eleven pages and needs more than ten labelled, trapped
  dialogs (`:225-244`); it reads a static `aria-label` or `aria-labelledby` (a bound `:aria-label` alone
  fails it). The shell's notifications drawer and Go to are dialogs on every swept page. The status
  mapping is `apps/approvals/templatetags/approval_extras.STATUS_META` (tone per status) and, for briefs,
  the branches of `templates/studio/partials/status_badge.html`. `apps/studio/tests/test_setup.py` holds
  three protected tests (`test_readiness_speaks_plainly_and_points_at_set_up`,
  `TestToday::test_private_telegram_jobs_stay_out_of_the_card`,
  `TestSetupPage::test_owners_see_the_exact_names_and_others_are_told_to_ask`) beside ordinary ones
  that screens 1, 2, 4 and 9 move.
- **Approve paths.** `apps/approvals/views.approve` has four outcomes that move a post (two-stage,
  scheduled, no future time, plain) and three refusals. The built-in client role grants
  `approve_posts` (`apps/members/models.py`); `calendar_view` sets `can_approve` from it alone
  (`apps/calendar/views.py:625`); `_approval_row.html:136-142` then offers *Approve & schedule* on a
  `pending_client` row; `gate._stamp_on_approve` keeps the internal stamp for a client's sign-off and
  `_schedule_at_approved_time` schedules any approved channel with a future `approved_publish_at`.
- **Creation refusals.** `customer_workflow.start_idea` can save the idea and start no job when
  `chat.reply_refusal` answers "cap" (`customer_workflow.py:229-231`, `chat.py:842`); the view shows
  `started.note` then (`views.py:289-292`). `budget.over_budget_message` says "AI budget" with the
  amount and "Agency → Autopilot" (`budget.py:64-68`), has about 20 callers, and
  `apps/blog/tests/test_team_views.py:121` pins "AI budget". `base.html:313-326` returns on
  `data-no-error-toast` before it reads `data-inline-error`.
- **Destructive and paid actions with browser modals or no confirm** on the eleven screens are listed
  in the spec's D8 table (`hx-confirm` and `confirm()` sites, the post page's unconfirmed *Discard*).

### Allowed APIs and patterns (copy these)

| Need | Copy from |
|---|---|
| Who may start posts | `require_permission("create_posts")`; `is_plain_client` and `_workspace` (`apps/studio/views.py:51-74`) |
| HTMX answer and redirect | `request.htmx`; `HttpResponse(status=204, headers={"HX-Redirect": …})`; inline errors through `data-inline-error` (`base.html:323-327`) |
| Switches | `features` in templates (`apps/common/context_processors.py`), `feature_enabled(workspace, key)` |
| Dialog focus | `x-trap.noscroll`; close the phone drawer before opening (`this.mobileMenuOpen = false;` first, `base.html:1409-1427`); Escape closes and returns focus to the opener |
| Floating above the bar | the `ABOVE_THE_BAR` class string plus `lg:` placement; lifting by body class like `has-selection` |
| Status words and tone | `approval_extras.status_badge` / `STATUS_META`; `studio/partials/status_badge.html` |
| E2E | `tests/e2e/support/test.ts` (`test`, `expect`, `as`, `axe`, `harness`), `support/settled.ts`, `support/nav.ts`; fixtures with `@fixture`/`@probe` in `tests/e2e/server/steps/*.py`, their pytest in `tests/test_e2e_steps_*.py` |
| Runtime fakes in the e2e process | `tests/e2e/server/fakes.py` patches modules after start; a harness switch does the same, never a production hook |
| Lighthouse | `budgets.mjs` (`validateConfig` unchanged, `measurements`, `evaluate`) |
| Contrast | WCAG 2.x relative luminance, the method of `DESIGN_SYSTEM.md` §23 |
| Node tests of template JS | `tests/lighthouse/emoji-init.test.mjs` (slice a function from a file, run it in `vm`) |

### Anti-patterns (do not)

- Edit `apps/approvals/gate.py`, `actor.py`, `apps/publisher/engine.py` or `apps/studio/services.approve`;
  any golden spec (01–12, 05-06, 11-inputs); any test that enforces a `CLAUDE.md` invariant
  (`test_a11y_sweep.py`, `test_setup.py::test_readiness_speaks_plainly_and_points_at_set_up`,
  `test_setup.py::TestToday::test_private_telegram_jobs_stay_out_of_the_card`,
  `test_setup.py::TestSetupPage::test_owners_see_the_exact_names_and_others_are_told_to_ask`,
  `test_chat_provider_readiness.py`, `apps/telegram/tests/test_web_privacy.py`, the gate and publisher
  tests, `live_verify`'s isolation check). The guard is per test (T1's protected-test hashes), so the
  ordinary tests beside them in the same file may move.
- Add a URL path part, or a URL without D12's checklist. Deep entry is an anchor (`#new-post`).
- Let a gesture, a scroll or the browser approve, schedule or compute an approval time (D13).
- Write a colour value in a template outside emails, the standalone pages and platform content; add a
  default Tailwind palette class; put `light-dark()` in a custom property (iOS Safari 16 and 17.0–17.4
  drop the whole property, and section 5 supports iOS Safari 16+).
- Load a font from another host or use a weight above 700.
- `test.skip`/`test.fixme` to hide a failure. The only declared skip is D9's: visual specs compare
  only under `E2E_VISUAL=1`, which only CI's jobs set (not `CI`, which `CLAUDE.md`'s local runs set).
- Write baselines locally, or change one outside a `visual:` commit.
- Remove a pytest assertion without a replacement that protects the same behaviour (D11).
- Move the chart initialiser out of `base.html` (`tests/lighthouse/chart-init.test.mjs`); change
  `.lighthouserc.json`'s budgets, or its three URLs without the owner's answer at S4 (D10); add retries.
- Confirm a destructive or paid action in a modal, `hx-confirm` or `confirm()` (D8).
- Put `data-no-error-toast` on a form that relies on `data-inline-error`: the handler returns before
  it writes the inline error (`base.html:313-326`).
- Show a time the server did not stamp, or say "Scheduled" for an outcome that did not schedule (D13).

### Routes and hooks that must keep working

The URL contract (`studio:detail`, `studio:job`, `calendar:calendar` including
`?mode=list&tab=approvals`, `client_portal:*`, `telegram:settings`); every URL in
`tests/fixtures/product_map_urls.txt` without a 404 or 500 (`studio:create` answers 405 to GET);
`composer:compose` answering 200 without a redirect (`live_verify` `dashboard.composer`);
`studio:thread_start`, the four `studio:workflow*` names, `composer:create_landing`, `drafts_list`,
`csv_upload`, `template_list`, `category_list`. Each screen's golden test ids and accessible names are
listed under its "Must not change" in the spec.

### Commands

```bash
.venv/bin/pytest -q -p no:cacheprovider <app or file>                     # C1
.venv/bin/ruff check . && .venv/bin/ruff format --check .                  # C2
.venv/bin/mypy apps/ config/ providers/ tests/ --ignore-missing-imports    # C3
.venv/bin/python manage.py makemigrations --check --dry-run                # C4
(cd theme/static_src && npm ci && npm run build)                           # C5
.venv/bin/python tools/recolor.py --check                                  # C6
npm ci --ignore-scripts && npm run test:ui && node --test tests/lighthouse/*.test.mjs   # C7
# C8, locally (iPhone 13 runs on Chromium here: not Safari coverage); unique DB_NAME and E2E_PORT per run
DB_NAME=brightbean_p3_e2e E2E_PORT=8152 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers npx playwright test <files>
# C9, two terminals
DB_NAME=brightbean_lighthouse_e2e .venv/bin/python -m tests.e2e.server --reset --no-worker --static manifest --port 8151
LIGHTHOUSE_BASE_URL=http://127.0.0.1:8151 node tests/lighthouse/run.mjs [--targets=<names>]
.venv/bin/pytest -q -p no:cacheprovider                                    # C10, the full suite
.venv/bin/python tools/contrast.py [--markdown]                            # C11, from T2
# C12, in CI by hand (from T10 and T11): baselines, and per-screen Lighthouse targets on the runner
gh workflow run visual-baselines.yml --ref claude/trusting-dijkstra-m7nul1 -f specs=<files>
gh workflow run lighthouse-targets.yml --ref claude/trusting-dijkstra-m7nul1 -f targets=<names>
```

### The per-screen gate (G)

D1's checklist with the command for each item. A screen's last task runs all twelve and records the
results in `docs/specs/CHANGELOG.md`, with the working days used against the spec's estimate. If the
estimate is exceeded, the entry says so and the work **stops** for the owner to choose what moves out
(nothing the owner asked for leaves P0 without the owner's word).

1. **390 px first.** The screen's spec and pair were built on `iphone-13` before widening to 1440 px.
2. **Light and dark.** The screen's pages are in `screens.DARK_READY`; its spec runs axe and the
   visual snaps in both schemes (behavioural flows in light only, D10); previews stay white in dark.
3. **One primary.** `apps/common/tests/test_one_primary.py` passes with the screen marked `gated`:
   at most one per breakpoint, and in its place (D5).
4. **Reduced motion.** Its case in `tests/e2e/self/reduced-motion.spec.ts` passes.
5. **Audits.** `impeccable` and `design-is` audits run; must-fix findings fixed before the pair.
6. **axe.** 0 serious or critical, light and dark, three devices (the screen's specs, C8 and CI).
7. **Lighthouse.** C9 on the screen's targets: Performance ≥ 0.9, LCP ≤ 2,500 ms, CLS ≤ 0.1, lab INP
   ≤ 200 ms, gzip JS ≤ 150,000 bytes; medians recorded beside the Start task's reading on main; then
   the same targets once in CI (C12 `lighthouse-targets`), and that run's medians are the gate's.
8. **E2E.** The screen's specs green in CI (`CI=1`, WebKit for iPhone 13), zero retries; goldens
   unedited and green; the E2E job's wall time recorded and under 70 % of its limit.
9. **Palette.** C6 says "nothing left to do".
10. **Suite.** C10 green, with `tests/test_protected_tests.py` (T1) green: every protected invariant
    test's source equals its source on `045978b`; C2, C3, C4.
11. **Baseline.** The screen's files, and any earlier screen's files whose pages it changed, under
    `tests/e2e/__screenshots__/` in one `visual:` commit with their pairs.
12. **Sign-off.** The owner's words on the before/after pair, recorded with the date and SHA. **Stop.**

## The screen registry

One plain module, `apps/common/screens.py` (no Django import at module level, so `tools/recolor.py`
can import it), shared by every guard below:

- `DARK_READY: frozenset[tuple[str, str]]` — the `(app_name, url_name)` pages declared dark-ready.
- `PAGE_TEMPLATES: dict[tuple[str, str], tuple[str, ...]]` — for every page in `DARK_READY` or in a
  screen's `pages`, the root templates it renders (for example `("calendar", "calendar")` →
  `calendar/calendar.html`, `("studio", "index")` → `studio/index.html`; `base.html` is reached
  through `{% extends %}`). recolor cannot resolve URL → view → template without Django, so this map is
  how it finds a page's tree.
- `SCREENS: dict[str, Screen]` — per rebuilt screen: `templates` (root templates), `fragments`
  (partials that HTMX loads into its pages), `pages` (`(app_name, url_name)` to render), `roles` (who
  may open them) and `gated` (flipped at its gate).
- `template_tree(roots)` — the roots plus every template they reach through literal `{% include %}`
  and `{% extends %}` names; dynamic includes are listed in `fragments`.

Users: the readiness flag on `<html>` (T1), recolor's raw-colour rule (T3, over
`template_tree(PAGE_TEMPLATES[page])` for every `DARK_READY` page, plus the screens' `fragments`), the
spacing guard (T7), the one-primary test (T8), the inline-confirm guard (T8) and the motion guard
(T9). It grows at each gate.

## Part A — Foundations (F1–F7, about three days)

**T1. The registry and dark readiness, no visible change (F1).** Files: new `apps/common/screens.py`;
`apps/common/context_processors.py` (new `theme_context` returning `theme_ready` from
`request.resolver_match` against `DARK_READY`) registered in `config/settings/base.py`'s
`TEMPLATES`; `templates/base.html:3` and `templates/client_portal/portal_base.html` (`<html … {% if
theme_ready %}data-theme-ready{% endif %}>`); `apps/common/tests/test_screens.py`; the protected-test
guard: new `tools/protected_tests.py` (extracts each listed test's source with `ast`, by node id, and
prints a SHA-256 per node), `tests/fixtures/protected_tests.json` (the node ids of D11's list, with
their hashes written once from `045978b` and never regenerated in Phase 3), new
`tests/test_protected_tests.py` (recomputes each hash from the working tree; needs no git history, so
it runs in CI's shallow checkout).
Red: every registered template exists and every page reverses with a workspace id; `template_tree`
follows a literal include and an extends on fixture templates; every page in `PAGE_TEMPLATES`,
rendered with the test client as a member who may open it, has its listed roots in
`response.templates` (so the map cannot drift from the views); `theme_ready` is false for every page
today; with `DARK_READY` patched to hold `studio:index`, Home's `<html>` carries `data-theme-ready` and
Calendar's does not; an HTMX fragment never renders an `<html>` tag; the protected-test guard fails on
a fixture file whose protected function changed by one character and passes when only a neighbouring
function changed. Verify: C1 `apps/common tests/test_protected_tests.py`, C2, C3.

**T2. Dark tokens and the contrast checker (F1).** Files: `theme/static_src/src/styles.css` (dark
Layer 1 and Layer 2 under `:root[data-theme="dark"]`, the same declarations under
`@media (prefers-color-scheme: dark) { :root[data-theme-ready]:not([data-theme="light"]) { … } }` so a
declared page follows the device without JavaScript, `color-scheme: dark`; new tokens `--on-fill`,
`--surface-inverse`, `--text-on-inverse`, `--scrim` with utilities `text-on-fill`, `bg-inverse`,
`text-on-inverse`, `bg-scrim`; the light content scope `[data-theme-scope="light"]`, which re-declares
the light Layer 1 and Layer 2 values and `color-scheme: light`, for platform previews and creatives,
which must look the way the platform shows them in both themes), new `tools/contrast.py`, new
`apps/common/tests/test_contrast.py`, `docs/DESIGN_SYSTEM.md` (§21 becomes "Dark mode" with the
checker's tables and the light scope; §23 says how they are made).
Red: (a) the parser reads Layer 1 and Layer 2 for both themes and resolves `var()` chains; (b) five
light rows of §23 are reproduced to two decimals (proves the method); (c) every pair passes in both
themes; (d) the media block and the attribute block declare the same properties with the same values;
(e) every Layer 1 and Layer 2 property has a dark value; (f) the new tokens' light values equal the
literals they replace (`--on-fill` and `--surface-0` are `#FFFFFF`), so light rendering cannot move;
(g) the light scope declares every Layer 1 and Layer 2 property with exactly the light `:root` value,
and `color-scheme: light`. (c)–(e) and (g) fail today.
Pairs (in `tools/contrast.py`, one list): §23's text pairs on every surface; `--on-fill` on brand
700/800/900, danger 500/600, ink 800/900 and each status 500 used as a fill; tinted (brand-700 on
brand-100, brand-800 on brand-200); chips (status-600 on status-50, ink-700 on ink-100 and ink-200);
status-600 text on ink-0 and ink-50; 3:1 for `--border-control`, `--focus-ring` and status-500 icons on
every surface; `--text-on-inverse` and ink-300 icons on `--surface-inverse`; the sticky bar blended
over §23's worst creatives.
Green: start from §21 (links at the brand-300 role, the fill at brand-500 with dark text) while each
step keeps its role (D2: `ink-0` the card, `ink-50` the canvas, `ink-950` the strongest text,
`brand-700` the primary fill and link, status 50 soft fill, 600 chip text, 500 icon); let the checker
decide every value; never accept a pair under its bar. `C11 --markdown` writes the tables for §21.
Verify: C1 `apps/common/tests/test_contrast.py`, C5, C11.

**T3. The dark codemod and recolor's new rules (F1).** Files: `tools/recolor.py` (a `dark` pass and
new `--check` rules), new `apps/common/tests/test_recolor_dark.py`; then the tree it rewrites
(templates, `static/js/*.js` except vendor, the 17 Python class strings in `apps/`, styles.css), and
`apps/composer/tests/test_compose_layout.py:77, 87`, which pins `bg-white` in `composer-approval-panel`
(changed to `bg-surface` in the same commit; it is the only test that pins these classes).
First, the inventory of dark fills: every solid `bg-ink-800|900|950` (39 uses in 25 templates) is
listed in `apps/common/tests/test_recolor_dark.py` with its decision, inverse (stays dark in both
themes) or flips. The two selection bars (`calendar-bulk-bar`, `calendar.html:314-325`;
`approvals-bulk-bar`, `publish_approvals.html:60-69`) and any container whose children use white or
200/300-step colours are inverse.
Rewrites: `bg-white[/NN]` → `bg-surface[/NN]`, except inside the light scope (the composer's previews,
`composer/partials/preview_panel.html`, and later `components/post_preview.html`, which gain
`data-theme-scope="light"` on their root and keep `bg-white` and `bg-white/90` as the platform's look);
`text-white` (and `hover:`) on an element whose own class string or nearest ancestor (recolor's
`_element_context`) sets a fill that flips (`bg-brand-600…950`, `bg-ink-700…950`, a status `-500…950`,
`bg-black`) → `text-on-fill`; the elements that stay dark in both themes (toast, tooltip, chart tip,
selected filter chip, logo mark, `.hour-bar.is-now`, `.timeline-now`, the two selection bars and the
rest of the inventory's inverse set) → `bg-inverse`/`text-on-inverse`; their children's `text-white`,
`bg-white/NN` and `hover:bg-white/NN` stay (white is the palette lock and does not flip, and the
surface stays dark), and the check accepts them because the nearest ancestor's fill is inverse; scrims
`bg-ink-950/NN`, `bg-ink-900/NN` (NN ≥ 30) and `bg-black/NN` → `bg-scrim/NN`;
`ring|outline|border-white` → `-surface` on content and `-on-inverse` on inverse
surfaces; styles.css literals (the lines listed in Phase 0) → tokens by role, `rgb(14 17 20 / a)` and
`rgba(14, 17, 20, a)` (the shadows) → `color-mix(in srgb, var(--ink-950) a, transparent)`, the pulse
colour → `var(--info-500)` through `color-mix`, the two data-URI chevrons → a CSS mask with
`background-color: var(--text-tertiary)` (data URIs cannot read variables); `--primary-rgb` is retired
(no user). `text-white` over a photo or a scrim stays, with `recolor: keep` after a look.
New `--check` failures: `bg-white` on any page that loads the stylesheet, outside the light scope;
`text-white`, `bg-white/NN` or `hover:bg-white/NN` on an element whose own fill or nearest ancestor's
fill flips, without `recolor: keep`; a hex, `rgb()` or `hsl()` value in a `<style>` block, `style=`,
`:style=` or an SVG colour attribute of any template in the tree of a `DARK_READY` page
(`template_tree(PAGE_TEMPLATES[page])`); in styles.css, a case-insensitive match of
`#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(` in a declaration's value (not a selector) outside the Layer 1 block,
with two named exemptions, the palette
lock's `--color-white: #fff` and `--color-black: #000` lines. Exempt as today: emails, `TOKEN_ROOTS`'
standalone pages, `LITERAL_DIRS`, `presets|type="color"|recolor: keep` lines; plus platform glyphs
(`partials/_platform_icon.html`) and the light scope's subtrees.
Red: for each rewrite, an input string and its expected output, including a `text-white` child of an
inverse bar (kept) and of a flipping fill (rewritten or flagged); for each check, a temporary template
that makes `--check` return 1 and name the file; styles.css cases for `rgba(14, 17, 20, .05)`, `#FFFFFF`
and `hsl(` outside Layer 1
fail, and the two palette-lock lines pass; `--check` on the tree fails with today's counts.
Green: run `python tools/recolor.py`, read `git diff` file by file, mark the keeps.
Acceptance: C6 clean; light rendering unchanged by machine (T12's `pairs:diff`: the a11y sweep's
eleven pages and the three Lighthouse pages at 390 and 1440 px, main against this branch with the same
data and the time-printing elements masked, each light screenshot within 0.1 %); the golden suite is
green on desktop.
Verify: C1 `apps/common apps/composer`, C5, C6, C10, T12's `pairs:diff`, C8 `tests/e2e/golden` on
`desktop-chrome`.

**T4. Charts read the theme (F1).** Files: `templates/base.html` (inside `bbInitHeroChart`, keeping
the markers `chart-init.test.mjs` slices by), `static/js/live_board.js:183, 228`, a token reader
`bbToken(name)` (`getComputedStyle(document.documentElement).getPropertyValue('--' + name).trim()`), a
redraw on the `bb:themechange` event (T5 fires it); the chart's text at 13 px
(`Chart.defaults.font.size = 13` set inside `bbInitHeroChart` before `new Chart`, which the vendored
4.4.6 otherwise draws at 12 px on canvas, out of the type guard's reach; `live_board.js`'s hour chart
and tip are DOM text sized by styles.css and covered by T6's guard). Red:
`tests/lighthouse/chart-init.test.mjs` gains "no colour literal between `function bbInitHeroChart(`
and `// Wrap in a no-arg callback`" and "the sliced function sets the font size to 13 or more"; new
`tests/js/live_board_colors.test.cjs` (colours come from the token reader; a stubbed theme change
redraws once). Verify: C7, C1 `apps/analytics apps/studio/tests/test_live.py`.

**T5. Appearance and the head script (F1).** Files: `templates/base.html:27-36` (the existing nonce'd
head script gains `window.bbTheme`: the preference `system|light|dark` in `localStorage.theme`,
default `system`; `data-theme` is set only when `<html>` has `data-theme-ready`; it follows
`matchMedia('(prefers-color-scheme: dark)')` and `storage` events and fires `bb:themechange`); the
account menu (`base.html` near `:822`) gains **Appearance**, a labelled radio group System · Light ·
Dark (`data-testid="account-appearance-system|light|dark"`), with "This page stays light for now." on
a page not declared ready; `client_portal/portal_base.html` gets the same head script; new harness
fixture `dark_ready` in `tests/e2e/server/steps/p3.py` (adds or clears URL names in the e2e process's
readiness set by patching `apps.common.screens`, as `fakes.py` patches) with
`tests/test_e2e_steps_p3.py`.
Red: `apps/common/tests/test_theme.py` (the head script carries the nonce and precedes `<body>`; the
group has three labelled radios; `test_csp_headers.py` unchanged and green); new
`tests/js/theme_resolve.test.cjs` (sliced from `base.html` like `emoji-init.test.mjs`: not ready → no
attribute; system with a dark device → dark; light chosen → light; storage throws → system); new
`tests/e2e/self/theme.spec.ts` on three devices, with `dark_ready` set for `accounts:settings` and
cleared after each test: a dark device paints the Account page dark; choosing Light repaints without a
navigation and survives a reload; an undeclared page with Dark chosen stays light; with JavaScript off
and a dark device, the declared page is dark (the media block).
Acceptance (F1): no page is dark until declared; switching repaints without a reload.
Verify: C1 `apps/common tests/test_e2e_steps_p3.py`, C7, C8 `tests/e2e/self/theme.spec.ts`.

**T6. Type (F2).** Files: styles.css (`--text-caption` and `--text-micro` → 13/18; an `@theme`
override `--text-xs: 0.8125rem; --text-xs--line-height: 1.125rem;` so its 425 uses follow; the 17
sub-13 px rules; `--read-size`/`--read-leading` 16/24 below 1024 px and 15/22 from 1024 px, set on
`body` and offered as `@utility text-read`; `--font-display: system-ui, -apple-system,
BlinkMacSystemFont, "Segoe UI Variable Display", "Segoe UI", Roboto, …` on `h1`, `h2`,
`.ui-page-title`, `.text-display`, `.text-h1`, `.text-h2`, `h3`, `.text-h3`, `.ui-card-title`; page
titles 700 at −0.02 em, display −0.03 em, h2 700, h3 700; inputs stay 16 px below 1024 px); the 55
arbitrary `text-[9|10|11|12px]` uses → `text-xs` (the phone bar's labels, `base.html:928`, among them);
the 26 inline sizes; class strings in `static/js`; the standalone pages' inline `font-size` rules
under 13 px (`members/accept_invite.html:41, 54, 90`, and any the guard finds in the magic-link, legal,
error and unsubscribe pages) → 13 px, their literal colours untouched; `docs/DESIGN_SYSTEM.md` §5
("never smaller than 13px", the body token, the display stack, h3 at 700).
Red: new `apps/common/tests/test_type_floor.py` fails today, listing file:line for any `text-[Npx]`
under 13 or `text-[Nrem]` under 0.8125, any `font-size` under 13 px in a style block or attribute, any
`--text-*` token under 0.8125rem, in every template (the standalone pages included: the guard does not
use recolor's token classifier, which skips them), `static/js/*.js` and styles.css. Two named
allowlists, each entry with its reason: emails (the owner question on emails; removed if the owner
says no) and `static/css/marketing.css` with `templates/marketing/` (removed in screen 11). New
`tests/e2e/self/foundations.spec.ts`: `body` computes 16 px on the phones and 15 px on desktop at
1440 × 900; no horizontal overflow (`scrollWidth <= innerWidth`) on Home, Approvals, Calendar month and
Calendar list at 390 px. New `tests/e2e/support/type.ts` (`expectReadSize(locator)`: 16 px below
1024 px, 15 px from 1024 px), which each screen's spec calls on its named running-text elements (D3);
`<body>` alone proves nothing, because running text sets its own size.
Pinned strings: any test string holding a replaced arbitrary size changes in the same commit
(`grep -rn "text-\[\(9\|1[0-2]\)px\]" apps tests`); `test_shell_a11y.py:91` and `test_review_a11y.py:181`
keep `text-xs` and pass unchanged.
Verify: C1 `apps/common`, C10, C5, C6, C8 `tests/e2e/self/foundations.spec.ts` and goldens 01, 03, 05.

**T7. Spacing and cards (F3).** Files: styles.css (`.ui-card` 20 px below 1024 px and 24 px from
1024 px, `.ui-card-nested` 16 px, `.ui-sections` with a 32 px gap between a screen's sections), new
`apps/common/tests/test_spacing_grid.py`. Red: in the trees of `gated` screens (empty today), the
guard flags, on every spacing utility (`p`, `px`, `py`, `pt`…, `m`…, `gap`, `gap-x|y`, `space-x|y`,
`inset`, `top|right|bottom|left`, with any breakpoint or state prefix): odd integer steps (1, 3, 5, 7,
9, 11), `.5` steps, `px` spacing, and arbitrary values that are not multiples of 8 px. Steps 1 and 3
pass only inside a control (an element carrying `ui-btn`, `ui-input`, `ui-select`, `ui-chip`,
`ui-tab`, `ui-pill` or a `data-control` marker) or as the gap of an icon-and-label pair (an element
whose children are one `aria-hidden` svg and text), through an explicit allowlist in the test. Each
rule is proved on fixture strings. The `.ui-card` 20 px padding is set in CSS, not by a utility, so
the guard never sees it. The foundations spec measures 20 px on `home-thread` (a `.ui-card`; confirm,
else another card's test id) at 390 px and 24 px at 1440 px. Overrides (`p-0`, `p-3`, `p-6`, `sm:p-6`
on 27 cards) keep working outside gated trees; inside them, `p-3` goes.
Verify: C1 `apps/common`, C5, C8 `tests/e2e/self/foundations.spec.ts`.

**T8. Shared components (F4).** Files: new `templates/components/primary_action.html` (one `<a>` or
`<button>`: label, `aria-hidden` icon, `data-testid` passed in, `aria-haspopup="dialog"`,
`aria-expanded`, `aria-controls` when it opens a dialog; `.ui-fab`: on a phone fixed 16 px from the
right on `ABOVE_THE_BAR`, 56 px tall, icon and label; from 1024 px `lg:static` in the page header),
`templates/components/empty_state.html` (32 px line icon, one sentence, one tinted or secondary
button), `templates/components/inline_confirm.html` (the act's button with `aria-expanded`; a
`role="group"` region labelled by the words of what it removes or starts; Confirm and Cancel; Escape
cancels and returns focus), styles.css (`.ui-fab`; `[data-tone]` rows with a 2 px left border in the
tone's 500 step; `body.has-fab #bb-toast-host` and the error toast lifted above the button on phones,
as `has-selection` lifts them; `.ui-fab` hidden under `body.has-selection` and
`body.has-approval-selection`), `apps/approvals/templatetags/approval_extras.py` (`status_tone` from
`STATUS_META`), new `apps/studio/templatetags/studio_status.py` (`brief_status_meta`, used by
`studio/partials/status_badge.html` and a `brief_tone` filter, so briefs keep one mapping),
`docs/DESIGN_SYSTEM.md` §10–§11.
Red: new `apps/common/tests/test_components.py` (each component's markup and attributes; the button
carries `ABOVE_THE_BAR` and `lg:` placement and never `max-sm:bottom-4`; the lift and hide rules exist
in styles.css; every `data-tone` value is one of the five tones; the brief pill's output is identical,
status by status, before and after the move; a guard that no template in a `gated` screen's tree
contains `hx-confirm` or `confirm(`, D8); new `apps/common/tests/test_one_primary.py` (a counter:
`ui-btn-primary`, `.ui-fab` and solid `bg-brand-700` buttons and links outside `role="dialog"`
subtrees and `<template>`; `hidden lg:…` counts for desktop only, `lg:hidden` for phone only; each
dialog's `data-view` panel counted as its own view; proved on fixture HTML; then each `gated` screen's
pages for each of its roles, at most one per breakpoint). It also checks the place (D5): a
screen-level primary below 1024 px is the `.ui-fab` carrying the `ABOVE_THE_BAR` classes, and from
1024 px sits inside the page header's slot (`primary_action.html` renders inside an element marked
`data-primary-slot="header"`, which the page header partial provides); an item decision's primary on a
phone sits inside its `data-decision-bar`; a primary anywhere else fails, so a departure the owner
has not accepted cannot slip in.
**D5's toast rule.** D5 asks that the button and a toast never cover each other. The shell already
lifts toasts above the selection bars with a body class, so the toast rises above the button (not the
reverse), with no script measuring heights. The outcome is the one D5 requires; the S1 changelog entry
says so for the owner.
**Browser case.** Nothing floats until screen 1, so the floating-button case of
`self/phone-bar-overlap.spec.ts` is written in T21 with the first page that has the button; the F gate
records that F4's browser acceptance completes there.
Verify: C1 `apps/common apps/approvals apps/studio`, C5, C6.

**T9. Motion (F5).** Files: styles.css (`--dur-snap: 200ms`, `--dur-exit: calc(var(--dur-snap) * .7)`
(140 ms); `.motion-rise` (opacity and a 6 px rise, `--dur-snap`), `.motion-sheet-*` (below 1024 px up
from the bottom, from 1024 px in from the right, enter `--dur-snap`, leave `--dur-exit`),
`.motion-fill` (`--dur-snap`), `.motion-snap` (`--dur-snap`); `base.html:248`'s local reduced-motion
block moved in; the global rule unchanged), `docs/DESIGN_SYSTEM.md` §8 (a message arrives in 200 ms;
sheets enter in 200 ms; new motion uses `--dur-fast` or `--dur-snap` only) and §12.3 (the approve
sequence as D7 rewrites it: spinner while in flight, its 300 ms minimum kept as display time; the fill
in 200 ms; the 1.2 s reading hold; the 200 ms exit). Red: new `apps/common/tests/test_motion.py`
(the tokens and their values; every `.motion-*` class's duration is `--dur-fast` or `--dur-snap`;
no `--dur-base` or `--dur-slow` in a `gated` screen's tree; no `@keyframes` and no local reduced-motion
block in `base.html` or a `gated` screen's tree); new `tests/e2e/self/reduced-motion.spec.ts`
(`reducedMotion: 'reduce'`: opening Go to and the notifications drawer runs no transform animation or
transition longer than
0.01 ms; screens 1–3 add the sheet, a new message and the approve fill). Verify: C1 `apps/common`, C5,
C8 `tests/e2e/self/reduced-motion.spec.ts`.

**T10. Visual baselines, schemes, the clock and the browser job's time (F6).** Files:
`playwright.config.ts`
(`updateSnapshots: process.env.E2E_VISUAL === '1' && process.env.E2E_UPDATE_BASELINES === '1' ? 'all' : 'none'`,
so a local run never writes); new `tests/e2e/support/visual.ts` (`snap(target, name)`: takes a
locator (the screen's own region, the shared shell masked) or, for a whole-page state, the page; waits
with `settled` and `document.fonts.ready`, masks `[data-visual-dynamic]`, `animations: 'disabled'`,
`caret: 'hide'`, appends the scheme to the name; compares only when `E2E_VISUAL=1`, which only CI's
visual and baseline jobs set, and otherwise skips with the reason "baselines are made and compared in
CI (D9)": `CI` is not the switch, because `CLAUDE.md` documents local `CI=1` runs and a local machine's
fonts (Inter here) differ from the runner's); new `tests/e2e/support/schemes.ts` (`forSchemes(fn)`: a
`test.describe` per scheme with `test.use({ colorScheme })`, for axe and visual cases only; behavioural
flows run in light); new `tests/e2e/server/steps/visual.py` (fixture `visual_workspace`: fixed UUID
`00000000-0000-4000-8000-0000000000c1`, its own organisation "Visual Agency" (Asia/Kolkata), owner
`visual-owner@e2e.test` and editor `visual-editor@e2e.test`, three connected accounts, a brand profile,
posts at fixed times in the week of Mon 4 Jan 2027 (`?date=2027-01-04`) with `created_at`,
`finished_at` and message times set by the fixture; with the clock below frozen before that week,
nothing falls due whatever its status, so the publish loop never acts on them; each call resets its own
rows to the same state and answers the same ids; it never touches A or B;
fixture `visual_clock` (`{at}` sets, `{}` clears): freezes the e2e process's clock, patched as
`fakes.py` patches (`django.utils.timezone.now` and every module that imported `now` by name, found by
grep and listed), so request threads and the worker read the same instant, set to Sun 3 Jan 2027 09:00
in the workspace's time zone, before the fixture's week) with `tests/test_e2e_steps_visual.py`; each
visual spec sets the clock before its first page and clears it after, and calls `page.clock.setFixedTime`
with the same instant; `data-visual-dynamic` on Home's greeting and date (`templates/studio/index.html:10,
30`), on every `timesince` and printed date in a snapped tree (`studio/index.html:215`,
`thread_messages.html:37, 74, 79, 85`, the shell's relative times; each screen adds its own) and on
nothing else; new `.github/workflows/visual-baselines.yml` (its own file and concurrency group so it
never cancels CI; `workflow_dispatch` with a `specs` input, run on the branch ref with C12; also
`pull_request: types: [labeled]` for the `visual-baselines` label, which registers the workflow on its
first run, since GitHub offers a workflow for dispatch only once it has run or is on the default branch;
if dispatch is refused, re-label once; the E2E job's setup steps; the `specs` input through an
environment variable, `E2E_VISUAL=1 E2E_UPDATE_BASELINES=1 npx playwright test $SPECS`; uploads
`tests/e2e/__screenshots__/` and the WebKit type pair (T12) as the artifact `visual-baselines`, 14
days); `tests/e2e/README.md` (visual
specs; `data-visual-dynamic` as the one selector that is not a test id, for masking only; the frozen
clock; `E2E_VISUAL`; the baseline run) and `CLAUDE.md`'s browser-test section (a local `CI=1` run skips
the visual specs; they compare only in CI).
*Browser-job time.* `.github/workflows/ci.yml`: the E2E job becomes a matrix over the three projects
(`--project=<name>`), each shard with its own `DB_NAME` and `E2E_PORT` (one worker per server, as
today), and a new `visual` job runs `tests/e2e/visual` with `E2E_VISUAL=1`, so visual cases leave the
behavioural shards; the 35-minute limit is not raised without a measured reason. Each shard's and the
visual job's wall time is read from the run and recorded at every gate; each stays under 70 % of its
limit (24.5 minutes for 35), and a gate that would breach it first moves dark-scheme cases back to
axe and snaps only.
Red: `tests/test_e2e_steps_visual.py` (two calls give the same ids and row counts; A and B unchanged;
no "My Workspace"; `visual_clock` set makes `timezone.now()` in a request and in the worker return the
instant, and cleared restores the real clock); new `tests/e2e/self/visual-harness.spec.ts` (runs
everywhere: `updateSnapshots` is `none` unless both variables are set; two masked screenshots of the
visual Home two seconds apart are byte-identical; the same masked screenshots with the clock moved
90 days on are byte-identical; the masked elements exist).
First baseline: `tests/e2e/visual/shell.spec.ts` (the visual workspace's Home, light, three projects)
proves the run before any screen depends on it; it is committed at the F gate.
Verify: C1 `tests/test_e2e_steps_visual.py tests/test_e2e_server.py`, C3, C8
`tests/e2e/self/visual-harness.spec.ts`; push, run C12 `visual-baselines` on the branch, download the
artifact, commit; the next CI run shows the sharded E2E job and the visual job green, with their times.

**T11. Lighthouse per-screen targets (F6).** Files: new `tests/lighthouse/targets.mjs` (the three CI
targets moved out of `run.mjs:184-188` with their interactions from `:100-142` as they are, each `{
name, path, testId, interact(page, ctx) }`, and the registry later screens add to); `run.mjs`
(`--targets=a,b` or `LIGHTHOUSE_TARGETS`; default the three CI targets in `.lighthouserc.json`'s order;
a named target uses the same three runs, `evaluate` and budgets and writes under its own name);
`budgets.mjs` (`validateTarget`: a known name, a path in the seeded workspace, a test id, a function;
public and portal paths refused until screens 10 and 11 allow them); new
`tests/lighthouse/targets.test.mjs`; new `.github/workflows/lighthouse-targets.yml` (its own
concurrency group; `workflow_dispatch` with a `targets` input, run on the branch ref with C12, plus
`pull_request: types: [labeled]` for the `lighthouse-targets` label to register it; the Lighthouse
job's setup; the input passed through an environment variable, never interpolated into the
script (`TARGETS: ${{ inputs.targets }}`, then
`node tests/lighthouse/run.mjs --targets="$TARGETS"`); uploads
`.lighthouseci/` as an artifact). Red: the default selection equals the three configured URLs; an
unknown name and an outside path are refused; `budgets.test.mjs` passes untouched. Verify: C7; one C9
run of the default three, medians beside the Phase 2 record (`CHANGELOG.md:52-54`); one C12
`lighthouse-targets` run of the default three, whose medians match CI's Lighthouse job within its
spread.
From screen 1 on, each screen's Start task runs C9 on main for the targets it will add (median and
machine recorded in the PR), and its gate runs C9 and then C12 for the same targets (G7).

**T12. Pairs and the light diff (before T3).** Files: new `playwright.pairs.config.ts` (projects
`pair-390` (iPhone 13 at 390 × 844) and `pair-1440` (Desktop Chrome at 1440 × 900); no comparison;
output `test-results/pairs/`, which is gitignored; `reuseExistingServer: true`), new
`tests/e2e/pairs/00-shell.pair.ts` (Home, Approvals and Calendar month, light; a `before` block using
only hooks that exist on `045978b` and an `after` block), new `tests/e2e/pairs/diff.ts` and the
`package.json` scripts `pairs` and `pairs:diff` (`pairs:diff` renders a fixed list, the a11y sweep's
eleven pages and the three Lighthouse pages, at 390 and 1440 px, light, on the before and the after
server with the same seeded data, masks the elements that print times by a selector list in the
config (`time`, the greeting, the date, relative times: main has no `data-visual-dynamic`), and fails
when any pair differs by more than 0.1 % of its pixels, listing the page and the ratio). A *before*
is taken from a worktree of main: `git worktree add ../smbean-main 045978b`, then in it the same
`.venv` (`../calander-9-/.venv/bin/python`, or a fresh venv from `requirements.lock`) and the CSS
build (`(cd theme/static_src && npm ci && npm run build)`; `theme/static/css/dist/` is gitignored, so
without it the worktree serves no stylesheet), its server on its own `DB_NAME` and port, then
`E2E_PORT=<that port> PAIR_SIDE=before npm run pairs -- <file>` from this branch; an *after* from this
branch's server. Pairs go to the owner (attached to the PR and sent in the session), never into the
repository. Local pairs run Chromium with the local `system-ui` (Inter here), so they are not a
typeface sign-off (D9): the D3 type pair (a heading, body and caption sample on Home) is taken on
WebKit by the baseline workflow (T10), which uploads it, or on a real iPhone. Red: the after side
fails while an expected hook is missing and writes six images once present; `pairs:diff` fails on a
deliberately changed page and passes on two identical servers. Verify: the images exist and open;
`pairs:diff` between two main servers reports 0 differences.

**T13. Foundations gate (F7).** Run C10, C2, C3, C4, C5, C6, C7, C11; every browser spec on three
projects (C8, then CI with `CI=1`); C9 for the three CI targets with budgets unchanged. `impeccable`
audit of the shell (type, spacing, cards) at 390 and 1440 px; must-fix findings fixed.
`engineering:code-review` and `requesting-code-review` on Part A's diff. Commit the shell baseline in a
`visual:` commit. Send the shell pair (T12) and the WebKit type pair from the baseline run.
`CHANGELOG.md` entry "Phase 3 · Foundations": tested SHA, CI run, commands and results, audit findings
and fixes, Lighthouse medians (local and C12), the E2E shards' and the visual job's wall times against
their limits, `pairs:diff`'s result, the protected-test guard green, the working days used against
the estimate, the F4 note (T8), the two light movements T3 made by design on no `pairs:diff` page
(the composer's tooltip from ink-800 to the inverse surface, ink-900; the analytics drawer's
media-kind badge in `analytics/_post_detail.html` from `bg-ink-900/80` to `bg-scrim/80`, ink-950 at
80 %), and that `frontend-design` was unavailable and `impeccable`'s shape step stood in. **Stop: screen 1 starts after the owner signs off the shell pair.**

## Part B — Screen 1 · New post sheet (size L)

**T14. Start.** Load `impeccable` (and `frontend-design` if it is available by then); shape the sheet
at 390 px first (trigger above the phone bar, both modes, the idea form, a refusal), then the 480 px
drawer at 1440 px; the notes go in the PR. Take the *before* side of new
`tests/e2e/pairs/01-new-post.pair.ts` from the main worktree: Home, the New menu open (desktop; the
drawer then New on a phone), the New idea dialog, Calendar month. Screen 1 adds no Lighthouse target
(it measures through the CI Home and Calendar targets), so the before reading is T11's. Re-grep the
screen's tree for `hx-confirm`, `confirm(` and unconfirmed destructive or paid forms and update the
spec's D8 table if it finds more. Add `SCREENS["new_post"]` (templates: the sheet and its three
partials; pages `studio:index` and `calendar:calendar`; roles owner, manager, editor; `gated` false)
and its pages' `PAGE_TEMPLATES` entries.

**T15. `studio:create` answers the sheet.** Files: `apps/studio/views.py` (`create`, `:240-293`),
`apps/studio/forms.py:102` (the photo choice says "The team makes the picture"), new
`templates/studio/partials/new_post_team_error.html` (the error words only), new
`apps/studio/tests/test_new_post_sheet.py`.
Behaviour for `request.htmx` only: not configured → 400 with today's sentence ("Your team isn't
connected yet. Ask the workspace owner to finish Set up."); over budget → 400 with the sheet's own
sentence, "This month's allowance for the team is used up. An owner can raise it in Settings →
Autopilot." (`budget.over_budget_message` says "AI budget", the amount and "Agency → Autopilot"; it
stays unchanged for its other callers, and `apps/blog/tests/test_team_views.py:121` keeps passing); an
invalid form → 400 with each error in the form's words; a `ChatError` or `WorkflowError` → 400 with
its words; the idea saved but no job started (`started.job is None`, e.g. `chat.reply_refusal` at the
daily cap, `customer_workflow.py:229-231`) → 204 with `HX-Redirect` to
`chat.staff_thread_url(conversation)` and `started.note` as the message, as the non-HTMX path does
today; success → 204 with `HX-Redirect` to `chat.staff_thread_url(conversation)` and the info message
("Your idea is with your manager. What we're making appears here in a moment.", D15). The 400 body is
the sentence alone, so the form's `data-inline-error` writes exactly it. Without HTMX nothing changes,
and `test_agency_pages.py:199-212` and `test_conversation_manager.py:311-345` pass untouched.
Red (`fake_team`, `world`): HTMX success makes exactly one conversation, one message of kind `create`,
one `chat` job and no `StudioBrief`, and answers 204 with that `HX-Redirect`; each refusal before the
idea is saved (not configured, over budget, invalid form) answers 400 with its sentence and creates
nothing; with `DAILY_REPLY_CAP` reached, the answer is 204 to the idea's thread, the idea and its
conversation exist, no `chat` job exists, the message is `started.note`, and no response or message
says "is with your manager"; a viewer and a plain client get 403 with and without HTMX; anonymous gets
the login redirect; GET answers 405; no 400 body or rendered form contains `\bAI\b`, an amount or a
model or vendor name; `over_budget_message` is unchanged; the guards' order (rate limit,
`llm.is_configured`, `budget.can_spend`, then `save_idea`/`start_idea`) is unchanged.
Verify: C1 `apps/studio`, C2, C3.

**T16. The sheet and its trigger (Ask the team).** Files: new `templates/components/new_post_sheet.html`
(an overlay `fixed inset-0` holding `id="new-post-sheet" data-testid="new-post-sheet" role="dialog"
aria-modal="true" aria-labelledby="new-post-title"` with `<h2 id="new-post-title">` whose text the mode
sets ("New post", or "New idea" for the idea form; a static `aria-labelledby` because the a11y sweep
reads only static labels), `x-trap.noscroll`, a grabber and `rounded-t-2xl max-h-[92vh]` below
1024 px, a 480 px right drawer from 1024 px, the `.motion-sheet-*` classes; a segmented control
`new-post-mode-team` · `new-post-mode-self`; three panels with `data-view`; the foot links
`new-post-link-ideas` (`composer:create_landing`), `-drafts` (Calendar's Drafts tab,
`?mode=list&tab=drafts`), `-csv` (`composer:csv_upload`), and `-templates`, `-categories` with the
`templates` switch), new `templates/studio/partials/new_post_team.html` (`BriefForm` rendered: "Your
idea" `new-post-team-idea`, up to 2,000 characters; channels `new-post-team-channels` from
`studio_accounts(workspace)`; under *More*: goal, direction, photo, *Keep the brand look*; the line
"Your manager replies with what we're making. Nothing is made until you go ahead."; Send
`new-post-team-send` (the sheet's one primary); `new-post-team-error` with `role="alert"`; the form
`hx-post` to `studio:create`, `hx-swap="none"`, `data-inline-error="#new-post-team-error"` and
`hx-disabled-elt`, and no `data-no-error-toast`: `base.html:313-326` returns on that attribute before
it reads `data-inline-error`, so the refusals would show nowhere, and `data-inline-error` already
keeps the toast away when its target exists), new `static/js/new-post-sheet.js` (`newPostSheet()`: lives
in the shell's Alpine scope so `open()` sets `this.mobileMenuOpen = false;` before it opens; remembers
the opener; focuses the first field; Escape and close return focus; opens on the `new-post:open` window
event and on `#new-post`; `has-sheet` on `body` while open; what was typed survives closing), Home and
Calendar (`templates/studio/index.html` and `templates/calendar/calendar.html` include the sheet and
`primary_action` labelled **New post**, `data-testid="new-post-open"`, `aria-controls="new-post-sheet"`,
in the page header's `data-primary-slot="header"` from 1024 px; `has-fab` on `body`), the allowance line
beside *Send* ("This starts the team's work and counts toward this month's allowance.", D8's
exemption), `apps/studio/views.py` (`can_start_posts(membership)`:
`create_posts` and not `is_plain_client`; `_index_context` renders the `BriefForm` it already builds
at `:237`), `apps/calendar/views.py` (`calendar_view`: the flag and the form), the script loaded
`defer` before `js/alpine.min.js` on these two pages only (`test_page_script_budgets.py` gains that
line).
Red: new `apps/studio/tests/test_new_post_sheet_render.py`: an owner, a manager and an editor get one
trigger and one sheet on Home and Calendar with the attributes above; a viewer gets neither; a plain
client gets Calendar without them (Home stays 403); the form posts to `studio:create`, every control is
labelled, the channels equal `studio_accounts`; no sheet on Approvals, Inbox, Activity or Settings;
"Start a post" still absent from Home (`test_setup.py:411`); no `\bAI\b` and no "brief" in the sheet's
visible text; one primary per view on Home and Calendar for each role, in its place (T8's counter);
Home's query
count grows only by what the form reads. `test_a11y_sweep.py`, unedited, passes.
Verify: C1 `apps/studio apps/calendar apps/common`, C5, C6, C8 goldens 02 and 03.

**T17. Write it myself and the Calendar cells.** Files: new `templates/studio/partials/new_post_self.html`
(one sentence; **Open the editor** `new-post-self-open` → `composer:compose`, carrying only
`scheduled_date`, `scheduled_time` and `account` when the sheet was opened with them, built with
`URLSearchParams`; *Start from a template* → `composer:create_landing?tab=templates` with the switch),
`templates/calendar/partials/month_grid.html:25`, `week_grid.html:31, 46`, `day_grid.html:21, 35` (each
"+" keeps its `href`, so the composer is still reached without JavaScript, and gains
`@click.prevent="$dispatch('new-post:open', {mode: 'self', date, time, account})"` and
`aria-haspopup="dialog"`; touch and keyboard reach comes in screen 4). Red: the cell links keep today's
`href` and carry the same values in the event; the editor link's base is `composer:compose`; the
template link only with the switch. Verify: C1 `apps/calendar apps/studio`, C8 goldens 04 and 07.

**T18. Save it as an idea.** Files: new `templates/composer/partials/new_post_idea.html` (the form from
`base.html:521-731`: column, `idea-title` focused when shown, `idea-description`, media through
`composer:idea_upload_media` as asset ids, `idea-emoji-toggle|search|option` (95 options, rendered only
while open), `idea-close`; tags and the "Create new tag" dialog only with `features.templates`, through
`composer:tag_create`; `ideaChanged` fired on success; reached by `new-post-save-idea`), `new-post-sheet.js`
(gains `ideaModalHelpers` and the emoji helpers from `base.html:1291-1611`; columns and tags read from
`json_script` instead of being interpolated into JavaScript, `base.html:1392-1407`),
`apps/common/context_processors.py` (the idea column and tag queries and keys leave
`sidebar_context`), `_index_context` and `calendar_view` (those two queries, only when
`can_start_posts`), `tests/lighthouse/emoji-init.test.mjs` (reads `static/js/new-post-sheet.js`; same
cases). Red: the sheet's idea form creates an idea in the chosen column (`test_idea_media_flows.py`
stays green); with `templates` off Home has no tag control and no `tag_create` URL, with it on it has
both; a column named with a quote renders safely; `sidebar_context` reads two fewer queries
(`test_navigation_and_guards.py:100`'s bound goes from 6 to 4, its comment updated). Verify: C1
`apps/composer apps/common apps/studio`, C7.

**T19. The New menu leaves the shell.** Files: `templates/base.html` (the menu, the idea and tag
dialogs and their scripts go; `x-ref="wsBtn"`, the bell and Go to stay),
`templates/telegram/settings.html:4`
(drops `.sidebar-new-wrap`). The tests that pin the menu move in the same commit, red first against the
new markup, each behaviour kept (D11):

- `apps/common/tests/test_shell_a11y.py` — `:61-67` (drawer closes before the dialog opens; first field
  focused) → the same order in `newPostSheet().open`; `:69-78` (Escape returns focus to `newBtn`) →
  Escape returns focus to the opener; `:80-88` (idea field focus CSS) → the same rule for the sheet's
  idea fields; `:103-125` (menu labels, "New idea" h2) → the foot link labels "Ideas", "Drafts",
  "Import from CSV" and the idea form's "New idea" heading.
- `apps/common/tests/test_navigation_render.py` — `_new_menu` (`:181-183`) → `_sheet(html)` cut at
  `data-testid="new-post-sheet"`; `:351-374` → the foot links on Home and Calendar, templates and
  categories only with the switch; `:384` (bell before New) → bell before the first place; a new guard:
  no template contains `sidebar-new-`.
- `apps/studio/tests/test_setup.py:410-414` (an ordinary `TestHome` test) → the sheet's URLs on Home;
  "Start a post" still absent. The three protected tests in the same file are not touched, and
  `tests/test_protected_tests.py` proves it.
- `apps/composer/tests/test_channelless_drafts.py:183-191` → the composer and Ideas page light nothing
  and carry neither the menu nor the sheet.
- `tests/e2e/self/emoji-picker.spec.ts` → `new-post-open`, `new-post-save-idea`, the "New idea" dialog,
  95 options only while open; `tests/e2e/self/phone-menu-focus.spec.ts` → with the drawer open, the
  sheet opened by `new-post:open` (the route `#new-post` takes) closes the drawer and focuses its field.
- No golden spec uses the menu (`grep -rn sidebar-new tests/e2e/golden` is empty).

Verify: C1 `apps/common apps/studio apps/composer`, `test_a11y_sweep.py` unedited and green (the shell's
two dialogs on every swept page plus the sheet keep the count above ten), C8 `tests/e2e/self`
(emoji-picker, phone-menu-focus, session) and `tests/e2e/screens/navigation.spec.ts`.

**T20. Keyboard (D16, the parts screen 1 needs).** Files: new `static/js/shortcuts.js` (deferred on
workspace pages: `n` opens the sheet where the trigger is and otherwise goes to Home's `#new-post` for
someone who may start posts; `/` opens Go to; `?` opens the list; ignored in a text field, select or
editable region, with a modifier other than Shift for `?`, while a dialog is open, below 1024 px, and
when single keys are off (`localStorage.shortcuts = 'off'`)), `templates/base.html` (the list dialog:
`role="dialog" aria-modal="true" aria-labelledby`, `x-trap.noscroll`, `data-testid="shortcuts-dialog"`,
the switch "Single-key shortcuts" (`role="switch"`, `data-testid="shortcuts-toggle"`); Go to's open
handler returns early while the sheet is open, every string `test_navigation_render` pins kept).
Red: new `tests/js/shortcuts.test.cjs` (each ignored case; the three keys; the switch); new
`tests/e2e/self/shortcuts.spec.ts` (`desktop-chrome` only, said in the title: phones have no keys): `n`
on Home opens the sheet with focus in its field and Escape returns focus; `n` on Approvals reaches Home
with the sheet open; "n" typed in the thread composer is just a letter; `?` lists the keys; switched
off, `n` does nothing, still after a reload; `/` opens Go to; Ctrl-K inside the sheet does nothing;
axe on the list in both schemes. Verify: C7, C8 `tests/e2e/self/shortcuts.spec.ts`.

**T21. The screen's browser specs.** Files: new `tests/e2e/screens/new-post.spec.ts` (three projects;
the behavioural cases in light, the axe cases in both schemes through `forSchemes`, D10);
`tests/e2e/server/steps/p3.py` (fixture `workspace_over_budget`,
a test-made workspace whose month is spent, refusing A and B; probe `new_post_outcome`
(`?workspace_id&since=`: conversations, messages by kind, chat jobs, briefs, ideas, tags)) and
`tests/test_e2e_steps_p3.py`; `tests/e2e/self/phone-bar-overlap.spec.ts` (the floating-button case: on
Home and Calendar `new-post-open` ends above the phone bar on phones and sits in the header on desktop;
an error toast and an approval toast ride above it; with posts selected in Calendar's list it is
hidden); `tests/e2e/self/reduced-motion.spec.ts` (the sheet appears without a transform under reduce).
Cases: one tap opens the sheet on a phone from Home and from Calendar, focus in `new-post-team-idea`;
*Ask the team* lands on the idea's thread and the probe shows one conversation, one `create` message,
one chat job and no brief; over budget, the sheet's own sentence ("This month's allowance for the team
is used up. …") shows in `new-post-team-error`, no toast shows, nothing is made, the text is still
there; closing and reopening keeps the text; an editor sees the trigger, a viewer and
a plain client do not, and the client's direct POST to `…/studio/new/` answers 403; *Write it myself*
opens `/compose/` (200, `compose-caption` visible); from a week cell on desktop the sheet opens in
*Write it myself* and the editor link carries that cell's date and time (phones get the cell control in
screen 4); *Save it as an idea* shows the dialog named "New idea", saves, and the probe shows the idea,
and with `templates` off (`workspace_switches`) there is no tag control; the foot links reach their
pages; axe with the sheet closed and open in each mode. Goldens 02, 03, 04 and 07 stay unedited and
green. Verify: C1 `tests/test_e2e_steps_p3.py`; C8 the four specs on three projects, twice; CI.

**T22. Home and Calendar declared dark-ready.** Files: `apps/common/screens.py` (`DARK_READY` gains
`("studio", "index")` and `("calendar", "calendar")`); the raw colours recolor then reports in their
trees — today `calendar/partials/_publish_filter_styles.html` (15), `base.html` (12, less what T4
moved), `calendar/partials/event_form.html` (9), `calendar/calendar.html` (4),
`approvals/partials/_toasts.html` (4), `calendar/partials/publish_queue.html` (1),
`approvals/partials/_approval_row.html` (1): the list tabs and the event form render inside Calendar,
so they are in its tree; then every dark axe finding. Red: C6 fails once the pages are declared; new
`tests/e2e/screens/dark-shell.spec.ts` (dark, three projects: Home with waiting items, a brief card and
a receipt (the `team_workspace`/`home_request` fixtures), Calendar month, week, day, its four list tabs,
the event form, and posts selected in each selection bar (`calendar-bulk-bar` in the calendar view and
`approvals-bulk-bar` in the Approvals list tab): axe 0 serious, the canvas is the dark `ink-50`, each
bar's computed background is the inverse surface (still dark) and its labels and divider stay visible)
fails before. Approvals
(`/approvals/`) shares the list partial but stays light until screen 3. Verify: C6, C8 dark-shell and
new-post on three projects.

**T23. Lighthouse.** Files: `tests/lighthouse/targets.mjs` (Home: the thread typing as today, then
`new-post-open`, typing in `new-post-team-idea`, `new-post-save-idea`, the emoji picker's first
opening, a search, a choice and `idea-close`; Calendar: the timezone filter and mode switch as today,
then the same sheet sequence; Approvals: the timezone filter and details only, since it has no
trigger), `run.mjs` (`:134-142` removed). Red: `targets.test.mjs` (Home and Calendar open
`new-post-sheet`; Approvals touches neither `new-post-*` nor `sidebar-new-*`). Run C9 three times;
medians into the changelog; budgets as configured. Watch Home's CLS (0.078 on `ff90678`): the button is
fixed on a phone and the sheet is `x-cloak`ed, so neither shifts layout. Verify: C7, C9, the Lighthouse
CI job.

**T24. Baselines.** File: new `tests/e2e/visual/new-post.spec.ts` (the visual workspace and its frozen
clock; Home at rest with the trigger, the sheet in *Ask the team*, in *Write it myself*, the idea form,
each snapped as the sheet's region where it can, the shell masked; both schemes; three projects;
reduced motion; masks). This screen also changes what `tests/e2e/visual/shell.spec.ts` shows (the New
menu leaves the sidebar, the floating button arrives on Home), so its files are refreshed in the same
run. Push, run C12 `visual-baselines` on the branch for both specs (re-label only if dispatch is
refused), download the artifact, copy both specs' files into `tests/e2e/__screenshots__/visual/`, and
commit them alone as `visual: new post sheet baselines (screen 1), shell refreshed`, with the shell's
before/after pair attached. Verify: the visual job compares and passes on that commit.

**T25. Audits, docs and the gate.** `impeccable` audit and `design-is` audit of the trigger, both
modes and the idea form at 390 and 1440 px in both schemes; each must-fix finding fixed with its failing
test first where it changes markup or behaviour. Docs: `docs/DESIGN_SYSTEM.md` §10.9 (sheet and drawer)
and §11 (the trigger, no New menu); `docs/PRODUCT_MAP.md` (the sheet on Home and Calendar; Home's typing
posts to `studio:thread_start`, the sheet's *Ask the team* to `studio:create`); `CLAUDE.md` (New post,
the shortcuts); `tests/e2e/README.md` (new hooks; `sidebar-new-*` retired). Set
`SCREENS["new_post"].gated = True` (the spacing and one-primary guards now cover it; fix anything they
find). Run gate G 1–12. Take the *after* pair (both schemes). `CHANGELOG.md` entry "Phase 3 · Screen 1 —
New post sheet": SHA, CI run, commands and results, audit findings and fixes, Lighthouse medians
(local and C12), the E2E shards' and the visual job's wall times, the working days used against the
estimate, the D5 toast note, F4's browser case done. **Stop: screen 2 starts only after the owner's
sign-off on this
pair is recorded.**

## Part C — Screens 2–11 (outlines, expanded after each sign-off)

Each outline becomes tasks shaped like Part B: start (shape at 390 px, *before* pair, registry entry
and `PAGE_TEMPLATES`, C9 on main for the screen's new Lighthouse targets with the median and machine
recorded, a re-grep of the tree for `hx-confirm`, `confirm(` and unconfirmed destructive or paid
forms), server changes red first, markup and moved tests, browser specs (behaviour in light, axe and
snaps in both schemes, `expectReadSize` on the named running text), dark readiness (previews stay white
in dark), Lighthouse (C9, then C12), baselines in a `visual:` commit that also refreshes any earlier
screen's files whose pages this screen changed, audits, docs, gate G with the days used, **stop**.

**S2 · Home (M).** *Goal:* greeting and one status line, **New post** as the primary, Today first on a
phone when something waits (one line otherwise), the thread as a chat (composer sticky at the bottom
of its card on a phone, the floating button hidden while the composer is on screen, messages grouped
under one avatar, a new message rising in 200 ms, "The team is working" while a job runs, cards
inline), *Send* and *Go ahead* tinted with D8's allowance line (no confirm until the owner answers),
the agency tabs gone, the body token on running text (`thread_messages.html`'s `text-body-lg` and
`thread_draft.html`'s `text-sm` move to it), "Nothing yet" with a sentence and a button that opens
the sheet; the thread's and `customer_workflow.py:246`'s "brief" copy per D15. *Risks:* CLS 0.078
against 0.1 (the sticky composer reserves its height); the thread's JavaScript contract
(`static/js/agency-thread.js`, `tests/js/agency_thread_state.test.cjs`) and every `data-thread-*`
attribute; the 3 s and 30 s polls only while visible. *Keep:* the "Today" region, `home-today*`,
`home-thread`, `thread-composer-body|send`, `thread-message-<id>`, `thread-brief-*`; `studio:approve`
with `mode=proposed` for `approve_posts` only; the section order anchors; invariant 4, with
`TestToday::test_private_telegram_jobs_stay_out_of_the_card` unedited. *Moves:* `test_setup.py`
(TestHome, TestToday's class strings; not the protected test), `test_thread_creative_ui.py`,
`test_live.py` (strip), `test_chat.py` copy that says "brief". *New:* `screens/home.spec.ts`
(`expectReadSize` on a thread message body, a draft's caption and a Today row title), the new message
case in `self/reduced-motion`, `visual/home.spec.ts`; the refresh of `visual/new-post.spec.ts`'s Home
states in the same `visual:` commit. *Pair:* waiting items; nothing waiting; a brief card. Lighthouse:
the CI Home target.

**S3 · Approvals (L).** *Goal:* below 1024 px the same `approvals-list` as a horizontal scroll-snap
stack (one card per width, a real-size preview edge to edge, *Approve & schedule* and *Request changes*
in a bottom bar, "3 of 7", Previous and Next); each card's bar inside its own `approvals-row-<id>`,
keeping the row-scoped ids (`approvals-row-approve-schedule` and the rest, no post id), only the card in
view interactive (the others `inert`), no shared bar outside the rows; from 1024 px a restyled list
with status borders and `a`/`r` (added to `shortcuts.js` and the list dialog: the same POST as a click,
one post) with D16's guards (`a` only where *Approve & schedule* is present; `event.repeat` ignored;
disarmed after an approve until the person moves focus; after the reload focus on the list heading,
never the next row; `r` opens the form and never sends); new `components/post_preview.html`
(Instagram 1:1 and 4:5, LinkedIn, Facebook, X, in the platform's light look in both themes, inside
`data-theme-scope="light"`); the approve fill with the four outcomes and refusals of D13's table, the
words and the time built in `apps/approvals/views.py` from the row after `approve` returns, in the
workspace's time zone or the list's `tz` filter (sent with the POST), never in the browser; the plain
client's restriction (below); bulk reject as an inline confirm; the bulk bar inverse in both themes;
the empty state's button; `approvals:index` dark-ready. *Server, red first:* one pytest per outcome
(two-stage with and without a stamped time, scheduled, no future time, plain with and without a stamped
time, each refusal) pinning the fill words and the time zone; a plain client POSTs `schedule=1` on a
`pending_client` post in an enforced two-stage workspace and the post ends `approved`, not `scheduled`
(`approvals:approve` ignores `schedule=1` from anyone who is not `is_internal_approver`; `calendar_view`
passes a flag so `_approval_row.html` offers a plain client only *Approve*). *Risks:* goldens 05, 05-06
and 06 click rows on phones (rows stay in the DOM; Playwright scrolls them in; the buttons stay inside
the rows); a scroll must never send a POST (asserted); `test_index`'s equal row hooks between the page
and Calendar's tab; the reload that replaces `approvals-list`; the bulk modal's removal keeps the a11y
sweep above ten dialogs (the shell's own carry it). *Keep:* `schedule=1` on *Approve & schedule* for an
internal approver, plain *Approve* never schedules, `gate.enforced` with `is_internal_approver`, the
204, every `approvals-*` id, viewer and editor control rules, client 403 on `/approvals/`, status words
through the status partials, the out-of-band tab counts. *Moves:* `apps/approvals/tests/test_index.py`
markup, `test_review_a11y.py` (`aria-label="Select post"`, `data-select-spacer`),
`test_status_words.py`, `_toasts.html` script strings, the Approvals cases of `self/phone-bar-overlap`.
*New:* `screens/approvals-stack.spec.ts` (each card's buttons are descendants of its row; only the card
in view is interactive; a preview's computed background is white in dark), `tests/js/shortcuts.test.cjs`
cases for `a` (repeat ignored, disarmed after an approve, nothing on a row without *Approve &
schedule*), a `self/shortcuts.spec.ts` case (after `a` and the reload, focus is on the list heading and
a second `a` does nothing), the fill case in `self/reduced-motion`, `visual/approvals.spec.ts`. *Pair:*
the stack on a phone, the list on desktop, a card after *Approve & schedule*, the request-changes form,
empty. Lighthouse: the CI Approvals target with its timezone and details interaction.

**S4 · Calendar (L).** *Goal:* heading "Calendar"; agenda below 1024 px and week from 1024 px when no
`view=` is given (the server renders the agenda and a desktop fetches the week through the existing
shell refresh when the 1024 px query matches; an explicit `view=` always wins); *Add a post* per day and
grid "+" on focus and touch, both opening the sheet with that time; drag snaps and shows the new time,
then the server's; status borders in the list tabs; the header's links go: Drafts is the list tab,
Posting schedule and Media library move to an overflow menu keeping `calendar-link-*`; the confirm
modals, the bulk delete and the event delete (`event_form.html:71`, `confirm()`) become inline
confirms; local styles and keyframes into styles.css. *Owner, at Start:* CI's Calendar URL moves to
`/calendar/` or `/calendar/` is added as a fourth CI URL (D10); `.lighthouserc.json` changes only on the
answer. *Risks:* golden 07's real drag and `rescheduleChip`; `self/calendar-keyboard` (issue #21);
desktop flash when the week replaces the agenda (reserve height; measure CLS with a desktop run);
SortableJS only where it loads today. *Keep:* dropping a draft or failed chip (an implicit schedule)
needs `publish_directly` (`_IMPLICIT_SCHEDULE_STATUSES`, `apps/calendar/views.py:58`, `:1210-1215`);
moving a scheduled post needs edit rights (own post or `edit_others_posts`), and the gate withdraws
its approval unless an internal approver moves it, whose drag approves the new time (golden 07; no new
permission check and no hidden drag handles for editors); `calendar:calendar` and
`?mode=list&tab=approvals`; `calendar-shell` with `rescheduleChip`, `calendar-week-grid`,
`calendar-week-cell-*`, `calendar-chip-*`, `calendar-select-*`, `calendar-bulk-bar`,
`calendar-mode-*`, `ui-select-calendarFilters.*`, `publish-tab-*`; the "Calendar week" region; a client's
`/` and the X callback land on `/calendar/`. *Moves:* the `<h1 …>Publish</h1>` pins;
`test_setup.py:417` (an ordinary test) and `test_navigation_and_guards.py:102-130` (Drafts becomes the
list tab; Posting schedule and Media stay linked from the overflow menu); `test_review_a11y.py`'s phone
chip CSS. *New:* `screens/calendar.spec.ts`, the snap case in `self/reduced-motion`, Lighthouse target
`calendar-agenda` (`/calendar/` without `view`, read on main at Start and run with C12 before the gate),
`visual/calendar.spec.ts`. *Pair:* agenda on a phone, week on desktop, a chip mid-drag, the list tabs.

**S5 · Post page and composer (L).** *Goal:* each destination in `post_preview` (light in dark,
asserted); the phone decision bar with *Approve & schedule* on the right and the fill; breadcrumb Home;
"what we're making"; *Stop and discard* and *Discard* (`studio/detail.html:33, 56, 357`, no confirm
today), *Retry* (`:51`), choosing an angle (`:175`) and *Start over with three new angles* (`:343`) as
inline confirms (D8); *Request changes* (`studio-revise-send`, golden 06) with the allowance line until
the owner answers; the composer's header, action bar at 390 px and preview drawer restyled, with one
primary: the act `save_post` will honour for this person (*Submit for approval* when a schedule would
be converted, otherwise the publish button and its modes), chosen from the flags the view already
computes (`apps/composer/views.py:744-778`); the composer's previews (`preview_panel.html`) inside the
light scope; `compose.html`'s keyframes and reduced-motion block into styles.css; `studio:detail`,
`composer:compose`, `compose_edit` dark-ready. *Risks:* `compose.html` is 3,175 lines with 60,984
characters of inline script (16.8 KB gzip), so the `composer` target's reading on main at Start decides
whether ≥ 90 is reachable before the work; `save_post` must not change. *Keep:*
`studio/services.approve` as the one place a brief's time becomes a schedule, `mode=proposed`; the post
page's *Request changes* passes the staff member's words as the team's own feedback (no
`requested_by`), while client and thread words stay wrapped by `untrusted()` (invariant 5);
`studio-detail-revision` ("Revision N"), `-notes`, `-progress`, `studio-revise-form` ("What should
change?"), `studio-revise-send`, `data-decision-bar`, no phone bar on either page; golden 04's ids and
behaviour; `gate.check_write`/`_clear` withdrawing approval; `live_verify`'s 200. *Moves:*
`test_compose_layout.py`, `test_readonly_composer.py`, `test_account_pills.py`, `test_review_a11y.py`'s
composer strings, `test_preview.py`, `test_two_stage_send_back.py` markup. *New:*
`screens/post-page.spec.ts`, Lighthouse targets `post-page` and `composer`, `visual/post-page.spec.ts`.
*Pair:* waiting for approval, the team at work, *Revision 2*, the composer at 390 px.

**S6 · Inbox (M).** *Goal:* the open conversation as a chat (theirs left, ours right, internal notes
dashed with a lock), the reply composer at the bottom with *Send reply* as the primary; status borders
(waiting: warning; replied or resolved: success; failed: danger) from one inbox status-to-tone mapping;
sentiment and the SLA countdown only with their filter; *Draft replies with the team* as an inline
confirm that says what starts and that it counts toward the monthly allowance (rate limit unchanged),
its results labelled as drafts a person reads and sends; discarding a draft reply
(`_draft_reply_item.html:40`, `hx-confirm`) as an inline confirm; `feed.html`'s keyframes into
styles.css. *Keep:* every `inbox-*` id golden 09 uses; no `role="button"` or `tabindex` on the row, the
stretched button's label; nothing sent without a press; client 403 on every Inbox URL; "Reply not
sent", "Reconnect the account", "does not support replies". *Moves:* `test_draft_reply_views.py`
markup, `test_review_a11y.py` ("Posts on"). *New:* `screens/inbox.spec.ts` (`expectReadSize` on the
open message), Lighthouse target `inbox`, `visual/inbox.spec.ts`. *Pair:* the list, an open
conversation, a failed reply.

**S7 · Analytics (M).** *Goal:* the four cards the page computes (`services.hero_cards` and the
engagement card), one trend, the posts table as list rows below 640 px, chart colours and 13 px chart
text from T4, the empty state's *Create a post* to Home's `#new-post`; no primary except *Reconnect*
(the owner question of D5). *Keep:* platform numbers; *Reconnect* posting `social_accounts:reconnect`;
the drawer as a trapped dialog; `chart.umd` only on `analytics:account`; the chart initialiser in
`base.html`. *New:* fixture `analytics_account` (a test-made workspace with metrics),
`screens/analytics.spec.ts`, Lighthouse target `analytics` on the account page (the index redirects,
which the runner refuses), `visual/analytics.spec.ts`. *Moves:* `test_review_a11y.py`'s drawer strings
if the markup moves; `apps/analytics/tests/test_views.py` copy. *Pair:* with data, empty, needs
reconnecting.

**S8 · Activity (M).** *Goal:* the board, the job timeline (`studio:job`) and the routines restyled,
status borders on job rows, the agency tabs gone, "Your team" kept, no primary (the owner question of
D5), the presets as the empty state's action; deleting a routine (`routine_rows.html:47`, `confirm()`),
*Run now* (`:36-39`) and a job's retry and resume as inline confirms (D8). *Keep:* the board polls
only while visible and announces only meaningful changes (`team-live-announce`, polite, before
`#routines`); routines for `create_posts`; job controls under the job lock with current authority;
`studio:job`; `activity-board`, `activity-routines`, `routine-preset-*`; the exact strings
`test_activity.py` and `test_live.py` pin (`id="team-board" data-live-board data-no-error-toast`, the
5 s trigger, the out-of-band `team-status`); the words the board must never contain. *New:* dark cases
in `screens/activity.spec.ts`, Lighthouse target `activity`, `visual/activity.spec.ts`. *Pair:* the
team at work, idle, a job page.

**S9 · Settings, the onboarding wizard and Go to search (L + M).** *Goal:* the tabs as a rail from
1024 px and the strip below; one primary per panel (each form's Save at the end of its form, D5's owner
question; Advanced: Health's first unfinished step); the danger zone as an inline confirm keeping the
typed confirmation; Team & clients' `hx-confirm` dialogs (`members/partials/member_row.html:75`,
`invitation_row.html:35`, `client_portal/admin/partials/pending_invites_section.html:38`,
`client_portal/admin/partials/client_row.html:39, 49`) as inline confirms; **Advanced → Features** for
owners: a POST to the existing `settings:index` (no new URL; the view gains a POST branch for
`action=features`, owner check, `select_for_update`, `update_fields=["features"]`), five switches each
with one sentence; the autopilot form's save stops writing `features` (today `form.save()` in
`views_autopilot.py:168` writes every column), with the test that saving it a moment later does not
undo a switch; **the wizard** (D14) in Home's onboarding card for an owner or manager: brand → connect
one account → choose who approves → first post, states read like Set up's rows; by default each step
an existing handler and a toast on Calendar after the provider callback linking back; if the owner
asks for the in-place flow, the brand and approver steps render in the card, the callback returns to
Home, and golden 02 is rewritten with the owner's leave; **Go to search** (D17): a fragment URL
(through D12: `PRODUCT_MAP.md` line, `tests/fixtures/product_map_urls.txt` line, refuses like its
pages, golden 11 sweeps it), `@ratelimit`, reads through the workspace-scoped managers, posts the
person may open, portal clients only for someone who may manage clients, actions, never a private
Telegram conversation, nothing a plain client may not see, an answer under 200 ms on the seeded
workspace; the palette debounces and keeps the Phase 2 list first. *Keep:* each tab's permission check
and 403; old pages' 301 after their checks and their
POSTs; `next` through `settings_links.returning_to`; `require_dashboard_approval`; Health's names for
owners only, with `TestSetupPage::test_owners_see_the_exact_names_and_others_are_told_to_ask` unedited;
the readiness invariant test; the brand colour inputs exactly the form's widget; `settings-tab-*`,
`settings-panel-*`, `brand-*`, `setup-row-*`, `setup-action-*`, `connect-*`, `org-settings-timezone*`;
golden 01 lands on Home's "Today", golden 02 keeps passing on today's pages unless the owner allows
its rewrite; `telegram:settings` untouched; Go to's Phase 2 list and `test_navigation_render`'s pinned
strings. *Moves:* `test_settings_tabs.py`, `test_settings_screen.py`, `test_setup.py`'s eleven-row
regex and copy if the card changes (not its protected tests), `test_brand_page_hooks.py`. *New:*
`screens/onboarding.spec.ts`, `screens/go-to.spec.ts` (a post, a client and a setting found; workspace
B's rows refused; a viewer sees no clients; axe in both schemes), the search endpoint's pytest
(isolation, private Telegram rows absent, plain client limits, rate limit), Settings dark cases,
Lighthouse target `settings`, `visual/settings.spec.ts`. *Pair:* Brand on a phone, Advanced with
Features, each wizard step, Go to with results.

**S10 · Client portal (L).** *Goal:* three parts and nothing else: Waiting (the D13 stack with the
portal's own cards and endpoints; one solid *Approve* per card in view), Live (a grid), Chat (Talk to
the team); the header with logo, name and the three parts as tabs; today's Home, Reports, Activity and
Telegram tabs (`portal_base.html:47-57`) leave the navigation; `client_portal:dashboard` (`/portal/`)
renders Waiting with its tab lit (no summary of its own); Reports and Activity keep rendering at their
URLs with no link; the client's Telegram pairing reached by one line inside Chat; the Chat tab's unread
count only through `chat.portal_unread_total` and `chat.recent_messages(..., for_client=True)` on
`audience=CLIENT` conversations; the portal's accent from `BrandProfile.primary_color` through a new
guard built to `DESIGN_SYSTEM.md` §22 with T2's contrast method (700 step darkened until white on it is
≥ 4.5:1; 600 step ≥ 3:1 on white, ink-50 and ink-100; the dark theme's fill and link steps checked),
falling back to Pine when the guard refuses, no opt-in; body 16/26; `portal_base.html` dark-ready;
`DESIGN_SYSTEM.md` §15 updated (three parts, the colour and its guard). *Server, red first:* the guard
(the default `#081D4A`, a pale colour refused with Pine shown, a dark colour accepted; both themes);
an internal note and a private conversation's message never appear on `/portal/`, Waiting, Live or the
unread count; the three tabs and no others for a client. *Keep:* every `client_portal:*` URL; external
comments only; no internal notes in client threads; a client's sign-off completes the client stage
only and says "Your agency team schedules it next."; the magic-link GET never consumes the link; the
client's Telegram pairing; the Focus plugin before Alpine in `portal_base.html`; `portal-continue`,
`portal-nav-approvals` (two copies, one visible), `portal-approvals-pending|decided`, `portal-card-*`;
golden 08 (lands on `/portal/`, then `portal-nav-approvals` to `/portal/approvals/`) and golden 11's
portal sweep; no gesture approves. *Moves:* `apps/client_portal/tests.py` markup,
`test_portal_team.py` strings. *New:* `screens/portal.spec.ts` (`expectReadSize` on a card caption at
16 px both widths, the portal's 16/26), the guard's pytest; the Lighthouse runner gains a portal
session (the `magic_link` fixture) and `/portal/` paths in `validateTarget`, target `portal-waiting`;
`visual/portal.spec.ts`. *Pair:* Waiting on a phone, Live, Chat, each with the default colour and a
workspace colour.

**S11 · Marketing (L).** *Goal:* Home with a dark hero (ink-950), one line of promise, an animated
screen built from real UI (not the LCP element; a still under reduced motion), three outcomes with
numbers the owner supplies or that can be checked, the invite form inline posting to
`marketing:request_invite`; the network strip, the feature cards and the scheduler copy gone; How it
works drawn as one flow; Request invite restyled; dark `--mk-*` values (the public site follows the
device only) checked by `tools/contrast.py`; `marketing.css`'s sub-13 px rules fixed and its allowlist
in `test_type_floor.py` removed; *Source code* stays a footer text link; `DESIGN_SYSTEM.md` §17
rewritten (dark hero, no feature grid, no pricing cards, Request invite instead of "Get started").
*Keep:* CSRF, the honeypot (`data-testid="request-invite-honeypot" hidden`), the per-address limit,
the site-wide cap, one notification per operator; robots.txt, the sitemap, Privacy and Terms; the
header and footer link set; `marketing-nav-*`, `request-invite-*`; hidden pages unlinked and `noindex`;
no vendor names; the orange check on marketing screenshots. *Moves:* `apps/marketing/tests/test_pages.py`,
`test_request_invite.py`, `apps/common/tests/test_seo.py`, `test_pricing.py`,
`test_marketing_screenshots.py` (re-captured images). *New:* `screens/marketing.spec.ts` dark cases;
public Lighthouse targets (`/`, `/how-it-works/`, `/request-invite/`) allowed in `validateTarget`;
`visual/marketing.spec.ts`. *Pair:* Home, How it works, Request invite, each at 390 and 1440 px.

**R3 · Dark for the remaining pages (M; default, subject to the owner's answer).** After screen 11:
the pages a beta member reaches that the eleven screens did not rebuild (sign-in and account pages,
media library, posting schedule, Ideas and Drafts, notifications, Telegram settings, Set up), each
added to `PAGE_TEMPLATES`, run through C6's raw-colour rule, and given a dark axe case on three
devices in a new `screens/dark-remaining.spec.ts`; each that passes joins `DARK_READY`; any that fails
stays light and is listed in `CHANGELOG.md` for the owner. If the owner answers no, R3 is skipped; if
the owner moves it to Phase 4, it is recorded there.

**Phase gate (R1, R2).** All eleven screens and F signed off, and R3 done or answered;
`docs/DESIGN_SYSTEM.md` (§5, §8, §10–§11, §12.3, §15, §17, §21 dark mode), `docs/PRODUCT_MAP.md`,
`CLAUDE.md` (including the browser-test section's `E2E_VISUAL`) and `tests/e2e/README.md` current;
C10 green with `tests/test_protected_tests.py` green; CI green on the final commit, with the E2E
shards and the visual job under 70 % of their limits; one complete local browser run; TOTP still
pending and reported apart; the tested SHA and CI run in `CHANGELOG.md`; stop for the owner. The spec
estimates about 19–24 working days against ten. Each gate records the days used; when the estimate is
exceeded, **stop**: the owner chooses what moves out. Nothing the owner asked for (the portal's Live
grid and colour, the marketing animation, Go to search, R3) leaves P0 unless the owner releases it.

## Verification checklist (each task)

- [ ] The red test was seen failing for the stated reason before the change.
- [ ] `tests/test_protected_tests.py` is green (no protected invariant test changed), and `git diff`
      touches no golden spec and none of `gate.py`, `actor.py`, `publisher/engine.py`,
      `services.approve`.
- [ ] Every moved pytest assertion has a replacement that protects the same behaviour (D11).
- [ ] No new URL path part; any new URL went through D12 (PRODUCT_MAP line, fixture line, refuses like
      its page; golden 11 sweeps it).
- [ ] The touched apps' pytest, C2 and C3 pass; C5 builds; C6 is clean.
- [ ] Any inline script carries the nonce; any copy follows `CLAUDE.md`'s naming rules (no "AI", no
      model, vendor or worker names); no `hx-confirm` or `confirm()` added.

## Order and parallelism

T1 → T2 → T12 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10 → T13 **stop**. T12 comes before T3 because
T3's acceptance is T12's `pairs:diff`. T11 touches only `tests/lighthouse/`, its workflow and
`package.json`, and can run beside T4–T9 in a separate worktree with its own `DB_NAME` and port.
Everything else in Part A edits styles.css, `base.html`, `ci.yml` or `playwright.config.ts` and runs
alone, in order. Part B: T14 → T15 → T16 → (T17 ∥ T18: cells and calendar partials against the idea
form and context processor) → T19 → T20 → T21 → T22 → T23 → T24 → T25 **stop**. Part C runs one screen
at a time, each expanded here first and each closed by its sign-off; R3 follows S11.
