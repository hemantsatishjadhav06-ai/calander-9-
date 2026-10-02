# SM Manager — live operations for Neopolis and More Space

Production: **https://sm-bean-production-eb50.up.railway.app** (Railway project
`sm-bean`, service `sm-bean` + `sm-bean-worker`, Postgres, Redis, bucket
`sm-bean-media`). Deploys from `main` of `hemantsatishjadhav06-ai/calander-9-`.

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

* Only an owner/manager **signed in to the dashboard** can approve. The Agent
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
  **Sent** lists published and failed posts with the error and a retry option.
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

## Checking the live deployment

Every release runs `python manage.py release --setup-brands --verify` before the
new code takes traffic. The deploy log of the `sm-bean` service then contains
`live_verify:` lines — PASS / FAIL / BLOCKED (waiting on the owner) — covering
configuration, storage, the worker, both brand workspaces, every connected
account's identity (read-only API calls), workspace isolation, and the full
approval → publish path on a throwaway fixture that is rolled back (provider
stubbed; nothing is posted). Run it any time with
`python manage.py live_verify`.

## Rollback

The release step takes a database backup **before** migrating
(`backups/db-<timestamp>.tar.gz` in the media bucket; the log names it).

1. **Code only (normal case):** Railway → `sm-bean` → Deployments → the previous
   successful deployment → **Rollback**; do the same for `sm-bean-worker`. This
   release's migrations only *add* columns (nullable or with database
   defaults), so the previous code runs against the migrated database as is.
2. **Turn the gate off without a deploy:** Settings → Approvals → untick
   *Require dashboard approval* (owner only). Posts keep their approvals.
3. **Data restore (only if data was damaged):** with the matching code deployed,
   run on the web service
   `python manage.py restore_database backups/db-<timestamp>.tar.gz --yes-wipe-data`.
   This replaces current data with the backup.
4. **Websites:** Netlify → the site → Deploys → pick the previous deploy →
   **Publish deploy**. Blog posts can also be removed by reverting their commit
   in the website repository and re-running its publish workflow.
