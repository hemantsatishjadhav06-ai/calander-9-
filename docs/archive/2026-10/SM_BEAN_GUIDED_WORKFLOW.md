# From an idea to an approved post

Open [SM Bean](https://sm-bean-production-eb50.up.railway.app/), choose your
company and select **Start a post**. This guide describes the 14 October
workflow implementation. Release verification determines when it is available
on the live site.

1. **Share an idea.** A rough thought, customer question, update or event is
   enough. Your idea is saved before generation starts. If AI setup or budget
   needs attention, the saved idea stays available with a clear next action.
2. **Answer the questions.** Open the idea's conversation to supply missing
   facts, references, audience and purpose. Review the proposed brief and
   explicitly confirm the direction before the team creates a draft.
3. **Review the draft.** Check the actual caption, visual, factual claims and
   destination accounts. Request changes through the existing review flow.
   Clients use their own portal and approvals; viewers keep their permitted
   calendar and review access.
4. **Approve and schedule.** A permitted person approves the final work and
   selects its accounts and future time. Changing material details can require
   another approval. Delivery is complete only when every selected destination
   has a confirmed native receipt.

The progress cards show what happened and what to do next. Opening or
refreshing the page reads saved status; it does not create another draft,
repeat a question or silently approve a post. A queued request is labelled as
waiting for the worker. An uncertain delivery needs inspection before retrying.

## Continue the idea in Telegram

In **Agency → Telegram**, connect the company's bot, choose **Create my
personal Telegram link**, open that link and press **Start** within ten
minutes. Each person needs their own one-use link. Opening the generic bot
profile does not pair your identity with a company.

When saving a web idea, explicitly check **Send questions and draft updates to
my paired Telegram account**. It starts unchecked. The original author receives
the actual missing-input questions and permitted progress updates in their
paired private chat. Use Telegram's **Reply** on the delivered question to
answer. Each question accepts one answer and expires after seven days.

That answer continues the original shared workspace idea and is visible to
its team. Ordinary private bot conversation history stays private. Forwarding
or copying a question does not grant access. A changed pairing, removed role
or disabled opt-in blocks further delivery and processing. Brief confirmation
and final publication approval remain separate human decisions.

You can also begin a permitted Telegram conversation with `/brainstorm` or
`/brief`, and inspect it with `/status`. `/week` shows the permitted weekly
plan. Use `/help` for the bot's current commands. In groups, use a command,
mention or reply when Telegram privacy mode is enabled.

## Add a Telegram channel

A settings manager who has paired their own account can use **Connect a channel
for status updates** in the same Telegram settings page:

1. Create the channel in Telegram. Your paired account must be its administrator.
2. Add the company's bot as an administrator and enable **Post Messages**.
3. Enter its public `@username` or negative numeric channel ID in SM Bean.
4. Confirm who may see the updates and choose **Verify and connect channel**.

SM Bean checks both administrator identities and the bot's posting rights.
Use a separate destination for each company. A channel broadcasts brief draft,
review, scheduling and confirmed delivery status. Its subscribers receive no
raw ideas, private history, captions, internal costs or approval buttons.
Questions and answers use the paired private chat; client and team groups have
their own pairing and audience rules. Changing pairing or bot permissions
requires verification again. You control the channel's subscribers and history.

For a new company's bot, use the supported manager flow when Telegram gives
the manager bot creation capability. Otherwise create it through BotFather's
`/newbot` and enter its token securely in that company's settings. SM Bean's
connect form validates an existing bot; a normal bot cannot silently create
other bots or groups. See [Telegram setup details](../../TELEGRAM_CHANNELS.md).

## Pause or recover work

Open the task's progress page to pause future assistant steps or resume saved
work. Failed or interrupted work requires inspection and an explicit review
before retrying. An already submitted provider request may still finish or
incur a charge after a pause. Resuming preserves completed stages and does
not replay an uncertain action automatically.

These persistent controls adapt the MIT-licensed
[CopilotKit/OpenDots source](https://github.com/CopilotKit/OpenDots/tree/625452e06cde74cb25b0ce319e2c1be0488f5a5f)
to SM Bean's existing jobs and worker. The integration does not start the full
CopilotKit application or enable computer, browser, voice or MCP agents. See
[the integration and license](../../OPENDOTS_INTEGRATION.md).

## Complete the real pilot

An administrator must securely configure the live AI provider. Email onboarding
requires the mailbox owner's real Google consent through **Email operations**.
Telegram requires personal Start/pairing and the intended group or channel
permissions. Test a real idea, question, confirmed brief, reviewed draft and
notification before expanding customer access. A connected bot or passing
source tests alone does not establish receipt or successful social publication.
