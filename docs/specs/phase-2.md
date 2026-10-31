# Phase 2 plan — cut and merge, no restyling

Executes [`02-cut-and-merge.md`](02-cut-and-merge.md) (spec, decisions D1–D10, requirements R1–R10)
on top of [`00-cut.md`](00-cut.md). Skills: `make-plan` → `do`, `test-driven-development` inside each
task, `engineering:code-review` and `requesting-code-review` before the gate,
`verification-before-completion` for the gate.

## Phase 0 — Documentation discovery (done)

Eight read-only readers mapped every area on 31 Oct 2026; the result is
[`phase-2-code-map.md`](phase-2-code-map.md) (sections: nav, approvals, settings, activity, flags, cut,
marketing, productmap). **Every task below starts by reading its section there and the files it
cites**, then confirms each cited line before editing (the map is a snapshot; line numbers drift).

### Allowed APIs and patterns (cited)

- Switches: `apps/common/features.py` — `feature_enabled(workspace, key)`, `FEATURE_KEYS`; tests in
  `apps/common/tests/test_features.py`. Add `features_for(workspace) -> dict[str, bool]` next to it.
- Permissions: `apps.members.decorators.require_permission("<perm>")`, `effective_permissions`,
  `has_org_permission(membership, "manage_api_keys")`; studio's `_workspace(request, workspace_id)`
  (`apps/studio/views.py:62-74`) refuses plain clients with 403. Copy these; never re-implement.
- Rate limiting: `django_ratelimit.decorators.ratelimit`, keyed like existing public views
  (`ratelimit_client_ip`, see map §marketing).
- Notifications: `apps/notifications/models.EventType`, `DEFAULT_CHANNELS`, the `notify` service (map
  §marketing). A new event type is a choices-only migration (no column, no `db_default` needed).
- Alpine: `x-trap` (focus plugin, `static/js/vendor/alpine-focus.min.js`), `x-ref`, `$refs`; HTMX
  attributes as used in `templates/calendar/partials/publish_approvals.html`.
- Context processors are registered in `config/settings/base.py:152-162`
  (`apps.common.context_processors.sidebar_context`).
- E2E: `tests/e2e/support/test.ts` (`test`, `expect`, `as`, `axe`, `harness`), `data-testid` only,
  `settled()` before axe on animated regions; see `tests/e2e/README.md` "Rules for specs".

### Anti-patterns (do not)

- Do not edit `apps/approvals/gate.py`, `apps/approvals/actor.py`, any test that enforces a `CLAUDE.md`
  invariant, or any existing `tests/e2e/golden/*.spec.ts`.
- Do not add URL path parts beyond `workspace_id` (`?tab=`, anchors instead) — the isolation sweep's
  sampled parts are an invariant test.
- Do not redirect in `urls.py` with a bare `RedirectView` for pages that check permissions: redirect
  inside the view, after `@login_required`, the permission and the workspace checks.
- Do not 301 POST endpoints, HTMX fragments, or anything in the URL contract (`studio:detail`,
  `studio:job`, `calendar:calendar`, `client_portal:*`, `telegram:settings`).
- Do not gate a route with 404/302 because a switch is off; switches hide links and creation buttons.
- Do not restyle: reuse existing partials and component classes; no new colours (run
  `tools/recolor.py --check`).

### Routes that must keep rendering 200 (from the map; tests that must not change load them)

`studio:index`, `studio:thread`, `studio:autopilot`, `studio:setup`, `studio:brand` (GET and POST),
`studio:detail`, `studio:job`, `studio:team` (by name — its path moves to `activity/`),
`studio:team_board`, `calendar:calendar` including `?mode=list&tab=approvals`,
`calendar:publish_tab_approvals`, `composer:compose`, `workspaces:approvals_settings` (POST),
`telegram:settings`, `notifications:list`, `notifications:preferences`, `social_accounts:connect`,
`studio:workflow*`, every `approvals:*` action, every `client_portal:*`, and campaign outcomes (its
test reads a token from the GET page). Pages not on this list may 301 on GET per D1 once their
ordinary tests are updated.

## Phase 1 — Foundations (no visible change)

**T1. `features_for` and one read per request.** Files: `apps/common/features.py`,
`apps/common/context_processors.py`, `config/settings/base.py`, `apps/common/tests/test_features.py`.
Red: `features_for(ws)` returns every key in `FEATURE_KEYS`; at most two queries
(`assertNumQueries`); a request reads it once (cache on the request object); no workspace → all
defaults without a query. Then implement; expose `features` to templates from `sidebar_context`.
Also drop the three unused channel queries in `sidebar_context` only if no test reads them (map §nav 3;
`test_navigation_and_guards.py:56` reads `sidebar_connectable_platforms` — update that test in T8).

**T2. Navigation builder.** New `apps/common/navigation.py` with `build_nav(request)` returning
items (`key`, `label`, `url`, `count`, `active`), the settings entry and the phone bar entries. Rules
(spec R1): Home on `studio:index` and `studio:detail`; Activity on `studio:team`, `studio:job`,
`studio:routines`; Settings on `settings:index` and the old settings pages while they still render;
Approvals on `approvals:index` (and `calendar` with `tab=approvals`); Calendar on `calendar:*` except
that; Inbox, Analytics (only with `analytics_enabled_platforms`), Blog (only with the `blog` switch).
Red: `apps/common/tests/test_navigation.py` with `RequestFactory` + `resolve()` for each rule. Not yet
used by `base.html` (T9).

## Phase 2 — The three new screens

**T3. `/approvals/`** (map §approvals). Files: `apps/calendar/views.py` (new `approvals_index`, reusing
the Approvals tab's private helpers so there is one query), `apps/approvals/urls.py`
(`path("approvals/", …, name="index")`), new `templates/approvals/index.html` extending `base.html`
and including `calendar/partials/publish_approvals.html`, hidden `#tabcount-*` targets so the
out-of-band count spans land, and the filter scope from `calendar.html`'s `publishList()` (copy the
function into a shared static file or the new template's `extra_js`; no behaviour change).
Red tests `apps/approvals/tests/test_index.py`: owner sees the same rows as the tab for the same
data; approve-and-schedule from the page posts to the unchanged `approvals:*` endpoint; plain client
403; viewer read-only exactly like the tab; another workspace's member 403/404. Keep
`calendar:calendar?tab=approvals` rendering.

**T4. Activity** (map §activity). Files: `apps/studio/urls.py` (`path("activity/", views_agency.team,
name="team")`; `path("team/", <gated 301>, name="team_legacy")`; `studio:routines` GET becomes a gated
301 to `studio:team` + `#routines`, its POST handlers unchanged), `templates/studio/team.html` (or the
view's template) gains a routines section shown only with `create_posts`, `templates/studio/routines.html`
split into `partials/routine_presets.html` and `partials/routine_form.html` (pure extraction, same
markup), `apps/studio/live.py` routine-event URLs and the `closed` set (`:1150`) if repointed.
Red tests: Activity renders `#team-status`, `#team-board` (`data-live-board`, 5 s poll),
`#team-live-announce` and the presets for an editor; a viewer sees no routine title or
`studio:routines` link (`test_live.py:582` rule); `/studio/team/` and `/studio/routines/` answer 403 to
a client and 302-to-login to anonymous before any 301; the routine create error path still answers
400 with the form. Update only non-invariant tests that GET the old routines page for content
(`test_routines.py`, copy in `test_live.py:547,762,871,895`).

**T5. Settings shell and the first four tabs** (map §settings). Files: new `apps/studio/urls_settings.py`
(`app_name = "settings"`, `path("", views_settings.index, name="index")`) mounted in `config/urls.py`
at `workspace/<uuid:workspace_id>/settings/` **before** the `settings/clients/` include; new
`apps/studio/views_settings.py` (tab registry: key, label, permission check, context builder,
partial); `templates/settings/index.html` (tab strip using the existing tab component classes; only
the active tab built). Tabs here: Brand (`studio:brand` body), Accounts (`social_accounts:list` body;
the connect link goes to the existing connect page), Team & clients (links to `members:list` and the
client-portal admin list with their counts; their modals stay on their own pages — map §settings 9),
Approvals (`workspaces:approvals_settings` body). Extract each body to a partial included by both its
old page and the tab; give every form an explicit `action=` to its old URL; fix trust's relative
`?claim=` link (map §settings 5). Red tests `apps/studio/tests/test_settings_screen.py`: each tab
renders for its permission and is absent (and 403 by URL) otherwise; saving from the tab posts to the
old handler and gives the same result; plain client 403; `no-store` where Telegram or Set up panels
are included.

**T6. The last three tabs and the redirects.** Autopilot (the whole `AgencySettingsForm`, unsplit),
Notifications (links to `notifications:preferences` and `telegram:settings`; the bell is T9), Advanced
(Health = the Set up checklist included from `studio/setup.html`; the free-form routine form from T4;
*Developers* link to the API keys page for `manage_api_keys` only; the danger zone from
`workspaces:settings`; Verified facts, Creative memory and Outcomes only when `advanced_settings` is
on). Then the GET 301s per D1 for the pages not on the keep-rendering list (`studio:settings_hub` →
Brand, `studio:trust`/`studio:memory` → Advanced, `workspaces:settings` → Brand or Advanced,
`social_accounts:list` → Accounts, `client_portal_admin:client_list` → Team & clients), each inside
its view after its checks, carrying `?open=`/`?claim=`. Red tests first for each redirect (status,
`Location`, refusal-before-redirect); update the ordinary tests that read those pages' GET content.

## Phase 3 — Switches, cut items, the new navigation

**T7. Switches applied** (map §flags). Blog: nav item via T2; the autopilot form drops
`blog_posts_per_month` fields in `__init__` when off (stored value kept). Queues: hide Queues links
and the recurring-rule action; keep "Next available" and the posting schedule. Templates: hide
Templates, Categories, Tags and the Ideas page's Templates tab; CSV import moves to the New menu.
Extra providers: filter the connect screen and `onboarding:connection_page` for new connections;
Bluesky/Mastodon/DEV.to forms allow reconnect when the workspace already has that platform; Threads
and TikTok keep reconnect and callback. Advanced settings: per T6. Red tests for each switch off and
on (`apps/*/tests/test_feature_switches_*.py`); update `test_navigation_and_guards.py`,
`test_review_a11y.py`, `test_channelless_drafts.py` and `test_a11y_sweep.py`'s More-link checks to set
the switch, with an off-state counterpart.

**T8. Cut items** (map §cut). Remove the Intelligence link (`base.html:807-813`) and the API keys item
in `layouts/settings.html:35-38`; nothing else changes for Agent API, MCP, OAuth or
`studio:workflow_*`. Red: a test that the sidebar has no Intelligence or API keys link and Settings →
Advanced has *Developers* only for owners/admins.

**T9. The new navigation live** (map §nav). `templates/base.html`: render `build_nav` (six items, the
gear, Blog when on); remove *More* and relocate its entries — Drafts, Posting schedule and Media as
links in the Calendar page header; Ideas and Import from CSV in the New menu; Queues, Templates and
Categories only with their switches (in the Calendar header and New menu respectively); Notifications
becomes a bell (sidebar header, phone top bar) opening the existing `notifications:drawer` partial,
keeping `data-testid="notification-badge"` and `notificationBadge(N)`; the account footer's
"Settings" becomes "Account"; the phone bottom bar (Home, Approvals with count, Calendar, Inbox, More
→ opens the drawer) with `main` bottom padding, hidden where the post page shows its phone Approve bar;
the command palette stub (R2) as an `x-trap`ped, labelled dialog. Keep every `data-testid` the golden
specs use (`sidebar-new-toggle`, `sidebar-new-idea`, `mobile-menu-toggle`, …) and the drawer's
inert/dialog/trap behaviour (`test_shell_a11y`). Red tests: `apps/common/tests/test_navigation_render.py`
(item order and labels per role and switch; More absent; bell present); update `test_setup.py:394`,
`test_shell_a11y.py` More-label tests and `test_channelless_drafts.py:185`.

## Phase 4 — Marketing

**T10. Three pages and Request invite** (map §marketing). `apps/marketing/urls.py` +
`views.py`: `request_invite` (GET form, POST with CSRF, honeypot, `@ratelimit` by IP, creates one
`invite_requested` Notification per active staff user, else mails `SUPPORT_EMAIL`; the requester's
text never reaches a prompt or Telegram); `templates/marketing/request_invite.html` using `mk-*`
classes; `apps/notifications/models.EventType.INVITE_REQUESTED` + `DEFAULT_CHANNELS` (in-app and
email) + migration; hidden from preference lists; `/pricing/` → 301 to Request invite inside
`views.pricing` (keep the `pricing` name); header/footer links reduced to Home, How it works, Request
invite, Sign in, Privacy, Terms (+ Source code, AGPL); Developers, Platforms, Features and Get started
keep rendering with `noindex`, unlinked; sitemap lists the three pages; CTAs point at Request invite
when sign-up is closed. Red tests: `apps/marketing/tests/test_request_invite.py` (creates once; bot
field refused; rate limit; no prompt or Telegram path), updated `test_pricing.py`, `test_seo.py`,
`test_signup_policy.py`.

## Phase 5 — Gate

**T11. The URL gate.** `tests/test_product_map_urls.py` with a frozen list in
`tests/fixtures/product_map_urls.txt` extracted from `PRODUCT_MAP.md` **before** T13 rewrites it (map
§productmap table). Owner session; accept 200, 301/302 whose target answers 200, 403 or 405 by design
(documented per URL); fail on 404/500.

**T12. E2E for the new routes.** New `tests/e2e/screens/` specs on all three devices, `data-testid`
only, axe on every screen: navigation (each item and the gear reaches its screen; More absent on
desktop; phone bar), approvals (approve & schedule from `/approvals/`, fingerprint shown, same gate),
settings (brand colour saved from the Brand tab; tabs a staff member may not use are absent), activity
(board and presets; viewer sees none), switches (Blog item appears when on), marketing (three pages
and Request invite, anonymous). Point `.lighthouserc.json`'s Approvals URL at `/approvals/`; budgets
unchanged. Existing golden specs stay unedited and green.

**T13. Docs.** `docs/PRODUCT_MAP.md` (new screens, routes, redirects), `CLAUDE.md` module map and
naming, `docs/DESIGN_SYSTEM.md` navigation section, `tests/e2e/README.md`, `README.md` public paths.

**T14. Review and gate.** `engineering:code-review` and `requesting-code-review` on the whole diff;
fix findings. Then run exactly: full `pytest` (with coverage ≥ main), `ruff check` and
`ruff format --check`, `mypy`, `makemigrations --check --dry-run`, `tools/recolor.py --check`,
`compilemessages`, `npm run test:ui`, the full Playwright suite (golden + screens) on three devices,
Lighthouse; CI green on all nine jobs. Record in `docs/specs/CHANGELOG.md` with section 6 quoted.

## Verification checklist (each task)

- [ ] The red test was observed failing for the stated reason before the change.
- [ ] `git diff` touches no invariant test and no existing golden spec.
- [ ] `grep -rn "RedirectView" apps config` shows no new bare redirect for a permission-checked page.
- [ ] The touched app's pytest passes; `ruff`, `mypy` clean; `recolor.py --check` clean.
- [ ] Any new route answers 403/404 for workspace B (the isolation sweep picks it up automatically).

## Order and parallelism

T1 → T2 → (T3 ∥ T4 ∥ T10) → T5 → T6 → T7 → T8 → T9 → T11 → T12 → T13 → T14. T3, T4 and T10 touch
disjoint apps and can run in separate worktrees; everything that edits `templates/base.html` (T9) or
`apps/studio/urls.py` (T4, T5) runs alone.
