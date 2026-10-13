# Controlled Railway release — SM Bean

Updated 13 October 2026 for the reviewed cumulative release, including managed
Telegram bot reservations. Use [the read-only inspector](../tools/telegram_release_inspect.py),
[the immutable source-manifest generator](../tools/generate_release_source_manifest.py),
and [the Neopolis pilot worksheet](NEOPOLIS_LIVE_PILOT_WORKSHEET.md).
The [12 October pending receipt](TELEGRAM_RAILWAY_RELEASE_RECEIPT.json) describes
historical source `6cb392ff35494a0cb3172c95e654663cfe6dfce9`; preserve it as a
historical record and create fresh receipts for this release. This runbook does
not establish a production release.
Use the [current launch report](audit/LAUNCH_READINESS_2026-10-13.md) and
[current release status](audit/RELEASE_STATUS_2026-10-13.json) for the 13 October
review and observed rollout evidence.

The public SM Bean health, landing and login pages are reachable. The Railway
GraphQL endpoint is reachable. Railway, OpenRouter and fal secret bindings were
saved after local verification; authenticated service IDs, deployment controls
and deployed source must still be recorded by the live rollout. The user-confirmed target project is
`66526b2a-6a09-43d8-bedb-ecfdd37f8d8a`. Restrict changes to its SM Bean web and
worker services; do not operate on the separate calander-6 project. The current
cloud bindings do not establish that the services use the same credentials.

## 1. Control the rollout before a main merge

The services deploy from `main`. Hold/disable automatic deployment while
preparing the first release that introduces the worker singleton lease.
Stop and drain the old `sm-bean-worker` process before starting the new worker.
The old code does not acquire the new lease, so observing a lease is insufficient
to prove that the old process stopped. Confirm the old deployment is actually
stopped in Railway; allow an in-flight model/image call to finish. A forced
termination requires inspecting interrupted jobs and ambiguous provider sends.

Use an explicit maintenance window that prevents web/API/Telegram writes and
worker writes while taking the backup and applying migrations. The backup uses
a consistent repeatable-read database snapshot. Pause all writers to prevent
changes between that snapshot and migration, and to keep old application code
from writing against schema that is being changed.
Do not turn approval enforcement off. Hold bot activation until its new route
is ready. Record the baseline web/worker deployment IDs and prior commit.

Review `codex/sm-bean-oct13-launch` against `main` and merge/push `main` only once
this rollout is controlled. The earlier `codex/telegram-client-hub` branch and
its `6cb392f` commit are historical inputs, not the current deployment identity.
Verify the resulting main commit contains the exact reviewed and tested source.
A merge may create a new commit SHA; record its full lowercase 40-character SHA
for both service receipts and `--expected-deployment-commit`. Generate a fresh
manifest from that immutable commit, as shown below. An inaccessible control
plane does not establish that automatic deployments are held.

## 2. Migrate once, then deploy matching services

Configure only the **web service's** pre-deploy command:

```bash
python manage.py release --verify
```

The command requires a successful backup before migrating and reports readiness.
Keep its backup location/manifest as release evidence. Inspect the existing
web pre-deploy setting: the historical `--setup-brands` flag also seeds static
test drafts and retrieves website assets. Omit it for this existing Neopolis
rollout so the target week is created by the requested AI-worker flow. Reuse
the actual workspace UUID; provision future brands through the normal app. Do not use `--skip-backup`
for production. Do not place a pre-deploy command in the shared `railway.toml`;
both services would execute it. Do not put `/health/` in that shared file either:
the worker serves no HTTP. Put `/health/` on the web service's own healthcheck.

Apply the full migration graph. The current inspector requires nine cumulative
release migrations, including `telegram.0001_initial`,
`telegram.0002_telegrammanagedbotreservation` and
`studio.0005_private_transport_history`. It checks migration records, the actual
private-history column and all 18 columns of the managed-bot reservation table;
a migration record alone does not prove that schema is usable. Deploy web and worker from the same recorded
merge/source SHA. Preserve the existing `SECRET_KEY` and `ENCRYPTION_KEY_SALT`
and share the same existing values across services. Changing them breaks
previously encrypted accounts, bot credentials and payloads.

Set `STUDIO_PROVIDER=openrouter`, securely bind the supplied OpenRouter key,
choose an available `STUDIO_MODEL`, and verify actual credit balance. Image
requests use the separate `FAL_KEY`/image pipeline; model-key presence does not
prove real graphics. Validate actual storage and brand account permissions.
Use securely bound credentials privately; never paste their contents into logs
or the release receipt. No credential-file attachment is available in this
environment. Saved cloud bindings and Railway variables are separate.

On both services set:

```text
TELEGRAM_WEBHOOK_BASE_URL=https://sm-bean-production-eb50.up.railway.app
TELEGRAM_WEBHOOK_READY=false
```

The web service uses the Dockerfile's Gunicorn command. The worker service runs:

```bash
python manage.py run_worker
```

Use one worker replica/process, the always-restart policy, and reserve an extra
PostgreSQL connection for its dedicated session lease. Do not add `--keep-locks`
to make an overlapping deployment succeed. Keep web writes paused until the
migration and startup checks complete, then resume controlled traffic.

## 3. Collect source/schema receipts, then runtime evidence

After the final reviewed and tested commit is recorded, generate a new artifact
from its committed Git blobs. The generator rejects branch names, abbreviated
SHAs and existing output paths; it does not hash a dirty working tree or prove
that tests passed. Keep the manifest outside the source commit to avoid a
self-referential commit hash:

```bash
python tools/generate_release_source_manifest.py \
  --project . --source-commit FULL_REVIEWED_TESTED_MAIN_SHA \
  --output /tmp/SM_BEAN_RELEASE_SOURCE_MANIFEST.json
```

Copy this manifest to `/tmp/SM_BEAN_RELEASE_SOURCE_MANIFEST.json` in each
selected container without changing app source. Run the tracked inspector with
that container's normal Python, working directory and production settings. It
makes no external call and runs database inspection in an enforced PostgreSQL
read-only transaction:

```bash
python /app/tools/telegram_release_inspect.py --project /app \
  --source-manifest /tmp/SM_BEAN_RELEASE_SOURCE_MANIFEST.json \
  --expected-deployment-commit FULL_REVIEWED_TESTED_MAIN_SHA \
  --service sm-bean --stage schema
python /app/tools/telegram_release_inspect.py --project /app \
  --source-manifest /tmp/SM_BEAN_RELEASE_SOURCE_MANIFEST.json \
  --expected-deployment-commit FULL_REVIEWED_TESTED_MAIN_SHA \
  --service sm-bean-worker --stage schema
```

Replace both SHA placeholders with the same actual full commit. The inspector
checks the manifest structure, committed source hashes and
`RAILWAY_GIT_COMMIT_SHA` before importing application code. Fresh-manifest mode
requires Telegram migration `0002` and its real reservation schema. Omitting
the manifest intentionally selects the historical `6cb392f` expectations and
is unsuitable for this release. Do not rewrite the old anchor digests or disable
verification to accept a new commit.

Preserve each JSON result. Exit 2 means one or more checks remain blocked;
exception output is limited to its type. No token, secret, transcript or
commercial claim is included. A helper pass does not certify the live campaign.

After the worker has processed real cycles, rerun both commands with
`--stage runtime`, retaining the same manifest and explicit full commit.
The receipt observes task-specific publisher, agency, confirmation and
Telegram processing plus the lease; a registered task alone does not pass.
A missing real Neopolis workspace, saved bot/groups/people, unknown send hold,
provider configuration or recurring plan blocks this limited receipt.
Graphics-key presence is informational: real access or authentic-photo fallback
must be demonstrated separately. Pairing counts are not a role certification.

Strict verification needs worker and pilot evidence; running it before the
first worker starts creates a readiness dependency. Run it after startup and
the authorized human-approved pilot:

```bash
python manage.py live_verify --strict --json
```

Later deployments with established evidence can choose a strict release gate.
Optional/informational provider checks remain distinct from critical acceptance.

## 4. Activate Telegram and Neopolis deliberately

Check that a wrong-secret POST to the **deployed** webhook route is rejected
with 403 before setting `TELEGRAM_WEBHOOK_READY=true` on both services.
Then connect the intended bot in Neopolis Agency → Telegram. Its supplied
username is an entry point, not a human recipient. Replace the token previously
shared in chat through BotFather before production use, and enter it through
the encrypted workspace form. Pair the real current lead/head, worker and client,
then pair separate internal and client groups as an authorized Telegram admin.
Control passive viewers and group history; command authorization cannot erase
messages they already received.

Configure authentic project references, current owner-backed facts, selected
native social accounts, permitted lead and distinct backup, pillars, volume,
creative memory and the soft budget. `/week prepare 2026-10-19` prepares the
source/configuration review for 19–25 October 2026 in Asia/Kolkata. Explicit
preparation confirmation queues analysis and drafts. A person approves each
exact final revision/account/future time before publishing.

Require one independent native social receipt, a Telegram update, delivered
lead/backup alerts, useful graphics on a phone, observed model/image costs and
worker restart/held-send behavior before marking the product launched.
Record those receipts in `docs/audit/RELEASE_STATUS_2026-10-13.json` without secrets. Preserve
`TELEGRAM_RAILWAY_RELEASE_RECEIPT.json` as the historical 12 October pending
record; local synthetic checks and public health responses do not replace live
Neopolis acceptance evidence.

## Recovery

Keep automatic generation and publishing paused while investigating schema,
credential, worker or uncertain-send failures. Preserve new holds and approval
fingerprints; do not revert blindly to baseline `05ca828`, which removes those
controls and the lease. Inspect native accounts before recovering unknown
outcomes. Restore a backup only into an isolated database with the matching
manifest/source and a reviewed recovery plan; restoring it over production can
lose later human changes and create duplicate-post risk.
