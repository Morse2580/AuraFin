# scripts/setup_environment.py

#!/usr/bin/env python3
"""
Environment setup script for CashAppAgent
Sets up local development environment or prepares for deployment
"""

import os
import sys
import json
import subprocess
import shutil
from pathlib import Path
from typing import Dict, Optional
import argparse

def run_command(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result"""
    print(f"🔧 Running: {cmd}")
    
    result = subprocess.run(
        cmd.split(),
        capture_output=True,
        text=True,
        check=False
    )
    
    if check and result.returncode != 0:
        print(f"❌ Command failed: {cmd}")
        print(f"   stderr: {result.stderr}")
        sys.exit(1)
    
    return result

def check_tool_installed(tool: str) -> bool:
    """Check if a tool is installed"""
    return shutil.which(tool) is not None

def create_config_file(environment: str, config_dir: Path) -> None:
    """Create environment configuration file"""
    config_file = config_dir / f"{environment}.json"
    
    if config_file.exists():
        print(f"✅ Configuration file already exists: {config_file}")
        return
    
    # Template configuration
    config_template = {
        "environment": environment,
        "resource_group": f"rg-cashappagent-{environment}",
        "location": "East US 2",
        "container_registry": f"crcashappagent{environment}001",
        "storage_account": f"sacashappagent{environment}001",
        "key_vault": f"kv-cashappagent-{environment}-001",
        "postgresql": {
            "server_name": f"psql-cashappagent-{environment}-001",
            "database_name": "cashappagent"
        },
        "app_services": {
            "cle": f"app-cashappagent-cle-{environment}",
            "eic": f"app-cashappagent-eic-{environment}",
            "cm": f"app-cashappagent-cm-{environment}"
        },
        "aks": {
            "cluster_name": f"aks-cashappagent-{environment}",
            "node_count": 2 if environment == "production" else 1
        }
    }
    
    config_dir.mkdir(parents=True, exist_ok=True)
    
    with open(config_file, 'w') as f:
        json.dump(config_template, f, indent=2)
    
    print(f"✅ Created configuration file: {config_file}")
    print("📝 Please review and customize the configuration as needed")

def setup_terraform_backend(environment: str) -> None:
    """Setup Terraform backend configuration"""
    backend_file = Path("terraform") / "backend.tf"
    
    backend_config = f'''# Backend configuration for {environment}
terraform {{
  backend "azurerm" {{
    resource_group_name  = "rg-terraform-state"
    storage_account_name = "saterraformstate001"
    container_name       = "tfstate"
    key                  = "cashappagent-{environment}.tfstate"
  }}
}}
'''
    
    with open(backend_file, 'w') as f:
        f.write(backend_config)
    
    print(f"✅ Created Terraform backend configuration: {backend_file}")

def create_terraform_tfvars(environment: str) -> None:
    """Create Terraform variables file"""
    tfvars_dir = Path("terraform") / "environments"
    tfvars_file = tfvars_dir / f"{environment}.tfvars"
    
    if tfvars_file.exists():
        print(f"✅ Terraform variables file already exists: {tfvars_file}")
        return
    
    tfvars_template = f'''# Terraform variables for {environment}

# Basic configuration
environment      = "{environment}"
location        = "East US 2"
business_owner  = "finance-team@company.com"
technical_owner = "devops-team@company.com"

# Network configuration
vnet_address_space = ["10.{1 if environment == 'dev' else 2 if environment == 'staging' else 0}.0.0/16"]
enable_ddos_protection = {str(environment == "production").lower()}

# Database configuration
postgresql_sku_name = "{"GP_Standard_D4s_v3" if environment == "production" else "GP_Standard_D2s_v3"}"
postgresql_storage_mb = {65536 if environment == "production" else 32768}
postgresql_backup_retention_days = {30 if environment == "production" else 7}
postgresql_ha_enabled = {str(environment == "production").lower()}

# Storage configuration
storage_replication_type = "{"GRS" if environment == "production" else "LRS"}"
blob_soft_delete_days = {30 if environment == "production" else 7}

# App Service configuration
app_service_sku_name = "{"P2v3" if environment == "production" else "P1v3"}"

# Kubernetes configuration
aks_system_node_count = {3 if environment == "production" else 2}
aks_gpu_node_count = {2 if environment == "production" else 1}
aks_gpu_vm_size = "Standard_NC6s_v3"

# Monitoring configuration
log_analytics_retention_days = {90 if environment == "production" else 30}
ops_team_email = "ops-team@company.com"

# Additional tags
tags = {{
  Environment = "{environment}"
  Project     = "CashAppAgent"
  CostCenter  = "IT"
}}
'''
    
    tfvars_dir.mkdir(parents=True, exist_ok=True)
    
    with open(tfvars_file, 'w') as f:
        f.write(tfvars_template)
    
    print(f"✅ Created Terraform variables file: {tfvars_file}")
    print("📝 Please review and customize the variables as needed")

def setup_local_development() -> None:
    """Setup local development environment"""
    print("🏠 Setting up local development environment...")
    
    # Create .env file for local development
    env_file = Path(".env")
    
    if not env_file.exists():
        env_template = """# Local development environment variables

# Database
DATABASE_URL=postgresql://cashappuser:cashapppass@localhost:5432/cashappagent
REDIS_URL=redis://localhost:6379

# Azure (for local testing - use dev environment)
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=devstorageaccount;AccountKey=...
AZURE_KEY_VAULT_URL=https://kv-cashappagent-dev-001.vault.azure.net/
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-client-id
AZURE_CLIENT_SECRET=your-client-secret

# Service Configuration
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=DEBUG

# Communication Module
SLACK_BOT_TOKEN=xoxb-your-slack-bot-token
SLACK_DEFAULT_CHANNEL=#cashapp-alerts

# ERP Systems (for testing)
NETSUITE_ACCOUNT_ID=your-account
NETSUITE_CONSUMER_KEY=your-key
NETSUITE_CONSUMER_SECRET=your-secret
NETSUITE_TOKEN_ID=your-token
NETSUITE_TOKEN_SECRET=your-token-secret
"""
        
        with open(env_file, 'w') as f:
            f.write(env_template)
        
        print(f"✅ Created environment file: {env_file}")
        print("📝 Please fill in the actual values in the .env file")
    
    # Set up Python virtual environment
    venv_dir = Path("venv")
    
    if not venv_dir.exists():
        print("🐍 Creating Python virtual environment...")
        run_command(f"{sys.executable} -m venv venv")
        
        # Install dependencies
        pip_cmd = "venv/bin/pip" if sys.platform != "win32" else "venv\\Scripts\\pip.exe"
        
        requirements_files = [
            "shared/requirements.txt",
            "services/cle/requirements.txt",
            "services/dim/requirements.txt",
            "services/eic/requirements.txt",
            "services/cm/requirements.txt"
        ]
        
        for req_file in requirements_files:
            if Path(req_file).exists():
                run_command(f"{pip_cmd} install -r {req_file}")
        
        print("✅ Virtual environment created and dependencies installed")
    else:
        print("✅ Virtual environment already exists")

def main():
    parser = argparse.ArgumentParser(description="Setup CashAppAgent environment")
    parser.add_argument('--environment', '-e', choices=['dev', 'staging', 'production'],
                       default='dev', help='Target environment')
    parser.add_argument('--local', action='store_true',
                       help='Setup local development environment')
    parser.add_argument('--terraform-only', action='store_true',
                       help='Setup Terraform configuration only')
    
    args = parser.parse_args()
    
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    print(f"🚀 Setting up CashAppAgent environment: {args.environment}")
    
    # Check prerequisites
    required_tools = ['python', 'git']
    if not args.local:
        required_tools.extend(['az', 'terraform', 'kubectl', 'docker'])
    
    missing_tools = [tool for tool in required_tools if not check_tool_installed(tool)]
    
    if missing_tools:
        print(f"❌ Missing required tools: {', '.join(missing_tools)}")
        print("Please install the missing tools and try again.")
        sys.exit(1)
    
    try:
        # Create directories
        directories = ['config', 'logs', 'terraform/environments']
        for directory in directories:
            Path(directory).mkdir(parents=True, exist_ok=True)
        
        if args.local or args.environment == 'dev':
            setup_local_development()
        
        if not args.local:
            # Create configuration files
            create_config_file(args.environment, Path("config"))
            setup_terraform_backend(args.environment)
            create_terraform_tfvars(args.environment)
        
        print("\n🎉 Environment setup completed successfully!")
        print("\n📋 Next steps:")
        
        if args.local:
            print("1. Fill in the actual values in .env file")
            print("2. Start local services: make dev-up")
            print("3. Run tests: make test")
        else:
            print(f"1. Review and customize config/{args.environment}.json")
            print(f"2. Review and customize terraform/environments/{args.environment}.tfvars")
            print("3. Set up Azure credentials: az login")
            print(f"4. Deploy infrastructure: python scripts/deploy.py {args.environment}")
        
    except Exception as e:
        print(f"❌ Setup failed: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main()
