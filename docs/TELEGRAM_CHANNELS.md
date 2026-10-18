# Telegram status channels

Implementation prepared 14 October 2026. This document describes the reviewed
code; it does not establish that a real customer channel was connected or sent
a message. No channel target was supplied during implementation.

In **Agency → Telegram**, connect the workspace bot, link your own Telegram
account and press Start. Create a channel in Telegram, make your own paired
account an administrator, then add the workspace bot as an administrator with
**Post Messages** enabled. In **Connect a channel for status updates**, enter
the channel's public `@username` or its negative numeric ID. Confirm its
subscriber audience and choose **Verify and connect channel**.

SM Bean checks the bot identity, the selected chat's channel type, the bot's
posting privilege and the paired person's administrator membership. A channel
belongs to one workspace; disabling it does not silently transfer it to another
client. A current internal settings manager must perform setup. Clients can
pair their own private account but cannot change broadcast destinations.

Channels receive fixed draft, review, scheduling and confirmed publication
status messages for permitted canonical posts. They receive no raw brainstorm
text, internal costs, private conversation content, captions, attachments or
approval buttons. Ideas without a canonical post remain in their originating
conversation. Questions and approvals use the paired private chat or the
appropriate linked client/team group. A status update is historical; open
SM Bean for the post's current revision, destination and time.

For an idea saved in the web workflow, its original author can explicitly
enable Telegram questions and progress updates. Genuine missing-input
questions go to that person's paired private chat. Use Telegram's **Reply**
action on the actual question message to continue the original shared idea;
the bot states that your reply will appear in that team thread. Copied question
text, a forwarded question or another person's reply does not identify or
authorize a workflow. A question expires after seven days and accepts one
answer. Revoked membership, pairing, opt-in or changed source evidence blocks
both delivery and further processing. Draft preparation confirmation and
publication approval remain separate human steps. Private Telegram history is
never rebound into the web thread.

Telegram cannot enumerate every passive subscriber. The administrator must
manage who can see the channel and its existing history. Changing bot setup,
pairing or permissions requires channel verification again. Disabling the bot,
personal identity or channel invalidates queued updates; lost native posting
rights also suspend it. A send whose outcome is uncertain is held for manual
inspection, rather than automatically resent.

The web and worker releases must apply Telegram migrations
`0003_telegramchannel_telegramchanneldelivery_and_more` and
`0004_telegramworkflowprompt`. The existing Telegram recurring cycle drains
channel deliveries under the worker lease. Delivery scope is encrypted and
rechecked against current tenant, author, role and pairing authority before
native transport. Channel content receives the configured delivery retention
policy; cleared content does not clear an uncertain outcome hold.

Focused tests use PostgreSQL and mocked Telegram responses. Live acceptance
still requires a genuine paired administrator and actual customer channel;
local tests do not establish receipt by a Telegram subscriber.
