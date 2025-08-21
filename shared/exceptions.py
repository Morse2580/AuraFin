# shared/exceptions.py
"""
Custom exceptions for CashAppAgent
Centralized error handling across all services
"""

class CashAppException(Exception):
    """Base exception for all CashApp errors"""
    def __init__(self, message: str, error_code: str = None, details: dict = None):
        self.message = message
        self.error_code = error_code or "CASHAPP_ERROR"
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(CashAppException):
    """Data validation errors"""
    def __init__(self, message: str, field: str = None, value=None):
        details = {"field": field, "value": value} if field else {}
        super().__init__(message, "VALIDATION_ERROR", details)


class ProcessingError(CashAppException):
    """Payment processing errors"""
    def __init__(self, message: str, transaction_id: str = None):
        details = {"transaction_id": transaction_id} if transaction_id else {}
        super().__init__(message, "PROCESSING_ERROR", details)


class ERPIntegrationError(CashAppException):
    """ERP system integration errors"""
    def __init__(self, message: str, erp_system: str = None, operation: str = None):
        details = {"erp_system": erp_system, "operation": operation}
        super().__init__(message, "ERP_INTEGRATION_ERROR", details)


class DocumentIntelligenceError(CashAppException):
    """Document parsing and ML errors"""
    def __init__(self, message: str, document_uri: str = None, model_name: str = None):
        details = {"document_uri": document_uri, "model_name": model_name}
        super().__init__(message, "DOCUMENT_INTELLIGENCE_ERROR", details)


class CommunicationError(CashAppException):
    """Communication module errors"""
    def __init__(self, message: str, recipient: str = None, comm_type: str = None):
        details = {"recipient": recipient, "communication_type": comm_type}
        super().__init__(message, "COMMUNICATION_ERROR", details)


class SecurityError(CashAppException):
    """Security and authentication errors"""
    def __init__(self, message: str, resource: str = None):
        details = {"resource": resource} if resource else {}
        super().__init__(message, "SECURITY_ERROR", details)


class ERPConnectionError(CashAppException):
    """ERP connection specific errors"""
    def __init__(self, message: str, erp_system: str = None):
        details = {"erp_system": erp_system} if erp_system else {}
        super().__init__(message, "ERP_CONNECTION_ERROR", details)


class ERPAuthenticationError(CashAppException):
    """ERP authentication specific errors"""
    def __init__(self, message: str, erp_system: str = None):
        details = {"erp_system": erp_system} if erp_system else {}
        super().__init__(message, "ERP_AUTH_ERROR", details)


class ERPDataError(CashAppException):
    """ERP data format or validation errors"""
    def __init__(self, message: str, erp_system: str = None):
        details = {"erp_system": erp_system} if erp_system else {}
        super().__init__(message, "ERP_DATA_ERROR", details)


class DIMProcessingError(CashAppException):
    """Document Intelligence Module processing errors"""
    def __init__(self, message: str, document_uri: str = None):
        details = {"document_uri": document_uri} if document_uri else {}
        super().__init__(message, "DIM_PROCESSING_ERROR", details)