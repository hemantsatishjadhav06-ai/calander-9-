# Telegram client hub and SM Bean weekly planning

Prepared 12 October 2026, Asia/Kolkata, on `codex/telegram-client-hub`. **This is local implementation guidance, not proof of production activation.** SM Bean remains the source of truth for conversations, generated drafts, human reviews, schedules and delivery receipts. Telegram is a permitted interface to those services, not a second AI agency or an external SM Manager import.

The Neopolis target week is **Monday 19–Sunday 25 October 2026**, in `Asia/Kolkata`. No actual production weekly plan, approval or schedule has been changed during this work. The local development database has zero workspaces; the production Neopolis UUID is absent. Test/browser fixtures are not production client data.

## Choose the workspace and audience

Use one brand bot connection per workspace, with a distinct client group, internal team group and private paired chats. A head/manager who works across brands pairs separately with each workspace's bot; membership in one does not grant access to another. Private worker conversations belong to the paired person and stay separate from the client thread.

A Telegram numeric user ID is paired to a currently active SM Bean member using a short-lived one-use code issued while signed in. Usernames, group titles, forwarded messages and anonymous `sender_chat` identities do not authorize work. Group activation requires a paired authorized manager and a real Telegram admin check. Revoked roles, removed membership, inactive pairings, archived workspaces and deleting organizations stop further actions.

Client groups receive client-visible conversations and already shared review/publication material. They receive no internal notes, raw audience analysis, AI costs, credentials, claim-verification controls or unrelated private conversations. Even a staff member asking `/week` in a client group receives the client-safe summary. Keep preparation and budget/source analysis in a team/private chat.

Telegram does not enumerate all passive group viewers. Control team-group membership as an operator, remove unauthorized people and consider existing group history when revoking access. Bot authorization prevents unauthorized commands; it cannot make messages already seen by passive viewers private again.

## Human setup and deployment

Private transcripts and their raw job/run details are accessible through their paired Telegram identity, not ordinary Studio or portal pages, even for that person's web login. A persistent privacy marker protects old history after disconnects and role changes. Private requests needing a human ask the person to share an appropriate summary in the intended client/team group; the bot does not silently broadcast the private request or promise an inaccessible human reply.

Photos and PDFs use the shared brand media library and publicly accessible publishing storage, including before post approval. In a private chat, resend your own file with the exact caption `/reference shared` (optionally followed by a space and a note) only when you intend that sharing. Without it the file is not downloaded or saved; inherited forwarded captions do not establish consent. Private plain UTF-8 text remains a bounded conversation excerpt without a new media asset. Group references retain their shared-workspace behavior. Sharing a reference never verifies its factual claims or approves publication.

1. If the intended brand bot does not exist, create it through **BotFather**. Create the client/team Telegram groups, add the bot and configure intended human admins. The Bot API cannot create new bots or groups. A supplied token is not verified until its identity and webhook state can be read successfully.
2. Deploy the reviewed cumulative code to both Railway services, apply all migrations including the new Telegram app migration, and confirm the public HTTPS app/webhook endpoint. Keep model settings and encrypted app credentials consistent. Do not register a loopback/undeployed webhook or overwrite an unrelated bot webhook.
3. Activate the saved cloud networking configuration and verify runtime access. `api.telegram.org` was added to a saved cloud draft; it has not been published and that addition did not change this running environment. Telegram `getMe`/`getWebhookInfo` probes returned `ProxyError`; no webhook or message was activated/sent. Model/image/website/Meta access needs separate verification.
4. Under the workspace's **Agency → Telegram** page, enter the intended token securely, validate the bot identity and webhook ownership, then pair the human accounts and chats. Never paste tokens into posts, documents, screenshots or team conversations. Failed validation must not destroy a previously working connection.
5. Decide whether to enable final Telegram publication approvals. This is a separate opt-in setting; preparation works through current authorized pairing, while final approvals use an explicit verified-human Telegram actor. Clients' sign-off cannot create an internal publication approval.
6. Drain the old worker before a first singleton-lease rollout, reserve its additional PostgreSQL connection, and start one compatible worker with a restart policy. Confirm task-specific agency/publisher/confirmation success and Telegram processing/outbox progress. A long source/model/image call can still occupy the single worker; do not promise a strict response or delivery deadline.

The deployed web and worker services need the same public origin:

```dotenv
TELEGRAM_WEBHOOK_BASE_URL=https://sm-bean-production-eb50.up.railway.app
TELEGRAM_WEBHOOK_READY=false
```

Deploy first, confirm the webhook route exists and a wrong-secret POST returns 403, then set `TELEGRAM_WEBHOOK_READY=true` before connecting the bot. Bot credentials belong in the workspace's encrypted connection form; there is no shared global token for all brands. The separate cloud networking draft must be reviewed, saved and published in environment settings to affect future cloud access; it does not configure Railway.

Telegram group privacy mode normally delivers commands, mentions and replies directed to the bot. Use those for the initial rollout. Reading every ordinary group message requires a deliberate BotFather privacy/admin configuration and informed group membership; it is not silently enabled here. The bot does not scrape inaccessible Telegram history or arbitrary channels. Automatic completion notices for a Telegram-requested week go only to its original internal team/private conversation; `/week` remains the current status view.

Railway/OpenRouter runtime credentials are unavailable in this environment. There is no proof here of live model balance, Telegram bot identity, native social permissions or production publication. See [CTO readiness](CTO_AGENCY_READINESS.md) and [safe operations](LIVE_OPERATIONS.md).

## Everyday use

The hub supports brief discussion, brainstorming, photo/design references, status, weekly summaries, review and changes through the existing agency conversation and services. Commands include `/help`, `/brainstorm`, `/brief`, `/reference`, `/status`, `/week`, `/approvals`, `/post` and `/stop`; unsupported commands are refused clearly. Genuine Telegram photos/documents use bounded official file download, decoding and tenant-scoped storage. Video/voice transcription is not promised without an implemented configuration.

A casual staff reply remains a person's reply. Staff explicitly asking the AI team in a client conversation use the canonical account manager. Client requests stay client requests: they do not impersonate the lead or bypass staff creative confirmation. An ordinary “yes” or a model's text never grants draft confirmation or publication approval.

Before final publication, the review action shows the actual revision, graphic, platform caption, native destination and future time. One-use buttons are bound to the paired actor, chat, bot, workspace and exact snapshot. Changing source/content/destination/time requires the applicable fresh review. Unknown/expired social outcomes stay held for human account inspection; a human-recorded existing-post receipt is an attestation, not independent provider confirmation. An uncertain Telegram send also needs inspection rather than an automatic duplicate.

## Review and prepare the 19–25 October week

1. Use `/week 2026-10-19` for a DB-only summary of the requested volume, existing work and current plan stage in a team/private chat. In a client group it shows only content already shared through the client review/publication workflow. Proposed times are labeled as proposals, distinct from actual scheduled/published times.
2. A currently paired internal manager uses `/week prepare 2026-10-19`. Preparation collects the saved website and selected connected-channel evidence outside database locks, plus current source-backed claims, designer-selected references, available slots, measured-history availability, existing drafts and soft budget. This is a reviewable source/configuration analysis, **not a completed AI strategic analysis or generated week**.
3. Inspect the source freshness/fallback labels, missing facts, claim expiry through the target week, actual accounts, references and costs. The card shows the selected bounded evidence: up to 500 website characters and two recent caption excerpts per account, with selected/collected counts. Those selected excerpts also go to the planner. Website/caption excerpts and designer references remain untrusted evidence; they are not instructions or automatically verified commercial claims. A missing website or stored-history fallback is explicitly disclosed. Critical setup blockers prevent queueing; fact gaps require the person's reviewed confirmation and safe omission/owner follow-up. If the complete relevant review exceeds one Telegram card, no button is issued: review the full administrative `--prepare` output or use dashboard planning rather than confirm a silently truncated card.
4. Use the explicit **prepare week** confirmation button to queue SM Bean's canonical `listen → moments → plan → brief` workers. The signed review snapshot expires after 30 minutes and is actor/chat/workspace/week-bound; its large token stays in the one-use action record, never in Telegram callback data. Changed facts, references, destinations, settings, role or existing work require fresh review. The worker checks the reviewed context before paid stages and before creating briefs; a delayed/expired review can need operator attention.
5. Existing target-week posts and produced/in-progress drafts count toward configured volume before extra content is requested. One workspace/week claim prevents repeated buttons or an overlapping tick from starting another plan. New extra volume is bounded to at most 14 configured posts; partial/failed work is inspected rather than silently replaced. A completed plan with shortfalls does not trigger an unlimited paid top-up loop.
6. The canonical planner analyzes available performance, scrubbed audience questions, timely moments and reviewed untrusted website/channel/reference evidence. Missing insights are recorded honestly. Holiday dates without verified research remain uncertain; do not copy fixture dates into a real campaign. The existing graphic pipeline uses brand direction and curated references, while actual commercial claims and authentic project imagery need current owner verification.
7. Drafts appear for human review with proposed slots. This action **does not approve or schedule them** and does not switch recurring autopilot on. A person approves each final revision, exact native account and posting time. Verify actual native receipts, delivered lead/backup notices and a report before calling the live week complete.

The configured recurring autopilot continues its separately authorized planning workflow; this manual Telegram preparation does not add a new approval loop to recurring draft generation. Final publication always retains human approval.

## CTO command and integration contract

The management command is read-only by default and requires an exact real workspace plus a current active member. Replace the example email with the actual paired member. There is no workspace-name/fixture fallback.

```bash
python manage.py telegram_week_plan --workspace b1cb458c-cfaf-43cf-8e23-f5e18a9717c7 --actor-email approver@example.com --week-start 2026-10-19 --json
```

For source review, add `--prepare --chat-id <already-paired-numeric-id>`. Inspect the result separately, then use `--queue --chat-id <same-id> --analysis-token 'TOKEN_FROM_REVIEW'`. `--prepare` and `--queue` cannot be combined; queueing without a reviewed token is refused. Keep the internal review output out of client groups. Use Telegram's actor-bound button for normal operation rather than sharing the token.

Consumer APIs in [weekly.py](../apps/telegram/weekly.py):

- `summary(workspace, week_start=None, user=..., audience=...)`: tenant/role-filtered DB summary.
- `summary_text(...)`: bounded human text for status/week commands.
- `queue_week_plan(link, chat, week_start=None, confirmed=False)`: source/configuration preview, warnings and signed token.
- `queue_week_plan(..., confirmed=True, analysis_token=...)`: current paired-manager confirmation, canonical plan queue only.

The plan remains associated with the requesting chat's canonical conversation for permitted progress/receipt routing. The narrow [planner hook](../apps/studio/jobtypes/plan.py) consumes bounded reviewed evidence as untrusted notes; nothing is attached merely to imply unused evidence was analyzed.

## Telegram versus Slack

| Choice | Practical tradeoff |
|---|---|
| Telegram | Low-friction client participation and photos on phones. This implementation provides paired bot commands and review controls, but operators must manage group viewers/history and inspect uncertain sends. Bot/group creation remains manual. |
| Slack | Often suits an agency's existing internal channels, threads and administrative/audit processes. Retention, guest/admin features and costs depend on the actual plan. It needs its own installed app, identity/event/approval transport and acceptance work; this Telegram implementation does not provide a Slack hub. |

Keep SM Bean's records and approval rules as the common source of truth whichever communication app is used. Choose based on where this client/team already works and the required membership/history controls, rather than replacing publication safeguards with chat messages.

## Validation limits

Telegram transient-content retention is configurable: update payloads default to seven days, delivery payloads to 30 days and action snapshots to 30 days; expired pairing records are removed after one day. Settings are `TELEGRAM_UPDATE_RETENTION_DAYS`, `TELEGRAM_DELIVERY_RETENTION_DAYS`, `TELEGRAM_ACTION_RETENTION_DAYS` and `TELEGRAM_PAIRING_RETENTION_DAYS`. Clearing an old payload does not clear an unknown-delivery hold: status, semantic source key, native IDs and safe error remain. Action actor/digest/result/use records remain, and canonical conversations/approval audits follow their own retention. These defaults are not a certification of Telegram/model/social-provider retention or training policies.

Focused weekly tests exercise real PostgreSQL/canonical planning, reviewed source propagation, existing-content volume, duplicate claims, changed evidence, revoked roles, private/client boundaries and default read-only commands. All source/model/provider boundaries are controlled. Final Telegram/full-repository results belong to the root validation record, not overlapping focused totals.

The live acceptance gates remain actual bot/webhook identity, deployed services/migrations, member/admin pairing, model/image/Meta access, verified facts/assets, a completed useful campaign, real human approval and exactly-once native receipt, delivered alerts, realistic costs and a phone/keyboard walkthrough. No fixture, saved networking draft or queued local job establishes that the production Neopolis week was updated.
