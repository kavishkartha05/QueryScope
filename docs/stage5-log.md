# Stage 5 log (resource names only, no values)

Subscription: Azure for Students (748dedb2-950b-4925-b4af-b573d0f89dc5). Region: westus2.
OIDC for GitHub is blocked (tenant does not allow app registrations); deploying from the laptop.

## Created
- Providers registered: Microsoft.App, ContainerRegistry, DBforPostgreSQL, KeyVault, OperationalInsights, Web, Insights, ManagedIdentity, Cdn
- Resource group: kqscope-rg
- Deployment `kqscope-platform` (deployApps=false) FAILED partway; these exist in kqscope-rg (westus2):
  kqscope-logs, kqscope-id, kqscopeacrq5k64cq4fxoro (ACR, AcrPull assigned), kqscope-kv-q5k64c (purge protection off),
  kqscope-alerts, kqscope-env, kqscope-web
- Not created (failed): Postgres kqscope-pg-q5k64c, Key Vault Secrets User assignment
- Local only: ~/.qs-stage5/pgpw (Postgres password file, to be deleted after Phase C)

## Failure notes
- Wrong Key Vault Secrets User role GUID in main.bicep (fixed in dbd0a69)
- Postgres is blocked for this subscription in westus2 ("Subscriptions are restricted from provisioning in this region"); centralus and westus are open

## Platform deployment `kqscope-platform` succeeded (retry, Postgres in westus)
- Postgres server kqscope-pg-q5k64c (westus, Standard_B1ms, v16), database queryscope, firewall rule AllowAzureServices
- Metric alert kqscope-pg-storage
- Role assignments for kqscope-id: AcrPull (ACR), Key Vault Secrets User (vault)
- Everything else is in westus2: kqscope-logs, kqscope-id, kqscopeacrq5k64cq4fxoro, kqscope-kv-q5k64c, kqscope-alerts (global), kqscope-env, kqscope-web
- Not created by design: budget (createBudget=false), apps and migration job (deployApps=false)

## Phase C: Key Vault secrets (names only) in kqscope-kv-q5k64c
- session-secret, code-pepper, admin-api-key, postgres-admin-password, database-url (ssl=require), azure-search-key, openai-api-key
- Role assignment: Key Vault Secrets Officer for krkartha@ucdavis.edu, vault scope only (remove after setup if desired)
- ~/.qs-stage5/pgpw deleted

## Phase D (part 1): images
- ACR Tasks is blocked for this subscription (TasksOperationsNotAllowed); built locally with --platform linux/amd64 and pushed
- Role assignment: AcrPush for krkartha@ucdavis.edu, registry scope only (remove after setup if desired)
- az CLI: use ~/.azcli-venv/bin/az (Homebrew az cannot install the containerapp extension)
- Images in kqscopeacrq5k64cq4fxoro: queryscope-backend:85fa8ad, queryscope-demo-target:85fa8ad

## Phase D (part 2): deployApps=true FAILED (nothing destructive)
- Created: kqscope-target (container app, westus2)
- Failed: kqscope-api, kqscope-migrate
- Cause: kqscope-env is a Container Apps *Express* environment (environmentMode Express); Express does not support Jobs or keyVaultUrl secrets
- kqscope-pg-q5k64c unchanged after the deploy (Standard_B1ms, v16, 32 GB, westus, Ready)
- ~/.qs-stage5/pgpw deleted again

## Phase D (part 3): environment recreated and apps deployed
- Deleted (after approval): container app kqscope-target, environment kqscope-env (it was an Express environment)
- Recreated kqscope-env as WorkloadProfiles (Consumption profile); new default domain thankfulcliff-1eb007f1.westus2.azurecontainerapps.io
- Created via deployApps=true (images :85fa8ad): kqscope-api (min=max=1), kqscope-target, job kqscope-migrate, alerts kqscope-api-restarts (RestartCount), kqscope-api-5xx (Requests)
- Migration job execution kqscope-migrate-bfl93uw: Succeeded (0001 to 0004); ssl=require worked with asyncpg + Alembic
- Backend URL: https://kqscope-api.thankfulcliff-1eb007f1.westus2.azurecontainerapps.io (health ok)
- Demo target: https://kqscope-target.thankfulcliff-1eb007f1.westus2.azurecontainerapps.io/work
- Static Web App URL (unchanged): https://green-beach-08d11881e.6.azurestaticapps.net
- ~/.qs-stage5/pgpw deleted after each use

## Phase E: index and seed (done by the user in an interactive exec shell)
- az containerapp exec needs a real TTY (fails non-interactively with termios error 19), so the scripts were run from the user's terminal
- Search index created: benchmark-runs-prod on queryscope-search (Free tier); the dev index benchmark-runs was not touched
- seed_demo.py --index: 4 demo runs created and indexed; second run skipped all 4 (idempotent)
- Postgres: 4 demo runs, exactly 1 demo baseline; index holds 4 documents
- OpenAI and Search keys both worked (no 401/403)
- First access code created by the user (label not recorded here)

## Phase F: frontend
- Built frontend/dist with build:swa (VITE_API_URL = backend URL above); CONTACT_EMAIL set (commit 6abb738 locally, pushed by the user)
- Deployed dist/ to kqscope-web by the user with the SWA CLI 2.1.0 (token via hidden prompt)
- Live checks passed: root 200 with CSP/nosniff/no-referrer/X-Frame-Options DENY; /anything 200; bundle contains API origin, no localhost:8000
- CORS: preflight from the SWA origin echoes it (no wildcard); an unknown origin gets no allow-origin; Retry-After is exposed
- Unauthenticated API: /health ok; /benchmark/runs 401; /config 401; /admin/codes 403; POST /benchmark/llm 401 (404 check needs a token, Phase G)
