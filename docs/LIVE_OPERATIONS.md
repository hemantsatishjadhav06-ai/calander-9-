# SM Bean — live operations for Neopolis and More Space

Production: **https://sm-bean-production-eb50.up.railway.app** (Railway project
`sm-bean`, service `sm-bean` + `sm-bean-worker`, Postgres, Redis, bucket
`sm-bean-media`). Deploys from `main` of `hemantsatishjadhav06-ai/calander-9-`.

Updated 23 October 2026. This document describes the code on `main`. Whether a
given deployment runs it, and whether its credentials work, is established by
`python manage.py live_verify` on that deployment and by the Set up page, not
by this document. No production post was approved or published while writing
it. For what every page does see the [product map](PRODUCT_MAP.md); for the
engineering rules see [`CLAUDE.md`](../CLAUDE.md).

## The two brand workspaces

| | Neopolis | More Space |
|---|---|---|
| Website | https://www.neopolisinfra.com (Netlify `neopolis-infra`, `47e0a5cc-…`) | https://morespace.netlify.app (Netlify `morespace`, `964e086b-…`) |
| Facebook Page | "Neopolis Infra" — Graph Page id `585141221346435`, profile URL id `61595008380228` | "More Space" — Graph Page id `1282011328339050`, profile URL id `61577172604485` |
| Instagram | @neopolis_infra | @morespacehyd |
| X | @neopolisinfra | @morespaceai |
| Timezone | Asia/Kolkata | Asia/Kolkata |
| Approval | required, dashboard-enforced | required, dashboard-enforced |

`python manage.py setup_brands` creates/reuses both (idempotent; runs on every
release). The approver is `BRAND_APPROVER_EMAIL` if set, otherwise the
organization owner who signed in most recently — the deploy log names who it
picked (masked). Set `BRAND_APPROVER_EMAIL` on the `sm-bean` service to pin it.

## How approval works (enforced workspaces)

Draft → **Awaiting approval** (`pending_review`) → **Approved** → **Scheduled** →
Publishing → **Published** or **Failed**.

The post's thread also distinguishes **Delivery outcome unknown** and
**Expired — needs review**. Those are durable holds, not ordinary retryable
failures. Human recovery requires account inspection and is bound to the exact
attempt/content; it does not send a post.

* Only a currently authorized internal approver **signed in to the dashboard**,
  or acting through a verified one-use Telegram review button when the
  workspace has switched that on, can approve. The Agent API, MCP clients, the
  client portal and background jobs can create drafts and submit them for
  review — never approve, never schedule unapproved content.
* An approval covers the exact text, title, first comment, media files (and
  their order and alt text), each channel's own wording and format, the
  destination account, and the publish time. It is recorded with who, when,
  the version number and a fingerprint (Approvals history and the `ApprovalAction`
  audit table).
* Any change to those withdraws the approval and puts the post back in
  *Awaiting approval*. Moving the time is fine when you do it in the dashboard
  (that is you approving the new time); anyone or anything else moving it needs
  a fresh approval.
* The publisher checks the approval again under a row lock before claiming a
  post, on every retry, and once more on freshly read data immediately before
  calling the platform. A post that fails the check is not sent; it lands in
  **Sent → Failed** with the reason.
* Duplicate publishing is prevented by the claim: a row moves from `scheduled`
  to `publishing` in one guarded statement, so concurrent workers, double clicks
  and retries cannot both send it.

### Approving content

1. Open the brand workspace → **Approvals** in the sidebar (the Calendar's list
   view, Approvals tab), or the post's own page from Home's *Waiting for you*,
   or the review card in your paired Telegram chat.
2. Expand a post (**Details**) to see the preview for every destination: the
   exact text each channel will publish, its length against the platform
   limit, format, and media.
3. **Approve** (then schedule from the composer or calendar), or
   **Approve & schedule** to approve and put it on the calendar at its proposed
   time in one step. **Review** lets you request changes or reject with a
   comment.

### Scheduling and the calendar

* **Calendar** shows scheduled posts; its list view's **Drafts** tab lists
  drafts with their *Proposed* time, **Queue** what is scheduled, **Sent**
  published and failed posts. Inspect the per-account receipt on the post's
  page before any recovery. An uncertain outcome requires checking the native
  account, while an expired time requires fresh review and future approval;
  neither permits an ordinary automatic resend.
* Dragging a post on the calendar as the approver approves the new time.

### Messages, comments and results

* **Inbox** — comments and DMs for connected Facebook Pages and Instagram
  accounts (polled every five minutes; real-time once Meta webhooks are set
  up, see below). Nothing is sent automatically; replies are yours, including
  the ones the team drafts.
* **Analytics** — Page and post insights from Meta once accounts are connected.
* X: publishing only. X's API is pay-per-use; the inbox and analytics never
  call it, so no credits are spent in the background.

## Blogs

**Blog & SEO** in the workspace sidebar. Write the post (title, slug, excerpt,
body, featured image, SEO title/description) or have the team write it,
**Preview** (signed-in only, `noindex`), **Submit for approval**, **Approve**,
then **Publish**.

* Drafts never leave SM Bean: nothing is committed to a website repository
  until the exact revision is approved, and edits after approval withdraw it.
* Publishing commits the post, its image and the updated blog index to the
  website repository in one commit and runs that site's deploy workflow:
  * Neopolis → `neopolis-site-deploy`: `publish-payload3/blog/…`, workflow
    `publish3.yml` (mirrors the live site, overlays the blog, ZIP-deploys).
  * More Space → `morespace-website`: `blog/…`, workflow `netlify-publish.yml`
    (same pattern).
* SM Bean then checks the live URL and records it, with the commit and the
  workflow run, on the post.
* **Make social posts** turns an approved or published article into social
  drafts, which go through approval like any other post.

## The agency

**Home** is the conversation with your team: say what you want, your manager
answers with a brief, and the team makes the post, which waits under *Waiting
for you* until a person approves it. The whole product is described page by
page in the [product map](PRODUCT_MAP.md); the short version for operators:

* **Set up** (sidebar) is the one checklist: AI team, Pictures, Social
  accounts, Approvers, Autopilot, Creation mode, Telegram, Email, Verified
  facts, Blog website, Monthly AI budget. Each row shows its live state and the
  one button that fixes it. Owners see the variable names there; everyone else
  is told to ask the owner. The same line sits under the Home greeting.
* **Routines** (Agency tab) are standing instructions on a schedule: the
  morning briefing, a Monday plan, replies to new comments every evening. They
  run by themselves to the minute, skip a run when the workspace, the provider
  or the budget says no, and never retry an interrupted run without a person.
* **Autopilot** (Settings → Autopilot, settings managers): posts per week,
  accounts, pillars, when to plan (Friday 16:00 workspace time by default),
  articles per month, inbox drafts, the lead and backup approvers and the
  monthly soft budget. The planner fills next week's open slots, the team makes
  every post, and the lead approver hears once when they are ready. The On
  badge is a saved setting, not live certification; the Set up line says when
  automatic work has not run recently.
* **Telegram** (Settings → Telegram): one bot per workspace. Paired approvers
  get a review card or an *Open to approve* preview for every finished draft,
  reminders, a planned week, failed deliveries, the weekly report and the
  morning briefing in their private chat, with quiet hours (22:00–07:00
  workspace time), a daily cap and `/mute`. Plain text in that chat is an
  instruction to the manager. See [Telegram](TELEGRAM_CLIENT_HUB.md).
* **Ask the team**: on Home and on every post. Ask a question or for a change
  and the account manager gets the right agent on it. Tick *Internal note* for
  a note clients never see. Clients have the same thread in the client portal
  (**Talk to the team**), where the weekly report is under **Reports**. Their
  requests still need internal approval.
* **Inbox drafts**: with *Draft replies to comments, messages and reviews* on in
  Autopilot (or **Draft replies with the team** in the inbox), new comments and
  reviews get a drafted reply in the inbox, labelled with the agent that
  wrote it. A person sends it; unhappy reviews are flagged.
* **Blog**: **Write with the team** on the blog list turns a topic into a full
  article (keyword, outline, article, fact check, SEO title and description, a
  designed cover). The editor's **SEO score** lists every check with its fix;
  *Improve SEO* sends the article back to the SEO team. Connect **Google
  Search Console** on the blog list to see positions, clicks and searches per
  article; **Run an SEO check-up** suggests what to refresh.
* **Creative direction and memory**: choose brand/fresh style and keep,
  replace or clear the selected photo while revising. **Creative memory**
  separates designer-selected references from measured performers. Measured
  rankings require recent successful captures and mature same-account history;
  a chosen design reference is inspiration, not evidence of results.
* **Costs**: every agent turn is recorded with an estimated cost. The budget is
  a soft pre-call threshold: the team stops starting new work when the month's
  estimate reaches it, but in-flight and external charges are not reserved or
  guaranteed to stay below an invoice ceiling.

Nothing the team makes is approved, scheduled or published by an agent, in any
workspace, from any channel.

## One-time owner setup (still needed)

1. **Connect accounts** — in each brand workspace: Settings → Social accounts
   → Connect → Facebook (pick that brand's Page; the picker marks it and flags
   the other brand's Page), then Instagram. Meta must list these redirect URIs
   (Meta app → Facebook Login → Settings → Valid OAuth Redirect URIs):
   `https://sm-bean-production-eb50.up.railway.app/social-accounts/callback/facebook/`
   and `…/callback/instagram/`. While the Meta app is in Development mode, the
   connecting Facebook user must have a role on the app.
2. **Blog publishing token** — create a fine-grained GitHub token with
   *Contents: read and write* and *Actions: read and write* on
   `neopolis-site-deploy` and `morespace-website`, and set it as
   `BLOG_GITHUB_TOKEN` on the `sm-bean` service. More Space also needs a
   `NETLIFY_TOKEN` repository secret in `morespace-website`.
3. **X (optional, paid)** — create an app at console.x.com (OAuth 2.0, Web
   App, callback `…/social-accounts/callback/x/`), buy API credits, set
   `PLATFORM_X_CLIENT_ID` / `PLATFORM_X_CLIENT_SECRET`, then connect @neopolisinfra
   and @morespaceai.
4. **Real-time Meta webhooks (optional)** — set `FACEBOOK_WEBHOOK_VERIFY_TOKEN`
   on the service, then in the Meta app → Webhooks subscribe
   `…/webhooks/facebook/` with the same token (Page: feed, messages; Instagram:
   comments, messages).
5. **The agency** — on **both** `sm-bean` and `sm-bean-worker` set
   `STUDIO_PROVIDER` and the matching key (`OPENROUTER_API_KEY` or
   `ANTHROPIC_API_KEY`; never one provider's key in the other's variable), and
   `FAL_KEY` for pictures; leave `STUDIO_MODEL` empty for the provider's
   default. Then open the workspace's **Set up** page: it says in words whether
   the AI team and Pictures rows are done, and `live_verify` reports
   `agency.provider` and `agency.fal_key`. Key presence does not establish
   credits or a successful generation; the first real draft does. Enter current
   **Verified facts** with sources and expiry, attest authentic project photos,
   then use Set up → Autopilot (**Turn on with sensible defaults**) or Settings
   → Autopilot to choose accounts, posts per week, pillars, lead, backup and
   the soft budget.
6. **LinkedIn Company Pages** — at developer.linkedin.com create an app tied to
   a Company Page, add the **Community Management API** product (LinkedIn
   reviews it), and list the redirect URLs
   `https://sm-bean-production-eb50.up.railway.app/social-accounts/callback/linkedin_company/`
   and `…/callback/linkedin_personal/`. Set `PLATFORM_LINKEDIN_COMPANY_CLIENT_ID`
   / `PLATFORM_LINKEDIN_COMPANY_CLIENT_SECRET` on both services, then in each
   brand workspace Connect → LinkedIn (Company Page) and pick that brand's Page.
   The connecting LinkedIn member must be an admin of the Page. If LinkedIn
   answers that a scope isn't authorized, see README → LinkedIn → "Scopes must
   match the app".
7. **Sign in with Google (optional)** — Google Cloud Console → Credentials →
   OAuth client ID (Web application) with the redirect URI
   `https://sm-bean-production-eb50.up.railway.app/accounts/google/login/callback/`;
   set `GOOGLE_AUTH_CLIENT_ID` / `GOOGLE_AUTH_CLIENT_SECRET` on `sm-bean`. The
   instance stays invite-only: a Google address needs an invitation or a
   `SIGNUP_ALLOWLIST` entry (for example `@neopolisinfra.com`) to get an account.
8. **Google Search Console (optional)** — in Google Cloud Console enable the
   *Google Search Console API*, create an OAuth client ID (Web application)
   with the redirect URI
   `https://sm-bean-production-eb50.up.railway.app/blog/search-console/callback/`,
   and set `GSC_CLIENT_ID` / `GSC_CLIENT_SECRET` on both services. Then on
   each brand's blog list choose **Connect Google Search Console** with a Google
   account that can see that website's property.
9. **Telegram** — set `TELEGRAM_WEBHOOK_BASE_URL` to the public origin on both
   services, deploy, confirm a wrong-secret POST to the webhook route returns
   403, then set `TELEGRAM_WEBHOOK_READY=true`. Connect the bot token in
   Settings → Telegram, pair yourself, and switch **Approvals from Telegram**
   on if you want to approve from your phone. See
   [Telegram](TELEGRAM_CLIENT_HUB.md).

## Environment variables

The one canonical list. "Service" says where the value must be set: **web**
(`sm-bean`), **worker** (`sm-bean-worker`) or **both** (the same value on each;
a value the worker lacks shows up as work that silently never happens).
"Verify" names the page or `live_verify` check that proves it works; key
presence alone proves nothing. `.env.example` carries every variable's full
comment.

### Core

| Variable | Service | Required | How to verify |
|---|---|---|---|
| `SECRET_KEY` | both | required | `manage.py check --deploy`; sessions survive a redeploy |
| `ENCRYPTION_KEY_SALT` | both (same value) | required; never rotate casually | tokens still decrypt: `live_verify accounts.connected`, `credentials.*` |
| `DEBUG` | both | required, `false` | `live_verify config.debug` |
| `ALLOWED_HOSTS`, `APP_URL`, `CSRF_TRUSTED_ORIGINS` | both | required | `live_verify config.app_url`, `config.oauth_callbacks`; the login page loads over https |
| `APP_DOMAIN`, `POSTGRES_PASSWORD`, `CADDY_MEDIA_ROOT` | Compose only | required on a VPS | Caddy obtains the certificate; uploads load |
| `BB_TRUSTED_PROXIES` | web | optional (behind a proxy you run) | `live_verify config.https_behind_proxy`; one person's failed logins do not lock out everyone |
| `DATABASE_URL`, `DB_CONN_MAX_AGE` | both | required | `live_verify db.connection`, `db.migrations` |
| `REDIS_URL` | both | required in multi-process production | rate limits and OAuth state hold across processes |
| `SIGNUP_MODE`, `SIGNUP_ALLOWLIST`, `ACCOUNT_EMAIL_VERIFICATION` | web | optional (invite-only by default) | a stranger cannot register; an allowlisted address can |
| `ADMIN_URL` | web | optional | the admin answers at that path only |
| `SITE_NAME`, `SUPPORT_EMAIL`, `SOURCE_URL`, `LEGAL_ENTITY_NAME`, `LEGAL_UPDATED`, `LEGAL_TERMS_URL`, `LEGAL_PRIVACY_URL` | web | optional | the footer and the legal pages |
| `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_SAMPLE_RATE`, `SENTRY_PROFILES_SAMPLE_RATE` | both | optional | an event arrives in Sentry |
| `MALLOC_ARENA_MAX` | both | optional (memory) | see README → Production Deployment |

### Storage and media

| Variable | Service | Required | How to verify |
|---|---|---|---|
| `STORAGE_BACKEND` | both | required (`s3` on any host with an ephemeral disk) | `live_verify storage.round_trip` |
| `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET_NAME`, `S3_CUSTOM_DOMAIN`, `S3_REGION_NAME`, `S3_ADDRESSING_STYLE`, `AWS_S3_MAX_MEMORY_SIZE` | both | required with `s3` | `live_verify storage.round_trip`; an uploaded picture renders on the post page |
| `MEDIA_ROOT`, `SERVE_MEDIA`, `MEDIA_STORAGE_PERSISTENT` | both | required with `local` | `live_verify config.durable_media`; a platform can fetch an attachment URL |

### Email

| Variable | Service | Required | How to verify |
|---|---|---|---|
| `EMAIL_BACKEND_TYPE`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | both | required before inviting people | Set up → Email (owners); `/ops/email/` sends a test |
| `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` | web | optional (send through a Gmail account from `/ops/email/`) | Set up → Email shows "connected" |
| `RESEND_WEBHOOK_SECRET` | web | optional | delivery events are recorded |

### Sign-in and platform credentials

| Variable | Service | Required | How to verify |
|---|---|---|---|
| `GOOGLE_AUTH_CLIENT_ID`, `GOOGLE_AUTH_CLIENT_SECRET` | web | optional | the Sign in with Google button appears; `live_verify login.page` |
| `PLATFORM_FACEBOOK_APP_ID`, `PLATFORM_FACEBOOK_APP_SECRET`, `PLATFORM_FACEBOOK_CONFIG_ID` | both | per platform used | `live_verify credentials.facebook`; Settings → Social accounts → Connect |
| `PLATFORM_INSTAGRAM_APP_ID`, `PLATFORM_INSTAGRAM_APP_SECRET` | both | per platform used | `live_verify credentials.instagram` |
| `PLATFORM_THREADS_APP_ID`, `PLATFORM_THREADS_APP_SECRET` | both | per platform used | `live_verify credentials.threads` |
| `PLATFORM_LINKEDIN_COMPANY_CLIENT_ID`, `PLATFORM_LINKEDIN_COMPANY_CLIENT_SECRET`, `PLATFORM_LINKEDIN_PERSONAL_CLIENT_ID`, `PLATFORM_LINKEDIN_PERSONAL_CLIENT_SECRET`, `PLATFORM_LINKEDIN_COMPANY_SCOPES`, `PLATFORM_LINKEDIN_PERSONAL_SCOPES` (legacy `PLATFORM_LINKEDIN_CLIENT_ID`/`_SECRET`) | both | per platform used | `live_verify credentials.linkedin`, `credentials.linkedin_company` |
| `PLATFORM_TIKTOK_CLIENT_KEY`, `PLATFORM_TIKTOK_CLIENT_SECRET`, `PLATFORM_GOOGLE_CLIENT_ID`, `PLATFORM_GOOGLE_CLIENT_SECRET`, `PLATFORM_PINTEREST_APP_ID`, `PLATFORM_PINTEREST_APP_SECRET` | both | per platform used | Settings → Social accounts → Connect succeeds |
| `PLATFORM_X_CLIENT_ID`, `PLATFORM_X_CLIENT_SECRET` | both | optional, paid | `live_verify credentials.x` |
| `FACEBOOK_WEBHOOK_VERIFY_TOKEN`, `INSTAGRAM_LOGIN_WEBHOOK_VERIFY_TOKEN`, `YOUTUBE_WEBHOOK_SECRET` | web | optional (real-time inbox) | `live_verify webhooks.meta` |
| `UNSPLASH_ACCESS_KEY` | web | optional | stock search in the composer |

### The agency

| Variable | Service | Required | How to verify |
|---|---|---|---|
| `STUDIO_PROVIDER` | both | required for the team | Set up → AI team; `live_verify agency.provider`, `agency.team` |
| `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY` | both | one of them, matching `STUDIO_PROVIDER` | Set up → AI team; the first draft arrives |
| `STUDIO_MODEL`, `STUDIO_EFFORT`, `STUDIO_TIMEOUT`, `STUDIO_FALLBACKS` | both | optional | the Team page shows agents finishing; the job timeline shows durations |
| `STUDIO_WEB_SEARCH` | both | optional (billed per search) | `live_verify agency.web_research` |
| `AGENCY_MAX_ACTIVE_BRIEFS` | worker | optional | Home's *In progress* never shows more briefs working than this |
| `FAL_KEY`, `FAL_IMAGE_MODEL` | both | optional (pictures) | Set up → Pictures; `live_verify agency.fal_key`; a post gets a generated picture |
| `BRAND_APPROVER_EMAIL` | web (release) | optional | the `setup_brands` line in the deploy log |

### Blog

| Variable | Service | Required | How to verify |
|---|---|---|---|
| `BLOG_GITHUB_TOKEN` | both | required to publish articles | Set up → Blog website; `live_verify credentials.blog_github`, `blog.publish_ready` |
| `GSC_CLIENT_ID`, `GSC_CLIENT_SECRET` | both | optional | **Connect Google Search Console** on the blog list succeeds |
| `INDEXNOW_KEY` | both | optional | `live_verify blog.indexnow` |

### Telegram

| Variable | Service | Required | How to verify |
|---|---|---|---|
| `TELEGRAM_WEBHOOK_BASE_URL` | both | required for Telegram | Settings → Telegram → *Deployment ready*; `live_verify telegram.webhook` |
| `TELEGRAM_WEBHOOK_READY` | both | `true` once the route answers 403 to a wrong secret | same row; *Bot connected* shows ✓ after connecting |
| `TELEGRAM_MANAGED_BOTS_ENABLED` | both | optional | the Advanced section offers managed creation when a manager bot can do it |
| `TELEGRAM_UPDATE_MAX_BYTES` | web | optional | oversized updates are refused |
| `TELEGRAM_UPDATE_RETENTION_DAYS`, `TELEGRAM_DELIVERY_RETENTION_DAYS`, `TELEGRAM_ACTION_RETENTION_DAYS`, `TELEGRAM_PAIRING_RETENTION_DAYS` | worker | optional | old payloads are cleared by `run_telegram_cycle` |

### Publisher and background work

| Variable | Service | Required | How to verify |
|---|---|---|---|
| `PUBLISHER_STALE_PUBLISHING_TIMEOUT`, `PUBLISHER_PUBLISH_CONFIRM_TIMEOUT`, `PUBLISHER_UNCONFIRMED_TIMEOUT` | worker | optional | a killed publish ends as a visible failure within the timeout |
| `PUBLISHER_MAX_CONCURRENT_PUBLISHES`, `PUBLISHER_MAX_CONCURRENT_POSTS`, `PUBLISHER_MAX_CONCURRENT_PLATFORM_PUBLISHES` | worker | optional (a Postgres connection budget) | no connection-limit errors in the worker log |
| `WEBHOOK_SECRET` | both | optional | receivers verify `X-Signature-256` |

### Optional integrations

| Variable | Service | Required | How to verify |
|---|---|---|---|
| `MCP_PUBLIC_BASE_URL`, `MCP_OAUTH_ISSUER_URL` | web | optional (split app/api hosts) | `/.well-known/oauth-authorization-server` names the public origin |
| `INTELLIGENCE_INTERNAL_URL`, `INTELLIGENCE_PUBLIC_URL`, `STUDIO_DEPLOYMENT_ID`, `STUDIO_SHARED_SECRET`, `STUDIO_BASE_URL` | both | all five or none | the Intelligence item appears in the sidebar |

`RAILWAY_ENVIRONMENT*` and `RAILWAY_GIT_COMMIT_SHA` are set by the platform and
only read.

## Checking the live deployment

The configured release uses `python manage.py release --setup-brands --verify`
before new code takes traffic. The deploy log of the `sm-bean` service contains
`live_verify:` lines — PASS / FAIL / BLOCKED (waiting on the owner) — covering
configuration, storage, the worker, both brand workspaces, every connected
account's identity (read-only API calls), workspace isolation, Telegram, and
the full approval → publish path on a throwaway fixture that is rolled back
(provider stubbed; nothing is posted). Run it any time with
`python manage.py live_verify`.

**Default verification is best effort:** FAIL/BLOCKED output does not by itself
stop the release. Opt in to the critical launch gate with:

```bash
python manage.py live_verify --strict
python manage.py release --setup-brands --strict-verify
```

These are alternatives: `--strict-verify` implies verification and stops on
critical failed/unverified checks. Strict verification requires task-specific
recent success, an eligible active agency and recent recorded model/delivery
evidence; skipping account checks remains blocked. Optional blog/X/LinkedIn
setup is separate from the critical Meta pilot. A human-attested receipt is
recorded evidence, not an independent provider lookup. Inspect its verification
type, native account and permalink. Fixture checks and strict success do not
certify real graphics, credits, a delivery SLA or the complete live pilot.

Before the first singleton-lease rollout, pause and drain the old baseline
worker: that code does not participate in the new lease. Reserve one extra
PostgreSQL connection for the worker's dedicated session lease. Deploy the same
reviewed code to both services, apply every new migration and start one
`python manage.py run_worker` process with an appropriate restart policy.
An overlapping new worker must fail before clearing task locks. `--keep-locks`
opts out of the singleton lease; do not use it as an overlap workaround without
a separately tested multi-worker plan. Verify publisher, agency and confirmation
success individually after restart, and obtain fresh approvals for affected
queued content/destinations. The October rollout runbooks and audits are kept
in [the archive](archive/2026-10/TELEGRAM_RAILWAY_ROLLOUT.md).

## Rollback

The release step takes a database backup **before** migrating
(`backups/db-<timestamp>.tar.gz` in the media bucket; the log names it).

Do not assume older code is safe merely because it can read the migrated
database. Reverting to `05ca828` removes source/expiry guards, durable
uncertain-delivery holds and the worker lease. Never turn approval enforcement
off as a recovery shortcut.

1. **Pause and drain first:** stop automatic generation and drain/stop the worker
   before changing either service. Keep approval enforcement on. Record every
   in-flight, unknown, expired and held destination with its native identity,
   attempt and content. Inspect accounts before any retry; stopping a process
   does not prove a platform write failed.
2. **Choose a reviewed compatible rollback:** prefer a fix or version retaining
   the new guards. Verify both services, migration compatibility and unresolved
   parent-post holds. Keep older code's publisher disabled if it cannot enforce
   those holds. Do not clear them, bulk-restamp approvals, or allow automatic
   resend to restore a green status.
3. **Preserve data:** additive schema does not justify destructive reverse
   migrations. Keep claim/outcome/heartbeat/hold records and audit history.
   Restore a database only for confirmed damage under a separately approved
   recovery plan, after taking a current backup and accounting for external
   social writes since the selected backup. A restore replaces current data and
   cannot undo already published posts; never run it as a routine code rollback.
4. **Resume deliberately:** inspect held/unknown outcomes through the human
   recovery controls, review current facts/content and approve fresh future
   times where needed. Restart one compatible worker and confirm each required
   task's success. Complete a controlled delivery check before unattended work.
5. **Websites:** a reviewed previous Netlify deploy or website commit can restore
   site content. Verify the resulting live canonical URL and existing social
   links; reverting a site does not reconcile or remove social publications.
