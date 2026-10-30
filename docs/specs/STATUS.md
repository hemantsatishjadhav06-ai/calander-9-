# Beta plan status

Where each phase of [`docs/BETA_PLAN.md`](../BETA_PLAN.md) stands, and what is left. Updated
30 Oct 2026. The detail of what changed and what each gate said is in [`CHANGELOG.md`](CHANGELOG.md).

| Phase | State |
|---|---|
| 0 · Agree the cut | **Done.** Spec approved, gate passed, released to production (24 Oct, main `6d9cf1d`). |
| 1 · Test harness first | **Completion and full verification in progress**, on open PR #17 (branch `claude/trusting-dijkstra-m7nul1`); gate not yet passed. |
| 2 · Cut and merge, no restyling | Not started. |
| 3 · Rebuild the nine screens | Not started. |
| 4 · Standards | Not started (two pieces landed early: dependency audits and `compilemessages` in CI). |
| 5 · Platform connections | Not started; most of it waits on the owner's developer apps. |
| 6 · Beta release | Not started. |

## Phase 1 — completion and verification

The 26 Oct continuation is limited to finishing and verifying Phase 1. PR #17
is not authorized to merge or release, and Phases 2–6 have not started. The
starting PR head is `4b697579d25a5ddf71d1dc015ab28f2a26e7620b`; its tree is
identical to GitHub's test merge `9582e28226b0fdd23f9fa51f11e2a219fa45bbc5`
against main `6d9cf1d450282e295a779dcdbdea5252d7e8c3d2`. This establishes the
combined tree to test, not a completed merge. The later documentation-only
commit `35f30cd` records the preceding session's final paths 6 and 8 review;
it does not change the application or test tree. Commit `2f14e96` preserves
that session's subsequent test receipt and redirect self-check fix.

Implemented: the dependency bump and audit checks, translation compilation,
the local e2e server, Playwright and axe, Lighthouse config/runner, the E2E
and Lighthouse CI jobs, and all three remaining tests (CSP response header,
client changes and manager approval). `CLAUDE.md` and `CONTRIBUTING.md` now
describe each test layer and how to run it.

This continuation's original full pytest baseline passed **5,530 tests with
1 explicit Redis-only skip**. The original 126 browser cases produced
**120 passes, 3 redirect self-check failures and 3 pending TOTP cases**.
All eleven implemented golden paths passed across the three devices,
including actual WebKit. After correcting the self-check, the focused run
of paths 6, 7 and 8, the new role variants and the redirect self-check passed
**21/21** on all three devices. These are baseline and focused results,
not the final Phase 1 gate; full receipts are in `CHANGELOG.md`.

The completed CI run on `d1dcb146` passed 5,536 Python cases (one Redis-only
skip) and 135 browser cases (three TOTP and three quarantined emoji skips).
Eight jobs passed; Calendar Lighthouse Performance 89 failed the 90 budget.
On 28 Oct, a red browser regression demonstrated eager closed-filter option
bindings. The shared filter now mounts options on opening, with unchanged
selection logic and new keyboard/single/multiple-selection coverage. Fresh
local Lighthouse medians pass (Home 96, Approvals 95, Calendar 92); the
first filter opening remains in the 200 ms measured interaction budget.

CI on `59a2c9c` still failed Calendar (Performance 89, median LCP 2,889 ms),
while the other eight jobs passed. Its full Python suite passed 5,536 cases
with one skip and 86.807009% coverage; one full local browser run passed
141 with only three deferred TOTP cases. Those results precede the next fix:
Calendar-only response compression, guarded by five new red-to-green tests
for markup, CSP/CSRF, negotiation, fragments and access boundaries. Fresh
performance and full final-source verification are pending.

CI on `b5a04f0` passed all nine jobs, including Lighthouse after compression
and the public-CSRF-test typing repair. The first local full stability run
still found one intermittent WebKit mocked-OAuth navigation race in golden
path 2 (140 passed, three TOTP skips, one failure). The sequence stopped;
[issue #19](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/19)
tracks its quarantine and harness repair. The invariant test remains unchanged.
The bounded mocked-navigation repair is now present; its verification and the
emoji stability requirement still need three consecutive complete runs.

On resuming 30 Oct, PR #17 remained at `52892bca`. Its CI passed eight jobs,
including 5,541 Python cases with one Redis-only skip and all performance
budgets. E2E failed golden path 3: READY became visible before the platform
posts entered review. [Issue #20](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/20)
tracks the atomic handoff repair and quarantine. One full local browser pass
(144 passed, three TOTP cases pending) predates that repair; the sequence was
paused before its second run and does not satisfy the stability gate.

The handoff fix passed 129 focused Python cases and 18 focused browser cases
(original paths 3, 6 and 8 across all devices). CI's browser jobs are now pinned
to supported Ubuntu 24.04 after `ubuntu-latest` moved to unsupported 26.04.
The first full stability attempt then exposed a serious Calendar keyboard
scrolling defect; [issue #21](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/21)
tracks its deterministic regression and template fix. The interrupted attempts
are recorded separately in the changelog, not counted as complete gate runs.
The keyboard fix passed all 12 focused browser cases (including unchanged
paths 6 and 8) and 11 accessibility/CSP/compression Python cases. Fresh full
stability verification now covers 150 cases, with only three TOTP cases pending.

At `ac164ef`, full CI pytest passed 5,550 cases with one Redis-only skip,
coverage above main, and every performance budget passed. Two full local
browser runs passed 147 cases each with three TOTP cases pending. CI exposed
an overlapping-scroll race in the new Pixel 7 keyboard test; issue
[#22](https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/22) tracks
waiting for native scroll completion without repeating input or weakening
movement assertions. The third local attempt was stopped before completion.
A fresh full stability sequence and normal CI are still required.
The native-event helper has passed controlled ordering checks on Chromium and
WebKit; it preserves one keypress per axis, the movement assertions and a bounded
failure path. Focused verification and fresh complete suites are in progress.
The focused run has now passed all 12 cases across the three device projects
(175.36 seconds). The fresh three-run sequence and normal CI remain pending.

Remaining for the gate:

1. Final-source full pytest with coverage at least main's exact ratio
   (41,054/47,301 statements; 87% when displayed), three consecutive complete
   browser runs with all repaired quarantined cases included, and all nine CI
   jobs green after removing the quarantines. TOTP stays pending for Phase 4.
2. Fresh CI performance measurements with every section 5 budget unchanged.
   All samples and the configured medians are retained as CI artifacts.
3. Gate record: quote section 6 exactly and record final commands, tested
   commit and CI URL, then stop. No merge, release or Phase 2 is authorized.

The added isolation tests cover workspace-B IDs in form bodies and query
strings; existing Agent API tests cover the corresponding foreign-resource
inputs. Independent review found no missing isolation blocker. The original
invariant tests and the three known issues below remain unchanged.

The owner manages the `main` branch ruleset separately. Required job names
are **Lint (ruff)**, **Type check (mypy)**, **Test (pytest)**, **Agency UI state
tests**, **Docker build**, **Secret scan (gitleaks)**, **Dependency audit**,
**E2E (Playwright)** and **Lighthouse CI**. That owner task does not pause
this verification.

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

## Owner-managed work (does not block this Phase 1 continuation)

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
