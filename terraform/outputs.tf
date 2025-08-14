# terraform/outputs.tf

output "resource_group_name" {
  description = "Name of the main resource group"
  value       = azurerm_resource_group.main.name
}

output "location" {
  description = "Azure region where resources are deployed"
  value       = azurerm_resource_group.main.location
}

# Networking outputs
output "vnet_id" {
  description = "Virtual network ID"
  value       = azurerm_virtual_network.main.id
}

output "vnet_name" {
  description = "Virtual network name"
  value       = azurerm_virtual_network.main.name
}

output "subnet_ids" {
  description = "Subnet IDs"
  value = {
    app  = azurerm_subnet.app.id
    data = azurerm_subnet.data.id
    ai   = azurerm_subnet.ai.id
  }
}

# Storage outputs
output "storage_account_name" {
  description = "Storage account name"
  value       = azurerm_storage_account.main.name
  sensitive   = true
}

output "storage_account_id" {
  description = "Storage account ID"
  value       = azurerm_storage_account.main.id
}

output "container_registry_name" {
  description = "Container registry name"
  value       = azurerm_container_registry.main.name
}

output "container_registry_login_server" {
  description = "Container registry login server"
  value       = azurerm_container_registry.main.login_server
}

# Security outputs
output "key_vault_id" {
  description = "Key Vault ID"
  value       = azurerm_key_vault.main.id
}

output "key_vault_uri" {
  description = "Key Vault URI"
  value       = azurerm_key_vault.main.vault_uri
  sensitive   = true
}

output "app_identity_id" {
  description = "Application managed identity ID"
  value       = azurerm_user_assigned_identity.app_identity.id
}

output "app_identity_principal_id" {
  description = "Application managed identity principal ID"
  value       = azurerm_user_assigned_identity.app_identity.principal_id
}

# Database outputs
output "postgresql_server_name" {
  description = "PostgreSQL server name"
  value       = azurerm_postgresql_flexible_server.main.name
}

output "postgresql_server_fqdn" {
  description = "PostgreSQL server FQDN"
  value       = azurerm_postgresql_flexible_server.main.fqdn
  sensitive   = true
}

output "redis_cache_hostname" {
  description = "Redis cache hostname"
  value       = azurerm_redis_cache.main.hostname
  sensitive   = true
}

# Compute outputs
output "app_service_plan_id" {
  description = "App Service Plan ID"
  value       = azurerm_service_plan.main.id
}

output "app_service_urls" {
  description = "App Service URLs"
  value = {
    cle      = "https://${azurerm_linux_web_app.cle.default_hostname}"
    eic      = "https://${azurerm_linux_web_app.eic.default_hostname}"
    cm       = "https://${azurerm_linux_web_app.cm.default_hostname}"
    frontend = "https://${azurerm_linux_web_app.frontend.default_hostname}"
  }
  sensitive = true
}

output "aks_cluster_name" {
  description = "AKS cluster name"
  value       = azurerm_kubernetes_cluster.dim.name
}

output "aks_cluster_id" {
  description = "AKS cluster ID"
  value       = azurerm_kubernetes_cluster.dim.id
}

output "aks_cluster_fqdn" {
  description = "AKS cluster FQDN"
  value       = azurerm_kubernetes_cluster.dim.fqdn
  sensitive   = true
}

# Monitoring outputs
output "log_analytics_workspace_id" {
  description = "Log Analytics workspace ID"
  value       = azurerm_log_analytics_workspace.main.id
}

output "application_insights_instrumentation_key" {
  description = "Application Insights instrumentation key"
  value       = azurerm_application_insights.main.instrumentation_key
  sensitive   = true
}

output "application_insights_connection_string" {
  description = "Application Insights connection string"
  value       = azurerm_application_insights.main.connection_string
  sensitive   = true
}

# Application registration outputs
output "app_registration_client_id" {
  description = "Application registration client ID"
  value       = azuread_application.cashapp_agent.client_id
  sensitive   = true
}

# Environment information
output "environment" {
  description = "Environment name"
  value       = var.environment
}

output "deployment_timestamp" {
  description = "Deployment timestamp"
  value       = timestamp()
}