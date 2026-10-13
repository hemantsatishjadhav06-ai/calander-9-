# Railway build initialization investigation

SM Bean source deployments fail before any Docker or application log appears. This is a reproducible build initialization blocker; Railway has returned no diagnosis or error detail.

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

Every attempt contains exactly one build log:

```text
scheduling build on Metal builder "builder-ijrmto"
```

All three report `FAILED`, `deploymentStopped=true`, `diagnosis=null`, no image, and zero deployment logs. The diagnostic V2 request was accepted and its actual deployment manifest used V2; it failed at the same scheduling stage. Original web V3 was then restored using skipDeploys, and the entire environment configuration matches its pre-diagnostic baseline. No further source build has been requested.

The final source tree passed all six CI jobs, including Docker build. The isolated local production-container smoke passed the preceding integrated revision before the final OAuth/tooling repair. These results do not prove why Railway initialization failed or that the final image has booted in Railway. The Railway status homepage reported Fully Operational; its own scope excludes smaller isolated issues.

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

For Railway support, inspect the selected builder node and source checkout/build scheduling errors for these deployment IDs. The logs expose no Dockerfile step or application failure to act upon. No message or support ticket has been sent.

Official references:

- https://docs.railway.com/deployments/reference#redeploy
- https://docs.railway.com/builds/dockerfiles
- https://docs.railway.com/builds/build-configuration
- https://github.com/railwayapp/cli/blob/v5.66.0/src/controllers/config/environment.rs#L301
- https://status.railway.com/
