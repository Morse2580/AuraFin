# services/eic/app/connectors/base.py

from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
import json

from shared.models import Invoice, MatchResult
from shared.logging_config import get_logger
from shared.exceptions import ERPConnectionError, ERPAuthenticationError, ERPDataError

logger = get_logger(__name__)

@dataclass
class ERPCredentials:
    """ERP system credentials"""
    system_type: str  # 'netsuite', 'sap', 'quickbooks', etc.
    client_id: str
    client_secret: str
    additional_params: Dict[str, Any]  # System-specific parameters
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for secure storage"""
        return {
            "system_type": self.system_type,
            "client_id": self.client_id,
            "client_secret": "***REDACTED***",  # Never log secrets
            "additional_params": self.additional_params
        }

@dataclass
class ERPTransactionLog:
    """Log entry for ERP transactions"""
    transaction_id: str
    operation_type: str  # 'get_invoices', 'post_application'
    status: str  # 'success', 'error', 'pending'
    erp_system: str
    request_data: Dict[str, Any]
    response_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    processing_time_ms: int = 0
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()

class BaseERPConnector(ABC):
    """Base class for all ERP connectors"""
    
    def __init__(self, credentials: ERPCredentials, client_config: Dict[str, Any] = None):
        self.credentials = credentials
        self.client_config = client_config or {}
        self.system_type = credentials.system_type
        self._access_token = None
        self._token_expires_at = None
        
        logger.info(f"Initialized {self.system_type} ERP connector")
    
    @abstractmethod
    async def authenticate(self) -> bool:
        """Authenticate with the ERP system"""
        pass
    
    @abstractmethod
    async def get_invoices(self, invoice_ids: List[str]) -> List[Invoice]:
        """Retrieve invoice information from ERP"""
        pass
    
    @abstractmethod
    async def post_application(self, match_result: MatchResult) -> Dict[str, Any]:
        """Post cash application to ERP system"""
        pass
    
    @abstractmethod
    async def test_connection(self) -> Dict[str, Any]:
        """Test connection to ERP system"""
        pass
    
    async def ensure_authenticated(self) -> bool:
        """Ensure valid authentication token"""
        if self._access_token is None or self._is_token_expired():
            return await self.authenticate()
        return True
    
    def _is_token_expired(self) -> bool:
        """Check if current token is expired"""
        if self._token_expires_at is None:
            return True
        return datetime.utcnow() >= self._token_expires_at
    
    def _sanitize_log_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Remove sensitive information from log data"""
        sanitized = data.copy()
        
        # Remove common sensitive fields
        sensitive_fields = [
            'password', 'secret', 'token', 'authorization', 
            'client_secret', 'api_key', 'private_key'
        ]
        
        for field in sensitive_fields:
            if field in sanitized:
                sanitized[field] = "***REDACTED***"
        
        return sanitized