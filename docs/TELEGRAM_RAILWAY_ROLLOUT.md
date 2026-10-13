# Controlled Railway release — SM Bean

Prepared 12 October 2026 for reviewed source `6cb392ff35494a0cb3172c95e654663cfe6dfce9`.
Use [the read-only inspector](../tools/telegram_release_inspect.py), [the pending receipt](TELEGRAM_RAILWAY_RELEASE_RECEIPT.json) and [the Neopolis pilot worksheet](NEOPOLIS_LIVE_PILOT_WORKSHEET.md). This is an executable operator runbook, not evidence of a production release.
The source is uploaded and locally tested; runtime proxy access has prevented
verification of Railway, live SM Bean and real provider credentials.

## 1. Control the rollout before a main merge

The services deploy from `main`. Hold/disable automatic deployment while
preparing the first release that introduces the worker singleton lease.
Stop and drain the old `sm-bean-worker` process before starting the new worker.
The old code does not acquire the new lease, so observing a lease is insufficient
to prove that the old process stopped. Confirm the old deployment is actually
stopped in Railway; allow an in-flight model/image call to finish. A forced
termination requires inspecting interrupted jobs and ambiguous provider sends.

Use an explicit maintenance window that prevents web/API/Telegram writes and
worker writes while taking the backup and applying migrations. The existing
backup exports tables individually, so merely stopping the worker does not
establish a consistent snapshot if web clients keep changing related rows.
Do not turn approval enforcement off. Hold bot activation until its new route
is ready. Record the baseline web/worker deployment IDs and prior commit.

Review/merge the cumulative `codex/telegram-client-hub` branch only once this
rollout is controlled. Verify the resulting main commit contains the exact
reviewed source. A normal merge may create a new commit SHA; record that full
SHA for both service receipts and the helper's `--expected-deployment-commit`.
Never bypass a denied API by pushing `main` before establishing this rollout.

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

Apply all eight cumulative migrations, including `telegram.0001_initial` and
`studio.0005_private_transport_history`; the helper checks applied records and
the real private-history column. Deploy web and worker from the same recorded
merge/source SHA. Preserve the existing `SECRET_KEY` and `ENCRYPTION_KEY_SALT`
and share the same existing values across services. Changing them breaks
previously encrypted accounts, bot credentials and payloads.

Set `STUDIO_PROVIDER=openrouter`, securely bind the supplied OpenRouter key,
choose an available `STUDIO_MODEL`, and verify actual credit balance. Image
requests use the separate `FAL_KEY`/image pipeline; model-key presence does not
prove real graphics. Validate actual storage and brand account permissions.
Use the uploaded credential file privately; never paste its contents into logs
or the release receipt. Saved cloud bindings and Railway variables are separate.

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

Copy the tracked `tools/telegram_release_inspect.py` to `/tmp/TELEGRAM_RELEASE_INSPECT.py` in each selected container
without changing app source. Run it with that container's normal Python,
working directory and production settings. It makes no external call and runs
all database inspection in an enforced PostgreSQL read-only transaction.
For the reviewed source SHA, the commands are:

```bash
python /tmp/TELEGRAM_RELEASE_INSPECT.py --project /app --service sm-bean --stage schema
python /tmp/TELEGRAM_RELEASE_INSPECT.py --project /app --service sm-bean-worker --stage schema
```

If main has a verified merge commit, add
`--expected-deployment-commit FULL_VERIFIED_MERGE_SHA` to both commands.
Preserve each JSON result. Exit 2 means one or more checks remain blocked;
exception output is limited to its type. No token, secret, transcript or
commercial claim is included. A helper pass does not certify the live campaign.

After the worker has processed real cycles, rerun both with `--stage runtime`.
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
Record those receipts in `TELEGRAM_RAILWAY_RELEASE_RECEIPT.json` without secrets.

## Recovery

Keep automatic generation and publishing paused while investigating schema,
credential, worker or uncertain-send failures. Preserve new holds and approval
fingerprints; do not revert blindly to baseline `05ca828`, which removes those
controls and the lease. Inspect native accounts before recovering unknown
outcomes. Restore a backup only into an isolated database with the matching
manifest/source and a reviewed recovery plan; restoring it over production can
lose later human changes and create duplicate-post risk.
