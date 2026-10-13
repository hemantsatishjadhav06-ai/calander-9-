# SM Manager — live operations for Neopolis and More Space

Production: **https://sm-bean-production-eb50.up.railway.app** (Railway project
`sm-bean`, service `sm-bean` + `sm-bean-worker`, Postgres, Redis, bucket
`sm-bean-media`). Deploys from `main` of `hemantsatishjadhav06-ai/calander-9-`.

Updated 12 October 2026. The operating changes below are prepared locally;
their deployment to Railway and a real-provider pilot remain unverified.
Railway credentials and an authenticated production session are unavailable.
No actual production post was approved or published during this work.

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

The Agency conversation also distinguishes **Delivery outcome unknown** and
**Expired — needs review**. Those are durable holds, not ordinary retryable
failures. Human recovery requires account inspection and is bound to the exact
attempt/content; it does not send a post.

* Only a currently authorized internal approver **signed in to the dashboard** can approve. The Agent
  API, MCP clients, the client portal and background jobs can create drafts and
  submit them for review — never approve, never schedule unapproved content.
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

1. Open the brand workspace → **Publish** → **List** → **Approvals**.
2. Expand a post (**Details**) to see the preview for every destination: the
   exact text each channel will publish, its length against the platform
   limit, format, and media.
3. **Approve** (then schedule from the composer or calendar), or
   **Approve & schedule** to approve and put it on the calendar at its proposed
   time in one step. **Review** lets you request changes or reject with a
   comment.

### Scheduling and the calendar

* **Publish → Calendar** shows scheduled posts; **Drafts** lists drafts with
  their *Proposed* time (the seven-day plan); **Queue** lists what is scheduled;
  **Sent** lists published and failed posts. Inspect the Agency per-account
  receipt before recovery. An uncertain outcome requires checking the native
  account, while an expired time requires fresh review and future approval;
  neither permits an ordinary automatic resend.
* Dragging a post on the calendar as the approver approves the new time.

### Messages, comments and results

* **Social Inbox** — comments and DMs for connected Facebook Pages and
  Instagram accounts (polled every few minutes; real-time once Meta webhooks are
  set up, see below). Nothing is sent automatically; replies are yours.
* **Analytics** — Page and post insights from Meta once accounts are connected.
* X: publishing only. X's API is pay-per-use; the inbox and analytics never
  call it, so no credits are spent in the background.

## Blogs

**Blog** in the workspace sidebar. Write the post (title, slug, excerpt, body,
featured image, SEO title/description), **Preview** (signed-in only,
`noindex`), **Submit for approval**, **Approve**, then **Publish**.

* Drafts never leave SM Manager: nothing is committed to a website repository
  until the exact revision is approved, and edits after approval withdraw it.
* Publishing commits the post, its image and the updated blog index to the
  website repository in one commit and runs that site's deploy workflow:
  * Neopolis → `neopolis-site-deploy`: `publish-payload3/blog/…`, workflow
    `publish3.yml` (mirrors the live site, overlays the blog, ZIP-deploys).
  * More Space → `morespace-website`: `blog/…`, workflow `netlify-publish.yml`
    (same pattern).
* SM Manager then checks the live URL and records it, with the commit and the
  workflow run, on the post.
* **Create social drafts** turns an approved or published blog into social
  drafts, which go through approval like any other post.

## The agency

**Agency** in the workspace sidebar is the AI team's home: 28 agents in seven
departments (see **Agency → Team**). Everything they make waits for an owner or
manager under **Waiting for you** — nothing is approved, scheduled or
published by an agent, in any workspace.

* **Guided post creation**: use **Start guided post** on the agency home. Answer
  focused questions, inspect website/channel evidence, verified facts and photo
  provenance, then explicitly confirm the brief before creative work starts.
  Review the finished revision before **Approve & schedule**. Generation and
  delivery times are not guaranteed; **Publish now** acknowledges queueing.
* **Creative direction and memory**: choose brand/fresh style and keep, replace
  or clear the selected photo while revising. **Creative memory** separates
  designer-selected references from fresh measured performers. Measured rankings
  require recent successful captures and mature same-account history; a chosen
  design reference is inspiration, not evidence of results.
* **Autopilot** (**Agency → Autopilot**, workspace owners): set posts per
  week, the accounts, the content pillars and when to plan (Friday 16:00 by
  default, workspace time). The planner fills next week's open slots, the team
  makes every post, and the lead approver gets one notification when they are
  ready. Assign a different eligible backup for deadline reminders, checked
  every 15 minutes. Set a monthly soft budget; the team stops starting new work
  when recorded/estimated spend reaches it, but in-flight and external charges
  are not reserved or guaranteed to stay below an invoice ceiling.
* **Ask the team**: on the agency home and on every post. Ask a question or
  for a change and the account manager gets the right agent on it. Tick
  *Internal note* for a note clients never see. Clients have the same thread
  in the client portal (**Talk to the team**), where the weekly report is under
  **Reports**. Their requests still need internal approval.
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
5. **The agency** — for OpenRouter, set `STUDIO_PROVIDER=openrouter`,
   `OPENROUTER_API_KEY` securely, `STUDIO_MODEL=anthropic/claude-sonnet-4.5`,
   and `STUDIO_WEB_SEARCH=false` on **both** `sm-bean` and `sm-bean-worker`.
   Confirm the model is available to this OpenRouter account and has credits.
   Do not put an OpenRouter key in `ANTHROPIC_API_KEY`. Direct Anthropic remains
   available with `STUDIO_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`.
   The agents run in the worker. Verify `FAL_KEY` and actual image-service
   access, or supply an owner-attested project photo and inspect the explicit
   background fallback. Historical key presence does not establish current
   credits or successful generation. Enter current **Verified facts** with
   sources and expiry, and attest authentic project assets to their current
   file/project. Then open **Agency → Autopilot**, choose accounts, posts per
   week, pillars, lead, backup, soft budget and maximum delivery delay, and
   switch it on. The On badge is a saved setting, not live certification.
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

For the reviewed automation gaps, required activation evidence and real-platform
pilot, see [CTO agency readiness](CTO_AGENCY_READINESS.md).

## Checking the live deployment

The configured release uses `python manage.py release --setup-brands --verify`
before new code takes traffic. The deploy log of the `sm-bean` service contains
`live_verify:` lines — PASS / FAIL / BLOCKED (waiting on the owner) — covering
configuration, storage, the worker, both brand workspaces, every connected
account's identity (read-only API calls), workspace isolation, and the full
approval → publish path on a throwaway fixture that is rolled back (provider
stubbed; nothing is posted). Run it any time with
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
queued content/destinations. See [CTO readiness](CTO_AGENCY_READINESS.md).

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
