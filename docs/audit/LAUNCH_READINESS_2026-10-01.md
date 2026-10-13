# Launch readiness audit — 1 October 2026

This report describes the repository changes and checks performed in the cloud
development environment. It does not establish that a hosted deployment or a
credentialed social-platform integration has been tested.

## Release decision

The application has received security, correctness, usability and deployment
repairs. Public launch still depends on the deployment prerequisites and live
checks below. Previous audit reports describe earlier releases and are not
evidence of the current production environment.

## Repairs

| Area | Confirmed problem and resulting behavior |
| --- | --- |
| Client portal | Passwordless approval sessions are confined to the portal, bound to a consumed token, and invalidated by link revocation, expiration, account deactivation, role changes or archived workspaces. Internal discussions and attachments remain private. |
| Invitations | Signup and acceptance verify the invited email, refresh invitation state under a row lock, and reject revoked, rotated or used credentials. |
| Accounts and API keys | Password changes apply Django validators. Disabled users and archived workspaces cannot use issued keys. Workspace rosters respect membership. |
| Image uploads | Avatars and workspace icons verify actual image content and use filenames based on the detected image format. Untrusted filename extensions cannot make an uploaded image render as same-origin HTML. |
| OAuth | Registration validates redirect URLs and grant metadata, limits registration using trusted client addresses, and rejects inactive token owners. The hash-checked dependency lock upgrades allauth and oauthlib to fix CVE-2026-49265. |
| Publishing | Successful platform writes are not repeated because local logging or bookkeeping failed. Unknown remote outcomes stop automatic reposting and require checking the platform first. Claiming posts rechecks the current schedule, holds, retry delay and workspace scope while holding database locks. Thumbnail/cover assets enforce workspace scope. Provider Retry-After dates and durations are honored. |
| Social credentials | Token refresh is serialized; current refresh credentials and reconnects are preserved. Worker startup restores recurring account-health schedules. |
| Composer and approvals | Autosave and media operations enforce role/ownership boundaries. Approval invalidation includes per-platform content, metadata and ordered media. Queue failures roll back conflicting content changes. Invalid Idea references, recurrence settings and duplicate category names return validation errors before writes. |
| API and media | Upload retry fingerprints include content bytes; invalid folders and queue failures release claims and roll back database writes. Post creation and its retry response commit together. Image processing validates dimensions/crop bounds and marks undecodable uploads failed. |
| Inbox | Unsupported reply operations cannot falsely report successful delivery. Malformed bulk IDs and date filters return validation errors. |
| Notifications and onboarding | Pagination accepts malformed input safely. Read controls preserve navigation and refresh correctly. Preference validation is atomic. Public connection pages work for signed-in visitors, DEV.to uses its API-key flow, and the onboarding checklist does not cover form actions. Runtime chart/date/drag libraries are served locally with verified distributions and licenses. |
| Backups | Tables are exported from one repeatable-read snapshot and spooled to disk. A concurrent-write regression and backup/restore round trip exercise PostgreSQL behavior. |
| Deployment | Production checks reject unusable or unsafe origins, encryption, host, database and cache configuration. Production Compose exposes only the reverse proxy and retains shared durable media. Web and worker startup retain deployment checks. Test caches are isolated from deployment Redis bindings. |

## Validation

| Check | Result |
| --- | --- |
| Full PostgreSQL suite on the final source | **2,577 passed, 1 skipped**; 29 warnings, primarily test-settings override warnings |
| Ruff lint and formatting | Passed |
| mypy | Passed; 617 source files checked |
| Migration drift | No changes detected |
| Python dependency audit | No known vulnerabilities after the allauth/oauthlib update |
| npm audits, Tailwind and pinned vendored runtime libraries | No known vulnerabilities |
| Checksum-verified Gitleaks scan | No leaks in the 55 available Git commits or current tracked/nonignored source |
| Chromium functional checks | **25 passed**; no JavaScript errors or failed requests; mobile, reduced-motion and no-JavaScript marketing checks included |
| Live Redis integration | **5 passed**, including health and filmstrip cache round trip |
| PostgreSQL concurrent backup and backup/restore round trip | **2 passed**, also included in the full suite |
| Container build | Passed with official base images, verified dependencies and production collectstatic |
| Production smoke | Gunicorn pages, database/cache health, collected static/vendor assets, worker startup, unprivileged runtime and writable media verified |
| Caddy media boundary | Public media and Range requests work; private attachments return 404; switching to S3 blocks stale local media |

Component tests use PostgreSQL, including concurrent registration, scheduling,
token rotation, authorization, retries and backup behavior. Production smoke
checks use an isolated database/cache, local test keys and a synthetic HTTPS
origin; they do not test your real domain, email service or social accounts.

The default unit suite deliberately isolates caches in memory. A live Redis
service is exercised separately; a test that requires a Redis-backed filmstrip
cache can remain skipped in the default suite. Passing mocked provider tests
does not prove that an external platform has approved the application or will
accept a real publish.

## Deployment prerequisites

1. Configure the real HTTPS `APP_URL`, explicit `ALLOWED_HOSTS`, trusted reverse
   proxy addresses and matching web/worker configuration. Keep generated
   `SECRET_KEY` and `ENCRYPTION_KEY_SALT` stable; changing them invalidates
   sessions or makes stored credentials unreadable.
2. Use PostgreSQL and shared Redis in production. Keep their ports private.
   Perform migrations once before the web service and worker use the new code.
   Production Compose requires Docker Compose **2.24 or later** and a real
   `APP_DOMAIN`, strong `POSTGRES_PASSWORD`, and matching URL-encoded
   `DATABASE_URL` pointing at the `postgres` service. It starts six services and
   publishes only Caddy ports 80/443. Render/Heroku additionally require the
   configured public hostname, Redis and shared S3-compatible storage.
3. Use an S3-compatible bucket shared by web and worker on hosts with ephemeral
   disks, or a durable shared media volume on a VPS. Verify uploads survive a
   restart and are readable by the worker and intended publishing platforms.
4. Configure transactional email with a real sender/domain. Verify invitations,
   password resets, portal links and approval notifications arrive. Set
   `ACCOUNT_EMAIL_VERIFICATION=mandatory` once delivery works. Signup remains
   invite-only by default; set `SIGNUP_MODE=open` only when opening registration.
5. Provide platform app credentials and obtain required application approvals.
   Publish one text/image/video post on each platform you intend to advertise;
   verify the actual post, worker result, analytics and inbox rather than only
   the request response.
6. Replace placeholder Terms and Privacy pages with reviewed policies, set the
   real operator/support details, and configure the intended data-retention and
   deletion process. Software checks cannot provide legal review.
7. Configure error/uptime monitoring, backup retention and a recovery owner.
   Restore a production-sized backup into an isolated database before inviting
   customers. The existing restore command requires a PostgreSQL role allowed
   to disable foreign-key triggers; restricted managed roles need an approved
   administrator-assisted restore procedure.

## Rollout notes and remaining limits

- Old portal sessions without the new token binding need a fresh approval link.
- SQLite remains suitable for limited single-user development. It does not
  enforce PostgreSQL advisory locks or the nulls-distinct folder uniqueness
  constraint; use PostgreSQL to validate production concurrency.
- The existing OAuth server stores tokens in plaintext. Enabling hashed storage
  requires a deliberate compatibility migration for existing MCP connections;
  the audit did not silently invalidate those connections. Restrict database
  and backup access and schedule that migration before accepting higher-risk
  integrations.
- Platform network errors can leave the result of a remote write unknown.
  A platform response loss cannot prove that nothing was published. Check the
  platform before manually reposting an uncertain item.
- Live email, S3, public TLS, platform approvals, external billing/Intelligence,
  load capacity and the hosted production environment require separate live
  verification. They were not certified by this source-code audit.

## Suggested staging acceptance

On an isolated staging deployment, run the production checks and migrations,
confirm database/cache health, then exercise signup or invitation, login,
password reset, organization/workspace membership, upload, draft, review,
client approval, scheduling, publishing, inbox reply and analytics. Revoke a
portal link and API key and confirm access stops. Restart web and worker, verify
durable media and recurring jobs, and complete a backup/restore drill. Use the
actual public origin to check redirects, secure cookies, CSRF and OAuth.

Do not open public registration until those selected workflows pass with the
real credentials and the external prerequisites above are complete.
