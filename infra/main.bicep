// QueryScope hosted demo. Resource group scope.
//
// Two-phase deploy (see docs/deploy.md):
//   1. deployApps=false  -> platform only (ACR, Key Vault, Postgres, environment, SWA)
//   2. push images and set Key Vault secrets, then deployApps=true -> apps and job
//
// No secret values live in this file. The Postgres admin password is a @secure
// parameter supplied at deploy time; every other secret is set in Key Vault by
// the operator and referenced by the apps through a managed identity.

targetScope = 'resourceGroup'

// ---------------------------------------------------------------- parameters

@description('Short lowercase prefix used in resource names (3-12 chars).')
@minLength(3)
@maxLength(12)
param namePrefix string

param location string = resourceGroup().location

@description('Static Web Apps is only available in some regions.')
@allowed(['westus2', 'centralus', 'eastus2', 'westeurope', 'eastasia'])
param staticWebAppLocation string = 'eastus2'

@description('Phase 1 = false (platform only). Phase 2 = true (apps and migration job).')
param deployApps bool = false

@description('Full image references, for example <acr>.azurecr.io/queryscope-backend:<tag>. Used when deployApps is true.')
param backendImage string = ''
param demoTargetImage string = ''

@description('Region for Postgres. Some subscriptions (for example Azure for Students) are blocked from Postgres in certain regions even when other services work there.')
param postgresLocation string = location
param postgresAdminUser string = 'qsadmin'
@secure()
param postgresAdminPassword string
param postgresDatabaseName string = 'queryscope'
@description('Smallest burstable SKU. Verify availability in your region.')
param postgresSkuName string = 'Standard_B1ms'
param postgresStorageGb int = 32
param postgresVersion string = '16'

param acrSku string = 'Basic'
param logRetentionDays int = 30
@description('Daily ingestion cap in GB for Log Analytics (-1 = no cap).')
param logDailyQuotaGb int = 1

param backendCpu string = '0.5'
param backendMemory string = '1Gi'
param demoTargetCpu string = '0.25'
param demoTargetMemory string = '0.5Gi'

@description('Azure AI Search endpoint (not a secret).')
param azureSearchEndpoint string
param azureSearchIndex string = 'benchmark-runs-prod'

@description('Comma-separated exact hostnames the backend may benchmark, in addition to the demo target (added automatically).')
param extraAllowedHosts string = 'httpbin.org'

@description('Extra CORS origins (for a custom domain). The Static Web App origin is always included.')
param extraCorsOrigins array = []

@description('Trusted reverse-proxy hops in front of the backend. See docs/deploy.md for how to verify.')
param trustedProxyHops int = 1

@description('Email for budget and alert notifications.')
param alertEmail string
@description('Purge protection blocks purging a deleted vault for the soft-delete period, which makes teardown and redeploy of a demo awkward. It cannot be turned off once on.')
param kvPurgeProtection bool = true
@description('Create the Consumption budget. Set false if the subscription type rejects it (for example Azure for Students) and create one in the portal instead.')
param createBudget bool = true
@description('Monthly budget in your billing currency.')
param monthlyBudget int = 40
param budgetStartDate string = '${utcNow('yyyy-MM')}-01'

param tags object = { app: 'queryscope', env: 'demo' }

// ----------------------------------------------------------------- variables

var suffix = uniqueString(resourceGroup().id)
var acrName = toLower('${namePrefix}acr${suffix}')
var kvName = toLower('${namePrefix}-kv-${take(suffix, 6)}')
var postgresName = toLower('${namePrefix}-pg-${take(suffix, 6)}')
var logName = '${namePrefix}-logs'
var envName = '${namePrefix}-env'
var identityName = '${namePrefix}-id'
var backendName = '${namePrefix}-api'
var demoTargetName = '${namePrefix}-target'
var migrateJobName = '${namePrefix}-migrate'
var swaName = '${namePrefix}-web'

var acrPullRole = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var kvSecretsUserRole = '4633458b-17de-408a-b874-0445c86b69e6'

// Container Apps hostnames are predictable from the environment's default
// domain, so they are known in phase 1, before any app exists. That lets the
// frontend build and the allowlist be set up ahead of the apps.
var backendHost = '${backendName}.${containerEnv.properties.defaultDomain}'
var demoTargetHost = '${demoTargetName}.${containerEnv.properties.defaultDomain}'
var allowedTargetHosts = '${extraAllowedHosts},${demoTargetHost}'
var demoTargetUrl = 'https://${demoTargetHost}/work'

var corsOrigins = concat(['https://${staticSite.properties.defaultHostname}'], extraCorsOrigins)

// ------------------------------------------------------------------ platform

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logName
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: logRetentionDays
    workspaceCapping: { dailyQuotaGb: logDailyQuotaGb }
  }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
  tags: tags
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: tags
  sku: { name: acrSku }
  properties: {
    adminUserEnabled: false // pull via managed identity, push via the deploy identity
  }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, identity.id, acrPullRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRole)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    // Omitted (null) when off: Key Vault rejects an explicit false on some API paths and it cannot be undone once true
    enablePurgeProtection: kvPurgeProtection ? true : null
    publicNetworkAccess: 'Enabled'
  }
}

resource kvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, identity.id, kvSecretsUserRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsUserRole)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: postgresName
  location: postgresLocation
  tags: tags
  sku: {
    name: postgresSkuName
    tier: 'Burstable'
  }
  properties: {
    version: postgresVersion
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    storage: { storageSizeGB: postgresStorageGb }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: { mode: 'Disabled' }
    network: { publicNetworkAccess: 'Enabled' }
  }
}

resource pgDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: postgresDatabaseName
}

// The 0.0.0.0 rule means "any Azure service". It is the simple option without a
// VNet; the database still requires TLS and a strong password. See docs/deploy.md
// for the tighter alternative.
resource pgAllowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgres
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource containerEnv 'Microsoft.App/managedEnvironments@2026-07-01' = {
  name: envName
  location: location
  tags: tags
  properties: {
    // Explicit on purpose: without it Azure created an Express environment for this
    // subscription, and Express rejects Jobs and Key Vault secret references.
    environmentMode: 'WorkloadProfiles'
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource staticSite 'Microsoft.Web/staticSites@2023-12-01' = {
  name: swaName
  location: staticWebAppLocation
  tags: tags
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {}
}

// ---------------------------------------------------------------------- apps

// Built from the name, not kv.properties, so it is known at the start of the deployment
var kvUri = 'https://${kvName}${environment().suffixes.keyvaultDns}/'

// Container Apps secret -> Key Vault reference through the managed identity.
var secretDefs = [
  { name: 'session-secret', kvName: 'session-secret' }
  { name: 'code-pepper', kvName: 'code-pepper' }
  { name: 'admin-api-key', kvName: 'admin-api-key' }
  { name: 'database-url', kvName: 'database-url' }
  { name: 'azure-search-key', kvName: 'azure-search-key' }
  { name: 'openai-api-key', kvName: 'openai-api-key' }
]

var appSecrets = [
  for s in secretDefs: {
    name: s.name
    keyVaultUrl: '${kvUri}secrets/${s.kvName}'
    identity: identity.id
  }
]

var backendEnv = [
  { name: 'AUTH_ENABLED', value: 'true' }
  { name: 'LLM_BENCHMARK_ENABLED', value: 'false' }
  { name: 'RUN_MIGRATIONS', value: 'false' }
  { name: 'CORS_ORIGINS', value: string(corsOrigins) }
  { name: 'TRUSTED_PROXY_HOPS', value: string(trustedProxyHops) }
  { name: 'AZURE_SEARCH_ENDPOINT', value: azureSearchEndpoint }
  { name: 'AZURE_SEARCH_INDEX', value: azureSearchIndex }
  { name: 'ALLOWED_TARGET_HOSTS', value: allowedTargetHosts }
  { name: 'DEMO_TARGET_URL', value: demoTargetUrl }
  { name: 'SESSION_SECRET', secretRef: 'session-secret' }
  { name: 'CODE_PEPPER', secretRef: 'code-pepper' }
  { name: 'ADMIN_API_KEY', secretRef: 'admin-api-key' }
  { name: 'DATABASE_URL', secretRef: 'database-url' }
  { name: 'AZURE_SEARCH_KEY', secretRef: 'azure-search-key' }
  { name: 'OPENAI_API_KEY', secretRef: 'openai-api-key' }
]

var registries = [
  {
    server: acr.properties.loginServer
    identity: identity.id
  }
]

resource backend 'Microsoft.App/containerApps@2024-03-01' = if (deployApps) {
  name: backendName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: registries
      secrets: appSecrets
    }
    template: {
      containers: [
        {
          name: 'backend'
          image: backendImage
          resources: {
            cpu: json(backendCpu)
            memory: backendMemory
          }
          env: backendEnv
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/health', port: 8000 }
              initialDelaySeconds: 20
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: { path: '/health', port: 8000 }
              periodSeconds: 10
            }
          ]
        }
      ]
      // Exactly one replica: the login throttle and the run admission lock are
      // in-process. Do not raise maxReplicas without moving them out of process.
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
  dependsOn: [acrPull, kvSecretsUser]
}

resource demoTarget 'Microsoft.App/containerApps@2024-03-01' = if (deployApps) {
  name: demoTargetName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
        allowInsecure: false
      }
      registries: registries
    }
    template: {
      containers: [
        {
          name: 'demo-target'
          image: demoTargetImage
          resources: {
            cpu: json(demoTargetCpu)
            memory: demoTargetMemory
          }
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/health', port: 8080 }
              periodSeconds: 30
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
  dependsOn: [acrPull]
}

// One-off migration job: started manually by the deploy workflow (or by hand).
resource migrateJob 'Microsoft.App/jobs@2024-03-01' = if (deployApps) {
  name: migrateJobName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    environmentId: containerEnv.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 600
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: registries
      secrets: [
        {
          name: 'database-url'
          keyVaultUrl: '${kvUri}secrets/database-url'
          identity: identity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'migrate'
          image: backendImage
          command: ['alembic']
          args: ['upgrade', 'head']
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            { name: 'DATABASE_URL', secretRef: 'database-url' }
          ]
        }
      ]
    }
  }
  dependsOn: [acrPull, kvSecretsUser]
}

// --------------------------------------------------------- budget and alerts

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: '${namePrefix}-alerts'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: take('${namePrefix}al', 12)
    enabled: true
    emailReceivers: [
      {
        name: 'owner'
        emailAddress: alertEmail
        useCommonAlertSchema: true
      }
    ]
  }
}

resource budget 'Microsoft.Consumption/budgets@2023-05-01' = if (createBudget) {
  name: '${namePrefix}-monthly'
  properties: {
    category: 'Cost'
    amount: monthlyBudget
    timeGrain: 'Monthly'
    timePeriod: { startDate: budgetStartDate }
    notifications: {
      actual50: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 50
        contactEmails: [alertEmail]
      }
      actual80: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 80
        contactEmails: [alertEmail]
      }
      forecast100: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 100
        thresholdType: 'Forecasted'
        contactEmails: [alertEmail]
      }
    }
  }
}

// Repeated restarts usually mean a crash loop or a bad secret.
resource restartAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = if (deployApps) {
  name: '${namePrefix}-api-restarts'
  location: 'global'
  tags: tags
  properties: {
    description: 'Backend restarted several times in 15 minutes'
    severity: 2
    enabled: true
    scopes: [backend.id]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'restarts'
          metricName: 'RestartCount'
          metricNamespace: 'Microsoft.App/containerApps'
          operator: 'GreaterThan'
          threshold: 3
          timeAggregation: 'Total'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [{ actionGroupId: actionGroup.id }]
  }
}

// Sustained server errors from the API.
resource errorAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = if (deployApps) {
  name: '${namePrefix}-api-5xx'
  location: 'global'
  tags: tags
  properties: {
    description: 'More than 20 5xx responses in 15 minutes'
    severity: 2
    enabled: true
    scopes: [backend.id]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'errors'
          metricName: 'Requests'
          metricNamespace: 'Microsoft.App/containerApps'
          operator: 'GreaterThan'
          threshold: 20
          timeAggregation: 'Total'
          criterionType: 'StaticThresholdCriterion'
          dimensions: [
            {
              name: 'statusCodeCategory'
              operator: 'Include'
              values: ['5xx']
            }
          ]
        }
      ]
    }
    actions: [{ actionGroupId: actionGroup.id }]
  }
}

resource dbStorageAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: '${namePrefix}-pg-storage'
  location: 'global'
  tags: tags
  properties: {
    description: 'Postgres storage above 80 percent'
    severity: 2
    enabled: true
    scopes: [postgres.id]
    evaluationFrequency: 'PT15M'
    windowSize: 'PT1H'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'storage'
          metricName: 'storage_percent'
          metricNamespace: 'Microsoft.DBforPostgreSQL/flexibleServers'
          operator: 'GreaterThan'
          threshold: 80
          timeAggregation: 'Average'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [{ actionGroupId: actionGroup.id }]
  }
}

// ------------------------------------------------------------------- outputs

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output keyVaultName string = kv.name
output identityName string = identity.name
output postgresHost string = postgres.properties.fullyQualifiedDomainName
output postgresDatabase string = postgresDatabaseName
output staticWebAppName string = staticSite.name
output staticWebAppUrl string = 'https://${staticSite.properties.defaultHostname}'
output backendAppName string = backendName
output demoTargetAppName string = demoTargetName
output migrateJobName string = migrateJobName
output backendUrl string = 'https://${backendHost}'
output demoTargetFqdn string = demoTargetHost
output demoTargetPublicUrl string = demoTargetUrl
