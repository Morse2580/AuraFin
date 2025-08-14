# shared/request_models.py
"""
Request and response models for API endpoints
Shared models used across all CashAppAgent services
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from decimal import Decimal

from .models import MatchResult, PaymentTransaction, DocumentParsingResult

# Document Intelligence Module Models
class DocumentParseRequest(BaseModel):
    """Request for document parsing"""
    document_uris: List[str] = Field(..., min_items=1, max_items=10, description="URIs of documents to parse")
    client_id: Optional[str] = Field(None, description="Client ID for custom processing rules")
    processing_options: Dict[str, Any] = Field(default_factory=dict, description="Additional processing options")

class DocumentParseResult(BaseModel):
    """Response from document parsing"""
    document_uri: str
    invoice_ids: List[str] = Field(default_factory=list)
    confidence_score: float = Field(..., ge=0, le=1)
    extracted_amounts: Optional[List[Decimal]] = None
    customer_identifiers: Optional[List[str]] = None
    processing_time_ms: int = Field(..., ge=0)
    ocr_text: Optional[str] = None

# Communication Module Models
class ClarificationEmailRequest(BaseModel):
    """Request for sending clarification email"""
    match_result: MatchResult
    customer_info: Dict[str, Any] = Field(..., description="Customer contact information")
    template_overrides: Optional[Dict[str, str]] = None

class InternalAlertRequest(BaseModel):
    """Request for internal alert"""
    match_result: MatchResult
    alert_type: str = Field(..., description="Type of alert: email, slack, or both")
    alert_config: Dict[str, Any] = Field(default_factory=dict, description="Alert configuration")

class BatchNotificationRequest(BaseModel):
    """Request for batch notifications"""
    notifications: List[Dict[str, Any]] = Field(..., min_items=1, max_items=100)

class CommunicationResponse(BaseModel):
    """Response from communication operations"""
    success: bool
    message_id: Optional[str] = None
    provider: str
    processing_time_ms: int
    details: Optional[Dict[str, Any]] = None

# ERP Integration Models
class InvoiceRequest(BaseModel):
    """Request for invoice retrieval"""
    invoice_ids: List[str] = Field(..., min_items=1, max_items=100)
    erp_system: Optional[str] = None
    currency_filter: Optional[str] = None
    status_filter: List[str] = Field(default_factory=lambda: ["open", "overdue"])

class ApplicationRequest(BaseModel):
    """Request for cash application posting"""
    match_result: MatchResult
    erp_system: Optional[str] = None
    idempotency_key: Optional[str] = None

class ERPSystemConfig(BaseModel):
    """ERP system configuration"""
    system_name: str
    system_type: str
    endpoint_url: str
    auth_config: Dict[str, Any]
    timeout_seconds: int = 30
    max_retries: int = 3

# Health Check Models
class HealthResponse(BaseModel):
    """Standard health check response"""
    status: str
    timestamp: str
    response_time_ms: int
    service: str
    version: str
    checks: Optional[Dict[str, Any]] = None

class DeepHealthResponse(BaseModel):
    """Comprehensive health check response"""
    status: str
    timestamp: str
    response_time_ms: int
    service: str
    version: str
    checks: Dict[str, Any]
    system_info: Dict[str, Any]
    dependencies: Dict[str, Any]

# Metrics Models
class MetricData(BaseModel):
    """Metric data point"""
    name: str
    value: float
    timestamp: datetime
    labels: Dict[str, str] = Field(default_factory=dict)

class MetricsResponse(BaseModel):
    """Metrics endpoint response"""
    service: str
    timestamp: str
    counters: Dict[str, int]
    gauges: Dict[str, float]
    histograms: Dict[str, Dict[str, float]]

# Transaction Processing Models
class ProcessTransactionRequest(BaseModel):
    """Request to process a payment transaction"""
    payment_transaction: PaymentTransaction
    client_id: Optional[str] = None
    processing_options: Dict[str, Any] = Field(default_factory=dict)

class ProcessTransactionResponse(BaseModel):
    """Response from transaction processing"""
    match_result: MatchResult
    processing_summary: str
    next_steps: List[str]
    recommendations: Optional[List[str]] = None

# Client Management Models
class ClientOnboardingRequest(BaseModel):
    """Request for client onboarding"""
    client_id: str = Field(..., min_length=2, max_length=50)
    client_name: str = Field(..., min_length=1, max_length=255)
    erp_connections: List[ERPSystemConfig]
    primary_contact_email: str = Field(..., pattern=r'^[^@]+@[^@]+\.[^@]+$')
    finance_team_emails: List[str] = Field(default_factory=list)
    matching_rules: Optional[Dict[str, Any]] = None
    onboarded_by: str

class ClientConfigurationResponse(BaseModel):
    """Response from client configuration operations"""
    client_id: str
    client_name: str
    status: str
    configuration_summary: Dict[str, Any]
    last_updated: datetime

class ClientListResponse(BaseModel):
    """Response from client listing"""
    clients: List[Dict[str, Any]]
    total_count: int
    active_count: int

# System Status Models
class SystemStatusResponse(BaseModel):
    """System status response"""
    service: str
    version: str
    status: str
    timestamp: str
    uptime_seconds: float
    configuration: Dict[str, Any]
    feature_flags: Dict[str, bool]

class ServiceDiscoveryResponse(BaseModel):
    """Service discovery response"""
    services: Dict[str, str]
    environment: str
    timestamp: str
