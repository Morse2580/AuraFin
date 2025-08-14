# terraform/monitoring.tf

# Log Analytics Workspace
resource "azurerm_log_analytics_workspace" "main" {
  name                = local.resource_names.log_analytics
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = var.log_analytics_sku
  retention_in_days   = var.log_analytics_retention_days
  
  tags = local.common_tags
}

# Application Insights
resource "azurerm_application_insights" "main" {
  name                = local.resource_names.application_insights
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"
  
  tags = local.common_tags
}

# Store Application Insights connection string in Key Vault
resource "azurerm_key_vault_secret" "app_insights_connection_string" {
  name         = "app-insights-connection-string"
  value        = azurerm_application_insights.main.connection_string
  key_vault_id = azurerm_key_vault.main.id
  
  depends_on = [azurerm_role_assignment.app_key_vault_secrets_user]
}

# Store Application Insights instrumentation key in Key Vault
resource "azurerm_key_vault_secret" "app_insights_instrumentation_key" {
  name         = "app-insights-instrumentation-key"
  value        = azurerm_application_insights.main.instrumentation_key
  key_vault_id = azurerm_key_vault.main.id
  
  depends_on = [azurerm_role_assignment.app_key_vault_secrets_user]
}

# Action Group for alerts
resource "azurerm_monitor_action_group" "main" {
  name                = "ag-${local.prefix}-${local.environment}"
  resource_group_name = azurerm_resource_group.main.name
  short_name          = "cashapp"
  
  email_receiver {
    name          = "ops-team"
    email_address = var.ops_team_email
  }
  
  dynamic "webhook_receiver" {
    for_each = var.slack_webhook_url != "" ? [1] : []
    content {
      name        = "slack-alerts"
      service_uri = var.slack_webhook_url
    }
  }
  
  tags = local.common_tags
}

# Alert rules
resource "azurerm_monitor_metric_alert" "high_cpu" {
  name                = "alert-high-cpu-${local.environment}"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_postgresql_flexible_server.main.id]
  description         = "High CPU usage on PostgreSQL server"
  
  criteria {
    metric_namespace = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name      = "cpu_percent"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = 80
  }
  
  window_size        = "PT15M"
  frequency          = "PT5M"
  severity           = 2
  
  action {
    action_group_id = azurerm_monitor_action_group.main.id
  }
  
  tags = local.common_tags
}

resource "azurerm_monitor_metric_alert" "high_memory" {
  name                = "alert-high-memory-${local.environment}"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_postgresql_flexible_server.main.id]
  description         = "High memory usage on PostgreSQL server"
  
  criteria {
    metric_namespace = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name      = "memory_percent"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = 85
  }
  
  window_size        = "PT15M"
  frequency          = "PT5M"
  severity           = 2
  
  action {
    action_group_id = azurerm_monitor_action_group.main.id
  }
  
  tags = local.common_tags
}

resource "azurerm_monitor_metric_alert" "storage_usage" {
  name                = "alert-storage-usage-${local.environment}"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_storage_account.main.id]
  description         = "High storage usage"
  
  criteria {
    metric_namespace = "Microsoft.Storage/storageAccounts"
    metric_name      = "UsedCapacity"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = var.storage_alert_threshold_gb * 1024 * 1024 * 1024 # Convert GB to bytes
  }
  
  window_size        = "PT1H"
  frequency          = "PT15M"
  severity           = 3
  
  action {
    action_group_id = azurerm_monitor_action_group.main.id
  }
  
  tags = local.common_tags
}

