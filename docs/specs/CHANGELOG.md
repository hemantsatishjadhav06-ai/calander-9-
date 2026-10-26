# Beta changelog

One entry per phase of [`docs/BETA_PLAN.md`](../BETA_PLAN.md): the date, what changed, and what the
phase gate (section 6) said. Newest first.

## In progress — Phase 1: the test harness

**Changed** (so far; the gate is recorded when the phase closes)

- Dependencies: Pillow's range moves to `>=13.0,<14.0`, and `requirements.lock` now pins Pillow
  13.0.0 and certifi 2026.10.23. That clears the 38 known vulnerabilities `pip-audit` found in the
  lock: 37 in Pillow 12.3.0 and one in certifi 2026.7.22 (PYSEC-2026-4320). Pillow 13.0.0 is eight
  days old; it is taken anyway because it is the only fixed version and several of the bugs are
  memory corruption in parsers that read uploaded files. No other pin, hash or annotation changed.
- The lock's header command no longer has `--no-index`. In pip-tools 7.6.2 that flag means "ignore
  the package index", so the recorded command could not resolve anything (it stops at
  `No matching distribution found for Django`); the new header command, run again, writes the
  committed lock byte for byte. The lock is still written without an index URL
  (`--no-emit-index-url`). This is the only line outside the Pillow and certifi blocks that
  differs.
- CI: a new **Dependency audit** job (`pip-audit` 2.10.1 on the hashed lock, nothing installed;
  `npm audit --audit-level=high` in the repository root and in `theme/static_src`), and
  `compilemessages` in the **Test (pytest)** job after `gettext` is installed.
- `LOCALE_PATHS = [BASE_DIR / "locale"]`, with `locale/.gitkeep` keeping the directory: Django reads
  the project's own catalogues (outside any app) only from `LOCALE_PATHS`.
- **The e2e server** (`python -m tests.e2e.server`, `config/settings/e2e.py`): the web app and the
  worker in one process on `127.0.0.1`, its own database (the name must end in `_e2e`; the server
  refuses any database host or libpq variable that is not this machine), the suite's `FakeTeam` and a
  rule-based account manager, an `httpx` mock transport for the few platform calls the paths make, a
  socket guard that refuses and records every other connection, a fixed seed (workspace A
  `…000a` with owner, manager, editor and client; workspace B `…000b` in another organisation),
  and named, typed fixtures and probes in `tests/e2e/server/steps/`. No endpoint runs code from a
  request; they answer loopback, same-origin, JSON only, and only under `config.settings.e2e`
  (`config/urls.py` never mounts them). Pytest: `tests/test_e2e_server.py` and the per-group step
  tests.
- **Playwright** (`@playwright/test` 1.56.1, `@axe-core/playwright` 4.13.0, `lighthouse` 13.5.0, all
  exact; `npm audit` 0), `playwright.config.ts` with Desktop Chrome, iPhone 13 (WebKit in CI;
  Chromium with the iPhone 13 device here, where WebKit cannot be downloaded) and Pixel 7, one worker,
  no retries; an axe helper (WCAG 2.2 AA tags, fails on serious or critical); a browser network guard
  (outside requests aborted; a redirect followed off the server fails the test); the harness's own
  self-checks in `tests/e2e/self/`; `tests/e2e/README.md`.
- **The 12 golden paths** in `tests/e2e/golden/`, written against today's UI as mapped in
  `01-harness.md`: 1 sign-in (email and a mocked Google), 2 today's onboarding steps (brand, connect
  X through a mocked OAuth, Use me as lead, first brief), 3 ask the team, 4 compose with an override
  and a library image, 5 Approve & schedule with the fingerprint, 6 request changes in a two-stage
  workspace, 7 calendar drag (real drag on desktop; the page's own drop handler on the touch
  projects), 8 client portal sign-off, 9 inbox from a signed webhook, 10 brand colour and the
  organisation timezone, 11 workspace isolation (every workspace-B URL refused, 403 or 404, never
  B's data), 12 TOTP as the one declared pending test (`test.fixme`; TOTP is Phase 4). `data-testid`
  hooks were added next to the existing attributes in the templates the paths touch.
- **Defects the paths found and fixed** (each with a red test first): in a two-stage workspace, a
  post sent back at the client stage left its brief "approved" with no way to send it to the team
  (`services.reopen_sent_back`, only when a channel was sent back or rejected and none still carries
  an approval; `apps/studio/tests/test_two_stage_send_back.py`); the brand page's colour inputs now
  render from the form's own widget; the composer's channel pills are toggle buttons with a pressed
  state; the open inbox message scrolls with the keyboard on a short screen (axe
  `scrollable-region-focusable`).
- **Date-dependent tests** (owner-approved, 25 Oct): five studio tests hard-coded the week of
  19 October and began failing on every branch, `main` included, once the date passed 24 October.
  Their dates are now computed from today in the workspace timezone; every assertion is unchanged.
  `test_insights.py::test_the_plan_queues_the_months_articles_for_the_seo_team` failed in the last
  week of every month because of query order; it now reads oldest first.

**Not done yet in Phase 1** (left when the session's credits ran out, 26 Oct): Lighthouse with the
section 5 budgets (`.lighthouserc.json`, `tests/lighthouse/run.mjs`; the package is installed); the
**E2E (Playwright)** and **Lighthouse CI** jobs in `ci.yml`; the P1 items (CSP header test, the
client variant of path 6, the manager variant of path 5); `CLAUDE.md` and `CONTRIBUTING.md` (the e2e,
Lighthouse, audit and `compilemessages` commands, and the "CI runs exactly these" sentence); a
second review of group 4 after its last fixes (its final verification did not report); group 1's
open review point (path 11 sweeps workspace-B ids in URL paths only, not in form bodies or query
strings, and leaves out the Agent API); the gate itself; and the owner's branch ruleset making CI
required on `main` (R11: needs GitHub admin rights).

## 24 Oct 2026 — Phase 0: agree the cut

**Changed**

- The owner confirmed every decision in section 2 and five resolutions: Blog on where a blog
  website already exists; TikTok hidden with Bluesky, Mastodon, DEV.to and Threads behind
  `extra_providers` (connected accounts keep working); the Agent API, API keys, MCP and OAuth
  leave the navigation only; Pricing redirects to Request invite; Routines live in Activity with
  the three presets and the free-form form under Settings → Advanced.
- `docs/BETA_PLAN.md` (the plan, sections numbered 1–8, decisions recorded), `docs/specs/00-cut.md`
  (the spec) and `docs/specs/phase-0.md` (the plan for this phase).
- `AgencySettings.features`: a JSON object with a database default of `{}` (migration
  `studio/0008_agencysettings_features`, one additive column), read only through
  `apps.common.features.feature_enabled(workspace, key)` with the keys `blog`, `queues`,
  `templates`, `extra_providers` and `advanced_settings`. An unknown key raises; a key left out takes
  its default (Blog on where an enabled blog website exists, everything else off); a workspace
  without settings gets the defaults and no row is created.
- `AgencySettings` in the Django admin (staff only) so switches can be set before Settings exists;
  the form refuses anything but known keys with true or false, an emptied box saves as empty, the
  workspace cannot be changed on an existing row, and no other organisation's accounts are listed.
- Nothing a person sees in the product changed; no template, view or URL reads the switch yet.

**Gate** (`spec approved; migration passes makemigrations --check`) — on commit `b54b6c1`:

- `python manage.py makemigrations --check --dry-run` → `No changes detected` (exit 0).
- `sqlmigrate studio 0008` → `ALTER TABLE "studio_agency_settings" ADD COLUMN "features" jsonb DEFAULT '{}'::jsonb NOT NULL;`
- Full suite (section 7 rule): `5415 passed, 1 skipped` in 14 min 8 s, 0 failed.
- ruff check and format, mypy (924 files), `test:ui` (30/30), `recolor.py --check`: clean.
- Reviews: three independent passes; every finding fixed with a failing test first, or recorded
  as a Phase 2/3 question in `00-cut.md`.
- Spec approval: **approved by the owner, 24 Oct 2026.** Phase 0 gate passed.

**Released** — 24 Oct 2026, main `6d9cf1d` (PR #15, squash) on both Railway services: web
deployment `431540ad`, worker `c33a6a5a`. The release step applied `studio.0008_agencysettings_features`
(`db.migrations: 0 unapplied` after it); the new worker took over the single-worker lock from the
old one and reported its schedules verified; no error about the new column in either service's
logs. `live_verify` in the release step: 48 passed, 1 failed (More Space's Instagram account is
`@morespace.ai`, not the expected brand account, as before this release), 5 blocked on the owner (no
X app, no LinkedIn company app, the Meta webhook token unset, X not connected for either brand),
11 info. `/health/` answered 200 to Railway's health check. Rollback: web `a483e2c6` and worker
`fcca5126` (`38f4eab`); the added column stays, since the previous code ignores it and its database
default covers that code's inserts.
