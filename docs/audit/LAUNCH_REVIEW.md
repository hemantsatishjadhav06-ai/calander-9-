# Launch review — CTO, CEO, CMO

Three independent reviews of branch `claude/friendly-sagan-pl70p6` (PR #1), run
after every engineering row in `GAPS.md` was closed. Each reviewer read the code,
the gap register and the verified facts about the live Railway environment, and
was asked for a go / no-go.

## Verdict

| Reviewer | Public launch | Closed beta |
|----------|---------------|-------------|
| CTO | **No-go** | **Go with conditions**: 3–10 hand-picked agencies onboarded by the team |
| CEO | **No-go** | **Go with conditions**: 3–5 design partners, free, under a signed beta agreement |
| CMO | **No-go** | **Go with conditions**: 5–10 hand-held design partners |

**Unanimous: do not open the product to the public yet. Start a closed, free,
invite-only beta once the conditions below are met.** The engineering work earns
a beta, not customers' money. None of it is live until PR #1 merges: production
still runs the pre-audit `main`, which has a cross-tenant publishing hole and
dependency CVEs.

## What engineering already fixed from the reviews

Everything the reviewers found that code could fix is fixed on the branch, with
tests (full suite 2309 passed):

- **Signup closed by default** (`SIGNUP_MODE=invite_only`). Invitation links
  always work; `SIGNUP_ALLOWLIST` admits design partners by address or domain;
  everyone else sees an invite-only page. `SIGNUP_MODE=open` when you decide to
  go public.
- **Public pages promise only what exists.** Removed or corrected: data export,
  backups and uptime monitoring, white-label and custom domains, SLAs,
  "publish across 11 platforms". CTAs read "Request early access" while
  invite-only.
- **Connect page** shows customers "Coming soon" instead of server-admin
  instructions for platforms they cannot enable.
- **Onboarding checklist** counts a *scheduled* post (activation), not a draft,
  and refreshes the moment a channel connects.
- **CSV import** no longer lets a contributor schedule around client approval.
- **Login lockout**: allauth's rate limits keyed on the proxy's address, so ten
  bad logins from anyone locked everyone out. Fixed, along with a client-IP
  helper that trusted the forgeable end of `X-Forwarded-For`, and the admin
  login's missing throttle.
- **Rollback safety**: new columns no longer break the previous release's
  inserts; a folder migration cleans duplicates instead of failing the deploy.
- **Container** runs as an unprivileged user; `WEBHOOK_SECRET` is honoured.

## Conditions before the first external customer (owner)

These need credentials, money, legal review or a decision — nothing code can do.
In order:

1. **Legal** — real Terms and Privacy Policy (the current pages say they are
   placeholders and are linked from signup), a beta agreement with no SLA, and a
   DPA with a sub-processor list: the product holds agencies' clients' social
   tokens. Meta and Google app review also require a real privacy policy URL.
2. **Email** — SMTP with SPF/DKIM on your domain (`EMAIL_*`,
   `DEFAULT_FROM_EMAIL`) on **both** Railway services, and a public
   `SUPPORT_EMAIL`. Without it invites, client magic links, approval reminders
   and password resets fail, and a locked-out customer has no way back.
3. **Media storage** — `STORAGE_BACKEND=s3` and `S3_*` on **both** services.
   Without it every post with an image fails: the worker cannot read the web
   container's disk, and redeploys wipe it.
4. **Monitoring** — `SENTRY_DSN`, an external uptime check, and an alert on failed
   publishes with a named person watching. A client's post that silently doesn't
   go out is how an agency fires us.
5. **Admin credential** — stop the web pre-deploy command from re-setting the
   superuser password from an env var on every deploy (see runbook step 3).
6. **Platform access** — start Meta App Review, Google OAuth verification for
   YouTube upload, LinkedIn Community Management and the TikTok audit now; they
   take weeks. Until approved, partners' staff are added as testers.
7. **Brand** — "SM Bean" and the monogram are placeholders. No press or public
   marketing until the name is cleared (trademark search).

## Go-live runbook

1. **Before merging**: `pg_dump` the production database and enable Railway
   Postgres backups. Run
   `SELECT workspace_id, name, count(*) FROM media_library_folder WHERE parent_folder_id IS NULL GROUP BY 1,2 HAVING count(*) > 1;`
   (the migration now renames duplicates itself; this just tells you what it will touch).
2. Set SMTP, S3, `SENTRY_DSN`, `SUPPORT_EMAIL`, `WEBHOOK_SECRET` as **shared**
   variables on both services. Confirm `ENCRYPTION_KEY_SALT` and the
   `PLATFORM_*` values are identical on web and worker.
3. Change the web pre-deploy command to `python manage.py migrate --noinput`,
   set a strong admin password in the app, then delete the
   `DJANGO_SUPERUSER_*` variables.
4. Merge PR #1. Watch the web pre-deploy migrate succeed, then **restart the
   worker** so it isn't running new code against old columns.
5. Set the worker start command to `python manage.py run_worker` and confirm
   "Worker ready" in its logs. Set the web service's health check path to
   `/health/` (it must not go in `railway.toml`, which the worker also reads).
6. Smoke test: `/health/` returns 200; log in; send an invite and receive it;
   reset a password; upload an image and publish it to one test account per
   platform; take a scheduled post through client-portal approval; redeploy the
   worker while a post is due and confirm no duplicate and nothing stuck in
   "Publishing"; 11 bad logins return a 429.
7. **Rollback**: prefer rolling forward. If you must go back to `566b08c`, the
   new columns are rollback-safe, but take the step-1 dump first regardless.

## Beta scope (CEO)

- **Launch, beta-labelled where noted**: composer, calendar and queues;
  approvals and the client portal (once SMTP works); media library (once S3 is
  live); publishing to Bluesky, Mastodon and DEV.to for anyone, and to
  Facebook Pages, Instagram, Threads and YouTube for partners added as app
  testers; analytics and the unified inbox as **Beta**.
- **Hide, don't promise**: LinkedIn, TikTok, Pinterest, Google Business until
  their reviews pass; the AI add-on; Managed Cloud / Agency plans; white-label;
  public API/MCP (on request only, until OAuth token hashing ships, GAPS O6).
- **Pricing**: free during the beta, no card, 30 days' written notice before any
  paid plan. Decide pricing at launch + 30 days.

## Positioning (CMO)

> The social scheduler for agencies where client approval is built in: compose
> once, get sign-off through a no-login client portal, and publish on schedule —
> with no per-seat or per-client fees during the beta.

- **ICP**: agencies of 3–20 people managing 5–30 client brands, paying per seat
  or channel elsewhere and chasing approvals over email or WhatsApp.
- **Proof points we can honestly make**: per-client workspaces with internal and
  client approval stages and a magic-link portal; unlimited seats, workspaces
  and channels during the beta; open source (AGPL) with an API and MCP.
- **Don't claim yet**: "11 platforms" on the hosted product, "free forever" for
  hosted, data export, managed backups/monitoring/support, stock-photo search.
- **Open decision**: lead with the hosted product for agencies, and move
  open-source/self-hosting to a trust section. The site still tells both stories.

## First 30 days

1. **Publishing reliability** — review every failed post with the partner within
   24 hours; target 99% on time. Watch for rows stuck in "Publishing", worker
   memory, token-refresh failures, 429s on login and webhooks.
2. **Platform approvals** — the reviews that decide whether a public launch is
   possible at all.
3. **Account security** — two-factor login and the OAuth token-hashing cutover.
4. **Activation** — privacy-friendly product analytics with funnel events
   (signup → channel connected → first post scheduled); agency and first-client
   names at signup instead of "My Organization".
5. **Decision at launch + 30 days** — go public when: zero open P0/P1 issues,
   Meta and LinkedIn live on the hosted product, at least 40% of beta signups
   connect a channel, and at least three partners say they would pay.

## Accepted risks (CTO)

One replica per service; a worker killed mid-publish fails the post after 15
minutes rather than risking a duplicate (by design); OAuth tokens stored
encrypted but not hashed (O6); no billing; placeholder brand.
