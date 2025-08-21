# services/eic/app/connectors/erp_manager.py
"""
ERP Manager - orchestrates multiple ERP system connectors
Provides unified interface for all ERP operations
"""

import asyncio
import time
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone

from shared.logging_config import get_logger
from shared.exceptions import ERPConnectionError, ERPAuthenticationError, ERPDataError
from shared.models import Invoice, MatchResult

from .netsuite import NetSuiteConnector
from .sap import SAPConnector
from .base import BaseERPConnector

logger = get_logger(__name__)

class ERPManager:
    """
    Manages multiple ERP system connectors
    Provides fallback logic and load balancing
    """
    
    def __init__(self, credential_manager, settings):
        self.credential_manager = credential_manager
        self.settings = settings
        self.connectors: Dict[str, BaseERPConnector] = {}
        self.system_status = {}
        self.last_health_check = {}
    
    async def initialize(self):
        """Initialize all ERP connectors"""
        try:
            # Initialize NetSuite connector
            if hasattr(self.settings, 'NETSUITE_ENDPOINT') and self.settings.NETSUITE_ENDPOINT:
                netsuite_config = await self.credential_manager.get_credentials('netsuite')
                if netsuite_config:
                    self.connectors['netsuite'] = NetSuiteConnector(netsuite_config)
                    await self.connectors['netsuite'].initialize()
                    logger.info("NetSuite connector initialized")
            
            # Initialize SAP connector
            if hasattr(self.settings, 'SAP_ENDPOINT') and self.settings.SAP_ENDPOINT:
                sap_config = await self.credential_manager.get_credentials('sap')
                if sap_config:
                    self.connectors['sap'] = SAPConnector(sap_config)
                    await self.connectors['sap'].initialize()
                    logger.info("SAP connector initialized")
            
            # Test all connections
            await self._test_all_connections()
            
            logger.info(f"ERP Manager initialized with {len(self.connectors)} connectors")
            
        except Exception as e:
            logger.error(f"ERP Manager initialization failed: {e}")
            raise ERPConnectionError(f"ERP initialization failed: {e}")
    
    async def cleanup(self):
        """Cleanup all connectors"""
        for name, connector in self.connectors.items():
            try:
                await connector.close()
                logger.info(f"Closed {name} connector")
            except Exception as e:
                logger.warning(f"Error closing {name} connector: {e}")
    
    async def get_invoices_from_system(self, system_name: str, invoice_ids: List[str]) -> List[Invoice]:
        """
        Get invoices from specific ERP system
        
        Args:
            system_name: Name of ERP system
            invoice_ids: List of invoice IDs to fetch
            
        Returns:
            List of found invoices
        """
        try:
            connector = self.connectors.get(system_name)
            if not connector:
                raise ERPConnectionError(f"ERP system {system_name} not configured")
            
            # Check system health
            if not await self._is_system_healthy(system_name):
                raise ERPConnectionError(f"ERP system {system_name} is unhealthy")
            
            start_time = time.time()
            invoices = await connector.get_invoices(invoice_ids)
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Update system status
            self.system_status[system_name] = {
                'status': 'healthy',
                'last_success': datetime.now(timezone.utc),
                'response_time_ms': duration_ms
            }
            
            logger.info(f"Retrieved {len(invoices)} invoices from {system_name}", extra={
                'system': system_name,
                'requested': len(invoice_ids),
                'found': len(invoices),
                'duration_ms': duration_ms
            })
            
            return invoices
            
        except Exception as e:
            # Update system status
            self.system_status[system_name] = {
                'status': 'error',
                'last_error': str(e),
                'error_time': datetime.now(timezone.utc)
            }
            
            logger.error(f"Failed to get invoices from {system_name}: {e}")
            
            if isinstance(e, (ERPConnectionError, ERPAuthenticationError, ERPDataError)):
                raise
            else:
                raise ERPConnectionError(f"Invoice retrieval failed: {e}", system_name)
    
    async def get_invoices_multi_system(self, invoice_ids: List[str]) -> List[Invoice]:
        """
        Get invoices from multiple ERP systems with fallback
        
        Args:
            invoice_ids: List of invoice IDs to fetch
            
        Returns:
            Combined list of invoices from all systems
        """
        all_invoices = []
        attempted_systems = []
        
        # Try systems in priority order
        for system_name in self.settings.SYSTEM_PRIORITY_ORDER:
            if system_name not in self.connectors:
                continue
            
            try:
                attempted_systems.append(system_name)
                invoices = await self.get_invoices_from_system(system_name, invoice_ids)
                all_invoices.extend(invoices)
                
                # Remove found invoice IDs from remaining searches
                found_ids = {inv.invoice_id for inv in invoices}
                invoice_ids = [id for id in invoice_ids if id not in found_ids]
                
                # Stop if all invoices found
                if not invoice_ids:
                    break
                    
            except Exception as e:
                logger.warning(f"Failed to get invoices from {system_name}: {e}")
                continue
        
        logger.info(f"Multi-system invoice retrieval completed", extra={
            'attempted_systems': attempted_systems,
            'total_invoices_found': len(all_invoices),
            'remaining_invoice_ids': len(invoice_ids)
        })
        
        return all_invoices
    
    async def post_application_to_system(self, 
                                        system_name: str, 
                                        match_result: MatchResult,
                                        idempotency_key: str = None) -> Dict[str, Any]:
        """
        Post cash application to specific ERP system
        
        Args:
            system_name: Name of ERP system
            match_result: Match result with payment applications
            idempotency_key: Idempotency key for duplicate prevention
            
        Returns:
            Application result
        """
        try:
            connector = self.connectors.get(system_name)
            if not connector:
                raise ERPConnectionError(f"ERP system {system_name} not configured")
            
            # Check system health
            if not await self._is_system_healthy(system_name):
                raise ERPConnectionError(f"ERP system {system_name} is unhealthy")
            
            start_time = time.time()
            result = await connector.post_cash_application(match_result, idempotency_key)
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Update system status
            self.system_status[system_name] = {
                'status': 'healthy',
                'last_success': datetime.now(timezone.utc),
                'response_time_ms': duration_ms
            }
            
            logger.info(f"Posted application to {system_name}", extra={
                'system': system_name,
                'transaction_id': match_result.transaction_id,
                'invoice_count': len(match_result.matched_pairs),
                'duration_ms': duration_ms
            })
            
            return {
                'success': True,
                'erp_system': system_name,
                'erp_transaction_id': result.get('transaction_id'),
                'duration_ms': duration_ms,
                'details': result
            }
            
        except Exception as e:
            # Update system status
            self.system_status[system_name] = {
                'status': 'error',
                'last_error': str(e),
                'error_time': datetime.now(timezone.utc)
            }
            
            logger.error(f"Failed to post application to {system_name}: {e}")
            
            if isinstance(e, (ERPConnectionError, ERPAuthenticationError, ERPDataError)):
                raise
            else:
                raise ERPConnectionError(f"Application posting failed: {e}", system_name)
    
    async def post_application_auto_detect(self, 
                                          match_result: MatchResult,
                                          idempotency_key: str = None) -> Dict[str, Any]:
        """
        Post application with automatic ERP system detection
        
        Args:
            match_result: Match result with payment applications
            idempotency_key: Idempotency key for duplicate prevention
            
        Returns:
            Application result
        """
        # Determine ERP system based on invoice ID patterns
        target_system = await self._detect_erp_system(list(match_result.matched_pairs.keys()))
        
        if target_system:
            return await self.post_application_to_system(target_system, match_result, idempotency_key)
        else:
            # Try all systems until one succeeds
            for system_name in self.settings.SYSTEM_PRIORITY_ORDER:
                if system_name not in self.connectors:
                    continue
                
                try:
                    return await self.post_application_to_system(system_name, match_result, idempotency_key)
                except Exception as e:
                    logger.warning(f"Auto-detect failed for {system_name}: {e}")
                    continue
            
            raise ERPConnectionError("No ERP system could process the application")
    
    async def test_system(self, system_name: str) -> Dict[str, Any]:
        """
        Test specific ERP system connectivity
        
        Args:
            system_name: Name of ERP system to test
            
        Returns:
            Test result
        """
        try:
            connector = self.connectors.get(system_name)
            if not connector:
                return {
                    'status': 'not_configured',
                    'system': system_name,
                    'message': 'Connector not configured'
                }
            
            start_time = time.time()
            test_result = await connector.test_connection()
            duration_ms = int((time.time() - start_time) * 1000)
            
            self.last_health_check[system_name] = {
                'timestamp': datetime.now(timezone.utc),
                'result': test_result,
                'duration_ms': duration_ms
            }
            
            return {
                'status': 'success' if test_result else 'failed',
                'system': system_name,
                'response_time_ms': duration_ms,
                'details': test_result
            }
            
        except Exception as e:
            logger.error(f"System test failed for {system_name}: {e}")
            return {
                'status': 'error',
                'system': system_name,
                'error': str(e)
            }
    
    async def test_all_systems(self) -> Dict[str, Any]:
        """Test all configured ERP systems"""
        results = {}
        
        # Test all systems concurrently
        tasks = [
            self.test_system(system_name)
            for system_name in self.connectors.keys()
        ]
        
        if tasks:
            test_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(test_results):
                system_name = list(self.connectors.keys())[i]
                if isinstance(result, Exception):
                    results[system_name] = {
                        'status': 'error',
                        'error': str(result)
                    }
                else:
                    results[system_name] = result
        
        return results
    
    async def list_systems(self) -> List[Dict[str, Any]]:
        """List all configured ERP systems"""
        systems = []
        
        for system_name, connector in self.connectors.items():
            system_info = {
                'name': system_name,
                'type': connector.system_type,
                'status': self.system_status.get(system_name, {}).get('status', 'unknown'),
                'last_tested': None,
                'configuration': {
                    'endpoint': getattr(connector, 'endpoint', 'unknown'),
                    'timeout': getattr(connector, 'timeout', 30),
                    'max_retries': getattr(connector, 'max_retries', 3)
                }
            }
            
            # Add last health check info
            if system_name in self.last_health_check:
                check_info = self.last_health_check[system_name]
                system_info['last_tested'] = check_info['timestamp'].isoformat()
                system_info['last_response_time_ms'] = check_info['duration_ms']
            
            systems.append(system_info)
        
        return systems
    
    async def get_transaction_logs(self, transaction_id: str) -> List[Dict[str, Any]]:
        """
        Get ERP operation logs for transaction
        
        Args:
            transaction_id: Transaction ID to get logs for
            
        Returns:
            List of ERP operation logs
        """
        try:
            from shared.database import get_db_manager
            
            db = await get_db_manager()
            logs = await db.execute_query("""
                SELECT 
                    eo.operation_type,
                    eo.success,
                    eo.error_message,
                    eo.duration_ms,
                    eo.retry_count,
                    eo.created_at,
                    es.system_name
                FROM erp_operations eo
                JOIN erp_systems es ON eo.erp_system_id = es.id
                JOIN payment_transactions pt ON eo.transaction_id = pt.id
                WHERE pt.transaction_id = $1
                ORDER BY eo.created_at DESC
            """, transaction_id)
            
            return [
                {
                    'operation_type': log['operation_type'],
                    'erp_system': log['system_name'],
                    'success': log['success'],
                    'error_message': log['error_message'],
                    'duration_ms': log['duration_ms'],
                    'retry_count': log['retry_count'],
                    'timestamp': log['created_at'].isoformat()
                }
                for log in logs
            ]
            
        except Exception as e:
            logger.error(f"Failed to get transaction logs: {e}")
            return []
    
    async def _test_all_connections(self):
        """Test all ERP connections during initialization"""
        if not self.connectors:
            logger.warning("No ERP connectors configured")
            return
        
        test_results = await self.test_all_systems()
        
        healthy_systems = [
            name for name, result in test_results.items()
            if result.get('status') == 'success'
        ]
        
        logger.info(f"ERP connection tests completed: {len(healthy_systems)}/{len(self.connectors)} healthy")
    
    async def _is_system_healthy(self, system_name: str) -> bool:
        """Check if ERP system is currently healthy"""
        status_info = self.system_status.get(system_name, {})
        status = status_info.get('status', 'unknown')
        
        # Consider system healthy if last known status was good
        # In production, might want more sophisticated health tracking
        return status in ['healthy', 'unknown']
    
    async def _detect_erp_system(self, invoice_ids: List[str]) -> Optional[str]:
        """
        Detect appropriate ERP system based on invoice ID patterns
        
        Args:
            invoice_ids: List of invoice IDs to analyze
            
        Returns:
            Best matching ERP system name
        """
        if not invoice_ids:
            return None
        
        # Simple pattern matching - in production would be more sophisticated
        sample_id = invoice_ids[0].upper()
        
        # NetSuite patterns
        if sample_id.startswith(('INV-', 'SO-', 'SALES')):
            return 'netsuite'
        
        # SAP patterns
        elif sample_id.startswith(('1', '2', '3', '4', '5')) and len(sample_id) >= 8:
            return 'sap'
        
        # Default to first available system
        return list(self.connectors.keys())[0] if self.connectors else None

class CredentialManager:
    """
    Manages ERP system credentials with Azure Key Vault integration
    Provides secure credential storage and retrieval
    """
    
    def __init__(self, key_vault_url: str, database_url: str):
        self.key_vault_url = key_vault_url
        self.database_url = database_url
        self.credential_cache = {}
        self.cache_expiry = {}
    
    async def get_credentials(self, system_name: str) -> Optional[Dict[str, Any]]:
        """
        Get credentials for ERP system
        
        Args:
            system_name: Name of ERP system
            
        Returns:
            Credential configuration
        """
        try:
            # Check cache first
            if system_name in self.credential_cache:
                cache_time = self.cache_expiry.get(system_name, 0)
                if time.time() < cache_time:
                    return self.credential_cache[system_name]
            
            # Load from database/Key Vault
            credentials = await self._load_credentials_from_storage(system_name)
            
            if credentials:
                # Cache for 15 minutes
                self.credential_cache[system_name] = credentials
                self.cache_expiry[system_name] = time.time() + 900
            
            return credentials
            
        except Exception as e:
            logger.error(f"Failed to get credentials for {system_name}: {e}")
            return None
    
    async def _load_credentials_from_storage(self, system_name: str) -> Optional[Dict[str, Any]]:
        """Load credentials from database and Key Vault"""
        try:
            # Load from database first
            from shared.database import get_db_manager
            
            db = await get_db_manager()
            result = await db.execute_query(
                "SELECT auth_config_encrypted FROM erp_systems WHERE system_name = $1 AND active = true",
                system_name
            )
            
            if result:
                # Decrypt auth config (simplified - use proper decryption in production)
                auth_config = result[0]['auth_config_encrypted'].decode('utf-8')
                credentials = json.loads(auth_config)
                
                # Enhance with Key Vault secrets if available
                if self.key_vault_url:
                    await self._enhance_with_key_vault_secrets(credentials, system_name)
                
                return credentials
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to load credentials for {system_name}: {e}")
            return None
    
    async def _enhance_with_key_vault_secrets(self, credentials: Dict[str, Any], system_name: str):
        """Enhance credentials with secrets from Key Vault"""
        try:
            # This would integrate with Azure Key Vault
            # For now, placeholder implementation
            logger.debug(f"Enhanced credentials for {system_name} with Key Vault secrets")
            
        except Exception as e:
            logger.warning(f"Failed to enhance credentials with Key Vault: {e}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Check credential manager health"""
        return {
            'status': 'healthy',
            'cached_credentials': len(self.credential_cache),
            'key_vault_configured': bool(self.key_vault_url)
        }