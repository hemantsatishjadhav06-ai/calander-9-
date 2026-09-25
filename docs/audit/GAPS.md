# Audit gap register

Every known gap in the product, in one place, with its status. Rounds 1–4
(security, brand, correctness, marketing, authorization, first-run UX) are
merged into the PR history; this file tracks what is still open and what
round 5 found. Update the status column as fixes land — a row is not "fixed"
until a test pins it.

Severity: **P0** exploitable or data-losing · **P1** breaks a core flow ·
**P2** wrong, confusing or slow · **P3** polish, docs, hygiene.

## Open — needs the owner (credentials, money, or a product call)

| # | Sev | Area | Gap | Status |
|---|-----|------|-----|--------|
| O1 | P1 | Deploy | No SMTP configured on Railway. Invites, client-portal magic links and password resets fail **silently**. | Owner: supply `EMAIL_HOST/PORT/USER/PASSWORD`, `DEFAULT_FROM_EMAIL` |
| O2 | P1 | Deploy | No S3 configured. Media lives on the container's ephemeral disk (wiped on redeploy) and social platforms cannot fetch a localhost URL, so media posts fail at publish time. | Owner: `STORAGE_BACKEND=s3` + `S3_*` |
| O3 | P2 | Deploy | `SUPPORT_EMAIL` unset, so the pricing/legal contact CTAs hide themselves. Deliberately not set to the owner's personal address. | Owner: choose a public address |
| O4 | P1 | Legal | `/terms/` and `/privacy/` are placeholders that say so. They are public and linked from signup. | Owner: reviewed legal text |
| O5 | P3 | Brand | Generated monogram stands in for a logo; the product name itself is a placeholder. | Owner decision |
| O6 | P2 | Security | OAuth token-at-rest hashing (`COMPLIANT_BCP_RFC9700_TOKEN_STORAGE`) deferred: it cannot read already-stored tokens, so it is a migration, not a flag flip. | Plan a cutover: rotate MCP connections |
| O7 | P3 | Ops | Database/service names in compose, CI and `render.yaml` still carry the previous brand. Renaming repoints live resources. | Leave, or do it with a documented data migration |
| O8 | P3 | Ops | `SENTRY_DSN` unset — no error monitoring in production. | Owner: create a Sentry project |
| O9 | P2 | Product | Monetization for the core product, product analytics — not started. | Owner decision |
| O10 | P1 | Deploy | **After this PR merges**, the Railway worker service's start command must change from `python manage.py process_tasks` to `python manage.py run_worker --duration 3600` (service `sm-bean-worker`). Until then the worker runs without SIGTERM handling, stale-lock recovery or schedule repair. Doing it before the merge would crash-loop the worker, because `main` does not have the command yet. | After merge: update the start command, redeploy, confirm "Worker ready" in the logs |

## Open — engineering

| # | Sev | Area | Gap | Evidence | Status |
|---|-----|------|-----|----------|--------|
| E5 | P3 | Deps | No lockfile: `requirements.txt` uses floating ranges, so each deploy resolves whatever is newest inside the range. Reproducibility and the E1–E3 pattern (a range that can never reach the fix) are the same problem. | `requirements.txt` | Open — consider `pip-compile` |
| E7 | P3 | Ops | `manage.py check --deploy` is not part of the deploy path. The custom checks in `apps/common/checks.py` only run when someone runs it by hand. | `railway.toml` | Open — add to the pre-deploy command once the live environment is confirmed to pass it (a failing check would block every deploy) |
| E9 | P3 | Ops | With more than one worker replica, `run_worker`'s boot-time lock release must be disabled (`--keep-locks`). Every shipped target runs one replica; documented in the README. | `apps/common/management/commands/run_worker.py` | Documented |
| F2 | P2 | A11y | Modals have no focus trap, most lack `role="dialog"`, several ignore Escape (invite modals, publish approvals, token reveal, composer ×12, settings, media library). Needs Alpine Focus + `x-trap` + roles across ~20 templates. | audit | Open |
| F4 | P2 | A11y | Body copy in `text-stone-400` / `--text-ghost` (≈2.6:1) at ~350 sites and `text-stone-300` at 36; labels and table headers included. Needs a palette pass: reserve those for icons, move copy to `--text-tertiary`. | audit | Open |
| F6 | P2 | Forms | Composer validation errors lose the field name (`Object.values(errors).flat()`), render in a toast without `role="alert"`, and vanish after 5s. | `compose.html:2722`, `composer/views.py:968` | Open |
| F7 | P2 | A11y | Inputs with no associated label (event form, categories, idea modal, inbox filter bar, composer ×10, create landing ×8, queues, posting slots, library search). | audit | Open |
| F8 | P2 | A11y | 63 icon-only buttons with no accessible name; toggles without `aria-expanded`. | audit | Open |
| F10 | P2 | Forms | Calendar event errors reach the user as raw JSON (`{"error": ...}`) through the global HTMX handler; an end date before the start is silently coerced. | `apps/calendar/views.py` event views | Open |
| F11 | P3 | Forms | Category create/edit rejects with a bare "Invalid data." | `composer/views.py:3254` | Open |
| F12 | P2 | Notifications | No unread-notification indicator anywhere: `notificationBell()` in `base.html` is never mounted (and uses the Alpine v2 `__x` API); the drawer partial targets a container no template has. | `base.html:996`, `notifications/partials/drawer.html` | Open — mount a bell in the header |
| F14 | P3 | UX | Idea modal: Save and Cancel look identical, no initial focus, failure is a `window.alert` that drops the server's reason. | `base.html:635`, `:1196` | Open |
| C6 | P2 | Concurrency | Web-side status writes (`_transition_or_skip`, chip endpoint, `_sync_platform_posts`, `_bulk_save_platform_posts`, `reschedule_post`) write in-memory state without re-checking the from-status in the WHERE clause; a hold placed while the engine claims the row can be overwritten. The engine's own writes are now guarded, which closes the resurrect-and-republish half of this. | `apps/approvals/services.py:53`, `apps/composer/views.py:1300`, `apps/calendar/views.py:1194` | Open — convert to `filter(id, status=<from>).update()` |
| C11 | P2 | Product | Disconnecting an account hard-deletes every PlatformPost, PublishLog, analytics snapshot, queue and posting slot on it, and single-target published posts. Now atomic and refused mid-publish, but a soft-disconnect (clear tokens, keep history) is a product decision. | `apps/social_accounts/views.py` `disconnect` | Owner decision |
| M18 | P3 | Perf | The onboarding checklist runs four existence queries on every authenticated page render. | `apps/onboarding/context_processors.py` | Open — cache per (user, workspace) briefly |
| M16 | P3 | Members | The org's daily invite budget is charged before the send; a failed send keeps the row and the spent slot. | `apps/members/services.py:144` | Open |

## Fixed in round 5

| # | Sev | Area | Gap | Commit | Test |
|---|-----|------|-----|--------|------|
| E1 | P0 | Deps | Pillow 10.4.0 — 33 pip-audit findings in the decoders this app feeds user uploads to. Pin forbade the fix. | 6f4b818 | full suite on 12.3.0 |
| E2 | P0 | Deps | Django 5.1.15 — 7 findings; 5.2 is the LTS. | 6f4b818 | full suite on 5.2.17 |
| E3 | P1 | Deps | cryptography 43.0.3 — 10 findings in the library that protects every stored OAuth token. | 6f4b818 | full suite on 49.0.0 |
| E4 | P3 | Deps | pytest 8.4.2 — 1 finding (dev-only). | 6f4b818 | — |
| E6 | P3 | API | Seven ninja views returned `(status, body)` tuples, deprecated in 1.x and removed in 2.0 (48 warnings per test run). | 6f4b818, this round | API suite emits none |
| W1 | P1 | Worker | **Worker ignored SIGTERM.** django-background-tasks binds SIGTSTP; every platform sends SIGTERM, so each deploy killed the task in flight. | this round | `test_worker_reliability` |
| W2 | P1 | Worker | **A killed worker left `run_publish_cycle` locked for an hour** (`MAX_RUN_TIME`) — an hour with no publishing after every crash or deploy, nothing in the logs. `run_worker` releases stale locks on boot. | this round | `test_boot_releases_locks_a_dead_worker_left` |
| W3 | P1 | Worker | **A raising recurring task backed off `attempts**4+5`s and was deleted at 25 attempts**, turning "every 15 seconds" into "never" — silently, until the next release's `migrate`. Every recurring task now runs under `keep_schedule`; the worker re-registers missing schedules on boot. | this round | `KeepScheduleTests`, `test_boot_puts_back_a_schedule_the_library_deleted` |
| W4 | P2 | Worker | Two processes registering the same schedule at once (web start-up migrate racing the worker) could both insert it. Registration now runs under a Postgres advisory lock. | this round | `ConcurrentRegistrationTests` |
| I1 | P1 | Inbox | **SLA notification storm.** Each poll `update_or_create`'d `extra` wholesale, wiping `sla_notified`, so every overdue message re-alerted every owner and manager every cycle. `extra` is now merged. | this round | `test_a_repoll_keeps_sla_notified` |
| I2 | P1 | Inbox | A display name over 255 characters was a Postgres `DataError` that aborted the account's poll; a long name in a notification title did the same in `notify()`. Both cut to the column; one bad message no longer aborts the SLA sweep. | this round | `test_an_overlong_display_name_is_stored_not_raised`, `test_a_long_title_is_cut_to_the_column`, `test_one_bad_message_does_not_stop_the_sweep` |
| I3 | P1 | Webhooks | `@ratelimit(key="ip")` behind Railway's edge keyed on the edge's address: **one 60/min bucket shared by Meta, YouTube, Resend and any abuser**. Keyed on the trusted-proxy client IP. | this round | `TestRateLimitKey` |
| I4 | P2 | Webhooks | A non-ASCII signature header was a 500 (`compare_digest` on str) in the Meta, YouTube and Resend receivers. Compared as bytes. | this round | `*_non_ascii_signature_is_403_not_500` |
| I5 | P2 | Webhooks | A signed-but-malformed Meta body (a list, a non-dict entry) was a 500, which Meta retries with backoff and eventually disables the subscription over. | this round | `test_a_signed_but_malformed_body_is_not_a_500` |
| I6 | P2 | Webhooks | The YouTube hub GET echoed the challenge for **any** `hub.mode`, confirming unsubscribe intents on our behalf; its POSTs filed the channel's own uploads as inbox comments from "YouTube". | this round | `TestYouTubeHub` |
| I7 | P2 | Inbox | Backlog messages (already overdue when first synced) alerted every owner and manager on the first sync. Flagged silently now. | this round | `test_a_backlog_message_is_flagged_without_an_alert` |
| I8 | P2 | Inbox | A member removed from a workspace kept its messages assigned to them, hidden from everyone's "unassigned" view. Unassigned on membership removal. | this round | `TestAssignmentsFollowMembership` |
| I9 | P2 | Inbox | Any inbox user could discard a teammate's draft reply. Author or `reply_from_inbox` only. | this round | `TestDiscardingDrafts` |
| I10 | P3 | Inbox | SLA target of 0 minutes was accepted (every message instantly overdue). `MinValueValidator(1)` + migration 0005. | this round | `test_zero_minutes_is_rejected` |
| I11 | P3 | Inbox | Double-clicking Send posted a reply twice. `hx-disabled-elt` on both send buttons. | this round | — (template) |
| N1 | P2 | Notifications | Switching digest mode off with rows queued flushed unbatched event types through `BATCH_HEADINGS[event_type]` → `KeyError` → rows retried until reaped, **emails lost**. Generic heading fallback. | this round | `test_a_flushed_digest_of_an_unbatched_type_has_a_heading` |
| N3 | P3 | Notifications | Turning the **in-app** channel off for an event type still showed those notifications in the bell, drawer, history and badge: the row is created for every event (email and webhook hang off it). New `shown_in_app` flag set by `notify()`; the five in-app query sites filter on it. Migration 0006. | this round | `test_in_app_off_keeps_the_bell_quiet_but_still_emails` |
| N2 | P2 | Notifications | Outbound webhook signatures were keyed with `SECRET_KEY` itself when `WEBHOOK_SECRET` was unset — the key that signs sessions and password-reset tokens, handed to third parties to attack offline. Derived key now. | this round | `test_webhook_signatures_never_use_secret_key_directly` |
| S1 | P2 | Security | SSRF check allowed shared address space 100.64.0.0/10 (CGNAT), where cloud providers put internal services. `is_global` added. | this round | `test_shared_address_space_is_not_public` |
| D1 | P2 | Deploy | `CONN_MAX_AGE` was 0: a fresh TCP + TLS + auth handshake to Postgres per request. Now 60s with health checks. | this round | settings smoke test |
| D2 | P2 | Deploy | No SMTP timeout: a hung mail server held a password-reset request or the digest sweep open forever. `EMAIL_TIMEOUT=10`. | this round | — |
| D3 | P2 | Deploy | No Railway health check, so a broken build took traffic. `healthcheckPath=/health/` + `healthcheck.railway.app` allowed automatically when `RAILWAY_ENVIRONMENT` is set. | this round | settings smoke test |
| D4 | P3 | Deploy | No `.dockerignore`: a local build copied `.git`, the venv, `node_modules`, test media and any `.env` into image layers. | this round | — |
| D5 | P3 | Deploy | Dockerfile CMD was shell form, so Gunicorn was not PID 1 and SIGTERM stopped at `sh`. Exec form. | this round | — |
| D6 | P3 | Data | Migration 0015's reverse used `prefetch_related(...).iterator()` without `chunk_size`, which silently ignores the prefetch: one query per post. | this round | — |
| D7 | P3 | Docs | README, Procfile, compose, Render and Railway configs all name the worker command consistently (`run_worker`). | this round | — |
| C1 | P0 | Composer | **Cross-tenant publish.** Autosave bound any account UUID to a post; Schedule then published workspace A's content through workspace B's channel with B's token. Accounts resolved through the workspace; the engine's due and retry queries also refuse a channel from another workspace. | this round | `AutosaveScopingTests`, `TenantGuardTests` |
| C2 | P1 | Publisher | The retry loop claimed rows on state read minutes earlier and blindly wrote `publishing`, publishing posts the user had unscheduled or held meanwhile. Guarded claim on the row's current state. | this round | `test_a_row_unscheduled_during_the_loop_is_not_published` |
| C3 | P1 | Publisher | A retry fired on its backoff time even after the post was moved a week out. Retries now also wait for the (new) scheduled time. | this round | `test_a_retry_waits_for_a_later_schedule` |
| C4 | P1 | Calendar | **Recurrence was dead code**: the composer wrote rules nothing consumed; had it run, dedup by caption would have duplicated posts after any edit, and monthly stepping drifted the 31st to the 28th. Registered hourly under `keep_schedule`; per-rule `generated_dates` ledger; one transaction per occurrence; dates computed from the base; a held source generates nothing. | this round | `RecurrenceTests` |
| C5 | P1 | Composer | Deleting a child or post mid-publish let the engine's later full-row saves re-insert the deleted row or publish a post the user removed. Delete refuses `publishing`; the engine's retry and confirm writes use `update_fields` (no INSERT fallback). | this round | `DeleteProtectsInFlightTests` |
| C7 | P2 | Composer | The chip endpoint accepted `published`/`publishing` targets (faking a publish) and moves out of `publishing` (double post). Whitelisted; nothing leaves `publishing` by hand; scheduling a child pins its time so a cancelled sibling cannot strand it. | this round | `TransitionEndpointTests` |
| C8 | P2 | Composer | Schedule bypassed the approval gate every other path enforces, and the draft hop lifted a client hold. Without `publish_directly`, Schedule is a review request unless the post is approved; `on_hold` never hops through draft. | this round | `ScheduleGateTests` |
| C9 | P2 | Publisher | A rate-limited publish burned the whole retry ladder inside the window. Retries now wait for `window_resets_at`. | this round | `RateLimitRetryTests` |
| C10 | P2 | Accounts | Disconnect deleted posts and the account in separate statements outside a transaction, and would delete a row mid-publish. Atomic; refused while a post is publishing. | this round | — |
| C12 | P2 | Accounts | Two threads refreshing one channel's rotating refresh token: the loser persisted an invalidated token and every scheduled post on the account then failed. Refresh runs under `select_for_update`, adopting a refresh another caller just completed. | this round | full suite |
| C13 | P3 | Accounts | The health check wrote the token columns back unconditionally, overwriting a reconnect that landed during its network calls. Token fields saved only when the check rotated them. | this round | — |
| C14 | P3 | Composer | `PostVersion` numbering used `count()+1` (a gap → IntegrityError → 500); now `Max+1`. Deselecting a channel left its queue entry behind; removed with the row. | this round | `VersionNumberingTests` |
| M1 | P0 | Media | **The orphan sweep deleted library uploads** after 14 days, storage object included, no trash. Restricted to composer scratch uploads. | this round | `OrphanSweepScopeTests` |
| M2 | P1 | Members | An org admin could remove an owner (with two present) or a fellow admin. | this round | `RemoveMemberHierarchyTests` |
| M3 | P1 | Media | Stored XSS: a folder name with a quote ran as script in every member's browser (Alpine expression interpolation + `unsafe-eval`). Names via `data-*`. | this round | `FolderNameInjectionTests` |
| M4 | P1 | Members | A user in two orgs got a random one per request; the org owning the current workspace wins, then the oldest. | this round | `OrgResolutionTests` |
| M5 | P1 | Media | Image/video edits never reached `asset.file`, so every post published the original. Edits replace the file; the original is kept as version 1. | this round | `EditsReachThePublishedFileTests` |
| M6 | P1 | Media | Upload over the storage quota was a 500 on the library page. | this round | `test_over_quota_is_reported_not_a_500` |
| M7 | P2 | Analytics | HTML views ignored `view_analytics`. | this round | `AnalyticsPermissionTests` |
| M8 | P2 | Members | Accepting an invitation naming a deleted workspace was a 500 with the org membership half-applied. | this round | `test_a_deleted_workspace_in_the_assignments_is_skipped` |
| M9 | P2 | Members | A failed resend invalidated the link the invitee already had. | this round | `test_a_failed_resend_keeps_the_old_link_valid` |
| M10 | P2 | Onboarding | "Invite your team" only ticked for a client. | this round | `test_inviting_an_editor_completes_the_team_item` |
| M11 | P2 | Onboarding | A revoked connection link could page every owner and manager, unlimited. | this round | `test_a_revoked_link_cannot_page_the_team` |
| M12 | P2 | Members | Assigning a built-in role left a custom role's grants in force. | this round | `CustomRoleTests` |
| M13–M17, M19, M20 | P3 | Media/Members/Onboarding | Junk `?folder=`/`?uploader=`/API dates 500; nonsense trim ranges; reflected errors unescaped; invitee address unvalidated; junk `expiry_days` 500; dead `hx-get` on the folder tree; duplicate root folder names. | this round | `UploadAndFilterEdgeTests`, `test_a_malformed_address_is_refused`, `test_junk_expiry_days_falls_back` |
| F1 | P1 | Inbox | Saved replies could not be created or edited from the UI: the New/edit links rendered a page with no form and no list. | this round | `SavedRepliesPageTests` |
| F5 | P2 | Responsive | Drafts and Sent tables were clipped at 375px with no way to scroll. | this round | — |
| F9 | P2 | Forms | Double-submit on nine HTMX forms (comments, events, categories, queues, folders, both invite modals, posting slots, workspace assignments). | this round | — |
| F3 | P2 | A11y | Hover-revealed controls (`group-hover:opacity-100`, `group-hover:flex`) were invisible to keyboard users at 18 sites across 13 templates; they now also appear on `group-focus-within`. | this round | — |
| F13, F15, F16 | P3 | UX/A11y | Empty states with no next step; Django messages not announced (`role="status"`/`alert`); client-invite modal's inline error slot never used. | this round | — |

## Fixed in rounds 1–4 (for the record)

Security: trusted-proxy rate-limit (CIDR), DNS-rebind SSRF pinning, constant-time webhook compare, real `/health/`, deploy-time checks, five RFC 9700 OAuth flags, **cross-tenant comment-delete IDOR**, viewer-reachable destructive views (posts, media, queues, categories, templates, workspace rename, status transitions), API media folder scoping.

Correctness: atomic `save_post`, N+1 in categories/queues/calendar, hard-delete in one transaction, revoke magic link wired, Google error messages readable, **ghost posts** (no-channel guard, channel-less drafts visible), dead token flags the account, client hold on scheduled posts.

Brand/marketing: configurable `SITE_NAME` everywhere, mascot retired, false "no paid tier" and hosted-version claims corrected, AGPL §13 link, sitemap.

UX: branded error pages, WCAG-AA contrast token, SEO meta, HTMX loading bar, six orphan pages linked, sidebar advertises only connectable platforms, POST-only logout, client roster hidden from external clients, placeholder settings page removed.

Deployment: `ENCRYPTION_KEY_SALT`, `APP_URL`, `SITE_NAME`, `BB_TRUSTED_PROXIES` set; worker service created and verified processing.
