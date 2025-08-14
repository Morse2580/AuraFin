# terraform/main.tf

terraform {
  required_version = ">= 1.5"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.80"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.40"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }

  backend "azurerm" {
    # Configure this with your storage account details
    # resource_group_name  = "rg-cashappagent-tfstate"
    # storage_account_name = "sacashappagentstate"
    # container_name       = "tfstate"
    # key                  = "cashappagent.tfstate"
  }
}

# Configure Azure Provider
provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy    = true
      recover_soft_deleted_key_vaults = true
    }
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}

provider "azuread" {}

# Data sources
data "azurerm_client_config" "current" {}

data "azurerm_subscription" "current" {}

# Local values for consistency
locals {
  # Environment and naming
  environment = var.environment
  location    = var.location
  prefix      = "cashappagent"
  
  # Common tags
  common_tags = merge(var.tags, {
    Environment   = var.environment
    Project       = "CashAppAgent"
    ManagedBy     = "Terraform"
    CreatedDate   = timestamp()
    BusinessOwner = var.business_owner
    TechnicalOwner = var.technical_owner
  })
  
  # Resource naming convention
  resource_names = {
    resource_group          = "rg-${local.prefix}-${local.environment}"
    vnet                   = "vnet-${local.prefix}-${local.environment}"
    subnet_app             = "snet-${local.prefix}-app-${local.environment}"
    subnet_data            = "snet-${local.prefix}-data-${local.environment}"
    subnet_ai              = "snet-${local.prefix}-ai-${local.environment}"
    nsg_app                = "nsg-${local.prefix}-app-${local.environment}"
    nsg_data               = "nsg-${local.prefix}-data-${local.environment}"
    nsg_ai                 = "nsg-${local.prefix}-ai-${local.environment}"
    key_vault              = "kv-${local.prefix}-${local.environment}-${random_string.unique.result}"
    storage_account        = "sa${local.prefix}${local.environment}${random_string.unique.result}"
    container_registry     = "cr${local.prefix}${local.environment}${random_string.unique.result}"
    app_service_plan       = "asp-${local.prefix}-${local.environment}"
    postgresql_server      = "psql-${local.prefix}-${local.environment}-${random_string.unique.result}"
    application_insights   = "ai-${local.prefix}-${local.environment}"
    log_analytics         = "log-${local.prefix}-${local.environment}"
    kubernetes_cluster     = "aks-${local.prefix}-${local.environment}"
  }
  
  # Network configuration
  vnet_address_space = var.vnet_address_space
  subnet_config = {
    app = {
      address_prefixes = [cidrsubnet(local.vnet_address_space[0], 8, 1)]
      service_endpoints = [
        "Microsoft.Storage",
        "Microsoft.KeyVault",
        "Microsoft.Sql"
      ]
    }
    data = {
      address_prefixes = [cidrsubnet(local.vnet_address_space[0], 8, 2)]
      service_endpoints = [
        "Microsoft.Storage",
        "Microsoft.Sql"
      ]
    }
    ai = {
      address_prefixes = [cidrsubnet(local.vnet_address_space[0], 8, 3)]
      service_endpoints = [
        "Microsoft.Storage",
        "Microsoft.KeyVault"
      ]
    }
  }
}

# Generate unique suffix for globally unique resources
resource "random_string" "unique" {
  length  = 6
  special = false
  upper   = false
}

# Main Resource Group
resource "azurerm_resource_group" "main" {
  name     = local.resource_names.resource_group
  location = local.location
  tags     = local.common_tags

  lifecycle {
    prevent_destroy = true
  }
}