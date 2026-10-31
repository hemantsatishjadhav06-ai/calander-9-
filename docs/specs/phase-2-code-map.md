# Phase 2 code map (read-only snapshot, 31 Oct 2026)

Eight read-only readers mapped the code Phase 2 touches, before any Phase 2 change, at commit `5e242dc`. Line numbers are a snapshot; confirm each before editing. Used by [`phase-2.md`](phase-2.md).

# AREA nav

# Navigation map for Phase 2 (read-only survey, branch `claude/trusting-dijkstra-m7nul1`)

The whole desktop and phone navigation lives in `templates/base.html`. Nothing exists yet for a phone bottom bar, a command palette or a bell dropdown. No template tag computes the active item: each link checks `request.resolver_match` inline. Two Phase 2 choices are already fixed by invariant tests: `studio:team`, `studio:index`, `studio:thread` and `studio:autopilot` must keep answering 200, and `studio:setup` must keep its name. Details are in section 10.

## 1. Shell layout (`templates/base.html`)

| Lines | Element | Notes |
|---|---|---|
| 26-35, 38-66 | `window.bbSidebarStorage` (localStorage `sidebarCollapsed`), pre-Alpine `.sidebar-initial` CSS | Phone at ≤1023px: a 280px off-canvas drawer |
| 326-332 | Root `x-data="{ sidebarCollapsed, mobileMenuOpen, isDesktop }"`, `@keydown.escape.window="mobileMenuOpen = false"` | The one global keyboard hook |
| 335-344 | Phone backdrop `x-show="mobileMenuOpen"` | |
| 347-361 | `<aside id="app-sidebar">` with `:inert="!isDesktop && !mobileMenuOpen"`, `:role` dialog, `:aria-modal`, `x-trap.noscroll` | Clicking any `<a>` inside closes the drawer on phone (line 361) |
| 363-444 | Workspace switcher (`x-ref="wsBtn"`, Escape handler) | Lists `sidebar_workspaces` → `calendar:calendar` (403); "Create workspace" if `can_create_workspace` (420-430, dispatches `open-create-ws`); **"Workspace settings" → `workspaces:settings`** (433) |
| 446-702 | "+ New" (`sidebarNewMenu()`, defined at 1251) | `data-testid="sidebar-new-toggle"` (453). Menu: **Post** → `composer:compose` (469); **Idea** button `data-testid="sidebar-new-idea"` (479) opens a teleported modal (490-700) that posts to `composer:idea_create` (502). Uses `sidebar_idea_columns` / `sidebar_idea_tags`, `composer:tag_create` (1351), `composer:idea_upload_media` (1456) |
| 705-815 | `<nav class="sidebar-nav" aria-label="Main">`, `{% block sidebar_nav %}` 706-814 | The entries in section 2 |
| 817-906 | Organisation footer (`orgMenuOpen`) | Collapse/expand buttons; popover with **Manage Team** → `members:list` (877), **Settings** → `accounts:settings` (886), Log out form `data-testid="account-sign-out"` (895-899) |
| 911-946 | Phone top bar (`lg:hidden`) | `data-testid="mobile-menu-toggle"`, `aria-label="Toggle menu"`, `aria-controls="app-sidebar"` (913). Approvals badge link → `calendar:calendar?mode=list&tab=approvals` when `sidebar_pending_approvals` (937-942), else an empty spacer `<div class="w-11 flex-shrink-0" aria-hidden="true">` (944) |
| 948-969 | `<main id="main-content">` with `pb-12`, messages, scroller `relative … -m-1 p-1` | |
| 989-1012 | `notificationBadge(initial)` | Polls `fetch('{% url "notifications:unread_count" %}')` every 60s and on the `notifications-read` event. Plain fetch, not HTMX. No `hx-boost` anywhere, so every nav link is a full page load |

- **CSS:** `theme/static_src/src/styles.css` 366-441 (`.sidebar-nav-item`, `.active` / `[aria-current="page"]`, `.sidebar-badge(.is-turn)`, `.sidebar-more*`), 873-885 (`.ui-segmented` / `.ui-segment`), 1067 (forced colours).
- **`data-testid` hooks in base.html:** `sidebar-new-toggle` 453, `sidebar-new-idea` 479, `idea-close` 499, `idea-title` 598, `idea-description` 599, `idea-emoji-toggle` 636, `idea-emoji-search` 645, `idea-emoji-option` 651, `notification-badge` 747, `account-sign-out` 899, `mobile-menu-toggle` 913. The nav links themselves have no testids.

## 2. Current sidebar and More entries

Each link uses `{% with match=request.resolver_match %}`.

| Line | Label | URL name → path | Active when |
|---|---|---|---|
| 710 | Home | `studio:index` → `/workspace/<id>/studio/` | `match.app_name == 'studio' and match.url_name != 'setup'`. This lights **every** studio page: team, routines, settings_hub, brand, autopilot, memory, trust, outcomes, detail, job, thread |
| 714 | Approvals (badge `.is-turn` `sidebar_pending_approvals`; aria-label "Approvals, N waiting") | `calendar:calendar` + `?mode=list&tab=approvals` | `url_name == 'calendar' and request.GET.tab == 'approvals'` |
| 720 | Calendar | `calendar:calendar` → `/workspace/<id>/calendar/` | `url_name == 'calendar' and request.GET.tab != 'approvals'` |
| 724 | Inbox (badge `sidebar_unread_inbox_count`) | `inbox:feed` | `app_name == 'inbox'` |
| 729 | **Blog &amp; SEO** (always shown) | `blog:list` → `/workspace/<id>/blog/` | `app_name == 'blog'` |
| 733-738 | Analytics, only `{% if analytics_enabled_platforms %}` (a global setting, not per workspace) | `analytics:index` | `app_name == 'analytics'` |
| 742-748 | Notifications (`x-data="notificationBadge(N)"`) | `notifications:list` → `/notifications/` (not workspace-scoped) | `url_name == 'list' and app_name == 'notifications'` |
| 752 | **Set up** (uses the cog icon) | `studio:setup` → `/workspace/<id>/studio/setup/` | `url_name == 'setup'` |
| 758 | `<details class="sidebar-more" data-sidebar-more[ open]>`, summary "More", `aria-label="More pages"` | — | Open when url_name is one of `create_landing`, `drafts_list`, `queue_list`, `queue_detail`, `posting_slots`, `template_list`, `category_list`, `csv_upload`, or `app_name == 'media_library'` |
| 765 | More › Ideas | `composer:create_landing` → `…/create/` | `create_landing` |
| 769 | More › Drafts | `composer:drafts_list` → `…/drafts/` | `drafts_list` |
| 773 | More › Queues | `calendar:queue_list` → `…/calendar/queues/` | `queue_list` or `queue_detail` |
| 777 | More › Posting schedule | `calendar:posting_slots` | `posting_slots` |
| 781 | More › Templates | `composer:template_list` | `template_list` |
| 785 | More › Categories | `composer:category_list` | `category_list` |
| 789 | More › Import from CSV | `composer:csv_upload` → `…/import/csv/` | `csv_upload` |
| 793 | More › Media | `media_library:index` → `…/media/` | `app_name == 'media_library'` |
| 807-813 | Intelligence, only with `INTELLIGENCE_ENABLED and request.org` | `intelligence:playground` (org-scoped) | `app_name == 'intelligence'` |

That makes 8 top items plus 8 under More: the "16" in `00-cut.md`.

## 3. Context data the navigation reads

Registered in `config/settings/base.py:152-162`:

- **`apps.common.context_processors.sidebar_context` (52-184)**
  - Gives `sidebar_workspaces` (69-77), `can_create_workspace` (168-171), `sidebar_unread_inbox_count` (133-140), `sidebar_pending_approvals` (142-155: distinct posts with a `PlatformPost` in `pending_review` or `pending_client`), `sidebar_idea_columns` / `sidebar_idea_tags` (157-165) and `analytics_enabled_platforms` (66).
  - It also queries `sidebar_channels`, `sidebar_unhealthy_channels` and `sidebar_connectable_platforms` (79-131), but **no template renders them**. Only `test_navigation_and_guards.py:56` reads `sidebar_connectable_platforms` from the context.
- **`apps.notifications.context_processors.unread_notification_count`** gives `unread_notification_count`.
- **`apps.intelligence.context_processors.intelligence_flag`** gives `INTELLIGENCE_ENABLED`.
- **`apps.onboarding.context_processors.onboarding_checklist`** is cached 60s per workspace.
- **`request.workspace`** comes from `apps/members/middleware.py`. `__call__` (86-101) falls back to `user.last_workspace_id` on pages without a workspace in the URL (`/notifications/`, `/members/`, `/accounts/settings/`), so the workspace items render there too. Portal sessions also go through this fallback, so `sidebar_context` runs on portal pages even though `portal_base.html` does not show it. `process_view` (105-158) resolves the workspace from the URL kwarg.
- **Plain clients:** `base.html` never checks `is_plain_client` (`apps/studio/views.py:51`). A client with a password session lands on the Calendar (`apps/accounts/views.py:111-121`) and sees the full sidebar, where Home etc. answer 403.

## 4. Agency four-tab strip

- **Template:** `templates/components/agency_tabs.html`: `<nav aria-label="Agency"><div class="ui-segmented">` with `.ui-segment` links and `aria-current="page"`.
- **Builder:** `apps/studio/dashboard.py:56-79` `tabs(workspace, active, perms)`. It returns Home (`studio:index`), Routines (`studio:routines`, dropped without `create_posts`), Team (`studio:team`) and Settings (`studio:settings_hub`). `SETTINGS_PAGES` (line 50) and `"telegram"` light Settings; `"workflow"` and `"thread"` light Home. `settings_cards()` (82-100) builds the Settings hub cards.
- **Callers:** `views.py:178` (overview), `views.py:399` (`[]` on the brief page), `views_agency.py:68` (job page → "overview"), `views_live.py:44` (team), `views_routines.py:57`, `views_setup.py:516` (settings), `views_autopilot.py:122`, `views_memory.py:109`, `views_trust.py:154`, `views_outcomes.py:74`, `views_chat.py:149` (thread), `customer_workflow.py:474`, `apps/telegram/views.py:99`.
- **Included by:** `studio/index.html:17`, `routines.html:13`, `team.html:23`, `settings_hub.html:12`, `autopilot.html:30`, `memory.html:31`, `trust.html:9`, `outcomes.html:9`, `thread.html:13`, `telegram/settings.html:27` (only when `internal`).
- **Studio routes:** `apps/studio/urls*.py`
  - `team/` = `studio:team` (`views_agency.team_roster` → `views_live.team_page`), `jobs/<uuid>/` = `studio:job`, `team/board/` = `studio:team_board`.
  - `team_board` is the HTMX refresh. It uses `render_to_string` with no request, so **no context processors run**.
  - `setup/` = `studio:setup`, `settings/` = `studio:settings_hub`, `routines/` = `studio:routines`.
  - `workflow*` = `studio:workflow*`; `studio:workflow` already answers 302 to Home.
  - **No `activity/` route exists.**

## 5. Pages that replace the sidebar

These override `{% block sidebar_nav %}`, so the main items disappear on them:

- **`templates/layouts/settings.html`**, extended by `accounts/settings.html`, `organizations/settings.html`, `organizations/workspaces.html`, `organizations/cross_calendar.html`, `members/list.html`, `api_keys/list.html`, `media_library/shared_library.html`.
  - Line 7 is labelled "Settings" but links to `calendar:calendar`.
  - Profile 13, Preferences 17, General 23, Workspaces 27, Team members 31, **API keys** 35 (`api_keys:list`), All calendars 39, Media library 43.
  - The active item is the view's `settings_active` context value.
- **`templates/layouts/workspace_settings.html`**, extended by `workspaces/settings.html`, `workspaces/approvals_settings.html`, `social_accounts/list.html`, `client_portal/admin/client_list.html` and **`media_library/library_index.html`**. So More › Media opens a page with a different sidebar.
  - Line 7 is labelled "Workspace settings" and links to the calendar.
  - General 13, Social accounts 17, Media library 21, Approvals 25, Client portal 29.
- **`templates/telegram/settings.html:4-10`**: for non-internal people it hides `.sidebar-new-wrap` through `extra_head` and replaces the nav with "My Telegram connection". `telegram:settings` is a URL-contract name.

## 6. Phone

- The phone menu is the same `<aside>`, opened by `mobile-menu-toggle`. There is no bottom bar.
- The client portal has its own tab navigation in `templates/client_portal/portal_base.html:47-71` (`data-testid="portal-nav-approvals"`).
- **Fixed-bottom elements a bottom bar would collide with:**
  - `studio/detail.html:72` and `:80`: the phone decision bar `lg:hidden fixed inset-x-0 bottom-0 z-30` with **Approve & schedule**.
  - The base toast at `base.html:296`.
  - `calendar/calendar.html:344` (bulk bar) and `calendar/partials/publish_approvals.html:50`.
  - `media_library/library_index.html:91`, `composer/compose.html:1978`, and the sticky bar at `blog/post_form.html:178`.

## 7. Where new pieces would attach

- **Command palette stub:**
  - The key handler belongs on the root `x-data` at `base.html:328`, next to the Escape handler. `compose.html:297-298` already binds `meta.s` and `ctrl.s`.
  - The dialog should follow the idea-modal pattern (`<template x-teleport="body">`, `role="dialog" aria-modal="true" aria-label`, `x-trap.noscroll`, around 490-500), because `test_a11y_sweep.test_every_modal_is_a_labelled_trapped_dialog` requires it.
  - Trigger spots: the `sidebar-new-wrap` row (446) on desktop, and the phone top-bar spacer at 944.
  - There is no search endpoint today.
- **Blog as the seventh item:**
  - Wrap `base.html:729-732` in a condition such as `{% if nav_features.blog %}`. The target IA calls it "Blog"; today's label is "Blog &amp; SEO".
  - `00-cut.md` gives no position for it. Today it sits between Inbox and Analytics.
- **Reading `feature_enabled` once per request:**
  - `apps/common/features.py:35-46` costs one query on `AgencySettings.features`, plus a `BlogSite` exists check when the switch is unset. `test_features.py` caps this at two queries.
  - The natural place is inside the `if workspace:` block of `sidebar_context` (84-165), or memoised on `request` so views and templates share it. This is the `features_for()` the spec suggests.
  - Context processors run on **every** `render(request, …)`, including HTMX partials and portal pages (see section 3).
  - Today only `apps/studio/admin.py` and tests import the helper. No template or view reads it.

## 8. Notifications and the bell

- `notifications:drawer` (`/notifications/drawer/`, `apps/notifications/views.py:26`) renders `notifications/partials/drawer.html`. That partial targets `#notification-drawer-content`, but **no container with that id exists in base.html**. The drawer is ready but nothing is wired to it.
- `notifications:preferences` exists for Settings → Notifications.

## 9. Tests that assert on navigation

### Invariant tests in or near this area (never edit)

- **`apps/studio/tests/test_telegram_job_privacy.py`** (invariant 4)
  - 103-129: GETs `studio:team` and `studio:index` and expects **200** with the shared summary, and no private content.
  - 150-170: `studio:autopilot` must answer **200**.
  - 85-100: `studio:job` (and its progress, retry and cancel actions) answer **404** for a private job.
- **`apps/telegram/tests/test_web_privacy.py`** (invariant 4), 108-121 and 124ff: `studio:index` and `studio:thread` must answer **200**, and the thread's `context["rows"]` is checked. 327, 344 and 356 also use `studio:thread`.
- **`apps/studio/tests/test_setup.py:528-546`** `test_readiness_speaks_plainly_and_points_at_set_up` (invariant 9)
  - Asserts the copy "Your AI team isn't connected yet — open Set up.", "Connect a social account in Set up.", "…open Set up to check."
  - Asserts `state["setup_url"] == reverse("studio:setup")`.
  - Bans `API_KEY`, `worker`, `operator`, `lead`, `FAL`, `administrator` in that copy.
  - `test_chat_provider_readiness.py:42` bans `assistant`, `administrator`, `AI service`.
- **`apps/client_portal/test_telegram_onboarding.py:215-225`** (invariant 3)
  - The portal Telegram page's `response.context` must not contain `tabs`, `can_manage`, `can_pair_group`, `managed_form`, `chats`, `deliveries` or `updates`.
  - `telegram:settings` answers 403 for a client.
  - Context-processor values appear in `response.context`, so any new global key with one of those names would fail this test.

### Other pytest tests (editable)

- **`apps/studio/tests/test_setup.py`**
  - 394-404: labels exactly `<span class="sidebar-nav-label">{Home|Approvals|Calendar|Inbox|Blog &amp; SEO|Set up|More}</span>`, `<details class="sidebar-more"`, links on Home to `drafts_list`, `queue_list`, `csv_upload`, `media_library:index`; "Start a post" absent.
  - 406-415: `<details class="sidebar-more" data-sidebar-more>` closed on `studio:detail`, `studio:index` and `blog:list`; `… open>` on `drafts_list`.
  - 280-287: Settings hub cards. 291-300: tab labels and keys. 303-319: Routines tab hidden for a viewer, Routines 403. 322-328: `aria-current="page">Settings</a>` on autopilot. 75-98 and others: GET `studio:setup` and parse its rows.
- **`apps/studio/tests/test_routines.py:811-816`**: tab order `["overview", "routines"]`.
- **`apps/studio/tests/test_live.py`**: 655-665 Team tab for staff; 724-730 `studio:team` `hx-trigger` interval; 742-753 team_board query budget (no context processors); 850-868 Home query budget, measured relative to the same page.
- **`apps/studio/tests/test_agency_pages.py:66`**: `studio:team`.
- **`apps/common/tests/test_shell_a11y.py`** (setUp GETs the calendar)
  - 47-55: drawer inert, dialog and `aria-controls`.
  - 57-66: Escape on `wsBtn` and `newBtn`.
  - 68-76: idea modal focus CSS. 78-79: account line `text-ink-600`. 81-84: scroller class.
  - 86-102: More labels "Ideas", "Posting schedule", "Import from CSV", and the `<h1>` on their pages.
- **`apps/common/tests/test_navigation_and_guards.py:50-76`**: `sidebar_connectable_platforms` in the context; the calendar page links all six of `drafts_list`, `queue_list`, `posting_slots`, `template_list`, `category_list`, `csv_upload`. Those links exist only in More.
- **`apps/composer/tests/test_channelless_drafts.py:173-190`**: regex `sidebar-nav-item active".*?sidebar-nav-label">`; Ideas lit on `create_landing` and not on `compose`; Queues lit on `queue_list` and not on `social_accounts:list`.
- **`apps/common/tests/test_round6_layout.py:33-54`**: `data-testid="notification-badge"` and `notificationBadge(3)` / `notificationBadge(0)` on the calendar page.
- **`apps/common/tests/test_a11y_sweep.py:162-182`**
  - Pages: calendar, compose, `create_landing`, `category_list`, inbox, saved replies, media, `members:list`, `studio:index`, `studio:team`, `studio:brand`. Each must answer **200**.
  - Full pages including the sidebar are checked for faint copy, accessible names and dialogs. `seen > 10` dialogs (line 244) depends on the idea modal appearing on every page.
- **`apps/common/tests/test_app_shell.py:16`**: `/notifications/` with `follow=True`.
- `test_pricing.py:33` is the marketing nav, outside this area.

### Playwright and Lighthouse

- `tests/e2e/self/emoji-picker.spec.ts:9-11`: `mobile-menu-toggle`, `sidebar-new-toggle`, `sidebar-new-idea`, `idea-*`.
- `tests/e2e/golden/01-sign-in.spec.ts:133-141`: button named "Toggle menu", the account button named after the owner, `account-sign-out`.
- `tests/lighthouse/run.mjs:135-142`: the same New-menu testids, inside the measured interaction budget.
- `.lighthouserc.json:5-7` measures `…/studio/`, `…/calendar/?mode=list&tab=approvals` and `…/calendar/?mode=calendar&view=month`.
- Golden specs reach pages by `goto` only:
  - `05-approve-and-schedule:101,179`, `05-06-role-variants:46,104` (expects status 200) and `06-request-changes:92` go to `calendar/?mode=list&tab=approvals`.
  - `02-onboarding:80,127` goes to `studio/setup/` and uses `setup-row-*` testids.
  - `03-ask-the-team:250-260`: a client lands on the calendar; Home answers 403.
  - `08-client-portal:143`: the studio page is refused to a portal session.
- Axe (WCAG 2.2 AA) runs on every page and includes the sidebar and drawer.

## 10. Risks and decisions for Phase 2

1. **Old routes pinned by invariant tests.** `studio:team`, `studio:index`, `studio:thread` and `studio:autopilot` must keep **rendering 200** (no 301), because the invariant-4 tests do not follow redirects. Either Activity and Settings are new routes while those keep rendering, or the new views are served under those names. `studio:job` is a URL-contract name and also invariant-pinned.
2. **"Set up" leaves the sidebar but not the copy.** The invariant-9 test pins readiness copy saying "open Set up" and `setup_url == reverse("studio:setup")`. The name must keep resolving, and a destination recognisably called "Set up" must still exist (for example in Settings → Advanced). A 301 on `studio:setup` passes that test but breaks `test_setup.py` row tests and golden 02.
3. **Active-state rules break with new routes.** The Home rule (`app_name == 'studio'`) will also light Home on `/studio/activity/` and on any studio-namespaced settings page. The Approvals and Calendar rules key on `?tab=approvals`. A single Python nav builder that returns items and the active key (like `dashboard.tabs`) would make the six items and the gear testable.
4. **Approvals.** `calendar:calendar` is in the URL contract, so only the `tab=approvals` variant could redirect to `/approvals/`. The Lighthouse URL, three golden specs, the phone top-bar badge (937) and the sidebar badge count (`context_processors.py:142-155`) all depend on this. Decide whether the new screen uses the same pending query.
5. **Removing More** breaks `test_setup` (two tests), `test_shell_a11y` (More labels), `test_navigation_and_guards` (six orphaned pages) and `test_channelless_drafts` (active state). All are editable. With flags off, Queues, Templates and Categories must not be linked. Decide where Drafts (Calendar list tab), Posting schedule (stays visible), CSV (inside New post), Ideas (merged into New post) and Media are reached. Phone keeps a "More" tab per `BETA_PLAN.md:174`, while "More removed" applies to desktop.
6. **The "+ New" menu and idea modal.** Removing or moving them breaks `emoji-picker.spec.ts`, the Lighthouse INP interaction, `test_shell_a11y` (newBtn Escape, modal focus) and possibly `test_a11y_sweep`'s `seen > 10` dialog count. Under "no restyling", decide whether New stays in the sidebar until the Phase 3 New post sheet.
7. **The agency tab strip.** It becomes redundant once Team and Routines move to Activity and Settings to `/settings/`. Twelve views pass `tabs`, and `test_setup`, `test_routines` and `test_live` pin labels and keys. Decide whether to keep it on the old pages, which still render, or drop it. Any new global context key must not be named `tabs` (invariant 3 test).
8. **Three settings entry points plus two override layouts.** Today: Set up (cog), "Workspace settings" in the switcher, and the account "Settings" plus "Manage Team" in the footer. `layouts/settings.html` and `layouts/workspace_settings.html` replace the sidebar. Decide which of these 301 to `/settings/` tabs and which keep rendering in their layout. "API keys" (layouts/settings.html:35) leaves the nav and becomes the *Developers* link in Advanced. The account "Settings" label collides with the new gear.
9. **Route paths are free:**
   - `/workspace/<id>/settings/`: only `settings/clients/` (client-portal admin) is taken.
   - `/workspace/<id>/approvals/`: the approvals app is mounted at `workspace/<id>/` with `approvals/<uuid>/…` and `approvals/bulk/` only.
   - `/workspace/<id>/studio/activity/`: free; `<uuid:brief_id>/` cannot match it.
10. **Bell dropdown.** Wire the existing `notifications:drawer` partial by adding a `#notification-drawer-content` container. Keep `data-testid="notification-badge"` and `notificationBadge(N)` (`test_round6_layout`). `/notifications/` must keep working (`test_app_shell`, the drawer's fallback links).
11. **Phone bottom bar.** It must not cover the phone **Approve & schedule** bar on the post page (`studio/detail.html:72`, invariant-1 path) or the toasts and bulk bars. `<main>` needs bottom padding for it. The drawer's inert, dialog and trap behaviour stays pinned by `test_shell_a11y` while the drawer exists.
12. **Feature-flag cost.** Navigation will be the first reader of `feature_enabled` (Phase 0 R4 had none). It adds up to two queries on every `render(request)`, including HTMX partials and portal pages. `test_live`'s Home budget is relative, so it holds. Consider skipping the lookup when `request.htmx` or with no workspace. While there, `sidebar_context` makes three unused channel queries per render.
13. **Item count varies.** Analytics depends on the global `AnalyticsPlatformConfig`, so desktop can show five items. Plain clients and viewers see links that answer 403 (Home); this predates Phase 2 and no invariant enforces nav hiding.
14. **Intelligence.** Removing its link (807-813) breaks no test.

---

# AREA approvals

# Approvals surfaces: Phase 2 engineering map

All paths are under `/home/user/calander-9-/`. This was read-only: nothing was edited, no tests were run, no servers were started.

**Main finding:** the old approvals URL `calendar:calendar?mode=list&tab=approvals` cannot be turned into a 301. An invariant test requires it to answer 200 (`apps/approvals/test_gate.py:394-401`, invariant 1). The HTMX endpoint `calendar:publish_tab_approvals` must also keep answering 200 (golden path 05, line 69). So `/approvals/` has to be a new view that sits alongside these two, not a redirect target for them.

## 1. Where a person reviews or approves today

| # | Surface | Route (namespace:name → path) | View | Template / partials | Who can act |
|---|---|---|---|---|---|
| A | Calendar list view, Approvals tab (full page) | `calendar:calendar` → `/workspace/<id>/calendar/?mode=list&tab=approvals` | `apps/calendar/views.py:685-783` `calendar_view` (`@login_required`, `@gzip_page`, membership via `_get_workspace` :85). In list mode, :769-772 renders the approvals tab inline. | `templates/calendar/calendar.html` → `calendar/partials/publish_list_shell.html` (tabs :22-25, `#tab-content` :47-49) → `calendar/partials/publish_approvals.html` | Anyone may look. `can_approve` comes from `effective_permissions["approve_posts"]` (:639-642) |
| A′ | Approvals tab fragment (HTMX) | `calendar:publish_tab_approvals` → `/workspace/<id>/calendar/publish/approvals/` (`apps/calendar/urls.py:40`) | `views.py:1133-1137` → `_render_tab` :1108 (sets `is_htmx=True` and `render_tab_counts_oob=True`, adds the four counts) | the same partial | same |
| B | Approval actions (204 + HX-Trigger) | mounted at `workspace/<uuid:workspace_id>/` (`config/urls.py:109`): `approvals:approve` `approvals/<post_id>/approve/`, `:request_changes`, `:reject`, `:resume`, `:bulk_action` `approvals/bulk/`, `:add_comment`, `:edit_comment`, `:delete_comment`, `:comment_attachment`, `:version_diff` (`apps/approvals/urls.py:8-21`) | `apps/approvals/views.py`: approve :50-92, request_changes_view :114-133, reject :136-155, resume :158-170, bulk_action :173-212 (each `@login_required @require_permission("approve_posts") @require_POST`). Comment and diff views :220-412 use `@require_workspace_role("viewer")`. | `approvals/partials/_approval_row.html`, `version_diff.html` (HTMX) or `approvals/version_diff.html` (full page) | `approve_posts` |
| C | Post page | `studio:detail` `/workspace/<id>/studio/<brief_id>/`; `studio:approve` `<brief_id>/approve/`; `studio:request_changes` `<brief_id>/changes/` (`apps/studio/urls.py:25-33`) | `apps/studio/views.py`: `detail` :446-454, `approve` :490-513 (`approve_posts`; modes `approve`/`proposed`/`schedule`/`now`, where `now` also needs `publish_directly`), `request_changes` :516-537 (`create_posts`, `@ratelimit 10/m`, `budget.can_spend`). Plain clients get 403 via `_workspace` :62-75. | `templates/studio/detail.html`: phone decision bar :70-83; approve forms :271-318; revise form :336-341 | `approve_posts`; plain client 403 |
| D | Home "Waiting for you" card | `studio:index` | posts to `studio:approve` with `mode=proposed` | `templates/studio/index.html:60-69` (`home-today-approve-schedule`, `home-today-review`); "Open approvals" link :85 points at the old URL | `approve_posts` |
| E | Telegram card | Bot callbacks, no web route | `apps/telegram/actions.py`: `issue_post_review` :179-280; `handle_callback` :435; `_apply_post` :550-610 calls `approval_services.approve_post` (:593). The `/approvals` command is in `conversations.py:264-297` and :479. | "Open to approve" button = `inbox.post_path` (`apps/telegram/inbox.py:123-133`), which returns `studio:detail` when a brief exists, else `approvals_path` (:136-137, old URL) | Gate enforced, `approvals_enabled`, fresh `approve_posts` |
| F | Client portal | `client_portal:approval_queue` `/portal/approvals/`, plus `:approve`, `:request_changes`, `:reject`, `:request_hold`, `:post_ask`, `:post_thread` (`apps/client_portal/urls.py:10-14, 27-28`) | `apps/client_portal/views.py:156-327` (`@portal_auth_required`); answers use the `portalAction` trigger (:22-29) | `templates/client_portal/approval_queue.html` (refresh on `portalAction`, `#portal-posts`), `_client_card.html`, `portal_base.html:49,63,83` | Portal session only; `/portal/` prefix gives the PORTAL actor (`apps/approvals/actor.py:31-35, 66-70`) |
| G | Composer inline review (not in the cut table) | `composer:compose_edit` | — | `templates/composer/compose.html:1622-1634` (htmx to `approvals:approve` and `approvals:request_changes`), comments :1655-1661, toasts :2050 | `can_approve` |

Settings pages next to this area (owned by the Settings mapping): `workspaces:approvals_settings` `/workspaces/<id>/settings/approvals/` (`apps/workspaces/urls.py:11`, view `apps/workspaces/views.py:174-176`) and `telegram:toggle_approvals` (`apps/telegram/views.py:204`).

## 2. HTMX contract of the Approvals tab

- **Action responses.** `apps/approvals/views.py:35-42` calls `apps/common/htmx.py:17-27 toast_response`. It returns 204 with `HX-Trigger: {"showToast":…, "approvalAction"|"bulkActionComplete": true}`.
- **List refresh.** `publish_approvals.html:11-16`: the root `x-data` div has `hx-trigger="approvalAction from:body, bulkActionComplete from:body"`, `hx-get="{% url 'calendar:publish_tab_approvals' %}?approval_status=…&{{ approval_filter_qs }}"`, `hx-target="#tab-content"`, `hx-swap="innerHTML"`, and `data-testid="approvals-list"`.
- **Filter pills.** `calendar/partials/_approval_pill.html:2-3` also targets `#tab-content` on the calendar endpoint.
- **Out-of-band counts.** Line 1 includes `_tab_counts_oob.html` when `render_tab_counts_oob` is set. It emits four out-of-band spans, `#tabcount-queue|drafts|approvals|sent`, and the targets live in `publish_list_shell.html:16-28`.
- **Toast host.** `approvals/partials/_toasts.html` listens for `showToast` on `body` and must be included once, outside `#tab-content`: `calendar.html:333-334`, `portal_base.html:83`, `compose.html:2050`. The `.modal-pop` and `.anim-collapse` CSS is defined inside it; `.tab-slide-in` and `body.has-selection #bb-toast-host` are in `calendar.html:300-321`.
- **Version diff.** The row's "View changes" button does an hx-get of `approvals:version_diff` into `#diff-modal-body`, which sits in `publish_approvals.html:96-109`.
- **Filters (channel, tag, timezone).** These are `ui_select` components in `publish_list_shell.html:35-41` (`data-testid="ui-select-<model>"`, from `templates/components/ui_select.html:10`). They are bound to `publishList()` (`calendar.html:600-634`), which is defined only in calendar.html's `extra_js`. `reloadTab()` re-requests the tab fragment into `#tab-content`, adding `channel`, `tag` and `tz` to the query.

## 3. data-testid hooks in this area

- **`_approval_row.html`:** `approvals-row-<post.id>`, `approvals-row-select`, `approvals-row-details`, `approvals-row-view-changes`, `approvals-row-approve-schedule`, `approvals-row-approve`, `approvals-row-review`, `approvals-row-edit`, `approvals-row-resume`, `approvals-row-request-changes`, `approvals-row-reject`, `approvals-row-review-comment`, `approvals-row-send-back`, `approvals-row-reject-post`, `approvals-row-cancel`. pytest also reads the `data-select-spacer` attribute.
- **Tab and shell:** `approvals-list`, `publish-tab-approvals` (and the queue, drafts and sent tabs), `calendar-mode-list`, `ui-select-displayTimezone`.
- **Post page:** `studio-detail-revision`, `studio-detail-notes`, `studio-detail-progress`, `studio-revise-form`, `studio-revise-send`, plus the `data-decision-bar` and `data-decision-more` attributes.
- **Portal:** `portal-nav-approvals`, `portal-approvals-pending`, `portal-approvals-decided`, `portal-card`, `portal-card-approve`, `portal-card-request-changes`, `portal-card-comment`, `portal-card-send-changes`.

## 4. What a new `/workspace/<id>/approvals/` view can include unchanged

**URL.** Add `path("approvals/", views.index, name="index")` to `apps/approvals/urls.py`, giving **`approvals:index`** → `/workspace/<id>/approvals/`. This follows the existing `studio:index` and `analytics:index` naming. It does not collide with anything: the existing patterns are `approvals/<uuid>/…` and `approvals/bulk/`, and composer, which is mounted on the same prefix, has no `approvals/` route. The path is not under `/api/`, `/oauth/` or `/portal/`, so `channel_for_path` treats it as DASHBOARD.

**Decorators.** `@login_required` and `@require_GET`. The membership middleware (`apps/members/middleware.py:105-123`) already answers 403 for non-members. `gzip_page` is optional, as on `calendar_view`.

**Context.** `_get_tab_context(request, workspace, "approvals")` (`apps/calendar/views.py:501`, approvals branch :572-683) provides:
- `workspace`, `display_timezone`, `has_connected_accounts`
- `posts`, each with `.visible_comments` and `.is_actionable`
- `status_filter`, `can_approve`, `approval_filter_qs`
- `all_count`, `pending_review_count`, `pending_client_count`, `approved_count`, `rejected_count`, `changes_requested_count`, `on_hold_count`

Also set `is_htmx=False` and leave `render_tab_counts_oob` unset. For filters, take `channels_with_posts`, `all_tags` and `timezone_options` from `_get_publish_context` (:395).

**Template skeleton.**
1. Extend `base.html`.
2. `<div id="tab-content">{% include "calendar/partials/publish_approvals.html" %}</div>`. This brings in `_approval_pill.html`, `approvals/partials/_approval_row.html`, `_status_badge.html`, `_status_icon.html`, `partials/_platform_icon.html` and the bulk, reject and diff modals.
3. `{% include "approvals/partials/_toasts.html" %}` outside that div.
4. If filters are wanted: the three `ui_select` tags plus an Alpine scope providing `selectedChannels`, `activeTag`, `displayTimezone` and `reloadTab()`.

**Side effects to expect when it is included unchanged:**
- Refreshes and pill clicks still GET `calendar:publish_tab_approvals`.
- Every refresh returns four out-of-band `#tabcount-*` spans. Without matching targets on the page, htmx raises `htmx:oobErrorNoTarget` in the console.

## 5. Places that build the old URL (`calendar:calendar` + `?mode=list&tab=approvals`)

| File and line | Pinned by a test? |
|---|---|
| `templates/base.html:714-719` sidebar link; active state `match.url_name == 'calendar' and request.GET.tab == 'approvals'`; Calendar item active rule at :720; badge from `apps/common/context_processors.py:142-155` | `apps/studio/tests/test_setup.py:399` checks label text only |
| `templates/base.html:937-943` phone header badge link | no |
| `templates/studio/index.html:85` "Open approvals" | no |
| `templates/studio/partials/team_board.html:35`, from `apps/studio/live.py:1128, 1178-1180` | no |
| `templates/approvals/version_diff.html:7` "Back to approvals" | no |
| `apps/onboarding/checklist.py:79` (review_draft step) | no |
| `apps/telegram/inbox.py:136-137` `approvals_path`, used by `inbox.py:133, 223`, `notifications.py:305, 423, 513` and `apps/studio/briefing.py:97, 144` | `apps/telegram/tests/test_inbox.py:221-223` (`"tab=approvals" in button["url"]`); `test_briefing.py:24-25` |
| `apps/approvals/tasks.py:248-254` `_review_url` → `action_url` (:165) for reminders and emails | `apps/approvals/test_deadline_reminders.py:102-103` |
| `apps/common/management/commands/live_verify.py:296` (info line) | no |
| `.lighthouserc.json:6` | Lighthouse runner |

## 6. Tests that load these routes

**[INV] = enforces one of the nine CLAUDE.md invariants. These must not be edited.**

### pytest

- **[INV-1] `apps/approvals/test_gate.py`**
  - :105-111 POSTs `approvals:approve` → 204, stamped.
  - :386-421 `ApprovalsQueueViewTests`:
    - :394-401 GETs `calendar:calendar` with `{"mode":"list","tab":"approvals"}` and asserts **200**, "Preview per destination" and "Approve &amp; schedule".
    - :403-411 Approve & schedule uses the proposed time.
    - :413-420 a client role gets 204 with "internal approver" and nothing moves.
- **`apps/approvals/test_workflow.py`**
  - :59-117 `ActionViewContractTests` (the `showToast` + `approvalAction` contract, bulk).
  - :398-429 `ApprovalTabChannelFilterTests` on `calendar:publish_tab_approvals`.
  - :432-480 `PortalMixedPostActionTests` (`client_portal:approval_queue`).
  - [INV-1] `HoldPublishGuardTests` :211-285 and `ApprovedEditReReviewTests` :287-396.
- **`apps/approvals/test_status_words.py`**: :82-96 (`calendar:publish_tab_approvals`), :98 (portal), :124 (brief page pill).
- **`apps/common/tests/test_review_a11y.py`**: :115-120 (`publish_tab_approvals`: one "Select post" checkbox and one `data-select-spacer`), :122-130 (toast script on `calendar:calendar`).
- **`apps/common/tests/test_page_script_budgets.py:47`**: old URL → 200 with Sortable loaded.
- **`apps/calendar/test_response_compression.py:29`**: old URL → 200, gzip, and the page must be rendered through `apps.calendar.views.render`.
- **`apps/approvals/test_deadline_reminders.py:91-105`**: action_url ends with `?mode=list&tab=approvals`. The same test asserts no state change, which is close to invariant 1.
- **`apps/telegram/tests/test_inbox.py:208-224`, `test_briefing.py:17-49`, `test_routines_telegram.py:201`**: the URL and the "Open approvals" label.
- **[INV-2] `apps/approvals/test_security.py:39-89`**: cross-workspace `edit_comment` → 404.
- **[INV-3] `apps/approvals/test_security.py:91-145`**: comment visibility for clients.
- **[INV-2/3] `apps/approvals/test_comment_attachment.py:45-140`**.
- **[INV-2] `apps/members/tests/test_authorization_boundaries.py:68-110`**: cross-tenant `approvals:delete_comment`.
- **[INV-1/3] `apps/approvals/test_client_hold_on_scheduled.py`** and **[INV-1] `test_neopolis_destination.py`**.
- **Post page**
  - `apps/studio/tests/test_views.py:150-180` `TestApproving` (editor 403 = [INV-1]).
  - [INV-3] `apps/studio/tests/test_agency_pages.py:80-92`: a plain client gets 403 on `studio:index`, `studio:detail` and `studio:approve`.
  - [INV-1/3] `test_agency_pages.py:170-190`: one-click approval never skips the client's sign-off.
  - `apps/studio/tests/test_two_stage_send_back.py:50-70`.
- **[INV-2] `tests/test_e2e_steps_sign_in_isolation.py:72-141`**: the resolver count is computed automatically, so a new `approvals:index` is picked up without edits; portal paths are listed at :136-141.

### Playwright (`tests/e2e/golden/`)

- **[INV-1] `05-approve-and-schedule.spec.ts`**
  - :101 and :179 goto the old URL and expect 200.
  - :64 and :189 POST `/workspace/<id>/approvals/<post>/approve/`; :189 is the editor and expects 403.
  - :69 waits for the reload GET whose pathname is `/workspace/<id>/calendar/publish/approvals/` and expects **200** (:138).
  - Uses the row testids and the week grid.
- **[INV-1/3] `05-06-role-variants.spec.ts`**: :46 and :104 goto the old URL; :55 and :110 approve POST; portal path 6 runs :119-140.
- **[INV-1] `06-request-changes.spec.ts`**: :92 goto the old URL; the row's review, request-changes and send-back hooks; `/studio/<brief>/` detail hooks at :156-231.
- **[INV-1] `07-calendar-drag.spec.ts`**: drag approves the new time, or withdraws the approval for staff. Week view only.
- **[INV-1/3] `08-client-portal.spec.ts`**: `/portal/<token>/` → `portal-nav-approvals` → `/portal/approvals/`; sign-off completes the client stage only; the portal session is refused `/studio/` (:143-144).
- **[INV-3] `03-ask-the-team.spec.ts`**: Home approve controls :148-172 (editor 403); a client with a password session lands on `/calendar/` (:253-256).
- **[INV-2] `11-isolation.spec.ts`**: sweeps every workspace pattern automatically; `notFoundAnswers` has `'approvals:delete_comment': status(400)` (:176); `approvals:version_diff` is used for the client at :391. **`11-isolation-inputs.spec.ts`** as well.
- **Lighthouse:** `tests/lighthouse/run.mjs:100-122, 181` needs `approvals-list`, `approvals-row-<id>` with `approvals-row-details`, and `ui-select-displayTimezone` reloading with `tz=UTC`.

## 7. Risks and decisions for Phase 2

1. **The old Approvals tab URL cannot 301.** `test_gate.py:396` (invariant), `test_page_script_budgets.py:47` and `test_response_compression.py:29` all require 200 from `calendar_view`. `calendar:calendar` is in the URL contract anyway. Decision needed: keep the tab rendering inside Calendar, or hide only the tab button while `?tab=approvals` still renders. Either way, the plan's "old URLs 301" does not apply to this URL.
2. **Never 301 `calendar:publish_tab_approvals`.** Golden path 05 waits for a 200 on that pathname. Three pytest tests GET it. A permanent redirect on an XHR endpoint also gets cached by browsers.
3. **Nothing in this area should 301 to `/approvals/`.** `studio:detail`, `studio:approve`, `client_portal:*`, the `approvals:*` actions and `approvals:version_diff` all keep rendering. The portal cannot merge into `/workspace/<id>/approvals/`: it has its own session auth and gets the PORTAL actor from the `/portal/` prefix, and `actor.py` and `gate.py` are off-limits.
4. **Should plain clients be refused on `approvals:index`?**
   - Today a client with a password session can open the Calendar Approvals tab with `can_approve=True`, because the client role has `approve_posts` (`apps/members/models.py:237-240`).
   - The studio pages refuse plain clients with 403, and invariant 3 says plain clients use the portal.
   - Recommendation: 403 for plain clients. This matches `studio._workspace`, and golden path 03 is unaffected.
5. **Repointing links versus pinned tests.**
   - Can move to `approvals:index` without breaking a test: the sidebar, the phone badge, Home :85, the team board, version_diff's back link, the onboarding checklist.
   - Pinned by tests: `inbox.approvals_path` (test_inbox, test_briefing) and `tasks._review_url` (test_deadline_reminders). Either leave them on the old URL, which keeps working, or edit those tests. test_deadline_reminders sits next to an invariant assertion.
   - Telegram buttons and emails already sent carry the old URL permanently, which is another reason it must keep working.
6. **Golden paths conflict.** `tests/e2e/README.md:58` says the existing invariant golden paths stay unchanged. `docs/BETA_PLAN.md:278` says the 12 e2e tests are updated to the new routes. If the old URL keeps rendering, 05, 05-06 and 06 pass untouched. To cover `/approvals/`, add new specs rather than editing those.
7. **Out-of-band count spans on the new page.** Each refresh from `_render_tab` emits four `#tabcount-*` spans. Decide between: providing hidden targets, adding a fragment endpoint that skips the counts (golden 05 only covers the old page), or accepting the console errors.
8. **Filters live only in Calendar.** `publishList()` exists only in `calendar.html`'s `extra_js`. The new page needs its own small scope if it keeps the channel, tag and timezone filters, and Lighthouse needs `ui-select-displayTimezone` if `.lighthouserc.json` is pointed at the new page. Pointing Lighthouse at a URL that redirects adds a hop to LCP.
9. **Sidebar active state.** It is keyed on `request.GET.tab` and needs `match.app_name == 'approvals' and match.url_name == 'index'`. The sidebar badge does not refresh after HTMX actions; this is existing behaviour.
10. **Mismatched copy and links that already exist.**
    - `apps/studio/views.py:423-429` ("Open Approvals to retry", "Pick a posting time on the Approvals page") and the Telegram "Open delivery" button (`notifications.py:305`) send people to Approvals for failed or scheduled rows.
    - The tab's status list (`calendar/views.py:345-352`) excludes those statuses.
    - `detail.html:322` mentions the Approvals list without a link.
    - Decide where these point, or keep them as they are under "no restyling".
11. **Composer inline review (surface G) is not in the cut table.** It depends on `_toasts.html` and the `approvals:*` endpoints. If it stays, nothing changes.
12. **Code location.** Reusing the private helpers from `apps/calendar/views.py` keeps one source of truth. If the approvals branch moves into `apps/approvals`, `calendar_view` must still call `render` from `apps.calendar.views`, or the compression test fails.

---

# AREA settings

# Settings surfaces: engineering map for Phase 2

The tree was only read. No files were changed and no git state, servers, pytest or Playwright were touched.

Two terms used throughout:
- **staff-only (`_workspace`)** means `apps/studio/views.py:62`. It raises 403 for a plain client (`is_plain_client`, `views.py:51`) and for anyone without a membership. `_perms` (`views.py:77`) returns `request.workspace_membership.effective_permissions`.
- **The middleware** is `apps/members/middleware.py:107-158`. Any URL whose kwargs include `workspace_id` returns 403 to a non-member before the view runs.

Two permission facts matter for every tab:
- Only `owner` has `manage_workspace_settings` among the built-in roles. `manager` does not (`apps/members/models.py:190-265`).
- Three of the old pages gate on `workspace_role` or `org_role` instead: workspaces general and approvals, the client admin, and members.

## 1. Route inventory

Mount points in `config/urls.py`:
- L68 `workspaces/`
- L69 `members/`
- L70 `social-accounts/`
- L111 `workspace/<uuid>/settings/clients/` (client admin; the only existing route under `/workspace/<id>/settings/`)
- L124 `workspace/<uuid>/studio/`
- L125 `workspace/<uuid>/agency/telegram/`
- L128 `notifications/`

No composer or approvals route collides with `workspace/<uuid>/settings/`.

### Agency (studio app; `apps/studio/urls.py` collects the sub-URL files)

**`studio:setup`**
- Path `/workspace/<id>/studio/setup/`, defined at `urls_setup.py:7`.
- View `views_setup.setup` (`views_setup.py:487-503`): `@login_required @require_GET`, staff-only. Every staff member may read it.
- Context comes from `checklist()` (`:412-433`) with 11 rows: ai_team, pictures, accounts, approvers, autopilot, creation_mode, telegram, email, facts, blog, budget.
- Owner detail is decided by `is_owner()` (`:40`, org owner or superuser).
- Response header `Cache-Control: no-store, private`.
- Template `templates/studio/setup.html` extends base, full page, and has no agency tabs.

**Set up POST actions**
- `studio:setup_lead` (`/setup/lead/`, `use_me_as_lead`, `:531-547`): the presser must be an eligible lead. Replacing another lead needs `manage_workspace_settings`.
- `studio:setup_autopilot` (`/setup/autopilot/`, `autopilot_defaults`, `:550-582`): needs `manage_workspace_settings`.
- Both redirect through `_back` (`:527`) to `studio:setup`.
- The creation-mode row posts to `studio:creation_mode` (`/studio/thread/creation-mode/`, `views_chat.py:339`). That view requires `manage_workspace_settings` and posts back with `next=<setup url>`, validated against the host.

**`studio:settings_hub`**
- Path `/workspace/<id>/studio/settings/` (`urls_setup.py:10`).
- View `views_setup.settings_hub` (`:506-519`): `@login_required @require_GET`, staff-only.
- Cards come from `dashboard.settings_cards` (`dashboard.py:82-100`): brand, trust, memory, outcomes, autopilot, telegram, and budget (which is `studio:autopilot` + `ADVANCED_OPEN = "?open=advanced"`, `:53`).
- Agency tabs come from `dashboard.tabs` (`:56-79`). The Settings tab points to `studio:settings_hub`, and `SETTINGS_PAGES` (`:51`) lights it.
- Template `templates/studio/settings_hub.html`, full page.

**`studio:brand`**
- Path `/workspace/<id>/studio/brand/` (`urls.py:22`).
- View `views.brand_profile` (`views.py:622-642`): `@login_required @require_http_methods(GET, POST)`, staff-only.
- Write gate `_can_edit_brand` (`:617`): `approve_posts` or `manage_workspace_settings`.
- On save it redirects to `studio:brand`. An invalid form re-renders with status 200.
- Template `studio/brand_profile.html`, full page, no tabs. Its `<form method="post">` at L31 has **no `action`**.
- Supporting route `studio:brand_sample` (`brand/sample/<template>.jpg`, `views.py:645`) returns an image.

**`studio:trust`** (Verified facts)
- Path `/workspace/<id>/studio/verified-facts/` (`urls_trust.py:5`).
- View `views_trust.verified_facts` (`:17-161`), GET and POST. Staff-only, plus a refusal for the client role and for `client_facing` custom roles (`:27-33`).
- Writes need `_can_edit_brand` and `trust.verification_people`.
- POST calls `guards.forbid_in_agent_work` (`:44`) and takes `select_for_update` locks.
- GET accepts `?claim=<uuid>` to edit an existing claim.
- Template `studio/trust.html`. Its forms at L13, L61 and L85 have **no `action`**, and L60 is a relative link `href="?claim=…"`.

**`studio:memory`** (Creative memory)
- Path `/workspace/<id>/studio/memory/`. View `views_memory.memory` (`:132-137`): `require_permission("create_posts")`, staff-only.
- POST endpoints, all `create_posts` + `ratelimit 10/m`:
  - `memory_house_style` (`house-style/`): also needs `_can_edit_brand`.
  - `memory_upload` (`references/`): also needs `upload_media`.
  - `memory_refresh` (`refresh/`): queues a paid learn job.
  - `memory_reference` (`<insight_id>/reference/`).
- Errors re-render `studio/memory.html` with status 400. Success redirects to `studio:memory`.
- All forms carry an explicit `action=`.

**`studio:outcomes`**
- Path `/workspace/<id>/studio/outcomes/`. View `views_outcomes.outcome_page` (`:23-80`), GET and POST, `ratelimit 30/m` on POST.
- Staff-only, client refused. Reading needs `can_record` or `view_analytics`.
- A submission token travels in the form's initial data. Errors re-render with status 400.
- The form in `outcomes.html` L18 has **no `action`**.

**`studio:autopilot`**
- Path `/workspace/<id>/studio/autopilot/`. View `views_autopilot.settings_page` (`:141-163`): `require_permission("create_posts")`. POST needs `manage_workspace_settings`.
- The form is `AgencySettingsForm` (`forms_agency.py:147-240`). It holds the whole row: autopilot, posts/week, accounts, pillars, weekday/hour, blog, **monthly budget, lead, backup**, delivery delay, learn_from_best, inbox drafts, creation_mode.
- POST endpoints, both `create_posts` + `ratelimit 10/m`:
  - `autopilot_plan` (`plan/`): also needs `_can_plan`, i.e. an internal approver.
  - `autopilot_report` (`report/`).
- `?open=advanced` opens the approvers and budget section (`_context` `:122-125`).
- Template `studio/autopilot.html`; every form has an explicit action. Errors re-render with status 400.

**`studio:routines`** (Activity owns the list; Settings → Advanced gets only the free-form form)
- Path `/workspace/<id>/studio/routines/`. View `views_routines.routines_page` (`:70-75`): `create_posts`.
- The free-form form posts to `studio:routines_create` (`routines/new/`, `:92-120`): `create_posts`, `ratelimit 10/m`.
- `_back` (`:45-50`) honours a same-host `next` POST field. `routines.html` L40 sends no `next`.
- Errors re-render the full `routines.html` with status 400.

### Telegram (`apps/telegram/urls.py:7-18`; the URL contract requires `telegram:settings` to keep rendering)

**`telegram:settings`**
- Path `/workspace/<id>/agency/telegram/`. View `views.settings_page` (`:156-159`): `@login_required @require_GET`.
- Context `_context` (`:36-146`) uses `permissions.current_member`, so **clients can open it**; it is not staff-only. It renders a client variant through `internal_member`.
- `_render` (`:149`) sets `Cache-Control: no-store` and `Referrer-Policy: same-origin`.
- Template `telegram/settings.html` overrides `sidebar_nav` and `extra_head` for clients (L4-10). It includes the agency tabs only for internal members (L27).

POST endpoints. All except `pair` redirect to `telegram:settings`:
- `connect/`
- `webhook/retry/`
- `approvals/`
- `test/`
- `create-bot/`
- `pair/`
- `channel/connect/`
- `channel/<id>/disconnect/`
- `disconnect/`
- `unpair/`
- `chat/<id>/disconnect/`

Manage actions check `can_manage` (`permissions.py:25`: internal member and `manage_workspace_settings`). Two endpoints render the page instead of redirecting:
- **`pair`** (`:236-267`) answers 200 with the one-time `/start <nonce>` code.
- **`managed_create`** answers with the one-time t.me/newbot link.

`connect`, `connect_channel`, `pair` and `managed_create` re-render with status 400 on error.

### Workspace settings (`apps/workspaces/urls.py`)

**`workspaces:settings`**
- Path **`/workspaces/<id>/settings/`** (plural `workspaces`). View `workspace_settings` (`views.py:54-171`), GET and POST.
- Any member may GET. Writes require `workspace_role` owner or manager; without it the POST answers 403 (`:114`).
- POST `action` values: `archive_workspace`, `unarchive_workspace`, `delete_workspace` (the danger zone), and otherwise name and logo. It redirects to itself, or to `organizations:workspaces`.
- Template `workspaces/settings.html` extends `layouts/workspace_settings.html` (replaces `sidebar_nav`). All five forms (L14, L25, L91, L123, L182) have **no `action`**.

**`workspaces:approvals_settings`**
- Path `/workspaces/<id>/settings/approvals/`. View `approvals_settings` (`:174-226`).
- POST needs owner or manager. Changing `require_dashboard_approval` is owner-only.
- Template `workspaces/approvals_settings.html`; the form at L10 has **no `action`**. L83 links to `members:list`.

### Members (org-level; no workspace in the URL)

- `members:list` at `/members/`: `member_list` (`views.py:43`), `require_org_role("member")`. A client-only person gets 403 (`:55-62`). Template `members/list.html` extends `layouts/settings.html`.
- POST actions, all `require_org_role("admin")`:
  - `invite/`: `ratelimit 10/m`.
  - `invite/<id>/resend/`: `ratelimit 10/m`.
  - `invite/<id>/revoke/`.
  - `<membership_id>/role/`.
  - `<membership_id>/remove/`.
  - `<membership_id>/workspaces/`: GET and POST.
- Each answers an HTMX request with a partial: `members/partials/{member_row,invitation_row,workspace_assignments}.html`. Without HTMX it redirects to `members:list`.
- HTMX targets: `#member-<id>`, `#invite-<id>`, `#invitations-list`, `#ws-modal-content-<id>`.
- `invite_modal.html:24` has `@htmx:after-request.window` and Alpine `showInviteModal`.

### Client portal admin

- `client_portal_admin:client_list` at `/workspace/<id>/settings/clients/` (`urls_admin.py:8`): `views_admin.client_list` (`:26`), `require_workspace_role("manager")`. Template `client_portal/admin/client_list.html` extends the workspace_settings layout.
- POST actions:
  - `invite/`: `ratelimit 10/m`.
  - `<membership_id>/send-link/`: `ratelimit 10/m`.
  - `<membership_id>/revoke-link/`: `ratelimit 10/m`.
  - `<membership_id>/remove/`.
- Each answers HTMX with a partial; otherwise it redirects to `client_list`.
- HTMX targets: `#client-<id>`, `#pending-invites-section`, `#client-invite-<id>`.
- `invite_client_modal.html:24` also listens on `.window` and removes `#no-invites-placeholder`, which is the **members** page's id.

### Social accounts

**`social_accounts:list`**
- Path `/social-accounts/<id>/`. View `account_list` (`views.py:176-202`): `require_permission("manage_social_accounts")` (owner and manager).
- Template `social_accounts/list.html` (workspace_settings layout).
- Account cards (`partials/_account_card.html`) use explicit `action` plus `hx-post` and target `#account-<id>`.
- Posting slots (`partials/_posting_slots_grid.html`) use `calendar:*` HTMX endpoints with `hx-swap="none"` and the `slotsUpdated` trigger.

**Social-account actions**
- POST per account: `reconnect`, `retry-webhooks`, `disconnect`, `remove`.
- These redirect to `social_accounts:list` (`views.py:834-1000`).
- The OAuth callback (`:426`) also redirects there, or to `calendar:calendar` (`:450`).
- `apps/onboarding/views.py:146-225` redirects there as well.

**`social_accounts:connect`**
- Path `/social-accounts/<id>/connect/`. View `connect_platform` (`:205-264`), `ratelimit 20/m`. Template `connect.html` (base layout; testid `connect-platform-<value>`).
- The Bluesky, Mastodon and DEV.to forms live at `connect/<provider>/`.
- These are the gates for the `extra_providers` flag. Reconnect and the callback must stay open.

### Notifications

- `notifications:preferences` at `/notifications/preferences/`: `views.preferences` (`:135-184`), `@login_required`, per user, with no workspace. The form at L19 has an explicit action. Save goes through `_save_preferences` (`:227-255`) and redirects to itself. Errors answer 400.
- **Emails hard-code `/notifications/preferences/`**: `templates/notifications/email/{notification,digest}.{html,txt}`.

### Developers and the org danger zone (link targets only)

- `api_keys:list` at `/organizations/api-keys/` (`_require_manage_api_keys`).
- Organisation deletion lives in `organizations:settings` (`views.py:53-67`, `require_org_role(ADMIN)`).

## 2. Can each page's body sit in a tab without changing behaviour?

Every page's markup sits inside `{% block content %}` of a full-page template. A tab needs that body extracted into an `{% include %}`-able partial, plus each view's context builder.

| Page | Includable as-is? | Blocker |
|---|---|---|
| Set up checklist | Yes | Actions return to `studio:setup`; header `no-store, private`; context costs several queries |
| Settings hub | n/a (the tabs replace it) | — |
| Brand | **No** | Form has no `action` (would post to `/settings/`) |
| Workspace general / danger | **No** | 5 forms with no `action`; uses `workspace_role` gate |
| Approvals settings | **No** | Form has no `action` |
| Verified facts | **No** | 3 forms with no `action`; relative `?claim=` link drops `tab=` |
| Outcomes | **No** | Form has no `action` |
| Creative memory | Yes | Errors re-render full `memory.html` at 400; needs `create_posts` |
| Autopilot | Yes, but only as **one whole form** | Splitting `AgencySettingsForm` across tabs blanks the omitted fields (checkboxes → False, accounts → empty, required errors) |
| Routines free-form form | Yes, with a hidden `next` | Errors re-render `routines.html` |
| Telegram | Partly | Client variant and sidebar override; `pair` and `managed_create` render the page with one-time codes; context is large (`test_settings_do_not_probe_telegram_or_models_on_get` must hold) |
| Members | Yes (HTMX) | Org-wide data; org-role gate; see modal collision below |
| Clients | Yes (HTMX) | Collides with members on `.window` events if both render in one tab |
| Social accounts list | Yes (explicit actions + HTMX) | `manage_social_accounts` gate |
| Connect platform | Keep as its own page | OAuth flow and the flag gate |
| Notification preferences | Yes | Per user, not per workspace |

## 3. Code that links into these pages (outside tests)

- **`base.html`**
  - L433 workspace switcher → `workspaces:settings`.
  - L742 Notifications → `notifications:list`.
  - L752 "Set up" → `studio:setup`.
  - L877 "Manage Team" → `members:list`.
  - L710 Home is active for every `studio:*` page except `setup`, so the hub, brand, autopilot etc. light Home.
- **`layouts/workspace_settings.html`** (L13-29): general, social accounts, media, approvals, clients.
- **`layouts/settings.html`**: members and API keys.
- **`organizations/partials/workspace_card.html:27`** → `workspaces:settings`.
- **`studio:setup` links**
  - `readiness._setup_url` (`readiness.py:20`).
  - `views_setup.status_line` (`:443`).
  - `opendots.py:177` (`policy_url`).
  - `templates/blog/{write,post_list,no_sites}.html`.
- **`studio:autopilot` links (deep links from Telegram cards, emails and alerts)**
  - `apps/telegram/notifications.py:333` ("Open the report").
  - `apps/studio/alerts.py:137`.
  - `live.py:679`.
  - `opendots.py:177`.
  - `views_setup.py:146,184,458`.
  - `telegram/settings.html:165` (`?open=advanced`).
- **`studio:routines` links**
  - `telegram/notifications.py:83,474`.
  - `telegram/conversations.py:418`.
  - `routines.py:681`.
  - `chat.py:797`.
  - `live.py:661`.
  - `live.py:1150` (`for_viewer` strips these links for people without `create_posts`).
- **`studio:trust` links**
  - `onboarding/checklist.py:58`.
  - `views_setup.py:330`.
  - `brand_profile.html:14`.
  - `studio/partials/thread.html:64`.
- **`studio:memory`**: `thread.html:80`.
- **`telegram:settings` links**
  - `views_setup.py:250,463`.
  - `dashboard.py:90`.
  - `customer_workflow.py:464`.
- **`workspaces:approvals_settings`**: `telegram/settings.html:80,132`.
- **`social_accounts:connect`**: 9 templates plus `onboarding/checklist.py:65` and `views_setup.py:124`.
- **`members:list`**: `onboarding/checklist.py:95`.

## 4. Test hooks

- **Set up**
  - `data-testid`: `setup-row-<key>` (L20), `setup-action-<key>` (L39, L42).
  - Data hooks: `data-setup-rows`, `data-setup-row`, `data-setup-state`, `data-setup-link`, `data-setup-progress`.
- **Settings hub**: `data-settings-cards`, `data-settings-card="<key>"`.
- **Brand**
  - `data-testid`: `brand-save` (L79), `brand-sample-image-<layout>` (L23).
  - `brand-primary-color` and `brand-accent-color` come through `studio/partials/brand_colour_field.html:10`.
- **Autopilot**: `data-autopilot-summary`, `data-autopilot-advanced` (with `open`).
- **Telegram**: `data-telegram-onboarding`, `data-telegram-progress`, `data-step=deployment|bot|pairing|approvals|advanced`.
- **Routines**: `data-routine-team-link`.
- **Connect**: `connect-platform-<value>`.

## 5. Tests that load or post to these routes

★ marks a test that enforces one of the CLAUDE.md invariants (number in brackets). These must not be edited.

### `apps/studio/tests/test_setup.py`

GET Set up and parse rows:
- L51, L79, L90 ★[9] (owner-only names), L101, L133, L160, L267.
- L77 asserts `Cache-Control == "no-store, private"`.

Access and isolation:
- L110 ★[3] `test_clients_and_outsiders_are_kept_out`: GET setup and settings_hub → 403; POST setup_lead and setup_autopilot → 403; outsider 403/404.
- L121 ★[2] `test_rows_only_read_this_workspace`.

Set up actions:
- L175-212: `setup_lead`. L180 asserts `Location == studio:setup`.
- L218-265: `setup_autopilot`.

Hub, agency tabs and sidebar:
- L281: the hub's 7 cards and "Open Set up".
- L291: tab labels and the `SETTINGS_PAGES` active mapping.
- L303: no tab leads to a refusal.
- L323: `aria-current` Settings on the autopilot page.
- L394: sidebar labels include "Set up" and "More".
- L417: `?open=advanced` appears twice on setup and once on the hub.

Home status line, policy links and readiness:
- L337, L353: status line links to `telegram:settings`.
- L510 ★[4] private Telegram jobs stay out of the Home card.
- L528 ★[9] `test_readiness_speaks_plainly_and_points_at_set_up`: the copy "open Set up" / "in Set up" must stay, and `setup_url == reverse("studio:setup")`.
- L549 and L567: `policy_url` equals `studio:autopilot` / `studio:setup`, and `policy_link == "open Set up"`.

Accessibility and creation mode:
- L584: a11y sweep GETs setup, settings_hub and index.
- L604-614: creation mode, `next=<setup url>` and `Location == setup`.
- L639: autopilot saves the mode.
- L657-693: `telegram:settings` GET answers 200.

### Other agency tests

- **`test_autopilot.py`**
  - L285, L367, L376: GET page content.
  - L292: POST → 302.
  - L302 ★[3]: viewer and client GET → 403; manager POST → 403.
  - L314 ★[2]: foreign account or client lead refused.
  - L336: plan now.
  - L351 ★[6]: plan needs provider and budget.
  - L382: a11y sweep of `autopilot` and `memory`.
- **`test_report.py:239`** and **`test_trustworthy_reporting.py:237`**: GET autopilot.
- **`test_memory.py`**
  - L189 ★[2], L255 ★[2]: another workspace's posts are never learned or toggled.
  - L222: page content.
  - L230 ★[3]: clients and people without `create_posts` → 403/404.
  - L241-318: POST endpoints. L318 ★[6] refresh is refused over budget or without a provider.
- **`test_verified_claims.py`**
  - L272: POST → 302.
  - L282 ★[3]: viewer, client and `client_facing` refused.
  - L315 ★[1]: POST inside `guards.agent_work` raises.
  - L323: rechecks authority.
  - L345 ★[2]: a foreign claim cannot be edited.
  - L356: malformed id.
- **`test_photo_provenance.py`**
  - L36-195 POST `studio:trust`.
  - L109 ★[2], L163 ★[2]: foreign or out-of-scope photos.
  - L176 ★[3]: a client cannot attest a photo.
  - L187 ★[1]: a worker cannot attest even with the owner's cookie.
- **`test_campaign_outcomes.py`**
  - L32, L59: GET 200.
  - L81: reads `.context["form"].initial["submission_token"]` from a GET.
  - L88: read-only staff 200.
  - L93 ★[3]: client and outsider 403/404.
  - L104 ★[1]: worker or API actor cannot record (service level).
  - L131 ★[2]: token cannot cross a user or workspace.
- **`test_views.py`** L199-236: brand GET and POST, `context["can_edit"]`, editor POST → 403. L240+: `brand_sample`.
- **`test_routines.py`**
  - L274 ★[4]: a private thread is never used.
  - L814-897: page, `routines_create` 400/302, toggle.
- **`test_live.py`**
  - L190: `policy_url` equals autopilot.
  - L585-595: viewer sees no links to routines or autopilot.
  - L889: GET routines.
  - L897-902: GET setup, `data-setup-link="autopilot"`.

### Telegram tests (`apps/telegram/tests/`; all need `telegram:settings` GET 200 and the POSTs at their current URLs)

- **`test_setup_page.py`**
  - L83 ★[1]: approvals switch needs the gate.
  - L106, L119 ★[9]: owner-only variable names.
  - L151: toggle and test message.
  - L170 ★[3]: clients cannot change approvals or retry the webhook.
  - L179: managed bot creation hidden unless a manager bot exists.
- **`test_onboarding_usability.py`**
  - L39-56: `pair` answers 200, and the next GET has no code.
  - L58 ★[3]: client gets the personal link only.
  - L75 ★[4]: group setup excludes the private audience.
  - L102-251: pair and managed-create errors; L236 no probing on GET.
- **`test_provisioning.py`**: ★[2/4] throughout, including L255 ★[1] gate, L284, L305, L332, L401, L449. L462 "nonce is not reloaded". L486 ★[3] client sees the pair page only. L556: CSRF on the real page.
- **`test_channels.py`**: L325, L341 ★[3], L360, L372 ★[2].
- **`apps/client_portal/test_telegram_onboarding.py:215`** ★[3]: a portal session gets 403 on `telegram:settings`, and portal context lacks `tabs`.

### Workspace, approvals, members, clients, accounts, notifications

- **`apps/approvals/test_gate.py`** `SettingsTests` L427 and L435 ★[1]: POST `workspaces:approvals_settings` → 302; a manager cannot switch the gate off.
- **`apps/members/tests/test_authorization_boundaries.py:171`**: a viewer's POST to `workspaces:settings` → 403 (security boundary).
- **`apps/accounts/tests/test_launch_security.py`** L96-124: logo and name POSTs to `workspaces:settings` → 302.
- **`apps/common/tests/test_review_a11y.py:103`**: GETs `workspaces:settings`, but skips anything that is not 200.
- **`apps/common/tests/test_navigation_and_guards.py`**: L128 ★[3] external client gets 403 on `members:list`; L136 contributor 200.
- **`apps/members/tests/test_role_hierarchy.py`**: L148, L187 GET `members:list`; L332 POST `invite_client`.
- **`apps/common/tests/test_a11y_sweep.py`** L172, L176: GETs `members:list` and `studio:brand`, expects 200 (this is the design-system ink check).
- **`apps/client_portal/test_magic_link_revoke.py:62`**: `Location` must end with `/settings/clients/`.
- **`apps/social_accounts/tests/test_views.py`**
  - L70: anonymous → 302.
  - L76-95: list GET 200.
  - L100-264: connect.
  - Callbacks at `/social-accounts/callback/x/`.
- **`apps/composer/tests/test_channelless_drafts.py:185`**: `resolver_match.url_name == "list"` on the list GET. L128: connect link.
- **`apps/composer/tests/test_no_channel_guard.py:73`** and **`apps/accounts/tests/test_signup_policy.py:151`**: connect.
- **`apps/notifications/tests.py:216-222`**, **`test_launch_usability.py:77-129`**, **`test_batched_digests.py:331`**: preferences GET 200, POST 302/400. These users may have no workspace.

### Playwright (`tests/e2e/golden/`)

- **`02-onboarding.spec.ts`**: `/studio/brand/` POST, with `Location` equal to the brand path (L62-72). `/studio/setup/` with `setup-row-accounts`, `setup-action-accounts` and `setup-action-approvers` (L80-132). `/social-accounts/<id>/connect/` path wait and the X callback (L84-119).
- **`10-brand-and-timezone.spec.ts`**: the brand path with its hooks; save `Location` equals the brand path (L113-127); editor read-only and POST refused (L221-229).
- **`11-isolation.spec.ts`** and **`11-isolation-inputs.spec.ts`** ★[2]: these sweep every route that takes `workspace_id`, from the resolver (`tests/e2e/server/steps/g1.py:385`).
  - Every one of B's URLs must answer 403/404 for every accepted method.
  - At least 150 POST URLs must exist.
  - `SAMPLE_PARTS` must equal the set of unfilled path parts exactly.
  - Any new `/settings/` route is swept automatically.

## Risks and decisions

1. **Redirect only on GET, inside the existing views, after their own checks.** Every POST test above targets the old URLs, including the invariant tests in `test_gate` SettingsTests, `test_verified_claims:315`, `test_photo_provenance:187` and `test_authorization_boundaries:171`. A bare `RedirectView` in `urls.py` would also turn invariant-3 refusals into 301s: `test_setup:110` (setup and hub), `test_autopilot:302`, `test_memory:230`, `test_campaign_outcomes:93`, `test_navigation_and_guards:128`. Keep `@login_required` outermost, so anonymous users still get the 302 to login (`social test_views:70`). Preserve `?open=advanced` and `?claim=` on the redirect.

2. **Pages that must keep rendering:**
   - `telegram:settings`: URL contract, client variant, one-time pairing codes.
   - `social_accounts:connect` and the three provider forms.
   - `notifications:preferences`: hard-coded email links, users with no workspace. At most, redirect when `request.workspace` exists.
   - `studio:brand_sample`.
   - Candidates for a GET 301 to `/workspace/<id>/settings/?tab=…`:
     - `studio:settings_hub` → Brand.
     - `studio:setup` → Advanced/Health.
     - `studio:brand` → brand.
     - `studio:trust`, `studio:memory`, `studio:outcomes` → advanced.
     - `studio:autopilot` → autopilot.
     - `workspaces:settings` → brand or advanced; it holds both name/logo and the danger zone.
     - `workspaces:approvals_settings` → approvals.
     - `client_portal_admin:client_list` and `members:list` → team. `/members/` has no workspace, so it needs a fallback.
     - `social_accounts:list` → accounts.
   - Each 301 breaks the non-invariant GET-content tests listed in section 5, and they must be updated. Outcomes is the awkward one: `test_campaign_outcomes:81` reads the form token from a GET in the same file as invariant tests. The alternative is to keep outcomes rendering.

3. **`studio:setup` must stay a named URL.** `readiness._setup_url` and `opendots` must keep reversing `studio:setup`, because `test_setup.py:542` (★9) and `:576` assert it. The readiness copy "open Set up" / "in Set up" is asserted verbatim by ★9 L537-540, so the wording stays even after the page moves.

4. **The new route must take no path part except `workspace_id`.** Use `?tab=`, not `/settings/<tab>/`, or the `SAMPLE_PARTS` check in `11-isolation.spec.ts` (★2) fails. Removing POST endpoints could also drop below the 150-POST floor.

5. **Forms without `action=`** (brand L31, trust L13/61/85, outcomes L18, workspaces/settings L14/25/91/123/182, approvals_settings L10) would post to `/settings/` once included. Choose between adding explicit actions that point at the old URLs and making the settings view dispatch POST by tab. Also fix trust's relative `href="?claim=…"` (L60), which drops `tab=`.

6. **Where to land after a save.** Every handler redirects to its old URL; with a GET 301 that becomes two hops but needs no handler change. Assertions that pin the old `Location`:
   - `test_setup:180`, `:614`.
   - `test_magic_link_revoke:62`.
   - e2e 02 L72 and 10 L127.

   Error paths re-render the standalone template at status 400 (status 200 for brand), so a bad input lands outside the tab unless POST is dispatched through the settings view.

7. **Permissions differ per tab.** The settings view must apply each tab's own gate and hide tabs that would refuse:
   - Brand: read for staff; write needs `approve_posts` or `manage_workspace_settings`.
   - Autopilot, memory, routines: `create_posts`, so viewers get 403.
   - Accounts: `manage_social_accounts`.
   - Clients: `workspace_role` manager or higher.
   - Members: org member, but not client-only.
   - General, danger zone, approvals: `workspace_role` owner or manager, while `manage_workspace_settings` belongs to owner only. Decide whether to unify.
   - Telegram: any member.

8. **Keep Autopilot as one whole form.** Lead, backup and budget are fields of `AgencySettingsForm`. Moving approvers to the Approvals tab, or budget elsewhere, means splitting the form, which wipes omitted fields. Also, `form.save()` writes the whole row, so it can overwrite `features` if Advanced ever writes flags (00-cut open question).

9. **Team & clients HTMX collision.** Both invite modals listen on `@htmx:after-request.window`. The client modal removes `#no-invites-placeholder`, which belongs to the members page. With both in one tab, any successful HTMX request closes both modals, and a client invite removes the members placeholder.

10. **Org and user scope inside a workspace screen.** Members is org-wide, notification preferences and Telegram pairing are per person, and Developers (API keys) is org-level. Decide whether these render inside the panel or appear as links.

11. **Telegram is reachable by clients** (`current_member`; tests ★3 above), while `/settings/` would be staff-only through `_workspace`. `telegram:settings` must therefore keep its own page, client sidebar and headers. The Notifications tab can link to it or include the internal body. Any page that includes the Telegram or Set up panels must carry `no-store` (`test_setup:77`).

12. **`advanced_settings` flag scope.**
    - What the flag hides: Verified facts, Creative memory and Outcomes, behind Advanced, with the flag off by default.
    - Links that still point at them: `onboarding/checklist.py:58` ("Confirm your brand facts"), the Set up facts row, `brand_profile.html:14`, and `thread.html:64,80`.
    - Decision: does the flag hide only the panel, or also refuse the routes? The recommendation is navigation only.

13. **Navigation tests will break by design.** Affected:
    - `test_setup:291`, `:303`, `:323` (agency tabs and `SETTINGS_PAGES`).
    - `:394` (sidebar "Set up" and "More").
    - `test_channelless_drafts:185` (`url_name == "list"`).
    - e2e 02 (Set up testids and connect path) and 10 (brand path).

    None of these is an invariant test. They need updating to the new routes, as the Phase 2 gate expects.

14. **Deep links from Telegram cards and alerts** (`studio:autopilot`, `studio:routines`, `studio:setup`) only need to keep resolving; a 301 satisfies the contract. If the Team board's "Plan next week" event URL changes to the settings tab, also update `live.for_viewer`'s `closed` set (`live.py:1150`).

15. **Cost of the combined page.** Building every tab's context on each request runs many queries: the Set up checklist, autopilot `last_run`, memory `best_performers`, and the Telegram `_context`. Server-render only the active `?tab=` panel; this also avoids the HTMX and Alpine id clashes above.

---

# AREA activity

# Activity: engineering map for Phase 2

Read-only mapping of branch `claude/trusting-dijkstra-m7nul1`. All paths are relative to `/home/user/calander-9-`. No file was changed, no git state changed, and nothing was run.

**Biggest constraint:** three tests that must not be edited request `reverse("studio:team")` and expect a 200 page:
- `apps/common/tests/test_a11y_sweep.py:175`
- `apps/studio/tests/test_telegram_job_privacy.py:103`
- `apps/studio/tests/test_live.py:633`

So the URL name `studio:team` cannot become a 301. The routines tests that must not be edited expect `studio:routines` to keep answering 403 to viewers and clients. Details are in section 8 and under Risks.

## 1. Routes today

All routes sit under `/workspace/<uuid:workspace_id>/studio/` (`config/urls.py:124`, `apps/studio/urls.py:38-49` concatenates the sub-modules).

| Name | Path | View | Methods and decorators |
|---|---|---|---|
| `studio:team` | `team/` | `views_agency.team_roster` (`apps/studio/views_agency.py:24-28`), which calls `views_live.team_page` (`views_live.py:40-45`) | `@login_required @require_GET`; `_workspace()` gives clients a 403; any staff member, viewer included |
| `studio:team_board` | `team/board/` | `views_live.team_board` (`views_live.py:48-69`) | `@login_required @require_GET`; `_workspace()`; `?part=strip` returns Home's card; answers 204 with `no-store` if the snapshot fails; rendered with `render_to_string` and no request |
| `studio:job` (**URL contract**) | `jobs/<uuid:job_id>/` | `views_agency.job_detail` (`:72-76`) | `@login_required @require_GET`; `_get_job` uses `chat.web_jobs(...)` scoped to the workspace, so another workspace's or a private job is a 404 |
| `studio:job_progress` | `jobs/<uuid>/progress/` | `views_agency.job_progress` (`:79-86`) | GET; sets `HX-Refresh: true` once the job is no longer active |
| `studio:job_retry` | `jobs/<uuid>/retry/` | `views_agency.job_retry` (`:89-98`) | `@require_permission("create_posts") @ratelimit(10/m) @require_POST`, then `opendots_views.apply_control(..., "retry")`; 302 to `studio:job` |
| `studio:job_cancel` | `jobs/<uuid>/cancel/` | `views_agency.job_cancel` (`:101-109`) | `create_posts`, POST; 302 to `studio:job` |
| `studio:busy` | `busy.txt` | `views_agency.health` (`:112-118`) | GET; returns plain text `"N working"`; no template uses it, only the e2e isolation sweep reaches it |
| `studio:coworker_job_control` | `coworkers/jobs/<uuid>/control/` | `opendots_views.job_control` (`apps/studio/opendots_views.py:21-30`) | `create_posts`, `ratelimit 20/m`, POST; **302** to `studio:job` (e2e path 11 expects exactly this) |
| `studio:routines` | `routines/` | `views_routines.routines_page` (`views_routines.py:70-75`) | `@login_required @require_permission("create_posts") @require_GET` |
| `studio:routines_create` | `routines/new/` | `routines_create` (`:92-120`) | `create_posts`, `ratelimit 10/m`, POST; handles both `suggestion=<key>` and the free-form form; on a `RoutineError` it **re-renders `studio/routines.html` with status 400** (`:114-117`) |
| `studio:routines_toggle` | `routines/<uuid>/toggle/` | `:132-143` | `create_posts`, POST; `_changeable`: only the author or someone with `manage_workspace_settings`, otherwise 403 |
| `studio:routines_run_now` | `routines/<uuid>/run/` | `:146-156` | `create_posts`, `ratelimit 10/m`, POST |
| `studio:routines_delete` | `routines/<uuid>/delete/` | `:159-168` | `create_posts`, POST; same author-or-manager check |

URL modules: `apps/studio/urls_agency.py:7-15`, `urls_routines.py:7-13`, `opendots_urls.py:7-9`.

How each control decides where to go back to: `views_routines._back` (`:45-50`) honours a `next` value on the same host, otherwise `redirect("studio:routines")`.

No other route can catch `activity/`: the only catch-all is `path("<uuid:brief_id>/")` (`urls.py:25`), which matches UUIDs only.

## 2. Context builders and services

- **`views_live._context`** (`views_live.py:28-37`) returns `workspace`, `live` (`live.for_viewer(live.snapshot(ws), ws, can_create=...)`), `can_create` and `can_approve`. `team_page` adds `tabs = dashboard.tabs(ws, "team", perms)`.
- **`views_agency._job_context`** (`:39-69`) returns `stages`, `runs`, `can_act` (`create_posts`), `assistant_task = opendots.task_record(job)` and `tabs` with "overview" active. `job_detail.html` never renders those tabs.
- **`views_routines._context`** (`:53-67`) returns `tabs` ("routines"), `routines = routines.rows(ws, viewer, perms)`, `suggestions`, `cadences`, `weekdays`, `form`, `error`, `tzname`, `can_manage` (`manage_workspace_settings`).
- **`apps/studio/live.py`:**
  - The snapshot is cached for 6 s (`CACHE_SECONDS`, `:43`) under key `CACHE_PREFIX "studio:live:v1:"`.
  - It costs at most 22 queries (enforced by `test_live.py:686`). `snapshot` is at `:961`, `_build` at `:979`.
  - URLs baked into the cached snapshot:
    - `studio:detail` (`:312`, `:830`, `:951`)
    - `studio:job` (`:379`, `:426`, `:854`)
    - `studio:routines` for routine events (`:661`)
    - `studio:autopilot` (`:679`)
    - `composer:compose_edit` (`:704`)
    - `approvals_url`, built from `calendar:calendar?mode=list&tab=approvals` (`:1128`, `:1178-1180`)
    - `team_url = studio:team` (`:1129`)
  - **`for_viewer`** (`:1141-1175`) hides routine titles and links from people without `create_posts` by comparing exact URLs against `closed = {studio:routines, studio:autopilot}` (`:1150`).
  - `digest` (`:1183`) hashes everything except the fields that change on every build; a refresh with the same digest swaps nothing.
- **`apps/studio/routines.py`:** `SUGGESTIONS` (`:66-96`) holds three presets:
  - `"morning"`: Morning briefing, `BRIEFING` kind, weekdays 08:30
  - `"monday"`: Monday plan, instruction, weekly on Monday at 09:00
  - `"replies"`: Draft replies to new comments, instruction, weekdays 17:00

  Other functions used here:
  - `suggestion()` (`:256`), `rows()` (`:323-376`, 2 queries using Postgres `DISTINCT ON`, returns `last_job_id`), `can_change` (`:293`), `run_now` (`:630`).
  - `_notify_creator` (`:660-697`) stores `action_url = absolute(reverse("studio:routines"))` in **persisted `Notification.data`**.
- **`apps/studio/team.py`** is the roster source: `AGENTS`, `DEPARTMENTS`, `by_department` (`:289`), `get` (`:277`).
- **`apps/studio/opendots.py:165-195`** (`task_record`): `policy_url` points to `studio:setup` or `studio:autopilot`.
- **`dashboard.tabs`** (`apps/studio/dashboard.py:56-79`): Home (`studio:index`), Routines (`studio:routines`, left out without `create_posts`), Team (`studio:team`), Settings (`studio:settings_hub`). It is called from 12 places:
  - `views.py:178`, `views_agency.py:68`, `views_live.py:44`, `views_routines.py:57`
  - `views_setup.py:516`, `views_memory.py:109`, `views_autopilot.py:122`, `views_trust.py:154`, `views_outcomes.py:74`
  - `views_chat.py:149`, `customer_workflow.py:474`, `apps/telegram/views.py:99`

## 3. Templates, partials, HTMX and hooks

**`templates/studio/team.html`**
- `:14` `data-team-live`
- `:20` includes `team_status.html`
- `:23` includes `components/agency_tabs.html`
- `:26-31` the board container:
  ```
  <div id="team-board" data-live-board data-no-error-toast hx-get="{% url 'studio:team_board' %}" hx-trigger="every 5s [document.visibilityState === 'visible']" hx-swap="innerHTML">
  ```
- `:32` `<p id="team-live-announce" role="status" aria-live="polite">`
- `:37` `live_board.js` loaded with the CSP nonce

**`partials/team_status.html`**
- `:6` `id="team-status"`, with `hx-swap-oob="true"` when `refresh` is set. Every board refresh re-renders it out of band, so any page that hosts the board must contain `#team-status`.

**`partials/team_board.html`**
- `:8` includes `team_status` on refresh
- `:9` `data-board-digest`, `data-announce`, `data-server-now`
- Includes: `team_track` (`:53`), `team_recent` (`:72` or `:78`), `team_activity` (`:77`, which includes `team_receipt` and holds the `data-hour-chart` / `data-chart-live` 24-hour chart), `team_upcoming` (`:83`), `team_roster` (`:86`)
- Idle state links to `studio:index` ("Ask your team", `:65`)

**`partials/live_strip.html`** (Home's "Right now" card)
- `:9` loads `live_board.js` unless `refresh`
- `:10-13`: `id="live-strip" data-live-strip data-no-error-toast`, `hx-get="{% url 'studio:team_board' %}?part=strip"`, `every 15s`, `hx-swap="outerHTML"`
- `:16` "Open Team" link to `live.team_url`
- `:29` includes `team_track` with `compact=True`

**`static/js/live_board.js`** (362 lines)
- Hard-codes the ids `team-board`, `live-strip` and `team-live-announce` (`:82`, `:105-106`) and the attributes `data-live-board` / `data-live-strip` (`:24`).

**`templates/studio/job_detail.html`**
- `:8` breadcrumb "Agency" points to `studio:index`
- `:20` and `:37` forms post to `coworker_job_control` (resume / pause)
- `:23` form posts to `job_retry`, `:44` to `job_cancel`
- `:72` `data-task-waiting-policy`
- `:78` includes `job_progress`
- It does **not** render `agency_tabs`.

**`partials/job_progress.html`**
- `:2-3`: `id="job-progress"`, `hx-get studio:job_progress`, `every 4s`, `outerHTML`, only while `job.is_active`
- Includes `components/agent_avatar.html` and `agent_state.html`

**`templates/studio/routines.html`**
- `:13` agency tabs
- `:25-26` includes `routine_rows` with `team_url = {% url 'studio:team' %}`
- **Free-form form inline at `:36-76`** (fields `instruction`, `cadence`, `weekday`, `time`, `title`; Alpine `x-data`); it is not a partial
- **Presets inline at `:80-98`** (posts `suggestion=<key>`, **no `next`**); not a partial
- "Nothing goes out without you" callout at `:100-107`

**`partials/routine_rows.html`**
- Context: `routines`, `workspace`, `can_manage`, `team_url`
- `:20` `data-routine-team-link` "See it on Team"
- `:33` run now, `:39` toggle, `:44` delete; each carries `next = request.path` (`:35`, `:41`, `:46`)

**`components/agency_tabs.html`** (11 lines)
- Renders `<nav aria-label="Agency">`, a segmented control with `aria-current="page"`
- Included by: `index`, `team`, `routines`, `memory`, `trust`, `settings_hub`, `autopilot`, `outcomes`, `thread`, `telegram/settings.html:27`

**Home (`templates/studio/index.html`)**
- `:17` tabs
- `:134-135` `{% if live %}{% include "studio/partials/live_strip.html" %}`
- `:164-189` routines section:
  - `data-home-routines`
  - "All routines" link to `studio:routines` (`:169`)
  - `routine_rows` with `team_url` (`:173`)
  - `data-home-routines-empty` with "pick a routine" linking to `studio:routines` (`:178`)
  - `data-home-morning-briefing` form posting `suggestion=morning` with `next` = Home (`:179-184`)
- Context in `apps/studio/views.py`: `_index_context` `:140-182` (`live`, `team_url` `:160-161`, `routine_rows` `:171`), `_live_strip` `:185-207` (needs `create_posts` or `approve_posts`, never a plain client; falls back to None on error), `_routine_rows` `:210-216` (`create_posts`, limit 3)

**`data-testid` hooks in this area: none.** The only hooks are `data-*` attributes (listed above, plus `data-health`, `data-live-age`, `data-live-ago`, `data-live-elapsed`).

**Sidebar** (`templates/base.html:710`): Home is highlighted for `match.app_name == 'studio' and match.url_name != 'setup'`, so Team, Routines and job pages all light Home today.

## 4. Places that link into these routes

Names in **bold** must keep working because their URLs are stored or sent outside the page.

**`studio:job`**
- **`alerts.py:102`** (stored as Notification `action_url` and sent as a Telegram "Open it" button)
- **`telegram/conversations.py:352`** ("Open the task")
- `blog/views.py:744,747`; `templates/blog/team_job.html:18`; `templates/blog/partials/seo_site_overview.html:111`
- `views_memory.py:257,272`; `views_autopilot.py:187,213`
- `dashboard.py:199,351,430`; `customer_workflow.py:293,303`; `live.py` (see section 2)
- `templates/studio/memory.html:60,66`; `autopilot.html:207`; `partials/thread_messages.html:41`
- `opendots_views.py:30`

**`studio:routines`**
- **`routines.py:681`** (stored in Notification data)
- **`telegram/notifications.py:83,474`** and **`telegram/conversations.py:418`** (Telegram buttons)
- `chat.py:797` (the `set_routine` card's "All routines" link, rendered at `thread_messages.html:62`)
- `live.py:661,1150`; `dashboard.py:64`; `index.html:169,178`; `views_routines.py:50`

**`studio:routines_toggle`**: `chat.py:795` (thread card), plus `routine_rows`.

**`studio:team`**: `views_setup.py:194` ("See your team at work"), `live.py:1129`, `dashboard.py:65`, `routines.html:25`.

## 5. Polling endpoints the live views use

| Poller | Endpoint | Interval | Swap | Notes |
|---|---|---|---|---|
| Team board (`#team-board`) | `studio:team_board` | 5 s while the tab is visible | `innerHTML`, plus out-of-band `#team-status` | Must stay under `CACHE_SECONDS` = 6 (`test_live.py:724` checks this with a regex on `studio:team`'s HTML) |
| Home strip (`#live-strip`) | `studio:team_board?part=strip` | 15 s while visible | `outerHTML` | Browser tabs left open during a deploy keep polling the old path |
| Job timeline (`#job-progress`) | `studio:job_progress` | 4 s while active | `outerHTML`; `HX-Refresh` at the end | |

`studio:busy` is not polled by anything.

## 6. pytest tests that load these routes, links or templates

**I** = pins one of the nine invariants, or is treated as such by `docs/specs/phase-1.md:8-9,70` and `BETA_PLAN.md:371` ("the 403 tests", `test_a11y_sweep.py`). Never edit these.

**`apps/common/tests/test_a11y_sweep.py`**
- `:175` **I**. `"agency_team": reverse("studio:team")`; `_render` asserts 200 (`:180-183`); faint text, control names and dialogs are checked.

**`apps/studio/tests/test_telegram_job_privacy.py`** (invariant 4)
- `:88` **I**. `job`, `job_progress`, `job_retry` and `job_cancel` answer 404 for a private job.
- `:103` **I**. `GET studio:team` returns **200** containing the shared summary and never the private title or summary.
- `:191` **I**. `studio:job` on a private job is a 404.

**`apps/studio/tests/test_live.py`** (`_url` helper at `:36`)
- `:507` **I** (4). Private jobs and their turns stay out of the snapshot.
- `:526`. Content of `studio:team`: polls every 5 s, `team_board` URL, `live_board.js`, headings, `team-live-announce`, every agent. The board must not contain the banned vendor words (**I**, invariant 9).
- `:547`. `team_board` is GET only, `no-store`, out-of-band `team-status`; the strip contains "Open Team"; POST returns 405.
- `:582`. A viewer on `studio:team` and on the board sees no routine text and no `href` to `studio:routines`, `studio:autopilot` or `composer:compose_edit`. Permission trimming: treat as do-not-edit.
- `:613`. A viewer on `studio:team` and on `?part=strip` gets "Next: Routine, " with no secret text.
- `:633` **I** (3). Viewer gets 200 on `studio:team` and `team_board`; client gets 403 on both and on `?part=strip`; an outsider gets 302, 403 or 404; signed out gets 302 to login.
- `:656`. `dashboard.tabs(..., "team")` contains "team" and it is active.
- `:724`. The `hx-trigger` regex on `studio:team`.
- `:742`. `team_board` stays within 30 queries.
- `:762`. Home: `data-live-strip`, "Open Team", `href=studio:team`, `?part=strip`; order is Today, then the strip, then the thread.
- `:781`. Viewer: no card on Home, and **`studio:team` returns 200**.
- `:792`, `:812`, `:823`, `:836` (`id="team-board" data-live-board data-no-error-toast` on `studio:team`), `:846` (Home query budget).
- `:871`. `studio:routines` page: `data-routine-team-link` with `href=studio:team` and "See it on Team".
- `:895`. Set up links to `studio:team` ("See your team at work").
- `:906` **I** (9). The roster names no vendor.

**`apps/studio/tests/test_agency_pages.py`**
- `:62`. `studio:team` shows the three headings, every agent and every department.
- `:79` **I** (3). A client gets 403 on `studio:index` and `studio:detail`.
- `:111`. Job timeline, plus `HX-Refresh` on `job_progress`.
- `:123`. Viewer gets 403 on `job_retry`; retry needs a review receipt.
- `:139` **I** (2). A job from another workspace is a 404 on `studio:job`.

**`apps/studio/tests/test_routines.py`** (`_url` at `:65`)
- **I**:
  - `:274` and `:1270`: never uses a private thread (4)
  - `TestGates` `:285` (6)
  - `TestLease` `:426`: never retries (7)
  - `:648`: the tick never raises (7)
  - `TestRoutinesNeverApprove` `:768` (1)
  - `TestPermissions` `:957`: client and viewer get **403 on GET `studio:routines`** and on every POST
  - `TestPermissions` `:967`: signed out gets 302 to login
  - `TestPermissions` `:971`: another editor gets 403 on toggle and delete
  - `TestIsolation` `:1017` and `:1028` (2)
- UI tests (may be updated):
  - `TestPage` `:811-946`: tab order; GET `studio:routines` content including `aria-current` and the three presets; `:846` with `follow=True` expects "Saved"; `:858` expects 400 plus a sentence; `:870` presets return 302; `:912` and `:921` a foreign `next` falls back to `Location == studio:routines`; `:932` a11y on the routines page
  - `TestChatAction` `:1143` and `:1182` (thread card toggle with `next`)
  - `TestHomeRows` `:1289` and `:1301` (Home contains `studio:routines`, "All routines", the morning form)
  - `:489` (toggle with `follow=True`, expects "On. Next run")

**`apps/studio/tests/test_setup.py`**
- `:291`. Tab labels: first is "Home", last two are "Team", "Settings".
- `:303` **I** (it pins a 403). `dashboard.tabs` for someone without `create_posts` must equal `["overview","team","settings"]`; a viewer's Home must not contain `studio:routines`; GET `studio:routines` returns 403 for the viewer; **an editor's Home must contain the `studio:routines` URL** (`:320`).
- `:323`. Settings pages light up the Settings tab.
- `:549` and `:567`. `studio:job` shows the waiting-on-policy state.

**`apps/studio/tests/test_opendots.py`**
- `:203` **I** (2, 4). Foreign and private job ids are refused.
- `:217` and `:250` **I** (6). No bypass of workspace policy; no paid work without a provider.
- `:261`. The old retry view cannot bypass the review receipt (invariant 1, via `studio:job_retry`).

**`apps/telegram/tests/test_routines_telegram.py`**
- `:34`, `:87`, `:132` assert the **literal path** `/workspace/<id>/studio/routines/` in Telegram buttons (`:39`, `:119`, `:158`).
- `:71` **I** (3) and `:165` **I** (2).

**`apps/blog/tests/test_seo_pages.py:208`**: `Location == reverse("studio:job")`.

## 7. Playwright e2e

- No golden or self spec opens Team, Routines, a job page or Activity, and none uses copy from those pages. Golden paths 02 and 03 render Home (with the strip) under axe.
- **`tests/e2e/golden/11-isolation.spec.ts`** **I** (2) discovers every workspace URL through `tests/e2e/server/steps/g1.py`:
  - `_B_ROWS` `:206-256` includes `job_id` and `routine_id`; `_methods` `:297` reads the `require_GET` / `require_POST` decorators.
  - B's URLs must answer 403 or 404. The middleware answers 403 before any view runs, so new redirect views pass.
  - `:163` `byName(['studio:index','studio:job'])` requires both names to exist.
  - `:182` requires `'studio:coworker_job_control'` to answer **302** to A's `studio:job` path; `redirectTo` accepts 302 only.
  - `:350` requires the set of non-row path parts to equal `SAMPLE_PARTS` exactly.

## Risks and decisions

1. **`studio:team` cannot become a 301 as the URL name stands.** Three tests that must not be edited request `reverse("studio:team")` and expect 200: `test_a11y_sweep.py:175`, `test_telegram_job_privacy.py:103` and `test_live.py:633` (also `:781`).
   - Option A: move the name. Put `path("activity/", <activity view>, name="team")`, or give it both a new `activity` name and keep `team`, and add `path("team/", <301>)` under a new name. Old `/studio/team/` links then 301, while `reverse("studio:team")` returns the Activity page with status 200.
   - Option B: keep `/studio/team/` rendering. This breaks the spec rule that every route outside the URL contract answers 301.
   - Whichever page answers `studio:team` must keep, for every test above: `#team-status`, `#team-board` with `data-live-board data-no-error-toast` polling every 5 s, `#team-live-announce`, `live_board.js`, every agent name, and no private job text.
2. **`studio:routines`.** A viewer or client must still get 403 and a signed-out visitor a 302 to login (`test_routines.py:957`, `:967`; `test_setup.py:315`). A 301 view must therefore apply `@login_required`, `@require_permission("create_posts")` and `_workspace()` before redirecting. Telegram tests pin the literal path `/studio/routines/`, and old Notification rows and Telegram cards store it, so keep that path as a gated 301 to Activity, perhaps with `#routines`.
   - Activity is for every staff member, viewers included, so its routines section and preset forms must render only with `create_posts`.
   - `test_live.py:582` forbids an `href` to `studio:routines` and any routine title on the page answering `studio:team` for a viewer.
3. **`test_setup.py:303` is a 403 test that must not be edited** and it also asserts:
   - `dashboard.tabs` returns `["overview","team","settings"]` for people without `create_posts`;
   - an editor's Home contains the `studio:routines` URL (`:320`).

   Removing the Agency tabs or pointing Home's "All routines" link at Activity breaks it. Decide whether `dashboard.tabs` keeps its keys (even if the strip changes) and whether Home keeps linking to `studio:routines`, which would then 301.
4. **Free-form form and presets.** Both are inline in `routines.html` (`:36-76`, `:80-98`); neither is a partial.
   - Phase 2 must extract them (a template refactor, no restyle) so that Activity includes the presets and Settings → Advanced includes the form.
   - `routines_create` re-renders `studio/routines.html` with 400 on an error (`views_routines.py:114-117`; test `:858`). Choose which template and context an error re-render uses. The form needs `cadences`, `weekdays`, `form`, `tzname` and `error`.
   - Preset forms carry no `next`, so after one tap the person lands on `studio:routines` and goes through a 301. Add `next` or change `_back`'s default; `test_routines.py:921` pins `Location == studio:routines` for a foreign `next`.
5. **Keep these paths unchanged:**
   - `studio:job` and its `jobs/<uuid>/` path (URL contract; stored in alerts, Notifications and Telegram).
   - `job_progress`, `job_retry`, `job_cancel`, `coworker_job_control` (which must keep answering 302).
   - `studio:team_board` at `team/board/`, because open Home tabs poll it.

   Moving any of these to a 301 that takes an object id breaks e2e path 11 (rules expect 404 or exactly 302) and the 404 tests in `test_telegram_job_privacy.py`. Activity's URL must not take a non-row path part, or path 11's `SAMPLE_PARTS` check fails; use a query string instead.
6. **Links baked into `live.py`.** Routine events point to `studio:routines` (`:661`) and `team_url` to `studio:team` (`:1129`).
   - If routine events are repointed to an Activity anchor, `for_viewer`'s `closed` set (`:1150`) must include the new URL, or viewers get a link to a section they cannot see.
   - On Activity, routine events and `routine_rows`' "See it on Team" (`team_url`) would point back to the same page. Decide whether to drop `team_url` there or turn it into an anchor (`test_live.py:871` pins the current link).
7. **"Job list".** No job-list view exists. Activity today could only reuse the board's "Working now" (`MAX_TRACKS` 8) and "Recently finished" (`RECENT_LIMIT` 10, chat jobs excluded). Any new list must go through `chat.web_jobs` / `chat.web_agent_runs` (invariant 4; `test_telegram_job_privacy.py:103` loads `studio:team`) and should keep its query count bounded. `routines.rows` adds 2 queries.
8. **Copy pinned by tests that may be updated.** "Open Team" (`test_live.py:547`, `:762`), "See it on Team" (`:871`), "See your team at work" (`:895`), tab labels (`test_setup.py:291`). Renaming to Activity means updating these.
9. **Sidebar highlight.** `base.html:710` lights Home for every studio page except `setup`. The Activity item needs its own `url_name` set (`team` or `activity`, `job`, `routines`), and the Home condition must exclude them. The job page breadcrumb (`job_detail.html:8`) points to Home, not Activity.
10. **Existing copy issue, out of scope.** Flash messages in `opendots_views.py:48-50` say "Your assistant will…", which the CLAUDE.md naming rules forbid; `job_detail.html:30` says "AI charge". No test pins them.

---

# AREA flags

# Feature switches (Phase 2 map): `blog`, `queues`, `templates`, `advanced_settings`, `extra_providers`

Line numbers are from HEAD `3e12c00`. `templates/base.html` has an uncommitted change in the working tree (focus handling around line 330). From about line 350 down, the working-tree line numbers are one higher than the numbers below.

## 0. The helper as it stands

- **`apps/common/features.py`**
  - `FEATURE_KEYS = ("blog", "queues", "templates", "extra_providers", "advanced_settings")` (line 21).
  - `_blog_default` (lines 24–28) returns true when the workspace has a `BlogSite` with `is_enabled=True`. `_DEFAULTS` (line 32) holds only `blog`; every other key starts off.
  - `feature_enabled(workspace, key)` (lines 35–45) raises `ValueError` for an unknown key. It makes one `AgencySettings` `values_list` query, plus one `BlogSite.exists()` query when `blog` is not set explicitly. A value that is not a boolean falls back to the default.
- **Storage:** `AgencySettings.features` in `apps/studio/models.py:563-570`, with `default=dict` and `db_default={}`.
- **Admin:** `apps/studio/admin.py:4,21-32`. `clean_features` rejects unknown keys and values that are not booleans.
- **Nothing reads the helper yet** (requirement R4). A grep for `feature_enabled|FEATURE_KEYS|features_for` finds only the module and the admin.
- **Tests:**
  - `apps/common/tests/test_features.py`. **`test_a_switch_is_for_its_own_workspace_only` enforces invariant 2.** The query-count tests (`test_at_most_two_queries`, `test_one_query_when_the_switch_is_set`) pin the cost.
  - `apps/studio/tests/test_features_field.py`. **`RollbackSafeColumnsTests` enforces invariant 8. `test_the_workspace_cannot_be_changed_on_an_existing_row` and `test_the_change_page_lists_no_other_organisations_accounts` enforce invariant 2.**

### Where a `features_for(workspace)` helper should live

- **Function:** put `features_for(workspace) -> dict[str, bool]` in `apps/common/features.py`, next to `feature_enabled`.
  - It should share one resolver, for example `_resolve(raw_dict, workspace, key)`, so both functions apply the same "not a boolean means default" and "not an object means defaults" rules.
  - Cost: one `AgencySettings` query, plus one `BlogSite` query only when `blog` is not set explicitly. This meets the "at most two queries" rule.
- **Per-request cache:** memoise as `request._features`. Requests can still reach `feature_enabled` from views; the shared memo avoids repeated queries.
- **Context processor:** add `apps.common.context_processors.features` in `apps/common/context_processors.py`. Register it in `config/settings/base.py:152-161` after `sidebar_context`; no settings override `TEMPLATES`.
  - Return `{"features": SimpleLazyObject(lambda: features_for(request.workspace))}`, or `{}` when there is no `request.workspace`.
  - It must be lazy. Context processors run on every `render(request, …)`, including HTMX partials. `sidebar_context` (lines 52–184) already makes about eight queries per render.
- **Where `request.workspace` comes from:** `apps/members/middleware.py:113-136`, from the URL's `workspace_id`. Global pages such as `/notifications/` fall back to `last_workspace_id` (lines 84–101). That covers `/social-accounts/<uuid:workspace_id>/…` too. It does not cover `/onboarding/connect/<token>/`, which has no `workspace_id`; that view must call `features_for(link.workspace)` itself.
- **View gate:** add a `require_feature(key)` decorator in `apps/common/features.py`.
  - It must be the innermost decorator, after `@login_required` and `@require_permission`, so the permission tests that expect 403 still get 403.
  - Unknown keys should fail at import time.
- **Templates fail silently:** Django swallows lookup errors, so `{% if features.blgo %}` is silently false. Add a test that greps `templates/**/*.html` for `features\.(\w+)` and checks each key is in `FEATURE_KEYS`.

---

## 1. `blog`

Default: on when the workspace has an enabled `BlogSite` (Neopolis and More Space today).

| Entry point | Location | URL name → path | View, decorators |
|---|---|---|---|
| Sidebar "Blog & SEO" | `templates/base.html:729-732` | `blog:list` → `/workspace/<ws>/blog/` | `apps/blog/views.py:222-258` `post_list`: `@login_required @require_GET`, no permission check |
| New article (manual) | inside `templates/blog/post_list.html` | `blog:create` → `…/blog/new/` | `views.py:335-363` `post_create`: `login_required, require_permission("create_posts")`. Renders `blog/no_sites.html` when there is no enabled site (lines 340–341) |
| Write with the team | inside `templates/blog/*` | `blog:write` → `…/blog/write/` | `apps/blog/views_team.py:132-136`: `create_posts`, `@ratelimit 10/m` |
| Set up row "Blog website" | `apps/studio/views_setup.py:349-383`, called at line 429 | links to `blog:search_console_connect` (line 374) and `blog:list` (line 382) | `checklist()`. `templates/studio/setup.html:20,39,42` has `data-testid="setup-row-blog"` and `setup-action-blog` |
| Autopilot "Blog articles per month" and "Website" | `templates/studio/autopilot.html:85-95`; form `apps/studio/forms_agency.py:110-121, 156-157, 187-190, 218-219`; `views_autopilot.py:36` | `studio:autopilot` → `/workspace/<ws>/studio/autopilot/` | |
| Home "Waiting for you" article rows | `templates/studio/index.html:56` (`data-testid="home-today-article-<pk>"`), links at lines 75 and 78 → `blog:detail`; data from `apps/studio/dashboard.py:139-160` (`waiting`) and 270–281 (`waiting_blogs`) | `blog:detail` → `…/blog/<post_id>/` | `views.py:423-425` |
| Search Console connect | links from the Setup row and the blog list | `blog:search_console_connect`, `_property`, `_sync`, `_disconnect` → `…/blog/search-console/<site_id>/…` | `views_search_console.py:51-176`: `manage_workspace_settings`, ratelimit. The callback is the global name `blog_search_console_callback` → `/blog/search-console/callback/` (`config/urls.py:118-122`) |
| Autopilot article planning (background) | `apps/studio/jobtypes/plan.py:531-555` `_articles_wanted` (needs `blog_posts_per_month > 0` and an enabled site); `:742-760` creates child `AgencyJob.Kind.BLOG` jobs | — | — |
| Other links into blog pages | `apps/studio/views_chat.py:83` (redirects to `blog:detail` after a send in the article thread); `apps/studio/jobtypes/blog.py:1247` (notification URL → `blog:detail`); `apps/common/management/commands/live_verify.py:823` (`blog:preview`) | | |
| Recurring tasks | `apps/blog/apps.py:29-46`: `sweep_stuck_blog_publishes`, `queue_search_console_syncs`, `queue_seo_checkups` | | |

**What "hidden" means here** (navigation and creation only):

- **Hide:** the sidebar item, `blog:create` and `blog:write` (GET and POST), the autopilot blog fields, and the Setup "blog" row (or keep the row only for owners).
- **Keep:** `blog:detail`, `preview`, `cover`, `status`, `submit`, `approve`, `request_changes`, `publish`, `social_drafts`, `team_panel`, `team_job` and `team_retry`. Home rows, notifications and chat redirects point at these.
- **Keep running:** the recurring tasks and articles already planned.

**Shared partial:** `templates/blog/partials/field.html` is included by `templates/studio/brand_profile.html:39-73`. Keep that partial available whatever the switch says.

**Tests:**

- `apps/blog/tests/` (`conftest.py:43-70`: `world` makes two enabled sites, so blog is on by default): `test_views.py`, `test_team_views.py`, `test_seo_pages.py`, `test_search_console.py:242`, `test_covers.py`, `test_ai_images.py`, `test_publisher.py`, `test_seo_monitor.py`.
  - `test_team_views.py:160-166` `test_a_workspace_without_a_website_gets_the_no_sites_page` disables the site. That turns the default off, so a gate on `blog:write` breaks this test.
- `apps/studio/tests/test_setup.py`:
  - lines 50–77 assert the exact row set, including `blog` and `facts`, and "of 11 steps";
  - lines 395–404 assert the sidebar label "Blog &amp; SEO";
  - lines 406–415 GET `blog:list`.
  - The `world` fixture in `apps/studio/tests/conftest.py:47` makes **no** `BlogSite`, so blog is off there. These three tests will fail and need flags set or updating.
- `apps/studio/tests/test_blog_job.py`, `test_chat.py:667`, `test_autopilot.py`.
- **`apps/studio/tests/test_telegram_job_privacy.py:194-221` enforces invariant 4.** It needs `blog:write` and `blog:team_panel` to answer **200** for a workspace with an enabled site. It passes only if the gate follows the default (site means on); requiring an explicit `features.blog=True` would break it.
- e2e: `tests/e2e/golden/11-isolation.spec.ts:231` (`EMPTY_WHEN_REFUSED = ['blog:team_panel']`), `:354` (`blog:detail`); `tests/test_e2e_steps_sign_in_isolation.py:95-97`; `tests/e2e/server/steps/g1.py:572` (only workspace B gets a `BlogSite`, so blog is off in workspace A).

---

## 2. `queues`

Queues and recurring rules are hidden; the posting schedule stays visible.

| Entry point | Location | URL name → path | View, decorators |
|---|---|---|---|
| Sidebar More "Queues" | `base.html:773-776`; More stays open when on `queue_list` or `queue_detail` (line 758) | `calendar:queue_list` → `/workspace/<ws>/calendar/queues/` | `apps/calendar/views.py:1623` `@login_required` only |
| Create queue | `templates/calendar/queues.html:28` (`hx-post`), `:69` (`hx-get` refresh) | `calendar:queue_create` → `…/queues/create/` | `views.py:1653`: `require_permission("edit_others_posts")`, `require_POST` |
| Queue detail and management | `queues.html:83,97`; `queue_detail.html:8,45` | `queue_detail`, `queue_delete`, `queue_reorder`, `queue_entry_remove`, `queue_entry_reslot` → `…/queues/<id>/…` (`apps/calendar/urls.py:21-35`) | `views.py:1684-1800` (`edit_others_posts` or `create_posts`) |
| Composer "Add to queue / Next available / Prioritise" (the **default** publish mode) | `templates/composer/compose.html:1445-1490`, hidden `queue_id`/`queue_priority` at 1561–1562 | `composer:save_post` → `/workspace/<ws>/compose/save/` with `action=add_to_queue` or `add_to_queue_priority` | `apps/composer/views.py:1127` (`create_posts`); queue lookup at 545–580, actions at 1308–1380, compose context at 749–754 |
| Default queue made on connect | `apps/calendar/services.py:19-38` `create_default_queue_and_slots`, called at `apps/social_accounts/views.py:1134-1136` | — | Every connected account gets a queue plus default slots |
| Recurrence (no UI) | no form control in any template; server path `save_post` `make_recurring` at `composer/views.py:1232-1258, 1445-1449`; "Repeats" icon on chips `templates/calendar/partials/_post_chip.html:28`; worker `apps/calendar/tasks.py:29-57` | | |
| **Keep:** Posting schedule | `base.html:777-780` | `calendar:posting_slots` → `…/calendar/posting-slots/` (plus `save`, `grid`, `toggle-day`, `<id>/delete`, `<id>/update`) | `views.py:1426` (`login_required`), `1458+` (`manage_social_accounts`); slot grid on the account card at `templates/social_accounts/partials/_account_card.html:197` |
| **Keep:** Calendar list "Queue" tab | `templates/calendar/partials/publish_list_shell.html:14-16` (`data-testid="publish-tab-queue"`); `calendar.html:23,26,599,605` | `calendar:publish_tab_queue` → `…/calendar/publish/queue/` | `views.py:1120`. This tab lists all scheduled posts; it is not the Queues feature. `publish_queue.html:32` labels each row "Queue" or "Custom" |

**What "hidden" means here:**

- **Hide:** the sidebar item, the `queue_list` and `queue_detail` pages, and `queue_create`.
- **Leave open:** the entry and queue mutations, and anything already queued or recurring keeps publishing.

**Tests:**

- `apps/common/tests/test_navigation_and_guards.py:64-78` `test_the_six_orphaned_pages_are_linked` asserts that the Calendar page links `queue_list`, `template_list`, `category_list` and `csv_upload`.
- `apps/composer/tests/test_channelless_drafts.py:183-188` GETs `queue_list` and expects the active "Queues" label.
- `apps/common/tests/test_review_a11y.py:150-168` GETs `queue_list`, `posting_slots`, `template_list`, `category_list` and `csv_upload` and expects 200.
- `apps/studio/tests/test_setup.py:403` (link to `queue_list`).
- `apps/calendar/tests.py` (queues at 276, 341, 451, 907, 1052, 1092); `apps/calendar/test_bulk_actions.py:318`; `apps/publisher/tests.py:423`; `apps/publisher/test_publish_confirmation.py:322`; `apps/composer/tests/test_proposed_publish_at.py:317-360`; `apps/composer/tests/test_no_channel_guard.py:56`.
- **`apps/composer/tests/test_launch_integrity.py` enforces invariant 1:** `test_contributor_queue_actions_submit_for_review` (210–226, expects **302** and `pending_review` for `add_to_queue`), `test_changed_approved_content_cannot_bypass_review_through_queueing` (228–240), and the queueing rollback test (285+). Recurrence validation is at 360–425.
- **`apps/calendar/test_security.py:119-160` (V6, foreign category on `queue_create` answers 404) enforces invariant 2.**
- `apps/members/tests/test_authorization_boundaries.py:158-170` expects **403** for a viewer on `queue_create` and `queue_delete`.
- `test_navigation_and_guards.py` `CalendarRecurrenceQueryTests`.
- **`tests/e2e/golden/11-isolation.spec.ts:171-174` enforces invariant 2.** For the owner it expects `calendar:queue_entry_remove` to answer `json({removed:false})`, and `delete_posting_slot` / `update_posting_slot` to answer `json`.

---

## 3. `templates`

Templates, categories and tags are hidden; CSV import stays.

| Entry point | Location | URL name → path | View, decorators |
|---|---|---|---|
| Sidebar More "Templates" | `base.html:781-784` | `composer:template_list` → `/workspace/<ws>/templates/` | `composer/views.py:3615` `login_required` |
| Sidebar More "Categories" | `base.html:785-788` | `composer:category_list` → `/workspace/<ws>/categories/` (plus `create`, `<id>/edit`, `<id>/delete`) | `3521` (`login_required`); `3543`, `3572`, `3597` (`edit_others_posts`, POST); template `composer/categories.html:28,51,73,87` |
| Compose "Save as template" | `compose.html:485-513` (`{% if post and is_edit %}`, fetch at 504) | `composer:save_as_template` → `…/compose/<post_id>/save-as-template/` | `3633` (`create_posts`, POST) |
| Compose "Use template" and picker | `compose.html:514-534` (`hx-get` at 527) | `composer:template_picker` → `…/templates/picker/`; `use_template` → `…/templates/<id>/use/` | `3687`, `3704` (`login_required`, GET); partial `composer/partials/template_picker.html:4` |
| Template delete | `templates_list.html:49` | `composer:template_delete` | `3673` (`edit_others_posts`) |
| Ideas page "Templates" tab (built-in gallery) | `templates/composer/create_landing.html:421-422`, `519-524`; `partials/template_gallery.html:66`; `?template=` resolver at `views.py:583-613` | `composer:create_landing` → `/workspace/<ws>/create/` | `3043` (`create_posts`) |
| Compose "Category" select | `compose.html:1225-1238` (already behind `{% if categories %}`) | — | — |
| Compose "Tags" (Tag model, "Internal team only") | `compose.html:1242-~1375` (`tag_create` fetch at 1264 and 1276) | `composer:tag_create` → `/workspace/<ws>/tags/create/`; `tag_list` → `…/tags/` (JSON) | `4043` (`create_posts`, POST); `4029` (GET) |
| Idea modal tags (sidebar New → Idea) | `base.html` idea modal plus `tag_create` at 1351; data from `context_processors.py:156-165` `sidebar_idea_tags` | | |
| Ideas board tags | `create_landing.html:1291` | | |
| Calendar list "All tags" filter | `publish_list_shell.html:36` | | |
| Queue category select | `queues.html` (form) | | |
| **Keep:** CSV import | today **only** in the sidebar More: `base.html:789-792` | `composer:csv_upload` → `/workspace/<ws>/import/csv/` (plus `preview/`, `confirm/`) | `3722`, `3800`, `3889` (`create_posts`) |
| **Keep:** YouTube video tags | `compose.html:847-852` (`yt_tags_<acc>`) | — | These are a platform option, not the Tag model |

**What "hidden" means here:**

- **Hide:** the sidebar items, the template, category and tag controls in compose, the idea modal and the filters, and the creation endpoints.
- **Keep:** existing categories and tags on posts.
- **CSV import needs a new link.** The sidebar New menu (`base.html:453-488`: `sidebar-new-toggle` → Post `composer:compose` at 469, Idea `sidebar-new-idea` at 479) has no CSV entry today. Phase 2 must add the link inside New post before More goes away.

**Tests:**

- **`apps/composer/tests/test_template_picker.py:66` (`test_picker_excludes_other_workspace_templates`) enforces invariant 2.**
- `apps/composer/tests/test_round6_backend.py:134` (`tag_create`).
- `apps/members/tests/test_authorization_boundaries.py:150-155` (403 on `category_delete` and `template_delete`).
- `apps/common/tests/test_a11y_sweep.py:168` (GETs `category_list`); `test_review_a11y.py:159-163`; `test_navigation_and_guards.py:64-78`.
- CSV: `apps/composer/tests/test_csv_upload_size.py`, `apps/accounts/tests/test_cto_review.py:52-58`, `apps/common/tests/test_shell_a11y.py:86-101` (asserts the "Import from CSV" and "Posting schedule" sidebar labels, and the page `h1`s).
- `apps/media_library/tests/test_tag_endpoints.py` covers media-library tags, which are a separate system and not affected.

---

## 4. `advanced_settings`

Verified facts, Creative memory and Outcomes.

| Entry point | Location | URL name → path | View, decorators |
|---|---|---|---|
| Settings hub cards | `apps/studio/dashboard.py:86-88` (`settings_cards`, 80–98); `SETTINGS_PAGES` at 51; template `templates/studio/settings_hub.html:14-20` (`data-settings-cards`, `data-settings-card="<key>"`) | `studio:settings_hub` → `/workspace/<ws>/studio/settings/` | `views_setup.py:508-519` |
| Verified facts | cards above; `templates/studio/brand_profile.html:14`; `templates/studio/partials/thread.html:64` (photo provenance link); `views_setup.py:328-346` `_facts_row` (`setup-row-facts`); **`apps/onboarding/checklist.py:52-59`, milestone `verified_facts` "Confirm your brand facts", the first step**; `apps/studio/readiness.py:114-115` warning "Verify your facts in Set up…" | `studio:trust` → `…/studio/verified-facts/` | `views_trust.py:17-19` `login_required`, GET/POST; refuses clients inside the view; POST calls `guards.forbid_in_agent_work` |
| Creative memory | card; `thread.html:80` ("Creative memory" link) | `studio:memory`, `memory_house_style`, `memory_upload`, `memory_refresh`, `memory_reference` → `…/studio/memory/…` | `views_memory.py:132-249`: `require_permission("create_posts")`, POSTs `@ratelimit 10/m` |
| Outcomes | card | `studio:outcomes` → `…/studio/outcomes/` | `views_outcomes.py:23-26`: `login_required`, ratelimit on POST, refuses clients inside the view |

**Tests:**

- `apps/studio/tests/test_setup.py:280-287` asserts the `trust`, `memory` and `outcomes` cards; 290–299 cover tab mapping; 50–77 cover the `facts` row.
- **`apps/studio/tests/test_verified_claims.py`:** 315 `test_agent_context_cannot_attest…` enforces **invariant 1**; 345 `test_foreign_claim_edit…` enforces **invariant 2**.
- **`apps/studio/tests/test_photo_provenance.py`:** 187 (worker cannot attest) enforces **invariant 1**; 176 (client cannot attest) enforces **invariant 3**. It also covers lines 29 and 198.
- **`apps/studio/tests/test_memory.py`:** 189 and 255 enforce **invariant 2**; 230 (clients refused) enforces **invariant 3**; 318 (refused over budget) enforces **invariant 6**. It also covers 218–330.
- **`apps/studio/tests/test_campaign_outcomes.py:93` (client and outsider refused) enforces invariant 3.**
- `apps/studio/tests/test_agency_activation.py:42-60` (onboarding milestone `verified_facts`).

---

## 5. `extra_providers`

Bluesky, Mastodon, DEV.to, Threads and TikTok.

| Entry point | Location | URL name → path | View, decorators |
|---|---|---|---|
| Connect screen grid | `templates/social_accounts/connect.html:39-67` ("Ready to connect", `data-testid="connect-platform-<value>"`) and 78–120 ("Not available yet") | `social_accounts:connect` → `/social-accounts/<ws>/connect/` | `apps/social_accounts/views.py:205-269`: `login_required, require_permission("manage_social_accounts"), ratelimit 20/m`. The list comes from `_get_visible_platform_choices()` (44–50, site-wide `PlatformVisibility`, `models.py:399-433`). **The POST check at 226–229 is the natural gate**; it redirects to the three forms at 238–243 |
| Bluesky, Mastodon, DEV.to forms | the connect POST redirect; `bluesky_connect.html:21`, `mastodon_connect.html:21`, `devto_connect.html:21` | `connect_bluesky`, `connect_mastodon`, `connect_devto` → `/social-accounts/<ws>/connect/{bluesky,mastodon,devto}/` | `views.py:573-575`, `674-677`, `631-633` (`manage_social_accounts`). **They do not check `PlatformVisibility` today** |
| Reconnect (must stay open) | `_account_card.html:41,157`; `templates/analytics/_page.html:15` | `social_accounts:reconnect` → `/social-accounts/<ws>/<account_id>/reconnect/` | `views.py:772-803`. **For Bluesky, Mastodon and DEV.to it redirects to the same `connect_*` forms (780–785)**; Threads and TikTok go through OAuth |
| OAuth callback (must stay open) | — | `social_accounts:oauth_callback` → `/social-accounts/callback/<platform>/`; `select_account` → `/social-accounts/select-account/` | `views.py:272-275` (no `workspace_id`; the workspace travels in the signed state) |
| **Second connect screen (client connection link)** | `templates/onboarding/connection_page.html` | `onboarding:connection_page` → `/onboarding/connect/<token>/`; `connection_oauth_start`, `connection_bluesky`, `connection_mastodon`, `connection_devto`; `onboarding:oauth_callback` → `/onboarding/connect/callback/<platform>/` | `apps/onboarding/views.py:262-310` lists **all** `PlatformCredential.Platform.choices` (it does not even apply `PlatformVisibility`); forms at 644–723; there is no `request.workspace`, so the view must use `link.workspace` |
| Sidebar connect suggestions | `apps/common/context_processors.py:111-132` (`sidebar_connectable_platforms`, ranking at 187–216) | — | No template renders this; only a test reads it |
| Links that only lead to the connect page | `compose.html:373`, `inbox/partials/_empty_state.html:19`, `calendar/posting_slots.html:36`, `calendar/partials/_no_channels_banner.html:10`, `studio/autopilot.html:68`, `analytics/no_accounts.html:22`, `blog/partials/team_panel.html:46`, `social_accounts/list.html:13,40`, `views_setup.py:124`, `onboarding/checklist.py:65` | | |
| Composer accounts (must keep showing) | `composer/views.py:106, 714` | — | Filters on connection status only, not platform. Leave as is |
| `LAUNCHED_PLATFORMS` | `config/settings/base.py:337`, default `["bluesky","mastodon","devto"]`; `config/settings/e2e.py:128`; read only by `context_processors._platform_availability` (30–49) and `apps/marketing/views.py:176` | public pages only | |

**Tests:**

- `apps/social_accounts/tests/test_views.py`: connect grid and POST 100–200 (TikTok PKCE 125–146, Threads 159–200); TikTok reconnect 272–300; Threads callback 332–375; Bluesky and Mastodon forms 960–990. **905 `test_another_workspaces_account_is_not_reachable` enforces invariant 2.**
- `apps/common/tests/test_navigation_and_guards.py:52-62` asserts `bluesky` and `mastodon` are in `sidebar_connectable_platforms`.
- `apps/onboarding/tests.py`, `apps/onboarding/test_launch_usability.py` (connection page).
- `apps/common/tests/test_legal_pages.py:30`, `apps/accounts/tests/test_signup_policy.py` (`LAUNCHED_PLATFORMS`).
- `apps/composer/tests/test_no_channel_guard.py`, `test_channelless_drafts.py`.
- e2e: `tests/e2e/golden/02-onboarding.spec.ts:79-124` (Set up → `setup-action-accounts` → connect → `connect-platform-x`; X is not affected).
- **`tests/e2e/golden/11-isolation.spec.ts` enforces invariant 2:** `:70` excludes `social_accounts:oauth_callback`, `:82` excludes `onboarding/connect/`.

---

## Risks and decisions

1. **The gate must answer 404, sit after the permission check, and leave URL patterns in place.**
   - `11-isolation.spec.ts` (invariant 2, must not be edited) expects 404 for every object URL in workspace A that carries B's rows. Workspace A has no `BlogSite` and no flags, so its switches are off. A gate that redirects with 302 fails the sweep.
   - It also expects named answers: `calendar:queue_entry_remove` → `json({removed:false})`, posting-slot update and delete → `json`. Gating those endpoints breaks the spec. **Leave queue-entry and slot mutations ungated.**
   - Removing or renaming a URL changes the sampled-part list (`SAMPLE_PARTS`) and the `byName` lookup (`blog:detail`), which also breaks the spec. **Hide routes; do not remove them.**
   - `test_authorization_boundaries.py` expects 403 from `require_permission` before any other answer.
2. **Do not gate `save_post` queue actions on the server.** The invariant-1 tests in `test_launch_integrity.py` post `add_to_queue` and `add_to_queue_priority` with no flags and expect 302 or 400 (approval).
   - "Next available" is the composer's **default** mode and runs on the queue made automatically for every connected account.
   - Choose one: keep "Next available" visible when queues are off (it really means "next free slot"), or hide it and make "Schedule" the default. Hiding it changes the composer's default action for every beta workspace.
3. **Recurrence has no UI today.** Only the `make_recurring` POST path, the chip icon and the worker exist. Decide whether to reject `make_recurring` when queues are off, or to leave it alone because nothing reaches it.
4. **"Queue" names two different things.** The Calendar list tab `publish_tab_queue` / `data-testid="publish-tab-queue"` (all scheduled posts) is not the Queues feature. The target IA's "Calendar replaces … Queue list" refers to this tab. Keep it whatever the switch says, and consider renaming its label.
5. **Blog defaults to off for test and e2e workspaces with no enabled site.**
   - These will fail: `test_setup.py` 395–404 ("Blog &amp; SEO" label), 406–415 (`blog:list` GET), 50–77 (row set and "of 11 steps"), and `test_team_views.py:160-166` (the no-sites page reached only with a disabled site).
   - The invariant-4 test `test_telegram_job_privacy.py:194-221` passes only if the gate follows the default (an enabled site means on).
   - Decide whether `blog/no_sites.html` stays reachable at all: with the default, it now appears only when blog is explicitly on and there is no site.
6. **Blog work that already exists keeps appearing when the switch is off.** Autopilot (`plan.py:531-555, 742-760`) keeps writing articles when `blog_posts_per_month > 0`; Home still lists them (`dashboard.py:139-160`), and notifications link to `blog:detail`. The spec recommends hiding navigation and creation only. So: keep the detail, review and publish routes open, and either keep the Home article rows or filter them by the switch.
7. **The autopilot form breaks if the blog fields are only hidden in the template.** `blog_posts_per_month` is a required `TypedChoiceField` (`forms_agency.py:110`). Remove the fields in the form's `__init__` when blog is off, so a save never wipes or rejects the stored quota.
8. **`advanced_settings` off by default leaves Verified facts unreachable** behind the onboarding **first** milestone (`checklist.py:52-59`), the readiness warning (`readiness.py:114-115`), the Setup `facts` row, the Brand page link and the thread's provenance link. The team avoids prices and dates without verified claims. Choose one: exempt Verified facts (show it on the Brand or Advanced tab for everyone), or rewrite those four links. The owner must decide whether Verified facts is advanced at all.
9. **Bluesky, Mastodon and DEV.to reconnect goes through the connect forms.** Gating `connect_bluesky`, `connect_mastodon` and `connect_devto` outright breaks reconnect for accounts already connected, which conflicts with resolution 2. Allow the form when the workspace already has an account on that platform (or pass a reconnect flag); gate only new connections. Threads and TikTok are gated only at the POST check in `connect_platform` (226–229); reconnect and the callback stay open.
10. **The client connection link is a second connect screen** (`onboarding:connection_page`). It ignores even `PlatformVisibility` and has no `request.workspace`. It needs its own `features_for(link.workspace)` filter, or clients can still connect hidden providers.
11. **Filtering `sidebar_connectable_platforms` breaks a test.** `test_navigation_and_guards.py:52-62` asserts Bluesky and Mastodon are offered; this context variable is rendered nowhere, so either delete it or update the test.
12. **`LAUNCHED_PLATFORMS` contradicts the beta.** Its default advertises exactly the three hidden providers as "live" on the public pages. The spec defers this to Phase 5; record it as known.
13. **Tests that enumerate More links will fail once those links are flag-gated:** `test_navigation_and_guards.py:64-78`, `test_review_a11y.py:150-168`, `test_shell_a11y.py:86-101`, `test_channelless_drafts.py:183-188`, `test_a11y_sweep.py:168`. Update them to set the flag, and add an off-state counterpart for each. They are not invariant tests.
14. **CSV import has no home outside More.** Its only link is `base.html:789`. Add it to New post (or the New menu) before More is removed, and keep `test_shell_a11y`'s "Import from CSV" page-title check passing.
15. **The Ideas page has a built-in Templates tab** (`create_landing.html:421,519-524`). It is part of `templates`, but the IA merges Ideas into New post anyway. Decide in the same change.

---

# AREA cut

# Phase 2 engineering map: cut items (Intelligence, API keys, Agent API docs, MCP, OAuth server, `studio:workflow_*`)

Branch `claude/trusting-dijkstra-m7nul1`. Everything below was found by reading files only; nothing was run.

## 1. Routes and whether they keep working

| Item | Mounted at | URL names | Views / decorators |
|---|---|---|---|
| API keys UI | `config/urls.py:67` `path("organizations/api-keys/", include("apps.api_keys.urls"))` | `api_keys:list` → `/organizations/api-keys/`; `api_keys:issue` → `issue/`; `api_keys:revoke` → `<uuid:key_id>/revoke/`; `api_keys:edit` → `<uuid:key_id>/edit/`; `api_keys:workspace_options` → `_workspace-options/` (HTMX partial) | `apps/api_keys/views.py`. Every view is wrapped in `_require_manage_api_keys` (lines 61-79): `login_required`, then a 403 unless `has_org_permission(request.org_membership, "manage_api_keys")`. Owner and Admin hold it; Member does not (`apps/members/models.py:282-302`). The view sets `"settings_active": "api_keys"` (line 121). |
| Agent API and its docs | `config/urls.py:84` `path("api/v1/", agent_api.urls)`; namespace `agent_api_v1` (`apps/api/api.py:70`) | `agent_api_v1:openapi-view` → `/api/v1/docs`; `agent_api_v1:openapi-json` → `/api/v1/openapi.json`; `agent_api_v1:api-root` (names checked in `ninja/openapi/urls.py:22,34,41`) | `NoncedSwagger` (`api.py:30-35`, template `templates/ninja/swagger_cdn.html`). There is no `docs_decorator`, so the docs page is public. |
| MCP | `api.py:85` `api.add_router("/mcp", mcp_router, auth=McpAuth())` → `/api/v1/mcp` and `/api/v1/mcp/` | (Ninja router) | `apps/mcp/transport.py`. The app has no templates and no UI. |
| OAuth server | `config/urls.py:89` `path("oauth/", include("apps.oauth_server.urls"))`; `app_name = "oauth2_provider"` | `oauth2_provider:authorize` → `/oauth/authorize/`; `:token`; `:revoke-token`; `:register` → `/oauth/register`; plus `oauth-authorization-server-metadata`, `oauth-protected-resource-metadata`, `oauth-protected-resource-metadata-mcp` under `/.well-known/…` (`config/urls.py:90-108`) | django-oauth-toolkit views, plus `apps/oauth_server/views.py`. Templates: `templates/oauth2_provider/authorize.html` and `base.html`. Neither contains an in-app link. |
| Intelligence | Mounted **only when `settings.INTELLIGENCE_ENABLED`** (`config/urls.py:166-178`): `orgs/<uuid:org_id>/intelligence/` (namespace `intelligence`) and `intelligence/` (namespace `intelligence_global`) | `intelligence:playground`, `subscribe`, `checkout`, `discard-checkout`, `recover`, `portal`, `billing-settings`, `update-billing-contact`, `status`, plus six tool endpoints; `intelligence_global:activate`, `finalizing`, `finalizing-status` (`apps/intelligence/urls.py`) | `@require_org_permission("use_intelligence" / "manage_intelligence_billing")` and `@intelligence_subscription_required` (`apps/intelligence/views.py:169-1363`). Templates in `templates/intelligence/*`; `playground.html`, `subscribe.html` and `billing_settings.html` extend `base.html`. |
| Older workflow endpoints | `apps/studio/urls.py:45` (+ `urls_customer_workflow.urlpatterns`), under `/workspace/<uuid>/studio/` | `studio:workflow` → `workflow/` (GET); `studio:workflow_create` → `workflow/create/` (POST, `@ratelimit 10/m`); `studio:workflow_status` → `workflow/status/` (GET, JSON); `studio:workflow_resume` → `workflow/<uuid:conversation_id>/resume/` (POST, `@ratelimit 10/m`) | `apps/studio/views_customer_workflow.py:22-83`. All four use `@login_required` and `_staff_workspace` (`views_chat.py:35-40`: 403 without `create_posts`). |

**Will the URLs keep working?** If Phase 2 only removes links:
- Yes for API keys, `/api/v1/*` (including the docs), MCP and `/oauth/*`. Their mounts in `config/urls.py` do not depend on any navigation.
- Intelligence works only when its five environment variables are set (`config/settings/base.py:857-875`). Without them the routes are not mounted at all (404). It is False in test (unset) and in `config/settings/e2e.py:172`.
- `workflow_*` keeps working as long as `urls_customer_workflow` stays included.

**Only `studio:workflow` is a redirect.** It sends a GET to `studio:index` (line 27). The other three are live endpoints:
- `workflow_create` saves and starts an idea.
- `workflow_status` returns JSON with the In progress rows.
- `workflow_resume` starts a saved idea.

**`studio:workflow_resume` is still used by Home:**
- `customer_workflow._journey` builds `"resume_url": reverse("studio:workflow_resume", …)` (`apps/studio/customer_workflow.py:425-427`).
- Home calls `_journey` through `views._journeys` (`apps/studio/views.py:120-137`).
- `templates/studio/index.html:160` includes `templates/studio/partials/customer_workflow_journeys.html`.
- Line 25 of that partial renders `<form method="post" action="{{ journey.resume_url }}">…Continue…</form>` when `journey.can_resume and can_create`.

`workflow_create` and `workflow_status` have no caller in any template or static JS (searched `templates/`, `static/`, `theme/static_src/src`). Only tests and the partial's comment (line 4) refer to them.

## 2. Every navigation, menu, button or link to a cut item

### App UI (signed-in)
1. **`templates/base.html:807-813`** is the main sidebar Intelligence item:
   ```
   {% if INTELLIGENCE_ENABLED and request.org %}
   <a href="{% url 'intelligence:playground' org_id=request.org.id %}" class="sidebar-nav-item {% if request.resolver_match.app_name == 'intelligence' %}active{% endif %}">… Intelligence
   ```
   `INTELLIGENCE_ENABLED` comes from the context processor `apps.intelligence.context_processors.intelligence_flag` (`base.py:161`).
2. **`templates/layouts/settings.html:35-38`** is the organisation settings sidebar item "API keys": `{% url 'api_keys:list' %}`, active when `settings_active == 'api_keys'`. Templates extending this layout:
   - `accounts/settings.html`
   - `organizations/settings.html`, `organizations/workspaces.html`, `organizations/cross_calendar.html`
   - `members/list.html`
   - `media_library/shared_library.html`
   - `api_keys/list.html`
3. **Internal links inside cut apps:**
   - `templates/api_keys/list.html:22`, `_issue_modal.html:16,41` (`hx-get` to `api_keys:workspace_options`), `_key_row.html:81,213`.
   - All of `templates/intelligence/*` (for example `subscribe.html:14`, `billing_settings.html:12`, `_finalizing_completed.html:3,6`, and the HTMX `hx-post`/`hx-get` calls in the `_panel_*.html` files and `_overlay_finalizing.html:4`).
   - Redirects in `apps/intelligence/views.py` and `decorators.py:48,58`.
   These stay; they only matter once someone is inside the cut page.
4. **Workflow:** no navigation link anywhere.
   - `apps/studio/dashboard.py:72` maps `active in ("workflow", "thread")` to the Home tab.
   - `customer_workflow.py:474` passes `dashboard.tabs(current, "workflow", …)`.
   - Both are tab-highlight keys, not links.
5. **None found** in the Set up checklist, readiness, Telegram, notifications or email:
   - `apps/onboarding/checklist.py:51-95` links calendar, trust, connect, thread and members.
   - `apps/studio/readiness.py:22` links `studio:setup`.
   - Telegram and notifications reverse only `studio:autopilot/detail/index/job/routines`.
   - Searching email templates for api, intelligence, MCP, developers and workflow gave no hits.
6. **Copy only, no link:** `templates/workspaces/approvals_settings.html:66` says "the API, MCP clients and automations can only submit for review". This describes invariant 1; keep it.

### Copy that points people to "Organization → API Keys" (goes stale if the sidebar item moves)
- `apps/api/api.py:43`, the OpenAPI description shown at `/api/v1/docs`: "create one from the Organization → API Keys page".
- `templates/marketing/developers.html:27` ("Issue a key from **Organisation → API Keys**") and `:170`.
- `templates/marketing/get_started.html:26` ("API keys and MCP available from the organisation settings").
- `README.md:789`.

### Marketing pages (public)
- `templates/marketing/base.html:41`: header nav "Developers" → `marketing:developers`.
- `templates/marketing/base.html:77`: footer "API & MCP" → `marketing:developers`.
- `templates/marketing/base.html:86`: footer "API reference" → `marketing:developers#openapi`.
- `templates/marketing/home.html:266` (bullet), `:274-297` (the "Developers teaser" section `id="dev"`, with the link at `:282` "API and MCP reference" → `marketing:developers`).
- `templates/marketing/get_started.html:153`: "Read the API docs" → `marketing:developers`.
- `templates/marketing/features.html:216`: "API and MCP built in" card (copy only).
- `templates/marketing/developers.html:15,81,173`: hard-coded `href="/api/v1/docs"`. View at `apps/marketing/views.py:269-281` (`api_base_url=settings.APP_URL…+"/api/v1"`); route `apps/marketing/urls.py:12` (`developers/`).
- `templates/pricing.html` extends `marketing/base.html`, so it inherits the "Developers" nav item.
- `config/urls.py` `sitemap_xml` does not list `/developers/`. `robots_txt` disallows `/api/` and `/oauth/`.
- Developers and Platforms pages are hidden from public navigation by the marketing work in cut row 18.

### Machine-readable links (not navigation; leave alone)
- `apps/oauth_server/metadata.py:23,32,43`: `authorization_endpoint` and `service_documentation`/`resource_documentation` = `{MCP_PUBLIC_BASE_URL}/api/v1/docs`.

### `data-testid` hooks
None in `layouts/settings.html`, `api_keys/*`, `intelligence/playground.html`, `marketing/base.html`, `marketing/developers.html` or `customer_workflow_journeys.html`. Data attributes that do exist: `id="workflow-journeys"`, `data-workflow-journey`, `data-workflow-state` (partial lines 8 and 10).

## 3. Where the single "Developers" link should point

The target is Settings → Advanced, a workspace screen under `/workspace/<id>/settings/`. There are three options.

**A. `api_keys:list` → `/organizations/api-keys/`.**
- This is the only in-app UI among the four cut apps, so it is the natural target.
- It is organisation-scoped, but `RBACMiddleware.process_view` (`apps/members/middleware.py:142-157`) sets `request.org_membership` to the workspace's own organisation on workspace pages. So `has_org_permission(request.org_membership, "manage_api_keys")` is the right check.
- Show the link only to Owner/Admin. A Member gets a 403 there, which breaks the existing rule "no tab leads to a refusal" (`dashboard.tabs` docstring, `dashboard.py:54-57`).
- The page renders inside the organisation settings layout (`layouts/settings.html`), whose back link goes to `calendar:calendar`.
- The page does not link to `/api/v1/docs` or explain MCP (`templates/api_keys/list.html:1-17`). If it is the only target, people cannot get from it to the docs.

**B. `agent_api_v1:openapi-view` → `/api/v1/docs`.** Public Swagger, no auth, no app chrome. No test covers it rendering, including the CSP nonce.

**C. `marketing:developers` → `/developers/`.** A public page that links to `/api/v1/docs` and explains MCP. It is being hidden from public navigation, and its copy names "Claude Code" and "Claude Desktop" (`developers.html:118-126`; also `home.html:281`). Invariant 9 forbids vendor names in user-facing copy, so linking to it from inside the app is questionable.

Option A fits "URLs keep working so … the Developers link has somewhere to go" (`00-cut.md:108-109`). It needs the permission guard. The API reference link would then have to live on the API keys page or next to the Developers link (B), which is a decision for Phase 2.

## 4. Tests that assert on these routes, links or labels

**Navigation and labels (may need updating if Phase 2 changes them; not invariant tests):**
- `apps/common/tests/test_pricing.py:30-38` `test_pricing_uses_the_marketing_sites_header_and_footer`: asserts `">Developers</a>"`, `"Platforms"`, `"Get started"` and `"How it works"` appear in the pricing page header. **This breaks when Developers is removed from the marketing nav.**
- `apps/marketing/tests.py:13-20` `PUBLIC_PAGES` includes `"marketing:developers"`. Lines 27-43 require a 200 that extends `marketing/base.html` and is read-only (405 on POST). This breaks only if the route is redirected or removed.
- `apps/studio/tests/test_setup.py:395-403` `test_the_sidebar_is_short_with_more_behind_a_disclosure`: asserts `"customer_workflow" not in html` (line 402). Phase 2's new nav keeps this true. The labels on line 399 belong to the navigation area.
- `apps/api_keys/tests/test_views.py:145-150`: `reverse("api_keys:list")` returns 200 and contains `b"API keys"`. Line 148 matches the page `<h1>` and `<title>`, not the sidebar.
- No test asserts the sidebar "API keys" item (`layouts/settings.html:35`) or the Intelligence sidebar item (`base.html:808`). Intelligence is never enabled in tests: `apps/intelligence/tests/test_discard_checkout.py:40-55,355-370` mounts its own `ROOT_URLCONF`, and `tests/test_e2e_server.py:452,530` asserts e2e has intelligence False.

**Route behaviour for `workflow_*` (would need updating only if the routes change):**
- `apps/studio/tests/test_setup.py:374-379` `test_the_old_guided_page_redirects_home`: 302 to `studio:index`. A switch to 301 would fail this.
- `apps/studio/tests/test_customer_workflow.py:280-286` `test_the_guided_page_is_home_now`: 302 to index; the viewer gets 403.
- `test_customer_workflow.py:264-278`: `workflow_status` JSON, `no-store`, and the partial's `id="workflow-journeys"`.
- `test_customer_workflow.py:288-297`: `workflow_create` POST.
- `test_customer_workflow.py:299-304`: `workflow_status` access is re-checked after membership revocation.
- `apps/accounts/tests/test_guided_landing.py:37`: `studio:workflow` returns 403 for viewer and client.

**Cut-app behaviour (confirms the URLs keep working):**
- `apps/api_keys/tests/test_views.py` (list, issue, revoke, edit, `workspace_options`; 403 for a member at lines 186-201 and 509; anonymous redirected to login at 203-207; cross-organisation revoke/edit returns 404 at 470-485 and 615-628).
- `apps/api/tests/test_review_fixes_round2.py:425-447` uses the literal paths `/organizations/api-keys/_workspace-options/` and `/organizations/api-keys/issue/`, so the mount path must not change.
- `apps/api/tests/*`, `apps/mcp/tests/*` (`/api/v1/mcp/`), `apps/oauth_server/tests.py:130-160` (metadata endpoints end in `/oauth/authorize/` and similar), `apps/oauth_server/test_token_storage.py`.

**Tests that enforce a CLAUDE.md invariant (must not be edited):**
- **Invariant 1** (Agent API and MCP never approve): `apps/approvals/test_gate.py`, including `test_automation_cannot_approve` (92), `test_unapproved_content_cannot_be_scheduled_by_anyone` (136), `test_the_api_cannot_create_a_scheduled_post` (145) and `test_a_different_time_needs_an_approver` (163), all using `actor.API`. Also `apps/api/tests/test_review_fixes_round2.py:206` `test_schedule_route_blocked_when_workspace_requires_approval`.
  - The rule behind them is path-based: `apps/approvals/actor.py:28-35` `_NON_DASHBOARD_PREFIXES = (("/api/", API), ("/oauth/", API), ("/portal/", PORTAL))`.
  - Moving the Agent API, MCP or OAuth off `/api/` or `/oauth/`, or putting a dashboard-session view under those prefixes, changes who counts as a person in the dashboard.
- **Invariant 3** (clients only in the portal): `apps/client_portal/test_security_boundaries.py:86-92` `test_approval_link_cannot_change_account_or_authorize_oauth` asserts `GET /oauth/authorize/` returns 403 for a portal session.
- **Invariant 2** (isolation):
  - `tests/e2e/golden/11-isolation.spec.ts`:
    - `byName(swept, [… 'api_keys:revoke'])` at line 314. `byName` fails with "every named URL still exists" (150-155).
    - `notFoundAnswers` maps `'studio:workflow_resume': redirectTo(home.path)` (line 180), so A's resume with B's `conversation_id` must still redirect to A's Home.
    - `OTHER_UNSWEPT_PREFIXES['api/v1/']` (line 81) is checked for staleness at 286-291, so some route under `api/v1/` must exist.
  - `tests/test_e2e_steps_sign_in_isolation.py:124-161` asserts `"api_keys:revoke": "/organizations/api-keys/<key_id>/revoke/"`.
  - `apps/api_keys/tests/test_views.py` cross-organisation 404 tests (470-485, 615-628).
  - `apps/studio/tests/test_customer_workflow.py:208` `test_private_history_and_other_workspaces_are_excluded` (also invariant 4), `:105` `test_private_threads_cannot_become_shared_workflow_reply_targets` (invariant 4), and `:216` `test_client_custom_role_cannot_open_the_staff_workflow` (invariant 3).
- **Invariant 6:** `workflow_create` and `workflow_resume` carry `@ratelimit(key="user", rate="10/m")` (`views_customer_workflow.py:31,53`); keep these if the views are touched.

## Risks and decisions

1. **Do not redirect or remove `studio:workflow_resume`, `workflow_create` or `workflow_status`.**
   - `workflow_resume` is the live POST target of Home's In progress "Continue" button (`customer_workflow.py:425`, partial line 25).
   - Golden 11 (an isolation test) names `studio:workflow_resume` and expects a redirect to A's Home for an unknown conversation.
   - A 301 on a POST endpoint would also drop the action.
   - "Redirects kept during the beta" (cut row 26) can only mean `studio:workflow` stays a redirect. Whether it stays a 302 or becomes a 301:
     - `test_setup.py:379` and `test_customer_workflow.py:282` assert 302, so a change to 301 needs those tests updated (they are not invariant tests).
     - It must keep pointing to `studio:index`, which stays at `/studio/`.
2. **Keep the mount paths for the cut apps:** `organizations/api-keys/`, `api/v1/`, `oauth/` and `.well-known/…`.
   - Literal paths in tests: `test_review_fixes_round2.py:429,438`; `test_e2e_steps_sign_in_isolation.py:147`; the golden 11 prefix `api/v1/`.
   - The invariant-1 actor prefixes (`/api/`, `/oauth/`) depend on these paths.
3. **Intelligence:** remove `base.html:807-813`.
   - If any replacement link is ever kept, it must stay inside `{% if INTELLIGENCE_ENABLED %}`. Otherwise `{% url 'intelligence:playground' %}` raises NoReverseMatch in tests, in e2e and on every deployment without the five variables, because the namespace is not registered.
   - Intelligence pages extend `base.html`. Once the link is gone they render with no active nav item; that is acceptable.
4. **The "API keys" item in `layouts/settings.html:35-38`:** remove it in favour of Settings → Advanced → Developers, or keep it because the organisation settings sidebar is not "beta navigation". Decide this explicitly.
   - If it is removed, `api_keys/list.html` still extends that layout and still highlights `settings_active == 'api_keys'` (harmless).
   - These copies then point to a menu item that no longer exists: `api.py:43`, `developers.html:27,170`, `get_started.html:26`, `README.md:789`. Decide whether Phase 2 updates them; the copy is not navigation.
5. **The Developers link:** choose its target (section 3) and its visibility rule. Recommended guard: `has_org_permission(request.org_membership, "manage_api_keys")` (Owner/Admin). Otherwise a Member follows the link into a 403.
   - Add a test for the link. None exists today because the Advanced tab is new.
   - No test covers `/api/v1/docs` rendering under CSP (`NoncedSwagger`). Add one if the link targets the docs.
6. **Marketing:** removing "Developers" from `marketing/base.html:41` (and the footer at 77 and 86) breaks `apps/common/tests/test_pricing.py:33`, which asserts `">Developers</a>"` and `">Platforms</a>"`.
   - Keeping `marketing:developers` rendering (hidden, not redirected) keeps `apps/marketing/tests.py` `PUBLIC_PAGES` green.
   - A redirect instead needs that list updated.
   - `home.html:274-297` and `get_started.html:153` link to `marketing:developers`. Decide whether they go along with the three-page rewrite.
   - `developers.html` and `home.html:281` name "Claude", which conflicts with invariant 9's no-vendor-names rule if these pages stay public.
7. **Golden 11 sweeps every workspace URL automatically** (`isolation_urls` probe, `tests/e2e/server/steps/g1.py:384-405`). Any new Settings → Advanced or Developers route under `/workspace/<id>/` is swept: it must answer 403 or 404 for workspace B, and give a 404-style answer for B's rows under A. A redirect view that takes an object id would fail unless it is added to `notFoundAnswers`, which would mean editing an invariant test.
8. **Telegram, emails, the checklist and readiness have nothing to change.** None of them link to a cut item (checked `apps/telegram`, `apps/notifications`, `apps/onboarding/checklist.py`, `apps/studio/readiness.py` and email templates).

---

# AREA marketing

## Marketing site map (Phase 2, no restyling)

Repository checked: `/home/user/calander-9-` at HEAD `3e12c00`. Other sessions have uncommitted changes in `templates/base.html` and `apps/common/tests/test_shell_a11y.py`; none are in this area. Paths under `.claude/worktrees/*` are copies and are left out.

### 1. Routing

Root URLconf: `config/urls.py`
- L18: `from apps.marketing import views as marketing_views`
- L132: `terms` -> `/terms/` is `TemplateView(template_name="legal/terms.html")`
- L133: `privacy` -> `/privacy/` is `TemplateView("legal/privacy.html")`
- L137: `support` -> `/support/` is `TemplateView("legal/support.html")`
- **L138: `pricing` -> `/pricing/` is `marketing_views.pricing`.** It is a root name with no `marketing:` namespace and is not in `apps/marketing/urls.py`.
- L52: `sitemap_xml` lists `["/", "/pricing/", "/terms/", "/privacy/", "/support/"]`.
- L24-41: `robots_txt` has `Allow: /$`. No marketing path is disallowed.
- L152: `path("", include("apps.marketing.urls"))` is mounted before L153 `path("", include("apps.accounts.urls_root"))`. Because of this order, `/` resolves to `marketing.views.home`, while `reverse("dashboard")` (`apps/accounts/urls_root.py:8`, `views.home`) still gives `/`. That name is never served directly.

`apps/marketing/urls.py` (`app_name="marketing"`):

| name | path | view |
|---|---|---|
| `marketing:home` | `/` | `views.home` (L8) |
| `marketing:features` | `/features/` | `views.features` (L9) |
| `marketing:how_it_works` | `/how-it-works/` | `views.how_it_works` (L10) |
| `marketing:platforms` | `/platforms/` | `views.platforms` (L11) |
| `marketing:developers` | `/developers/` | `views.developers` (L12) |
| `marketing:get_started` | `/get-started/` | `views.get_started` (L13) |

There is no request-invite route, view, form, model or template anywhere in the repository. A search for waitlist, access_request, invite_request, early_access and contact form found nothing.

### 2. Views: `apps/marketing/views.py` (295 lines)

- L23 `UPSTREAM_URL` (AGPL notice). L27-156 `PLATFORMS` (14 rows). L159-172 `NETWORKS`.
- L175-192 `_page(...)` builds the context: `site_name`, `upstream_url`, `source_url`, `page_key`, `page_title`, `meta_description`, `site_url`, `canonical_url`, `networks`, and `platforms` (with `live` taken from `settings.LAUNCHED_PLATFORMS`).
- Every view is `@require_GET` with no auth decorator and no permission check.
  - `home` L195-209: `if request.user.is_authenticated: return dashboard(request)` (imported from `apps.accounts.views`). Otherwise renders `marketing/home.html`.
  - `pricing` L212-224: renders the root template `pricing.html`.
  - `features` L227, `how_it_works` L241, `platforms` L255.
  - `developers` L269, which adds `api_base_url=APP_URL + "/api/v1"` at L280.
  - `get_started` L284.
- The module docstring says the pages do "no per-request database work". A Request invite POST would be the app's first database write.
- `apps/accounts/views.py:59-71` (`home`) is the fallback if marketing is ever unmounted (it redirects to `account_login`). `dashboard` is at L74 and `_workspace_landing` at L111.

### 3. Templates

`templates/marketing/` holds 7 page templates and 1 partial. `templates/pricing.html` is outside that folder.
- `base.html` (108 lines) loads `static/css/marketing.css` (L24) and `static/js/marketing.js` (L106).
  - Header nav L38-43: features, how_it_works, platforms, developers, get_started, `{% url 'pricing' %}`.
  - Mobile CTA L45-46 and desktop CTA L50-51: `account_login`, and `account_signup` labelled `{% if SIGNUP_OPEN %}Create account{% else %}Request early access{% endif %}`.
  - Footer "Product" L74-77: features, how_it_works, platforms ("Supported platforms"), developers ("API & MCP").
  - Footer "Get going" L83-86: account_signup, account_login, get_started ("Self-host it"), `developers#openapi`.
  - **Footer "Legal" L92-95: `{{ LEGAL_TERMS_URL }}`, `{{ LEGAL_PRIVACY_URL }}`, `{% url 'support' %}`, `{{ source_url }}` "Source code".**
  - L101: the upstream AGPL link.
- `home.html` (313 lines):
  - signup CTAs L15 and L307; `how_it_works` L16, L211 and L237 (`#engine`)
  - `platforms` L48 and L55; `features` L191; `pricing` L248; `developers` L282; `get_started` L308
  - Section ids: `#what`, `#how`, `#engine`, `#deal`, `#dev`
  - L281 names "Claude" (vendor name in public copy). The same goes for `developers.html` L122 and L125.
- `how_it_works.html` (144): `get_started` L127, signup L138, `features` L139. Section `#engine` at L89.
- `features.html` (234): `platforms` L11 and L229, signup L228.
- `platforms.html` (107): signup L101, `get_started` L102.
- `developers.html` (178): signup L172. Anchors `#openapi`, `#auth`, `#limits`, `#endpoints`, `#mcp`.
- `get_started.html` (158): `SIGNUP_OPEN` branches L22, L24 and L29; login L30; `developers` L153; `source_url` at about L44.
- `_icon.html`: a one-line SVG partial.
- `templates/pricing.html` (104): extends `marketing/base.html` and adds an inline `<style nonce>` with `pr-*` classes. "Get the source" uses `SOURCE_URL`, falling back to `account_signup` (L56). Managed and Agency CTAs are `mailto:{{ SUPPORT_EMAIL }}` (L71, L86).

Across all marketing and legal templates there are **no `data-testid`, no `hx-*` attributes and no `<form>`**. `marketing.js` uses `[data-nav]`, `[data-nav-toggle]`, `[data-header]`, `.reveal`, `[data-copy]` and `[data-year]`.

**Legal pages:**
- `templates/legal/base_legal.html` has its own inline CSS and does not use marketing.css. Header: brand `href="/"` (L55) and `/support/` (L56). Footer L68: Terms · Privacy · Support.
- `terms.html` L8 links Privacy. `support.html` L28 links Privacy.

**Sign-up today:**
- `templates/account/signup.html` L33-38: "By signing up, you agree to our" plus the `LEGAL_TERMS_URL` and `LEGAL_PRIVACY_URL` links.
- `templates/account/accept_terms.html` L38 and L40 link both.
- **`templates/account/signup_closed.html` (the page an invite-only stranger actually gets) has no Terms or Privacy link.** Its only "Request early access" is `mailto:SUPPORT_EMAIL` (L16), shown only when `SUPPORT_EMAIL` is set.

### 4. Settings, context and middleware

- Base settings (`config/settings/base.py`):
  - L43 `SITE_NAME`
  - L50-51 `LEGAL_TERMS_URL` / `LEGAL_PRIVACY_URL` (defaults `/terms/` and `/privacy/`)
  - L55 `SOURCE_URL`
  - L331 `SIGNUP_MODE` (default `invite_only`)
  - L337 `LAUNCHED_PLATFORMS`
  - L780 `RATELIMIT_ENABLE = not DEBUG`
- Test and e2e settings both force `SIGNUP_MODE="open"` (`config/settings/test.py:10`, `config/settings/e2e.py:56,167`).
- `apps/common/context_processors.branding` L15-27 provides `LEGAL_*`, `SOURCE_URL`, `SUPPORT_EMAIL`, `SIGNUP_OPEN` (L25), `LIVE_PLATFORM_NAMES` and `COMING_SOON_PLATFORM_NAMES`.
- `apps/accounts/signup_policy.py` has `signup_is_open` and `may_sign_up`. `apps/accounts/adapters.py:49-58` uses `is_open_for_signup` and `clean_email`, with `NOT_INVITED_MESSAGE` at L13.
- `apps/accounts/middleware.py`:
  - `EXEMPT_PATH_PREFIXES` L27-46 lets a signed-in user who has not accepted the terms through `/terms/`, `/privacy/`, **`/pricing/`** and `/support/`. Other marketing paths are not exempt.
  - `AUTH_RATE_LIMITED_PATHS` L14-20 covers only login, signup, reset and admin login.
- `apps/members/middleware.py:51-59`: a portal session on `/` is redirected to `client_portal:dashboard`. Its public paths cover terms, privacy and support only, so any other marketing path raises 403 for a portal session.
- Rate limiting: `django_ratelimit` with key `apps/common/net.py:147 ratelimit_client_ip` (example: `apps/common/webhooks.py:81`).
- **No signup or invite path calls `notify(...)` today.** The pieces a Request invite would use:
  - `apps/notifications/engine.py:158 notify(user, event_type, title, body, data)`
  - `EventType` at `apps/notifications/models.py:7-29` (no invite-request type; latest migration is `0008_agency_alert_event_types.py`)
  - `DEFAULT_CHANNELS` at `engine.py:124-145`
  - "Owner" as an instance superuser: the patterns at `apps/common/views_mail.py:20` (`superuser_required`) and `apps/workspaces/management/commands/setup_brands.py:72`

### 5. Tests that assert on these pages or links

pytest:
- `apps/marketing/tests.py` (collected via `python_files=["tests.py",…]`):
  - `PUBLIC_PAGES` L14-21 lists all 6 marketing names.
  - L28-38: each page renders `marketing/base.html` and contains the signup and login URLs.
  - L41-44: **POST gives 405 on every page.**
  - L47-50: `reverse("marketing:home") == reverse("dashboard") == "/"`.
  - L53-63: a signed-in owner gets a 302 to `studio:index`.
  - L66-72: the platform matrix lists every connector.
  - L75-84: canonical URL on `marketing:features`.
  - L87-93: footer "Source code" uses `SOURCE_URL` on home and get_started (AGPL §13).
- `apps/common/tests/test_pricing.py` L6-38: `/pricing/` returns 200 with plan copy, signup href and `mailto`. `/` contains `href="/pricing/"`. Pricing has nav links "How it works", "Platforms", "Developers", "Get started" and the footer text "Supported platforms".
- `apps/accounts/tests/test_signup_policy.py`:
  - L23-27: "invite-only" page.
  - L105-111: invite_only CTAs on `/` and `reverse("pricing")` say "Request early access" (`assertContains` expects 200).
  - L116-120: open mode shows "Create your account".
  - L126-136: claims banned on `/` and pricing.
- `apps/accounts/tests/test_landing.py` L8-13 (`mk-hero`, signup and login hrefs on `/`) and L17-22.
- `apps/common/tests/test_seo.py` L43-52: the **sitemap must contain `/`, `/pricing/` and `/terms/`.** Robots and favicon are at L29-58.
- `apps/common/tests/test_legal.py` L6-23 and `test_legal_pages.py` L8-37: terms, privacy and support are public; draft notice; support platform lists.
- `apps/accounts/tests/test_google_signin.py:167-173`: invite-only social signup shows "invite-only".
- `apps/common/tests/test_marketing_screenshots.py` with `tools/recolor.py:695-726`: no orange in `static/img/marketing/*`.
- Sweeps that include every template:
  - `apps/studio/tests/test_naming.py:40-43` bans "AI Studio".
  - `apps/common/tests/test_template_comments.py`.
  - `apps/common/tests/test_branding_templates.py:111-125`.
- Root `/` for signed-in users goes through `marketing.views.home`:
  - `apps/accounts/tests/test_guided_landing.py` L13-36, L39-54, L57-79
  - `tests/test_media_routing.py:262-278` (terms redirect on `/`)
  - `tests/test_e2e_server.py:670`, `:846`
  - `tests/test_e2e_steps_sign_in_isolation.py:259`
  - `apps/client_portal/test_security_boundaries.py:94-99`

Playwright: there are no anonymous visits to any marketing page. Signed-in `goto('/')` happens in:
- `tests/e2e/golden/03-ask-the-team.spec.ts:254` (a client lands on Calendar; Home answers 403)
- `11-isolation.spec.ts:329`
- `09-inbox.spec.ts:217` (client landing plus axe)
- `01-sign-in.spec.ts` goes through `/accounts/accept-terms/` (testids `accept-terms-agree` and `accept-terms-continue`).

Lighthouse: `.lighthouserc.json` measures only `/workspace/…/studio/`, the Approvals tab and the Calendar. **No marketing URL.** `tests/lighthouse/budgets.mjs:18` only requires the base URL path to be `/`.

**Tests that enforce a CLAUDE.md invariant (never edit):**
- `apps/client_portal/test_security_boundaries.py:94-99` (inv. 3)
- `apps/accounts/tests/test_guided_landing.py:13-36` (inv. 3: client and viewer land on Calendar, `studio:workflow` answers 403)
- `tests/e2e/golden/03-ask-the-team.spec.ts:248-262` (inv. 3)
- `tests/e2e/golden/11-isolation.spec.ts` (inv. 2)
- `tests/e2e/golden/09-inbox.spec.ts:210-224` (inv. 3)
- `tests/test_e2e_steps_sign_in_isolation.py:250-262` (inv. 2)

These all rely on `/` keeping two behaviours: `marketing:home` handing signed-in users to `dashboard`, and the members middleware portal redirect. None of the marketing-only tests enforce an invariant.

### Risks and decisions for Phase 2

1. **Keep `marketing:home` at `/`, GET-only, still handing signed-in users to `dashboard`.** Changing either breaks the invariant tests above and every `redirect("dashboard")`. If the Request invite form sits on Home, it must POST to its own URL so `test_public_pages_are_read_only` stays true for `/`.
2. **Request invite needs a new route and decisions on:**
   - Name, for example `marketing:request_invite` at `/request-invite/`.
   - A POST view behind `@ratelimit(key=ratelimit_client_ip)`; nothing in the auth middleware covers it.
   - A CSRF token, plus a honeypot or a cap, because `notify` sends email.
   - Who "the owner" is (active superusers? none exist → fall back to `SUPPORT_EMAIL`?).
   - A new `EventType` value. This is a choices-only `AlterField` migration on both `Notification.event_type` and `NotificationPreference.event_type`, so no `db_default` is needed.
   - A `DEFAULT_CHANNELS` entry. **Without it, `_resolve_channels` returns no channels and the row is saved with `shown_in_app=False`, so it never shows in the bell.**
   - Hiding the new type from the preferences lists (`apps/notifications/views.py:73,153,233`).
   - `test_digest_mode.py:389` (`off == set(EventType.values)`) keeps passing automatically.
   - The requester's text is untrusted. It must stay out of any prompt (invariant 5) and out of Telegram (`notification_event` already returns 0 for unknown types).
   - A new template under `templates/marketing/` falls in recolor's `LITERAL_DIRS`. It must use `mk-*` classes, not `ui-*` or Tailwind, which are not loaded there.
3. **Pricing redirect:**
   - Turn `config/urls.py:138` into a `RedirectView(permanent=True)` to Request invite, or redirect inside `views.pricing`, keeping the `pricing` name so `{% url 'pricing' %}` does not raise NoReverseMatch.
   - Tests that break and need updating: `test_pricing.py` (all 5), `test_signup_policy.py:109-111` (`assertContains` expects 200) and `:127` (would pass with an empty body), and `test_seo.py:48` (sitemap lists `/pricing/`).
   - Also update `sitemap_xml` L52, `home.html:248` and `base.html:43`.
   - The `/pricing/` entry in `EXEMPT_PATH_PREFIXES` can stay; the new path probably needs adding there.
   - `templates/pricing.html` becomes unused but stays (no deletion).
4. **"Hidden" for Developers and Platforms:**
   - Recommend they keep rendering 200 with every link removed (header L40-41, footer L76-77 and L86, `home.html` L48/L55/L282, `features.html` L11/L229, `get_started.html` L153), rather than a 301.
   - Reason: the Settings → Advanced *Developers* link (resolution 3) can point at `marketing:developers`.
   - `test_platform_matrix_lists_every_connector` stays valid.
   - Decide `noindex` or a robots `Disallow` for them.
   - Removing `#dev` from Home also removes the "Claude" mention at L281 (invariant 9 spirit).
5. **Features and Get started are not named in the cut:**
   - Decide hide (200, unlinked) or 301 (Features to `how_it_works`, Get started to Request invite).
   - If either is 301'd, these break: `PUBLIC_PAGES` L14-21 and L28-44, `test_pages_carry_canonical…` (uses features), `test_source_code_links…` (uses get_started), and `test_pricing.py:33-36` (nav text).
6. **CTA target:**
   - When `SIGNUP_OPEN` is false, CTAs could point at Request invite instead of `account_signup` (base L46/L51/L83, home L15/L307, how_it_works L138, plus the hidden pages).
   - Tests to adjust: `marketing/tests.py:37-38`, `test_landing.py:12`, `test_signup_policy.py:105-111` (copy "Request early access").
   - `signup_closed.html` should link to the form rather than, or as well as, the `mailto`.
7. **Privacy and Terms:**
   - The footer Legal column (base L92-95), the `support` link and `source_url` "Source code" must survive; AGPL §13 is tested at `marketing/tests.py:87-93`.
   - `signup.html:33-38` already satisfies "at sign-up".
   - Add a Privacy link to the Request invite form, which collects personal data, and consider `signup_closed.html`.
8. **Stale copy to update:**
   - `README.md:376` lists all six public paths.
   - `apps/marketing/tests.py` docstring.
   - `PRODUCT_MAP.md` has no marketing URLs, so its "no 404 for any URL listed" gate is unaffected. Nothing in the app shell links to any `marketing:*` page.
9. **No e2e or Lighthouse coverage of anonymous marketing pages.** Phase 2 changes here are pytest-only. Adding an axe-checked spec for the three pages, with `data-testid` hooks, is optional.

---

# AREA productmap

# Phase 2 engineering map: URL inventory and gate tests

Everything here was read from the source files; nothing was run, as the rules required. Line numbers are for branch `claude/trusting-dijkstra-m7nul1`.

## 1. Every URL in `docs/PRODUCT_MAP.md`, and whether it resolves today

**Mount points in `config/urls.py`.** These are the prefixes every path below sits under (by line):
- **Workspace pages under `workspace/<uuid:workspace_id>/`:**
  - `composer` (:72), `calendar/` (:73), `inbox/` (:74), `analytics/` (:75)
  - `approvals` (:109), `settings/clients/` (:111), `media/` (:113), `blog/` (:115)
  - `studio/` (:124), `agency/telegram/` (:125)
- **Pages outside any workspace:**
  - `workspaces/` (:68), `members/` (:69), `social-accounts/` (:70)
  - `webhooks/telegram/` (:78), `portal/` (:127), `notifications/` (:128)
  - `""` goes to marketing (:152), then `accounts.urls_root` (:153)

**Shorthand.** `W` = `/workspace/<ws>`. "Yes" = the name reverses and the path resolves to that view.

| Line in the map | Token | Section | Path today | Pattern; view | Methods / guard | Resolves? |
|---|---|---|---|---|---|---|
| 6 | `/workspace/<workspace id>/` | preamble | placeholder | — | — | n/a (template) |
| 6 | `app:name` | preamble | placeholder | — | — | not a URL |
| 46 | `/` | Signing in | `/` | `marketing/urls.py:8`; `marketing.views.home:196` hands signed-in people to `accounts.views.home:59` | GET → 302 to landing | Yes (the `dashboard` name also reverses to `/`, `accounts/urls_root.py:8`) |
| 55 | `studio:index`, `/studio/` | Home | `W/studio/` | `studio/urls.py:20`; `views.index:235` | GET | Yes |
| 72, 353 | `studio:create` | Home | `W/studio/new/` | `urls.py:21`; `views.create` (views.py:240-244) | POST only, `create_posts`, ratelimit | Yes (GET → 405) |
| 83 | `studio:setup`, `/studio/setup/` | Set up | `W/studio/setup/` | `urls_setup.py:7`; `views_setup.setup:489` | GET | Yes |
| 103 | `studio:routines`, `/studio/routines/` | Routines | `W/studio/routines/` | `urls_routines.py:8`; `views_routines.routines_page:73` | GET, `create_posts` | Yes |
| 123 | `studio:team`, `/studio/team/` | Team | `W/studio/team/` | `urls_agency.py:8`; `views_agency.team_roster:26` | GET | Yes |
| 123 | `studio:job` | Team | `W/studio/jobs/<job_id>/` | `urls_agency.py:10`; `job_detail:74` | GET | Yes (needs an `AgencyJob`) |
| 146 | `studio:team_board` | Team | `W/studio/team/board/` | `urls_agency.py:9`; `views_live.team_board:50` | GET partial | Yes |
| 151 | `studio:settings_hub`, `/studio/settings/` | Settings hub | `W/studio/settings/` | `urls_setup.py:10`; `settings_hub:508` | GET | Yes |
| 157 | `studio:brand` | Settings hub | `W/studio/brand/` | `urls.py:22`; `brand_profile:624` | GET/POST | Yes |
| 160 | `studio:trust` | Settings hub | `W/studio/verified-facts/` | `urls_trust.py:5`; `verified_facts:19` | — | Yes |
| 164 | `studio:memory` | Settings hub | `W/studio/memory/` | `urls_memory.py:8`; `memory:135` | — | Yes |
| 169 | `studio:outcomes` | Settings hub | `W/studio/outcomes/` | `urls_outcomes.py:5`; `outcome_page:26` | — | Yes |
| 172 | `studio:autopilot` | Settings hub | `W/studio/autopilot/` | `urls_autopilot.py:8`; `settings_page:144` | — | Yes |
| 179, 306 | `telegram:settings`, `/agency/telegram/` | Telegram | `W/agency/telegram/` | `telegram/urls.py:7`; `views.settings_page:158` | GET | Yes |
| 182 | `studio:detail`, `/studio/<brief id>/` | A post | `W/studio/<brief_id>/` | `urls.py:25`; `views.detail:448` | GET | Yes (needs a brief) |
| 202 | `studio:thread`, `/studio/thread/` | Team thread | `W/studio/thread/` | `urls_chat.py:8`; `thread_page:96` | GET | Yes |
| 213 | `calendar:calendar?mode=list&tab=approvals` | Approvals | `W/calendar/?mode=list&tab=approvals` | `calendar/urls.py:9`; `calendar_view:686` (`tab` read at :695) | GET, `gzip_page` | Yes |
| 233 | `calendar:calendar`, `/calendar/` | Calendar | `W/calendar/` | same | GET | Yes |
| 238 | `calendar:queue_list` | Calendar → More | `W/calendar/queues/` | `calendar/urls.py:22`; `queue_list:1623` | — | Yes |
| 239 | `calendar:posting_slots` | Calendar → More | `W/calendar/posting-slots/` | `:15`; `posting_slots:1426` | — | Yes |
| 244 | `inbox:feed`, `/inbox/` | Inbox | `W/inbox/` | `inbox/urls.py:11`; `inbox_feed:106` | `use_inbox` | Yes |
| 257 | `blog:list`, `/blog/` | Blog | `W/blog/` | `blog/urls.py:8`; `post_list:224` | — | Yes |
| 262 | `blog:write` | Blog | `W/blog/write/` | `urls_team.py:41`; `views_team.write:136` | GET/POST, `create_posts` | Yes |
| 274 | `analytics:index`, `/analytics/` | Analytics | `W/analytics/` | `analytics/urls.py:10`; `analytics_index:109` | — | Yes |
| 283 | `notifications:list`, `/notifications/` | Notifications | `/notifications/` | `notifications/urls.py:9`; `notification_list:44` | — | Yes |
| 292 | `composer:create_landing` | More | `W/create/` | `composer/urls.py:9`; `create_landing:3043` | — | Yes |
| 292 | `composer:drafts_list` | More | `W/drafts/` | `composer/urls.py:58`; `drafts_list:2680` | — | Yes |
| 294 | `media_library:index` | More | `W/media/` | `media_library/urls.py:8`; `library_index:123` | — | Yes |
| 300 | `workspaces:settings` | Workspace settings | `/workspaces/<ws>/settings/` (plural, not under `W`) | `workspaces/urls.py:10`; `workspace_settings:56` | — | Yes |
| 300 | `workspaces:approvals_settings` | Workspace settings | `/workspaces/<ws>/settings/approvals/` | `:11`; `approvals_settings:176` | GET/POST | Yes |
| 325 | `/webhooks/telegram/<connection id>/` | Telegram | same | `urls_webhooks.py:6`; `webhooks.ingress:134` | POST only, `csrf_exempt` | Yes (GET → 405) |
| 327 | `/portal/…` | Client portal | `/portal/` and below | `client_portal/urls.py` | `portal_auth_required` | Yes |
| 329 | `client_portal:magic_link_entry` | Client portal | `/portal/<token>/` | `client_portal/urls.py:30`; `views.magic_link_entry:45` | GET/POST | Yes (needs a real token) |
| 333 | `client_portal:team` | Client portal | `/portal/team/` | `:23`; `views_team.portal_team:117` | portal session | Yes |
| 345 | `studio:workflow` | Older entry points | `W/studio/workflow/` | `urls_customer_workflow.py:6`; `workflow` (views_customer_workflow.py:24) | GET → 302 to Home | Yes |
| 346 | `studio:workflow_create` | Older entry points | `W/studio/workflow/create/` | `:7`; line 33 | POST only | Yes |
| 346 | `workflow_resume` (no namespace) | Older entry points | `W/studio/workflow/<conversation_id>/resume/` | `:9`; line 55 | POST only | Yes |
| 346 | `workflow_status` (no namespace) | Older entry points | `W/studio/workflow/status/` | `:8`; line 70 | GET | Yes |
| 427, 448 | `/routines`, `/mute` | Telegram commands | — | — | — | **not URLs**; exclude |

**Pages the map names only in prose (no backticked name).** A gate has to list these by hand:

| Prose in the map | URL name | Path | Where it is defined |
|---|---|---|---|
| Templates, Categories, Import CSV | `composer:template_list`, `composer:category_list`, `composer:csv_upload` | `W/templates/`, `W/categories/`, `W/import/csv/` | `composer/urls.py:69,64,75` |
| Clients | `client_portal_admin:client_list` | `W/settings/clients/` | `urls_admin.py:8`; `views_admin.client_list:26` |
| Social accounts | `social_accounts:list` | `/social-accounts/<ws>/` | `social_accounts/urls.py:9` |
| Members | `members:list` | `/members/` | `members/urls.py:8` |
| Notification preferences | `notifications:preferences` | `/notifications/preferences/` | `notifications/urls.py:14` |
| Portal Approvals, Published, Activity, Reports, Telegram | `client_portal:{dashboard, approval_queue, published, activity, reports, telegram}` | under `/portal/` | `client_portal/urls.py:9-19` |
| Drafts from Home (`views_chat.inbox_draft`, `thread_stop_brief`) | `studio:inbox_draft`, `studio:thread_stop_brief` | — | POST only |

**Result: every name and path in the map resolves today.**

The three target routes do not exist yet. Today `W/approvals/` and `W/settings/` match no pattern; `W/studio/activity/` does not match either, because `<uuid:brief_id>/` only accepts a UUID. None of the three collides with an existing pattern.

**Links already sent in Telegram cards and emails.** These come from `reverse()` in app code (excluding tests):
- `studio:routines`, `studio:index`, `studio:thread` (with `?c=`), `studio:job`, `studio:detail`, `studio:autopilot`
- `calendar:calendar` with `?mode=list&tab=approvals`:
  - `apps/telegram/inbox.py:137`
  - `apps/approvals/tasks.py:253`
  - `apps/onboarding/checklist.py:79`
  - `apps/studio/live.py:1180`
- `blog:detail`, `inbox:feed`, `inbox:message_detail`, `client_portal:team` (with `?c=`), `client_portal:approval_queue`
- `notifications:unsubscribe`

Links already sent can never be updated, so every one of these paths must keep answering.

## 2. Existing tests that crawl or resolve URLs

- **`tests/e2e/server/steps/g1.py`.** `_routes()` (:275) walks `get_resolver()`. Two probes build on it:
  - `isolation_urls` (:384) returns every pattern that takes `workspace_id`.
  - `isolation_other_urls` (:410) returns every other pattern that takes a URL part.
  - Each comes back filled with B's rows, with its methods read through the decorators (`_methods`).
- **`tests/test_e2e_steps_sign_in_isolation.py` (pytest of those probes).**
  - Counts must match the resolver, with at least 200 workspace patterns (:79).
  - Exact sampled parts (:101-105): `["studio:brand_sample:template", "telegram:deactivate_chat:chat_id", "telegram:disconnect_channel:channel_id"]`.
  - Exact paths expected for 14 portal, organisation and notification names (:137-152).
- **`tests/e2e/golden/11-isolation.spec.ts`.** Sweeps every workspace-B URL with every method its view accepts (403/404 required).
  - Then sweeps A's URLs carrying B's rows: the owner must get 404 unless the URL is in `notFoundAnswers` (:160-186).
  - `SAMPLE_PARTS` (:49), `OTHER_UNSWEPT` (:62) and `OTHER_UNSWEPT_PREFIXES` (:79) are exact lists.
  - Minimums: at least 200 URLs, at least 150 POSTs, at least 120 object URLs.
- **`tests/e2e/golden/11-isolation-inputs.spec.ts`.** Foreign IDs in form bodies and query strings.
- **`apps/common/management/commands/live_verify.py`.**
  - `isolation.workspace` (:636-646): `composer:compose` and `calendar:calendar` must answer 403/404 to an outsider.
  - `dashboard.calendar` and `dashboard.composer` (:779-785) must answer **200** to an approver, without following redirects.
  - `approvals:approve` (:686) and `blog:preview` (:823).
  - The release runs `live_verify` (`test_delivery_worker_health.py:320-351`).
- **pytest page sweeps that require 200 without following redirects:**
  - `apps/common/tests/test_a11y_sweep.py:162-182`: calendar, compose, create_landing, category_list, inbox feed, saved_replies, media, `members:list`, `studio:index`, `studio:team`, `studio:brand`.
  - `test_review_a11y.py:156-170`: drafts_list, queue_list, posting_slots, template_list, category_list, csv_upload.
  - `test_page_script_budgets.py:41-55`: includes `calendar:calendar?mode=list&tab=approvals`.
  - `apps/calendar/test_response_compression.py:29`: the same approvals query.
- **Sidebar and link assertions:**
  - `test_navigation_and_guards.py`:
    - :51-61 Bluesky and Mastodon are offered in the sidebar.
    - :63-76 the calendar page links the six "More" pages.
    - :142-145 GET `/settings/` (top level) must be **404**.
  - `test_shell_a11y.py:109-125`: More labels Ideas / Posting schedule / Import from CSV, and `ui-page-title` on each page.
  - `apps/studio/tests/test_setup.py`:
    - :281-288 settings hub cards
    - :291-300 agency tabs Home·Routines·Team·Settings
    - :394-414 sidebar has More with `<details class="sidebar-more">`
    - :417-430 the `?open=advanced` links
- **Other resolve checks:** `tests/test_media_routing.py` (`resolve()` on media), `tests/test_oauth_aliases.py`, and `apps/common/tests/test_seo.py` (the sitemap lists `/pricing/`).

## 3. How the gate "no 404 for any URL in `PRODUCT_MAP.md`" could be written

**Where it goes.** Put it in `tests/` and reuse the e2e seed and the probe helpers:

```python
@pytest.fixture
def seeded(db): from tests.e2e.server import seed; return seed.run()
```

Workspace A is `00000000-…-0a`, and its owner is already a member there. `g1._routes(get_resolver().url_patterns)` and `g1._methods(view)` give each pattern's view and the methods it accepts.

1. **Freeze the list.** Snapshot today's tokens (the table above plus the prose list) as a constant in the test. Phase 2 must rewrite `PRODUCT_MAP.md`, and "no 404 for old URLs" only holds if the old set is tested. Also parse the live doc for new names.
   - Name regex: `` `([a-z_]+:[a-z_]+)(\?[^`]*)?` ``. Keep only namespaces in `get_resolver().namespace_dict`; that drops `app:name`.
   - Path regex: `` `(/[^`\s]*/)` ``. Skip `<…>` placeholders and `…`, and skip `/routines` and `/mute` (no trailing slash).
   - Qualify the bare `workflow_resume` and `workflow_status` as `studio:`.
2. **Fill the URL parts** from `pattern.converters`:
   - `workspace_id` = A
   - `brief_id` = a `StudioBrief` in A
   - `job_id` = `engine.create(ws, "report", …)` with `enqueue` monkeypatched
   - `conversation_id` = a `Conversation` in A
   - `token` = `client_portal.services.generate_magic_link(ws, client_user, owner)` (services.py:22)
   - `connection_id` = any UUID, resolve only
   - `reverse()` must not raise, and `resolve(path).view_name` must equal the name.
3. **Workspace-relative paths.** Try `resolve(path)`. On `Resolver404`, prefix `/workspace/<A>`. Doc line 6 says workspace pages are relative.
4. **GET as owner** with `Client.force_login`, without following redirects. Accept:
   - 200
   - 301/302, then follow the chain and require a final 200 that stays inside A (or `/portal/`)
   - 405 only when `g1._methods` says POST only (`studio:create`, `workflow_create`, `workflow_resume`, `thread_stop_brief`, `inbox_draft`, the telegram ingress)
   - 302 to `/portal/expired/?reason=signed_out` for `client_portal:*` without a portal session, or sign in through the magic link first (`magic_link_entry`, GET then POST) and require 200
   - 403 only from an explicit allowlist (none expected for the owner)
   - **Never 404, never 500.**
5. **Parametrise over feature flags.** Run all flags off and all flags on (`AgencySettings.features`). A hidden page must not 404 with its flag off.
6. **Role variant.** Also GET each URL as a plain client (A's `client` member) and require 403/302, never 200 on agency pages. This mirrors `test_setup.py:110-119` and invariant 3.

## 4. Golden paths: routes and test hooks

There are 12 paths in 14 files; `05-06-role-variants` and `11-isolation-inputs` were added in Phase 1.

| Spec | Routes it navigates or calls (`W` = `/workspace/<ws>`) | Key `data-testid` hooks | Touched by Phase 2? |
|---|---|---|---|
| 01-sign-in | `/accounts/login/`, `/accounts/google/login/` (+callback), `/accounts/accept-terms/`; lands on `W/studio/` (:113-118, :175, :188, :216) | `login-*`, `social-login-google`, `accept-terms-*`, `account-sign-out` | Only if Home moves |
| 02-onboarding (marked invariant in the e2e README, :69) | `W/studio/brand/` (POST → 302 back to the same path, :62-74); `W/studio/setup/` (:80, :127); `/social-accounts/<ws>/connect/` (:84); `/social-accounts/callback/x/` → `W/calendar/` (:119-120); `W/studio/` (:137) | `brand-save`, `setup-row-accounts`, `setup-action-accounts`, `setup-row-approvers`, `setup-action-approvers` (`data-setup-state`), `connect-platform-x`, `home-thread`, `thread-composer-*`, `thread-brief-*` | **Yes:** Set up, Brand |
| 03-ask-the-team | `W/studio/`; POST `W/studio/thread/send/`, `W/studio/<brief>/approve/` (:166-202); portal link → `/portal/` (:226); `/` → `W/calendar/` for a client (:254-255) | `home-today*`, `home-thread`, `thread-brief-*`, `thread-composer-*` | Landing only |
| 04-compose | `W/compose/` (:49, :126); post URL `/compose/<uuid>/` (:30, :88) | `compose-caption`, `compose-media-library`, `compose-media-picker`, `compose-saved-toast`, `compose-submit-for-approval` | **Yes:** New post |
| 05-approve-and-schedule | `W/calendar/?mode=list&tab=approvals` (:101, :179); POST `W/approvals/<post>/approve/` (:64, :189); reload GET `W/calendar/publish/approvals/` (:69); week view `W/calendar/?mode=calendar&view=week&date=` (:148) | `approvals-list`, `approvals-row-<post>`, `approvals-row-approve(-schedule)`, `approvals-row-review`, `calendar-week-grid` | **Yes:** Approvals |
| 05-06-role-variants | Same approvals list (:46, :104); approve POST (:55, :110); week view (:76); `/portal/`, `/portal/approvals/` (:126-129); `/portal/approvals/<post>/ask/` (:139); `W/studio/<brief>/` (:177) | `approvals-*`, `portal-*`, `studio-detail-*`, `studio-revise-form` | **Yes:** Approvals |
| 06-request-changes | `W/calendar/?mode=list&tab=approvals` (:92); `W/studio/<brief>/` (:156-200) | `approvals-row-request-changes`, `-send-back`, `-review-comment`, `studio-detail-*`, `studio-revise-*` | **Yes:** Approvals |
| 07-calendar-drag | `W/calendar/?mode=calendar&view=week&date=` (:168, :227); POST `W/calendar/reschedule/` (:74); GET calendar `view=week` (:79) | `calendar-shell`, `calendar-week-grid`, `calendar-week-cell-<date>-<HHMM>`, `calendar-chip-<pp>` | Only if the week view changes |
| 08-client-portal | Magic link → `/portal/`, `/portal/approvals/` (:100-111); `W/studio/` refused, 403/404 (:143) | `portal-continue`, `portal-nav-approvals`, `portal-approvals-pending`/`-decided`, `portal-card(-approve)` | No |
| 09-inbox | POST `/webhooks/facebook/` (:88); `W/inbox/` (:133, :221); `/` (:217); `W/inbox/<msg>/` and `/reply/` (:226-230) | `inbox-*` | No |
| 10-brand-and-timezone | `W/studio/brand/` GET/POST (:113, :221, :228); sample image src (:75-78); `/organizations/settings/` GET/POST (:169, :236, :239); week view (:85) | `brand-primary-color`, `brand-accent-color`, `brand-save`, `brand-sample-image-<layout>`, `org-settings-timezone(-save)` | **Yes:** Settings → Brand |
| 11-isolation | Every resolver URL (section 2); `studio:index`, `studio:detail`, `approvals:version_diff`, `client_portal:post_thread` (:386-428) | none (uses the probes) | Automatically covers new routes |
| 11-isolation-inputs | `W/studio/` (:24), POST `W/calendar/reschedule/` and `bulk-action/` (:33-54), `W/studio/thread/?c=` (:62) | `home-today` | No |
| 12-two-factor | `test.fixme` (pending until Phase 4) | — | No |

The self specs also navigate: `tests/e2e/self/*.ts` go to `W/studio/` (emoji-picker, phone-menu-focus, session) and `W/calendar/?mode=calendar&view=week` (calendar-keyboard, ui-select).

Lighthouse targets `W/calendar/?mode=list&tab=approvals` (`.lighthouserc.json:6`); `tests/lighthouse/run.mjs:181` expects testid `approvals-list`.

## 5. Tests that enforce the nine invariants (do not edit)

These are function-level tests inside mixed files, so the rule has to be "do not change these assertions".

1. **Nothing approves without a person:**
   - `apps/approvals/test_gate.py`. :394-401 GETs `calendar:calendar?mode=list&tab=approvals` and requires 200. :426-445 POSTs `workspaces:approvals_settings` and requires 302 plus a saved setting.
   - `apps/approvals/test_security.py`, `test_workflow.py`
   - `apps/publisher/test_claim_and_success.py`, `test_delivery_controls.py`
   - `apps/studio/tests/test_engine.py`, `test_services.py`, `test_verified_claims.py`, `test_photo_provenance.py`, `test_blog_job.py`
   - `apps/telegram/tests/test_actions.py`, `test_conversation_controls.py`, `test_weekly.py`, `test_inbox.py`
   - `apps/blog/tests/test_seo_monitor.py`
   - `apps/client_portal/test_security_boundaries.py`
   - `apps/api/tests/test_review_fixes_round2.py`
   - golden 05, 05-06, 06, 07, 08
2. **Workspace isolation:**
   - `tests/test_e2e_steps_sign_in_isolation.py`; golden `11-isolation.spec.ts`, `11-isolation-inputs.spec.ts`; `live_verify` `isolation.workspace`
   - `apps/members/tests/test_authorization_boundaries.py`
   - `apps/calendar/test_security.py`, `apps/media_library/tests/test_security.py`
   - `apps/telegram/tests/test_lifecycle_security.py`, `apps/studio/tests/test_neopolis_launch_security.py`
3. **Clients only in the portal:**
   - `apps/studio/tests/test_setup.py:110-119`: a client gets **403** on setup, settings_hub, setup_lead and setup_autopilot.
   - `apps/client_portal/test_security_boundaries.py`, `apps/studio/tests/test_portal_team.py`, `test_chat.py`, `test_approver_roles.py`
   - `apps/telegram/tests/test_inbox.py:89`
   - golden 03 (:208, :241), 04 (:122), 08 (:143), 09 (:199)
4. **Private Telegram stays private:**
   - `apps/telegram/tests/test_web_privacy.py`, `test_private_history_migration.py`
   - `apps/studio/tests/test_telegram_job_privacy.py`, `test_telegram_private_notifications.py`
5. **Untrusted text only through the wrappers:**
   - `apps/studio/tests/test_chat.py:432,778,800`, `test_inbox_team.py:188`, `test_insights.py:576`
   - `test_blog_job.py`, `test_report.py`, `test_art_direction.py`
6. **Paid actions behind budget, provider and rate limits:**
   - `apps/studio/tests/test_autopilot.py`, `test_routines.py`, `test_chat.py`, `test_pipeline.py`, `test_customer_workflow.py`, `test_openrouter.py`, `test_neopolis_usage_launch.py`
   - `apps/inbox/tests/test_round5_hardening.py`
7. **Tasks never raise:**
   - `apps/common/tests/test_worker_reliability.py`, `test_delivery_worker_health.py`
   - `apps/studio/tests/test_worker_lease_boundaries.py`
   - `apps/social_accounts/tests/test_tasks.py`, `apps/blog/tests/test_publisher.py`
8. **New columns carry `db_default`:**
   - the `makemigrations --check` CI step
   - `apps/telegram/tests/test_private_history_migration.py`
9. **No model identifiers in copy:**
   - `apps/studio/tests/test_setup.py:528-545`. It requires `state["setup_url"] == reverse("studio:setup")` and the copy "open Set up" / "in Set up".
   - `apps/studio/tests/test_chat_provider_readiness.py`

## Risks and decisions for Phase 2

1. **Approvals must keep rendering on the Calendar, with no 301.** Four tests GET `calendar:calendar?mode=list&tab=approvals` without following redirects and require 200:
   - `test_gate.py:394` (an invariant test)
   - `test_page_script_budgets.py:47`
   - `test_response_compression.py:29`
   - Lighthouse
   
   Golden 05 also waits for the HTMX reload of `W/calendar/publish/approvals/` (:69).
   
   **Decision:** the new `W/approvals/` view includes `calendar/partials/publish_approvals.html` with its existing `hx-get` to `calendar:publish_tab_approvals` (target `#tab-content`). The old query keeps rendering. Then update golden 05, 05-06 and 06 to the new path, or leave them as they are.
2. **Approvals links in Telegram and email.** These tests assert the links contain `tab=approvals`:
   - `apps/telegram/tests/test_inbox.py:223`
   - `test_briefing.py:25`
   - `apps/approvals/test_deadline_reminders.py:103`
   
   **Decision:** keep those link targets in Phase 2, or change the code and these three assertions together. The first is in an invariant-3 file.
3. **`studio:setup` must keep resolving and rendering.** It has to keep returning 200 for staff, 403 for clients, and the readiness copy "Set up":
   - `test_setup.py:528-545` (invariant 9)
   - `test_setup.py:110-119` (invariant 3)
   - golden 02, marked invariant; it reads `setup-row-*` and `setup-action-*` and posts `setup_lead`, which redirects back to `studio:setup`
   
   A 301 here breaks invariant tests. The new Settings → Advanced Health page could include `studio/setup.html`'s checklist while `/studio/setup/` keeps rendering.
4. **Any new redirect view must refuse before it redirects.**
   - Call `studio.views._workspace` (views.py:62-74) or `require_permission` first, so a plain client still gets 403, not 301.
   - A redirect that takes an object ID (brief, job, post) must do the workspace-scoped lookup first and answer 404. Otherwise golden 11 fails for the owner: its default rule is 404, and `notFoundAnswers` is an exact, reviewed list.
5. **New routes must not add new URL parts.** A route such as `settings/<str:tab>/` adds `"<name>:tab"` to the sampled list. That breaks the exact lists in `test_e2e_steps_sign_in_isolation.py:101-105` and `11-isolation.spec.ts` `SAMPLE_PARTS`, both invariant-2 tests. Use `?tab=` or one parameterless route per tab.
   
   Also keep Settings at `/workspace/<id>/settings/`. A top-level `/settings/` would break `test_navigation_and_guards.py:142-145`, and a new non-workspace route would need an `OTHER_UNSWEPT` review.
6. **`composer:compose` must keep returning 200.** `live_verify` `dashboard.composer` (:781) requires it without following redirects, and the release runs `live_verify`. `test_a11y_sweep.py:166` also needs it. If New post replaces `/compose/` with a sheet, keep `/compose/` rendering.
7. **Pages hidden by a flag must not 404.** With `queues` or `templates` off, `queue_list`, `template_list`, `category_list` and `tag_list` must still answer (render, or 302/301 to Calendar or Settings). Otherwise the gate fails.
   
   These pytest tests also need 200 and sidebar links for those pages and will need updating as ordinary, non-invariant tests:
   - `test_review_a11y.py:156-170`
   - `test_navigation_and_guards.py:63-76`
   - `test_shell_a11y.py:109-125`
   - `test_setup.py:394-414`
   
   `test_navigation_and_guards.py:51-61` (Bluesky and Mastodon offered in the sidebar) conflicts with the `extra_providers` flag.
8. **Old routes become 301; the contract names keep rendering.**
   - **Keep rendering:** `studio:detail`, `studio:job`, `calendar:calendar`, `client_portal:*`, `telegram:settings` (00-cut :132-134); plus everything above that a non-following test needs (`studio:setup`, `studio:brand`, `studio:team`, `calendar:calendar?tab=approvals`, `composer:compose`, `workspaces:approvals_settings`).
   - **Can 301 after updating ordinary tests:**
     - `studio:settings_hub`: `test_setup.py:281,417`; the client 403 in `test_setup.py:113` means it must refuse first
     - `studio:routines`, `studio:trust`, `studio:memory`, `studio:outcomes`, `studio:autopilot`: `test_setup.py:323,417`; `test_autopilot.py`
     - `composer:create_landing`, `composer:drafts_list`
     - `notifications:list`, `workspaces:settings`, `client_portal_admin:client_list`, `social_accounts:list`
   - **POST targets:** `studio:brand` (golden 10 :94, :228) and `workspaces:approvals_settings` (`test_gate.py:429`) must keep accepting POST. A 301 drops the POST body.
   - **Keep the older workflow endpoints exactly as they are:** `studio:workflow` (302 to Home, `test_setup.py:374`), `workflow_resume` (302 to Home, golden 11 `notFoundAnswers`), `workflow_create`, `workflow_status`.
9. **The gate must snapshot today's URL list.** Phase 2 will rewrite `PRODUCT_MAP.md`, so a gate that only parses the live doc would stop testing the old URLs. Also decide which status codes count as by design: 405 for POST-only, 302 for the portal without a session, 302 for `/`.
10. **Two plan rules conflict.** The plan says the 12 e2e tests are "updated to the new routes" (`BETA_PLAN.md:278`). The e2e README (:58, :69, :148) says the invariant golden paths, including 02, stay unchanged. This needs a written decision:
    - **Option A:** only the non-invariant specs (04, 05, 05-06, 06, 10) get new routes, and the old routes keep serving 02 and 11.
    - **Option B:** the owner explicitly allows edits to the golden files.