# 01 — The test harness

Phase 1 of [`docs/BETA_PLAN.md`](../BETA_PLAN.md). Status: **written 24 Oct 2026**, from four read-only
discovery passes over the code, the CI file and a prototype harness. Gate (section 6): CI green with
all new jobs; 12 e2e tests pass on the old UI.

This phase adds tests, the CI jobs that run them, and the test hooks they need. It changes nothing
a person sees, except where a test finds a defect that already exists, which is then fixed with the
test as its red test.

## Problem

Phase 3 rebuilds nine screens. Today nothing would notice if the rebuild broke an approval: the
pytest suite (5,415 tests) checks views and services through the Django test client, but no test
drives a real browser through a person's path, none runs on a phone-sized screen, none checks
accessibility on rendered pages, and none measures page weight. CI also misses three standards in
section 5: dependency audits (`pip-audit` reports 38 known vulnerabilities in the locked
Pillow 12.3.0 and certifi 2026.7.22 today), `npm audit`, and a check that the translation catalogue
compiles. Without a harness built first, every Phase 3 screen would be checked by hand, and a
regression would be found by a beta agency.

## Goals

1. **The 12 golden paths of section 7 run in a real browser** on Desktop Chrome, iPhone 13 and
   Pixel 7, against the current UI, from one command, with no network access beyond the machine.
2. **Every screen those paths visit is checked by axe** for WCAG 2.2 AA, and fails on any serious or
   critical violation.
3. **CI runs everything on every pull request**: the e2e suite, Lighthouse CI with the section 5
   budgets, `pip-audit`, `npm audit --audit-level=high`, and `compilemessages`, and all of them are
   green on `main`.
4. **Phase 3 can restyle freely**: the e2e tests find controls by `data-testid`, never by CSS class
   or copy, and assert outcomes in the database, not pixels.

## Non-goals

- **No new product behaviour.** The onboarding wizard, the Approvals stack, TOTP 2FA and the
  six-item navigation are built in Phases 2–4; Phase 1 tests today's equivalents and rewrites them
  when the screens change.
- **No visual-regression baselines.** The screenshot settings and folder exist; the baselines are
  taken per screen in Phase 3, where the before/after pairs are reviewed.
- **No change to the 403 that isolation returns today.** See golden path 11.
- **No performance work beyond what the budgets force.** If a budget fails on the old UI, Phase 1
  fixes it only when the fix changes nothing a person sees (R9).
- **No branch-protection change from this session.** No tool here can set it; the owner does (R11).

## Who it is for

| Person | What the harness gives them |
|---|---|
| The engineer or coding agent rebuilding a screen in Phase 3 | A red test the moment an approval, a schedule or an isolation boundary breaks, on all three devices |
| The agency owner signing off a screen | Evidence per screen: e2e green, axe 0 serious, Lighthouse numbers |
| A procurement or IT reviewer at a beta agency | Dependency audits, accessibility checks and budgets that run on every change, with reports |

## User stories

- As an engineer rebuilding Home, I want the "ask the team for a post" path to run in a phone-sized
  browser so that a layout change that hides *Go ahead* fails CI instead of failing a beta agency.
- As an engineer, I want e2e tests that find controls by `data-testid` so that restyling a button
  does not break a test that has nothing to do with its look.
- As an approver, I want "Approve & schedule" to be proven to stamp the fingerprint and schedule at
  the approved time, end to end, so that the rebuild cannot quietly turn it into a plain Approve.
- As an agency owner, I want a member of another workspace to be refused every one of my URLs, in a
  browser, on every change.
- As a reviewer, I want CI to fail when a locked dependency has a known high or critical
  vulnerability so that I do not have to check by hand.
- As an engineer, I want to run the whole suite on my machine without credentials or network so
  that I can reproduce a CI failure.

## The 12 golden paths, mapped to today's UI

Each path is one spec file, `tests/e2e/golden/NN-name.spec.ts`. Roles: **owner** (organisation
owner, internal approver), **manager** (approver), **editor** (staff who creates posts but cannot
approve), **client** (portal only). "DB" means the test reads the rows through the harness's named
probes (R4) and checks them, not only the page.

| # | Path (section 7) | Today's UI it runs on | Roles | What it asserts |
|---|---|---|---|---|
| 1 | Sign in with email, then with Google (mocked), land on Home | `/accounts/login/` form; *Sign in with Google* POST → the Google authorize URL, answered in the browser by a redirect to the callback; the server side of the exchange returns a fixed profile | owner, editor (email); a new and an existing Google user | wrong password stays on login with a message and no session; right password lands on Home (`[data-home-today]`) of the seeded workspace; DB session belongs to the user; a new Google user accepts the terms and lands on Home; an existing email signs straight in |
| 2 | Onboarding wizard: brand → connect one account → choose approver → first post queued | No wizard exists. Today's steps: Brand page → Connect an account (OAuth mocked) → Set up *Use me as lead* → Home idea → *Go ahead* | owner | brand saved; `SocialAccount` connected for the workspace; `AgencySettings.lead` is the owner; a `StudioBrief` exists, queued or working. Rewritten against the wizard in Phase 3 |
| 3 | Ask the team for a post from Home; the brief card appears; *Go ahead*; the draft reaches *Waiting for you* | Home thread, the brief card, *Go ahead*, the Today card | owner, editor; client refused | the brief card lists the asked-for channels and the key message; after *Go ahead* the worker runs the pipeline with the faked team; the brief reaches *Ready for approval* and shows under *Waiting for you*; `PlatformPost`s are `pending_review`; the editor sees no approve control |
| 4 | Write a post myself with a per-platform override and an image from the library; submit for review | Compose: two accounts, *Own wording for …*, Media library picker, *Submit for approval* | owner, editor; client refused | one `PlatformPost` per account, `pending_review`; the override caption only on the overridden account; the library asset attached at position 0; an `ApprovalAction` `submitted` |
| 5 | Approve & schedule from the Approvals stack; the post shows on the Calendar at that time with the fingerprint | Approvals today: `calendar/?mode=list&tab=approvals`, *Approve & schedule* on the row; Calendar week view | owner (manager in P1); editor refused | status `scheduled` at the proposed time; `approved_fingerprint` equals the gate's fingerprint of the post; `ApprovalAction` `approved` on channel `dashboard` with that fingerprint; the chip sits in the cell for that local date and hour; the editor sees no approve control and a direct POST is refused |
| 6 | Request changes with feedback; the revision appears; the earlier approval is withdrawn | Two-stage workspace: the owner approves (internal stage, fingerprint stamped), then requests changes with feedback from the Approvals row, then sends it to the team from the post page | owner; client variant in P1 | after the request: `changes_requested`, fingerprint and approver cleared, the feedback stored; after sending it to the team: *Revision 2* with the notes, and the brief back at *Ready for approval* with no approval on it |
| 7 | Drag a post on the Calendar as an approver; the new time is approved; as staff, it is not | Calendar week view, SortableJS drag of a scheduled chip | owner, editor | owner: status stays `scheduled`, `approved_publish_at` is the new time, `ApprovalAction` `time_approved`; editor (own post): back to `pending_review`, approval cleared, `ApprovalAction` `approval_withdrawn`. Desktop drives the real drag; on the two touch projects the test calls the same drop handler the gesture calls, and says so in its title |
| 8 | Client portal via magic link: sign off on a post; it completes the client stage but is not published | `/portal/<token>/` → *Continue to portal* → Approvals → *Approve* | client | status `approved`, never `scheduled` or `published`; the internal fingerprint unchanged; `ApprovalAction` by the client on channel `portal`; no publish log; the client is refused `/workspace/…/studio/` |
| 9 | Inbox: a mocked comment arrives; assign, reply, mark done | A signed Facebook webhook POST (the real arrival path) → Inbox → open → Assign → *Send reply* (the platform call answered by a mock transport) → status *Resolved* | owner, editor; client refused | `InboxMessage` created from the webhook; assigned to the chosen person; `InboxReply` `sent` with the mocked platform id; status `resolved` |
| 10 | Settings: change brand colour and timezone; the preview and the calendar reflect both | Brand page colour inputs and sample image; the organisation default timezone (no screen sets a workspace's own timezone today) | owner; editor read-only | the brand colour is saved and the sample image changes; with the workspace timezone blank, changing the organisation default moves a scheduled chip to the cell for the new local time. The calendar shows no brand colour today; Phase 3 decides whether it should |
| 11 | Workspace isolation: a member of workspace A is refused every workspace-B URL | Every page and action URL of workspace B, requested as members of A | owner, editor, client of A | every URL answers **403 or 404** and never shows B's data (the same rule as `live_verify isolation.workspace`); B's objects under A's URLs answer 404 |
| 12 | 2FA: enable TOTP, sign out, sign in with a code; an owner without 2FA is prompted | Does not exist (dormant `User.totp_*` columns only; Phase 4 builds it with `django-otp`) | owner | written now as a declared pending test (`test.fixme`) with the steps, so Phase 4 starts from a red test; **not counted as passing** |

Notes:

- **Path 11 and 404.** Section 7 says "gets 404". Today `RBACMiddleware` answers 403 for every one
  of the 240 workspace URLs before any view runs, and existing tests pin 403. Changing it is a
  behaviour change outside Phase 1; the test asserts *refused* (403 or 404) and the question is
  recorded below.
- **Path 6.** On the current UI an approver cannot send a post back after a single-stage approval
  (an approved post is not revisable). The two-stage path is the one that exists today. The client
  variant (the client requests changes in the portal) is P1.
- **Roles.** Section 7 asks for every path as owner, staff and, where it applies, client. The table
  lists where a role changes the outcome; a role that is simply refused is one extra assertion in
  the same test, not a separate run.

## Requirements

### P0 — must have

**R1. A server for the browser.** `python -m tests.e2e.server` starts the web app and the worker
in one process on `127.0.0.1` with `config.settings.e2e`.
- Its own database `brightbean_e2e` (from `DB_NAME`), dropped and re-created on `--reset` only
  when the settings module is `config.settings.e2e` and the name ends in `_e2e`; anything else is
  refused before a single statement runs.
- Settings: built on `base` (not `development`): `DEBUG=False`, CSP **enforced** (not report-only),
  rate limits on, local storage, local-memory cache and mail, loopback `ALLOWED_HOSTS`, placeholder
  provider settings that make readiness green, `SECRET_KEY` and salt defaulted like `test.py`, so no
  `.env` or `dev.env` is needed.
- The worker loop mirrors `run_worker`: the advisory-lock lease, stale-lock reclaim, recurring
  schedules, `run_next_task` under lease checks.
- One process, because the fakes are module attributes shared by request threads and the worker.

**R2. Nothing leaves the machine.** In the server process: the model client, the second
provider's client and the source fetcher refuse, as `conftest.py` makes them refuse in pytest; the
creative agents are the `FakeTeam` of `apps/studio/tests/conftest.py` (imported, not copied), with
the real queue and worker (unlike `fake_team`, `pipeline.enqueue` is **not** stubbed); the account
manager is a rule-based fake that returns schema-valid answers; provider HTTP goes through an
`httpx.MockTransport` that answers the few platform calls the paths make and refuses the rest; a
socket guard allows loopback to the database and the server port only, and records every refused
attempt. In the browser: every request to a host other than the server is aborted, except the two
OAuth authorize URLs, which are answered with a redirect to the callback.
*Acceptance:* a golden-path run leaves the guard's refused list without any platform, model or
Telegram host; a test that tries a real provider call fails loudly.

**R3. A seeded world.** On `--reset` the server seeds: an organisation with workspace A (fixed
UUID, Asia/Kolkata, `required_internal`, dashboard approval required) and workspace B (fixed UUID,
another owner), the users owner, manager, editor and client of A (terms accepted, landing on A, no
auto-created "My Workspace"), connected LinkedIn company and Instagram accounts, the brand profile,
verified facts, agency settings with the owner as lead, a library image, and the Facebook account
path 9 needs. The two-stage workspace paths 6 and 8 run on is not seeded: as `phase-1.md` Task 4
says, each of those tests makes its own with a fixture (`two_stage_brief`, `client_stage_post` in
`tests/e2e/server/steps/g4.py`: its own organisation, owner, client, LinkedIn account, brand and
agency settings), so neither depends on what another test did to a shared one.

**R4. Named fixtures and probes, no arbitrary code.** The harness serves
`/__e2e__/fixture/<name>` (POST, creates fresh rows for one test and returns their ids) and
`/__e2e__/probe/<name>` (GET, returns the rows a test asserts on). Each is a typed Python function,
linted and type-checked with the rest of `tests/`. They are mounted only by the e2e URL conf, only
answer `127.0.0.1`, and are refused when the settings module is not `config.settings.e2e`. There is
no endpoint that runs code from the request.
*Acceptance:* `config/urls.py` does not reference them; a pytest test proves the endpoints 404 under
`config.settings.test` and refuse a non-loopback address under the e2e settings.

**R5. Playwright in `tests/e2e/`.** `@playwright/test` 1.56.1 and `@axe-core/playwright` 4.13.0,
pinned exactly in the root `package.json` and lock (1.56.1 matches the installed Chromium build;
4.13.0 is the newest release older than two weeks); `playwright.config.ts` with three projects:
`desktop-chrome`, `iphone-13`, `pixel-7`. One worker (the suite shares one database and one
server); `webServer` starts R1 and waits for `/health/`; traces and screenshots kept on failure; the
screenshot folder `tests/e2e/__screenshots__/` and a 0.1 % diff threshold configured for Phase 3.
- **iPhone 13 runs on WebKit in CI** (`playwright install --with-deps chromium webkit`). WebKit
  cannot be downloaded in this sandbox (the network policy refuses the Playwright CDN), so a local
  run without WebKit uses Chromium with the iPhone 13 viewport, scale and touch, and prints that it
  did.
- Sign-in: the setup step creates one session per role through a fixture and stores it; only path 1
  posts the login form, which keeps the suite under the login rate limit (10 posts a minute).
- Each test creates its own rows through fixtures, so tests do not depend on order.

**R6. The 12 golden paths** as mapped above, on all three projects.
*Acceptance:* paths 1–11 pass on all three projects locally and in CI; path 12 is reported as
pending, with the reason, and is counted as such in the gate.

**R7. Axe in every test.** A helper runs `AxeBuilder` with the tags `wcag2a`, `wcag2aa`, `wcag21a`,
`wcag21aa`, `wcag22aa` on every screen a test reaches, and on each dialog it opens, and fails on any
`serious` or `critical` violation, listing rule, target and help URL.
*Acceptance:* every spec file calls it at least once per screen; a deliberately broken fixture page
(a form control without a label) makes the helper fail in its own test.

**R8. `data-testid` hooks.** Every control the paths touch gets a `data-testid` (kebab-case,
`<area>-<thing>`, for example `approvals-row-approve-schedule`), added next to the existing
attributes. Existing `data-*` hooks that pytest asserts stay exactly as they are.
*Acceptance:* no e2e selector uses a CSS class, copy text or an Alpine attribute; role and
accessible-name selectors (`getByRole`) are allowed where they are the point of the check.

**R9. Lighthouse CI.** `.lighthouserc.json` with three URLs on workspace A, mobile (Lighthouse's
default form factor), three runs each, median: Home, Approvals and Calendar. It is run by Lighthouse
13.5.0 itself through a short runner (`tests/lighthouse/run.mjs`) that drives the Playwright Chromium
and reads the budgets from the `assert` section of `.lighthouserc.json`, in Lighthouse CI's format.
The `@lhci/cli` package is not used: version 0.15.1 (the latest) pins Lighthouse 12 and brings 13
high-severity advisories (`tmp`, `extract-zip`, `basic-ftp`, an old `puppeteer-core`) into the
lockfile, which would fail the audit in R10; Lighthouse 13.5.0 with Playwright and axe audits at 0.
Budgets from section 5: performance ≥ 0.90; LCP ≤ 2,500 ms; CLS ≤ 0.1; measured lab
INP upper bound ≤ 200 ms; gzip JavaScript ≤ 150,000 bytes (decimal kilobytes, the stricter
reading of "150 KB"). The script-transfer limit is also 150,000 bytes. Gzip totals include inline
scripts. The e2e server uses `runserver` with `--static manifest --no-worker`: `collectstatic`
builds the compressed manifest and WhiteNoise serves it, bypassing Django's development static
handler. It does not use gunicorn. Authentication comes from a session fixture, not the form.

**Measurement clarification, 26 Oct 2026:** the original R9 used TBT ≤ 200 ms as a stand-in because
Lighthouse navigation cannot measure INP. The implemented runner instead drives real inputs,
observes Event Timing at 4× CPU slowdown, and enforces the 200 ms lab INP upper bound. It includes
the first emoji-picker opening, search and insertion, so deferring that work does not remove it
from the interaction measurement. TBT remains a navigation diagnostic; it is not an INP surrogate
or an additional interaction gate. This synthetic measurement does not establish field p75 INP.
The earlier TBT-gated run and its failures remain in the changelog/evidence; the section 5 targets
are unchanged.

The median numbers per URL and budget are printed in the job log, with TBT labelled diagnostic;
reports are never uploaded to public storage. Missing metrics, missing real interactions,
unexpected redirects or an external network attempt fail the run.
*Acceptance:* every section 5 budget is an error. If the old UI misses one, Phase 1 first fixes
work that changes nothing a person sees (for example, loading Chart.js and SortableJS only where
used). The 26 Oct continuation supersedes the original per-URL *warn* fallback: no required
budget is downgraded to a warning. Any unresolved budget is reported as a failed gate.

**R10. CI jobs.** In `.github/workflows/ci.yml`, with the existing pinned actions and the runner's
own PostgreSQL:
- **Dependency audit**: `pip-audit` on `requirements.lock` (hash-checked, no install) and
  `npm audit --audit-level=high` in the repository root and in `theme/static_src`.
- **compilemessages** in the pytest job, with `gettext` installed and a `locale/` directory in
  `LOCALE_PATHS` (today the command errors out because no locale directory exists).
- **E2E (Playwright)**: the CSS build, the e2e suite on three projects, failures printed in the
  job log with the step, the selector and the axe rule.
- **Lighthouse CI**: the CSS build, `collectstatic`, the runner, the median numbers printed.
- Every action pinned by commit SHA, as the file does today. Uploading the HTML reports and traces
  needs `actions/upload-artifact`, whose SHA this session cannot verify (no access to that
  repository), so it is P1 for whoever can pin it.
*Acceptance:* every new job is green on the pull request and on `main`; the job names are listed for
R11.

**R11. CI required on `main`.** The owner adds a branch ruleset requiring a pull request and the
checks *Lint (ruff)*, *Type check (mypy)*, *Test (pytest)*, *Agency UI state tests*, *Docker build*,
*Secret scan (gitleaks)* and the new ones. No tool in this session can set it (the protection API
answers 403 to the integration), so the CHANGELOG records it as waiting on the owner, with the exact
steps.

**R12. Dependency audit at zero.** Pillow's range moves to `>=13.0,<14.0` and the lock is
regenerated with `pip-compile` (only Pillow 13.0.0 and certifi 2026.10.23 change). Pillow 13.0.0 is
eight days old; it is taken anyway because it fixes 37 known vulnerabilities, several of them memory
corruption in image parsers that read uploaded files. The full pytest suite runs on the new lock.

### P1 — nice to have

- **CSP header test** (section 7, security row): a pytest test that, with CSP enforced, the
  `script-src` directive of a real response has no `'unsafe-inline'`. It passes today and guards it.
- **Client variant of path 6** (the client requests changes in the portal).
- **Manager variant of path 5** (a manager, not only the owner, approves and schedules).
- `pip-audit` installed from a hashed requirements file instead of a pinned name.
- E2E traces and Lighthouse HTML reports uploaded as CI artefacts with `actions/upload-artifact`
  pinned by SHA.

### P2 — later phases (designed for, not built)

- Visual-regression baselines per screen (Phase 3), taken in `visual:` commits.
- Rewrites of paths 2, 5, 6 and 10 against the wizard, the Approvals stack and Settings
  (Phases 2–3), and of path 12 against TOTP (Phase 4).
- A route sweep that runs axe on every page of the product map at 390 px and 1440 px (the
  prototype's sweep visited 168 pages); Phase 3 adds it per screen.

## Success metrics

| Metric | Target | How it is measured |
|---|---|---|
| Golden paths passing | 11 of 12 on all three projects (12th pending until Phase 4) | `npx playwright test` summary, locally and in CI |
| Flakiness | 0 failures in 3 consecutive local runs | three runs before the gate |
| E2E time in CI | about 6 minutes; at most 12 | the job's duration |
| Axe | 0 serious or critical on every screen the paths reach | the helper's failures |
| Dependency audit | 0 known vulnerabilities in the lock; 0 high or critical in npm | the job's output |
| Network | 0 refused attempts to platform, model or Telegram hosts during the paths | the guard's list, checked at the end of the run |

## Open questions

| Question | For | Blocking? |
|---|---|---|
| Should a member of another workspace get 404 instead of 403 (no hint that the workspace exists)? It changes the middleware and the tests that pin 403. Recommendation: decide in Phase 4 with the ASVS review. | owner, engineering | no |
| Path 10: should the calendar show the brand colour at all? Today only the cross-workspace calendar shows a workspace dot. | owner, design (Phase 3) | no |
| Path 10: a workspace's own timezone has no screen; Settings → Brand in Phase 3 is the natural home. | design (Phase 3) | no |
| The branch ruleset (R11) needs the owner's GitHub admin rights. | owner | for "CI required" only |

## Timeline

Two days in the plan. Order: the server and fakes (R1–R4) → Playwright and the axe helper (R5, R7)
→ the paths, one at a time, red first, with the test hooks each needs (R6, R8) → the dependency bump
and audits (R10, R12) → Lighthouse (R9) → CI jobs → review → gate.
