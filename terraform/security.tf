# terraform/security.tf

# Key Vault for secrets management
resource "azurerm_key_vault" "main" {
  name                = local.resource_names.key_vault
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = var.key_vault_sku

  # Security settings
  enable_rbac_authorization       = true
  enabled_for_disk_encryption     = true
  enabled_for_deployment          = true
  enabled_for_template_deployment = true
  purge_protection_enabled        = var.environment == "production"
  soft_delete_retention_days      = 30

  # Network access rules
  network_acls {
    bypass         = "AzureServices"
    default_action = "Deny"
    
    virtual_network_subnet_ids = [
      azurerm_subnet.app.id,
      azurerm_subnet.ai.id
    ]
    
    ip_rules = var.management_ip_ranges
  }

  tags = local.common_tags
}

# Private endpoint for Key Vault
resource "azurerm_private_endpoint" "keyvault" {
  name                = "pe-${azurerm_key_vault.main.name}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  subnet_id           = azurerm_subnet.data.id

  private_service_connection {
    name                           = "psc-${azurerm_key_vault.main.name}"
    private_connection_resource_id = azurerm_key_vault.main.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.keyvault.id]
  }

  tags = local.common_tags
}

# Managed Identity for applications
resource "azurerm_user_assigned_identity" "app_identity" {
  name                = "id-${local.prefix}-app-${local.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.common_tags
}

resource "azurerm_user_assigned_identity" "ai_identity" {
  name                = "id-${local.prefix}-ai-${local.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.common_tags
}

# Role assignments for managed identities
resource "azurerm_role_assignment" "app_storage_blob_contributor" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.app_identity.principal_id
}

resource "azurerm_role_assignment" "app_key_vault_secrets_user" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app_identity.principal_id
}

resource "azurerm_role_assignment" "ai_storage_blob_contributor" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.ai_identity.principal_id
}

resource "azurerm_role_assignment" "ai_key_vault_secrets_user" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.ai_identity.principal_id
}

# Application registration for service authentication
resource "azuread_application" "cashapp_agent" {
  display_name = "CashAppAgent-${local.environment}"
  
  required_resource_access {
    resource_app_id = "00000003-0000-0000-c000-000000000000" # Microsoft Graph
    
    resource_access {
      id   = "75359482-378d-4052-8f01-80520e7db3cd" # Files.ReadWrite.All
      type = "Role"
    }
    
    resource_access {
      id   = "b633e1c5-b582-4048-a93e-9f11b44c7e96" # Mail.Send
      type = "Role"
    }
  }
  
  web {
    redirect_uris = var.app_redirect_uris
  }
}

resource "azuread_service_principal" "cashapp_agent" {
  client_id = azuread_application.cashapp_agent.client_id
  
  tags = [
    "Environment:${local.environment}",
    "Project:CashAppAgent"
  ]
}

resource "azuread_application_password" "cashapp_agent" {
  application_id = azuread_application.cashapp_agent.id
  display_name   = "CashAppAgent-Secret"
  end_date       = timeadd(timestamp(), "8760h") # 1 year
}

# Store secrets in Key Vault
resource "azurerm_key_vault_secret" "app_client_id" {
  name         = "app-client-id"
  value        = azuread_application.cashapp_agent.client_id
  key_vault_id = azurerm_key_vault.main.id
  
  depends_on = [azurerm_role_assignment.app_key_vault_secrets_user]
}

resource "azurerm_key_vault_secret" "app_client_secret" {
  name         = "app-client-secret"
  value        = azuread_application_password.cashapp_agent.value
  key_vault_id = azurerm_key_vault.main.id
  
  depends_on = [azurerm_role_assignment.app_key_vault_secrets_user]
}

