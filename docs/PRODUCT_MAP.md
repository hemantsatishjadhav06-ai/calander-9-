# SM Bean product map

What SM Bean is, every page a signed-in person can reach, how work moves
through it, and what runs on its own. Written for a new engineer and for the
owner. Paths are relative to the repository; URL names are Django's
(`app:name`); every workspace page lives under `/workspace/<workspace id>/`.

## In one paragraph

SM Bean is a self-hosted social media manager. A brand is a **workspace**: it
connects its social accounts, and a few people run it together with an AI team
("your team") that plans, writes, designs and checks posts and blog articles.
You talk to the team in a conversation on **Home** or from Telegram; **routines**
run standing instructions on a schedule; **autopilot** plans each week.
Everything the team makes stops at the same place: a person with approval
rights reviews the exact post, destination and time and approves it. Only then
does the publisher send it.

## Who is who

| Person | Means | Where they work |
|---|---|---|
| **Owner** | Owner of the organisation, or a superuser | Everywhere; the only one who sees which environment variables are missing (on Set up and in Settings → Advanced → Health) |
| **Settings manager** | A member with `manage_workspace_settings` | Turns autopilot on, picks the lead and backup, connects Telegram, chooses how ideas start |
| **Staff** | An internal member with `create_posts` | Home, the conversation, Activity and its routines, posts, blog, inbox |
| **Approver** | An internal member with `approve_posts`; the **lead** and **backup** chosen in Autopilot are told first | Approvals, the post page, the Telegram review card |
| **Viewer** | A member without `create_posts` | Lands on the Calendar; reads |
| **Client** | An outside person with a passwordless portal link | The client portal only; may sign off on posts at the client stage; never approves publication |

Roles and permissions: `apps/members` (`WorkspaceMembership`,
`effective_permissions`, `require_permission`). "Plain client" is
`apps/studio/views.is_plain_client`. Telegram authority:
`apps/telegram/permissions.py`.

## Where things are on the screen

`apps/common/navigation.py` builds the navigation for each request
(`build_nav`: the places, the gear and the phone bar; `build_palette`: Go to)
from the counts `apps/common/context_processors.sidebar_context` already has
and the workspace's switches; `templates/base.html` draws it.

- **Sidebar**: **New** at the top, then six places: Home · Approvals ·
  Calendar · Inbox · Analytics · Activity. Analytics shows while analytics is
  on for at least one platform (`AnalyticsPlatformConfig`, site-wide); **Blog**
  is a seventh place only when the workspace's `blog` switch is on. **Settings**
  is the gear at the bottom. Approvals carries the count of posts waiting,
  Inbox the unread count. There is no *More*. A place shows only to someone
  its screen lets in (the checks Go to uses: Inbox needs `use_inbox`, Analytics
  `view_analytics`; a plain client is refused Home, Approvals, Activity and
  Settings), so a viewer has no Inbox and a contributor no Inbox or Analytics.
  A plain client keeps an **Approvals** that works, the Calendar's Approvals tab
  (`calendar:calendar?mode=list&tab=approvals`), and has no gear. The gear
  shows while a Settings tab lets the person in.
- **One place is lit** (`aria-current="page"`): Home on Home, the post page,
  the thread page and the agency's other pages; Approvals on Approvals and on
  the Calendar's Approvals tab; Calendar on the rest of the Calendar, Queues
  and the posting schedule; Inbox, Analytics and Blog on their own pages;
  Activity on Activity, a job, the live board and the routines; Settings on the
  Settings screen and every page a setting still lives on (Set up, Brand,
  Autopilot, Verified facts, Creative memory, Outcomes, Telegram, members, the
  client admin, social accounts, notification preferences, the workspace and
  approval settings). The composer, Drafts, Ideas, Media and your account light
  none.
- **New** (a menu): Post (the composer), Idea (the idea dialog), then Ideas
  (`composer:create_landing`), Import from CSV (`composer:csv_upload`), and
  Templates (`composer:template_list`) and Categories
  (`composer:category_list`) only with the `templates` switch.
- **Sidebar header**: the workspace switcher (its menu opens other workspaces
  and Workspace settings, which lands on Settings → Brand), **Go to** and the
  **bell**.
- **Bell**: the unread count; opens the notifications drawer, a labelled dialog
  that loads `notifications:drawer` each time it opens. Escape closes it and
  the focus goes back to the bell. `/notifications/` stays the full history.
- **Go to** (the command palette): the Go to button or Ctrl/Cmd-K opens a
  labelled dialog. Typing filters the places this person may open (the checks
  their pages make: Inbox needs `use_inbox`, Analytics `view_analytics`),
  Settings and the Settings tabs they may use. The arrow keys or Tab move,
  Enter opens, Escape closes and the focus goes back. It offers the sidebar's
  places: a plain client none of the agency's screens, with Approvals as the
  Calendar's Approvals tab.
- **Sidebar footer**: the account menu: Manage Team (`members:list`), Account
  (`accounts:settings`, the person's own settings), Appearance (System, Light or
  Dark, kept on this device; a page not yet declared dark-ready says "This page
  stays light for now."), sign out.
- **Phone** (below 1024px): the top bar holds the menu button, the workspace's
  name, Go to and the bell. The **phone bar** along the bottom holds Home,
  Approvals (with its count), Calendar, Inbox and More, each as the sidebar
  shows it to this person (one column each); More opens the drawer,
  which is the sidebar (Analytics, Activity, Blog, the gear). The post page and
  the composer have no phone bar (their own action bar sits there), nor do
  onboarding's connection pages or the Telegram pages for someone not on the
  team. Toasts and selection bars sit above the phone bar.
- **Agency tabs** on Home and the agency's pages
  (`templates/components/agency_tabs.html`, built by
  `apps/studio/dashboard.tabs`): Home · Routines · Team · Settings. Routines
  opens Activity's routines section, Team opens Activity, Settings opens the
  Settings screen. Routines is left out for people without `create_posts`.
- **Calendar header**: Drafts, Queues (only with the `queues` switch), Posting
  schedule and Media.
- **Signing in**: `/` (`apps/accounts/views._workspace_landing`) sends staff to
  Home and everyone else to the Calendar.
- **Client portal**: its own navigation (`templates/client_portal/portal_base.html`).
  The Approvals, Activity and Settings screens refuse a plain client (403),
  like the agency's other pages.

## The pages

Each page says who it is for, what it does, what happens next, and where the
code is (views, templates, services).

### Home — `studio:index` · `/studio/`

- **Who:** every member. The first page staff see.
- **What:** a greeting and one status line (set-up, "Autopilot on · 5 a week",
  whether Telegram is listening and you are paired); the **Today** card, built
  from plain queries: *Waiting for you* (with Review and Approve buttons),
  *Going out today*, *Done since yesterday*, *Needs your review* (paused,
  failed or interrupted tasks) and the next planned run; under it the
  **Right now** card (teammates working, stopped and idle, the busiest task's
  steps, *Open Team*, which opens Activity; it refreshes itself while the tab
  is visible); the **conversation** with your team (the general internal
  thread, composer visible without scrolling); **In progress** (one row per
  idea: idea → brief → draft → approval, one state and one button each);
  **Routines** (the next three, for staff, with *All routines*, which opens
  Activity's routines section); **Recent work**; the onboarding checklist card
  while set-up is incomplete.
- **Next:** a message in the composer becomes a `chat` job that the account
  manager answers in the worker. An idea typed as a new post (`studio:create`)
  becomes its own thread. Review opens the post page; Approve goes through the
  approval gate.
- **Code:** `apps/studio/views.py` (`index`, `_index_context`, `create`,
  `_journeys`), `apps/studio/dashboard.py` (`today`, `needs_review`, `tabs`),
  `apps/studio/views_setup.status_line`, `apps/studio/chat.py` (threads),
  `apps/studio/customer_workflow.py` (ideas). Templates
  `templates/studio/index.html`, `templates/studio/partials/thread*.html`,
  `customer_workflow_journeys.html`, `routine_rows.html`,
  `templates/onboarding/partials/_checklist.html`.

### Approvals — `approvals:index` · `/approvals/`

- **Who:** every member may look; `approve_posts` to act. A plain client gets
  403 (they approve in the client portal).
- **What:** every post awaiting approval — the team's and people's — with a
  preview per destination (exact text, length against the platform limit,
  format, media), **Approve**, **Approve & schedule**, **Request changes**,
  **Reject**, **Resume** after a client hold, comments with attachments, the
  version diff, bulk actions, and the channel, timezone and (with the
  `templates` switch) tag filters. It is
  the Calendar list's Approvals tab on a screen of its own: the same rows from
  the same query, the same HTMX endpoints (`calendar:publish_tab_approvals`
  refreshes it) and the same `approvals:*` actions.
- **Next:** approving stamps a fingerprint of the exact content and time; any
  later change withdraws it; the publisher re-checks it before sending. A
  workspace with `require_dashboard_approval` accepts approvals only from an
  internal approver in the dashboard or through a verified one-use Telegram
  button.
- **The Calendar's tab stays:** `calendar:calendar?mode=list&tab=approvals`
  (`/calendar/?mode=list&tab=approvals`) keeps rendering and lights Approvals.
  The sidebar and the phone bar lead to `/approvals/`; Home's *Open approvals*
  link, Telegram cards, emails, the onboarding checklist and the version diff's
  back link still open the Calendar's tab.
- **Code:** `apps/calendar/views.py` (`approvals_index`, `_get_tab_context`,
  `_publish_filter_context`, `publish_tab_approvals`, `_render_tab`),
  `apps/approvals/urls.py`, `apps/approvals/views.py`, `services.py`
  (`approve_post`, `request_changes`, `reject_post`, `request_hold`,
  `resume_hold`), `gate.py`, `actor.py`, `tasks.py` (reminders and
  escalation). Templates `templates/approvals/index.html`,
  `templates/calendar/partials/publish_approvals.html` and the
  `_publish_filters.html` it shares with the Calendar,
  `templates/approvals/partials/*`, `templates/approvals/version_diff.html`.

### Calendar — `calendar:calendar` · `/calendar/`

- **Who:** every member.
- **What:** month, week and day grids; the list view's tabs Drafts, Queue,
  Approvals, Sent; drag to reschedule (an approver dragging is approving the
  new time); calendar events. The header links Drafts (`composer:drafts_list`),
  **Queues** (`calendar:queue_list`, with the `queues` switch), **Posting
  schedule** (`calendar:posting_slots`), which the team's scheduler reads to
  propose times, and Media (`media_library:index`).
- **Code:** `apps/calendar/views.py`, `services.py`, `tasks.py` (recurring
  posts); `templates/calendar/*`.

### Inbox — `inbox:feed` · `/inbox/`

- **Who:** members with `use_inbox`.
- **What:** comments, mentions, messages and reviews from the connected
  accounts in one list, with assignment, status, sentiment, saved replies and
  an SLA. **Draft replies with the team** asks the community manager and the
  reviews manager for drafts, labelled as such, that a person reads and sends.
  Unhappy reviews are flagged.
- **Code:** `apps/inbox/views.py`, `services.py`, `tasks.py` (sync every five
  minutes), `webhooks.py`; drafts through `apps/studio/views_chat.inbox_draft`,
  `apps/studio/inbox_team.py`, `apps/studio/jobtypes/inbox.py`;
  `templates/inbox/*`.

### Analytics — `analytics:index` · `/analytics/`

- **Who:** members with `view_analytics`; in the sidebar while analytics is on
  for at least one platform.
- **What:** KPI cards, 7/30/90-day trends and the all-posts table from each
  platform's own numbers; a page per post and per account. `/analytics/` opens
  the first connected account's page.
- **Code:** `apps/analytics/views.py`, `services.py`, `tasks.py` (hourly
  sync); `templates/analytics/*`. The team reads the same numbers through
  `apps/studio/performance.py`.

### Activity — `studio:team` · `/studio/activity/`; a job — `studio:job`

- **Who:** every member; the routines section is for staff (`create_posts`).
  A plain client gets 403.
- **What:** the team at work, live (refreshed every five seconds while the tab
  is visible, changes announced to screen readers): four numbers (working now,
  queued, done today, needs you); **Working now**, one row per running task
  with its steps; **Last 24 hours** (turns per hour, with a table view) and
  the **Latest post**'s receipt from draft to published; **Next 24 hours**
  (scheduled posts, routines and plans, approvals due, queued work, under
  "Nothing goes out without your approval"); **Recently finished**; and the
  roster by department, each agent with its job, its state (Working, Stopped
  or Idle, shown by shape and word) and what it did last. Then
  **Routines** (`#routines`, staff only): standing instructions in plain words
  with a schedule. Each row shows title, cadence in words, next run, last
  result, and Pause/Resume, Run now and Delete; three one-tap presets:
  *Morning briefing* (weekdays 08:30), *Monday plan* (Mondays 09:00: plan the
  week's posts from the pillars), *Draft replies to new comments* (weekdays
  17:00). The free-form routine form is in Settings → Advanced.
- **A job page** shows one piece of agency work other than a post (a
  weekly plan, an article, a reply, a report, a learning pass) with its
  timeline and the task controls: Pause, Resume, Retry after review, Cancel.
  A job held by a switched-off autopilot says "Paused: autopilot is off" with
  the link to turn it on.
- **Next:** Resume and Retry acquire the person's current authority and the job
  lock; a failed or interrupted task needs the person to review the saved work
  and acknowledge the retry (a signed snapshot). No interrupted action is
  replayed on its own. A routine runs on the worker's minute tick (see
  *Routines* under *How work flows*); a failed or interrupted routine reaches
  every approver's Telegram inbox with a link back to the routines.
- **Old addresses:** `/studio/team/` and a GET of `studio:routines`
  (`/studio/routines/`) answer 301 to Activity (and its `#routines` section)
  after the pages' own checks. Every routine action still posts to its own
  handler; a routine that fails to save comes back on the old routines page
  with its form (400).
- **Code:** `apps/studio/views_agency.py` (`team_roster`, `team_legacy`),
  `apps/studio/views_live.py` (`team_page`, the Activity page with its
  routines section; `team_board`, the board's refresh and Home's strip),
  `apps/studio/urls_agency.py`, `apps/studio/team.py` (the one list of
  agents), `apps/studio/opendots.py` (`task_record`, `control_job`),
  `apps/studio/opendots_views.py`, `apps/studio/live.py` (the live snapshot;
  `studio:team_board` re-renders it), `apps/studio/views_routines.py`,
  `apps/studio/routines.py` (`create`, `propose`, `tick`, `run_now`,
  `next_run`, `SUGGESTIONS`), models `Routine` and `RoutineRun`. Templates
  `templates/studio/team.html`, `partials/team_board.html` and the
  `partials/team_*.html` it includes, `partials/routine_rows.html`,
  `routine_presets.html`, `routine_form.html`, `templates/studio/routines.html`
  (the form's error page), `partials/live_strip.html` (Home's card),
  `job_detail.html`, `partials/job_progress.html`; `static/js/live_board.js`.

### Blog & SEO — `blog:list` · `/blog/`

- **Who:** every member; writing needs `create_posts`, approving
  `approve_posts`, publishing a website token set by the owner. In the sidebar
  only with the `blog` switch; the pages answer either way.
- **What:** articles for the brand's own website. Write by hand or **Write
  with the team** (`blog:write`: keyword and intent, outline, the article, a
  fact check against the brand's facts, search title and description, a final
  read, a designed cover); a live **SEO score** with each check and its fix;
  preview (signed-in only); submit; approve the exact revision; publish (one
  commit to the website repository plus its deploy, with sitemap and feed);
  **Make social posts** from an approved article; Google Search Console
  rankings per article and **Run an SEO check-up**.
- **Code:** `apps/blog/views.py`, `views_team.py`, `views_search_console.py`,
  `services.py`, `publisher.py`, `seo.py`, `covers.py`, `search_console.py`,
  `tasks.py`; on the agency side `apps/studio/jobtypes/blog.py`,
  `repurpose.py`, `seo.py`; `templates/blog/*`.

### Settings — `settings:index` · `/settings/`

- **Who:** every member but a plain client (403). The strip shows only the
  tabs this person may use; asking for another one by `?tab=` answers
  403, and an unknown tab opens the first one.
- **What:** one screen with seven tabs. Only the open tab is built. Every form
  in a tab posts to its old page's handler (an explicit `action=`), so saving
  behaves exactly as it did on that page.
  - **Brand** — `/settings/?tab=brand`: the brand profile (`studio:brand`'s
    form: name, colours, voice, the facts the team may use, a sample graphic in
    the brand's look), then the workspace's name and logo (the forms from
    `workspaces:settings`). Every member reads it; saving needs what the brand
    page needs.
  - **Accounts** — `/settings/?tab=accounts`: the connected social accounts
    with their state, Reconnect and Disconnect, and the way to the connect
    screen (`social_accounts:connect`). Needs `manage_social_accounts`.
  - **Team & clients** — `/settings/?tab=team`: how many people the
    organisation has and the way to `members:list` (inviting and roles stay
    there), then the client admin itself (invite a client, send or revoke a
    magic link) for a workspace manager.
  - **Approvals** — `/settings/?tab=approvals`: the approval stages and whether
    dashboard approval is required (`workspaces:approvals_settings`'s form,
    which comes back to this tab after saving). Workspace owners and managers.
  - **Autopilot** — `/settings/?tab=autopilot`: the whole autopilot form
    (`studio:autopilot`'s): posts per week, accounts, content pillars, the
    weekday and hour to plan, articles per month (with the `blog` switch),
    inbox drafts, how ideas start; **Advanced** holds the lead and backup
    approvers and the monthly budget. Needs `create_posts`; saving needs
    `manage_workspace_settings`.
  - **Notifications** — `/settings/?tab=notifications`: where this person's
    notification settings and Telegram stand, with the way to
    `notifications:preferences` and `telegram:settings`. No form moves here.
  - **Advanced** — `/settings/?tab=advanced`: **Health** (the Set up
    checklist, the same as `studio:setup`); the free-form routine form (staff);
    **Developers**, a link to the API keys (`api_keys:list`) for the
    organisation's owners and admins only; the danger zone (archive or delete
    the workspace) for its owner or manager, which comes back to Advanced
    unless the workspace is archived or deleted; and, only with the
    `advanced_settings` switch, **Verified facts** (`#verified-facts`),
    **Creative memory** (`#creative-memory`) and a link to **Outcomes**, each
    with its page's own check.
- **Code:** `apps/studio/views_settings.py` (`TABS`, the tab registry: key,
  label, the page's own check, the context builder, the partial;
  `usable_tabs`; `index`), `apps/studio/urls_settings.py` (mounted in
  `config/urls.py` ahead of the client admin's `/settings/clients/`),
  `apps/studio/settings_links.py` (`tab_url`; `moved`, the 301 an old page
  answers; `returning_to`, the tab an old handler returns to). Templates
  `templates/settings/index.html` and `templates/settings/tabs/*.html`,
  which include the old pages' bodies:
  `studio/partials/brand_profile_form.html`, `autopilot_form.html`,
  `setup_checklist.html`, `verified_facts.html`, `memory_body.html`,
  `social_accounts/partials/_account_list.html`,
  `workspaces/partials/approvals_settings_form.html`, `danger_zone.html`,
  `client_portal/admin/partials/client_admin.html`.

The pages a setting lives on, and what they do now:

- **Set up** — `studio:setup` · `/studio/setup/` keeps rendering and keeps its
  name. Every member can read it; owners see exactly what to set; settings
  managers get the buttons. One checklist with live state, plain words and one
  button per row: AI team (the model provider and its key), Pictures (the
  picture key), Social accounts, Approvers (**Use me as lead** when eligible),
  Autopilot (**Turn on with sensible defaults**: lead = current or you,
  accounts = the connected ones, five a week, Friday 16:00), Creation mode
  (show me the brief first, or go ahead unless I say stop), Telegram, Email,
  Verified facts, Blog website, Monthly AI budget. The header counts "N of M
  done". Each button posts to its own small view or links to the page that
  owns the setting. The readiness line under the Home greeting, and wherever
  the team cannot work, never names a setting or a worker; it points here.
  Settings → Advanced → Health shows the same checklist (`health_context`).
  `apps/studio/views_setup.py` (`checklist`, `setup`, `health_context`,
  `use_me_as_lead`, `autopilot_defaults`, `status_line`),
  `apps/studio/readiness.py` (`operational_readiness`, `telegram_state`),
  `apps/telegram/state.py`; `templates/studio/setup.html`.
- **Brand** — `studio:brand` keeps rendering and takes the Brand tab's posts.
  `apps/studio/views.brand_profile`, `brand_defaults.py`, `design.py`;
  `templates/studio/brand_profile.html`.
- **Autopilot** — `studio:autopilot` keeps rendering (with **Plan now**,
  **Write the report now** and the last planned week with what it cost) and
  takes the Autopilot tab's posts. `apps/studio/views_autopilot.py`,
  `forms_agency.py`, `autopilot.py`, `budget.py`, models `AgencySettings`,
  `AutopilotWeek`; `templates/studio/autopilot.html`.
- **Verified facts** — `studio:trust`: prices, dates, availability and claims
  a person has checked, with source and expiry; photo attestations. With
  `advanced_settings` on, a GET answers 301 to Advanced's `#verified-facts`
  (never cached, `?claim=` carried); off, the page renders, so the onboarding
  checklist's and the readiness line's links to it keep working.
  `apps/studio/views_trust.py`, `trust.py`, `forms_trust.py`, model
  `BrandClaim`; `templates/studio/trust.html`.
- **Creative memory** — `studio:memory`: published creatives ranked against
  their own account's average, *Learn from this*, uploads of your designer's
  best work, the house-style paragraph the curator writes and a person may
  overwrite. With `advanced_settings` on, a GET answers 301 to Advanced's
  `#creative-memory` (never cached); off, the page renders.
  `apps/studio/views_memory.py`, `memory.py`, `jobtypes/learn.py`, model
  `CreativeInsight`; `templates/studio/memory.html`.
- **Outcomes** — `studio:outcomes`: campaign results a person records by hand
  (enquiries, site visits). Keeps rendering. `apps/studio/views_outcomes.py`,
  `outcomes.py`, `forms_outcomes.py`, model `CampaignOutcome`;
  `templates/studio/outcomes.html`.
- **Telegram** — `telegram:settings` (its own section below), linked from the
  Notifications tab.
- **Approval settings** — `workspaces:approvals_settings` keeps rendering and
  takes the Approvals tab's posts.
- **Members** — `members:list` (the organisation's people, roles and
  invitations) keeps rendering, linked from Team & clients and the account
  menu.
- **Notification preferences** — `notifications:preferences` keeps rendering,
  linked from the Notifications tab.

### A post — `studio:detail` · `/studio/<brief id>/`

- **Who:** every member can read it; `create_posts` to ask for changes;
  `approve_posts` to approve.
- **What:** the draft the team made: the graphic, the caption and each
  network's own version, the proposed time, the reviewer's score and the QA
  notes, the team's progress by agent, delivery receipts once it went out, and
  this post's own thread. The decision bar comes first on a phone: **Approve &
  schedule**, **Request changes**, new angles, retry, discard; telemetry sits
  behind *Details*. No phone bar covers it.
- **Next:** Approve goes through `apps/approvals/services` and the composer's
  scheduling, so the gate, the audit trail and the notifications are the same
  as on the Approvals screen. Request changes re-runs the team from the right
  stage with the person's words marked as untrusted feedback.
- **Code:** `apps/studio/views.py` (`detail`, `progress`, `approve`,
  `request_changes`, `new_angles`, `use_angle`, `retry`, `discard`),
  `apps/studio/services.py`. Templates `templates/studio/detail.html`,
  `partials/progress.html`, `thread_draft.html`, `thread_receipts.html`,
  `status_badge.html`.

### The team thread page — `studio:thread` · `/studio/thread/`

- **Who:** staff.
- **What:** every thread of the workspace — the general one, one per client,
  one per post, one per article — with one open. Home shows the general
  thread; this page is where the others are.
- **Code:** `apps/studio/views_chat.py`, `apps/studio/chat.py`,
  `apps/studio/jobtypes/chat.py`; `templates/studio/thread.html`.

### Notifications — the bell; `notifications:list` · `/notifications/`

- **Who:** the signed-in person.
- **What:** the bell (sidebar header, phone top bar) shows the unread count and
  opens the drawer with the latest notifications; `/notifications/` is the full
  in-app history. Under `notifications:preferences`: in-app, email and webhook
  delivery per event type, quiet hours and the daily digest (Settings →
  Notifications links there).
- **Code:** `apps/notifications/`; `templates/notifications/*`,
  `templates/components/notifications_bell.html`.

### The pages that were under More

The hand-driven composer and the library. The team's posts land in the same
`Post` and `PlatformPost` rows and the same approval queue.

- Ideas (`composer:create_landing`) and Import from CSV (`composer:csv_upload`):
  in the New menu.
- Templates (`composer:template_list`) and Categories (`composer:category_list`):
  in the New menu with the `templates` switch.
- Drafts (`composer:drafts_list`), Queues (`calendar:queue_list`, with the
  `queues` switch), Posting schedule (`calendar:posting_slots`) and Media
  (`media_library:index`, `apps/media_library`): in the Calendar's header.

Every one of these pages answers whatever the switches say.

### Telegram — `telegram:settings` · `/agency/telegram/`

- **Who:** every member can read it; settings managers connect the bot and
  the groups; each person pairs themselves. Settings → Notifications links
  here.
- **What:** five rows with their live state and one button each: **Deployment
  ready** (the public https origin and the ready switch; owners see the
  variable names, everyone else "Ask your owner"); **Bot connected** (the token
  form, or ✓ @bot with **Retry webhook**); **You are paired** (**Open Telegram
  and pair** with a ten-minute countdown, or ✓ with **Send me a test message**
  and Unpair); **Approvals from Telegram** (one switch; on needs the workspace
  approval gate); and a collapsed **Advanced** section with the team group, the
  client group, a status channel, managed-bot creation (shown only when a
  manager bot can do it) and the linked chats.
- **Next:** once paired, your private chat is your manager inbox and your
  instructions go to your manager (see *How work flows*). Clients pair
  themselves from the portal instead; for someone not on the team the page
  shows no navigation and no phone bar.
- **Code:** `apps/telegram/views.py`, `provisioning.py` (pairing, the webhook,
  the command menu), `state.py`, `permissions.py`, `managed.py`, `forms.py`;
  `templates/telegram/settings.html`. Inbound updates arrive at
  `/webhooks/telegram/<connection id>/` (`apps/telegram/webhooks.py`).

### Client portal — `/portal/…`

- **Who:** clients, through a 30-day magic link (`client_portal:magic_link_entry`).
- **What:** a dashboard with counts and quick links; **Approvals** (approve,
  request changes, reject, or hold at the client stage); **Published**;
  **Activity** (their own actions); **Reports** (the weekly report); **Talk to
  the team** (`client_portal:team`, plus *Ask a question* / *Request a change*
  on each post waiting for them); **Telegram** (pair their own account).
  Nothing in it changed with the agency's new navigation.
- **Next:** a client's message queues a `chat` job and the account manager
  answers; a client's change request reopens the post for the team but still
  needs internal approval; a client's sign-off completes the client stage and
  never publishes anything.
- **Code:** `apps/client_portal/views.py`, `views_team.py`, `views_telegram.py`,
  `decorators.py` (`portal_auth_required`), `services.py`;
  `templates/client_portal/*`.

### Old addresses

Old links in Telegram cards, emails and bookmarks keep working. An old page
that moved answers a 301 on GET, inside its own view, after its login,
permission and workspace checks, so someone it refused before is still
refused (403 or 404), never redirected. `?open=` and `?claim=` travel with
the redirect. POSTs and HTMX fragments never redirect.

| Old address | Answers |
|---|---|
| `studio:settings_hub` · `/studio/settings/` | 301 to Settings, Brand tab |
| `workspaces:settings` | 301 to Settings, Brand tab; its POSTs (name, logo, the danger zone) stay |
| `social_accounts:list` | 301 to Settings, Accounts tab |
| `client_portal_admin:client_list` | 301 to Settings, Team & clients tab |
| `studio:trust`, `studio:memory` | 301 to Settings, Advanced while `advanced_settings` is on; otherwise they render |
| `/studio/team/` | 301 to Activity |
| `studio:routines` · `/studio/routines/` | 301 to Activity's routines section on GET; its POSTs stay |
| `/pricing/` | 301 to Request invite |
| `studio:workflow` | 302 to Home (the earlier guided page) |

These keep rendering: `studio:setup`, `studio:brand`, `studio:autopilot`,
`studio:outcomes`, `studio:detail`, `studio:job`, `studio:team_board`,
`calendar:calendar` (with `?mode=list&tab=approvals` too),
`workspaces:approvals_settings`, `members:list`, `notifications:list`,
`notifications:preferences`, `telegram:settings` and every
`client_portal:*` page. `studio:workflow_create`, `workflow_resume` and
`workflow_status` keep deep links and the In progress rows working
(`apps/studio/views_customer_workflow.py`). `tests/test_product_map_urls.py`
fetches every address this map lists, and every one it listed before Phase 2
(`tests/fixtures/product_map_urls.txt`), and fails on a 404 or a 500.

### Switches

Each workspace has five switches in `AgencySettings.features` (a JSON object
like `{"queues": true}`, set in the Django admin under Agency settings).
`apps/common/features.py`: `feature_enabled(workspace, key)` reads one,
`features_for(workspace)` all of them in one query, and `request_features`
once per request; templates get the same answer as `features`. A switch hides
navigation and the ways to create; its pages still answer, existing data keeps
working, and nothing scheduled, queued or planned stops.

| Switch | Default | Off, it hides | Stays either way |
|---|---|---|---|
| `blog` | on when the workspace has an enabled blog website | the Blog place and its Go to entry; the autopilot form's articles per month and website fields (the stored values are kept) | the blog pages, articles, their publishing |
| `queues` | off | Queues in the Calendar's header; the composer's queue order | Next available, the posting schedule, recurring posts, the queue pages |
| `templates` | off | Templates and Categories in the New menu; the composer's Use template, Save as template and tag picker (a post's tags are kept); the Ideas page's Templates tab, tag filter and tag pickers; the tag filter on the Calendar list and Approvals | Import from CSV, the Templates and Categories pages |
| `extra_providers` | off | Bluesky, Mastodon, DEV.to, Threads and TikTok on the connect screen and the client connection page, unless the workspace already has an account there; their forms refuse a new connection in words | reconnect, the OAuth callbacks, accounts already connected |
| `advanced_settings` | off | Verified facts, Creative memory and Outcomes in Settings → Advanced | their pages, and the links to Verified facts from onboarding and the readiness line |

### Out of the navigation

Intelligence is no longer linked from the sidebar (its pages and its optional
add-on are unchanged). API keys left the organisation settings sidebar; the
*Developers* link in Settings → Advanced leads there, for the organisation's
owners and admins. The Agent API, MCP, OAuth and the `studio:workflow_*`
endpoints are unchanged.

## The public site

Signed out, three pages are linked to each other: Home (`marketing:home` at
`/`; signed in, `/` opens your workspace instead), How it works
(`marketing:how_it_works` · `/how-it-works/`) and **Request invite**
(`marketing:request_invite` · `/request-invite/`). The header links those three
and Sign in; the footer adds Terms, Privacy, Support and Source code (and
Create account only when sign-up is open). When sign-up is closed, every call
to action that led to sign-up leads to Request invite. `/pricing/` answers 301
to Request invite. Features (`/features/`), Platforms (`/platforms/`),
Developers (`/developers/`) and Get started (`/get-started/`) keep rendering
for old links, carry `noindex` and are linked from nowhere. The sitemap lists
the three pages and the legal pages.

- **Request invite:** name, agency, email and a note. CSRF, a hidden honeypot
  (a bot gets the thank-you and nothing is sent), at most 10 POSTs an hour per
  client address (an IPv6 client's whole /64 counts as one) and at most
  `REQUEST_INVITE_HOURLY_LIMIT` (30) requests an hour passed on from every
  address together (past it the person is thanked, nobody is told, and the log
  says so without their words). Each request makes one `invite_requested`
  notification for every active staff user: in the bell at once, by email in
  one message a day (after 08:00 UTC; quiet hours keep it in the bell), so it
  never spends the email allowance their alerts need. With no staff user, one
  email goes to `SUPPORT_EMAIL`; with neither, the page says it could not be
  passed on (503).
  A sent request redirects to `?sent=1`, which thanks the person, so a refresh
  never sends it twice. The requester's words are shown escaped and never
  reach a prompt or Telegram.
- **Code:** `apps/marketing/urls.py`, `views.py` (`home`, `how_it_works`,
  `request_invite`, `pricing`), `forms.py`; `config/urls.py` (`pricing`);
  `templates/marketing/*`; `static/css/marketing.css`.

## How work flows

### An idea becomes a post

1. **Idea.** A staff member types on Home (`studio:create` →
   `customer_workflow.save_idea` + `start_idea`) or in a paired Telegram chat
   (`apps/telegram/conversations.handle_message`). Either way the words become
   a `Message` in a `Conversation` and a `chat` job
   (`apps/studio/chat.post_message`, kind `create`). Nothing is spliced into
   the person's words; guidance travels as job input.
2. **Conversation.** The worker runs `apps/studio/jobtypes/chat.answer` inside
   `guards.agent_work`. The account manager reads the thread, the brand profile
   and fresh source evidence (`creative_sources.collect`: the brand website and
   the connected channels, cached for a quarter of an hour per workspace, always
   treated as untrusted), proposes a brief (`creative_brief`), and the code
   fills whatever is still empty from the brand's defaults
   (`creative_brief.defaults` and `complete`): audience and key message from
   the brand, the call to action, the connected accounts, the house style.
   Only the topic is truly required for staff; clients get the question round.
3. **Brief.** The card shows the fields and marks the defaults you can change.
   With *Show me the brief first* a person taps **Go ahead** (on the web, or
   on the Telegram card issued by `apps/telegram/actions.issue_brief_confirmation`);
   with *Go ahead unless I say stop* (`AgencySettings.creation_mode`) the team
   starts at once and the card shows **Stop** for a minute
   (`views_chat.thread_stop_brief`). Evidence older than a day is refreshed
   silently and you are asked again only when it changed
   (`creative_sources.digest`). With more than two posts already in the works
   from chat, the brief is created PLANNED and queued (`services.create_brief`,
   `start_planned`).
4. **Pipeline.** `apps/studio/pipeline.py`: strategy → copy → art → picture →
   render → review → channel → qa → schedule → handoff, one worker task per
   stage at a priority below publishing. The scheduler proposes a time from the
   account's posting slots and history (`scheduling.py`); the QA inspector runs
   code checks (`qa.py`); the producer creates the `Post` and its
   `PlatformPost`s and submits them for review (`step_handoff` →
   `apps/approvals/services.submit_for_review`). The brief is READY and appears
   under *Waiting for you*.
5. **Approval.** A person reviews on the post page or on the Approvals
   screen, or taps the Telegram review card
   (`apps/telegram/actions.issue_post_review`: one use, bound to the actor,
   chat, bot, workspace and the exact snapshot).
   `apps/approvals/gate.py` stamps the fingerprint; `actor.py` knows who is
   acting. Nothing else can approve: not the worker, the Agent API, MCP, the
   client portal, or a plain "yes" in a chat.
6. **Publish.** `apps/publisher/tasks.run_publish_cycle` (every 15 seconds)
   claims due `PlatformPost`s in one guarded statement, re-checks the approval
   under a row lock and once more before the platform call, and sends through
   `providers/<platform>.py`. `confirm_pending_publishes` settles what is in
   flight.
7. **Receipts.** Each destination's outcome is recorded on its `PlatformPost`.
   An uncertain outcome or an expired time is held (`apps/publisher/delivery.py`)
   for a person to reconcile from the post page (`views_delivery.py`); nothing
   is resent on its own. The thread shows the receipts
   (`chat.py`, `thread_receipts.html`) and Telegram mirrors them
   (`apps/telegram/notifications.platform_receipt`).

### Changes and questions

A message from a post card ("make the headline shorter") is a `chat` job with
kind `change`. The manager picks one action from a closed list
(`jobtypes/chat.ALL_ACTIONS`: answer, revise_copy, revise_design, new_picture,
new_angles, new_post, edit_blog, set_routine, escalate), offered only when the
asker may have it done and the thread's item supports it; the code then checks
the action again and calls the same services people use
(`services.request_changes`, `new_angles`, a `blog` job). A client's request goes
through `services.reopen` and still waits for internal approval. Anything the
manager cannot arrange is handed to a person ("escalate").

### Routines

`Routine` rows, listed on Activity, run by `apps/studio/routines.py`. A person
writes one in the form in Settings → Advanced or takes one of Activity's three
presets. Every minute `tick` settles
runs that ended and starts due routines under a row lock, after the same gates
as every other automatic action: an eligible workspace, a configured provider,
budget left, and the author still a staff member. An instruction routine posts
its text as the author's message with kind `routine`; a briefing routine calls
`briefing.send_daily`. A run whose 45-minute lease expires while its job is
still active becomes **interrupted** and is never retried on its own, not even
at its next time, until a person checks what it did. The chat action
`set_routine` proposes a routine switched off, with one tap to turn it on;
`/routines` lists them in Telegram.

### Autopilot

`apps/studio/autopilot.run_cycle` (every 15 minutes), each part reading the
database and queueing one-shot work: plan next week where it is due
(`plan_week` → a `plan` job: listen → moments → plan → brief, which creates
PLANNED briefs inside an `AutopilotWeek`); feed PLANNED briefs to the team a few
at a time (`feed_planned_briefs`, within `AGENCY_MAX_ACTIVE_BRIEFS`); refresh
creative memory after new analytics (a `learn` job); draft inbox replies where
switched on (an `inbox` job); announce a finished week once; queue the weekly
client report on Monday morning (a `report` job). Nothing here approves,
schedules or publishes.

### The Telegram manager inbox

`apps/telegram/inbox.tell` is the only route for "something needs a person": a
post entering review, a client sign-off request, a reminder (one fresh card a
day), a planned week, a failed delivery, a finished report, an agency alert, a
routine that failed or was interrupted, the morning briefing. It finds the
current approvers (the lead and backup first, then internal members who both
approve and create posts; never clients), respects `/mute`, quiet hours
(22:00–07:00 workspace time; reminders, failed deliveries and the briefing still
get through) and a cap of 40 proactive messages per person per day, dedupes by
a source key, and queues through the encrypted, retried outbox
(`apps/telegram/outbox.py`). The review card goes when the person may act from
Telegram; otherwise a preview with **Open to approve**. Entry points:
`apps/telegram/signals.py` runs after commit for every new `Notification`
(`notifications.notification_event`), every new thread `Message`
(`mirror_message`) and every `PlatformPost` change (`platform_receipt`).

### Alerts and the briefing

`apps/studio/alerts.py`: `job_failed` (any job other than a chat reply, once
per revision) and `week_failed` tell the lead and backup in-app, by email
(`EventType.AGENCY_ALERT`) and through the inbox; every link lands on the page
where the person decides. `apps/studio/briefing.py`: `build` is the same cheap
queries as Home's Today card, no model call; `send_daily` sends it once per
workspace day with **Open approvals** and **Open Home** buttons and the first
waiting post's card, through the inbox so muted people still get this one
message.

## What runs on its own

Everything recurring runs in the one worker (`python manage.py run_worker`),
registered by each app's `apps.py` through
`apps/common/background.register_recurring_task` and wrapped by
`keep_schedule`, so a failing run is logged and the schedule survives. None of
them approve, schedule or publish anything a person has not approved; the
publisher sends only what carries a matching approval.

| Task (app) | Every | What it does | May | May not |
|---|---|---|---|---|
| `run_publish_cycle` (`publisher`) | 15 s | Claims due, approved `PlatformPost`s and sends them | send approved content at its approved time | send anything whose approval no longer matches |
| `run_telegram_cycle` (`telegram`) | 30 s | Drains inbound updates, sweeps receipts and workflow replies, drains the outbox, clears old payloads | process paired people's messages; send queued messages | approve anything; replay an uncertain send |
| `confirm_pending_publishes` (`publisher`) | 60 s | Settles posts left in `publishing`; confirms asynchronous publishes | mark failed or confirmed; hold an uncertain outcome | resend on its own |
| `run_routine_tick` (`studio`) | 60 s | Settles routine runs; starts due routines | post an instruction as its author; send the briefing | start past a workspace, provider, budget or author gate; retry an interrupted run |
| `retry_failed_deliveries` (`notifications`) | 60 s | Retries notification deliveries past their backoff | deliver in-app, email, webhook | — |
| `send_batched_email_digests` (`notifications`) | 60 s | One email per person for waiting notifications | email | — |
| `run_inbox_sync_cycle` (`inbox`) | 5 min | Polls connected accounts for comments, messages and reviews | read | reply |
| `sweep_stuck_briefs` (`studio`) | 10 min | Fails briefs and jobs whose worker died mid-stage | mark failed so a person can Retry | retry on its own |
| `sweep_stuck_blog_publishes` (`blog`) | 10 min | Settles an article left in `publishing` | mark failed | publish again |
| `run_agency_cycle` (`studio`) | 15 min | Autopilot: plan due weeks, feed planned briefs, refresh memory, draft inbox replies, announce weeks, queue reports | queue agency jobs within budget and `AGENCY_MAX_ACTIVE_BRIEFS` | approve, schedule, send |
| `run_approval_reminders_cycle` (`approvals`) | 15 min | Reminders and escalation for stalled approvals; deadline reminders to the backup | notify | approve |
| `run_recurrence_cycle` (`calendar`) | 1 h | Creates posts from recurring rules | create drafts | schedule anything unapproved |
| `sync_all_account_analytics` (`analytics`) | 1 h | Refreshes metrics on the decay-by-age schedule | read | — |
| `sweep_pending_uploads` (`media_library`) | 1 h | Deletes expired, never-finished uploads | delete orphans | — |
| `sweep_idempotency` (`api`) | 1 h | Deletes stale Agent API idempotency records | — | — |
| `queue_search_console_syncs` (`blog`) | 6 h | Queues a daily rankings sync per connected website | read | — |
| `queue_seo_checkups` (`blog`) | 6 h | Queues the weekly `seo` job per workspace with live articles | queue a job within budget | change an article |
| `schedule_all_health_checks` (`social_accounts`) | 6 h | Checks each connected account's token | read; flag an account | — |
| `intelligence_reconcile` (`intelligence`) | 6 h | Reconciles the optional hosted add-on's subscription | — | — |
| `run_orphaned_media_sweep` (`media_library`) | 24 h | Deletes media no post, idea or template references | delete | — |
| `purge_email_counters` (`common`) | 24 h | Drops old email budget buckets | — | — |
| `clear_expired_sessions` (`accounts`) | 24 h | Deletes expired sessions | — | — |

Checks: `python manage.py live_verify` reports `worker.schedules` with the
rest; the Set up page and the Home status line say when automatic work has not
run recently (`readiness.operational_readiness`); a problem in the Telegram
cycle is recorded with `note_task_failure` and shows in the worker's health.
