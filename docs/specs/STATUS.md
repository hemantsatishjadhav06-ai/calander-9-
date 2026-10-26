# Beta plan status

Where each phase of [`docs/BETA_PLAN.md`](../BETA_PLAN.md) stands, and what is left. Updated
26 Oct 2026. The detail of what changed and what each gate said is in [`CHANGELOG.md`](CHANGELOG.md).

| Phase | State |
|---|---|
| 0 · Agree the cut | **Done.** Spec approved, gate passed, released to production (24 Oct, main `6d9cf1d`). |
| 1 · Test harness first | **About three quarters done**, on PR #17 (branch `claude/trusting-dijkstra-m7nul1`). |
| 2 · Cut and merge, no restyling | Not started. |
| 3 · Rebuild the nine screens | Not started. |
| 4 · Standards | Not started (two pieces landed early: dependency audits and `compilemessages` in CI). |
| 5 · Platform connections | Not started; most of it waits on the owner's developer apps. |
| 6 · Beta release | Not started. |

## Phase 1 — left to do

Done: the dependency bump and audits in CI (`pip-audit` 0, `npm audit` 0 high, `compilemessages`),
the e2e server, Playwright on three devices with axe, all 12 golden paths written (11 run, path 12
is the declared pending TOTP test), the defects they found fixed, and the date-dependent tests
repaired. Left:

1. **Lighthouse**: `.lighthouserc.json` with the section 5 budgets and `tests/lighthouse/run.mjs`
   (Lighthouse 13.5.0 is installed; `@lhci/cli` is not used, see `01-harness.md` R9). Measure Home,
   Approvals and Calendar; if the 150 KB script budget fails, load Chart.js and SortableJS only on
   the pages that use them.
2. **CI jobs**: *E2E (Playwright)* (with `npx playwright install --with-deps chromium webkit`, so the
   iPhone 13 project runs on WebKit for the first time there) and *Lighthouse CI*.
3. **Review leftovers**: a final review of group 4 (paths 6 and 8) after its last fixes; group 1's
   open point (path 11 sends workspace-B ids in URL paths only, not in form bodies or query strings,
   and skips the Agent API).
4. **P1 items**: a CSP header test; the client variant of path 6; the manager variant of path 5.
5. **Docs**: `CLAUDE.md` *Run and test* and the "CI runs exactly these" sentence (e2e, Lighthouse,
   audits, `compilemessages`, gitleaks); `CONTRIBUTING.md`.
6. **Gate**: CI green with all new jobs; the 12 e2e tests on the old UI (11 pass, 1 pending until
   Phase 4, reported as such); then merge PR #17 and release.
7. **Owner**: a branch ruleset on `main` requiring the CI checks (GitHub → Settings → Rules →
   Rulesets → New branch ruleset → target `main` → require a pull request and the status checks
   *Lint (ruff)*, *Type check (mypy)*, *Test (pytest)*, *Agency UI state tests*, *Docker build*,
   *Secret scan (gitleaks)*, *Dependency audit*, and later *E2E (Playwright)* and *Lighthouse CI*).

## Phases 2–6 — left to do

**Phase 2 — cut and merge, no restyling.** The six-item navigation (sidebar and phone bottom bar,
*More* removed, a command-palette stub); new views `/approvals/`, `/settings/` (tabs) and
`/studio/activity/` that include the existing partials, with the old URLs answering 301; the
`features` switches applied to Blog, Queues, Templates/Categories/Tags, the extra providers and
Advanced settings; Intelligence, API keys, MCP, the OAuth server and `workflow_*` out of the
navigation (URLs keep working); the marketing site down to three views. Gate: full pytest green, the
e2e paths updated to the new routes, no 404 for any URL in `PRODUCT_MAP.md`.

**Phase 3 — rebuild the nine screens** (in order: New post sheet, Home, Approvals stack, Calendar,
Post page, Inbox, Analytics, Activity, Settings with the onboarding wizard, client portal,
marketing). Per screen: 390 px first, dark and light, one primary action, `prefers-reduced-motion`,
`impeccable` and `design-is` audits, axe 0 serious, Lighthouse ≥ 90 mobile, the e2e path green,
`recolor.py --check`, a visual baseline in a `visual:` commit, and **the owner's sign-off on the
before/after screenshot pair**.

**Phase 4 — standards.** TOTP 2FA with `django-otp` (required for owners, recovery codes; golden
path 12 turns green); data export and self-serve account deletion; the `{% trans %}` sweep with an
`en` catalogue and `compilemessages` in the Docker build; `/health/` with the worker heartbeat and
Railway's health check on it; privacy, terms and sub-processor pages; a 14-day idle session
timeout; nightly Postgres backup to S3/R2 with one restore drill written up; Sentry on. Gate: every
row of section 5 passes its tool. Open decision for the owner: whether another workspace's URLs
should answer 404 instead of today's 403.

**Phase 5 — platform connections.** X, Pinterest, Google Business Profile and LinkedIn connected
and verified with one real post each, then deleted; the Connect screen showing only the seven beta
platforms unless `extra_providers` is on; token health on Settings → Accounts with a *Reconnect*
that works on a phone.

**Phase 6 — beta release.** Railway with web, worker, Postgres, Redis and S3/R2;
`SIGNUP_MODE=invite`; a Sentry DSN; the ten beta workspaces seeded and their owners invited; the
stakeholder update; the rollback trigger written down (any failed `run_publish_cycle` for 5 minutes
→ redeploy the previous image). Gate: the definition of done in section 8.

## Needs the owner

- **GitHub**: the branch ruleset above (admin rights).
- **Developer apps and credentials** (Phase 5, also blocking `live_verify`): an X app at
  console.x.com with the callback `https://sm-bean-production-eb50.up.railway.app/social-accounts/callback/x/`
  and credits; a LinkedIn company app with the Community Management API; Pinterest and Google
  Business Profile apps; `FACEBOOK_WEBHOOK_VERIFY_TOKEN` for real-time comments; X connected for
  Neopolis and More Space.
- **More Space's Instagram**: the connected account is `@morespace.ai`, not the brand account
  `live_verify` expects (the one failing check).
- **Production settings** (Phase 4/6): `SENTRY_DSN`; `ACCOUNT_EMAIL_VERIFICATION=mandatory` once
  email works; `ADMIN_ALLOWED_IPS`; S3/R2 bucket and Redis; `SIGNUP_MODE=invite`.
- **Beta**: the list of the ten agencies and owner emails; who receives the stakeholder update.
- **Phase 3**: sign-off on each screen's before/after pair.
- **Session**: the separate session "Pin the clock in two date-dependent studio tests"
  (branch `claude/nice-dirac-oaccgz`) duplicates the date fix already on PR #17; stop or archive it.

## Known issues found along the way (not fixed, outside Phase 1)

- `apps/studio/tests/test_report.py::test_the_client_safe_report_has_only_the_reports_own_words`
  fails about 1 run in 100 (a timestamp in the report can contain "4.2").
- `templates/blog/partials/field.html` names the error list `<id>_errors`, but Django 5.2's
  `aria-describedby` points at `<id>_error`, so screen readers miss field errors on the brand and
  blog forms.
- `apps/common/management/commands/restore_database.py:46-55` can query `information_schema` rows
  before filtering to `public`, which makes `test_backup_restore_round_trip_preserves_application_rows`
  fail intermittently.
