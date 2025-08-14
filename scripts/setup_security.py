#!/usr/bin/env python3
# scripts/setup_security.py
"""
Security setup script for CashAppAgent
Creates initial API keys and security configuration
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import ConfigurationManager
from shared.security import APIKeyManager, create_service_api_key
import redis.asyncio as redis
import json

async def setup_security():
    """Setup initial security configuration"""
    print("🔐 Setting up CashAppAgent security...")
    
    # Load configuration
    config = ConfigurationManager()
    
    # Connect to Redis
    redis_url = config.get('REDIS_URL', 'redis://localhost:6379')
    redis_client = redis.from_url(redis_url)
    
    try:
        # Test Redis connection
        await redis_client.ping()
        print("✅ Redis connection successful")
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        return False
    
    # Initialize API key manager
    api_key_manager = APIKeyManager(config, redis_client)
    
    # Create service-to-service API keys
    service_keys = []
    
    services = [
        ('cle', 'core-logic-engine', ['read', 'write', 'process_transactions']),
        ('dim', 'document-intelligence', ['read', 'write', 'process_documents']),
        ('eic', 'erp-integration', ['read', 'write', 'erp_operations']),
        ('cm', 'communication-module', ['read', 'write', 'send_notifications'])
    ]
    
    print("\n📋 Creating service API keys...")
    
    for service_code, service_name, permissions in services:
        try:
            key_info = await api_key_manager.generate_api_key(
                client_id='internal',
                service_name=service_name,
                permissions=permissions,
                expires_in_days=365
            )
            
            service_keys.append({
                'service': service_code,
                'key_id': key_info['key_id'],
                'api_key': key_info['api_key'],
                'permissions': permissions
            })
            
            print(f"✅ Created API key for {service_name}: {key_info['key_id']}")
            
        except Exception as e:
            print(f"❌ Failed to create API key for {service_name}: {e}")
    
    # Create client API keys for testing
    print("\n🧪 Creating test client API keys...")
    
    test_clients = [
        ('test-client-1', 'Test Client 1', ['read', 'process_transactions']),
        ('test-client-2', 'Test Client 2', ['read', 'write', 'process_transactions']),
        ('admin-client', 'Admin Client', ['admin'])
    ]
    
    client_keys = []
    
    for client_id, client_name, permissions in test_clients:
        try:
            key_info = await api_key_manager.generate_api_key(
                client_id=client_id,
                service_name='api-client',
                permissions=permissions,
                expires_in_days=90  # Shorter expiry for client keys
            )
            
            client_keys.append({
                'client_id': client_id,
                'client_name': client_name,
                'key_id': key_info['key_id'],
                'api_key': key_info['api_key'],
                'permissions': permissions
            })
            
            print(f"✅ Created API key for {client_name}: {key_info['key_id']}")
            
        except Exception as e:
            print(f"❌ Failed to create API key for {client_name}: {e}")
    
    # Save keys to secure file
    security_config = {
        'service_keys': service_keys,
        'client_keys': client_keys,
        'setup_timestamp': redis_client and await redis_client.time() or None
    }
    
    # Write to secure location
    keys_file = '/app/config/api_keys.json'
    os.makedirs(os.path.dirname(keys_file), exist_ok=True)
    
    with open(keys_file, 'w') as f:
        json.dump(security_config, f, indent=2)
    
    # Set secure permissions
    os.chmod(keys_file, 0o600)
    
    print(f"\n💾 API keys saved to: {keys_file}")
    print("⚠️  IMPORTANT: Store these keys securely and remove the file after distributing keys")
    
    # Display summary
    print(f"\n📊 Security Setup Summary:")
    print(f"   Service keys created: {len(service_keys)}")
    print(f"   Client keys created: {len(client_keys)}")
    print(f"   Total API keys: {len(service_keys) + len(client_keys)}")
    
    # Test key validation
    print("\n🧪 Testing API key validation...")
    
    if service_keys:
        test_key = service_keys[0]['api_key']
        validation_result = await api_key_manager.validate_api_key(test_key)
        
        if validation_result:
            print(f"✅ API key validation test passed")
        else:
            print(f"❌ API key validation test failed")
    
    await redis_client.close()
    
    print("\n🎉 Security setup completed successfully!")
    return True

async def reset_security():
    """Reset all security configuration"""
    print("🔄 Resetting security configuration...")
    
    config = ConfigurationManager()
    redis_url = config.get('REDIS_URL', 'redis://localhost:6379')
    redis_client = redis.from_url(redis_url)
    
    try:
        # Clear all API keys
        async for key in redis_client.scan_iter(match="api_keys:*"):
            await redis_client.delete(key)
        
        async for key in redis_client.scan_iter(match="key_hash:*"):
            await redis_client.delete(key)
        
        # Clear rate limiting data
        async for key in redis_client.scan_iter(match="rate_limit:*"):
            await redis_client.delete(key)
        
        async for key in redis_client.scan_iter(match="burst_limit:*"):
            await redis_client.delete(key)
        
        print("✅ Security configuration reset successfully")
        
    except Exception as e:
        print(f"❌ Failed to reset security configuration: {e}")
    
    finally:
        await redis_client.close()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='CashAppAgent Security Setup')
    parser.add_argument('action', choices=['setup', 'reset'], help='Action to perform')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    
    if args.action == 'setup':
        success = asyncio.run(setup_security())
        sys.exit(0 if success else 1)
    elif args.action == 'reset':
        asyncio.run(reset_security())
        sys.exit(0)