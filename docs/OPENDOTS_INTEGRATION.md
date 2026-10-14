# OpenDots in SM Bean

SM Bean now runs an actual source adaptation of OpenDots task controls inside
its existing assistant workflow. It keeps one set of tenant-scoped
conversations, drafts, approvals and background jobs. Customers can give an
idea, see the next required input, follow the assistant's stages, pause future
steps, resume a paused task and review saved work before retrying a failed
task. Existing Telegram pairing and approval rules still apply.

The reviewed upstream is
[CopilotKit/OpenDots at 625452e](https://github.com/CopilotKit/OpenDots/tree/625452e06cde74cb25b0ce319e2c1be0488f5a5f),
MIT licensed, copyright Atai Barkai. Exact reviewed source copies, hashes and
the license are in [`third_party/opendots`](../third_party/opendots/README.md).
The live Python adapter reports its exact integration mode and commit with
`apps.studio.opendots.integration_status()`.

## Persistent work and control

OpenDots' `Store.action` and `invalidate` task transitions and `TaskActions`
presentation have been translated into `apps/studio/opendots.py`. Canonical
`AgencyJob` rows persist state in PostgreSQL; SM Bean's existing leased worker
runs stages. A task pause sets the canonical job inactive and increments its
revision. Already queued stages and late writes from the older revision are
rejected by the same engine and chat side-effect guards used for normal
generation. Pausing a task leaves other jobs and recurring schedules under
their own settings.

Resume and Retry acquire current workspace and actor authority, then the job
lock. A stale revision cannot enqueue work twice. Resume retains completed
stage state and returns to the unfinished stage. The workspace's archival,
deletion, automatic-work policy and monthly budget are checked before work is
queued. Private Telegram job history cannot be read or controlled through the
shared dashboard.

A request already sent to a provider may still finish or incur a charge after
Stop. The assistant does not claim to retract it. A failed task or a task
paused during a running step requires a person to review saved work and
explicitly acknowledge the retry. The signed review snapshot covers the
job's state, timeline receipts and generated briefs/posts. A changed or
expired snapshot is rejected. No interrupted action is automatically replayed.
Post approvals, proposed times and actual publishing continue through the
existing human approval and publisher services; an assistant never approves
its own draft.

## Configuration and honest status

This native adaptation adds no model provider, conversation service, computer
host, telemetry or client-side credential. Model credentials remain on the
server. Missing provider credentials block generation with an actionable
setup state; they do not produce fictional posts or success notifications.
Telegram updates need an active connected workspace bot and a genuine paired
private chat or verified group. Telegram channels use their separate verified
destination flow; a public channel is not an interactive approval identity.

The native adaptation does **not** start the full OpenDots Node app. Upstream
conversations require CopilotKit Intelligence, through its hosted service,
local evaluation, or a licensed self-hosted deployment. That application uses
Node 24, TanStack AI, AG-UI and a separate workspace store. Installing it as a
companion requires a reviewed multi-tenant identity bridge, configuration and
explicit decisions about where conversation/tool data is stored. Upstream
describes its template as alpha and single-owner; directly exposing it to SM
Bean clients would bypass SM Bean's membership and privacy rules.

If a full companion is selected later, build the pinned version separately,
keep all provider and Intelligence credentials server-side, disable telemetry
where intended and use a tenant-scoped SM Bean API bridge. Do not run
`copilotkit onboard` inside the upstream app: its README explicitly says that
would create a second generic integration. OpenBot shell/browser, voice and
MCP actions are optional and require their own infrastructure and access
controls; none are enabled by this patch.

## Verification

Focused PostgreSQL tests exercise duplicate control requests, a stale worker
after pause, stage continuation after a single resume, late provider receipts,
expired/tampered/cross-task review tokens, removed/custom/client permissions,
private Telegram isolation, workspace/budget policy and the legacy Retry
route's review gate. Fixtures make no provider, Telegram or publishing calls.
Repository CI and deployment acceptance provide the release-specific results;
source integration tests do not prove a live model response or human approval.
