using './main.bicep'

// azd injects AZURE_ENV_NAME / AZURE_LOCATION; the defaults make manual
// `az deployment sub create` runs work too.
param environmentName = readEnvironmentVariable('AZURE_ENV_NAME', 'pawse-dev')
param location = readEnvironmentVariable('AZURE_LOCATION', 'westeurope')
param apiKey = readEnvironmentVariable('PAWSE_API_KEY', '')
