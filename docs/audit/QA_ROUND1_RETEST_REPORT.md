# QA round 1 retest — engineering report (27 Sep 2026)

**Summary: NO-GO until PR #4 is deployed. After that, every code bug is fixed.**

QA's 2 PM retest ran against production. The release (#3, `226ed66`) never went
live on the web service, so QA was still testing the old build (`21052a5`).
That is why most bugs looked unchanged. The retest also found two real
deploy bugs, BUG-31 and BUG-32, both caused by the release itself and both
fixed in PR #4.

## What broke the release, from the Railway logs

| Bug | Cause | Fix (PR #4) | Verified |
|---|---|---|---|
| BUG-31: web crash on start | `gunicorn --error-logfile /dev/stdout` opens a pipe with mode `a+`, which raises `File or stream is not seekable` | `gunicorn.conf.py` sends gunicorn's logs to stdout as JSON through a handler | Reproduced with the old flags. With the new config: boots, `/health/` 200, JSON on stdout |
| BUG-32: worker on new code, database not migrated | Railway runs the pre-deploy command **without a shell**. `backup && migrate && import` ran only the backup, and the step still "passed" | `manage.py release` does backup, then migrate, then media import. It needs no shell and fails as a unit. The Railway pre-deploy command is already switched | Rehearsed on a database at production's schema (21052a5): every migration applied, `shown_in_app` exists |

The backup step itself worked in production: `backups/db-20260927T080207Z.tar.gz`
is in the `sm-bean-media` bucket. So the bucket credentials (BUG-03) are proven.

## Retest method

- Release code at `5d96138`, run locally under **gunicorn with `config.settings.production`**.
- Driven in Chromium (Playwright): 38 checks across public pages, signup, composer, Publish, media, CSV, portal, dialogs and contrast.
- This sandbox cannot reach the production URL (egress policy), so production evidence comes from the Railway deploy logs.
- 2,383 automated tests pass. Ruff and mypy are clean.

## Results (33 bugs)

| Result | Count | Bugs |
|---|---|---|
| Pass in browser retest | 22 | 05, 08, 10–20, 22–25, 27–29, 33 |
| Fixed in PR #4 (verified) | 3 | 01, 31, 32 |
| Code ready, needs deploy / owner step | 2 | 02 (connect Gmail at /ops/email/), 03 (bucket) |
| Unit-tested, needs QA with a video | 1 | 21 |
| Partly fixed | 3 | 04 (needs SENTRY_DSN), 07 (delete superuser vars, set ADMIN_ALLOWED_IPS), 30 (type/wordmark design) |
| Owner / plan action | 2 | 09 (connect test accounts), 26 (update test plan) |

Per-bug evidence: `SM_Bean_QA_Round1_Retest_Engineering.xlsx`, Bugs tab, last four columns.

## To reach GO

1. **Merge PR #4.** Railway then runs `release` (backup, migrate, copy media into the bucket) and boots web and worker on the same code.
2. Open `/ops/email/`, connect neopolisinfrallp3@gmail.com and send the test email. Then set `ACCOUNT_EMAIL_VERIFICATION=mandatory`.
3. Set `SENTRY_DSN` (both services), `SIGNUP_ALLOWLIST` and `ADMIN_ALLOWED_IPS`. Delete the `DJANGO_SUPERUSER_*` variables and rotate the admin password.
4. Delete the QA accounts `qa-test-noninvited@example.com` and `qa-test-noninvited2@example.com`.
5. Connect the Bluesky, Mastodon and DEV.to test accounts, then run QA round 2. Publishing (sections D, N) is still untested for lack of accounts.
