# Railway build initialization investigation

The actual failure is now identified: Railway rejects the optional BuildKit `type=secret` mounts in the production Dockerfile. The earlier generic `buildLogs` endpoint omitted this error; official CLI snapshot-scoped `environmentLogs` exposed it. The prior unexplained-platform-failure assessment is superseded.

```text
dockerfile invalid: flag '--mount=type=secret,id=build_ca_bundle' is missing a type=cache argument (other mount types are not supported)
```

The error points to lines 9 and 38 in the previous recipe. Keep certificate and package-hash verification enabled: the canonical recipe must use standard trusted roots without these mounts, while a generated `Dockerfile.cloud` preserves optional BuildKit CA-secret support for local cloud builds. CI builds both recipes and checks their consistency.

- Project: `66526b2a-6a09-43d8-bedb-ecfdd37f8d8a`
- Environment: `be4c1d8d-84ce-47ce-9e24-56be144551cf`
- Web service: `6ef064fe-9804-4118-95b3-749ab17b795a`
- Reviewed source: `e630f34e1eaabe7ea4bfd8cb1b1ffe966d13a60f` (main).
- Detected builder: `DOCKERFILE`, `/Dockerfile`.

| Deployment | Build route | Created UTC | Failed UTC |
| --- | --- | --- | --- |
| `a378721c-6d62-448b-b899-ca2fab612116` | V3 | 2026-10-13T12:13:00.758Z | 2026-10-13T12:13:09.612Z |
| `620bc09e-7340-4620-9b30-5618436f937f` | V3 | 2026-10-13T12:35:10.369Z | 2026-10-13T12:35:16.863Z |
| `0d6ad38d-76fd-4fa2-967a-12e94a121e6a` | V2 | 2026-10-13T12:41:26.787Z | 2026-10-13T12:41:32.390Z |

The incomplete legacy log view returned only builder allocation messages:

```text
scheduling build on Metal builder "builder-ijrmto"
```

Those three Git-path attempts report `FAILED`, `deploymentStopped=true`, `diagnosis=null`, no image, and zero deployment logs. A fourth immutable CLI upload (`d188b90c-63cc-4e3a-9d5c-b55954b97d18`) failed with the same parser error on another builder. Its native source-archive digest matches the submitted Git archive. All four detailed snapshots identify the same Dockerfile error. The diagnostic V2 request was accepted and its actual deployment manifest used V2; it failed at the same scheduling stage. Original web V3 was then restored using skipDeploys, and the entire environment configuration matches its pre-diagnostic baseline. No further source build has been requested.

The final source tree passed all six CI jobs, including Docker build. The isolated local production-container smoke passed the preceding integrated revision before the final OAuth/tooling repair. These earlier BuildKit checks accepted secret mounts, so they did not establish Railway parser compatibility. The new canonical recipe must be tested on the actual target; no corrected image is yet serving. The Railway status homepage reported Fully Operational; its own scope excludes smaller isolated issues.

Both original web and worker deployments remain SUCCESS on `05ca828b2be22d4c3a65fbdf67404961e0f13124`. HTTPS `/health/` returns200. Auto deploy is held for both; the reviewed web release gate remains closed and no old deployment was stopped. Database snapshots and a verified application backup were retained, and the native DAILY backup schedule has six-day retention.

Read-only diagnostic GraphQL (use the existing protected environment credential binding; never include credentials in tickets):

```graphql
query InvestigateBuild($id: String!) {
  deployment(id: $id) {
    id status createdAt statusUpdatedAt diagnosis deploymentStopped
  }
  buildLogs(deploymentId: $id, limit: 50) { message severity timestamp }
  deploymentLogs(deploymentId: $id, limit: 50) { message severity timestamp }
}
```

The detailed diagnostic query uses the actual deployment snapshot ID and `environmentLogs`; the legacy query above is insufficient for this parser failure. The correction is in the build recipe. Billing inspection confirmed an active funded Pro workspace without a configured usage limit or project expiry. No external support message was sent.

Official references:

- https://docs.railway.com/deployments/reference#redeploy
- https://docs.railway.com/builds/dockerfiles
- https://docs.railway.com/builds/build-configuration
- https://github.com/railwayapp/cli/blob/v5.66.0/src/controllers/config/environment.rs#L301
- https://status.railway.com/
