# CLAUDE.md — SM Bean for engineers and coding agents

Read `docs/PRODUCT_MAP.md` first for what the product is and where every page
lives. This file is the working contract: how to run and test, the rules that
must hold, the module map, naming, and how to extend the three things people
extend most often.

## Run and test

Toolchain: Python 3.12 in `.venv/` (`.venv/bin/python`, `.venv/bin/pytest`,
`.venv/bin/ruff`, `.venv/bin/mypy`), Node 22 for the UI tests and the CSS build,
PostgreSQL 16 (tests need it; SQLite is not enough).

**Environment.** `config/settings/base.py` reads `.env` at the repository root
when it exists; `.env.example` lists every variable with its meaning. Agents
working in this repository have used a small exported file instead
(`dev.env`, kept outside the tree: `SECRET_KEY`, `ENCRYPTION_KEY_SALT`,
`DATABASE_URL`, `DEBUG`, `ALLOWED_HOSTS`, `APP_URL`, `STORAGE_BACKEND=local`,
`MEDIA_ROOT`, `SIGNUP_MODE`), loaded with `set -a; . dev.env; set +a` before a
command. Never commit either file.

**Tests** use `config.settings.test` (set in `pyproject.toml`). It supplies its
own `SECRET_KEY` and salt, uses local storage and in-memory mail and cache, and
connects to Postgres from `DB_NAME` (default `brightbean_test`), `DB_USER` and
`DB_PASSWORD` (`postgres`/`postgres`), `DB_HOST` (`localhost`) and `DB_PORT`.
pytest-django creates `test_<DB_NAME>`, so two suites running at once on one
machine need different `DB_NAME`s.

```bash
.venv/bin/pytest -q -p no:cacheprovider apps/studio            # one app
.venv/bin/pytest -q -p no:cacheprovider                        # everything (about eight minutes)
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy apps/ config/ providers/ tests/ --ignore-missing-imports
.venv/bin/python manage.py makemigrations --check --dry-run    # a model change needs its migration
npm ci --ignore-scripts && npm run test:ui                     # tests/js/*.test.cjs (the thread's state machine)
(cd theme/static_src && npm ci && npm run build)               # static/css/dist/styles.css is committed; rebuild after changing classes
.venv/bin/python manage.py runserver                            # the web app
.venv/bin/python manage.py run_worker                           # the one worker: publishing, agency, Telegram
```

CI (`.github/workflows/ci.yml`) runs exactly these: UI tests, `ruff check` and
`ruff format --check`, mypy, `makemigrations --check --dry-run`, pytest with
coverage on Postgres, then the Docker build. The pre-commit hooks mirror them
(`CONTRIBUTING.md`).

Tests never reach a provider: `conftest.py` makes the model client, the second
provider's client and the source fetcher refuse. Fake the team
(`apps/studio/tests/conftest.py`, `fake_team`) or install an httpx
`MockTransport`. Many tests rely on `select_for_update(skip_locked=True)`, so
they are Postgres-only by design.

## Invariants

These hold everywhere. Each names where it is enforced, so you can find the
test to extend when you change nearby code.

1. **Nothing publishes, schedules or approves without a person.** All agency
   work runs inside `apps/studio/guards.agent_work`; the few functions that
   approve, schedule or publish call `guards.forbid_in_agent_work` and raise if
   an agent ever reaches them. `apps/approvals/gate.py` stamps a fingerprint of
   the exact content and time when an internal approver acts through the
   dashboard or a verified one-use Telegram button (`apps/approvals/actor.py`);
   any later change withdraws it; `apps/publisher/engine.py` re-checks it under
   a row lock and again just before the platform call. The worker, the Agent
   API, MCP, the client portal and a plain "yes" in a chat can create and
   submit, never approve. The scheduler only proposes `proposed_publish_at`;
   `apps/studio/services.approve` is the one place a brief's time becomes a
   schedule, and only for a person.
2. **Workspace isolation.** Every query is scoped by workspace (the scoped
   managers in `apps/common`; views resolve the workspace from the URL and the
   person's membership). A Telegram identity is paired per workspace bot
   (`apps/telegram/permissions.current_member`, `fresh_member`); usernames,
   group titles and forwarded messages never grant access. A cross-workspace
   read is a bug; `live_verify` has `isolation.workspace`.
3. **Clients only in the portal.** A plain client (`apps/studio/views.is_plain_client`)
   uses `/portal/` and the client threads; `apps/studio/chat.py` decides who may
   write where, and internal notes never reach a client thread; a client's
   sign-off completes the client stage only. Client Telegram groups receive
   client-safe wording only; `apps/telegram/inbox.approvers` never includes a
   client, whatever a custom role says.
4. **Private Telegram stays private.** A paired private chat's history and jobs
   are visible only through that pairing. `chat.web_conversations`, `web_jobs`
   and `web_agent_runs` keep them out of every web list, and a privacy marker
   on the rows survives disconnects and role changes (`apps/telegram/models.py`).
   Never add a web view that reads them.
5. **Untrusted text only through the wrappers.** Anything written by people
   outside the team or fetched from outside — a client's or commenter's message,
   a review, a website, an old caption, a reference description, a routine's
   result quoted back — enters a prompt only through
   `apps/studio/roles/base.untrusted(tag, text, limit=…)` (or
   `prompts.feedback_block(..., untrusted=True)`); the preamble tells every
   agent to read `<untrusted>` as data. Never concatenate such text raw. Model
   answers are validated against `apps/studio/schemas.py` and the role's
   Pydantic models; the code, not the model, decides what happens next
   (`jobtypes/chat.py` re-checks the chosen action against the asker's
   permissions and the thread's item before doing anything).
6. **Paid actions behind budget, provider and rate limits.** Before any model or
   picture call: `llm.is_configured()`, `budget.can_spend(workspace)` (the
   month's estimate from `AgentRun` rows), the workspace's automatic-work
   policy (`autopilot.automatic_work_blocker`), the chat daily cap
   (`chat.DAILY_REPLY_CAP`), `AGENCY_MAX_ACTIVE_BRIEFS` and
   `jobtypes/chat.MAX_ACTIVE_CHAT_POSTS`. Every view that starts paid work
   carries `@ratelimit`. A request already sent to a provider cannot be
   retracted: say so, never claim it was.
7. **Tasks never raise.** A `@background` task catches everything and records
   the outcome on the brief, job or row (`apps/studio/tasks.py`,
   `apps/blog/tasks.py`); recurring tasks are wrapped in `keep_schedule` and
   report trouble with `note_task_failure`, because a raising task is backed off
   and eventually deleted by django-background-tasks. One stage per task,
   re-checked under a row lock against the job's revision (`engine.run_step`,
   `pipeline.run_step`), so a stale stage never overwrites a person's later
   decision.
8. **New columns carry `db_default`.** A new field on a live table has both
   `default=` and `db_default=` (see `Routine` in `apps/studio/models.py`), so
   the web and worker services can run one release apart and old code can
   still insert rows. Migrations are additive; never reverse destructively as
   part of a release.
9. **No model identifiers in code or copy.** Model and vendor names live only
   in environment variables (`STUDIO_PROVIDER`, `STUDIO_MODEL`,
   `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `FAL_KEY`, `FAL_IMAGE_MODEL`) and
   in the provider adapters' defaults. Nothing user-facing names a model, a
   provider, a worker, an environment variable or a token count outside Set up
   (owners only) and *Details* disclosures. `apps/studio/tests/test_setup.py`
   bans `API_KEY`, `worker`, `operator`, `lead`, `FAL` and `administrator` in
   readiness copy; `test_chat_provider_readiness.py` bans `assistant`,
   `administrator` and `AI service` in the thread.

Also: secrets never enter logs or error messages (`apps/telegram/api.py`,
`apps/studio/openrouter.py`); every Telegram button is one-use and bound to
actor, chat, bot, workspace and snapshot (`apps/telegram/actions.py`); an
uncertain send or delivery is held for a person, never replayed.

## Module map

### Apps (`apps/`)

- `accounts` — users, login, Google sign-in, the `/` landing (`_workspace_landing`).
- `organizations`, `workspaces`, `members` — organisation → workspace → membership; roles, `effective_permissions`, `require_permission`.
- `settings_manager` — cascading workspace defaults (hashtags, first comments).
- `credentials` — encrypted platform credentials per organisation.
- `social_accounts` — connecting accounts, token health checks.
- `composer` — posts, platform posts, the ideas board, templates, categories, CSV import.
- `calendar` — the calendar, posting slots, queues, recurrence; the list view's Approvals tab.
- `approvals` — the gate (`gate.py`, `actor.py`), services, comments, reminders.
- `publisher` — the publish loop, confirmation, delivery holds and reconciliation.
- `inbox` — social inbox sync, replies, SLA, platform webhooks.
- `analytics` — metric sync and the Analytics pages.
- `media_library` — assets, variants, sweeps.
- `blog` — articles, the SEO score, covers, publishing to a website repository, Search Console.
- `client_portal` — magic links, the portal, Talk to the team, a client's own Telegram pairing.
- `notifications` — event types, in-app/email/webhook delivery, preferences, digests.
- `onboarding` — the checklist card on Home.
- `studio` — the agency (below).
- `telegram` — the Telegram transport (below).
- `api`, `api_keys`, `mcp`, `oauth_server` — the Agent API, its keys, the MCP server and its OAuth.
- `intelligence` — an optional hosted add-on; off unless all five of its variables are set.
- `marketing` — the public pages.
- `common` — encrypted fields, scoped managers, `background.py` (recurring tasks, the worker lease), the mail budget, the `release`, `live_verify`, `run_worker` and backup commands.
- `providers/` (top level) — one module per platform API.

### `apps/studio` — the agency

- `models.py` — `BrandProfile`; `StudioBrief` (a post in the making) and `StudioConcept`; `AgentRun` (one agent turn: tokens, cost); `AgencyJob` (every other kind of work); `AgencySettings` (autopilot, approvers, budget, creation mode); `BrandClaim`; `CampaignOutcome`; `AutopilotWeek`; `CreativeInsight`; `Conversation` and `Message`; `Routine` and `RoutineRun`.
- `views.py` — Home, create, the post page and its actions, the brand profile. `views_setup.py` — Set up and the Settings hub. `views_routines.py`. `views_agency.py` — Team and job pages. `views_autopilot.py`. `views_chat.py` — threads and inbox drafts. `views_memory.py`, `views_outcomes.py`, `views_trust.py`. `views_customer_workflow.py` — the older endpoints (redirect to Home). `opendots_views.py` — task controls.
- `dashboard.py` — Today, the tabs, the settings cards, waiting / at work / week / stats; queries only.
- `readiness.py` — the one readiness line; its copy never names a setting or a worker.
- `chat.py` — threads: who may write where, who answers, caps, posting, receipts, `REQUEST_KINDS`.
- `jobtypes/` — one module per `AgencyJob.Kind`: `chat`, `plan`, `blog`, `inbox`, `report`, `learn`, `repurpose`, `seo`; `jobs.py` collects them into `JOB_TYPES`.
- `engine.py` — runs an `AgencyJob` stage by stage with revision fencing: `create`, `enqueue`, `save`, `update_state`, `finish`, `fail`, `call` (one agent turn with its run record), `sweep_stuck`, `resume_paused_jobs`.
- `pipeline.py` — the ten-stage post pipeline; `scheduling.py` proposes a time; `qa.py` runs the code checks; `design.py` renders the graphic; `images.py` fetches the picture; `style.py` picks the look to follow.
- `roles/` — the agents' prompts by department; `base.py` has the preamble, `untrusted` and `ask`. `agents.py`, `prompts.py`, `schemas.py` serve the original four creative agents.
- `creative_brief.py`, `creative_sources.py` — intake fields and defaults; source evidence, its cache and its digest.
- `customer_workflow.py` — save and start an idea as its own thread; the In progress rows.
- `services.py` — what people may do with a brief: `approve`, `request_changes`, `new_angles`, `retry`, `discard`, `reopen`, `create_brief`, `start_planned`.
- `autopilot.py` — the 15-minute heartbeat and its gates; `routines.py` — the minute tick; `briefing.py` — the morning briefing; `alerts.py` — failures to the lead and backup.
- `budget.py`, `llm.py` (provider-aware calls and cost), `openrouter.py` (the second adapter), `team.py` (the one list of agents), `memory.py`, `performance.py`, `inbox_team.py`, `reports.py`, `trust.py`, `outcomes.py`, `opendots.py` (pause, resume, retry after review), `guards.py`, `tasks.py` (the background entry points), `brand_defaults.py`, `forms*.py`, `urls*.py`.

### `apps/telegram` — the transport

- `models.py` — `TelegramConnection` (one bot per workspace), `TelegramChat`, `TelegramUserLink` (a person's pairing), `TelegramPairing` (one-use codes), `TelegramChannel` and `TelegramChannelDelivery`, `TelegramUpdate` (inbound), `TelegramAction` (one-use buttons), `TelegramDelivery` (the outbox), `TelegramWorkflowPrompt`, `TelegramManagedBotReservation`.
- `webhooks.py` — ingress at `/webhooks/telegram/<connection id>/`: stores the update and queues `process_update`; never runs model or network work.
- `processing.py` — claims each update once; handles lifecycle events (group migration, bot removed); routes `callback_query` → `actions.handle_callback`, `message` → `workflow_bridge.handle_workflow_reply` and then `conversations.handle_message`, `managed_bot` → `managed`.
- `conversations.py` — commands and plain text in paired chats, bridged into the exact Studio thread.
- `actions.py` — issues and applies the one-use review, confirm and week buttons.
- `inbox.py` — the manager inbox: `tell`, `approvers`, quiet hours, the daily cap, `URGENT_EVENTS`.
- `notifications.py` — mirrors thread messages, brief cards, ready drafts, delivery receipts and `Notification`s into Telegram; `notification_event` dispatches by `event_type`.
- `outbox.py` and `channel_outbox.py` — encrypted, deduplicated sending with uncertain-send holds; `api.py` is the bounded Bot API client.
- `permissions.py`, `state.py`, `provisioning.py` (pairing, the webhook, the command menu), `managed.py` (consented bot creation), `uploads.py`, `weekly.py` (`/week`), `workflow_bridge.py`, `signals.py` (after-commit hooks), `tasks.py` (`run_telegram_cycle`), `views.py` with `templates/telegram/settings.html`.

## Naming rules for UI copy

- The section is **Agency**. The helpers are **your team** and **your manager**
  (the account manager). Not "AI Studio", "assistant", "operator", "CTO" or
  "agent" in user-facing text; the roster names agents by their job
  (copywriter, art director, scheduler).
- One sentence per screen on what to do. Status in words: "Waiting for you",
  "The team is working", "Paused: autopilot is off", "Needs your review".
- No environment-variable names, worker names, token counts, contrast ratios,
  model or provider names outside Set up (owners only) and *Details*
  disclosures. Readiness copy points to Set up instead.
- Buttons say the act: **Go ahead**, **Stop**, **Approve & schedule**,
  **Request changes**, **Run now**, **Open to approve**. Plain **Approve** does
  not schedule, and the copy never pretends it does.
- Never say or imply that something was published, scheduled or approved unless
  it was; a started idea is "started", a queued one "queued", a proposed time
  is a proposal.
- Telegram: one line per message; the caveats live in `/help` and the first
  pairing message; cards that act carry the one footer (`actions.FOOTER`).
- Times are shown in the workspace's timezone; dates in words.

## How to add things

### A job kind

1. Add the value to `AgencyJob.Kind` in `apps/studio/models.py` with a plain
   label (a choices-only migration; no new column).
2. Create `apps/studio/jobtypes/<kind>.py`. Each stage is a function
   `(job) -> next stage name | None` that reads and writes through
   `engine.save` / `engine.update_state` and ends with
   `engine.finish(job, result=…)`. Every model turn goes through `engine.call`
   or a role's `ask`, with every outside text wrapped by
   `roles.base.untrusted`. Define
   `JOB = engine.JobType(kind, stages=(engine.Stage("name", "agent_slug", fn), …), priority=…, stuck_after=…)`.
3. Register it in `apps/studio/jobs.py` (`JOB_TYPES`) and its agents in
   `apps/studio/team.py` (`jobs=(…)`) so the roster, the timelines and the cost
   estimate know them.
4. Queue it with `engine.create(workspace, kind, …)` from a view (behind
   `require_permission` and `@ratelimit`) or from `autopilot.run_cycle`, after
   `automatic_work_blocker` and `budget.can_spend`.
5. Decide what people see. Home's `dashboard.today` and `needs_review` already
   list jobs; add a branch in `apps/telegram/notifications.notification_event`
   if its result should reach the manager inbox; `alerts.job_failed` already
   covers failures.
6. Tests in `apps/studio/tests/` with a faked agent: the happy path, a failure
   that marks the job failed without raising, and a stale-revision write that
   is dropped.

### A routine kind

1. Add the value to `Routine.Kind` in `apps/studio/models.py`.
2. In `apps/studio/routines.py`: teach `_blocker` which gates apply (a kind
   built by code needs no provider or budget), add the branch in `_start`
   (create a `RoutineRun`, do the work or queue a job, set the lease when it
   runs as a job), and extend `settle_running` if the kind runs as a job. Keep
   the rule that an interrupted run is never retried on its own.
3. Add a preset to `SUGGESTIONS` if it deserves a one-tap card, and its wording
   to `templates/studio/routines.html`, `partials/routine_rows.html` and the
   `/routines` lines in `apps/telegram/conversations.py`.
4. Tests in `apps/studio/tests/test_routines.py`: due → started, blocked →
   skipped with a plain `last_error`, lease expired → interrupted and not
   restarted.

### A Telegram event route

Outbound — something new should reach the manager inbox or a thread's chats:

1. Make the event a `Notification` (`apps/notifications/models.EventType` plus
   the place that creates it) or a thread `Message`; `apps/telegram/signals.py`
   already queues both after commit.
2. In `apps/telegram/notifications.notification_event`, add the branch for the
   `event_type`: one short line (client-safe when the chat may be a client
   group), a stable `source_key` so retries never send twice, and a call to
   `inbox.tell(workspace, text, source_key=…, event=…, reply_markup=…, post=…)`.
   Add the event to `inbox.URGENT_EVENTS` only if it must get through quiet
   hours. Never include private content, costs or credentials.
3. If the event needs a button, issue it from `apps/telegram/actions.py` (bound
   to actor, chat, bot, workspace and snapshot) and apply it in
   `handle_callback`.

Inbound — a new command or button:

1. Commands: add the handler in `apps/telegram/conversations.handle_message`
   (and to `_CLIENT_COMMANDS` only if clients may use it); check authority with
   `permissions.fresh_member(link, "<permission>")`; answer in one line; do the
   work through the same Studio services the web uses, never a new path; add
   the command to `provisioning.BOT_COMMANDS`
   (`manage.py telegram_set_commands` republishes the menu).
2. Buttons: a new `TelegramAction.kind` in `actions.py`, issued with `_issue`
   and applied in `handle_callback` after `_binding` and a fresh permission
   check; anything that approves goes through `apps/approvals` so the gate
   applies.
3. Tests in `apps/telegram/tests/` with mocked Bot API responses: the happy
   path, a stale or foreign binding refused, and nothing sent twice for the
   same `source_key`.

## Documents

`docs/README.md` indexes the rest: `docs/PRODUCT_MAP.md` (pages, flows, what
runs on its own), `docs/LIVE_OPERATIONS.md` (production, the canonical
environment-variable table, verification, rollback), `docs/TELEGRAM_CLIENT_HUB.md`,
`docs/TELEGRAM_CHANNELS.md`, `docs/OPENDOTS_INTEGRATION.md`. Older status and
audit documents are kept, unchanged, under `docs/archive/`.
