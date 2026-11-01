# 02 — Cut and merge, no restyling

Phase 2 of [`docs/BETA_PLAN.md`](../BETA_PLAN.md). Written 31 Oct 2026 from the owner-confirmed cut in
[`00-cut.md`](00-cut.md) and a read-only map of the code it touches. Gate (section 6): **full pytest
suite green (the invariants' tests untouched); 12 e2e tests updated to the new routes and green; no
404 for any URL listed in `PRODUCT_MAP.md`.**

## Problem

The beta shows thirty screens where ten agencies need nine. Today the sidebar has 8 items plus 8 under
*More*, there are three ways to start a post, three settings surfaces and four ways into approvals.
Phase 3 restyles screens one by one; before it can, the navigation has to point at the nine screens
it will restyle. Phase 2 makes that cut without changing how any page looks or behaves.

## Goals

1. **Six items and a gear.** The desktop sidebar shows Home, Approvals, Calendar, Inbox, Analytics and
   Activity, then Settings (the gear) at the bottom; Blog is a seventh item only when the workspace's
   `blog` switch is on. *More* is gone. The phone has a bottom bar: Home, Approvals, Calendar, Inbox,
   More (More opens the existing drawer).
2. **One place each.** `/workspace/<id>/approvals/`, `/workspace/<id>/settings/` (tabs) and
   `/workspace/<id>/studio/activity/` exist and render the existing partials.
3. **Nothing breaks.** Every URL in `PRODUCT_MAP.md` (as of the start of Phase 2) answers without a 404
   or a 500. Every old link in Telegram cards, emails and bookmarks keeps working.
4. **Hidden, not deleted.** Blog, Queues, Templates, extra providers and the advanced settings follow
   the per-workspace switches from Phase 0; their code and URLs stay.
5. **The nine invariants hold**, enforced by the same, unedited tests.

## Non-goals

- **No restyling.** New screens reuse existing partials and component classes. The New post sheet,
  the Approvals swipe stack and the onboarding wizard are Phase 3.
- **No deletion** of views, URLs, templates or models.
- **No change** to the approval gate, fingerprints, publishing, isolation, budgets, Telegram buttons
  or the untrusted-text wrappers (`apps/approvals/gate.py` and `actor.py` are not touched).
- **No change to background work.** A switch hides navigation and creation entry points only;
  anything already scheduled, queued or planned keeps running.
- **No edits to the existing golden e2e specs or to any test that enforces a `CLAUDE.md` invariant.**

## Who it is for

| Person | What changes for them |
|---|---|
| Manager / approver | Six items; Approvals is one screen; on a phone, a bottom bar with the approvals count |
| Agency owner | One Settings screen with seven tabs; power features under Advanced |
| Plain client | Nothing: the portal stays as it is; new agency screens refuse them like today's studio pages |
| Beta operator | Switches decide per workspace what shows; the marketing site asks for an invite |

## Decisions

These resolve the open questions in `00-cut.md` and the conflicts the code map found.

**D1. Which old routes redirect.** A route keeps **rendering** when it is in the URL contract
(`studio:detail`, `studio:job`, `calendar:calendar`, `client_portal:*`, `telegram:settings`), when a
test that must not be edited loads it without following redirects, or when it is a POST target or an
HTMX fragment. Every other old *page* answers a **301 on GET** to its new home. The redirect happens
inside the existing view, after its login, permission and workspace checks, so a person who was
refused before is still refused (403/404), never redirected. Query strings that select something
(`?open=`, `?claim=`) are carried over.

**D2. No new URL parts.** The new routes take only `workspace_id`; tabs and sections use `?tab=` and
anchors. (The isolation sweep's list of sampled URL parts is an invariant test.)

**D3. Approvals.** `approvals:index` at `/workspace/<id>/approvals/` renders the Calendar list's
approvals partial with the same query, the same HTMX endpoints and the same filters. The sidebar, the
phone badge and Home's "waiting" link point to it. The old `calendar?mode=list&tab=approvals` keeps
rendering (URL contract, invariant test), and Calendar keeps its Approvals tab until Phase 3 rebuilds
Calendar. Plain clients get 403, like the other agency screens. Links already sent in Telegram and
email are left as they are.

**D4. Activity.** The URL name `studio:team` moves to `/studio/activity/`: the Team page becomes
Activity (roster, the live board, recent jobs) plus the routines list with the three presets for
people who may create posts. `/studio/team/` answers a gated 301. `studio:routines` answers a gated
301 to Activity's routines section; the free-form routine form moves to Settings → Advanced. Job
pages and the board's polling URLs do not move.

**D5. Settings.** One view at `/workspace/<id>/settings/?tab=` with tabs Brand · Accounts · Team &
clients · Approvals · Autopilot · Notifications · Advanced. Only the active tab is built. Each tab
applies its page's own permission check and is not shown to someone it would refuse. Panels include
the existing page bodies; their forms post to the same handlers as today (explicit `action=`), so
saving behaves exactly as before. Advanced holds the owner's Health checklist (today's Set up),
the free-form routine form, a *Developers* link (organisation owners and admins only) and the danger
zone; Verified facts, Creative memory and Outcomes appear there when `advanced_settings` is on.
Organisation- and person-level pages (members, notification preferences, Telegram pairing, API keys)
keep their own pages and are linked from their tab. `studio:setup` keeps rendering and keeps its
"Set up" wording (an invariant test pins the readiness copy).

**D6. Switches hide navigation and creation only.** `features_for(workspace)` reads every switch in
one query (plus the blog check) once per request. With a switch off: its sidebar or menu entry is
gone and creation entry points are hidden; its pages still answer (never 404) and existing data keeps
working. Specifics: *blog* off removes the Blog item and the autopilot form's blog fields (stored values
kept); *queues* off hides Queues and recurring rules (the posting schedule and "Next available" stay,
because the scheduler needs them); *templates* off hides Templates, Categories and Tags (CSV import
stays, from the New menu); *extra_providers* off removes Bluesky, Mastodon, DEV.to, Threads and
TikTok from the connect screen and the client connection page for new connections only (reconnect and
callbacks stay open); *advanced_settings* off hides Verified facts, Creative memory and Outcomes from
Settings → Advanced, while the onboarding checklist's and readiness line's direct links to Verified
facts keep working because the team relies on verified claims.

**D7. Cut items.** Intelligence leaves the sidebar. API keys leave the organisation settings sidebar;
the *Developers* link in Settings → Advanced points to them. Agent API, MCP and OAuth mounts and the
`studio:workflow_*` endpoints are untouched.

**D8. Notifications.** The sidebar item becomes a bell (sidebar header and phone top bar) that opens
the existing notifications drawer; `/notifications/` keeps working; Settings → Notifications links to
preferences and Telegram.

**D9. Marketing.** Three linked views: Home, How it works and a new **Request invite** form
(`marketing:request_invite`, CSRF, rate-limited by IP, a honeypot field) that creates an
`invite_requested` Notification for each platform operator (active staff; falls back to the support
address). `/pricing/` answers 301 to Request invite. Developers, Platforms, Features and Get started
keep rendering but are unlinked and `noindex`. Privacy and Terms stay in the footer and at sign-up.

**D10. E2E.** The existing golden specs stay unedited and green, because every route they use keeps
working. New specs cover the new routes on all three devices: the six items and the gear lead to their
screens; `/approvals/` approves and schedules through the same gate; `/settings/?tab=brand` saves the
brand colour; Activity shows the board and the presets; switches add and remove their items. The
Lighthouse Approvals URL becomes `/approvals/` with the same budgets.

## Requirements

### P0 (Phase 2 ships with all of these)

**R1. Navigation builder.** `apps/common/navigation.py` returns the items, the active key and the
counts for a request; `base.html` renders it. Acceptance: Home is active only on Home and the post
page, Activity on Activity and job pages, Settings on Settings; unit tests cover each rule; the
switches decide Blog; Intelligence is not linked; the phone bottom bar shows Home, Approvals (with
its count), Calendar, Inbox and More; nothing covers the post page's phone Approve bar.

**R2. Command palette stub.** Ctrl/Cmd-K (and a button) opens a labelled dialog that filters the
destinations a person can open. Acceptance: keyboard-only use works; axe has no serious findings;
Escape returns focus.

**R3. `/approvals/`.** As D3. Acceptance: the list matches today's tab for the same workspace; approve
and schedule goes through `apps/approvals` unchanged; plain clients 403; workspace B's ids 404.

**R4. `/studio/activity/`.** As D4. Acceptance: everything the Team page's tests require is on Activity;
viewers see no routine controls; `/studio/team/` and `/studio/routines/` answer 301 only after the same
checks as before.

**R5. `/settings/`.** As D5. Acceptance: each tab saves through its old handler with the same result;
a tab a person may not use is absent and its URL answers 403; old settings pages answer 301 to their
tab on GET and keep accepting POST.

**R6. Switches applied.** As D6. Acceptance: for each switch, a test with it off and on; the connect
screen hides only new connections; nothing scheduled stops.

**R7. Cut items out of navigation.** As D7 and D8.

**R8. Marketing.** As D9. Acceptance: header and footer link only Home, How it works, Request invite,
Sign in, Privacy and Terms; the form creates the notification once per submission, refuses a bot and
is rate-limited; `/pricing/` 301s; the sitemap lists the three pages.

**R9. The URL gate.** `tests/test_product_map_urls.py` checks every URL in a frozen copy of today's
`PRODUCT_MAP.md` list, as the owner, and accepts only 200, 301/302 to a working page, 403 or 405 by
design. No 404, no 500.

**R10. Docs.** `PRODUCT_MAP.md`, `CLAUDE.md`, `DESIGN_SYSTEM.md` (navigation) and `tests/e2e/README.md`
describe the new navigation and routes.

### P1 (if time allows in Phase 2, else Phase 3)

- Desktop keyboard shortcuts `n`, `a`, `r`, `/`, `?`.
- A Settings → Advanced → *Features* panel writing the switches (`select_for_update`,
  `update_fields=["features"]`).

### P2 (designed for, not built)

- The New post sheet, the Approvals stack, the onboarding wizard (Phase 3).
- `extra_providers` versus `LAUNCHED_PLATFORMS` on the public pages (Phase 5).

## Success metrics

- **Leading (Phase 2 gate):** 6 items (7 with Blog) instead of 16; one settings surface; zero 404s on
  the frozen URL list; full pytest green with invariant tests unchanged; the golden and new e2e specs
  green on three devices; Lighthouse budgets unchanged.
- **Lagging (beta):** fewer than one "where is…?" question per agency per week.

## Open questions

None block Phase 2; each has a default above.

- *(owner)* Whether Verified facts should count as "advanced" at all (default D6: hidden from the
  Advanced panel when off, still reachable from onboarding and readiness).
- *(owner)* Who receives invite requests (default D9: platform staff, else the support address).

## Phasing inside Phase 2

1. Switch helper and navigation builder (no visible change).
2. Approvals, Activity and Settings screens, with redirects.
3. Switches applied; cut items out; new navigation and phone bar live; palette stub.
4. Marketing to three pages.
5. URL gate, e2e for the new routes, Lighthouse URL, docs; full gate.
