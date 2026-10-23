# Documentation

Start with the product map, then the document for the part you are working on.
Engineers and coding agents also read [`../CLAUDE.md`](../CLAUDE.md); install
steps and platform credentials are in [`../README.md`](../README.md); how to
contribute in [`../CONTRIBUTING.md`](../CONTRIBUTING.md).

## Current

| Document | What it is for |
|---|---|
| [PRODUCT_MAP.md](PRODUCT_MAP.md) | Every page a signed-in person can reach (who it is for, what it does, what happens next, where the code is), how work flows from an idea to receipts, and every task that runs on its own. |
| [LIVE_OPERATIONS.md](LIVE_OPERATIONS.md) | Running production: the brand workspaces, how approval and publishing behave, the one canonical table of environment variables, verifying a deployment, rollback. |
| [TELEGRAM_CLIENT_HUB.md](TELEGRAM_CLIENT_HUB.md) | Telegram end to end: setting it up, the manager inbox, alerts and the morning briefing, everyday commands, weekly preparation, the boundaries that keep client and private chats separate. |
| [TELEGRAM_CHANNELS.md](TELEGRAM_CHANNELS.md) | Status channels: a broadcast channel that receives fixed status messages for permitted posts and nothing else. |
| [OPENDOTS_INTEGRATION.md](OPENDOTS_INTEGRATION.md) | The task controls (pause, resume, retry after review) adapted from OpenDots, what was deliberately not adopted, and how the adaptation is verified. |

## Archive

`archive/2026-10/` keeps the status, audit and launch documents written in
early and mid October 2026, before the always-on manager (Home as a
conversation, routines, the Telegram manager inbox, Set up) was built. They are
kept as a record and are not updated; where they describe a screen, the
product map is current.

| Document | One line |
|---|---|
| [CTO_AGENCY_READINESS.md](archive/2026-10/CTO_AGENCY_READINESS.md) | 12 Oct handoff: activation gaps, recovery and the pilot plan for the agency before the always-on build. |
| [CTO_IMPLEMENTATION_STATUS.md](archive/2026-10/CTO_IMPLEMENTATION_STATUS.md) | 12 Oct: the 15 critical-review findings mapped to the behaviour that answered them. |
| [GUIDED_POST_CREATION.md](archive/2026-10/GUIDED_POST_CREATION.md) | 12 Oct: the guided thread flow as first built (today it is Home's conversation). |
| [NEOPOLIS_LAUNCH_AUDIT.md](archive/2026-10/NEOPOLIS_LAUNCH_AUDIT.md) | 12 Oct backend audit: failure, concurrency and usage regressions, remaining live gates. |
| [NEOPOLIS_LIVE_PILOT_WORKSHEET.md](archive/2026-10/NEOPOLIS_LIVE_PILOT_WORKSHEET.md) | Worksheet for the 19–25 October pilot week: evidence to record, gates, acceptance. |
| [SM_BEAN_GUIDED_WORKFLOW.md](archive/2026-10/SM_BEAN_GUIDED_WORKFLOW.md) | 14 Oct user guide to "Start a post" (today: Home). |
| [TELEGRAM_RAILWAY_ROLLOUT.md](archive/2026-10/TELEGRAM_RAILWAY_ROLLOUT.md) | 13 Oct controlled-release runbook for the first single-worker release. |
| [TELEGRAM_RAILWAY_RELEASE_RECEIPT.json](archive/2026-10/TELEGRAM_RAILWAY_RELEASE_RECEIPT.json) | 12 Oct pending production receipt for a historical source commit. |
| [audit/LAUNCH_READINESS_2026-10-01.md](archive/2026-10/audit/LAUNCH_READINESS_2026-10-01.md) | 1 Oct launch readiness audit. |
| [audit/LAUNCH_REVIEW.md](archive/2026-10/audit/LAUNCH_REVIEW.md) | Three independent launch reviews of the first PR. |
| [audit/GAPS.md](archive/2026-10/audit/GAPS.md) | The gap register from the audit rounds. |
| [audit/QA_ROUND1_RESPONSE.md](archive/2026-10/audit/QA_ROUND1_RESPONSE.md), [audit/QA_ROUND1_RETEST_REPORT.md](archive/2026-10/audit/QA_ROUND1_RETEST_REPORT.md) | QA round 1 (27 Sep): the engineering response and the retest report, with the two spreadsheets beside them. |
| [audit/LAUNCH_READINESS_2026-10-13.md](archive/2026-10/audit/LAUNCH_READINESS_2026-10-13.md) | 13 Oct release review: supervised operator beta. |
| [audit/USER_REVIEW_2026-10-13.md](archive/2026-10/audit/USER_REVIEW_2026-10-13.md) | 13 Oct 50-criterion review from the owner, approver, producer, client and support perspectives. |
| [audit/CTO_LAUNCH_DECISION_2026-10-13.md](archive/2026-10/audit/CTO_LAUNCH_DECISION_2026-10-13.md) | 13 Oct launch decision. |
| [audit/LAUNCH_FIX_VERIFICATION_2026-10-13.md](archive/2026-10/audit/LAUNCH_FIX_VERIFICATION_2026-10-13.md) | 13 Oct verification of the launch fixes on the deployed services. |
| [audit/RAILWAY_BUILD_BLOCKER_2026-10-13.md](archive/2026-10/audit/RAILWAY_BUILD_BLOCKER_2026-10-13.md) | 13 Oct: why the hosted build failed and how it was fixed. |
| [audit/RELEASE_STATUS_2026-10-13.json](archive/2026-10/audit/RELEASE_STATUS_2026-10-13.json) | 13 Oct machine-readable release status. |
| [audit/NEOPOLIS_WEEK_2026-10-19.md](archive/2026-10/audit/NEOPOLIS_WEEK_2026-10-19.md) | Preparation worksheet for the 19–25 October week. |
| `audit/evidence/2026-10-13/` | The JSON and screenshots the 13 October documents cite. |
