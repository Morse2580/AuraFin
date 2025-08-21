# terraform/storage.tf

# Storage Account for documents and application data
resource "azurerm_storage_account" "main" {
  name                     = local.resource_names.storage_account
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = var.storage_account_tier
  account_replication_type = var.storage_replication_type
  
  # Security settings
  min_tls_version                = "TLS1_2"
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false
  
  # Enable advanced security features
  blob_properties {
    versioning_enabled       = true
    change_feed_enabled      = true
    change_feed_retention_in_days = 7
    last_access_time_enabled = true
    
    container_delete_retention_policy {
      days = var.blob_soft_delete_days
    }
    
    delete_retention_policy {
      days = var.blob_soft_delete_days
    }
  }
  
  # Network access rules
  network_rules {
    default_action             = "Deny"
    bypass                     = ["AzureServices"]
    virtual_network_subnet_ids = [
      azurerm_subnet.app.id,
      azurerm_subnet.ai.id
    ]
    
    # Allow access from management IPs
    ip_rules = var.management_ip_ranges
  }

  tags = local.common_tags
}

# Storage containers
resource "azurerm_storage_container" "documents" {
  name                  = "documents"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "models" {
  name                  = "models"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "logs" {
  name                  = "logs"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "backups" {
  name                  = "backups"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

# Private endpoint for storage account
resource "azurerm_private_endpoint" "storage" {
  name                = "pe-${azurerm_storage_account.main.name}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  subnet_id           = azurerm_subnet.data.id

  private_service_connection {
    name                           = "psc-${azurerm_storage_account.main.name}"
    private_connection_resource_id = azurerm_storage_account.main.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.blob.id]
  }

  tags = local.common_tags
}

# Container Registry for application images
resource "azurerm_container_registry" "main" {
  name                = local.resource_names.container_registry
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = var.acr_sku
  admin_enabled       = false
  
  # Advanced security features
  public_network_access_enabled = false
  network_rule_bypass_option    = "AzureServices"
  
  # Content trust and vulnerability scanning (Premium SKU only)
  # trust_policy {
  #   enabled = true
  # }
  
  # Retention policy only available in Premium SKU
  # retention_policy {
  #   days    = var.acr_retention_days
  #   enabled = true
  # }
  
  tags = local.common_tags
}