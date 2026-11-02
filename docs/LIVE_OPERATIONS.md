# SM Bean — live operations for Neopolis and More Space

Production (from 2 November 2026): **https://sm-bean.netlify.app**, the Netlify
site `sm-bean`, which proxies every request to the Render web service
`sm-bean-web` (with `sm-bean-worker`, Postgres `sm-bean-db` and Key Value
`sm-bean-cache`, all in Singapore). Render deploys `main` of
`hemantsatishjadhav06-ai/calander-9-` once GitHub's checks pass. See
[Render with Netlify in front](#render-with-netlify-in-front-from-2-nov-2026).

Previous deployment, stopped: **https://sm-bean-production-eb50.up.railway.app**
(Railway project `sm-bean`, service `sm-bean` + `sm-bean-worker`, Postgres,
Redis, bucket `sm-bean-media`). Where a section below names Railway, its
service names or that address, it describes the previous deployment.

Updated 2 November 2026. This document describes the code on `main`. Whether a
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

## Render with Netlify in front (from 2 Nov 2026)

The address people use is **https://sm-bean.netlify.app**. That Netlify site
serves nothing itself: every request is proxied to the Render web service
`sm-bean-web`. Render also runs the one worker (`sm-bean-worker`: publishing,
the agency, Telegram), Postgres 16 (`sm-bean-db`, plan `basic-256mb`) and Key
Value (`sm-bean-cache`), all in Singapore, because the workspaces are in
Asia/Kolkata. Both services deploy `main` only after GitHub's checks pass
(`autoDeployTrigger: checksPass`). Everything Render creates is described in
[`render.yaml`](../render.yaml); the front door is [`deploy/netlify`](../deploy/netlify).

```
visitor ──https──▶ Netlify (sm-bean.netlify.app) ──https, signed──▶ Render proxy ──▶ sm-bean-web (gunicorn)
                                                                       sm-bean-worker ──▶ sm-bean-db, sm-bean-cache
```

### 1. Create the Render services

Merge the branch into `main` first: the Blueprint reads `render.yaml` from
`main`. Then open

https://dashboard.render.com/blueprint/new?repo=https://github.com/hemantsatishjadhav06-ai/calander-9-

give the Blueprint a name, leave every field the form asks for **blank**, and
choose **Deploy Blueprint**. Nothing typed there is needed for the first boot:
`check --deploy` passes with warnings only (email, Sentry, the agency's keys,
and W015 for the bucket that does not exist yet), `migrate` runs, and the web
service answers `/health/`. Whether Render leaves a blank value out or creates
it empty, the app reads it as not set and uses its default
(`tests/test_render_blueprint.py` boots both services both ways). Note the web
service's address on its page (normally `https://sm-bean-web.onrender.com`;
Render adds a suffix when the name is taken). It is the `RENDER_ORIGIN` of
step 2.

The values in `render.yaml` written as `value:` are fixed by the file: the
public address (`APP_URL`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`,
`TELEGRAM_WEBHOOK_BASE_URL`), `DEBUG=false`, `BB_TRUSTED_PROXIES=10.0.0.0/8`,
`STORAGE_BACKEND=s3`, `MEDIA_STORAGE_PENDING=true`, `S3_REGION_NAME=auto` and
`S3_ADDRESSING_STYLE=path`. A Blueprint sync puts them back, so change them in
the file, not in the dashboard. Render sets `RENDER_EXTERNAL_HOSTNAME` itself;
the app allows that hostname, trusts it for CSRF and answers a request under it
as `sm-bean.netlify.app`.

**Values left blank, copied from Railway through the API.** Copy each onto
`sm-bean-web`. The worker is linked to every one of them (`fromService` in
`render.yaml`), but Render's documentation does not say whether such a link
follows a value changed later through the API or copies it once when the
Blueprint syncs, so the two services are compared after the copy (below).

* `SECRET_KEY` and `ENCRYPTION_KEY_SALT`: overwrite the generated values with
  Railway's. The salt must match the data, or connected accounts' tokens no
  longer decrypt.
* `SENTRY_DSN`, `SITE_NAME`, `SUPPORT_EMAIL`, `LEGAL_ENTITY_NAME`,
  `WEBHOOK_SECRET`, `SIGNUP_MODE`, `SIGNUP_ALLOWLIST`,
  `ACCOUNT_EMAIL_VERIFICATION`, `ADMIN_URL`, `ADMIN_ALLOWED_IPS`.
* Email: `EMAIL_BACKEND_TYPE`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`,
  `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL`,
  `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`,
  `RESEND_WEBHOOK_SECRET`.
* Sign-in and platforms: `GOOGLE_AUTH_CLIENT_ID`, `GOOGLE_AUTH_CLIENT_SECRET`,
  every `PLATFORM_*` pair in `render.yaml`, `FACEBOOK_WEBHOOK_VERIFY_TOKEN`,
  `INSTAGRAM_LOGIN_WEBHOOK_VERIFY_TOKEN`, `YOUTUBE_WEBHOOK_SECRET`,
  `UNSPLASH_ACCESS_KEY`.
* The agency and the blog: `STUDIO_PROVIDER`, `STUDIO_MODEL`,
  `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `FAL_KEY`, `BLOG_GITHUB_TOKEN`,
  `GSC_CLIENT_ID`, `GSC_CLIENT_SECRET`, `INDEXNOW_KEY`.

A variable Railway has that `render.yaml` does not list (a tuning knob such as
`PUBLISHER_*`, `EMAIL_DAILY_SEND_LIMIT` or `STUDIO_TIMEOUT`) keeps its default
on Render. Copy one only if Railway's value differs from the default, and then
onto **both** services, since the worker cannot read a variable `render.yaml`
does not link.

**Never copy from Railway:** `APP_URL`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`,
`BB_TRUSTED_PROXIES`, `DATABASE_URL`, `REDIS_URL`, `PORT`, `DEBUG`,
`DJANGO_SETTINGS_MODULE`, `STORAGE_BACKEND`, any `S3_*` or `MEDIA_*` value (the
Railway bucket; R2 replaces it in step 3), `TELEGRAM_WEBHOOK_BASE_URL`,
`TELEGRAM_WEBHOOK_READY` (set in step 5), `MCP_PUBLIC_BASE_URL`,
`MCP_OAUTH_ISSUER_URL` (both default to `APP_URL`), and anything starting with
`RAILWAY_`.

Values set through the API take effect on the next deploy: deploy both
services afterwards (Manual Deploy → Deploy latest commit, or the API's deploy
endpoint). Then, from the web service's **Shell** tab,
`python manage.py check --deploy` should show no error, only the warnings for
what is still to come.

**Check that the worker has the same values**, before the data move and before
the worker runs against Railway's data. Run this in the **Shell** tab of
`sm-bean-web` and of `sm-bean-worker`; it prints a short fingerprint of the
keys, never the keys themselves:

```bash
python manage.py shell -c "import hashlib; from django.conf import settings as s; print(hashlib.sha256('|'.join(str(v) for v in (s.SECRET_KEY, s.ENCRYPTION_KEY_SALT, s.ANTHROPIC_API_KEY, s.OPENROUTER_API_KEY, s.FAL_KEY)).encode()).hexdigest()[:12])"
```

The last line each prints must be the same twelve characters. If they differ,
the worker still holds the generated `SECRET_KEY` and `ENCRYPTION_KEY_SALT`
and the empty provider keys: it could not decrypt the restored connected
accounts, and what it encrypted the web service could not read. Run a manual
sync of the Blueprint (Blueprints → the Blueprint → **Manual Sync**), deploy
the worker and compare again. If they still differ, the links copy once: set
every value copied above on `sm-bean-worker` as well, deploy it and compare
once more, and from then on change a value on both services. (Reading both
services' variables through the API, `GET /v1/services/<id>/env-vars`, is the
other way to compare.)

**Moving the data.** The keys above only matter with Railway's data. With the
worker suspended (`sm-bean-worker` → Settings → Suspend; its fingerprint
above matched the web service's), restore Railway's
database into `sm-bean-db` from a machine whose Postgres client is at least
as new as Railway's server, using the same client for both commands:
`pg_dump --format=custom --no-owner --no-acl "<Railway public DATABASE_URL>" -f sm-bean.dump`,
then `pg_restore --clean --if-exists --no-owner --no-acl -d "<sm-bean-db External Database URL>" sm-bean.dump`.
Redeploy `sm-bean-web` (Manual Deploy → Deploy latest commit; `migrate` runs
again) and resume the worker. The restored database still names the old
address in Django admin → *Sites* (the domain in allauth's emails): set it to
`sm-bean.netlify.app`. Media files stay in Railway's bucket until they are
copied into R2 (step 3), for example with `rclone copy`; until then the
pictures of existing posts do not show.

`sm-bean-db` has no `ipAllowList` in `render.yaml`, so its external address
accepts connections from anywhere (protected by its password) for the
`pg_restore` above. Once the data is in, close it: add `ipAllowList: []` under
`sm-bean-db` in `render.yaml` (only Render's private network may connect) and
merge it, or remove the `0.0.0.0/0` rule under the database's **Networking**
in the dashboard. Open it again the same way for a later dump from outside.

Render looks for the port the web service listens on when it starts, and its
probes may arrive with `Host: localhost:10000`. Django logs each as
`Invalid HTTP_HOST header` (`DisallowedHost`); that is noise, not an attack and
not a fault.

### 2. Point the Netlify site at Render

On the Netlify site `sm-bean`: **Project configuration → Build & deploy →
Continuous deployment**: link this repository, branch `main`, **Base
directory** `deploy/netlify` (the build command and publish directory come from
`deploy/netlify/netlify.toml`). **Project configuration → Environment
variables**, add:

* `RENDER_ORIGIN` = the web service's address from step 1, e.g.
  `https://sm-bean-web.onrender.com`. The build refuses anything but a plain
  https origin.
* `FRONT_DOOR_SIGNING_SECRET` = a long random value (`openssl rand -hex 32`),
  marked as containing a secret, with scopes including **Runtime**. Set the
  same value on `sm-bean-web` (Render → Environment). Netlify signs each
  proxied request with it (`X-Nf-Sign`); without it the app cannot tell one
  visitor from another (see *Client addresses* below).

Then **Deploys → Trigger deploy**. A change to either variable needs another
deploy. Check: `curl -sI https://sm-bean.netlify.app/health/` answers `200`, and
the login page loads with its assets.

**Then check that a visitor cannot choose their own address.** The design
assumes Netlify replaces any `X-Nf-Client-Connection-Ip` a visitor sends with
the address it saw. Confirm it once after the first deploy, and again after a
change to the Netlify site. From your own computer:

```bash
curl -4 -s https://api.ipify.org; echo         # your public IPv4 address
curl -4 -s -o /dev/null -w '%{http_code}\n' -X POST https://sm-bean.netlify.app/accounts/login/ \
  -H 'X-Nf-Client-Connection-Ip: 203.0.113.77'
```

The POST answers `403` (it carries no CSRF token), but the login throttle has
counted it under the address the app believed. In `sm-bean-web`'s **Shell**,
with your address in place of `<yours>`:

```bash
python manage.py shell -c "import hashlib; from django.core.cache import cache; n = lambda ip: cache.get('auth_ratelimit:' + hashlib.md5(ip.encode()).hexdigest()); print('yours', n('<yours>'), 'forged', n('203.0.113.77'))"
```

* `yours 1` (or more) and `forged None`: correct.
* `forged 1`: Netlify passed the visitor's header through, so anyone could
  pick their rate-limit bucket and the address in the audit rows. Remove
  `FRONT_DOOR_SIGNING_SECRET` from `sm-bean-web` and deploy it: every visitor
  is then counted under the Netlify address that reached Render (coarse, but
  not forgeable) until this is resolved.
* `yours None` and `forged None`: the signature did not verify, so the
  request was counted under Netlify's address. The two
  `FRONT_DOOR_SIGNING_SECRET` values differ, or the Netlify one lacks the
  **Runtime** scope.

What reaches the app, and why it works:

* **Host.** Netlify sends the Render service's own name as `Host` and sends no
  `X-Forwarded-Host` (it strips one a client sends), so `USE_X_FORWARDED_HOST`
  stays off. `apps.common.middleware.FrontDoorHostMiddleware` answers a request
  under `RENDER_EXTERNAL_HOSTNAME` as `sm-bean.netlify.app`, so absolute URLs
  (OAuth redirect URIs, onboarding links, the sitemap) name the public address.
  Only that one hostname is mapped, and only to `APP_URL`'s host.
* **https.** Netlify connects to Render over https and Render's proxy sets
  `X-Forwarded-Proto: https`, which `SECURE_PROXY_SSL_HEADER` reads.
* **CSRF.** The browser's `Origin` is `https://sm-bean.netlify.app`, which is
  in `CSRF_TRUSTED_ORIGINS` and is also the host the request is answered as.
* **Client addresses.** Netlify's supported header for the visitor's address
  is `X-Nf-Client-Connection-Ip`. An `X-Forwarded-For` may also arrive on a
  proxied request (Netlify sends one, by community reports, but promises
  nothing about it), and the app does not rely on it. Render's proxy, the
  socket peer, connects from its private network
  (`BB_TRUSTED_PROXIES=10.0.0.0/8`) and appends the address it saw, which for
  every visitor is one of Netlify's, so the nearest untrusted hop in
  `X-Forwarded-For` is always Netlify's, whatever was written before it. The
  app believes `X-Nf-Client-Connection-Ip` only on a request whose `X-Nf-Sign`
  verifies with `FRONT_DOOR_SIGNING_SECRET` (HS256, issuer `netlify`, not
  expired); `apps.common.net.front_door_client_ip`. The `*.onrender.com`
  address is public, so anyone can send both headers to it directly; without
  the secret they cannot sign them, and such a request is bucketed by the
  address Render's proxy saw. Login lockouts, rate limits, the admin allowlist
  and API audit rows all use this one address.
* **Caching.** Netlify caches a proxied response only when it says so
  (`Cache-Control: public, max-age=…`). Pages say nothing or `private`, so
  only the hashed static files are cached at the edge.
* **When Render is down** Netlify shows its own error page. It offers no custom
  page for a failed proxy (a site's `404.html` serves only missing static
  files, which a forced catch-all never reaches), so none is configured.

**Netlify gives up on a proxied request after 26 seconds**, while the app keeps
working on it. These requests can take longer:

* Uploads through the app, which travel through Netlify whole:
  `/workspace/<id>/media/upload/`, `/workspace/<id>/compose/upload-media/`,
  `/workspace/<id>/compose/thumbnail-upload/`, `/workspace/<id>/ideas/upload-media/`
  and `/organizations/media/upload/`. A large video on a slow connection is
  cut; the person sees an error and nothing is saved.
* The composer's frame picker, the first time for a video
  (`/workspace/<id>/compose/media-filmstrip/<asset>/` downloads the whole
  video and runs ffmpeg eight times; cached afterwards) and a long single
  response from `/workspace/<id>/compose/media-stream/<asset>/`.
* Unsplash import (`/workspace/<id>/compose/unsplash-import/`): up to ten
  photos, each up to 40 seconds.
* The blog's **Generate picture** (`/workspace/<id>/blog/<post>/generate-image/`),
  which waits for the picture service for up to `FAL_TIMEOUT` (90 seconds by
  default). If the browser shows an error, reload the editor: the picture is
  usually attached a little later.
* Long calls to the Agent API and MCP (`/api/v1/…`, `/api/v1/mcp`).

For a very large upload, the web service's own address works as well (sign in
there separately; it is a different site to the browser).

### 3. Cloudflare R2 for media

Until the bucket exists the app runs with uploads refused (`check --deploy`
warns with W015; `live_verify` fails `config.durable_media` and its storage
check). In the Cloudflare dashboard:

1. **R2 object storage → Overview → Create bucket**. Name `sm-bean-media`;
   location: a location hint of **Asia-Pacific**; default storage class
   Standard. **Create bucket**. Leave public access off: the app hands out
   signed links that expire after an hour.
2. **R2 object storage → Overview**, under **Account Details**: note the
   **Account ID**, then choose **Manage** next to **API Tokens** →
   **Create Account API token**. Name `sm-bean`; permission **Object Read &
   Write**; **Apply to specific buckets only** → `sm-bean-media`; TTL forever.
   **Create Account API token**, then copy the **Access Key ID** and the
   **Secret Access Key** (shown once).
3. On `sm-bean-web` (Render → Environment) set:

| Variable | Value |
|---|---|
| `S3_ENDPOINT_URL` | `https://<account id>.r2.cloudflarestorage.com` |
| `S3_BUCKET_NAME` | `sm-bean-media` |
| `S3_ACCESS_KEY_ID` | the token's Access Key ID |
| `S3_SECRET_ACCESS_KEY` | the token's Secret Access Key |
| `S3_REGION_NAME` | `auto` (already set by `render.yaml`) |
| `S3_ADDRESSING_STYLE` | `path` (already set by `render.yaml`) |

Save, then deploy both services so they read the values (the worker through
`fromService`; if step 1's comparison showed that the links do not follow
changes, set the four on `sm-bean-worker` as well). Check:
`python manage.py live_verify` in the web service's Shell reports
`storage.round_trip` PASS, and an uploaded picture shows on the post page.

Once uploads work, change `MEDIA_STORAGE_PENDING` to `"false"` in
`render.yaml` and merge it. While it says `"true"`, a deployment that later
loses `S3_BUCKET_NAME` by mistake keeps running and quietly refuses uploads
(only W015 in the deploy log and `live_verify` say so); with `"false"`,
`check --deploy` stops that deploy with E004 (the web service's pre-deploy
step fails and the version already running keeps serving). The
price: a Blueprint created afresh from the file then needs the four values
above typed into its form (`tests/test_render_blueprint.py` follows the file
either way).

### 4. OAuth callback URLs for the new address

Add each at the provider (keep the Railway ones until Railway is gone). Every
path below is on `https://sm-bean.netlify.app`. The client connection links
(`/onboarding/…`) are needed only where clients connect their own accounts.

| Provider (where) | Paths |
|---|---|
| Google sign-in (Google Cloud → Credentials → the OAuth client of `GOOGLE_AUTH_CLIENT_ID` → Authorized redirect URIs) | `/accounts/google/login/callback/`; if email is sent through Gmail (`/ops/email/`), also `/ops/email/callback/` on the client of `GMAIL_CLIENT_ID` (the same client unless it is set) |
| Search Console (the OAuth client of `GSC_CLIENT_ID`) | `/blog/search-console/callback/` |
| YouTube and Google Business Profile (the OAuth client of `PLATFORM_GOOGLE_CLIENT_ID`) | `/social-accounts/callback/youtube/`, `/social-accounts/callback/google_business/`, `/onboarding/connect/callback/youtube/`, `/onboarding/connect/callback/google_business/` |
| Meta: Facebook Login (Meta app → Facebook Login → Settings → Valid OAuth Redirect URIs) | `/social-accounts/callback/facebook/`, `/social-accounts/callback/instagram/`, `/onboarding/connect/callback/facebook/`, `/onboarding/connect/callback/instagram/` |
| Meta: Instagram API with Instagram Login (`PLATFORM_INSTAGRAM_APP_ID`; Business login settings → OAuth redirect URIs) | `/social-accounts/callback/instagram_login/`, `/onboarding/connect/callback/instagram_login/` |
| Meta: Threads (`PLATFORM_THREADS_APP_ID`; Threads use case → Settings → Redirect Callback URLs) | `/social-accounts/callback/threads/`, `/onboarding/connect/callback/threads/` |
| Meta webhooks (Meta app → Webhooks, same verify tokens) | `/webhooks/facebook/`, `/webhooks/instagram_login/` |
| LinkedIn (developer.linkedin.com → the app → Auth → Authorized redirect URLs) | `/social-accounts/callback/linkedin_company/`, `/social-accounts/callback/linkedin_personal/`, `/onboarding/connect/callback/linkedin_company/`, `/onboarding/connect/callback/linkedin_personal/` |
| TikTok (TikTok for Developers → the app → Login Kit → Redirect URI) | `/social-accounts/callback/social1/`, `/onboarding/connect/callback/social1/` (TikTok refuses a path containing its name, hence `social1`) |
| Pinterest (developers.pinterest.com → the app → Redirect URIs) | `/social-accounts/callback/pinterest/`, `/onboarding/connect/callback/pinterest/` |
| X (console.x.com → the app → User authentication settings → Callback URI) | `/social-accounts/callback/x/`, `/onboarding/connect/callback/x/`; Website URL `https://sm-bean.netlify.app` |

Also: Mastodon registers itself with each instance on first connect; if the
database came from Railway, delete the rows under Django admin → *Mastodon app
registrations* so the next connect registers the new address. Resend (if used)
posts delivery events to `/webhooks/resend/`, and a YouTube push subscription
(if one was made) to `/webhooks/youtube/`. MCP connectors (Claude and others)
were issued by the old address and connect again once.

### 5. Telegram on the new address

`TELEGRAM_WEBHOOK_BASE_URL` is already `https://sm-bean.netlify.app`. Confirm
the route answers a wrong secret with 403:
`curl -s -o /dev/null -w '%{http_code}\n' -X POST https://sm-bean.netlify.app/webhooks/telegram/00000000-0000-0000-0000-000000000000/ -H 'X-Telegram-Bot-Api-Secret-Token: wrong'`
prints `403` (any id answers 403 to a wrong secret, so this proves the route
reaches the app through Netlify). Then set `TELEGRAM_WEBHOOK_READY=true` on `sm-bean-web`, and in each
workspace with a bot open **Settings → Telegram** and press **Retry webhook**:
it registers the webhook on the new address with Telegram and republishes the
command menu (`python manage.py telegram_set_commands` republishes the menu
alone). *Bot connected* shows ✓ when Telegram accepted it.

### 6. Verify

From the web service's **Shell** tab:

```bash
python manage.py check --deploy
python manage.py live_verify            # add --strict for the launch gate
```

`live_verify` prints PASS / FAIL / BLOCKED lines (see *Checking the live
deployment* below). On Render the pre-deploy step runs `check --deploy` and
`migrate` only; it neither backs up nor runs `live_verify`, so run it after
each deploy that matters. Also check from a browser: sign in at
https://sm-bean.netlify.app, connect or refresh one account, and open the
Activity page to see the worker's heartbeat.

### Rollback on Render

The general rules under [Rollback](#rollback) apply: pause and drain first,
keep approval enforcement on, never reverse migrations destructively.

* **Code:** the service's **Deploys** page → a previous successful deploy →
  **Rollback** → **Rollback to this deploy**. Do it on `sm-bean-web` and
  `sm-bean-worker` alike, so both run the same code. A dashboard rollback turns
  automatic deploys off (Settings turns them on again); it reuses that deploy's
  environment variables, and it does not undo a migration.
* **Database:** `sm-bean-db` → **Recovery**. Render keeps point-in-time
  recovery for paid databases (3 days on a Hobby workspace, 7 on Pro); a
  recovery creates a new database, which the services then point at. Export a
  logical backup there before a risky migration.
* **The address:** Railway is stopped, not deleted. Until it is removed, going
  back means starting its services again and moving the OAuth callbacks and the
  Telegram webhook back; data written on Render since the move stays on Render.
* **The front door:** a failed Netlify deploy never goes live. To undo a bad
  one, revert the commit and let Netlify build again.

## One-time owner setup (Railway, the previous deployment)

For Render, the callback URLs and steps are in
[Render with Netlify in front](#render-with-netlify-in-front-from-2-nov-2026).

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
a value the worker lacks shows up as work that silently never happens). On
Render the web service is `sm-bean-web`, and the worker is linked to every
variable `render.yaml` lists on it, so "both" means setting it on
`sm-bean-web`, then confirming the worker agrees (step 1 of *Render with
Netlify in front*). An empty value of a variable `render.yaml` leaves blank
counts as unset. "Verify" names the page or `live_verify` check that proves it
works; key presence alone proves nothing. `.env.example` carries every
variable's full comment.

### Core

| Variable | Service | Required | How to verify |
|---|---|---|---|
| `SECRET_KEY` | both | required | `manage.py check --deploy`; sessions survive a redeploy |
| `ENCRYPTION_KEY_SALT` | both (same value) | required; never rotate casually | tokens still decrypt: `live_verify accounts.connected`, `credentials.*` |
| `DEBUG` | both | required, `false` | `live_verify config.debug` |
| `ALLOWED_HOSTS`, `APP_URL`, `CSRF_TRUSTED_ORIGINS` | both | required | `live_verify config.app_url`, `config.oauth_callbacks`; the login page loads over https |
| `APP_DOMAIN`, `POSTGRES_PASSWORD`, `CADDY_MEDIA_ROOT` | Compose only | required on a VPS | Caddy obtains the certificate; uploads load |
| `BB_TRUSTED_PROXIES` | web | optional (behind a proxy you run); `10.0.0.0/8` on Render, set by `render.yaml` | `live_verify config.https_behind_proxy`; one person's failed logins do not lock out everyone |
| `FRONT_DOOR_SIGNING_SECRET` | web (and the Netlify site, same name, Runtime scope) | required behind the Netlify front door | visitors behind one Netlify node are told apart: see *Client addresses* under Render with Netlify in front |
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
| `MEDIA_STORAGE_PENDING` | both | optional; `true` on Render until the R2 bucket exists (no effect once `S3_BUCKET_NAME` is set) | `check --deploy` warns W015 instead of stopping the deploy; uploads are refused |

### Email

| Variable | Service | Required | How to verify |
|---|---|---|---|
| `EMAIL_BACKEND_TYPE`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | both | required before inviting people | Set up → Email (owners); `/ops/email/` sends a test |
| `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` | web | optional (send through a Gmail account from `/ops/email/`) | Set up → Email shows "connected" |
| `RESEND_WEBHOOK_SECRET` | web | optional | delivery events are recorded |
| `EMAIL_SENDING_ENABLED`, `EMAIL_DAILY_SEND_LIMIT`, `EMAIL_RECIPIENT_HOURLY_LIMIT`, `EMAIL_RECIPIENT_DAILY_LIMIT` | both | optional (defaults on, 2000 a day, 6 and 20 notification emails per person an hour and a day) | a notification past a cap is recorded as stopped by the email budget; sign-in mail skips the per-person caps |
| `REQUEST_INVITE_HOURLY_LIMIT` | web | optional (default 30) | requests past it are thanked but not passed on, and a warning is logged |

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

`RENDER_EXTERNAL_HOSTNAME` (Render), `RAILWAY_ENVIRONMENT*` and
`RAILWAY_GIT_COMMIT_SHA` (Railway) are set by the platform and
only read.

## Checking the live deployment

`python manage.py live_verify` prints `live_verify:` lines — PASS / FAIL /
BLOCKED (waiting on the owner) — covering configuration, storage, the worker,
both brand workspaces, every connected account's identity (read-only API
calls), workspace isolation, Telegram, and the full approval → publish path on
a throwaway fixture that is rolled back (provider stubbed; nothing is posted).
On Render the pre-deploy step runs `check --deploy` and `migrate` only, so run
`live_verify` from the web service's Shell (step 6 of Render with Netlify in
front). On Railway, the previous deployment, the release command
`python manage.py release --setup-brands --verify` ran it before new code took
traffic, and its lines were in the deploy log of the `sm-bean` service.

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

### What the app compresses

HTML pages and HTMX fragments are gzipped by the app for browsers that ask
(`apps.common.middleware.HtmlGZipMiddleware`, with Django's BREACH padding).
Static files are served precompressed by WhiteNoise. File downloads (media,
attachments, exports), streamed responses and JSON (the Agent API, MCP,
webhooks) are sent as they are. A proxy in front that compresses again sees
`Content-Encoding: gzip` and leaves the page alone.

## Rollback

On Railway (the previous deployment), the release step took a database backup
**before** migrating (`backups/db-<timestamp>.tar.gz` in the media bucket; the
log names it). Render's pre-deploy step takes none; see
[Rollback on Render](#rollback-on-render) for its database recovery.

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
