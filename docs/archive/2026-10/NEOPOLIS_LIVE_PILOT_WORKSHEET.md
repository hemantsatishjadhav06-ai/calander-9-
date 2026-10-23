# Neopolis live pilot: 19–25 October 2026

**Status: waiting for production access and real acceptance evidence.** This worksheet completes the operational handoff; it does not claim deployment, activation, generated Neopolis posts or publication. Source code and local tests are complete. Use SM Bean's own AI workers for the campaign, and keep final publication behind a human review.

Workspace: `b1cb458c-cfaf-43cf-8e23-f5e18a9717c7`. Week: Monday 19 through Sunday 25 October, `Asia/Kolkata`. Database time window is **18 October 18:30 UTC inclusive to 25 October 18:30 UTC exclusive**. Preserve already produced content before generating extra volume.

[Open Neopolis approvals](https://sm-bean-production-eb50.up.railway.app/workspace/b1cb458c-cfaf-43cf-8e23-f5e18a9717c7/calendar/?mode=list&tab=approvals) · [Open Neopolis Telegram setup](https://sm-bean-production-eb50.up.railway.app/workspace/b1cb458c-cfaf-43cf-8e23-f5e18a9717c7/agency/telegram/) · [Open SM Bean](https://sm-bean-production-eb50.up.railway.app/)

## 1. Record deployment and configuration evidence

| Gate | Evidence to record | Current acceptance |
|---|---|---|
| Both Railway services run the same reviewed commit; migrations finish; old baseline worker is drained before the first singleton-lease rollout. | Web commit: ___; worker commit: ___; migration result: ___; worker restart time: ___ | Pending |
| Text and vision turns use OpenRouter on both services. | `STUDIO_PROVIDER=openrouter`; namespaced `STUDIO_MODEL`; securely bound key; useful schema-valid model turn ID and billing check: ___ | Pending |
| Graphics can use current authentic project assets or a separately configured image service. | Project/media IDs and current attestation: ___; if generation is used, fal.ai credit/model/result evidence: ___ | Pending |
| Correct native social destinations and public media access are established. | Actual Facebook Page ID: ___; actual Instagram numeric ID/handle: ___; live permissions/access result: ___ | Pending |
| Publisher, agency, confirmation and Telegram cycles process successfully after restart. | Fresh task-specific successful processing, not only registered task count: ___ | Pending |

OpenRouter does **not** configure image generation. Current generated-picture integration uses `FAL_KEY` and `FAL_IMAGE_MODEL`; the default is `fal-ai/flux/dev`. Without it the renderer can produce an explicit brand-background graphic. A successful fallback is insufficient acceptance for a property campaign that needs authentic site or listing photographs. Generated imagery stays illustrative and cannot prove a named project's appearance.

The existing `python manage.py live_verify --strict --json` checks the deployed app. It includes a temporary storage write/read/delete and rolled-back fixture checks, as well as live identity reads; it is not a purely read-only database inspection. It never publishes a real post. Configuration/key presence cannot prove real credits, usable graphics or publication. The [read-only release inspector](../../../tools/telegram_release_inspect.py) inspects DB/configuration without those external calls; follow the [controlled Railway rollout](TELEGRAM_RAILWAY_ROLLOUT.md).

## 2. Establish the client/team Telegram boundary

The supplied test handle is `@sammanager06_bot`; its live identity still requires verification. It is a bot handle, not a human recipient or group ID. A bot token alone cannot create human-managed bots or groups.

1. Deploy the HTTPS webhook route with `TELEGRAM_WEBHOOK_READY=false`. Confirm a wrong-secret request is rejected with 403. Set readiness true, then use **Agency → Telegram** to connect the intended bot through its encrypted form. Record actual bot ID, owned webhook and active connection state.
2. The head signs in to Neopolis, creates a one-use personal code and sends `/start CODE` privately to the bot. Each worker and client pairs their own active SM Bean identity separately. Expired/reused codes must be refused.
3. A paired manager who is a real Telegram group admin creates separate **internal team** and **client** groups, adds the bot and uses the corresponding one-use `/pair CODE`. Review all passive viewers and group history; the Bot API cannot enumerate every viewer. Do not reuse a group for the other audience.
4. Prove one permitted team question, one client remark and one private worker exchange reach their correct canonical SM Bean conversations. The client must not see internal costs/source reviews or worker private transcripts. A revoked identity must stop new commands and approval actions.
5. Enable Telegram publication approvals only with the workspace's exact human review gate enabled. A client can complete the client sign-off stage after the internal review, but cannot originate approval or select a new schedule.

Default group privacy mode handles bot commands, mentions and replies. Reading every group message needs a deliberate, informed BotFather/admin configuration. It does not grant access to old Telegram history or arbitrary channels.

Private photos/PDFs enter shared brand publishing storage only when the person resends their own file with `/reference shared` (optionally followed by a space and a note). Forwarded captions do not count as their consent. Those files can become publicly accessible before publication approval; choose suitable shared assets. Private text remains protected conversation material.

| Boundary | Real acceptance evidence |
|---|---|
| Head + worker + client personal pairing | Permitted numeric identities linked to current active membership; no usernames used as authority: ___ |
| Separate team and client group pairing | Group/admin/audience proof, membership reviewed: ___ |
| Replies, references and status stay in the intended audience | Message IDs and a head/client phone walkthrough: ___ |
| Privacy and revoked access | Private transcript not visible in web/team/client views; revoked pairing refused: ___ |
| Uncertain Telegram send | Held for inspection, with no automatic duplicate: ___ |

## 3. Review brand inputs before paid preparation

In **Agency → Autopilot**, save intended accounts, posts per week (1–14 for this Telegram workflow), useful pillars, the monthly soft budget, planning day/hour, current internal lead and a different current internal backup. Use `Asia/Kolkata`. The recurring switch should be on when recurring automatic draft generation is intended; a manual Telegram plan does not switch it on. Every final post still waits for a human.

In **Verified facts**, have a currently permitted person verify contact/CTA and any intended price, availability, registration/title or launch/date statements with evidence and expiry covering the publication date. A claim valid today may expire before 25 October. Saved profile notes, channel captions and scraped website text are untrusted background until a person verifies the commercial claim. Verify suggested holiday dates separately.

In **Creative memory**, mark the designer's accepted best work, add specific reference notes and enable learning from references. Accept actual project photographs against their current file/project and verifier. A raw `authenticity=verified` field alone is insufficient after file edits or verifier removal; the canonical provenance result must still be verified.

Documented Facebook Page ID is `585141221346435`; expected Instagram handle is `@neopolis_infra`. These are expected values from the handover, not live identity proof. Inspect actual provider identity/scopes before selecting accounts. No manual import from the older SM Manager is required: SM Bean workers create the new content after analysis.

| Required brand evidence | Record actual result |
|---|---|
| Current contact/CTA and applicable commercial claims through the week | Fact IDs, sources, verifier, expiry: ___ |
| Authentic current project media and accepted designer references | Media/reference IDs and acceptance: ___ |
| Accounts, volume, pillars, soft budget, lead and backup | Saved configuration reviewed: ___ |
| Existing posts, drafts, failed/held work and old approvals | Retained content count and operator decisions: ___ |

The two unapproved 8 October posts need their actual final content checked. Any publication now needs a newly reviewed future time; old dates or broad instructions do not authorize a stale send.

## 4. Let SM Bean prepare the week

In the paired manager's internal team/private chat:

1. Send `/week 2026-10-19`. This reads the database only; compare requested volume, retained work and additional needed. Proposed times are not actual scheduled times.
2. Send `/week prepare 2026-10-19`. Review current website/channel evidence, selected references, claims, destinations, source/freshness warnings, costs and open slots. This prepares a reviewable source/configuration snapshot; AI performance/audience/moments/planning analysis has not run yet.
3. Resolve setup blockers and commercial uncertainty. Inspect the complete evidence card before pressing **prepare week**. If it exceeds the transport limit, no confirmation button is issued; review the complete administrative preparation output or dashboard instead.
4. Explicit confirmation queues canonical **listen → moments → plan → brief** stages for only the remaining bounded content. The preparation token expires in 30 minutes and binds the actor/chat/workspace/week/evidence. Changed configuration, sources, role or existing work requires a fresh review. Do not share or log the token.
5. Observe actual job IDs/stages, generated briefs and final graphics. Keep already produced/in-progress content; inspect failures/shortfalls rather than repeatedly creating another paid week. The one workspace/week claim prevents an unlimited duplicate/top-up loop.

An operator can obtain the DB-only summary without paid work using:

```bash
python manage.py telegram_week_plan --workspace b1cb458c-cfaf-43cf-8e23-f5e18a9717c7 --actor-email ACTUAL_CURRENT_MEMBER_EMAIL --week-start 2026-10-19 --json
```

The real member must exist in the deployed database. There is no fixture/name fallback. Source preparation and queue confirmation are separate actions; normal users should use the actor-bound Telegram button.

| Weekly generation evidence | Record actual result |
|---|---|
| Requested / retained / additional volume | ___ / ___ / ___ |
| Source/evidence review and explicit human preparation confirmation | Review time and actor: ___ |
| Canonical job IDs and useful completed drafts | Job IDs: ___; draft IDs: ___; shortfall/failure: ___ |
| Delivered internal completion/status notice | Real Telegram message ID: ___ |
| No unapproved send | Unapproved draft remains unsent: ___ |

## 5. Accept graphics, approve exact posts and verify delivery

Have the head/designer review an educational sample, an authentic project/site-visit sample and a listing sample on a real phone. Check a clear hook, correct logo/wordmark, readable type/contrast/crops, accurate facts, useful CTA, platform-specific copy and authentic-versus-illustrative disclosure. Reference selection and a renderer test do not establish aesthetic acceptance.

For each final post, inspect its actual full graphic, title/caption/first comment, every native destination, current source provenance and future posting time. **Approve & schedule** authorizes those exact reviewed values. A plain chat “yes,” preparation confirmation, AI output or management command must not stamp publication approval. Changed photo, copy, account or time needs fresh review; multi-media or hidden publishing settings can require dashboard review.

| Final post acceptance | Evidence to record per post |
|---|---|
| Human designer/brand review | Post/revision, fact/media IDs, approver and decision: ___ |
| Human publication approval | Exact native account/time/fingerprint, internal approval and required client sign-off: ___ |
| Real native delivery | Provider/native ID and permalink, independently inspected intended account: ___ |
| Delivery status and Telegram update | Exactly one receipt and real message ID: ___ |
| Alerts and practical recovery | Lead/backup received actual alerts; late/unknown outcome remains held until human inspection: ___ |
| Costs and enquiries | Compare real provider billing with soft estimates; use consented manual campaign outcomes: ___ |

Leave one draft unapproved across its proposed time during the supervised pilot: it must remain unsent. For an unknown social outcome, inspect the native account before any resend; a human-recorded receipt is an attestation, not independent provider confirmation. No content edit should clear that hold. Do not intentionally create live provider timeouts or failures on client campaigns merely to test recovery; use the controlled failure tests and supervised harmless operator checks.

The Neopolis week is complete only when useful remaining drafts exist, every intended publication has its exact human approval and future schedule, real receipts match the intended accounts, Telegram updates/lead coverage work, and outstanding holds/shortfalls are explicitly owned. A nonpreemptive model/image call can occupy the worker, so agree monitoring/fallback coverage before promising a hard publishing deadline.

Final release decision: **Pending**. CTO evidence: ___; agency head acceptance: ___; designer acceptance: ___; actual launch blockers/owners: ___ .
