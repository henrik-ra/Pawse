// Pawse — cloud backend (Bicep entrypoint, subscription scope).
//
// Creates a resource group and deploys the full Pawse stack into it:
//   Managed Identity · ACR · Cosmos DB (serverless) · Container Apps ·
//   Static Web App · Log Analytics + Application Insights.
//
// Everything authenticates with a user-assigned managed identity — no secrets,
// no connection strings in code. Designed to deploy with `azd up`.

targetScope = 'subscription'

@minLength(1)
@maxLength(20)
@description('Environment name (azd). Used to name the resource group and seed a unique resource token.')
param environmentName string

@minLength(1)
@description('Primary location for all resources.')
param location string

@description('Container image for the Pawse API. Defaults to a placeholder; azd/CI replaces it with the image built from cloud/.')
param apiImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Optional API key protecting POST /api/days. Empty keeps ingestion open for the demo.')
@secure()
param apiKey string = ''

var tags = {
  'azd-env-name': environmentName
  workload: 'pawse'
}

// Short, deterministic suffix so every resource gets a globally-unique name.
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  scope: rg
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    apiImage: apiImage
    apiKey: apiKey
  }
}

@description('Login server of the container registry — azd pushes the API image here.')
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.acrLoginServer

@description('Public HTTPS endpoint of the Pawse API (also serves the dashboard).')
output SERVICE_API_ENDPOINT string = resources.outputs.apiUrl

@description('Dashboard URL (served by the container app, same origin as the API).')
output DASHBOARD_URL string = resources.outputs.dashboardUrl

@description('Cosmos DB account endpoint (data-plane access is via managed identity).')
output AZURE_COSMOS_ENDPOINT string = resources.outputs.cosmosEndpoint

output AZURE_LOCATION string = location
