#!/usr/bin/env python3
"""
ERP Connection Setup Tool
Helps you configure and test connection to your real ERP system
"""
import json
import requests
import getpass
import sys
from pathlib import Path

def load_erp_config():
    """Load ERP configuration"""
    config_path = Path("config/erp-config.json")
    if config_path.exists():
        with open(config_path, 'r') as f:
            return json.load(f)
    return {}

def save_erp_config(config):
    """Save ERP configuration"""
    config_path = Path("config/erp-config.json")
    config_path.parent.mkdir(exist_ok=True)
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

def test_connection(erp_type, config):
    """Test connection to ERP system"""
    print(f"\n🔍 Testing {erp_type.upper()} connection...")
    
    try:
        if erp_type == "sap":
            return test_sap_connection(config)
        elif erp_type == "netsuite":
            return test_netsuite_connection(config)
        elif erp_type == "oracle":
            return test_oracle_connection(config)
        elif erp_type == "dynamics":
            return test_dynamics_connection(config)
        elif erp_type == "quickbooks":
            return test_quickbooks_connection(config)
        elif erp_type == "custom":
            return test_custom_connection(config)
        else:
            print(f"❌ Unsupported ERP type: {erp_type}")
            return False
            
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

def test_sap_connection(config):
    """Test SAP OData connection"""
    url = f"{config['base_url']}{config['service_name']}{config['test_endpoint']}"
    
    auth = (config['username'], config['password'])
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    
    response = requests.get(url, auth=auth, headers=headers, timeout=config['timeout'])
    
    if response.status_code == 200:
        print("✅ SAP connection successful!")
        data = response.json()
        if 'd' in data and 'results' in data['d']:
            print(f"📊 Found {len(data['d']['results'])} records")
        return True
    else:
        print(f"❌ SAP connection failed: {response.status_code} - {response.text}")
        return False

def test_netsuite_connection(config):
    """Test NetSuite REST connection"""
    # NetSuite uses OAuth 1.0 - this is simplified for demo
    print("⚠️  NetSuite requires OAuth 1.0 setup - contact admin for full integration")
    return False

def test_oracle_connection(config):
    """Test Oracle Cloud connection"""
    url = f"{config['base_url']}{config['test_endpoint']}"
    
    auth = (config['username'], config['password'])
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    
    response = requests.get(url, auth=auth, headers=headers, timeout=config['timeout'])
    
    if response.status_code == 200:
        print("✅ Oracle connection successful!")
        return True
    else:
        print(f"❌ Oracle connection failed: {response.status_code}")
        return False

def test_dynamics_connection(config):
    """Test Dynamics 365 connection"""
    print("⚠️  Dynamics 365 requires Azure AD OAuth - contact admin for setup")
    return False

def test_quickbooks_connection(config):
    """Test QuickBooks connection"""
    print("⚠️  QuickBooks requires OAuth 2.0 setup - contact admin for integration")
    return False

def test_custom_connection(config):
    """Test custom REST API connection"""
    url = f"{config['base_url']}{config['test_endpoint']}"
    
    headers = {'Accept': 'application/json'}
    
    auth_type = config['authentication']['type']
    if auth_type == 'bearer':
        headers['Authorization'] = f"Bearer {config['authentication']['token']}"
    elif auth_type == 'api_key':
        key_header = config['authentication']['api_key_header']
        headers[key_header] = config['authentication']['token']
    elif auth_type == 'basic':
        auth = (config['authentication']['username'], config['authentication']['password'])
        response = requests.get(url, auth=auth, headers=headers, timeout=config['timeout'])
    else:
        response = requests.get(url, headers=headers, timeout=config['timeout'])
    
    if 'auth' not in locals():
        response = requests.get(url, headers=headers, timeout=config['timeout'])
    
    if response.status_code == 200:
        print("✅ Custom API connection successful!")
        return True
    else:
        print(f"❌ Custom API connection failed: {response.status_code}")
        return False

def setup_sap():
    """Interactive SAP setup"""
    print("\n🔧 SAP Configuration Setup")
    print("=" * 40)
    
    config = {
        "enabled": True,
        "connection_type": "odata",
        "read_only": True,
        "timeout": 30
    }
    
    config["base_url"] = input("SAP Server URL (e.g., https://sap.company.com:8000/sap/opu/odata/sap/): ").strip()
    config["service_name"] = input("Service Name (default: API_PURCHASE_ORDER_PROCESS_SRV): ").strip() or "API_PURCHASE_ORDER_PROCESS_SRV"
    config["username"] = input("Username: ").strip()
    config["password"] = getpass.getpass("Password: ")
    config["client"] = input("Client (default: 100): ").strip() or "100"
    config["language"] = input("Language (default: EN): ").strip() or "EN"
    config["test_endpoint"] = input("Test endpoint (default: /PurchaseOrder?$top=1): ").strip() or "/PurchaseOrder?$top=1"
    
    return config

def setup_custom():
    """Interactive custom API setup"""
    print("\n🔧 Custom API Configuration Setup")
    print("=" * 40)
    
    config = {
        "enabled": True,
        "connection_type": "rest",
        "read_only": True,
        "timeout": 30,
        "authentication": {}
    }
    
    config["base_url"] = input("API Base URL: ").strip()
    config["test_endpoint"] = input("Test endpoint (e.g., /invoices?limit=1): ").strip()
    
    print("\nAuthentication type:")
    print("1. Bearer Token")
    print("2. API Key")
    print("3. Basic Auth")
    print("4. None")
    
    auth_choice = input("Choose (1-4): ").strip()
    
    if auth_choice == "1":
        config["authentication"]["type"] = "bearer"
        config["authentication"]["token"] = getpass.getpass("Bearer Token: ")
    elif auth_choice == "2":
        config["authentication"]["type"] = "api_key"
        config["authentication"]["api_key_header"] = input("API Key Header (default: X-API-Key): ").strip() or "X-API-Key"
        config["authentication"]["token"] = getpass.getpass("API Key: ")
    elif auth_choice == "3":
        config["authentication"]["type"] = "basic"
        config["authentication"]["username"] = input("Username: ").strip()
        config["authentication"]["password"] = getpass.getpass("Password: ")
    else:
        config["authentication"]["type"] = "none"
    
    return config

def main():
    """Main setup flow"""
    print("🔧 CashUp Agent - ERP Connection Setup")
    print("=" * 50)
    
    print("Which ERP system do you want to connect to?")
    print("1. SAP")
    print("2. NetSuite") 
    print("3. Oracle ERP Cloud")
    print("4. Microsoft Dynamics 365")
    print("5. QuickBooks")
    print("6. Custom REST API")
    print("7. Test existing connection")
    
    choice = input("\nEnter choice (1-7): ").strip()
    
    erp_config = load_erp_config()
    
    if choice == "1":
        config = setup_sap()
        erp_config["erp_systems"]["sap"] = config
        erp_config["default_system"] = "sap"
        save_erp_config(erp_config)
        
        if test_connection("sap", config):
            print("\n🎉 SAP connection configured successfully!")
        
    elif choice == "6":
        config = setup_custom()
        erp_config["erp_systems"]["custom"] = config
        erp_config["default_system"] = "custom"
        save_erp_config(erp_config)
        
        if test_connection("custom", config):
            print("\n🎉 Custom API connection configured successfully!")
            
    elif choice == "7":
        # Test existing connections
        for erp_type, config in erp_config.get("erp_systems", {}).items():
            if config.get("enabled", False):
                test_connection(erp_type, config)
                
    else:
        print(f"\n⚠️  {['', 'SAP', 'NetSuite', 'Oracle', 'Dynamics', 'QuickBooks'][int(choice) if choice.isdigit() and 1 <= int(choice) <= 5 else 0]} setup requires additional OAuth configuration.")
        print("Please contact your ERP administrator for connection details.")
        print("For now, you can test with the Custom REST API option.")

if __name__ == "__main__":
    main()