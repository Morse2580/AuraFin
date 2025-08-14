# shared/client_manager.py
"""
Client configuration and onboarding system for CashAppAgent
Manages multi-tenant client configurations, ERP connections, and matching rules
"""

import json
import time
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
from uuid import uuid4

from .logging import setup_logging
from .exception import CashAppException
from .database import get_db_manager

logger = setup_logging("client_manager")

class ERPSystem(str, Enum):
    """Supported ERP systems"""
    NETSUITE = "netsuite"
    SAP = "sap"
    QUICKBOOKS = "quickbooks"
    SAGE = "sage"
    DYNAMICS = "dynamics"

class ClientStatus(str, Enum):
    """Client status in the system"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ONBOARDING = "onboarding"
    SUSPENDED = "suspended"

@dataclass
class ERPConnection:
    """ERP system connection configuration"""
    system_type: ERPSystem
    endpoint_url: str
    authentication: Dict[str, Any]
    timeout_seconds: int = 30
    max_retries: int = 3
    custom_fields_mapping: Dict[str, str] = None
    
    def __post_init__(self):
        if self.custom_fields_mapping is None:
            self.custom_fields_mapping = {}

@dataclass
class MatchingRules:
    """Client-specific matching rules and thresholds"""
    min_confidence_threshold: float = 0.8
    auto_apply_threshold: float = 10000.0
    require_exact_amount_match: bool = False
    allow_partial_payments: bool = True
    tolerance_percentage: float = 0.01  # 1% tolerance
    currency_codes: List[str] = None
    invoice_id_patterns: List[str] = None
    
    def __post_init__(self):
        if self.currency_codes is None:
            self.currency_codes = ["EUR", "USD", "GBP"]
        if self.invoice_id_patterns is None:
            self.invoice_id_patterns = [
                r'INV[-_]?(\d{4,8})',
                r'INVOICE[-_]?(\d{4,8})',
                r'PO[-_]?(\d{4,8})'
            ]

@dataclass
class CommunicationConfig:
    """Client communication preferences"""
    primary_contact_email: str
    finance_team_emails: List[str]
    notification_preferences: Dict[str, bool]
    email_templates: Dict[str, str] = None
    slack_webhook_url: Optional[str] = None
    
    def __post_init__(self):
        if self.email_templates is None:
            self.email_templates = {}
        if not hasattr(self, 'notification_preferences') or not self.notification_preferences:
            self.notification_preferences = {
                'send_match_confirmations': True,
                'send_discrepancy_alerts': True,
                'send_processing_summaries': False,
                'send_error_notifications': True
            }

@dataclass
class ClientConfiguration:
    """Complete client configuration"""
    client_id: str
    client_name: str
    status: ClientStatus
    erp_connections: List[ERPConnection]
    matching_rules: MatchingRules
    communication_config: CommunicationConfig
    
    # Metadata
    created_at: datetime
    updated_at: datetime
    onboarded_by: str
    
    # Feature flags for this client
    feature_flags: Dict[str, bool] = None
    
    # Custom business logic
    custom_processors: List[str] = None
    
    def __post_init__(self):
        if self.feature_flags is None:
            self.feature_flags = {
                'enable_ml_processing': True,
                'enable_automated_application': True,
                'enable_customer_notifications': True,
                'enable_advanced_matching': True
            }
        if self.custom_processors is None:
            self.custom_processors = []

class ClientManager:
    """
    Manages client configurations and onboarding
    Provides CRUD operations for client settings
    """
    
    def __init__(self):
        self.db = None
        self._client_cache = {}
        self._cache_expiry = {}
    
    async def initialize(self):
        """Initialize client manager with database connection"""
        self.db = await get_db_manager()
        await self._create_client_tables()
        logger.info("Client manager initialized")
    
    async def _create_client_tables(self):
        """Create client configuration tables if they don't exist"""
        try:
            # Client configurations table
            await self.db.execute_command("""
                CREATE TABLE IF NOT EXISTS client_configurations (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    client_id VARCHAR(100) UNIQUE NOT NULL,
                    client_name VARCHAR(255) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'onboarding',
                    configuration JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    onboarded_by VARCHAR(255) NOT NULL
                )
            """)
            
            # Client ERP connections table
            await self.db.execute_command("""
                CREATE TABLE IF NOT EXISTS client_erp_connections (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    client_id VARCHAR(100) NOT NULL,
                    erp_system VARCHAR(50) NOT NULL,
                    endpoint_url VARCHAR(500) NOT NULL,
                    auth_config_encrypted BYTEA NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    last_tested_at TIMESTAMPTZ,
                    last_error TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    
                    FOREIGN KEY (client_id) REFERENCES client_configurations(client_id),
                    UNIQUE(client_id, erp_system)
                )
            """)
            
            # Client processing history table
            await self.db.execute_command("""
                CREATE TABLE IF NOT EXISTS client_processing_history (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    client_id VARCHAR(100) NOT NULL,
                    date DATE NOT NULL,
                    transactions_processed INTEGER NOT NULL DEFAULT 0,
                    successful_matches INTEGER NOT NULL DEFAULT 0,
                    failed_matches INTEGER NOT NULL DEFAULT 0,
                    amount_processed DECIMAL(15,2) NOT NULL DEFAULT 0,
                    currency VARCHAR(3) NOT NULL,
                    
                    FOREIGN KEY (client_id) REFERENCES client_configurations(client_id),
                    UNIQUE(client_id, date, currency)
                )
            """)
            
            logger.info("Client tables created/verified")
            
        except Exception as e:
            logger.error(f"Failed to create client tables: {e}")
            raise CashAppException(f"Client table creation failed: {e}", "DB_SCHEMA_ERROR")
    
    async def onboard_client(self, 
                           client_id: str,
                           client_name: str,
                           erp_connections: List[ERPConnection],
                           onboarded_by: str,
                           matching_rules: MatchingRules = None,
                           communication_config: CommunicationConfig = None) -> ClientConfiguration:
        """
        Onboard new client with complete configuration
        
        Args:
            client_id: Unique client identifier
            client_name: Display name for client
            erp_connections: List of ERP system connections
            onboarded_by: User who performed onboarding
            matching_rules: Custom matching rules (optional)
            communication_config: Communication preferences (optional)
            
        Returns:
            Complete client configuration
        """
        try:
            # Validate client doesn't already exist
            existing_client = await self.get_client_config(client_id)
            if existing_client:
                raise CashAppException(f"Client {client_id} already exists", "CLIENT_EXISTS")
            
            # Create default configurations if not provided
            if not matching_rules:
                matching_rules = MatchingRules()
            
            if not communication_config:
                communication_config = CommunicationConfig(
                    primary_contact_email=f"finance@{client_id.lower()}.com",
                    finance_team_emails=[],
                    notification_preferences={}
                )
            
            # Create client configuration
            client_config = ClientConfiguration(
                client_id=client_id,
                client_name=client_name,
                status=ClientStatus.ONBOARDING,
                erp_connections=erp_connections,
                matching_rules=matching_rules,
                communication_config=communication_config,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                onboarded_by=onboarded_by
            )
            
            # Store in database
            await self._store_client_config(client_config)
            
            # Test ERP connections
            connection_results = await self._test_erp_connections(client_id, erp_connections)
            
            # Update status based on connection tests
            if all(result['success'] for result in connection_results.values()):
                client_config.status = ClientStatus.ACTIVE
                await self._update_client_status(client_id, ClientStatus.ACTIVE)
                logger.info(f"Client {client_id} successfully onboarded and activated")
            else:
                logger.warning(f"Client {client_id} onboarded but ERP connections failed")
            
            # Clear cache
            self._client_cache.pop(client_id, None)
            
            return client_config
            
        except Exception as e:
            logger.error(f"Client onboarding failed for {client_id}: {e}")
            raise CashAppException(f"Client onboarding failed: {e}", "CLIENT_ONBOARDING_ERROR")
    
    async def get_client_config(self, client_id: str) -> Optional[ClientConfiguration]:
        """
        Get client configuration by ID
        
        Args:
            client_id: Client identifier
            
        Returns:
            Client configuration if found
        """
        # Check cache first
        if client_id in self._client_cache:
            cache_time = self._cache_expiry.get(client_id, 0)
            if time.time() < cache_time:
                return self._client_cache[client_id]
        
        try:
            # Load from database
            result = await self.db.execute_query(
                "SELECT configuration FROM client_configurations WHERE client_id = $1 AND status != 'suspended'",
                client_id
            )
            
            if result:
                config_data = result[0]['configuration']
                client_config = ClientConfiguration(**config_data)
                
                # Cache for 5 minutes
                self._client_cache[client_id] = client_config
                self._cache_expiry[client_id] = time.time() + 300
                
                return client_config
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get client config for {client_id}: {e}")
            return None
    
    async def update_client_config(self, client_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update client configuration
        
        Args:
            client_id: Client identifier
            updates: Configuration updates to apply
            
        Returns:
            True if update successful
        """
        try:
            # Get current config
            current_config = await self.get_client_config(client_id)
            if not current_config:
                raise CashAppException(f"Client {client_id} not found", "CLIENT_NOT_FOUND")
            
            # Apply updates
            config_dict = asdict(current_config)
            self._apply_updates(config_dict, updates)
            
            # Update timestamp
            config_dict['updated_at'] = datetime.utcnow()
            
            # Store updated config
            updated_config = ClientConfiguration(**config_dict)
            await self._store_client_config(updated_config)
            
            # Clear cache
            self._client_cache.pop(client_id, None)
            
            logger.info(f"Client configuration updated: {client_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update client config for {client_id}: {e}")
            return False
    
    def _apply_updates(self, config_dict: Dict[str, Any], updates: Dict[str, Any]):
        """Apply nested updates to configuration dictionary"""
        for key, value in updates.items():
            if '.' in key:
                # Handle nested updates like 'matching_rules.min_confidence_threshold'
                parts = key.split('.')
                current = config_dict
                for part in parts[:-1]:
                    if part not in current:
                        current[part] = {}
                    current = current[part]
                current[parts[-1]] = value
            else:
                config_dict[key] = value
    
    async def _store_client_config(self, client_config: ClientConfiguration):
        """Store client configuration in database"""
        config_json = asdict(client_config)
        
        # Convert datetime objects to ISO strings for JSON serialization
        config_json['created_at'] = client_config.created_at.isoformat()
        config_json['updated_at'] = client_config.updated_at.isoformat()
        
        await self.db.execute_command("""
            INSERT INTO client_configurations (client_id, client_name, status, configuration, onboarded_by)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (client_id) 
            DO UPDATE SET 
                client_name = EXCLUDED.client_name,
                status = EXCLUDED.status,
                configuration = EXCLUDED.configuration,
                updated_at = NOW()
        """, 
        client_config.client_id,
        client_config.client_name,
        client_config.status.value,
        json.dumps(config_json),
        client_config.onboarded_by
        )
    
    async def _update_client_status(self, client_id: str, status: ClientStatus):
        """Update client status"""
        await self.db.execute_command(
            "UPDATE client_configurations SET status = $1, updated_at = NOW() WHERE client_id = $2",
            status.value,
            client_id
        )
    
    async def _test_erp_connections(self, client_id: str, connections: List[ERPConnection]) -> Dict[str, Any]:
        """
        Test all ERP connections for a client
        
        Args:
            client_id: Client identifier
            connections: List of ERP connections to test
            
        Returns:
            Dictionary of test results by ERP system
        """
        results = {}
        
        for connection in connections:
            try:
                # Store encrypted connection info
                await self._store_erp_connection(client_id, connection)
                
                # Test connection (placeholder - would call actual ERP test)
                test_result = await self._test_single_erp_connection(connection)
                results[connection.system_type.value] = test_result
                
            except Exception as e:
                logger.error(f"ERP connection test failed for {connection.system_type}: {e}")
                results[connection.system_type.value] = {
                    'success': False,
                    'error': str(e),
                    'tested_at': datetime.utcnow().isoformat()
                }
        
        return results
    
    async def _store_erp_connection(self, client_id: str, connection: ERPConnection):
        """Store ERP connection configuration with encrypted auth"""
        # In production, encrypt the auth_config before storing
        auth_config_json = json.dumps(connection.authentication)
        
        await self.db.execute_command("""
            INSERT INTO client_erp_connections (client_id, erp_system, endpoint_url, auth_config_encrypted)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (client_id, erp_system)
            DO UPDATE SET 
                endpoint_url = EXCLUDED.endpoint_url,
                auth_config_encrypted = EXCLUDED.auth_config_encrypted,
                status = 'active'
        """,
        client_id,
        connection.system_type.value,
        connection.endpoint_url,
        auth_config_json.encode('utf-8')  # Simple encoding - use proper encryption in production
        )
    
    async def _test_single_erp_connection(self, connection: ERPConnection) -> Dict[str, Any]:
        """
        Test single ERP connection
        
        Args:
            connection: ERP connection to test
            
        Returns:
            Test result
        """
        # Placeholder implementation - would test actual ERP connectivity
        await asyncio.sleep(0.1)  # Simulate connection test
        
        return {
            'success': True,
            'response_time_ms': 150,
            'tested_at': datetime.utcnow().isoformat(),
            'version': '2024.1',
            'capabilities': ['invoice_lookup', 'payment_posting']
        }
    
    async def list_clients(self, status_filter: List[ClientStatus] = None) -> List[Dict[str, Any]]:
        """
        List all clients with optional status filtering
        
        Args:
            status_filter: Optional list of statuses to filter by
            
        Returns:
            List of client summaries
        """
        try:
            query = "SELECT client_id, client_name, status, created_at, updated_at FROM client_configurations"
            params = []
            
            if status_filter:
                placeholders = ','.join(f'${i+1}' for i in range(len(status_filter)))
                query += f" WHERE status IN ({placeholders})"
                params = [status.value for status in status_filter]
            
            query += " ORDER BY created_at DESC"
            
            results = await self.db.execute_query(query, *params)
            
            return [
                {
                    'client_id': row['client_id'],
                    'client_name': row['client_name'],
                    'status': row['status'],
                    'created_at': row['created_at'].isoformat(),
                    'updated_at': row['updated_at'].isoformat()
                }
                for row in results
            ]
            
        except Exception as e:
            logger.error(f"Failed to list clients: {e}")
            return []
    
    async def get_client_matching_rules(self, client_id: str) -> Optional[MatchingRules]:
        """
        Get client-specific matching rules
        
        Args:
            client_id: Client identifier
            
        Returns:
            Matching rules for client
        """
        client_config = await self.get_client_config(client_id)
        if client_config:
            return client_config.matching_rules
        return None
    
    async def get_client_erp_connections(self, client_id: str) -> List[ERPConnection]:
        """
        Get all ERP connections for client
        
        Args:
            client_id: Client identifier
            
        Returns:
            List of ERP connections
        """
        client_config = await self.get_client_config(client_id)
        if client_config:
            return client_config.erp_connections
        return []
    
    async def update_client_processing_stats(self, 
                                           client_id: str,
                                           transaction_count: int,
                                           successful_matches: int,
                                           failed_matches: int,
                                           amount_processed: float,
                                           currency: str):
        """
        Update daily processing statistics for client
        
        Args:
            client_id: Client identifier
            transaction_count: Number of transactions processed
            successful_matches: Number of successful matches
            failed_matches: Number of failed matches
            amount_processed: Total amount processed
            currency: Currency code
        """
        try:
            today = datetime.utcnow().date()
            
            await self.db.execute_command("""
                INSERT INTO client_processing_history 
                (client_id, date, transactions_processed, successful_matches, failed_matches, amount_processed, currency)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (client_id, date, currency)
                DO UPDATE SET
                    transactions_processed = client_processing_history.transactions_processed + EXCLUDED.transactions_processed,
                    successful_matches = client_processing_history.successful_matches + EXCLUDED.successful_matches,
                    failed_matches = client_processing_history.failed_matches + EXCLUDED.failed_matches,
                    amount_processed = client_processing_history.amount_processed + EXCLUDED.amount_processed
            """,
            client_id, today, transaction_count, successful_matches, 
            failed_matches, amount_processed, currency
            )
            
        except Exception as e:
            logger.error(f"Failed to update processing stats for {client_id}: {e}")
    
    async def get_client_processing_summary(self, client_id: str, days: int = 30) -> Dict[str, Any]:
        """
        Get processing summary for client
        
        Args:
            client_id: Client identifier
            days: Number of days to include in summary
            
        Returns:
            Processing summary statistics
        """
        try:
            cutoff_date = datetime.utcnow().date() - timedelta(days=days)
            
            results = await self.db.execute_query("""
                SELECT 
                    COUNT(*) as total_days,
                    SUM(transactions_processed) as total_transactions,
                    SUM(successful_matches) as total_successful,
                    SUM(failed_matches) as total_failed,
                    SUM(amount_processed) as total_amount,
                    currency,
                    AVG(successful_matches::float / NULLIF(transactions_processed, 0)) as avg_success_rate
                FROM client_processing_history 
                WHERE client_id = $1 AND date >= $2
                GROUP BY currency
                ORDER BY total_amount DESC
            """, client_id, cutoff_date)
            
            summary = {
                'client_id': client_id,
                'period_days': days,
                'currencies': []
            }
            
            total_transactions = 0
            total_successful = 0
            
            for row in results:
                currency_data = {
                    'currency': row['currency'],
                    'total_transactions': row['total_transactions'] or 0,
                    'successful_matches': row['total_successful'] or 0,
                    'failed_matches': row['total_failed'] or 0,
                    'total_amount': float(row['total_amount'] or 0),
                    'success_rate': float(row['avg_success_rate'] or 0)
                }
                summary['currencies'].append(currency_data)
                
                total_transactions += currency_data['total_transactions']
                total_successful += currency_data['successful_matches']
            
            summary['overall'] = {
                'total_transactions': total_transactions,
                'successful_matches': total_successful,
                'overall_success_rate': total_successful / total_transactions if total_transactions > 0 else 0
            }
            
            return summary
            
        except Exception as e:
            logger.error(f"Failed to get processing summary for {client_id}: {e}")
            return {'error': str(e)}
    
    async def suspend_client(self, client_id: str, reason: str) -> bool:
        """
        Suspend client processing
        
        Args:
            client_id: Client identifier
            reason: Reason for suspension
            
        Returns:
            True if suspension successful
        """
        try:
            await self._update_client_status(client_id, ClientStatus.SUSPENDED)
            
            # Log suspension
            logger.warning(f"Client {client_id} suspended", extra={
                'reason': reason,
                'suspended_at': datetime.utcnow().isoformat()
            })
            
            # Clear cache
            self._client_cache.pop(client_id, None)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to suspend client {client_id}: {e}")
            return False
    
    async def reactivate_client(self, client_id: str) -> bool:
        """
        Reactivate suspended client
        
        Args:
            client_id: Client identifier
            
        Returns:
            True if reactivation successful
        """
        try:
            # Test ERP connections before reactivating
            client_config = await self.get_client_config(client_id)
            if not client_config:
                return False
            
            connection_results = await self._test_erp_connections(client_id, client_config.erp_connections)
            
            if all(result['success'] for result in connection_results.values()):
                await self._update_client_status(client_id, ClientStatus.ACTIVE)
                logger.info(f"Client {client_id} reactivated successfully")
                return True
            else:
                logger.warning(f"Client {client_id} reactivation failed - ERP connections not healthy")
                return False
                
        except Exception as e:
            logger.error(f"Failed to reactivate client {client_id}: {e}")
            return False

class ClientMatchingEngine:
    """
    Client-specific matching logic
    Applies custom rules and thresholds per client
    """
    
    def __init__(self, client_manager: ClientManager):
        self.client_manager = client_manager
    
    async def get_matching_strategy(self, client_id: str, transaction: PaymentTransaction) -> Dict[str, Any]:
        """
        Get client-specific matching strategy
        
        Args:
            client_id: Client identifier
            transaction: Payment transaction to match
            
        Returns:
            Matching strategy configuration
        """
        try:
            # Get client matching rules
            matching_rules = await self.client_manager.get_client_matching_rules(client_id)
            if not matching_rules:
                # Use default rules
                matching_rules = MatchingRules()
            
            # Build strategy based on transaction and rules
            strategy = {
                'min_confidence': matching_rules.min_confidence_threshold,
                'auto_apply_threshold': matching_rules.auto_apply_threshold,
                'require_exact_match': matching_rules.require_exact_amount_match,
                'allow_partial_payments': matching_rules.allow_partial_payments,
                'tolerance_percentage': matching_rules.tolerance_percentage,
                'supported_currencies': matching_rules.currency_codes,
                'invoice_patterns': matching_rules.invoice_id_patterns
            }
            
            # Apply transaction-specific logic
            if transaction.amount > matching_rules.auto_apply_threshold:
                strategy['require_human_review'] = True
                strategy['auto_apply'] = False
            else:
                strategy['require_human_review'] = False
                strategy['auto_apply'] = True
            
            return strategy
            
        except Exception as e:
            logger.error(f"Failed to get matching strategy for {client_id}: {e}")
            # Return safe defaults
            return {
                'min_confidence': 0.8,
                'auto_apply_threshold': 10000.0,
                'require_human_review': True,
                'auto_apply': False
            }

# Global client manager instance
_client_manager = None
_client_matching_engine = None

async def initialize_client_system() -> ClientManager:
    """
    Initialize global client management system
    
    Returns:
        Initialized client manager
    """
    global _client_manager, _client_matching_engine
    
    if not _client_manager:
        _client_manager = ClientManager()
        await _client_manager.initialize()
        
        _client_matching_engine = ClientMatchingEngine(_client_manager)
        
        logger.info("Client system initialized")
    
    return _client_manager

async def get_client_manager() -> ClientManager:
    """Get initialized client manager"""
    if not _client_manager:
        return await initialize_client_system()
    return _client_manager

async def get_client_matching_engine() -> ClientMatchingEngine:
    """Get initialized client matching engine"""
    if not _client_matching_engine:
        await initialize_client_system()
    return _client_matching_engine

# Utility functions for client operations
async def is_client_active(client_id: str) -> bool:
    """Check if client is active"""
    client_manager = await get_client_manager()
    client_config = await client_manager.get_client_config(client_id)
    return client_config and client_config.status == ClientStatus.ACTIVE

async def get_client_erp_system(client_id: str, preferred_system: str = None) -> Optional[ERPConnection]:
    """
    Get appropriate ERP system for client
    
    Args:
        client_id: Client identifier
        preferred_system: Preferred ERP system name
        
    Returns:
        ERP connection to use
    """
    client_manager = await get_client_manager()
    connections = await client_manager.get_client_erp_connections(client_id)
    
    if not connections:
        return None
    
    if preferred_system:
        # Look for specific system
        for connection in connections:
            if connection.system_type.value == preferred_system:
                return connection
    
    # Return first active connection
    return connections[0] if connections else None

async def client_health_check() -> Dict[str, Any]:
    """
    Check client system health
    
    Returns:
        Health status of client management components
    """
    try:
        if not _client_manager:
            return {"status": "not_initialized"}
        
        # Get basic stats
        active_clients = await _client_manager.list_clients([ClientStatus.ACTIVE])
        total_clients = await _client_manager.list_clients()
        
        return {
            "status": "healthy",
            "components": {
                "client_manager": "initialized",
                "database": "connected"
            },
            "stats": {
                "total_clients": len(total_clients),
                "active_clients": len(active_clients),
                "cached_configs": len(_client_manager._client_cache)
            }
        }
        
    except Exception as e:
        logger.error(f"Client health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }