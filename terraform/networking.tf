# terraform/networking.tf

# Virtual Network
resource "azurerm_virtual_network" "main" {
  name                = local.resource_names.vnet
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  address_space       = local.vnet_address_space
  tags                = local.common_tags

  # DDoS protection plan (optional for production)
  dynamic "ddos_protection_plan" {
    for_each = var.enable_ddos_protection ? [1] : []
    content {
      id     = azurerm_network_ddos_protection_plan.main[0].id
      enable = true
    }
  }
}

# DDoS Protection Plan (optional)
resource "azurerm_network_ddos_protection_plan" "main" {
  count               = var.enable_ddos_protection ? 1 : 0
  name                = "ddos-${local.prefix}-${local.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.common_tags
}

# Application Subnet
resource "azurerm_subnet" "app" {
  name                 = local.resource_names.subnet_app
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = local.subnet_config.app.address_prefixes
  service_endpoints    = local.subnet_config.app.service_endpoints

  # Delegate to App Service if using VNet integration
  dynamic "delegation" {
    for_each = var.enable_app_service_vnet_integration ? [1] : []
    content {
      name = "Microsoft.Web.serverFarms"
      service_delegation {
        name    = "Microsoft.Web/serverFarms"
        actions = ["Microsoft.Network/virtualNetworks/subnets/action"]
      }
    }
  }
}

# Data Subnet (for database and storage)
resource "azurerm_subnet" "data" {
  name                 = local.resource_names.subnet_data
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = local.subnet_config.data.address_prefixes
  service_endpoints    = local.subnet_config.data.service_endpoints
}

# AI/ML Subnet (for GPU VMs and ML services)
resource "azurerm_subnet" "ai" {
  name                 = local.resource_names.subnet_ai
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = local.subnet_config.ai.address_prefixes
  service_endpoints    = local.subnet_config.ai.service_endpoints
}

# Network Security Groups
resource "azurerm_network_security_group" "app" {
  name                = local.resource_names.nsg_app
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags

  # Allow HTTPS inbound
  security_rule {
    name                       = "HTTPS"
    priority                   = 1001
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  # Allow HTTP inbound (for health checks)
  security_rule {
    name                       = "HTTP"
    priority                   = 1002
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "80"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  # Allow application ports (8000-8010) from within VNet
  security_rule {
    name                       = "AppPorts"
    priority                   = 1003
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["8000-8010"]
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "*"
  }

  # Deny all other inbound traffic
  security_rule {
    name                       = "DenyAllInbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_network_security_group" "data" {
  name                = local.resource_names.nsg_data
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags

  # Allow PostgreSQL from app subnet only
  security_rule {
    name                       = "PostgreSQL"
    priority                   = 1001
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "5432"
    source_address_prefixes    = local.subnet_config.app.address_prefixes
    destination_address_prefix = "*"
  }

  # Allow Redis from app subnet only
  security_rule {
    name                       = "Redis"
    priority                   = 1002
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "6379"
    source_address_prefixes    = local.subnet_config.app.address_prefixes
    destination_address_prefix = "*"
  }

  # Deny all other inbound traffic
  security_rule {
    name                       = "DenyAllInbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_network_security_group" "ai" {
  name                = local.resource_names.nsg_ai
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags

  # Allow ML service ports from app subnet only
  security_rule {
    name                       = "MLServices"
    priority                   = 1001
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["8000-8010"]
    source_address_prefixes    = local.subnet_config.app.address_prefixes
    destination_address_prefix = "*"
  }

  # Allow SSH for management (from bastion only in production)
  security_rule {
    name                       = "SSH"
    priority                   = 1002
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.management_ip_range
    destination_address_prefix = "*"
  }

  # Deny all other inbound traffic
  security_rule {
    name                       = "DenyAllInbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

# Associate NSGs with subnets
resource "azurerm_subnet_network_security_group_association" "app" {
  subnet_id                 = azurerm_subnet.app.id
  network_security_group_id = azurerm_network_security_group.app.id
}

resource "azurerm_subnet_network_security_group_association" "data" {
  subnet_id                 = azurerm_subnet.data.id
  network_security_group_id = azurerm_network_security_group.data.id
}

resource "azurerm_subnet_network_security_group_association" "ai" {
  subnet_id                 = azurerm_subnet.ai.id
  network_security_group_id = azurerm_network_security_group.ai.id
}

# Private DNS Zones for private endpoints
resource "azurerm_private_dns_zone" "blob" {
  name                = "privatelink.blob.core.windows.net"
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags
}

resource "azurerm_private_dns_zone" "keyvault" {
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags
}

resource "azurerm_private_dns_zone" "postgresql" {
  name                = "privatelink.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags
}

# Link private DNS zones to VNet
resource "azurerm_private_dns_zone_virtual_network_link" "blob" {
  name                  = "blob-link"
  resource_group_name   = azurerm_resource_group.main.name
  private_dns_zone_name = azurerm_private_dns_zone.blob.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false
  tags                  = local.common_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "keyvault" {
  name                  = "kv-link"
  resource_group_name   = azurerm_resource_group.main.name
  private_dns_zone_name = azurerm_private_dns_zone.keyvault.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false
  tags                  = local.common_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgresql" {
  name                  = "psql-link"
  resource_group_name   = azurerm_resource_group.main.name
  private_dns_zone_name = azurerm_private_dns_zone.postgresql.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false
  tags                  = local.common_tags
}
