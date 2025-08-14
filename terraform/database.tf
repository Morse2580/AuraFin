# terraform/database.tf

# Random password for PostgreSQL
resource "random_password" "postgresql_admin" {
  length  = 32
  special = true
}

# PostgreSQL Flexible Server
resource "azurerm_postgresql_flexible_server" "main" {
  name                   = local.resource_names.postgresql_server
  resource_group_name    = azurerm_resource_group.main.name
  location               = azurerm_resource_group.main.location
  version                = var.postgresql_version
  administrator_login    = var.postgresql_admin_username
  administrator_password = random_password.postgresql_admin.result
  
  # Server configuration
  sku_name   = var.postgresql_sku_name
  storage_mb = var.postgresql_storage_mb
  
  # Backup configuration
  backup_retention_days        = var.postgresql_backup_retention_days
  geo_redundant_backup_enabled = var.environment == "production"
  
  # Network configuration
  delegated_subnet_id = azurerm_subnet.data.id
  private_dns_zone_id = azurerm_private_dns_zone.postgresql.id
  
  # High availability for production
  dynamic "high_availability" {
    for_each = var.postgresql_ha_enabled ? [1] : []
    content {
      mode = "ZoneRedundant"
    }
  }
  
  # Maintenance window
  maintenance_window {
    day_of_week  = var.postgresql_maintenance_day
    start_hour   = var.postgresql_maintenance_hour
    start_minute = 0
  }
  
  tags = local.common_tags
  
  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgresql]
}

# PostgreSQL server configuration
resource "azurerm_postgresql_flexible_server_configuration" "max_connections" {
  name      = "max_connections"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = var.postgresql_max_connections
}

resource "azurerm_postgresql_flexible_server_configuration" "shared_preload_libraries" {
  name      = "shared_preload_libraries"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "pg_stat_statements,pg_cron"
}

resource "azurerm_postgresql_flexible_server_configuration" "log_statement" {
  name      = "log_statement"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "mod"
}

resource "azurerm_postgresql_flexible_server_configuration" "log_min_duration_statement" {
  name      = "log_min_duration_statement"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "1000" # Log queries taking longer than 1 second
}

# PostgreSQL databases
resource "azurerm_postgresql_flexible_server_database" "cashapp_agent" {
  name      = "cashappagent"
  server_id = azurerm_postgresql_flexible_server.main.id
  collation = "en_US.utf8"
  charset   = "utf8"
}

resource "azurerm_postgresql_flexible_server_database" "monitoring" {
  name      = "monitoring"
  server_id = azurerm_postgresql_flexible_server.main.id
  collation = "en_US.utf8"
  charset   = "utf8"
}

# Store database connection string in Key Vault
resource "azurerm_key_vault_secret" "database_connection_string" {
  name         = "database-connection-string"
  value        = "postgresql://${var.postgresql_admin_username}:${random_password.postgresql_admin.result}@${azurerm_postgresql_flexible_server.main.fqdn}:5432/${azurerm_postgresql_flexible_server_database.cashapp_agent.name}?sslmode=require"
  key_vault_id = azurerm_key_vault.main.id
  
  depends_on = [azurerm_role_assignment.app_key_vault_secrets_user]
}

# Redis Cache for caching and session storage
resource "azurerm_redis_cache" "main" {
  name                = "redis-${local.prefix}-${local.environment}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  capacity            = var.redis_capacity
  family              = var.redis_family
  sku_name            = var.redis_sku_name
  
  # Security settings
  enable_non_ssl_port = false
  minimum_tls_version = "1.2"
  public_network_access_enabled = false
  
  # Network configuration
  subnet_id = azurerm_subnet.data.id
  
  # Redis configuration
  redis_configuration {
    maxmemory_policy = "allkeys-lru"
    notify_keyspace_events = "Ex"
  }
  
  # Backup configuration for production
  dynamic "patch_schedule" {
    for_each = var.environment == "production" ? [1] : []
    content {
      day_of_week    = "Sunday"
      start_hour_utc = 2
    }
  }
  
  tags = local.common_tags
}

# Store Redis connection string in Key Vault
resource "azurerm_key_vault_secret" "redis_connection_string" {
  name         = "redis-connection-string"
  value        = "rediss://:${azurerm_redis_cache.main.primary_access_key}@${azurerm_redis_cache.main.hostname}:${azurerm_redis_cache.main.ssl_port}"
  key_vault_id = azurerm_key_vault.main.id
  
  depends_on = [azurerm_role_assignment.app_key_vault_secrets_user]
}