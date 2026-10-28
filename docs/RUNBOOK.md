# Runbook

## First deploy

1. Build and push both images for linux/arm64. CI builds them on every push; pushing to ECR runs only in the release job:
   - `docker buildx build --platform linux/arm64 --target lambda -t <repo>:<v>-lambda .`
   - `docker buildx build --platform linux/arm64 --target runtime -t <repo>:<v>-runtime .`
2. Set `image.tag` in `config/infra.yaml`, then run `powerdesk export-schemas` and `cdk deploy -c account=<id>`.
3. Create the knowledge base table once, with the RDS Data API, using the cluster's admin secret:
   `aws rds-data execute-statement --resource-arn <cluster> --secret-arn <secret> --database powerdesk --sql file://infra/sql/bedrock_kb.sql`
   (run each statement separately).
4. Load the documents:
   - `powerdesk export-kb`
   - `aws s3 sync build/kb s3://<DocumentsBucket>/kb/`
   - start an ingestion job on the `desk-documents` data source.
5. Upload the skills: `aws s3 sync skills s3://<SkillsBucket>/skills/`.

## Every release

- `pytest -q`, `powerdesk evals all`, `powerdesk gate`. The gate fails on any leak, any untraced number shipped, or any filter/Cedar disagreement.
- Change a policy only with a test in `tests/test_policy.py` that shows the new decision.

## Rotating the identity key

The interceptors and the tool Lambda share `IdentityKey`. Envelopes live 120 seconds.

1. Put a new secret value.
2. Publish new versions of all five functions (or update an environment variable to force a cold start).
3. Calls signed with the old key during that window fail closed. Clients retry them.

## When the gateway refuses something it should allow

1. Look up the call in the tool-call log (console, Tool calls). Each refusal names the Cedar policy, or `default-deny`.
2. Reproduce the call: `pytest -k <user>` in `tests/test_policy.py`, with a new case.
3. Fix `policies/desk.cedar` or `config/org.yaml`, never the gateway code.
