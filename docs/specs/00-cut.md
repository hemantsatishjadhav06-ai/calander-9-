# 00 — The beta cut

Phase 0 of [`docs/BETA_PLAN.md`](../BETA_PLAN.md). Status: **confirmed by the owner, 24 Oct 2026** (the
Decision column of section 2 and the five resolutions below). Gate: this spec approved;
`python manage.py makemigrations --check --dry-run` passes.

This spec decides *what* the beta shows. It changes nothing a person sees: Phase 0 only adds the
switch that later phases read. Phase 2 applies the cut; Phase 3 restyles what survives.

## Problem

SM Bean's backend is sound, but its surface is three to four times what a 5–10 agency closed beta
will use: three ways to start a post (Home thread, Create Idea, Compose), three settings surfaces
(Set up, Settings hub, workspace settings), approvals reachable from four places, a 16-item sidebar,
and public pages that sell a 14-platform tool instead of the agency product. A 25-year-old social
media manager judging the tool in its first 30 seconds on a phone sees an admin panel. Cutting the
surface first keeps the rebuild (Phase 3) to nine screens instead of thirty.

## Goals

1. **Nine screens, one job each.** A new member can name every screen's job after one look:
   Home, Approvals, Calendar, Inbox, Analytics, Activity, Settings, plus the client portal and Blog
   where it is switched on.
2. **One way to start a post** (New post, from Home and Calendar) and **one settings surface**
   (Settings, with tabs).
3. **Nothing breaks.** Every URL named in `docs/PRODUCT_MAP.md` and every deep link in Telegram
   cards and emails resolves or redirects; nothing 404s during the beta.
4. **Nothing is deleted.** Features hidden for the beta come back per workspace with one switch.
5. **The nine invariants in `CLAUDE.md` stay exactly as they are**, enforced by the same tests.

## Non-goals

- **No restyling in Phases 0–2.** The cut and the look are separate so a regression has one cause.
- **No code deletion during the beta.** Cut means out of navigation and marketing; the code stays
  until after the beta (old `studio:workflow_*` redirects included).
- **No change to approval, publishing, isolation, budgets or Telegram security.** The gate,
  fingerprints, scoped managers, untrusted-text wrappers and one-use buttons are out of scope.
- **No per-person feature switches.** Flags are per workspace; roles and permissions already
  decide what a person may do.
- **No self-serve flag UI in Phase 0.** The owner sets flags in the Django admin until Settings →
  Advanced exists (Phase 2/3).

## Who it is for

| Person | What the cut gives them |
|---|---|
| Social media manager at a small agency (staff, approver) | Six sidebar items, one New post, approvals as one stack, a phone-first layout |
| Agency owner | One Settings screen; onboarding instead of a checklist; power features behind *Advanced* |
| The agency's client | The portal only: what waits for them, what went live, a chat with the team |
| Beta operator (us) | Hidden features switched on per agency without a deploy |

## User stories

- As a manager, I want one obvious place to start a post so that I never wonder whether Create
  Idea, Compose or the Home thread is the right one.
- As an approver on a phone, I want every post that needs me in one place so that I can clear them
  between meetings.
- As an agency owner, I want every setting on one screen with tabs so that I do not hunt across
  Set up, the Settings hub and workspace settings.
- As an agency owner whose client has a blog, I want Blog to stay in my sidebar so that the cut
  does not take away a feature we pay for.
- As a manager whose agency already connected a Threads or TikTok account, I want those posts to
  keep publishing so that hiding the platform from the connect screen does not break live work.
- As anyone holding an old link from Telegram or an email, I want it to still open the right page.

## The cut (confirmed)

Keep = stays as is (and is restyled in Phase 3). Merge = folds into another screen. Hide (flag) =
the code stays and a workspace flag turns it on. Cut = out of navigation and marketing; code stays.

| # | Surface | Today | Decision | Where it goes |
|---|---|---|---|---|
| 1 | Home (Today card, team thread, In progress) | `studio:index` | **Keep** | The daily screen and the only place to start a post |
| 2 | Calendar (month/week/day, list tabs) | `calendar:calendar` | **Keep** | Week view default on desktop, agenda list on phone |
| 3 | Inbox (comments, DMs, reviews, SLA) | `inbox:feed` | **Keep** | Sentiment and SLA move behind a filter |
| 4 | Analytics | `analytics:index` | **Keep** | Four KPI cards, one trend, the posts table |
| 5 | Routines | `studio:routines` | **Keep** | Listed in Activity with the three presets; the free-form form under Settings → Advanced (resolution 5) |
| 6 | Media library | `media_library` | **Keep** | A picker inside New post and a plain grid; folder management UI cut |
| 7 | Client portal | `/portal/` | **Keep** | Same visual pass; posts waiting, what went live, chat |
| 8 | Telegram transport | `apps/telegram` | **Keep** | Its settings move to Settings → Notifications |
| 9 | Autopilot (weekly planning) | `studio:autopilot` | **Keep** | One toggle and posts/week on Settings; *Plan now* on Home |
| 10 | Google sign-in · magic links · 14-day organisation deletion grace | `accounts`, `client_portal` | **Keep** | TOTP 2FA added in Phase 4 |
| 11 | Set up checklist | `studio:setup` | **Merge** | The onboarding wizard (first 10 minutes) and the owner's Health page under Settings → Advanced |
| 12 | Approvals | 4 routes (Calendar list tab, post page, Telegram card, portal) | **Merge** | One `/approvals/` screen; post page and Telegram card stay as entry points into it |
| 13 | Create Idea · Drafts · Compose | 3 entry points in `composer` | **Merge** | One **New post** sheet from Home and Calendar; Drafts become a Calendar list tab only |
| 14 | Team page (live board, roster, 24 h charts) | `studio:team` | **Merge** | Live strip on Home (already there); roster and job pages under **Activity** |
| 15 | Settings hub (Brand, Facts, Memory, Outcomes, Autopilot, Telegram, Budget) | `studio:settings_hub` | **Merge** | One Settings screen with tabs; Memory and Outcomes behind *Advanced* |
| 16 | Workspace settings · Approvals settings · Members · Clients · Social accounts | 5 pages | **Merge** | The same Settings tabs |
| 17 | Notifications page and preferences | `notifications:list` | **Merge** | A bell dropdown and Settings → Notifications |
| 18 | Marketing site | `apps/marketing`, 7 templates | **Merge** | Three pages: Home, How it works, Request invite; Developers and Platforms hidden; Pricing redirects to Request invite (resolution 4) |
| 19 | Blog & SEO | `apps/blog` | **Hide (flag `blog`)** | On where the workspace already has a blog website (resolution 1) |
| 20 | Queues · Posting schedule · Recurrence | `calendar` More | **Hide (flag `queues`)** | Posting schedule stays visible (the scheduler needs the slots); queues and recurring rules hidden |
| 21 | Templates · Categories · Tags · CSV import | `composer` More | **Hide (flag `templates`)** | CSV import stays (inside New post); templates, categories and tags hidden |
| 22 | Verified facts · Creative memory · Outcomes | 3 settings pages | **Hide (flag `advanced_settings`)** | Behind Settings → *Advanced* |
| 23 | Providers: Bluesky, Mastodon, DEV.to, Threads, TikTok | 5 of 14 | **Hide (flag `extra_providers`)** | Hidden from the connect screen; accounts already connected keep working (resolution 2) |
| 24 | Intelligence add-on and playground | `apps/intelligence` | **Cut** | Out of navigation; it stays off unless its five variables are set |
| 25 | Agent API · API keys · MCP server · OAuth server | 4 apps | **Cut** | Out of the beta navigation; URLs keep working; one *Developers* link in Settings → Advanced (resolution 3) |
| 26 | Older workflow endpoints | `studio:workflow_*` | **Cut** | Redirects kept during the beta; deleted after |

### Resolutions the owner confirmed

1. **Blog for existing workspaces.** Blog shows wherever the workspace already has an enabled blog
   website (today Neopolis and More Space); every other flag starts off.
2. **TikTok** joins Bluesky, Mastodon, DEV.to and Threads behind `extra_providers`. The beta's seven
   platforms are Facebook, Instagram, LinkedIn, YouTube, Google Business Profile, Pinterest and X.
   Hiding affects the connect screen only: accounts already connected keep publishing, syncing
   and appearing in the composer.
3. **Agent API, API keys, MCP and OAuth** leave the navigation only. Their URLs keep working so
   connected clients do not break and the *Developers* link has somewhere to go.
4. **Pricing** redirects to Request invite. Privacy and Terms stay linked in the footer and at
   sign-up (section 5, privacy row).
5. **Routines** are listed in Activity with the three presets (Morning briefing, Monday plan, Draft
   replies to new comments); the free-form instruction form lives under Settings → Advanced.

## Target information architecture (applied in Phase 2)

| Screen | Route | One job | Replaces |
|---|---|---|---|
| Home | `/studio/` | See what needs me today, talk to the team, start a post | Home, live strip from Team, Create Idea |
| Approvals | `/approvals/` | Review and approve the exact post, time and destinations | Calendar Approvals tab, approvals partials |
| Calendar | `/calendar/` | See what goes out when; move it; open a post | Calendar, Drafts list, Queue list |
| Inbox | `/inbox/` | Answer comments, DMs and reviews | unchanged |
| Analytics | `/analytics/` | Know what worked this month | unchanged, trimmed |
| Activity | `/studio/activity/` | See the team at work and every job's timeline | Team page, job pages, Routines |
| Settings | `/settings/` (gear, bottom of sidebar) | Everything configured, in tabs | Set up, Settings hub, 5 workspace pages, Telegram settings, notification preferences |
| Blog (flag) | `/blog/` | A seventh item only when `blog` is on | unchanged |

Every route above lives under `/workspace/<workspace id>/`. Settings tabs, left to right: Brand ·
Accounts · Team & clients · Approvals · Autopilot · Notifications · Advanced. Phone: a bottom tab
bar (Home, Approvals, Calendar, Inbox, More); desktop: the sidebar.

**URL contract.** These names keep resolving to a working page because Telegram cards and emails
link to them: `studio:detail`, `studio:job`, `calendar:calendar`, `client_portal:*`,
`telegram:settings`. Every other old route answers with a permanent redirect to its new home.

## Requirements

### P0 — Phase 0 (this phase)

**R1. A workspace feature switch.** `AgencySettings.features`: a JSON object, default `{}` in Python
and in the database (invariant 8, so the web and worker can run one release apart).

- [ ] The field exists with `default=dict` and a database default of `{}`; the migration is
      additive and `makemigrations --check --dry-run` reports no changes after it.
- [ ] Old code that inserts an `AgencySettings` row without the field still works (database default).

**R2. One helper decides.** `apps/common/features.py`: `feature_enabled(workspace, key) -> bool`
and the tuple `FEATURE_KEYS = ("blog", "queues", "templates", "extra_providers", "advanced_settings")`.

- Given an unknown key, when the helper is called, then it raises `ValueError` (a typo fails loudly
  in tests instead of silently hiding a feature).
- Given `features[key]` is a boolean, then that value is the answer.
- Given the key is absent (or not a boolean), then the default applies: `blog` is on when the
  workspace has an enabled `BlogSite`; every other key is off.
- Given the workspace has no `AgencySettings` row, then the defaults apply and no row is created.
- The helper is read-only, scoped to the one workspace, and costs at most two small queries.

**R3. Owners can set flags before there is a screen for it.** `AgencySettings` is registered in the
Django admin with `features` editable (staff only).

- [ ] Saving `{"queues": true}` for one workspace turns `feature_enabled(ws, "queues")` on for that
      workspace only.

**R4. Nothing a person sees changes in Phase 0.** No template, view or URL reads the helper yet;
the full suite stays green with the invariant tests untouched.

### P1 — Phase 2

- Navigation (six items, the gear, Blog when `blog` is on), the new `/approvals/`, `/settings/` and
  `/studio/activity/` views that include the existing partials, 301 redirects from old routes, the
  flags applied to every row marked Hide above, and the marketing app cut to three views.
- Accounts on a hidden provider keep working everywhere except the connect screen.

### P2 — later phases (designed for, not built now)

- A Settings → Advanced → *Features* panel for owners (Phase 3), writing the same JSON.
- A management command to set flags while seeding the ten beta workspaces (Phase 6).
- How `extra_providers` combines with the existing `LAUNCHED_PLATFORMS` setting on the public
  pages and the connect screen (Phase 5): the flag hides from a workspace; the setting decides what
  is offered at all.

## Success metrics

- **Leading (end of Phase 2):** 6 sidebar items (7 with Blog) instead of 16; one entry point to
  start a post instead of three; one settings surface instead of three; zero 404s across every URL
  in `docs/PRODUCT_MAP.md`; the full pytest suite green with invariant tests unchanged.
- **Lagging (beta, first month):** a new agency owner goes from invite to a client-approved,
  published post on a phone without reading anything (section 8 definition of done); fewer than
  one "where is…?" support question per agency per week.

## Open questions

None block Phase 0.

- *(engineering, Phase 2)* Which old routes get a 301 and which keep rendering inside the new
  screen (the five URL-contract names keep rendering).
- *(engineering, Phase 5)* The `extra_providers` / `LAUNCHED_PLATFORMS` split above.

## Phasing

Phase 0 (this spec + the flag field and helper) → Phase 1 (test harness on the old UI) → Phase 2
(cut and merge, no restyling) → Phase 3 (rebuild the nine screens) → Phase 4 (standards) → Phase 5
(platform connections) → Phase 6 (beta release). Each phase ends at its gate in `docs/BETA_PLAN.md`
section 6; the next starts only when the owner says so.
