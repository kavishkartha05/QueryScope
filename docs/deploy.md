# Hosted demo: deployment runbook

This is the step-by-step guide for putting QueryScope online as an invite-only
demo on Azure. Everything here is prepared as files; nothing has been deployed.
Commands marked **(changes Azure)** create or modify cloud resources. Read each
one before running it.

Costs and free-tier statements below are **estimates written from memory of
Azure's public pricing. Verify every number on the Azure pricing calculator and
your own subscription before relying on it.** The Bicep templates and workflows
were also written without being run against Azure; expect to fix small issues on
the first real deployment (see section 16).

## 0. Architecture

```
recruiter browser
   |  https                              https (Bearer token, CORS-restricted)
   v                                      ^
Azure Static Web Apps  ------------------>  Container App: backend (1 replica, fixed)
(Vite bundle, CSP, no-referrer)               |            |             |
                                              |            |             +--> Azure AI Search (index benchmark-runs-prod)
                                              |            +--> Key Vault (secrets, via managed identity)
                                              v
                                   PostgreSQL Flexible Server (B1ms)

Container App: demo-target (public HTTPS, benchmarked by the backend)
Container Apps Job: migrate (manual, runs "alembic upgrade head")
ACR (images)    Log Analytics (logs)    Budget + alerts
```

**The backend must stay at exactly one replica.** The login throttle and the
run-admission lock live in process memory. `infra/main.bicep` pins
`minReplicas = maxReplicas = 1`. The Horizontal Pod Autoscaler in `k8s/hpa.yaml`
(2 to 6 replicas) is therefore **incompatible with the hosted design**; `k8s/` is
left untouched and is for local Kubernetes experiments only.

## 1. Prerequisites

- An Azure subscription where you can create resources and role assignments.
- Azure CLI (`az`) with Bicep (`az bicep install`), signed in with `az login`.
- Docker, `openssl`, `curl`, `jq`.
- A GitHub repository with Actions enabled.
- An OpenAI account and an Azure AI Search service you control.
- A short `namePrefix` (3 to 12 lowercase letters), for example `qscope`.

Azure for Students notes (verify): the student offer gives a small credit (about
100 USD) and may restrict allowed regions and some SKUs through policy. If a
deployment is rejected with a policy error, choose a region from the allowed list
and re-run. ACR Tasks (`az acr build`) are sometimes blocked on student
subscriptions, which is why the workflow uses a local `docker build` and
`docker push` instead.

## 2. Before anything else: rotate leaked keys

The repository history contains a leaked Azure key (see the Week 4 TODO in
`CLAUDE.md`). Treat every key that was ever in `.env` as compromised.

1. **Azure AI Search**: Portal, your search service, Settings, Keys. Regenerate
   the admin keys (secondary first, switch to it, then the primary).
2. **OpenAI**: create a **new key in a new project** dedicated to this demo, then
   delete the old key.
3. Never paste keys into chat, tickets, shell history or files in the repo.
4. Before making the repository public, scrub history with `git filter-repo`
   and a replace-text file kept outside the repo, then force-push.

## 3. Spending caps

- **OpenAI**: in the dedicated project, Settings, Limits, set a monthly budget
  (a few dollars is plenty) with a hard stop if your plan offers it, plus a low
  email-alert threshold.
- **Azure**: `infra/main.bicep` creates a monthly budget with alerts at 50
  percent, 80 percent and forecast 100 percent. A budget **alerts**; it does not
  stop spending. Check it in Cost Management after deploying.
- The application limits itself too: 500 requests per run, 2,000 requests per
  code per day and 10,000 overall per day.

## 4. Create the resource group and deploy the platform (phase 1)

Phase 1 creates everything except the apps and the migration job, which need
images and secrets that do not exist yet.

```bash
az login
az account set --subscription "<subscription id>"

RG=queryscope-rg
LOCATION=eastus2
az group create --name "$RG" --location "$LOCATION"            # (changes Azure)

cp infra/main.parameters.example.json infra/main.parameters.json   # git-ignored
# Edit infra/main.parameters.json: namePrefix, azureSearchEndpoint, alertEmail.

# Generated without printing. Stored in Key Vault in section 5.
PGPASS=$(openssl rand -hex 24)

az deployment group create \
  --resource-group "$RG" \
  --template-file infra/main.bicep \
  --parameters @infra/main.parameters.json \
  --parameters postgresAdminPassword="$PGPASS" \
  --query properties.outputs --output json > qs-outputs.json   # (changes Azure)
```

`postgresAdminPassword="$PGPASS"` is visible in the local process list while `az`
runs; acceptable on a personal machine. `qs-outputs.json` holds names and
hostnames only, no secrets (it is git-ignored; do not commit it). Read values:

```bash
ACR=$(jq -r .acrName.value qs-outputs.json)
KV=$(jq -r .keyVaultName.value qs-outputs.json)
PGHOST=$(jq -r .postgresHost.value qs-outputs.json)
API_URL=$(jq -r .backendUrl.value qs-outputs.json)
WEB_URL=$(jq -r .staticWebAppUrl.value qs-outputs.json)
DEMO_URL=$(jq -r .demoTargetPublicUrl.value qs-outputs.json)
BACKEND_APP=$(jq -r .backendAppName.value qs-outputs.json)
MIGRATE_JOB=$(jq -r .migrateJobName.value qs-outputs.json)
```

The backend and demo-target hostnames are predictable from the environment's
default domain, so `API_URL`, `DEMO_URL` and the allowlist are already correct
even though the apps do not exist yet. `CORS_ORIGINS` is the exact Static Web App
origin, set automatically.

## 5. Put secrets in Key Vault (never print them)

Writing secrets needs the **Key Vault Secrets Officer** role:

```bash
ME=$(az ad signed-in-user show --query id -o tsv)
az role assignment create --assignee "$ME" --role "Key Vault Secrets Officer" \
  --scope "$(az keyvault show -n "$KV" --query id -o tsv)"            # (changes Azure)
```

Role assignments can take a minute or two. Two rules for every command below:
always `--output none` (otherwise `az` echoes the value back), and pass values
through stdin or a hidden prompt, never as arguments.

```bash
# Random secrets (generated and stored, never shown):
for NAME in session-secret code-pepper admin-api-key; do
  openssl rand -base64 48 | tr -d '\n' | \
    az keyvault secret set --vault-name "$KV" --name "$NAME" \
      --file /dev/stdin --encoding utf-8 --output none
done

# The Postgres admin password (needed again when the template is re-run):
printf '%s' "$PGPASS" | az keyvault secret set --vault-name "$KV" \
  --name postgres-admin-password --file /dev/stdin --encoding utf-8 --output none

# DATABASE_URL. ssl=require makes asyncpg use TLS, which Azure Postgres requires.
printf '%s' "postgresql+asyncpg://qsadmin:${PGPASS}@${PGHOST}:5432/queryscope?ssl=require" | \
  az keyvault secret set --vault-name "$KV" --name database-url \
    --file /dev/stdin --encoding utf-8 --output none
unset PGPASS

# Keys you paste yourself (hidden prompt, then unset):
for NAME in azure-search-key openai-api-key; do
  printf 'Value for %s (input hidden): ' "$NAME"; read -rs VALUE; echo
  printf '%s' "$VALUE" | az keyvault secret set --vault-name "$KV" --name "$NAME" \
    --file /dev/stdin --encoding utf-8 --output none
  unset VALUE
done
```

Keep the **admin API key** in a password manager (you need it for admin routes
and `queryscope reset`). Copy it without displaying it:
`az keyvault secret show --vault-name "$KV" --name admin-api-key --query value -o tsv | pbcopy`
(macOS), paste into the manager, then clear the clipboard.

## 6. Build and push images, then deploy the apps (phase 2)

Pushing needs AcrPush:
`az role assignment create --assignee "$ME" --role AcrPush --scope "$(az acr show -n "$ACR" --query id -o tsv)"`.

```bash
az acr login --name "$ACR"
TAG=$(git rev-parse --short HEAD)
docker build -t "$ACR.azurecr.io/queryscope-backend:$TAG" backend
docker build -t "$ACR.azurecr.io/queryscope-demo-target:$TAG" demo-target
docker push "$ACR.azurecr.io/queryscope-backend:$TAG"
docker push "$ACR.azurecr.io/queryscope-demo-target:$TAG"

PGPASS=$(az keyvault secret show --vault-name "$KV" --name postgres-admin-password --query value -o tsv)
az deployment group create \
  --resource-group "$RG" \
  --template-file infra/main.bicep \
  --parameters @infra/main.parameters.json \
  --parameters deployApps=true \
               backendImage="$ACR.azurecr.io/queryscope-backend:$TAG" \
               demoTargetImage="$ACR.azurecr.io/queryscope-demo-target:$TAG" \
               postgresAdminPassword="$PGPASS" \
  --output none                                                   # (changes Azure)
unset PGPASS
```

## 7. Run migrations and create the search index

The backend image does not migrate on start. Run the one-off job before the first
request:

```bash
EXEC=$(az containerapp job start -g "$RG" -n "$MIGRATE_JOB" --query name -o tsv)   # (changes Azure)
az containerapp job execution show -g "$RG" -n "$MIGRATE_JOB" \
  --job-execution-name "$EXEC" --query properties.status -o tsv   # repeat until Succeeded
```

Create the production index. The running container already has every setting, so
run the script there (no secrets on your laptop):

```bash
az containerapp exec -g "$RG" -n "$BACKEND_APP" --command "python scripts/create_azure_index.py"
```

It uses `AZURE_SEARCH_INDEX=benchmark-runs-prod` from the app environment, so it
never touches the old `benchmark-runs` index. Re-running is safe.

## 8. Seed demo runs and create the first access code

```bash
# Demo runs against the demo target, also indexed so diagnose can find them:
az containerapp exec -g "$RG" -n "$BACKEND_APP" --command \
  "python scripts/seed_demo.py --target-url $DEMO_URL --index"

# First access code. Printed ONCE; only its hash is stored. Do not paste it into
# chat or commit it. Share it with the recruiter privately.
az containerapp exec -g "$RG" -n "$BACKEND_APP" --command \
  "python scripts/manage_codes.py create stripe-rebecca"
```

Codes look like `label.aB3dE5gH7k`. A magic link is `<WEB_URL>/#code=<code>`: the
code sits in the URL fragment, which browsers never send to servers, and the app
removes it from the address bar on load. Use `manage_codes.py list` and
`manage_codes.py revoke <label>` to manage codes; revoking kills live tokens
immediately.

## 9. Frontend

The workflow does this (section 11). By hand:

```bash
cd frontend
npm ci --ignore-scripts
VITE_API_URL="$API_URL" npm run build:swa
TOKEN=$(az staticwebapp secrets list -g "$RG" -n "$(jq -r .staticWebAppName.value ../qs-outputs.json)" \
  --query properties.apiKey -o tsv)
npx @azure/static-web-apps-cli deploy ./dist --deployment-token "$TOKEN" --env production   # (changes Azure)
unset TOKEN
```

`build:swa` writes `dist/staticwebapp.config.json` with the CSP `connect-src` set
to your backend origin only. Headers: CSP, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer` (magic links carry codes in the fragment) and
`X-Frame-Options: DENY`.

## 10. TRUSTED_PROXY_HOPS: set it and verify it

The login throttle keys on the client IP. Container Apps ingress is a reverse
proxy that appends the address it saw to `X-Forwarded-For`; the app trusts the
Nth entry from the **right**. `TRUSTED_PROXY_HOPS=1` (the template default) is
right with only the built-in ingress in front. If you later add Front Door or
another proxy, raise it by one.

Verify with bad codes only. This will lock your own IP out for the throttle
window (15 minutes by default), so do it from a network you can wait out:

```bash
for i in 1 2 3 4 5 6; do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST "$API_URL/auth/login" \
    -H "Content-Type: application/json" -H "X-Forwarded-For: 10.0.0.$i" \
    -d '{"code":"not-a-real-code"}'
done
```

Expected: `401` five times, then `429`.
- `429` on the 6th request: correct; the spoofed header was ignored.
- Always `401`, never `429`: hops is too high and the header is spoofable. Lower it.
- `429` for unrelated people early on: hops is too low and everyone shares the
  proxy's address. Raise it.

## 11. GitHub Actions deploy (OIDC, no stored cloud passwords)

One-time setup:

```bash
SUB=$(az account show --query id -o tsv)
APP_ID=$(az ad app create --display-name queryscope-deploy --query appId -o tsv)   # (changes Entra)
az ad sp create --id "$APP_ID" --output none
az ad app federated-credential create --id "$APP_ID" --parameters '{
  "name": "github-production",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:<owner>/<repo>:environment:production",
  "audiences": ["api://AzureADTokenExchange"]
}'
az role assignment create --assignee "$APP_ID" --role Contributor \
  --scope "$(az group show -n "$RG" --query id -o tsv)"
az role assignment create --assignee "$APP_ID" --role AcrPush \
  --scope "$(az acr show -n "$ACR" --query id -o tsv)"
```

In GitHub create an environment `production` (add required reviewers) and set
these variables (identifiers, not secrets):

| Variable | Value |
|---|---|
| `AZURE_CLIENT_ID` | `$APP_ID` |
| `AZURE_TENANT_ID` | your tenant id |
| `AZURE_SUBSCRIPTION_ID` | `$SUB` |
| `AZURE_RESOURCE_GROUP` | `$RG` |
| `ACR_NAME` | `$ACR` |
| `BACKEND_APP` | `backendAppName` output |
| `DEMO_TARGET_APP` | `demoTargetAppName` output |
| `MIGRATE_JOB` | `migrateJobName` output |
| `SWA_NAME` | `staticWebAppName` output |
| `API_URL` | `$API_URL` |

Run Actions, Deploy (manual), Run workflow. It builds and pushes both images
tagged with the commit SHA, runs the migration job and **stops if it fails** (the
apps are not updated), updates both apps, waits for `/health`, then builds and
deploys the frontend. Actions are pinned to exact release tags; for stronger
supply-chain protection replace them with full commit SHAs (Dependabot can
maintain them).

## 12. End-to-end verification

Keep the code out of shell history: `read -rs CODE`.

1. **Health**: `curl -s "$API_URL/health"` returns `{"status":"ok","database":"ok"}`.
2. **401 without a token**: `curl -s -o /dev/null -w "%{http_code}\n" "$API_URL/benchmark/runs"` prints `401`.
3. **Login**:
   ```bash
   TOKEN=$(curl -s -X POST "$API_URL/auth/login" -H "Content-Type: application/json" \
     -d "$(printf '{"code":"%s"}' "$CODE")" | jq -r .token)
   ```
4. **SSRF and allowlist rejections** (each should print `422`):
   ```bash
   for T in http://169.254.169.254/latest/meta-data/ http://localhost:8000/ http://10.0.0.1/ https://example.com/; do
     curl -s -o /dev/null -w "%{http_code} $T\n" -X POST "$API_URL/benchmark" \
       -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
       -d "{\"target_url\":\"$T\",\"method\":\"GET\",\"num_requests\":5,\"concurrency\":2}"
   done
   ```
5. **A small run against the demo target** (expect `202`, then status `done`):
   ```bash
   curl -s -X POST "$API_URL/benchmark" -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d "{\"target_url\":\"$DEMO_URL\",\"method\":\"GET\",\"num_requests\":20,\"concurrency\":4}"
   ```
6. **Charts render**: open `WEB_URL`, sign in (or use the magic link), start a run
   from the form, and watch it go pending, running, done; the chart shows the new
   bars. The browser console must show no CSP violations.
7. **Diagnose answers**: ask "which run had the highest p99?". It should answer
   from the seeded runs. An empty or failing answer usually means the index is
   missing (section 7) or `--index` was skipped.
8. **Caps and quotas**: send 501 requests with curl and expect `422`; start a
   second run while one is active and expect `429` with a readable message.
9. **Restart leaves no stuck runs**: start a run, then
   `az containerapp revision restart -g "$RG" -n "$BACKEND_APP" --revision <name>`.
   After about 3 minutes (wall-clock limit plus grace) the run reads "timed out
   or failed", not "running".
10. **LLM route off**: `POST /benchmark/llm` with a valid token returns `404`.
11. **Logs are clean**: in Log Analytics search the backend logs for your code or
    token text. There should be none.

## 13. Rollback

- **Bad backend release**: list revisions with
  `az containerapp revision list -g "$RG" -n "$BACKEND_APP" -o table`, then
  redeploy the previous image tag with
  `az containerapp update -g "$RG" -n "$BACKEND_APP" --image "$ACR.azurecr.io/queryscope-backend:<previous tag>"`,
  or re-run the Deploy workflow from the previous good commit.
- **Bad migration**: prefer a forward fix. To step back one migration, change the
  job command to `alembic downgrade -1`, run it once, then restore
  `alembic upgrade head`. Only if the migration is reversible and no newer code
  depends on it. Postgres also has 7-day point-in-time restore.
- **Bad frontend**: re-run the workflow from the previous commit.
- **Emergency stop**: revoke codes (tokens die immediately), or
  `az containerapp ingress disable -g "$RG" -n "$BACKEND_APP"` (re-enable with
  `ingress enable --type external --target-port 8000`).
- **Total removal**: `az group delete -n "$RG"`. Key Vault has purge protection,
  so its name stays reserved for 7 days.

## 14. Backend environment variables

Read by `backend/app/core/config.py`. "Bicep" values come from `infra/main.bicep`;
secrets live in Key Vault and are injected through the managed identity.

| Variable | Secret? | Hosted value / note |
|---|---|---|
| `AUTH_ENABLED` | no | `true` (Bicep). Never `false` on the internet. |
| `SESSION_SECRET` | **yes** | Key Vault `session-secret`. 32+ random chars. |
| `CODE_PEPPER` | **yes** | Key Vault `code-pepper`. Changing it invalidates every code. |
| `ADMIN_API_KEY` | **yes** | Key Vault `admin-api-key`. Empty disables admin routes. |
| `DATABASE_URL` | **yes** | Key Vault `database-url` (contains the DB password). |
| `AZURE_SEARCH_KEY` | **yes** | Key Vault `azure-search-key` (the rotated admin key). |
| `OPENAI_API_KEY` | **yes** | Key Vault `openai-api-key` (new project key with a hard cap). |
| `AZURE_SEARCH_ENDPOINT` | no | Bicep parameter `azureSearchEndpoint`. |
| `AZURE_SEARCH_INDEX` | no | `benchmark-runs-prod` (Bicep default). |
| `CORS_ORIGINS` | no | JSON list with the exact Static Web App origin (Bicep). |
| `TRUSTED_PROXY_HOPS` | no | `1`; see section 10. |
| `ALLOWED_TARGET_HOSTS` | no | `httpbin.org,<demo target host>` (Bicep). Exact hostnames. |
| `DEMO_TARGET_URL` | no | `https://<demo target host>/work` (Bicep). |
| `LLM_BENCHMARK_ENABLED` | no | `false` (Bicep). |
| `RUN_MIGRATIONS` | no | `false`. Only the migrate job migrates. |
| `TARGET_ALLOWLIST_ENABLED` | no | Leave unset: on when auth is on. |
| `BLOCK_PRIVATE_TARGETS` | no | Leave `true` (default). |
| `MAX_NUM_REQUESTS`, `MAX_CONCURRENCY`, `MAX_REQUEST_TIMEOUT_S`, `RUN_WALL_CLOCK_LIMIT_S` | no | Defaults 500, 20, 10, 60. |
| `MAX_CONCURRENT_RUNS`, `MAX_ACTIVE_RUNS_PER_CODE` | no | Defaults 2 and 1. |
| `DAILY_BUDGET_PER_CODE`, `DAILY_BUDGET_GLOBAL` | no | Defaults 2,000 and 10,000 requests per UTC day. |
| `TOKEN_TTL_HOURS` | no | Default 12. |
| `LOGIN_MAX_FAILURES_PER_IP`, `LOGIN_MAX_FAILURES_GLOBAL`, `LOGIN_WINDOW_SECONDS` | no | Defaults 5, 100, 900. |
| `REAPER_GRACE_SECONDS`, `REAPER_INTERVAL_SECONDS` | no | Defaults 120 and 60. |
| `DNS_RESOLVE_TIMEOUT_S`, `HEALTH_DB_TIMEOUT_S` | no | Defaults 5 and 3. |
| `DEBUG`, `APP_NAME` | no | Leave default. |

Frontend build-time variable: `VITE_API_URL` (public in the bundle, not a secret).
It must be the https backend origin; `build:swa` refuses anything else.

## 15. Rough monthly cost (estimates, verify before relying on them)

Assumes one US region, light recruiter traffic, always-on single replicas.

| Item | Rough monthly cost | Notes |
|---|---|---|
| Container Apps, backend (0.5 vCPU, 1 GiB, always on) | about 5 to 15 USD | Mostly billed at the lower idle rate; a monthly free grant of vCPU-seconds, GiB-seconds and requests offsets part of it. |
| Container Apps, demo target (0.25 vCPU, 0.5 GiB) | about 2 to 6 USD | The free grant is shared across the subscription. |
| PostgreSQL Flexible Server, B1ms, 32 GB | about 15 to 20 USD | New Azure free accounts have included a 12-month allowance for a B1ms server and storage; check your offer. |
| Container Registry, Basic | about 5 USD | |
| Key Vault, Log Analytics (capped at 1 GB/day), Static Web Apps Free | about 0 to 3 USD | Log Analytics has a free monthly ingestion allowance. |
| OpenAI (embeddings and diagnose answers) | cents to a few USD | Bounded by your project hard cap. |
| **Azure AI Search** | **0 USD on the Free tier, roughly 70+ USD on Basic** | The dominant cost if you have no service yet. The Free tier allows a few small indexes and should be enough for this demo; check current limits. |

Typical total: about **30 to 50 USD per month**, plus Azure AI Search if you need a
paid tier. A credit of about 100 USD (Azure for Students) would cover roughly two
to three months. Static Web Apps Free and the Container Apps monthly grants
apply to any subscription; the Postgres free allowance only to eligible accounts.
Delete the resource group when the demo period ends.

## 16. Not validated, and not done

- The Bicep templates were **not compiled or deployed**: no Bicep or Azure CLI was
  available when they were written. Run `az bicep build --file infra/main.bicep`
  first and fix any error or warning. Metric names in the alert rules
  (`RestartCount`, `Requests`, `storage_percent`) and the preview Postgres API
  version are the likeliest places to need an adjustment.
- The Dockerfiles were not built (no Docker daemon was running). CI does not
  build images either; the first build happens in the deploy workflow.
- The workflows passed `actionlint` but were never run.
- The local `docker-compose.yml` still uses the old Docker Hub images, which
  predate access control. If you rebuild them from current source, run locally
  with `AUTH_ENABLED=false` in `backend/.env`.
- `k8s/` is unchanged and assumes multiple replicas; do not use it for the hosted
  deployment (section 0).
- Postgres accepts connections from any Azure service (firewall rule `0.0.0.0`)
  and is protected by TLS plus a random password. For a stricter setup, use
  VNet-integrated Container Apps with a private endpoint; that costs more and was
  left out to keep the demo simple.
