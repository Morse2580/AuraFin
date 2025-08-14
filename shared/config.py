# shared/config.py
"""
Environment configuration management for CashAppAgent
Integrates with Azure Key Vault and App Configuration
"""

import os
import json
import asyncio
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from azure.keyvault.secrets import SecretClient
from azure.appconfiguration import AzureAppConfigurationClient
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import AzureError

from .logging import setup_logging
from .exception import CashAppException

logger = setup_logging("config")

@dataclass
class DatabaseConfig:
    """Database configuration"""
    host: str = "localhost"
    port: int = 5432
    database: str = "cashapp"
    username: str = "cashapp_user"
    password: str = "password"
    pool_size: int = 20
    max_overflow: int = 10
    timeout: int = 30
    
    @property
    def connection_string(self) -> str:
        return f"postgresql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"

@dataclass
class AzureConfig:
    """Azure services configuration"""
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    key_vault_url: str = ""
    storage_connection_string: str = ""
    service_bus_connection_string: str = ""
    application_insights_key: str = ""
    form_recognizer_endpoint: str = ""
    form_recognizer_key: str = ""

@dataclass
class ERPConfig:
    """ERP systems configuration"""
    netsuite_endpoint: str = ""
    netsuite_token_key: str = ""
    netsuite_token_secret: str = ""
    sap_endpoint: str = ""
    sap_username: str = ""
    sap_password: str = ""
    quickbooks_app_id: str = ""
    quickbooks_app_secret: str = ""
    default_timeout: int = 30
    max_retries: int = 3
    retry_backoff: float = 1.0

@dataclass
class CommunicationConfig:
    """Communication services configuration"""
    smtp_server: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    slack_bot_token: str = ""
    slack_channel: str = "#cashapp-alerts"
    templates_dir: str = "./templates"
    from_email: str = "noreply@cashapp.com"

@dataclass
class BusinessRulesConfig:
    """Business rules and thresholds"""
    min_match_confidence: float = 0.8
    auto_apply_threshold: float = 10000.0
    max_processing_time: int = 300
    max_concurrent_transactions: int = 10
    human_review_threshold: float = 1000.0

@dataclass
class CashAppConfig:
    """Complete CashAppAgent configuration"""
    environment: str = "development"
    debug: bool = False
    service_name: str = "cashapp"
    version: str = "1.0.0"
    
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    azure: AzureConfig = field(default_factory=AzureConfig)
    erp: ERPConfig = field(default_factory=ERPConfig)
    communication: CommunicationConfig = field(default_factory=CommunicationConfig)
    business_rules: BusinessRulesConfig = field(default_factory=BusinessRulesConfig)
    
    # Runtime configuration
    api_keys: Dict[str, str] = field(default_factory=dict)
    feature_flags: Dict[str, bool] = field(default_factory=dict)
    client_configs: Dict[str, Dict] = field(default_factory=dict)

class ConfigurationManager:
    """
    Manages application configuration from multiple sources
    Priority: Environment Variables > Azure Key Vault > App Configuration > Defaults
    """
    
    def __init__(self, 
                 key_vault_url: str = None,
                 app_config_endpoint: str = None,
                 environment: str = None):
        self.environment = environment or os.getenv('ENVIRONMENT', 'development')
        self.key_vault_url = key_vault_url or os.getenv('AZURE_KEY_VAULT_URL')
        self.app_config_endpoint = app_config_endpoint or os.getenv('AZURE_APP_CONFIG_ENDPOINT')
        
        self._credential = DefaultAzureCredential()
        self._secret_client = None
        self._app_config_client = None
        self._config_cache = {}
        self._cache_expiry = 0
        
        logger.info(f"Configuration manager initialized for environment: {self.environment}")
    
    async def initialize(self):
        """Initialize Azure clients"""
        try:
            # Initialize Key Vault client
            if self.key_vault_url:
                self._secret_client = SecretClient(
                    vault_url=self.key_vault_url,
                    credential=self._credential
                )
                logger.info("Key Vault client initialized")
            
            # Initialize App Configuration client
            if self.app_config_endpoint:
                self._app_config_client = AzureAppConfigurationClient(
                    base_url=self.app_config_endpoint,
                    credential=self._credential
                )
                logger.info("App Configuration client initialized")
                
        except AzureError as e:
            logger.error(f"Failed to initialize Azure clients: {e}")
            # Don't raise - allow fallback to environment variables
    
    async def load_config(self, service_name: str = None) -> CashAppConfig:
        """
        Load complete configuration for service
        
        Args:
            service_name: Specific service name for targeted config
            
        Returns:
            Complete configuration object
        """
        try:
            # Start with defaults
            config = CashAppConfig()
            config.service_name = service_name or "cashapp"
            config.environment = self.environment
            
            # Load from multiple sources
            await self._load_from_environment(config)
            await self._load_from_key_vault(config)
            await self._load_from_app_config(config, service_name)
            
            # Validate configuration
            self._validate_config(config)
            
            logger.info(f"Configuration loaded successfully for {config.service_name}")
            return config
            
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            raise CashAppException(f"Configuration loading failed: {e}", "CONFIG_ERROR")
    
    async def _load_from_environment(self, config: CashAppConfig):
        """Load configuration from environment variables"""
        # Database configuration
        config.database.host = os.getenv('DB_HOST', config.database.host)
        config.database.port = int(os.getenv('DB_PORT', str(config.database.port)))
        config.database.database = os.getenv('DB_NAME', config.database.database)
        config.database.username = os.getenv('DB_USER', config.database.username)
        config.database.password = os.getenv('DB_PASSWORD', config.database.password)
        
        # Azure configuration
        config.azure.tenant_id = os.getenv('AZURE_TENANT_ID', config.azure.tenant_id)
        config.azure.client_id = os.getenv('AZURE_CLIENT_ID', config.azure.client_id)
        config.azure.client_secret = os.getenv('AZURE_CLIENT_SECRET', config.azure.client_secret)
        config.azure.key_vault_url = os.getenv('AZURE_KEY_VAULT_URL', config.azure.key_vault_url)
        config.azure.storage_connection_string = os.getenv('AZURE_STORAGE_CONNECTION_STRING', config.azure.storage_connection_string)
        
        # Business rules
        config.business_rules.min_match_confidence = float(os.getenv('MIN_MATCH_CONFIDENCE', str(config.business_rules.min_match_confidence)))
        config.business_rules.auto_apply_threshold = float(os.getenv('AUTO_APPLY_THRESHOLD', str(config.business_rules.auto_apply_threshold)))
        
        # Feature flags
        config.feature_flags = {
            'enable_ml_models': os.getenv('ENABLE_ML_MODELS', 'true').lower() == 'true',
            'enable_azure_form_recognizer': os.getenv('ENABLE_FORM_RECOGNIZER', 'true').lower() == 'true',
            'enable_slack_notifications': os.getenv('ENABLE_SLACK', 'false').lower() == 'true',
            'enable_multi_erp': os.getenv('ENABLE_MULTI_ERP', 'true').lower() == 'true'
        }
        
        logger.debug("Environment configuration loaded")
    
    async def _load_from_key_vault(self, config: CashAppConfig):
        """Load secrets from Azure Key Vault"""
        if not self._secret_client:
            logger.debug("Key Vault client not available, skipping secret loading")
            return
        
        try:
            # Define secrets to load
            secret_mappings = {
                'database-password': ('database', 'password'),
                'azure-client-secret': ('azure', 'client_secret'),
                'storage-connection-string': ('azure', 'storage_connection_string'),
                'service-bus-connection-string': ('azure', 'service_bus_connection_string'),
                'application-insights-key': ('azure', 'application_insights_key'),
                'form-recognizer-key': ('azure', 'form_recognizer_key'),
                'netsuite-token-key': ('erp', 'netsuite_token_key'),
                'netsuite-token-secret': ('erp', 'netsuite_token_secret'),
                'sap-password': ('erp', 'sap_password'),
                'slack-bot-token': ('communication', 'slack_bot_token'),
                'smtp-password': ('communication', 'smtp_password')
            }
            
            for secret_name, (section, attr) in secret_mappings.items():
                try:
                    secret = self._secret_client.get_secret(f"{self.environment}-{secret_name}")
                    section_config = getattr(config, section)
                    setattr(section_config, attr, secret.value)
                    logger.debug(f"Loaded secret: {secret_name}")
                    
                except Exception as e:
                    logger.warning(f"Failed to load secret {secret_name}: {e}")
                    # Continue with other secrets
            
            logger.info("Key Vault secrets loaded")
            
        except Exception as e:
            logger.warning(f"Key Vault loading failed: {e}")
    
    async def _load_from_app_config(self, config: CashAppConfig, service_name: str = None):
        """Load configuration from Azure App Configuration"""
        if not self._app_config_client:
            logger.debug("App Configuration client not available")
            return
        
        try:
            # Define configuration keys to load
            config_keys = [
                f"{self.environment}:BusinessRules:MinMatchConfidence",
                f"{self.environment}:BusinessRules:AutoApplyThreshold",
                f"{self.environment}:BusinessRules:MaxProcessingTime",
                f"{self.environment}:Database:PoolSize",
                f"{self.environment}:ERP:DefaultTimeout",
                f"{self.environment}:ERP:MaxRetries"
            ]
            
            # Add service-specific configs
            if service_name:
                config_keys.extend([
                    f"{self.environment}:{service_name}:FeatureFlags",
                    f"{self.environment}:{service_name}:BusinessRules"
                ])
            
            # Fetch configurations
            for key in config_keys:
                try:
                    config_setting = self._app_config_client.get_configuration_setting(key)
                    self._apply_config_value(config, key, config_setting.value)
                    
                except Exception as e:
                    logger.debug(f"Config key {key} not found: {e}")
            
            logger.info("App Configuration loaded")
            
        except Exception as e:
            logger.warning(f"App Configuration loading failed: {e}")
    
    def _apply_config_value(self, config: CashAppConfig, key: str, value: str):
        """Apply configuration value to config object"""
        try:
            # Parse the key to determine where to apply the value
            parts = key.split(':')
            if len(parts) < 3:
                return
            
            env, section, setting = parts[1], parts[2], parts[3] if len(parts) > 3 else parts[2]
            
            # Apply based on section
            if section == "BusinessRules":
                if setting == "MinMatchConfidence":
                    config.business_rules.min_match_confidence = float(value)
                elif setting == "AutoApplyThreshold":
                    config.business_rules.auto_apply_threshold = float(value)
                elif setting == "MaxProcessingTime":
                    config.business_rules.max_processing_time = int(value)
            
            elif section == "Database":
                if setting == "PoolSize":
                    config.database.pool_size = int(value)
            
            elif section == "ERP":
                if setting == "DefaultTimeout":
                    config.erp.default_timeout = int(value)
                elif setting == "MaxRetries":
                    config.erp.max_retries = int(value)
            
            # Handle feature flags (JSON format)
            elif "FeatureFlags" in key:
                try:
                    flags = json.loads(value)
                    config.feature_flags.update(flags)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in feature flags: {value}")
            
        except Exception as e:
            logger.warning(f"Failed to apply config value {key}: {e}")
    
    def _validate_config(self, config: CashAppConfig):
        """Validate configuration completeness"""
        required_fields = []
        
        # Check critical database config
        if not config.database.host:
            required_fields.append("database.host")
        if not config.database.password and self.environment != 'development':
            required_fields.append("database.password")
        
        # Check Azure config for production
        if self.environment in ['production', 'staging']:
            if not config.azure.tenant_id:
                required_fields.append("azure.tenant_id")
            if not config.azure.client_id:
                required_fields.append("azure.client_id")
        
        if required_fields:
            raise CashAppException(
                f"Missing required configuration: {', '.join(required_fields)}", 
                "CONFIG_VALIDATION_ERROR"
            )
        
        logger.info("Configuration validation passed")
    
    async def update_runtime_config(self, key: str, value: Any, ttl_seconds: int = 3600):
        """
        Update runtime configuration with TTL
        
        Args:
            key: Configuration key
            value: Configuration value
            ttl_seconds: Time to live for the setting
        """
        try:
            if self._app_config_client:
                from azure.appconfiguration import ConfigurationSetting
                
                setting = ConfigurationSetting(
                    key=f"{self.environment}:Runtime:{key}",
                    value=json.dumps(value) if not isinstance(value, str) else value
                )
                
                self._app_config_client.set_configuration_setting(setting)
                logger.info(f"Runtime config updated: {key}")
            else:
                # Fallback to local cache
                self._config_cache[key] = {
                    'value': value,
                    'expires_at': time.time() + ttl_seconds
                }
                
        except Exception as e:
            logger.error(f"Failed to update runtime config: {e}")
    
    async def get_client_config(self, client_id: str) -> Dict[str, Any]:
        """
        Get client-specific configuration
        
        Args:
            client_id: Client identifier
            
        Returns:
            Client configuration dictionary
        """
        try:
            if self._app_config_client:
                key = f"{self.environment}:Clients:{client_id}"
                setting = self._app_config_client.get_configuration_setting(key)
                return json.loads(setting.value)
            else:
                # Fallback to environment variable
                config_str = os.getenv(f'CLIENT_CONFIG_{client_id.upper()}', '{}')
                return json.loads(config_str)
                
        except Exception as e:
            logger.warning(f"Failed to load client config for {client_id}: {e}")
            return {}

class EnvironmentManager:
    """Manages environment-specific configurations and deployments"""
    
    def __init__(self, config_manager: ConfigurationManager):
        self.config_manager = config_manager
        self.current_environment = config_manager.environment
    
    def get_service_urls(self) -> Dict[str, str]:
        """Get environment-specific service URLs"""
        base_urls = {
            'development': {
                'cle': 'http://localhost:8000',
                'dim': 'http://localhost:8001',
                'eic': 'http://localhost:8002',
                'cm': 'http://localhost:8003'
            },
            'staging': {
                'cle': 'https://cle-staging.cashapp.internal',
                'dim': 'https://dim-staging.cashapp.internal',
                'eic': 'https://eic-staging.cashapp.internal',
                'cm': 'https://cm-staging.cashapp.internal'
            },
            'production': {
                'cle': 'https://cle.cashapp.internal',
                'dim': 'https://dim.cashapp.internal',
                'eic': 'https://eic.cashapp.internal',
                'cm': 'https://cm.cashapp.internal'
            }
        }
        
        return base_urls.get(self.current_environment, base_urls['development'])
    
    def get_deployment_config(self) -> Dict[str, Any]:
        """Get deployment-specific configuration"""
        return {
            'replicas': {
                'development': 1,
                'staging': 2,
                'production': 3
            }.get(self.current_environment, 1),
            'resources': {
                'development': {'cpu': '0.5', 'memory': '1Gi'},
                'staging': {'cpu': '1', 'memory': '2Gi'},
                'production': {'cpu': '2', 'memory': '4Gi'}
            }.get(self.current_environment, {'cpu': '0.5', 'memory': '1Gi'}),
            'autoscaling': {
                'development': False,
                'staging': True,
                'production': True
            }.get(self.current_environment, False)
        }

# Global configuration instances
_config_manager = None
_environment_manager = None
_current_config = None

async def initialize_config(service_name: str = None) -> CashAppConfig:
    """
    Initialize global configuration for service
    
    Args:
        service_name: Name of the service requesting config
        
    Returns:
        Loaded configuration
    """
    global _config_manager, _environment_manager, _current_config
    
    if not _config_manager:
        _config_manager = ConfigurationManager()
        await _config_manager.initialize()
        _environment_manager = EnvironmentManager(_config_manager)
    
    if not _current_config:
        _current_config = await _config_manager.load_config(service_name)
    
    return _current_config

async def get_config() -> CashAppConfig:
    """
    Get current configuration
    
    Returns:
        Current configuration instance
    """
    if not _current_config:
        return await initialize_config()
    return _current_config

async def get_service_urls() -> Dict[str, str]:
    """Get service URLs for current environment"""
    if not _environment_manager:
        await initialize_config()
    return _environment_manager.get_service_urls()

async def update_client_config(client_id: str, config_updates: Dict[str, Any]):
    """
    Update client-specific configuration
    
    Args:
        client_id: Client identifier
        config_updates: Configuration updates to apply
    """
    if not _config_manager:
        await initialize_config()
    
    # Get existing config
    existing_config = await _config_manager.get_client_config(client_id)
    
    # Merge updates
    existing_config.update(config_updates)
    
    # Update in App Configuration
    await _config_manager.update_runtime_config(f"Clients:{client_id}", existing_config)
    
    logger.info(f"Client configuration updated for: {client_id}")

def get_feature_flag(flag_name: str, default: bool = False) -> bool:
    """
    Get feature flag value
    
    Args:
        flag_name: Name of feature flag
        default: Default value if flag not found
        
    Returns:
        Feature flag value
    """
    if _current_config:
        return _current_config.feature_flags.get(flag_name, default)
    return default

# Configuration health check
async def config_health_check() -> Dict[str, Any]:
    """
    Check configuration system health
    
    Returns:
        Health status of configuration components
    """
    try:
        health_status = {
            "status": "healthy",
            "components": {
                "config_manager": "not_initialized",
                "key_vault": "not_configured",
                "app_config": "not_configured",
                "current_config": "not_loaded"
            }
        }
        
        if _config_manager:
            health_status["components"]["config_manager"] = "initialized"
            
            # Test Key Vault connectivity
            if _config_manager._secret_client:
                try:
                    # Try to list secrets (minimal permission test)
                    secrets = list(_config_manager._secret_client.list_properties_of_secrets(max_page_size=1))
                    health_status["components"]["key_vault"] = "connected"
                except Exception as e:
                    health_status["components"]["key_vault"] = f"error: {str(e)}"
            
            # Test App Configuration connectivity
            if _config_manager._app_config_client:
                try:
                    # Try to list configuration settings
                    settings = list(_config_manager._app_config_client.list_configuration_settings(max_page_size=1))
                    health_status["components"]["app_config"] = "connected"
                except Exception as e:
                    health_status["components"]["app_config"] = f"error: {str(e)}"
        
        if _current_config:
            health_status["components"]["current_config"] = "loaded"
            health_status["environment"] = _current_config.environment
            health_status["service_name"] = _current_config.service_name
        
        # Determine overall status
        error_components = [
            comp for comp, status in health_status["components"].items()
            if status.startswith("error")
        ]
        
        if error_components:
            health_status["status"] = "degraded"
            health_status["errors"] = error_components
        
        return health_status
        
    except Exception as e:
        logger.error(f"Config health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }