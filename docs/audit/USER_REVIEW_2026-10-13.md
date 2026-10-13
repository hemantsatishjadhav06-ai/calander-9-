# Critical agency-user review — 13 October 2026

This is a 50-criterion review from the perspectives of an agency owner, backup approver, producer, client and support operator. It is not evidence that 50 people used the app. The uploaded October source and its earlier reports were inspected first; their historical passing counts are not carried forward as proof of this integrated revision.

The useful product is one client conversation for ideas, references, questions, draft preparation and permitted status. It still needs an authenticated person to confirm preparation, and a current approver to approve the exact finished content, destination and time. A client's sign-off does not grant agency publication authority.

## Evidence and limits

- **Source reviewed** means the current implementation or interface was inspected; the real provider transaction remains unverified.
- **Controlled test** means a current local regression passed with synthetic records or controlled providers.
- **Browser checked** means Chromium exercised local Django with synthetic records. It does not prove real Telegram, model output or publication.
- **Live observation** records a narrowly observed real endpoint response, not a whole rollout.
- **Open acceptance** requires a real deployed, authenticated client/team/provider journey.

Fresh evidence: 83 current local provisioning/onboarding/UI tests passed; a later 17-test UI run includes the managed creation route and overlaps that run, so the counts are not added as unique coverage. The final Chromium pass exercised **49 checks, all passing**, with zero JavaScript page errors, failed network requests or HTTP 5xx. Expected 400/403 responses exercised invalid manager capability and forbidden full-app access. The actual magic-link client journey was included, not inferred from a full-app client login. Bot API replies, sources and account-manager output were controlled synthetic providers. See [browser evidence](evidence/2026-10-13/browser-review.json). The uploaded `TELEGRAM_50_POINT_REVIEW.md` remains prior evidence; its historical counts are not substituted for this run.

Root's real read-only observation identified `@sammanager06_bot` and reported `can_manage_bots=false`. The production health/login pages responded, but the deployed application's exact source revision and authenticated end-to-end workflow have not been established. No production login was invented.

## What was wrong before this pass

The settings page mixed personal identity and group pairing into one purpose/audience form, offered combinations the backend refused, hid field-specific errors and required every person to copy a command manually. It lacked an adoption-oriented sequence, a visible lead/backup next step, and a concise command guide. An inactive saved bot still presented pairing as an available next step. Reconnecting a bot also showed the approval preference unchecked regardless of its saved value. A second real-client adoption gap emerged: invited clients use scoped passwordless portal sessions, which correctly reject full-workspace settings. The initial full-app client tests did not exercise that path. A portal-only personal Telegram page and pairing/unpairing routes were added so existing clients do not need a usable password or internal app access.

The October 1 launch fixes must survive the cumulative merge. The only onboarding template conflict combined DEV.to and X descriptions; both are retained, along with DEV.to's actual API-key form. Locally served, integrity-verified browser libraries remain in place.

## The 50 criteria

| # | User's concrete question | Before / risk found | Current result and evidence |
|---|---|---|---|
| 1 | Can I understand the next setup action without reading an operator runbook? | Bot, identity and group controls were mixed together. | Browser checked: staged bot → personal account → separate groups, with visible prerequisites. |
| 2 | Does every client have an isolated bot and workspace? | Reusing a token could redirect another client/application. | Source reviewed: unique bot identity and workspace connection; foreign webhook protection. No shared-bot shortcut is advertised. |
| 3 | Can the app create a client bot for me? | Original UI only connected an existing BotFather token; claims of silent automatic creation would be false. | Controlled test and browser checked: tenant-bound manager selection → fresh consent URL → inspectable status. A capable Telegram manager is required; real creation remains open acceptance. BotFather fallback remains explicit. |
| 4 | Is the supplied trial bot actually eligible to manage client bots? | A handle or valid token was not proof of manager capability. | Live observation from root: `@sammanager06_bot` has `can_manage_bots=false`. It cannot enable managed creation until Telegram grants that capability. |
| 5 | Can an invited client link Telegram in one clear action? | Everyone had to copy `/start` manually. | Controlled test and browser checked: fresh personal responses provide a direct Start link plus command fallback; GET does not redisplay it. Both full-app and actual passwordless portal sessions were exercised. |
| 6 | Can a creation/link code be reused, forwarded or recovered from page history? | A convenience link must not weaken pairing boundaries. | Source reviewed: digest-only one-use tickets, ten-minute expiry, no-store responses and same-origin referrer policy. Fresh deep links are issued only in the requesting POST response. |
| 7 | Can client/staff HTML reveal the bot token? | Setup errors or password redisplay could leak credentials. | Source reviewed: password input never redisplays token; encrypted saved credentials; no token in pairing links. Current token-hiding controlled and browser checks passed. |
| 8 | Can I accidentally select a private audience for a group? | Mixed selectors offered an impossible combination. | Separate forms; group options contain only client/team; malformed combinations get visible validation errors before a ticket is issued. |
| 9 | Can I pair a group before my own identity is established? | The old page offered the action before its prerequisite. | The group action is disabled until the caller is personally paired; backend permission/admin checks remain authoritative. |
| 10 | Does an inactive bot misleadingly appear ready for client use? | Pairing controls remained active although the webhook was inactive. | Clear inactive setup message and disabled pairing actions; a configured bot is not represented as proof that replies arrive. |
| 11 | Can a workspace-only external client use the page? | Internal settings and language risked overwhelming clients. | Controlled and browser checked: actual unusable-password magic-link clients reach a portal-only personal pairing page, without token/group/admin controls. Grant revocation denies the page; full-app access stays forbidden. |
| 12 | Can staff brainstorm without silently starting production? | Ordinary team remarks might be treated as AI job/approval instructions. | Source reviewed: explicit `/brainstorm` and `/brief`; ordinary remarks and ordinary “yes” do not authorize preparation/publication. |
| 13 | Can I establish the head and backup review responsibilities? | The connection page did not lead to existing approver settings. | The internal setup links to current lead/backup settings and requires each person to pair their own identity. No fictional staff identities are created. |
| 14 | Can a username, bot sender or forwarded author impersonate a member? | Telegram display names are not authentication. | Source reviewed: current human numeric identity and scoped paired private chat authorize actions. Live identity acceptance remains open. |
| 15 | Can a non-admin or unapproved viewer join the wrong group boundary? | Group membership was easy to overlook. | The caller must attest membership; real administrator proof is checked when consuming a group code. Passive viewer enumeration is explicitly unavailable. |
| 16 | Can client and internal groups silently switch audience? | A rebind could expose team history to a client. | Source reviewed: explicit deactivation/re-pairing and fixed audience boundaries; separate groups are required in setup. |
| 17 | Does removing a staff member actually remove Telegram authority? | Pairing could otherwise outlive application membership. | Source reviewed: fresh membership, active-user/workspace/org and permission checks; epoch/invalidation handling belongs to current lifecycle regressions. |
| 18 | Can a colleague read my preceding private Telegram history through the web app? | Prior cumulative work found cross-interface private-history leaks. | Source reviewed: durable private-history state and shared-surface guards. Historical reports are not counted as fresh verification. |
| 19 | Does forwarding a private attachment imply permission to share it? | Inherited captions could falsely imply consent. | Source reviewed: current person's explicit `/reference shared` choice is required; the UI states that shared-library/publishing storage is a separate audience. |
| 20 | Will the bot see every ordinary message in a Telegram group? | A “one place” promise could conceal Telegram privacy-mode behavior. | The command guide states to use commands, mentions or replies; ordinary messages may not reach the bot. |
| 21 | Does `/brainstorm` clearly mean discussion rather than delivery? | Commands were not explained on the web setup page. | A concrete quick guide now distinguishes brainstorming, briefing, references, status and review. |
| 22 | Does the account manager ask missing brief questions in the same thread? | Generating from a vague request risks inaccurate content. | Source reviewed: guided question/summary flow; current guided engine tests and actual model quality remain separate acceptance. |
| 23 | Can an ordinary “yes” publish or approve something? | Ambiguous conversational consent is dangerous. | Source reviewed: exact current review actions are required; client/staff remarks do not supply approval. |
| 24 | Can I distinguish brief confirmation from finished-post approval? | Similar confirmation language increases friction and mistakes. | Setup and guided controls state the distinction directly: preparation first, finished version/destination/time approval later. |
| 25 | Does a changed source, photo, account or revision invalidate old review? | A stale card can approve a different payload. | Source reviewed: current scoped snapshots, revisions and source/provenance checks. Real phone stale-card exercise is open. |
| 26 | Can the head inspect exactly what and when will be published? | A friendly conversation is insufficient final review. | Source reviewed: exact review cards and full SM Bean review for complex content; human authority remains permission-scoped. |
| 27 | Are unsupported formats honestly explained? | “Everything in Telegram” would overpromise multi-graphic/complex review. | The guide explicitly sends complex formats to the full review and does not claim voice/video transcription or PDF extraction. |
| 28 | Does `/stop` mean what the user expects? | Stopping a chat job could be confused with cancelling a scheduled post. | The guide and source limit it to the caller's pending assistant requests in that conversation; publication controls are separate. |
| 29 | Can a missed proposed time send late content anyway? | Late automatic publication damages trust. | Source reviewed: deadline/hold and renewed human review; controlled current delivery tests are owned by the reliability pass. |
| 30 | Is a successful queue response falsely shown as native publication? | “Publish now” is not a delivery receipt. | Source reviewed: per-account status and native receipts, unknown/expired outcome labels; real social-provider acceptance is open. |
| 31 | Are website and native-channel excerpts treated as facts? | Scraping does not verify price, availability or registration claims. | Source reviewed: evidence timestamps/warnings and human verified claims; guided source warnings remain visible. |
| 32 | Can a former verifier's or expired commercial claim remain trusted? | Claims can outlive their evidence or authority. | Source reviewed: expiry/current verifier permissions and fresh review; real client fact inventory remains open. |
| 33 | Is an uploaded photo proof of a named property? | Agency users can mistake any supplied picture for authenticated evidence. | Source reviewed: file/project attestation and provenance controls; the UI labels selections and links to fact/photo review. |
| 34 | Can generated property images be passed off as authentic? | Rendering quality does not establish authenticity. | Source reviewed: illustrative/unverified provenance and code-owned final caption disclosures. A person still reviews final copy. |
| 35 | Can oversized, deceptive or active files enter the reference pipeline? | Intake needs real file validation, not filename trust. | Source reviewed: byte/pixel limits, MIME/decode checks and restricted file types. Current upload regressions remain distinct from design quality. |
| 36 | Will PDFs or voice notes automatically become verified briefs? | Prior product language could suggest extraction/transcription. | Explicit PDF fact-paste instruction and unsupported voice/video boundaries; passive reference storage is not verification. |
| 37 | Are generated graphics actually good enough for this client's campaign? | Passing source/tests cannot establish aesthetics or accurate brand depiction. | Open acceptance: generate with actual model/image services and compare final creative against approved client facts and references. |
| 38 | Can external source text become instructions to the agency? | Web/reference content is untrusted. | Source reviewed: bounded evidence is labeled untrusted; source inspection is not proof against every semantic model failure. |
| 39 | Can channel-specific shortening lose required claims/disclosures? | A short caption may omit essential text. | Source reviewed: final payload/source loss checks and channel-specific disclosures; inspect final native payloads in the pilot. |
| 40 | Can the client see the correct week and time zone? | Dates can be misread across web, bot and client phones. | Source reviewed: offset-aware scheduling and weekly selection. Open acceptance: compare India-time plan, phone review and native posting receipt. |
| 41 | Does weekly preparation falsely claim to have performed audience/performance analysis already? | Source/configuration review is narrower than a completed AI plan. | Source reviewed: the preliminary weekly evidence is labeled as such; stages run after preparation confirmation. |
| 42 | Does a weekly request publish the whole week automatically? | Batch planning could bypass individual review. | Source reviewed: queue preparation requires scoped confirmation; each final post retains human approval. |
| 43 | Is the displayed AI budget a guaranteed spending cap? | In-flight/unreported provider costs can exceed an estimate. | Source reviewed: soft-budget labeling and estimated charges; real provider credit/usage acceptance is open. |
| 44 | Can duplicate webhooks or competing workers produce duplicate paid work? | A smooth UI can hide duplicate processing. | Source reviewed: durable ingress claims/idempotency and worker lease; current controlled reliability regressions are required. |
| 45 | Does an uncertain Telegram or social send automatically retry into a duplicate? | A provider may have accepted a send before a network failure. | Source reviewed: uncertain sends require inspection; settings distinguish failures from unknown outcomes. Real recovery exercise remains open. |
| 46 | Can a client use the forms at 390 pixels without horizontal overflow? | Long codes, errors and setup details can break a phone layout. | Browser checked at 390-pixel phone, 800-pixel tablet and desktop sizes: no document overflow. Telegram navigation is visible immediately on a phone; long codes/errors wrap. |
| 47 | Can a keyboard/screen-reader user identify fields, errors and current actions? | Old group-purpose UI hid field errors and used nested labels. | Controlled and browser checked: associated labels, visible errors/status, reachable keyboard link, distinct group/personal forms, and native required fact checkbox before preparation. |
| 48 | Can support identify a useful next action without exposing client transcripts? | Generic failures encourage blind retry and sensitive screenshots. | Source reviewed and browser checked: inspectable setup status and clear next steps; unknown sends still require native inspection. Support staffing/SLA is not implied. |
| 49 | Is the accessible live site running this reviewed revision? | Public health/login success could be mistaken for a completed release. | Open acceptance: record exact web/worker source SHA, migration/worker health and authenticated client journey. Public 200 responses alone do not establish it. |
| 50 | Can the agency responsibly launch and promise delivery next week? | Historical local counts and uploaded source are not production/client acceptance. | Open acceptance: matching deployed services, real bot/group identities, actual creative quality, human phone review and native receipts. No unconditional launch-ready claim is made. |

## Telegram capability finding

The initial assumption that every bot must always be created manually through BotFather is incomplete for the current Telegram platform. Telegram's official source now includes a user-confirmed managed-bot path:

- `KeyboardButton.request_managed_bot` and the `managed_bot` update are present in Telegram's own Bot API implementation.
- A manager with `can_manage_bots=true` can request creation. Telegram asks the human to confirm; this is not silent arbitrary bot creation.
- The documented implementation generates `https://t.me/newbot/<manager>/<child>?name=<name>` and can retrieve the child token through `getManagedBotToken`.
- A client's separate bot does not imply that Telegram groups were also created. Group creation and ongoing viewer membership remain human-controlled.
- Reusing one bot across workspaces is not a supported shortcut in this application; its bot identity is globally unique.

Authoritative source references inspected with TLS verification on this pass:

1. [Telegram Bot API method registry and managed-bot update serializer](https://github.com/tdlib/telegram-bot-api/blob/master/telegram-bot-api/Client.cpp): method registry, `JsonManagedBotUpdated`, `request_managed_bot`, `process_get_managed_bot_token_query`.
2. [Official TDLib schema](https://github.com/tdlib/td/blob/master/td/generate/scheme/td_api.tl): `internalLinkTypeRequestManagedBot`, `createBot`, `getManagedBotToken`, `userTypeBot.can_manage_bots`.
3. [Official TDLib link generation](https://github.com/tdlib/td/blob/master/td/telegram/LinkManager.cpp): `internalLinkTypeRequestManagedBot` link builder.

The `core.telegram.org` documentation pages returned HTTP 403 from this environment. Their content was not claimed as retrieved. No authoritative enabling-menu labels or manager privilege-grant method were found in the inspected public schema; use a genuinely capable manager or the BotFather fallback rather than inventing a toggle or capability.

## Live pilot still required

Run the current deployed revision with one actual lead, a different backup approver and one external client. Pair their own identities, then separate client/team groups with current admin proof. Confirm actual replies, one source-backed post and weekly evidence, a complete draft/graphic, exact phone approval and native publication receipt. Test a membership removal and one uncertain-send recovery. Record the actual source SHA and outcomes; do not substitute a synthetic demonstration for this evidence.

## Representative browser evidence

These screenshots contain synthetic people, bot identities, a blank test photo and local one-use codes. They establish the interface and permission flow, not real model/Telegram output or graphic quality. The temporary client/session grants are removed after inspection.

- [Passwordless client portal on a phone](evidence/2026-10-13/telegram-passwordless-portal-mobile.png): Telegram navigation and direct personal link.
- [Controlled managed-bot consent on a phone](evidence/2026-10-13/telegram-managed-consent-mobile.png): human confirmation and pending status.
- [Guided brief and source review on a phone](evidence/2026-10-13/guided-thread-mobile.png): source warning, required fact checkbox and visibly unverified photo.
