# terraform/compute.tf

# App Service Plan for CLE, EIC, and CM services
resource "azurerm_service_plan" "main" {
  name                = local.resource_names.app_service_plan
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = var.app_service_sku_name
  
  # Zone redundancy for production
  zone_balancing_enabled = var.environment == "production"
  
  tags = local.common_tags
}

# App Services for each microservice
resource "azurerm_linux_web_app" "cle" {
  name                = "app-${local.prefix}-cle-${local.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  service_plan_id     = azurerm_service_plan.main.id
  
  # Application settings
  app_settings = {
    "WEBSITES_ENABLE_APP_SERVICE_STORAGE" = "false"
    "DOCKER_REGISTRY_SERVER_URL"          = "https://${azurerm_container_registry.main.login_server}"
    "WEBSITES_PORT"                       = "8001"
    "SCM_DO_BUILD_DURING_DEPLOYMENT"      = "true"
    
    # Application configuration
    "SERVICE_NAME"     = "cle"
    "ENVIRONMENT"      = var.environment
    "KEY_VAULT_URL"    = azurerm_key_vault.main.vault_uri
    "DATABASE_URL"     = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/database-connection-string/)"
    "REDIS_URL"        = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/redis-connection-string/)"
    "APPLICATIONINSIGHTS_CONNECTION_STRING" = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/app-insights-connection-string/)"
  }
  
  # Container configuration
  site_config {
    always_on         = var.environment == "production"
    ftps_state        = "Disabled"
    http2_enabled     = true
    minimum_tls_version = "1.2"
    
    # Health check
    health_check_path = "/health"
    health_check_eviction_time_in_min = 2
    
    application_stack {
      docker_image_name   = "cashappagent/cle:latest"
      docker_registry_url = "https://${azurerm_container_registry.main.login_server}"
    }
    
    # CORS settings
    cors {
      allowed_origins = ["https://${azurerm_linux_web_app.frontend.default_hostname}"]
    }
    
    # IP restrictions
    dynamic "ip_restriction" {
      for_each = var.allowed_ip_ranges
      content {
        ip_address = ip_restriction.value
        action     = "Allow"
        priority   = 100 + ip_restriction.key
        name       = "AllowedIP${ip_restriction.key}"
      }
    }
  }
  
  # Managed identity
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app_identity.id]
  }
  
  # VNet integration
  dynamic "virtual_network_subnet_id" {
    for_each = var.enable_app_service_vnet_integration ? [azurerm_subnet.app.id] : []
    content {
      virtual_network_subnet_id = virtual_network_subnet_id.value
    }
  }
  
  tags = local.common_tags
}

resource "azurerm_linux_web_app" "eic" {
  name                = "app-${local.prefix}-eic-${local.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  service_plan_id     = azurerm_service_plan.main.id
  
  app_settings = {
    "WEBSITES_ENABLE_APP_SERVICE_STORAGE" = "false"
    "DOCKER_REGISTRY_SERVER_URL"          = "https://${azurerm_container_registry.main.login_server}"
    "WEBSITES_PORT"                       = "8003"
    
    "SERVICE_NAME"     = "eic"
    "ENVIRONMENT"      = var.environment
    "KEY_VAULT_URL"    = azurerm_key_vault.main.vault_uri
    "DATABASE_URL"     = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/database-connection-string/)"
    "APPLICATIONINSIGHTS_CONNECTION_STRING" = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/app-insights-connection-string/)"
  }
  
  site_config {
    always_on         = var.environment == "production"
    ftps_state        = "Disabled"
    http2_enabled     = true
    minimum_tls_version = "1.2"
    health_check_path = "/health"
    
    application_stack {
      docker_image_name   = "cashappagent/eic:latest"
      docker_registry_url = "https://${azurerm_container_registry.main.login_server}"
    }
  }
  
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app_identity.id]
  }
  
  tags = local.common_tags
}

resource "azurerm_linux_web_app" "cm" {
  name                = "app-${local.prefix}-cm-${local.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  service_plan_id     = azurerm_service_plan.main.id
  
  app_settings = {
    "WEBSITES_ENABLE_APP_SERVICE_STORAGE" = "false"
    "DOCKER_REGISTRY_SERVER_URL"          = "https://${azurerm_container_registry.main.login_server}"
    "WEBSITES_PORT"                       = "8004"
    
    "SERVICE_NAME"     = "cm"
    "ENVIRONMENT"      = var.environment
    "KEY_VAULT_URL"    = azurerm_key_vault.main.vault_uri
    "AZURE_CLIENT_ID"  = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/app-client-id/)"
    "AZURE_CLIENT_SECRET" = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/app-client-secret/)"
    "AZURE_TENANT_ID"  = data.azurerm_client_config.current.tenant_id
    "APPLICATIONINSIGHTS_CONNECTION_STRING" = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault.main.vault_uri}secrets/app-insights-connection-string/)"
  }
  
  site_config {
    always_on         = var.environment == "production"
    ftps_state        = "Disabled"
    http2_enabled     = true
    minimum_tls_version = "1.2"
    health_check_path = "/health"
    
    application_stack {
      docker_image_name   = "cashappagent/cm:latest"
      docker_registry_url = "https://${azurerm_container_registry.main.login_server}"
    }
  }
  
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app_identity.id]
  }
  
  tags = local.common_tags
}

# Simple frontend app for monitoring (optional)
resource "azurerm_linux_web_app" "frontend" {
  name                = "app-${local.prefix}-frontend-${local.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  service_plan_id     = azurerm_service_plan.main.id
  
  app_settings = {
    "WEBSITES_ENABLE_APP_SERVICE_STORAGE" = "false"
    "DOCKER_REGISTRY_SERVER_URL"          = "https://${azurerm_container_registry.main.login_server}"
    
    # API endpoints
    "CLE_API_URL" = "https://${azurerm_linux_web_app.cle.default_hostname}"
    "EIC_API_URL" = "https://${azurerm_linux_web_app.eic.default_hostname}"
    "CM_API_URL"  = "https://${azurerm_linux_web_app.cm.default_hostname}"
  }
  
  site_config {
    always_on         = var.environment == "production"
    ftps_state        = "Disabled"
    http2_enabled     = true
    minimum_tls_version = "1.2"
    
    application_stack {
      docker_image_name   = "nginx:alpine"
      docker_registry_url = "https://index.docker.io"
    }
  }
  
  tags = local.common_tags
}

# AKS Cluster for DIM (AI/ML workloads)
resource "azurerm_kubernetes_cluster" "dim" {
  name                = local.resource_names.kubernetes_cluster
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  dns_prefix          = "${local.prefix}-${local.environment}"
  kubernetes_version  = var.kubernetes_version
  
  # Networking
  network_profile {
    network_plugin    = "azure"
    network_policy    = "azure"
    dns_service_ip    = "10.100.0.10"
    service_cidr      = "10.100.0.0/16"
    
    # Load balancer
    load_balancer_sku = "standard"
    outbound_type     = "loadBalancer"
  }
  
  # Default node pool (system workloads)
  default_node_pool {
    name                = "system"
    node_count          = var.aks_system_node_count
    vm_size             = var.aks_system_vm_size
    vnet_subnet_id      = azurerm_subnet.ai.id
    type                = "VirtualMachineScaleSets"
    enable_auto_scaling = true
    min_count           = 1
    max_count           = 5
    max_pods            = 30
    os_disk_size_gb     = 30
    
    # System node pool should only run system workloads
    only_critical_addons_enabled = true
    
    # Node labels
    node_labels = {
      "workload-type" = "system"
    }
    
    tags = local.common_tags
  }
  
  # Identity
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.ai_identity.id]
  }
  
  # RBAC and security
  role_based_access_control_enabled = true
  
  azure_active_directory_role_based_access_control {
    managed                = true
    tenant_id              = data.azurerm_client_config.current.tenant_id
    admin_group_object_ids = var.aks_admin_group_ids
    azure_rbac_enabled     = true
  }
  
  # API server access
  api_server_access_profile {
    vnet_integration_enabled = true
    subnet_id                = azurerm_subnet.ai.id
    authorized_ip_ranges     = var.aks_authorized_ip_ranges
  }
  
  # Add-ons
  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  }
  
  key_vault_secrets_provider {
    secret_rotation_enabled = true
  }
  
  tags = local.common_tags
}

# GPU node pool for ML workloads
resource "azurerm_kubernetes_cluster_node_pool" "gpu" {
  name                  = "gpu"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.dim.id
  vm_size               = var.aks_gpu_vm_size
  node_count            = var.aks_gpu_node_count
  vnet_subnet_id        = azurerm_subnet.ai.id
  
  # Auto-scaling
  enable_auto_scaling = true
  min_count          = 0  # Can scale to zero when not in use
  max_count          = 3
  
  # Node configuration
  max_pods        = 30
  os_disk_size_gb = 100
  
  # Node labels and taints for GPU workloads
  node_labels = {
    "workload-type" = "gpu"
    "node-type"     = "gpu"
  }
  
  node_taints = [
    "workload-type=gpu:NoSchedule"
  ]
  
  tags = local.common_tags
}

# Role assignments for AKS
resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.dim.kubelet_identity[0].object_id
}

resource "azurerm_role_assignment" "aks_network_contributor" {
  scope                = azurerm_subnet.ai.id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_user_assigned_identity.ai_identity.principal_id
}