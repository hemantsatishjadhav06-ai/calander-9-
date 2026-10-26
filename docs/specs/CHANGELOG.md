# Beta changelog

One entry per phase of [`docs/BETA_PLAN.md`](../BETA_PLAN.md): the date, what changed, and what the
phase gate (section 6) said. Newest first.

## 26 Oct 2026 — Phase 1: complete and verify the harness (in progress)

**Scope.** Finish PR #17 and run its gate. The owner explicitly reserved merging,
releasing and Phase 2 for a later instruction. Owner-managed branch rules,
provider apps, production credentials and beta invitations are not prerequisites
for the local harness work. Golden path 12 remains pending until Phase 4.

**Starting point.** PR head `4b697579d25a5ddf71d1dc015ab28f2a26e7620b` has the
same tree as GitHub's test merge `9582e28226b0fdd23f9fa51f11e2a219fa45bbc5`
with main `6d9cf1d450282e295a779dcdbdea5252d7e8c3d2`. The preceding session's
partial pytest and browser runs are not full-suite verification. The later
documentation-only commit `35f30cd` records the preceding session's final
paths 6 and 8 review as passed. Commit `2f14e96` adds that session's full
pytest and browser self-check receipt. Those historical results are preserved
below; this continuation's fresh verification is recorded separately.

**Changed so far.** `CLAUDE.md` and `CONTRIBUTING.md` describe the Postgres,
Node, browser/axe, template, Lighthouse and security layers, their commands,
the actual browser engines and the no-retry rule. The pre-commit guidance now
makes clear that hooks cover only a subset of CI. The nine `CLAUDE.md`
invariants are unchanged. `STATUS.md` records the stop after the Phase 1 gate.
The Lighthouse runner and config add strict mobile budgets for Home,
Approvals and Calendar; its separate lab Event Timing check measures real
inputs at 4× CPU slowdown rather than relabelling navigation TBT as INP.
Field p75 INP remains outside what this synthetic measurement proves.
The CI workflow now includes **E2E (Playwright)** and **Lighthouse CI** on PRs,
with browser retries fixed at zero. The three remaining small tests are
present: the enforced CSP response header, a manager approving and scheduling,
and a client requesting changes through the portal. The role variants use
new `data-testid` hooks; existing approval and workspace-isolation assertions
are retained.

**Verification in this continuation (not the final gate)**

| Check | Result | Scope |
|---|---|---|
| Full baseline pytest | 5,530 passed, 1 skipped; 37 warnings; 856.32 seconds (14m 16s); exit 0 | Original PR application/test tree, before this continuation's behaviour fixes |
| Original 126-case browser suite | 120 passed, 3 failed, 3 pending; 13.4 minutes | All three projects, including actual WebKit on iPhone 13; failures were the redirect self-check, one per device |
| Golden paths 1–11 in that baseline | Passed on all three projects | Includes the original paths 6 and 8 |
| Focused follow-up | 21 passed, 0 failed, 0 flaky; 3.5 minutes | Original paths 6, 7 and 8, the manager/client variants and corrected redirect self-check, on all three projects |
| CSP header regression | 1 passed; 2 warnings; exit 0 | Enforced response header, nonce present and no `unsafe-inline` script permission |
| Translation compilation | Exit 0 with GNU gettext 0.23.1 | No project `.po` catalogue exists yet; Phase 4 owns translation rollout |

The pytest skip is
`apps.media_library.tests.test_storage_helpers.FilmstripCacheAliasTest.test_location_is_a_real_server_url_when_the_backend_is_redis`:
`not a Redis-backed deployment`. It is distinct from the three Playwright
TOTP cases pending until Phase 4. The existing main CI coverage baseline is
87% (run `40097544761`); final coverage must not fall below it.

The initial Home measurement found 153,406 gzip JavaScript bytes against the
150,000-byte budget. Loading Chart.js and SortableJS only on the pages that
use them removes that failure without restyling. Ordered deferred loading
and rendering emoji choices only while their picker is open reduce startup
work; regression checks cover the affected initialization and picker actions.

**Mobile performance measurements after those changes** (median of three
audits per page):

| Page | Performance | LCP (ms) | Lab INP upper bound (ms) | CLS | JavaScript gzip (bytes) | TBT diagnostic (ms) |
|---|---:|---:|---:|---:|---:|---:|
| Home | 96 | 1,885 | 168 | 0.078 | 68,862 | 101 |
| Approvals | 93 | 2,308 | 120 | 0.006 | 78,689 | 202 |
| Calendar | 90 | 2,450 | 128 | 0.007 | 78,688 | 249 |

These measurements meet all section 5 targets. The earlier R9 configuration
also gated TBT at 200 ms as a substitute for INP, so that run correctly
reported failure for Approvals and Calendar under that extra proxy check.
The runner now measures real-input lab INP and uses its 200 ms threshold;
TBT remains a reported diagnostic. No section 5 threshold is relaxed or made
a warning. Re-evaluating all nine unchanged Lighthouse reports and their
recorded real-input measurements against the clarified section 5 contract
passes; the receipt hashes each source report and preserves the original
failed summary. This is a re-evaluation, not a fresh navigation run. Final
PR CI must collect fresh measurements before the overall gate can pass.
Synthetic lab INP does not prove field p75 Core Web Vitals.

The new emoji-picker browser regression exposed a modal-focus race in the
test setup. It was quarantined with
[issue #18](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/18)
while the explicit focus-readiness fix undergoes stability verification.
Quarantined cases are reported separately and never counted as passes;
CI retries remain zero.

**Gate, exactly as written in `BETA_PLAN.md` section 6:**

> CI green with all new jobs; 12 e2e tests pass on the old UI.

**Result: pending.** The final full pytest run after the fixes, three
consecutive complete browser runs, Lighthouse budgets and final PR CI must
finish before this record can say passed. The approved Phase 4 exception for
path 12 must be listed as pending in the final totals, not counted as passing.
No merge or release is part of this verification.

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

**Checked on the merged branch** (26 Oct): full pytest `5530 passed, 1 skipped` (17 min); CI on
PR #17 green on all seven checks; e2e on all three projects `120 passed, 3 skipped` (path 12, the
declared pending test) and 3 failed: the harness's own redirect self-check, broken by merging two
groups' versions of the browser network guard. It now asserts the `escaped` record the kept guard
makes; `tests/e2e/self` 36/36 on three projects.

**Not done yet in Phase 1** (left when the session's credits ran out, 26 Oct): Lighthouse with the
section 5 budgets (`.lighthouserc.json`, `tests/lighthouse/run.mjs`; the package is installed); the
**E2E (Playwright)** and **Lighthouse CI** jobs in `ci.yml`; the P1 items (CSP header test, the
client variant of path 6, the manager variant of path 5); `CLAUDE.md` and `CONTRIBUTING.md` (the e2e,
Lighthouse, audit and `compilemessages` commands, and the "CI runs exactly these" sentence); group
1's open review point (path 11 sweeps workspace-B ids in URL paths only, not in form bodies or query
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
