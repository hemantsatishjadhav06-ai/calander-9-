# Launch fix verification — 13 October 2026

The Railway-compatible build recipe and local marketing fixes passed the checks below. Full CI for these changes and deployment of the new source remain pending. The last observed active production source is `05ca828b2be22d4c3a65fbdf67404961e0f13124`.

| Check | Observed result |
| --- | --- |
| Docker recipe validation | `docker buildx build --check` passed for `Dockerfile` and `Dockerfile.cloud`, with official ECR Node/Python base overrides and no warnings. This did not execute a full build or start an image. |
| Generated cloud recipe | Deterministic generation and `--check` passed. Missing, duplicate, commented-out, changed install blocks and missing/stale generated files were rejected. Ruff, formatting, mypy and CI YAML/script syntax passed. |
| Local Chromium | **73 checks passed**: 66 navigation/layout/fallback checks and 7 mobile button contrast checks across desktop, tablet, mobile, disabled JavaScript, blocked script and reduced-motion scenarios. |
| Existing marketing suite | **17 passed**, as recorded in the completed reviewer run. |
| Existing DOM suite | **30 passed** with `npm run test:ui`, as recorded in the completed reviewer run. |

The browser run recorded no page exceptions or unintended request failures. Two marketing-script requests were deliberately blocked to test fallback navigation; their two resource console errors are expected. The additional contrast checks passed after the mobile button fix.

Canonical dependency installation still uses TLS, `npm ci` and hash-verified pip. The generated cloud recipe supplies optional CA trust through BuildKit secrets. CI is configured to build both recipes, execute the cloud dependency stages with a mounted CA and check that the secret, CA environment settings and `.env` are absent from its runtime image. These full-build results are not yet observed.

[Curated evidence](evidence/2026-10-13/launch-fix-verification.json) includes recipe/source-record digests and safe counts. It contains no private identities, credentials or capability links. These local anonymous checks do not establish Gmail consent, real provider generation/publication, authenticated acceptance or the new live worker/source revision.
