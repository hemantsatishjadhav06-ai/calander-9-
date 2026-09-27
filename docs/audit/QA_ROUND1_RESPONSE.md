# QA round 1 — engineering response and release runbook

QA ran on 27 Sep 2026 against production, which was still on commit `566b08c`
(before PR #1). This branch is PR #1 plus a fix for every code bug the round
found. The per-bug status lives in
`SM_Bean_QA_Round1_Engineering_Response.xlsx` (Bugs tab, last column).

## Fixed in code (retest after deploy)

| Bug | Fix |
|---|---|
| 05 | Invite-only signup for email and Google; an invite admits only the invited address |
| 08 | Real Terms / Privacy drafts (DPDP, GDPR, Google Limited Use, Meta Platform Terms) and `/support/` |
| 10 | Logout is POST-only |
| 11 | 4-step onboarding checklist |
| 12 | Sidebar shows only connectable platforms; others "Coming soon" |
| 13 | Save Draft with no channel saves, says so, and appears in Drafts |
| 14 | Idea → Create Post keeps the title and is visible |
| 15 | Rejected uploads return 400 with a reason; composer/idea uploads now type-checked (stored-XSS hole) |
| 16 | CSV preview 500 fixed |
| 17 | Random media filenames; Caddy serves only public prefixes (full fix needs private S3, below) |
| 18 | Accessible dialogs |
| 19 / 30 | One primary `#C2410C`, AA contrast on text and buttons |
| 20 | One "connect a channel" banner; tabs keep working |
| 21 | Video poster frame and Range-capable player |
| 22 | Platform claims driven by `LAUNCHED_PLATFORMS` |
| 23 | BrightBean leftovers removed |
| 24 | Branded error pages; portal says invalid / used / expired / no link |
| 25 | robots.txt, sitemap, a title on every page |
| 27 | Kolkata not Calcutta (with data migration); media times in workspace tz |
| 28 | Media library layout |
| 29 | Active nav item, tab scrollbar |
| 04 (code part) | JSON logs on stdout at their real level; Sentry env/release |

PR #2 (marketing site) is **not** in this release: it reintroduces the
"11 networks" claim, brightbean.xyz legal links and a logo file that no longer
exists (500 on `/` in production). It needs a rebase onto this branch first.

## Already changed on Railway (27 Sep)

- `sm-bean` pre-deploy command is now `python manage.py migrate --noinput`. It
  no longer re-creates the superuser or resets its password.
- `sm-bean` variables added: `WEBHOOK_SECRET` (random), `SIGNUP_MODE=invite_only`,
  `LAUNCHED_PLATFORMS=bluesky,mastodon,devto`. Nothing was redeployed.

## Cut-over runbook (owner go-ahead needed)

1. **Back up Postgres** (Railway → Postgres → Backups, or `pg_dump`).
2. Merge this PR to `main` (both services deploy from `main`).
3. Set `sm-bean-worker` start command to `python manage.py run_worker`, in the
   same deploy. It does not exist on the current production code, so don't
   set it earlier.
4. Storage: create a bucket (Railway bucket or Cloudflare R2), then set
   `STORAGE_BACKEND=s3`, `S3_BUCKET_NAME`, `S3_ACCESS_KEY_ID`,
   `S3_SECRET_ACCESS_KEY`, `S3_ENDPOINT_URL`, `S3_REGION_NAME` on **both**
   services. Copy the existing files from `/app/media` first.
5. Email: set `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`,
   `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`; verify SPF/DKIM/DMARC. Then
   set `ACCOUNT_EMAIL_VERIFICATION=mandatory`.
6. Set `SENTRY_DSN` (both services), `SUPPORT_EMAIL`, `LEGAL_ENTITY_NAME`,
   `SIGNUP_ALLOWLIST` (tester emails or `@domain`), `ADMIN_ALLOWED_IPS` and
   optionally `ADMIN_URL`.
7. Delete `DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD`, then rotate
   the admin password.
8. Delete the QA account `qa-test-noninvited@example.com`.
9. Connect the Bluesky, Mastodon and DEV.to test accounts (BUG-09), then run
   the P0 smoke twice.

`python manage.py check --deploy` warns about every item in steps 4–7 that is
still missing (smbean.W003–W010).

## Still open after this release

- BUG-30: the Analytics and portal serif headings, and a real SM Bean wordmark
  and icon, need a design pass.
- BUG-26: QA plan update. Ideas live at `/workspace/{ws}/create/`; tags are
  managed in the composer.
- Files uploaded before this release keep their guessable names until they
  are moved to the private bucket.
