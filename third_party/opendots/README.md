# OpenDots source integration

SM Bean includes an MIT-licensed adaptation of task lifecycle controls from
[CopilotKit/OpenDots](https://github.com/CopilotKit/OpenDots), pinned to
`625452e06cde74cb25b0ce319e2c1be0488f5a5f` (reviewed 14 October 2026).
Copyright (c) Atai Barkai. The complete upstream license is [LICENSE](LICENSE).

The `upstream` directory holds exact source copies for review and provenance;
they are not bundled into SM Bean's browser or executed as a second server.
The executable adaptation is `apps/studio/opendots.py`, its authenticated
controls and the existing job pages. It ports task state presentation,
pause/run/cancel invalidation and interrupted-run review to Django's canonical
jobs. SM Bean supplies tenant identity, PostgreSQL transactions, revision
fences and its existing leased worker. Resume and Retry require current
authority and budget. Failed or interrupted work needs a signed, current
snapshot and an explicit human review. A changed snapshot is rejected.

| Upstream source | SHA-256 | Adaptation |
| --- | --- | --- |
| `src/server/store.ts` | `ba4fd73dee166493431f56d8e6fffe3b2972404f0110ef12d815d5a04a5257db` | Task invalidation, action transitions, owner-fenced completion |
| `src/server/runner.ts` | `c5180d29700f4f75c7b9b4416ed46d068e8cc6b39e0aaa0d35db976317b1f668` | Stop future work and require explicit interrupted-work recovery |
| `src/client/TaskActions.tsx` | `2a6521420303d69a007c9d7c45412508eb58ec8b09793eb622da60479e046491` | Active task controls and “Retry after review” presentation |
| `src/shared/types.ts` | `774708cc0b4a23747d49d0232a673afc4f811b340bc716f5bbf6a809e8576ba1` | Queued/running/paused/completed/failed/interrupted/cancelled task vocabulary |
| `LICENSE` | `15a0e5343aea872c0573ad72feb6044b336f162d724cc1673c608e6b37ea071b` | MIT copyright and permission notice |

The integration does not claim that CopilotKit Intelligence, AG-UI streaming,
OpenBot computers, voice or MCP execution are installed. Those upstream
services require separate infrastructure, credentials and an approved data
destination. See [the integration guide](../../docs/OPENDOTS_INTEGRATION.md).
