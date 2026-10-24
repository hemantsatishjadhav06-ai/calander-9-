# SM Bean — Beta-Ready Rebuild Plan

24 Oct 2026 · owner: Hemant · copied from the "Beta-Ready Rebuild Plan (Claude Code handoff)" document.
Section 2 records the decisions the owner confirmed in Phase 0 (see `docs/specs/00-cut.md`).

## How to use this doc

Claude Code works phase by phase, using the skills named in each phase, and never moves to the
next phase until that phase's gate passes and the owner says so.

The brief in one line: **cut SM Bean down to the screens a 5–10 agency closed beta actually uses,
rebuild the interface so a 25-year-old social media manager finds it obvious on a phone, and ship
it behind measurable accessibility, performance and security gates.**

Repo: `hemantsatishjadhav06-ai/calander-9-` · Live: `sm-bean-production-eb50.up.railway.app` ·
Stack: Django 5 / Python 3.12 / PostgreSQL 16 / Tailwind 4 / HTMX-style partials / one background worker.

Skill pipeline, in order:

1. `brainstorming` → confirm the cut list in section 2 with the owner before touching code
2. `product-management:write-spec` → one spec per phase from sections 3–5
3. `make-plan` → phased plan with file-level tasks
4. `do` → execute with subagents, `test-driven-development` inside each task
5. `impeccable` + `frontend-design` → every screen rebuilt in Phase 3
6. `engineering:code-review` + `requesting-code-review` → before each phase gate
7. `verification-before-completion` → run the gate checklist in section 6
8. `engineering:deploy-checklist` → Railway release of each phase

Rules that already exist and still hold: `CLAUDE.md` (the nine invariants, naming rules,
design-system tokens) and `docs/PRODUCT_MAP.md`. This plan sits on top of them, never replaces them.

## 1. What SM Bean is today

SM Bean is already a large, well-engineered product; the problem for the beta is breadth, not
quality. The backend is sound and must be preserved; the surface area is 3–4× what ten agencies
will use in their first month.

| Measure | Value |
|---|---|
| Python (apps, config, providers; excl. migrations and tests) | ~98,000 lines |
| Django apps | 27 |
| HTML templates | 340 |
| Test files | 250 (pytest on Postgres, ~8 min full run) |
| Platform providers | 14 (FB, IG ×2, LinkedIn ×2, TikTok, YouTube, Pinterest, Threads, Bluesky, GBP, Mastodon, DEV.to, X) |
| AI agents | 28 in 7 departments, 8 job kinds |
| Recurring worker tasks | 22 (publish every 15 s, Telegram 30 s, routines 60 s, autopilot 15 min …) |
| Sidebar entries | 8 primary + 8 under *More*, plus a 4-tab Agency strip and a separate Settings hub |
| Front-end JS | 963 lines own code + HTMX + Alpine; no framework |
| CI gates | UI state tests, ruff, mypy, migration check, pytest + coverage, Docker build |
| Design system | `docs/DESIGN_SYSTEM.md` ("Quiet graphite + Pine"), 3-layer tokens in `theme/static_src/src/styles.css` |
| Accessibility tests | `test_a11y_sweep.py` (dialogs, contrast greys, control names) — HTML-level only |
| Security | HSTS, secure cookies, nosniff, django-csp, django-ratelimit, encrypted credentials, Google SSO; no 2FA |
| i18n | `USE_I18N=True` but zero `.po` files; en-US only; times shown in workspace TZ |
| Browser e2e / Lighthouse / axe | none |

**Already strong and not to be touched by this plan:** the approval gate and fingerprint
(`apps/approvals`), workspace isolation, the publisher's lock-and-recheck loop, the untrusted-text
wrappers, the budget/rate gates, the Telegram one-use buttons, additive migrations. These are the
nine invariants in `CLAUDE.md`; every phase gate below re-runs the tests that enforce them.

**What is weak:** the interface. Three overlapping entry points to create a post (Home thread,
Create Idea, Compose), three settings surfaces (Set up, Settings hub, Workspace settings), approvals
reachable from four places, a 16-item sidebar, desktop-first layouts, and public marketing pages
that pitch a 14-platform open-source alternative to Sendible rather than the agency product the
beta is selling.

## 2. Feature audit: keep, merge, hide, cut

The beta ships 9 screens, not 30. *Keep* = stays as is. *Merge* = folds into another screen.
*Hide (flag)* = code stays, a workspace feature flag (`AgencySettings.features`) turns it on per
agency; nothing is deleted in the beta. *Cut* = removed from navigation and marketing; code may
stay in the repo until after beta.

Confirmed by the owner on 24 Oct 2026, with the five resolutions marked ★ (details in
`docs/specs/00-cut.md`).

| Surface | Today | Decision | Why / where it goes |
|---|---|---|---|
| Home (Today card, team thread, In progress) | `studio:index` | Keep | The daily screen. Becomes the only place to start a post. |
| Set up checklist | `studio:setup` | Merge | Becomes the onboarding wizard (first 10 min) and the owner's health page. |
| Approvals | 4 routes: Calendar list tab, post page, Telegram card, portal | Merge | One `/approvals/` screen; post page and Telegram card remain as entry points into it. |
| Calendar (month/week/day + list tabs) | `calendar:calendar` | Keep | Week view default on desktop, agenda list on phone. |
| Create Idea · Drafts · Compose | 3 entry points in `composer` | Merge | One **New post** sheet opened from Home and Calendar; Drafts become a Calendar list tab only. |
| Inbox (comments, DMs, reviews, SLA) | `inbox:feed` | Keep | Keep; sentiment + SLA move behind a filter, not the default view. |
| Analytics | `analytics:index` | Keep | Keep, cut to 4 KPI cards + one trend + the posts table. |
| Blog & SEO (write, score, publish to GitHub, Search Console) | `apps/blog` | Hide (flag `blog`) | Not all ten beta agencies run client blogs. ★ On wherever the workspace already has an enabled blog website (Neopolis, More Space). |
| Routines | `studio:routines` | Keep | Three presets only; the free-form instruction form moves behind *Advanced*. ★ Listed in Activity with the three presets; the free-form form under Settings → Advanced. |
| Team page (live board, roster, 24 h charts) | `studio:team` | Merge | Merge the live strip into Home; roster + job pages stay under one *Activity* screen. |
| Settings hub (Brand, Facts, Memory, Outcomes, Autopilot, Telegram, Budget) | `studio:settings_hub` | Merge | One Settings screen with tabs; Memory and Outcomes behind *Advanced*. |
| Workspace settings + Approvals settings + Members + Clients + Social accounts | 5 pages | Merge | Same Settings screen, same tabs. One settings surface, not three. |
| Queues · Posting Schedule · Recurrence | `calendar` *More* | Hide (flag `queues`) | Posting Schedule stays (the scheduler needs slots); Queues and recurring rules hidden. |
| Templates · Categories · Tags · CSV import | `composer` *More* | Hide (flag `templates`) | CSV import stays; templates/categories/tags hidden. |
| Media library (folders, variants, Unsplash) | `media_library` | Keep | Keep as a picker inside New post and a plain grid; cut folder management UI. |
| Client portal | `/portal/` | Keep | Keep; it is the agency's selling point. Needs the same visual pass. |
| Telegram transport | `apps/telegram` | Keep | Keep; it is how approvers work from a phone. Settings moves into Settings → Notifications. |
| Notifications page + preferences | `notifications:list` | Merge | Merge into a bell dropdown + Settings → Notifications. |
| Autopilot (weekly planning) | `studio:autopilot` | Keep | Keep, exposed as one toggle + posts/week on Settings; *Plan now* on Home. |
| Verified facts · Creative memory · Outcomes | 3 settings pages | Hide (flag `advanced_settings`) | Hide behind *Advanced*; power-user features. |
| Intelligence add-on + playground | `apps/intelligence` | Cut | Cut from nav; off unless its 5 vars are set anyway. |
| Agent API · API keys · MCP server · OAuth server | 4 apps | Cut | Cut from the beta UI; keep code; one *Developers* link in Settings → Advanced. ★ Navigation only: the URLs keep working. |
| Providers: Bluesky, Mastodon, DEV.to, Threads (★ and TikTok) | 5 of 14 | Hide (flag `extra_providers`) | Hide from the connect screen; Indian agency clients use FB/IG/LinkedIn/YouTube/GBP/Pinterest/X. ★ Accounts already connected keep working. |
| Older workflow endpoints (`studio:workflow_*`) | redirects | Cut | Delete after beta; keep redirects during. |
| Marketing site (home, features, platforms, developers, how it works) | `apps/marketing`, 7 templates | Merge | Rewrite as 3 pages for the beta pitch: Home, How it works, Request invite. Developers/platforms pages hidden. ★ Pricing redirects to Request invite; Privacy and Terms stay in the footer. |
| Google SSO · magic links · 14-day org deletion grace | `accounts`, `client_portal` | Keep | Keep. Add TOTP 2FA before beta (section 5). |

## 3. Target information architecture

Six items in the sidebar, one Settings screen, one way to create a post. A new user should be able
to name every screen's job after one look.

| Screen | Route | One job | Replaces |
|---|---|---|---|
| **Home** | `/studio/` | See what needs me today, talk to the team, start a post | Home + live strip from Team + Create Idea |
| **Approvals** | `/approvals/` | Review and approve the exact post, time and destinations | Calendar Approvals tab, approvals partials |
| **Calendar** | `/calendar/` | See what is going out when; move it; open a post | Calendar + Drafts list + Queue list |
| **Inbox** | `/inbox/` | Answer comments, DMs and reviews | unchanged |
| **Analytics** | `/analytics/` | Know what worked this month | unchanged, trimmed |
| **Activity** | `/studio/activity/` | See the team at work and every job's timeline | Team page, job pages, Routines |
| **Settings** (gear, bottom of sidebar) | `/settings/` | Everything configured, in tabs | Set up + Settings hub + 5 workspace pages + Telegram settings + Notification prefs |
| Blog (flag) | `/blog/` | Appears as a 7th item only when the workspace flag is on | unchanged |

Settings tabs, left to right: **Brand** · **Accounts** (social + health) · **Team & clients**
(members, roles, invites, portal links) · **Approvals** (stages, dashboard-approval rule) ·
**Autopilot** (toggle, posts/week, pillars, lead/backup, budget) · **Notifications** (in-app, email,
Telegram pairing and bot) · **Advanced** (verified facts, creative memory, outcomes, routines form,
developers, danger zone).

**New post** is a bottom sheet on phone and a right-hand drawer on desktop, opened by one primary
button that exists on Home and Calendar only. It has two modes on one screen: *Ask the team* (a
topic → brief → pipeline, today's `studio:create`) and *Write it myself* (today's compose with
per-platform overrides). Drafts, templates and CSV import are reachable from inside it, not from
the sidebar.

**Onboarding** replaces Set up for a fresh workspace: a four-step wizard (brand → connect one
account → pick an approver → first post) with the readiness line underneath. After it completes,
Set up's checklist lives at Settings → Advanced → Health for owners only.

URL names that must keep working (deep links in Telegram cards and emails): `studio:detail`,
`studio:job`, `calendar:calendar`, `client_portal:*`, `telegram:settings`. Old routes redirect;
nothing 404s during the beta.

## 4. Interface direction: professionals and Gen Z

The audience is a 22–35-year-old social media manager at a small agency who runs 4–8 client
brands, lives in Instagram and WhatsApp, approves things from a phone between meetings, and judges
a tool in the first 30 seconds. The design must feel as fast and self-explanatory as a consumer app
while reading as serious enough to show a client.

**Keep the existing design system, change how it is used.** "Quiet graphite + Pine"
(`docs/DESIGN_SYSTEM.md`) is a good professional base; the tokens, contrast pairs and status colours
stay. What changes is density, hierarchy, motion and mobile layout.

### Visual rules

- One primary action per screen, always Pine, always in the same place: bottom-right floating on
  phone, top-right on desktop.
- Type: one display face for headings with real weight (700–800) and tight tracking; body stays at
  16 px on phone, 15 px on desktop; no text below 13 px anywhere.
- Spacing on an 8 px grid; cards get 20 px padding on phone, 24 px on desktop; section gaps 32 px.
  Today's screens are denser than that and read as admin panels.
- Status is always icon + word + colour (already the rule); add a 2 px left border on list rows so
  a scan of 20 rows shows state without reading.
- Dark mode is a beta requirement, not a nice-to-have; the Layer-2 tokens already make it a
  one-file change.
- Platform previews (IG square, LinkedIn card, FB post) are real-size and pixel-faithful; they are
  the thing a Gen Z manager trusts most.
- Micro-interactions with purpose only: approve button fills and shows the fingerprint time; a post
  dragged on the calendar snaps and shows the new time; a thread message arriving slides in.
  150–200 ms, `prefers-reduced-motion` respected. No decorative animation.
- Empty states carry one sentence and one button, never an illustration-only state.

### Interaction rules

- Phone first. Every screen is designed at 390 px first, then widened. Bottom tab bar on phone
  (Home, Approvals, Calendar, Inbox, More), sidebar on desktop.
- Approvals is a swipeable stack on phone: one post at a time, preview full-bleed, Approve &
  schedule / Request changes as thumb-reach buttons. The fingerprint rule and the gate do not change.
- The team thread behaves like a chat app: composer pinned to the bottom, messages grouped by
  sender, a typing-style "The team is working" state, cards (brief, draft, receipt) rendered inline
  as rich bubbles.
- Keyboard shortcuts on desktop: `n` new post, `a` approve, `r` request changes, `/` search, `?`
  list them.
- Command palette (`Cmd/Ctrl-K`) searches posts, clients, settings and actions; it replaces the
  *More* menu.
- Every destructive or paid action confirms inline, not in a modal, and says what it costs or removes.
- Copy stays as `CLAUDE.md` demands: one sentence per screen, buttons say the act, status in words.
  Add: no jargon a new hire would not know — "brief", "pipeline", "revision" become "what we're
  making", "progress", "version".

### Client portal

Same system, white-labelled with the workspace's logo and colour. The client sees three things:
posts waiting for them (swipe stack), what went live (grid, IG-style), and a chat with the team.
Nothing else.

### Marketing site

Three pages, same tokens, dark hero. Home: one line of promise, a 20-second product video or
animated screen, three outcomes with numbers, a request-invite form. How it works: the idea → team
→ approve → publish flow drawn once. Request invite: a form that creates a Notification for the
owner. No feature grid, no platform logo wall, no GitHub buttons.

## 5. International-standard bar

Every gate below is a number a script can check, so Claude Code can run it, not argue about it.
These are the standards an international client's IT team or a procurement checklist actually asks for.

| Area | Standard | Gate (must pass) | Tool |
|---|---|---|---|
| Accessibility | WCAG 2.2 AA | 0 serious/critical axe violations on the 9 screens + portal; all flows keyboard-only; contrast ≥ 4.5:1 text, 3:1 UI | `@axe-core/playwright`, existing `test_a11y_sweep.py` |
| Performance | Core Web Vitals | Lighthouse mobile: Performance ≥ 90, LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1 on Home, Approvals, Calendar; total JS ≤ 150 KB gzipped | Lighthouse CI in GitHub Actions |
| Security | OWASP ASVS L2 | CSP with no `unsafe-inline` scripts; TOTP 2FA available to every member and required for owners; session timeout 14 days idle; dependency audit 0 high/critical; `gitleaks` clean | django-csp (already), `django-otp`, `pip-audit`, `npm audit`, gitleaks (already) |
| Privacy | GDPR / India DPDP Act 2023 | Export my data (JSON) and delete my account self-serve; cookie banner only if non-essential cookies exist (there are none → no banner); privacy policy and terms pages linked in footer and sign-up; data-processing note naming sub-processors (Railway, S3/R2, model provider, fal.ai, Telegram, Sentry) | Django views + a `docs/PRIVACY.md` the pages render |
| Internationalisation | Unicode CLDR | All copy through `{% trans %}` / `gettext` with an `en` catalogue compiled; dates, numbers and currency through Django's locale formatting; workspace timezone respected everywhere (already); RTL not required for beta | `makemessages`, `compilemessages` in CI |
| Reliability | 99.5 % beta SLO | `/health/` checks DB, cache, worker heartbeat (last `run_publish_cycle` < 60 s ago); Railway health check wired; Sentry on; a status note in Settings → Advanced → Health | existing `live_verify`, Railway |
| Data safety | Backups | Nightly Postgres backup to S3/R2 with a restore drill documented and run once before beta | existing `backup` command + Railway cron |
| Browser support | Baseline 2024 | Last 2 versions Chrome, Safari, Firefox, Edge; iOS Safari 16+; Android Chrome | Playwright projects: Desktop Chrome, iPhone 13, Pixel 7 |
| Content limits | Platform rules | Caption length, media size and aspect per platform validated before approval (exists) and shown in the preview (make visible) | existing `PlatformPost` validation |

**Not in beta scope** (say so to clients rather than half-do it): SOC 2, ISO 27001, SSO via SAML,
RTL languages, full translation beyond English. Hindi UI is a post-beta item once the catalogue exists.

**Already there and only needs wiring into CI:** HSTS, secure cookies, nosniff, rate limits,
encrypted credentials, the a11y HTML sweep, the recolor palette check, gitleaks, and the migration check.

## 6. Build pipeline

Seven phases, each one Claude Code session or a few, each ending in a gate that must pass before
the next starts. Phases 1 and 2 are deliberately boring: nothing visual changes until the cut is
done and the tests that guard the invariants are green on the trimmed tree. Phase 3 is the only
phase that changes what users see; everything before it exists so that phase can be fast and safe.

| Phase | Length | Gate |
|---|---|---|
| 0 · Agree the cut | ½ day | spec approved · migration check passes |
| 1 · Test harness first | 2 days | CI green · 12 e2e tests pass on the old UI |
| 2 · Cut and merge, no restyling | 3 days | full pytest green · no 404 in the product map |
| 3 · Rebuild the nine screens | 2 weeks | per screen: axe 0 serious · Lighthouse ≥ 90 |
| 4 · Standards | 1 week | every row of section 5 passes its tool |
| 5 · Platform connections | 3 days | four real test posts published and deleted |
| 6 · Beta release | 2 days | definition of done in section 8 |

### Phase 0 — Agree the cut (½ day)

Skills: `brainstorming`, then `product-management:write-spec`.

- [ ] Read `CLAUDE.md`, `docs/PRODUCT_MAP.md`, `docs/DESIGN_SYSTEM.md` and this plan
- [ ] Confirm every *Decision* in section 2 with the owner; write `docs/specs/00-cut.md`
- [ ] Add `AgencySettings.features` (JSON, `db_default={}`) with keys `blog`, `queues`, `templates`,
      `extra_providers`, `advanced_settings`; a `feature_enabled(workspace, key)` helper in `apps/common`

Gate: spec approved; migration passes `makemigrations --check`.

### Phase 1 — Test harness first (2 days)

Skills: `engineering:testing-strategy`, `test-driven-development`.

- [ ] Add Playwright (`tests/e2e/`), three device projects, a seeded workspace fixture built from
      `apps/studio/tests/conftest.py::fake_team`
- [ ] Write the 12 golden-path e2e tests in section 7 against the *current* UI so the rebuild has a safety net
- [ ] Add `@axe-core/playwright` to each e2e test; add Lighthouse CI config with the budgets in section 5
- [ ] Add `pip-audit`, `npm audit --audit-level=high`, `compilemessages` to `ci.yml`; make CI required on `main`

Gate: CI green with all new jobs; 12 e2e tests pass on the old UI.

### Phase 2 — Cut and merge, no restyling (3 days)

Skills: `make-plan` → `do`, `engineering:code-review`.

- [ ] Navigation: new sidebar/bottom bar with the six items; *More* removed; command palette stub
- [ ] Routes: `/approvals/`, `/settings/` (tabs) and `/studio/activity/` as new views that *include*
      the existing partials; old URLs 301 to them
- [ ] Feature flags applied to Blog, Queues, Templates/Categories/Tags, extra providers, Advanced settings
- [ ] Intelligence, API keys, MCP, OAuth server, workflow_* removed from nav (code stays; URLs keep
      working, section 2 ★)
- [ ] Marketing app reduced to three views

Gate: full pytest suite green (the invariants' tests untouched); 12 e2e tests updated to the new
routes and green; no 404 for any URL listed in `PRODUCT_MAP.md`.

### Phase 3 — Rebuild the nine screens (2 weeks)

Skills: `impeccable` (load first, every screen), `frontend-design`, `design-is` for the audit at the
end of each screen.

Order, because each screen's components feed the next: 1 New post sheet → 2 Home → 3 Approvals
(swipe stack) → 4 Calendar → 5 Post page → 6 Inbox → 7 Analytics → 8 Activity → 9 Settings +
onboarding wizard → 10 Client portal → 11 Marketing.

Per screen: build at 390 px first; one primary action; dark mode; `prefers-reduced-motion`; run
`impeccable` audit, `design-is` audit, axe, Lighthouse; screenshot into `tests/e2e/__screenshots__/`
for the visual regression baseline.

Gate per screen: axe 0 serious; Lighthouse ≥ 90 mobile; e2e for that screen green;
`recolor.py --check` clean; owner sign-off on the screenshot pair (before/after).

### Phase 4 — Standards (1 week)

Skills: `engineering:architecture` (ADR for 2FA and i18n), `do`.

- [ ] TOTP 2FA with `django-otp`; required for owners; recovery codes
- [ ] Data export + account deletion self-serve
- [ ] `{% trans %}` sweep over the nine screens + portal; `en` catalogue; `compilemessages` in Docker build
- [ ] `/health/` extended with worker heartbeat; Railway health check pointed at it
- [ ] Privacy, terms and sub-processor pages
- [ ] Backup to S3/R2 nightly; one restore drill, written up in `docs/LIVE_OPERATIONS.md`

Gate: every row in section 5 passes its tool.

### Phase 5 — Platform connections for the beta (3 days)

- [ ] X, Pinterest, Google Business Profile, LinkedIn connect flows verified end to end with one
      real post each, deleted afterwards
- [ ] Connect screen shows only the seven beta platforms unless `extra_providers` is on
- [ ] Token health check surfaced on Settings → Accounts with a *Reconnect* button that works on a phone

Gate: four real test posts published and deleted; health check green for each.

### Phase 6 — Beta release (2 days)

Skills: `engineering:deploy-checklist`, `finishing-a-development-branch`,
`product-management:stakeholder-update`.

- [ ] Railway: web + worker + Postgres + Redis + S3/R2; `SIGNUP_MODE=invite`; Sentry DSN
- [ ] Seed the ten beta workspaces; invite owners; send the stakeholder update
- [ ] Rollback trigger written: any failed `run_publish_cycle` for 5 min → redeploy previous image

Gate: definition of done in section 8.

## 7. Testing pipeline

The existing 250-file pytest suite guards the backend and stays the slowest, most important layer.
The rebuild adds four layers above it so that a visual change can never silently break an approval,
and so that the standards in section 5 are checked by machines on every pull request.

| Layer | What it proves | Where | Runs | Gate |
|---|---|---|---|---|
| Unit + integration (pytest, Postgres) | Invariants, services, providers (mocked), tasks never raise | `apps/*/tests`, `tests/` | every PR, ~8 min | 100 % pass; coverage not below `main` |
| UI state (Node) | The thread's state machine | `tests/js/*.test.cjs` | every PR | pass |
| Template sweep | Dialogs labelled, contrast greys, control names, no old palette | `test_a11y_sweep.py`, `tools/recolor.py --check` | every PR | pass |
| **E2E golden paths (Playwright)** | The 12 flows below, on 3 devices | `tests/e2e/` (new) | every PR, ~6 min | pass on all 3 projects |
| **Accessibility (axe in e2e)** | WCAG 2.2 AA on every screen the e2e touches | inside each e2e test | every PR | 0 serious/critical |
| **Visual regression** | A screen did not change by accident | Playwright `toHaveScreenshot` | every PR | diff ≤ 0.1 % or reviewer approves |
| **Lighthouse CI** | Performance budgets | `.lighthouserc.json`, 3 URLs mobile | every PR to `main` | scores in section 5 |
| Security | Secrets, deps, CSP | gitleaks (exists), `pip-audit`, `npm audit`, a CSP-header test | every PR | 0 high/critical; CSP has no `unsafe-inline` script |
| Live verify | Worker schedules, isolation, provider readiness on the deployed app | `manage.py live_verify` | after every Railway deploy | all checks pass |

### The 12 golden-path e2e tests

Each runs as owner, as staff and (where it applies) as client, on Desktop Chrome, iPhone 13 and
Pixel 7. Providers are mocked at the HTTP layer with `MockTransport`; the model client is the faked
team from `conftest.py`, so the suite costs nothing and runs offline.

1. Sign in with email, then with Google (mocked), land on Home
2. Onboarding wizard: brand → connect one account (mocked OAuth) → choose approver → first post queued
3. Ask the team for a post from Home; the brief card appears; *Go ahead*; the draft reaches *Waiting for you*
4. Write a post myself with a per-platform override and an image from the library; submit for review
5. Approve & schedule from the Approvals stack; the post shows on the Calendar at that time with the fingerprint
6. Request changes with feedback; the revision appears; the earlier approval is withdrawn
7. Drag a post on the Calendar as an approver; the new time is approved; as staff, it is not
8. Client portal via magic link: sign off on a post; it completes the client stage but is not published
9. Inbox: a mocked comment arrives; assign, reply, mark done
10. Settings: change brand colour and timezone; the preview and the calendar reflect both
11. Workspace isolation: a member of workspace A gets 404 on every workspace-B URL (ports
    `live_verify isolation.workspace` to e2e)
12. 2FA: enable TOTP, sign out, sign in with a code; an owner without 2FA is prompted

### Rules for Claude Code when writing tests

- Red first: a failing test before the change, for every task that touches behaviour (`test-driven-development`).
- Never weaken an invariant test to make UI work pass; if a template change breaks
  `test_a11y_sweep.py`, the template is wrong.
- E2E selectors use `data-testid`, never CSS classes or copy, so `impeccable` can restyle freely.
- Screenshots are updated only in a commit whose message starts with `visual:` and carries the
  before/after pair in the PR.
- A flaky e2e test is quarantined the same day with an issue, not retried in CI.
- Run the full pytest suite before every phase gate; the one-app subset (`pytest apps/studio`) is for inner loops.

## 8. Definition of done

The beta is done when a new agency owner can go from invite to a published, client-approved post on
a phone without reading anything, and every number in section 5 is green in CI.

- [ ] Six-item navigation live; every URL in `PRODUCT_MAP.md` resolves or redirects
- [ ] Nine screens + portal + three marketing pages rebuilt and signed off on the before/after screenshots
- [ ] 12 golden-path e2e tests green on three devices; axe 0 serious; Lighthouse ≥ 90 mobile on Home, Approvals, Calendar
- [ ] Full pytest suite green; invariant tests unchanged
- [ ] 2FA, data export, account deletion, privacy and terms pages live
- [ ] X, Pinterest, GBP and LinkedIn verified with one real post each
- [ ] Nightly backup running; one restore drill done
- [ ] `docs/PRODUCT_MAP.md`, `CLAUDE.md` and `docs/DESIGN_SYSTEM.md` updated to describe the new navigation
- [ ] Ten beta workspaces seeded; owners invited; stakeholder update sent
