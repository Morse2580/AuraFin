# terraform/variables.tf

# Environment and basic configuration
variable "environment" {
  description = "Environment name (dev, staging, production, demo)"
  type        = string
  
  validation {
    condition     = contains(["dev", "staging", "production", "demo"], var.environment)
    error_message = "Environment must be dev, staging, production, or demo."
  }
}

variable "location" {
  description = "Azure region for resources"
  type        = string
  default     = "East US 2"
}

variable "business_owner" {
  description = "Business owner email"
  type        = string
}

variable "technical_owner" {
  description = "Technical owner email"
  type        = string
}

variable "tags" {
  description = "Additional tags for resources"
  type        = map(string)
  default     = {}
}

# Network configuration
variable "vnet_address_space" {
  description = "Address space for VNet"
  type        = list(string)
  default     = ["10.0.0.0/16"]
}

variable "enable_ddos_protection" {
  description = "Enable DDoS protection plan"
  type        = bool
  default     = false
}

variable "enable_app_service_vnet_integration" {
  description = "Enable VNet integration for App Services"
  type        = bool
  default     = true
}

variable "management_ip_range" {
  description = "IP range for management access"
  type        = string
  default     = "0.0.0.0/0"  # Restrict this in production
}

variable "management_ip_ranges" {
  description = "List of IP ranges for management access"
  type        = list(string)
  default     = []
}

variable "allowed_ip_ranges" {
  description = "List of allowed IP ranges for App Services"
  type        = list(string)
  default     = []
}

# Storage configuration
variable "storage_account_tier" {
  description = "Storage account tier"
  type        = string
  default     = "Standard"
}

variable "storage_replication_type" {
  description = "Storage account replication type"
  type        = string
  default     = "LRS"
  
  validation {
    condition     = contains(["LRS", "GRS", "RAGRS", "ZRS", "GZRS", "RAGZRS"], var.storage_replication_type)
    error_message = "Storage replication type must be a valid Azure replication type."
  }
}

variable "blob_soft_delete_days" {
  description = "Number of days to retain soft-deleted blobs"
  type        = number
  default     = 30
}

variable "storage_alert_threshold_gb" {
  description = "Storage usage alert threshold in GB"
  type        = number
  default     = 100
}

# Container Registry configuration
variable "acr_sku" {
  description = "Container Registry SKU"
  type        = string
  default     = "Standard"
}

variable "acr_retention_days" {
  description = "Container Registry retention policy days"
  type        = number
  default     = 30
}

# Key Vault configuration
variable "key_vault_sku" {
  description = "Key Vault SKU"
  type        = string
  default     = "standard"
}

# Database configuration
variable "postgresql_version" {
  description = "PostgreSQL version"
  type        = string
  default     = "14"
}

variable "postgresql_sku_name" {
  description = "PostgreSQL SKU name"
  type        = string
  default     = "GP_Standard_D2s_v3"
}

variable "postgresql_storage_mb" {
  description = "PostgreSQL storage in MB"
  type        = number
  default     = 32768  # 32 GB
}

variable "postgresql_admin_username" {
  description = "PostgreSQL admin username"
  type        = string
  default     = "cashappadmin"
}

variable "postgresql_backup_retention_days" {
  description = "PostgreSQL backup retention days"
  type        = number
  default     = 30
}

variable "postgresql_ha_enabled" {
  description = "Enable PostgreSQL high availability"
  type        = bool
  default     = false
}

variable "postgresql_maintenance_day" {
  description = "PostgreSQL maintenance day (0=Sunday)"
  type        = number
  default     = 0
}

variable "postgresql_maintenance_hour" {
  description = "PostgreSQL maintenance hour (0-23)"
  type        = number
  default     = 2
}

variable "postgresql_max_connections" {
  description = "PostgreSQL max connections"
  type        = string
  default     = "200"
}

# Redis configuration
variable "redis_capacity" {
  description = "Redis cache capacity"
  type        = number
  default     = 1
}

variable "redis_family" {
  description = "Redis cache family"
  type        = string
  default     = "C"
}

variable "redis_sku_name" {
  description = "Redis cache SKU name"
  type        = string
  default     = "Standard"
}

# App Service configuration
variable "app_service_sku_name" {
  description = "App Service Plan SKU name"
  type        = string
  default     = "P1v3"
}

# Kubernetes configuration
variable "kubernetes_version" {
  description = "Kubernetes version"
  type        = string
  default     = null  # Use latest stable
}

variable "aks_system_node_count" {
  description = "AKS system node pool node count"
  type        = number
  default     = 2
}

variable "aks_system_vm_size" {
  description = "AKS system node pool VM size"
  type        = string
  default     = "Standard_D2s_v3"
}

variable "aks_gpu_node_count" {
  description = "AKS GPU node pool node count"
  type        = number
  default     = 1
}

variable "aks_gpu_vm_size" {
  description = "AKS GPU node pool VM size"
  type        = string
  default     = "Standard_NC6s_v3"
}

variable "aks_admin_group_ids" {
  description = "Azure AD group IDs for AKS cluster admin access"
  type        = list(string)
  default     = []
}

variable "aks_authorized_ip_ranges" {
  description = "Authorized IP ranges for AKS API server"
  type        = list(string)
  default     = []
}

# Monitoring configuration
variable "log_analytics_sku" {
  description = "Log Analytics workspace SKU"
  type        = string
  default     = "PerGB2018"
}

variable "log_analytics_retention_days" {
  description = "Log Analytics data retention days"
  type        = number
  default     = 90
}

variable "ops_team_email" {
  description = "Operations team email for alerts"
  type        = string
}

variable "slack_webhook_url" {
  description = "Slack webhook URL for alerts"
  type        = string
  default     = ""
}

# Application configuration
variable "app_redirect_uris" {
  description = "Application redirect URIs"
  type        = list(string)
  default     = []
}