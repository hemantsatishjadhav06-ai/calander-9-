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
| **Owner** | Owner of the organisation, or a superuser | Everywhere; the only one who sees which environment variables are missing (on Set up) |
| **Settings manager** | A member with `manage_workspace_settings` | Turns autopilot on, picks the lead and backup, connects Telegram, chooses how ideas start |
| **Staff** | An internal member with `create_posts` | Home, the conversation, routines, posts, blog, inbox |
| **Approver** | An internal member with `approve_posts`; the **lead** and **backup** chosen in Autopilot are told first | Approvals, the post page, the Telegram review card |
| **Viewer** | A member without `create_posts` | Lands on the Calendar; reads |
| **Client** | An outside person with a passwordless portal link | The client portal only; may sign off on posts at the client stage; never approves publication |

Roles and permissions: `apps/members` (`WorkspaceMembership`,
`effective_permissions`, `require_permission`). "Plain client" is
`apps/studio/views.is_plain_client`. Telegram authority:
`apps/telegram/permissions.py`.

## Where things are on the screen

- **Sidebar** (`templates/base.html`): Home · Approvals · Calendar · Inbox ·
  Blog & SEO · Analytics · Notifications · Set up, then **More** (Create Idea,
  Drafts, Queues, Posting Schedule, Templates, Categories, Import CSV, Media).
  The workspace switcher at the top and the footer lead to workspace settings,
  members and your account.
- **Agency tabs** on Home and its pages (`templates/components/agency_tabs.html`,
  built by `apps/studio/dashboard.tabs`): Home · Routines · Team · Settings.
  Routines is left out for people without `create_posts`. The settings pages
  keep their own URLs and light up the Settings tab.
- **Signing in**: `/` (`apps/accounts/views._workspace_landing`) sends staff to
  Home and everyone else to the Calendar.
- **Client portal**: its own navigation (`templates/client_portal/portal_base.html`).

## The pages

Each page says who it is for, what it does, what happens next, and where the
code is (views, templates, services).

### Home — `studio:index` · `/studio/`

- **Who:** every member. The first page staff see.
- **What:** a greeting and one status line (set-up, "Autopilot on · 5 a week",
  whether Telegram is listening and you are paired); the **Today** card, built
  from plain queries: *Waiting for you* (with Review and Approve buttons),
  *Going out today*, *Done since yesterday*, *Needs your review* (paused,
  failed or interrupted tasks) and the next planned run; the **conversation**
  with your team (the general internal thread, composer visible without
  scrolling); **In progress** (one row per idea: idea → brief → draft →
  approval, one state and one button each); **Routines** (the next three, for
  staff); **Recent work**; the onboarding checklist card while set-up is
  incomplete.
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

### Set up — `studio:setup` · `/studio/setup/`

- **Who:** every member can read it; owners see exactly what to set; settings
  managers get the buttons.
- **What:** one checklist with live state, plain words and one button per row:
  AI team (the model provider and its key), Pictures (the picture key), Social
  accounts, Approvers (**Use me as lead** when eligible), Autopilot (**Turn on
  with sensible defaults**: lead = current or you, accounts = the connected
  ones, five a week, Friday 16:00), Creation mode (show me the brief first, or
  go ahead unless I say stop), Telegram, Email, Verified facts, Blog website,
  Monthly AI budget. The header counts "N of M done".
- **Next:** each button posts to its own small view or links to the page that
  owns the setting. The same readiness line appears under the Home greeting and
  wherever the team cannot work; the copy there never names a setting or a
  worker, it points here.
- **Code:** `apps/studio/views_setup.py` (`checklist`, `setup`,
  `use_me_as_lead`, `autopilot_defaults`, `status_line`),
  `apps/studio/readiness.py` (`operational_readiness`, `telegram_state`),
  `apps/telegram/state.py`. Template `templates/studio/setup.html`.

### Routines — `studio:routines` · `/studio/routines/`

- **Who:** staff (`create_posts`).
- **What:** standing instructions in plain words with a schedule. The list
  shows title, cadence in words, next run, last result, and Pause/Resume, Run
  now and Delete. A plain form (instruction, cadence, weekday, time) and three
  one-tap suggestions: *Morning briefing* (weekdays 08:30), *Monday plan*
  (Mondays 09:00: plan the week's posts from the pillars), *Draft replies to
  new comments* (weekdays 17:00).
- **Next:** a worker tick every minute starts due routines. An **instruction**
  routine posts its text as the author's message in the team thread (kind
  `routine`), so the manager does the task with defaults and asks nothing; a
  **briefing** routine sends the morning briefing. Results land in the thread;
  a failed or interrupted routine reaches every approver's Telegram inbox with
  a link back here.
- **Code:** `apps/studio/routines.py` (`create`, `propose`, `tick`, `run_now`,
  `next_run`, `SUGGESTIONS`), `apps/studio/views_routines.py`, models
  `Routine` and `RoutineRun`. Templates `templates/studio/routines.html`,
  `partials/routine_rows.html`.

### Team — `studio:team` · `/studio/team/`; a job — `studio:job`

- **Who:** every member.
- **What:** the roster of agents by department with what each one does and who
  is busy. A job page shows one piece of agency work other than a post (a
  weekly plan, an article, a reply, a report, a learning pass) with its
  timeline and the task controls: Pause, Resume, Retry after review, Cancel.
  A job held by a switched-off autopilot says "Paused: autopilot is off" with
  the link to turn it on.
- **Next:** Resume and Retry acquire the person's current authority and the job
  lock; a failed or interrupted task needs the person to review the saved work
  and acknowledge the retry (a signed snapshot). No interrupted action is
  replayed on its own.
- **Code:** `apps/studio/views_agency.py`, `apps/studio/team.py` (the one list
  of agents), `apps/studio/opendots.py` (`task_record`, `control_job`),
  `apps/studio/opendots_views.py`. Templates `templates/studio/team.html`,
  `job_detail.html`, `partials/job_progress.html`.

### Settings hub — `studio:settings_hub` · `/studio/settings/`

- **Who:** every member sees the cards; each page keeps its own permission.
- **What:** one card per page the agency's settings are spread over
  (`apps/studio/dashboard.settings_cards`; template
  `templates/studio/settings_hub.html`):
  - **Brand** — `studio:brand`: name, colours, voice, the facts the team may
    use, a sample graphic in the brand's look. `apps/studio/views.brand_profile`,
    `brand_defaults.py`, `design.py`; `templates/studio/brand_profile.html`.
  - **Verified facts** — `studio:trust`: prices, dates, availability and claims
    a person has checked, with source and expiry; photo attestations.
    `apps/studio/views_trust.py`, `trust.py`, `forms_trust.py`, model
    `BrandClaim`; `templates/studio/trust.html`.
  - **Creative memory** — `studio:memory`: published creatives ranked against
    their own account's average, *Learn from this*, uploads of your designer's
    best work, the house-style paragraph the curator writes and a person may
    overwrite. `apps/studio/views_memory.py`, `memory.py`, `jobtypes/learn.py`,
    model `CreativeInsight`; `templates/studio/memory.html`.
  - **Outcomes** — `studio:outcomes`: campaign results a person records by hand
    (enquiries, site visits). `apps/studio/views_outcomes.py`, `outcomes.py`,
    `forms_outcomes.py`, model `CampaignOutcome`; `templates/studio/outcomes.html`.
  - **Autopilot** — `studio:autopilot`: posts per week, accounts, content
    pillars, the weekday and hour to plan, articles per month, inbox drafts,
    how ideas start; **Advanced** holds the lead and backup approvers and the
    monthly budget; **Plan now** and **Write the report now**; the last planned
    week with what it cost. `apps/studio/views_autopilot.py`, `forms_agency.py`,
    `autopilot.py`, `budget.py`, models `AgencySettings`, `AutopilotWeek`;
    `templates/studio/autopilot.html`.
  - **Telegram** — `telegram:settings` (its own section below).
  - **Budget** — the Autopilot page opened on its Advanced section.

### A post — `studio:detail` · `/studio/<brief id>/`

- **Who:** every member can read it; `create_posts` to ask for changes;
  `approve_posts` to approve.
- **What:** the draft the team made: the graphic, the caption and each
  network's own version, the proposed time, the reviewer's score and the QA
  notes, the team's progress by agent, delivery receipts once it went out, and
  this post's own thread. The decision bar comes first on a phone: **Approve &
  schedule**, **Request changes**, new angles, retry, discard; telemetry sits
  behind *Details*.
- **Next:** Approve goes through `apps/approvals/services` and the composer's
  scheduling, so the gate, the audit trail and the notifications are the same
  as on the Approvals page. Request changes re-runs the team from the right
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

### Approvals — the Calendar's list view, Approvals tab

`calendar:calendar?mode=list&tab=approvals` · `/calendar/?mode=list&tab=approvals`

- **Who:** anyone may look; `approve_posts` to act.
- **What:** every post awaiting approval — the team's and people's — with a
  preview per destination (exact text, length against the platform limit,
  format, media), **Approve**, **Approve & schedule**, **Request changes**,
  **Reject**, **Resume** after a client hold, comments with attachments, the
  version diff, bulk actions.
- **Next:** approving stamps a fingerprint of the exact content and time; any
  later change withdraws it; the publisher re-checks it before sending. A
  workspace with `require_dashboard_approval` accepts approvals only from an
  internal approver in the dashboard or through a verified one-use Telegram
  button.
- **Code:** `apps/calendar/views.py` (`publish_tab_approvals`, `_render_tab`),
  `apps/approvals/views.py`, `services.py` (`approve_post`, `request_changes`,
  `reject_post`, `request_hold`, `resume_hold`), `gate.py`, `actor.py`,
  `tasks.py` (reminders and escalation). Templates
  `templates/calendar/partials/publish_approvals.html`,
  `templates/approvals/partials/*`, `templates/approvals/version_diff.html`.

### Calendar — `calendar:calendar` · `/calendar/`

- **Who:** every member.
- **What:** month, week and day grids; the list view's tabs Drafts, Queue,
  Approvals, Sent; drag to reschedule (an approver dragging is approving the
  new time); calendar events. Under More: **Queues** (`calendar:queue_list`)
  and **Posting Schedule** (`calendar:posting_slots`), which the team's
  scheduler reads to propose times.
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

### Blog & SEO — `blog:list` · `/blog/`

- **Who:** every member; writing needs `create_posts`, approving
  `approve_posts`, publishing a website token set by the owner.
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

### Analytics — `analytics:index` · `/analytics/`

- **Who:** every member.
- **What:** KPI cards, 7/30/90-day trends and the all-posts table from each
  platform's own numbers; a page per post and per account.
- **Code:** `apps/analytics/views.py`, `services.py`, `tasks.py` (hourly
  sync); `templates/analytics/*`. The team reads the same numbers through
  `apps/studio/performance.py`.

### Notifications — `notifications:list` · `/notifications/`

- **Who:** the signed-in person.
- **What:** the in-app history and, under preferences, in-app, email and
  webhook delivery per event type.
- **Code:** `apps/notifications/`; `templates/notifications/*`.

### More

Create Idea (`composer:create_landing`), Drafts (`composer:drafts_list`),
Queues, Posting Schedule, Templates, Categories, Import CSV (`apps/composer`,
`apps/calendar`) and Media (`media_library:index`, `apps/media_library`). These
are the hand-driven composer and the library; the team's posts land in the
same `Post` and `PlatformPost` rows and the same approval queue.

### Workspace settings

`workspaces:settings` (name, timezone, branding), `workspaces:approvals_settings`
(the approval stages and whether dashboard approval is required), **Clients**
(`apps/client_portal/urls_admin.py`: invite a client, send or revoke a magic
link), **Social accounts** (`apps/social_accounts`: connect, reconnect,
health), **Members** (`apps/members`: roles and invitations).

### Telegram — `telegram:settings` · `/agency/telegram/`

- **Who:** every member can read it; settings managers connect the bot and
  the groups; each person pairs themselves.
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
  themselves from the portal instead.
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
- **Next:** a client's message queues a `chat` job and the account manager
  answers; a client's change request reopens the post for the team but still
  needs internal approval; a client's sign-off completes the client stage and
  never publishes anything.
- **Code:** `apps/client_portal/views.py`, `views_team.py`, `views_telegram.py`,
  `decorators.py` (`portal_auth_required`), `services.py`;
  `templates/client_portal/*`.

### Older entry points that still work

`studio:workflow` (the earlier guided page) redirects to Home;
`studio:workflow_create`, `workflow_resume` and `workflow_status` keep deep
links and the In progress rows working (`apps/studio/views_customer_workflow.py`).

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
5. **Approval.** A person reviews on the post page or on Approvals, or taps the
   Telegram review card (`apps/telegram/actions.issue_post_review`: one use,
   bound to the actor, chat, bot, workspace and the exact snapshot).
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

`Routine` rows, run by `apps/studio/routines.py`. Every minute `tick` settles
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
