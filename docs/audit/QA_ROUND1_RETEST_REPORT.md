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

## Update, 1 Oct 2026: pre-deploy review of every migration

Before the third deploy attempt, each of the 8 migrations production will run
on top of `21052a5` was reviewed for failure on real data. A second,
adversarial reviewer checked each verdict. A review of the resulting fixes
followed. Production data could not be copied for a rehearsal (bucket
credentials were not available to this session), so the risky shapes were
seeded into a local Postgres database rewound to production's schema
instead.

| Found | Effect | Fixed |
|---|---|---|
| BUG-34 `media_library/0004`: the new folder-name key had no organisation; only root folders were de-duplicated; a duplicate could be renamed onto an existing "X (2)" | The deploy aborts (`could not create unique index`), or one tenant's org-wide folder is renamed because of another tenant's | The key includes the organisation; all scopes de-duplicated with the first free suffix. Test rewinds a real DB to `0003`, seeds every shape, migrates forward. It reproduces the abort on the old migration |
| BUG-35 recurrence: two workers during a deploy each cloned the same dates | Duplicate scheduled posts, i.e. a double publish once accounts are connected | Ledger re-read under a row lock per occurrence. A two-thread race test gives 24 clones for 12 dates without the lock (3 of 3 runs) and passes with it |
| Folder delete could 500 (name clash on promotion, concurrent deletes, an id-named sibling), and a non-clashing child could be renamed | Partial state or a failed delete | Atomic and serialised per workspace; names planned in memory; only real clashes get a suffix |
| `SET CONSTRAINTS` broke `migrate` on the README's SQLite setup | Local dev only | Runs on Postgres only |
| NUL byte in a folder name; double-submit on create/rename | HTTP 500 | 400 with a message |

Checked and fine: production runs Postgres 18 (`postgres-ssl:18`), so `NULLS
NOT DISTINCT` is supported. `composer/0015` was edited after production
applied it, but only its reverse function changed, so there is no schema
drift.

**Owner note, recurring posts.** The worker already on `226ed66` has queued an
hourly recurrence cycle. It fails today only because a column is missing.
Once the release migrates, any "Make recurring" rule saved earlier will
generate up to 90 days of scheduled copies. In the old build that tick did
nothing, so the user may not remember setting it. No accounts are connected,
so nothing would publish, but the calendar would fill. After the deploy,
review Calendar for unexpected repeated posts and delete the source post's
recurrence if it was a test.
