# Launch fix verification — 13 October 2026

The Railway-compatible Docker recipe and marketing corrections are now deployed
in matching native web/worker services at `91bef9ec9ff42b47fed80db66ca572fc5b066107`.
The evidence supports a supervised operator beta; production AI, Gmail, paired
customer/group approval and publication acceptance remain incomplete.

| Check | Observed result |
| --- | --- |
| Final required CI | All six jobs passed on tested PR11 head `30e4d3e0f2e018ba7725fd80cf4384cd9dc8a7c1`: **4,731 passed, 1 skipped, 194 subtests**. The merged deployed tree is identical. All six main checks also passed on the exact deployed commit; main-run totals were not separately inspected. |
| Full Docker builds | Canonical `Dockerfile` and generated `Dockerfile.cloud` both completed in CI. Cloud dependency stages executed with CA trust; runtime assertions confirmed absence of the secret file, CA environment overrides and `.env`. This is stronger evidence than the earlier recipe-only check. |
| Generated cloud recipe | Deterministic generation/drift validation and negative cases passed. TLS, frozen npm installation and hash-verified Python dependencies remain enforced. |
| Local Chromium, historical | **73 passed**: 66 layout/navigation/fallback checks plus 7 mobile-contrast checks; desktop/tablet/mobile, disabled JavaScript, blocked script and reduced motion. Two deliberate script blocks produced two expected resource errors. |
| Marketing and DOM suites | **17 marketing tests** and **30 locked DOM state tests** passed. Targeted counts overlap broader CI and are not added to its total. |
| Live anonymous production checks | **137 checks passed** against actual production browser/layout/navigation and route/header behavior, including fallback behavior. These are anonymous checks; email consent, client acceptance and paid providers remain separate. |
| Current native release | Web `aac80bcf-d891-4541-a312-ab5452c8ea13`, worker `afc72c9f-7640-4273-9f12-d7dc9fd8b222`:SUCCESS, correct native source,16 anchors each, actual `/Dockerfile`, one replica each. |
| Production security/reliability | Ten migrations; pending 0; 18 required managed-bot columns; physical OAuth plaintext counts 0; one worker lease; four actual successful recurring cycles; cache roundtrip/cleanup and public health pass. Wrong-secret Telegram POST returns 403. |
| Telegram and Neopolis preparation | Trial identity, encrypted workspace connection and native receiver pass; real operator scope and website-only canonical correction completed. Pairing, groups, child-bot creation, draft generation and real publication remain undone. |

[Current CI](evidence/2026-10-13/current-final-ci.json) ·
[Native rollout](evidence/2026-10-13/current-native-rollout.json) ·
[Schema/backups](evidence/2026-10-13/current-native-schema-backups.json) ·
[Worker](evidence/2026-10-13/current-native-worker.json) ·
[Encrypted trial connection](evidence/2026-10-13/current-telegram-neopolis.json).

The earlier [recipe-only receipt](evidence/2026-10-13/launch-fix-verification.json)
records validation before full CI and activation. Its pending/older-source fields
are historical snapshots, superseded by the current receipts above. Earlier
unsupported-mount failures and the preliminary platform diagnosis are also
historical. No credentials, private actors, raw logs or signed capability URLs
are included in the curated current evidence.

The [CTO decision](CTO_LAUNCH_DECISION_2026-10-13.md) retains the critical launch
limits. AI campaign generation requires the absent Railway OpenRouter key;
Gmail requires genuine human consent; actual clients, groups, approval and
native publication receipts still need a supervised pilot.
