# shared/models.py
"""
Core Pydantic models for CashAppAgent
These models define the data structures used across all services
"""

from typing import List, Dict, Optional
from decimal import Decimal
from datetime import datetime
from pydantic import BaseModel, Field, validator
from enum import Enum


class TransactionStatus(str, Enum):
    """Transaction processing status"""
    PENDING = "pending"
    PROCESSING = "processing"
    MATCHED = "matched"
    PARTIALLY_MATCHED = "partially_matched"
    UNMATCHED = "unmatched"
    REQUIRES_REVIEW = "requires_review"
    ERROR = "error"


class InvoiceStatus(str, Enum):
    """Invoice status in ERP system"""
    OPEN = "open"
    CLOSED = "closed"
    DISPUTED = "disputed"
    OVERDUE = "overdue"


class DiscrepancyCode(str, Enum):
    """Types of payment discrepancies"""
    SHORT_PAYMENT = "short_payment"
    OVER_PAYMENT = "over_payment"
    INVALID_INVOICE = "invalid_invoice"
    CURRENCY_MISMATCH = "currency_mismatch"
    DUPLICATE_PAYMENT = "duplicate_payment"


class PaymentTransaction(BaseModel):
    """
    Payment transaction from bank feed
    Core data structure for incoming payments
    """
    transaction_id: str = Field(..., description="Unique ID from bank feed")
    source_account_ref: str = Field(..., description="Source bank account reference")
    amount: Decimal = Field(..., description="Payment amount", gt=0)
    currency: str = Field(..., description="ISO 4217 currency code", min_length=3, max_length=3)
    value_date: datetime = Field(..., description="Value date of the payment")
    raw_remittance_data: Optional[str] = Field(None, description="Text from bank feed")
    associated_document_uris: Optional[List[str]] = Field(None, description="URIs to PDFs/emails in Azure Blob Storage")
    customer_identifier: Optional[str] = Field(None, description="Identified customer from remittance data")
    processing_status: TransactionStatus = Field(TransactionStatus.PENDING, description="Current processing status")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @validator('currency')
    def validate_currency(cls, v):
        """Ensure currency is uppercase ISO 4217 code"""
        return v.upper()

    @validator('amount')
    def validate_amount_precision(cls, v):
        """Ensure amount has max 2 decimal places for financial accuracy"""
        if v.as_tuple().exponent < -2:
            raise ValueError('Amount cannot have more than 2 decimal places')
        return v

    class Config:
        use_enum_values = True


class Invoice(BaseModel):
    """
    Invoice data from ERP system
    Represents an open or closed invoice
    """
    invoice_id: str = Field(..., description="Invoice ID from ERP system")
    customer_id: str = Field(..., description="Customer identifier")
    customer_name: Optional[str] = Field(None, description="Customer display name")
    amount_due: Decimal = Field(..., description="Outstanding amount", ge=0)
    original_amount: Decimal = Field(..., description="Original invoice amount", gt=0)
    currency: str = Field(..., description="ISO 4217 currency code", min_length=3, max_length=3)
    status: InvoiceStatus = Field(..., description="Current invoice status")
    due_date: Optional[datetime] = Field(None, description="Payment due date")
    created_date: datetime = Field(..., description="Invoice creation date")
    
    @validator('currency')
    def validate_currency(cls, v):
        return v.upper()

    @validator('amount_due', 'original_amount')
    def validate_amount_precision(cls, v):
        if v.as_tuple().exponent < -2:
            raise ValueError('Amount cannot have more than 2 decimal places')
        return v

    class Config:
        use_enum_values = True


class MatchResult(BaseModel):
    """
    Result of payment matching algorithm
    Core output of the CLE processing engine
    """
    transaction_id: str = Field(..., description="Reference to original transaction")
    status: TransactionStatus = Field(..., description="Matching result status")
    matched_pairs: Dict[str, Decimal] = Field(default_factory=dict, description="Invoice ID -> Amount applied")
    unapplied_amount: Decimal = Field(Decimal('0'), description="Remaining unallocated amount", ge=0)
    discrepancy_code: Optional[DiscrepancyCode] = Field(None, description="Type of discrepancy if any")
    log_entry: str = Field(..., description="Human-readable summary of actions taken")
    confidence_score: Optional[float] = Field(None, description="ML confidence score (0-1)", ge=0, le=1)
    processing_time_ms: Optional[int] = Field(None, description="Processing time in milliseconds", ge=0)
    requires_human_review: bool = Field(False, description="Flag for human intervention needed")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @validator('unapplied_amount')
    def validate_unapplied_precision(cls, v):
        if v.as_tuple().exponent < -2:
            raise ValueError('Unapplied amount cannot have more than 2 decimal places')
        return v

    @validator('matched_pairs')
    def validate_matched_pairs_precision(cls, v):
        """Ensure all matched amounts have proper precision"""
        for invoice_id, amount in v.items():
            if amount.as_tuple().exponent < -2:
                raise ValueError(f'Matched amount for {invoice_id} cannot have more than 2 decimal places')
        return v

    class Config:
        use_enum_values = True


class DocumentParsingResult(BaseModel):
    """
    Result from Document Intelligence Module
    Output of DIM document parsing
    """
    document_uri: str = Field(..., description="URI of processed document")
    invoice_ids: List[str] = Field(default_factory=list, description="Extracted invoice IDs")
    confidence_score: float = Field(..., description="Overall extraction confidence", ge=0, le=1)
    extracted_amounts: Optional[List[Decimal]] = Field(None, description="Extracted monetary amounts")
    customer_identifiers: Optional[List[str]] = Field(None, description="Extracted customer references")
    processing_time_ms: int = Field(..., description="Processing time in milliseconds", ge=0)
    ocr_text: Optional[str] = Field(None, description="Full OCR extracted text")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class ERPOperationResult(BaseModel):
    """
    Result from ERP Integration operation
    Output of EIC operations
    """
    operation_type: str = Field(..., description="Type of ERP operation")
    transaction_id: str = Field(..., description="Reference transaction ID")
    erp_transaction_id: Optional[str] = Field(None, description="ERP system transaction ID")
    success: bool = Field(..., description="Operation success flag")
    error_message: Optional[str] = Field(None, description="Error details if failed")
    affected_invoices: List[str] = Field(default_factory=list, description="List of affected invoice IDs")
    operation_timestamp: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class CommunicationRequest(BaseModel):
    """
    Request for Communication Module
    Input for CM email/message operations
    """
    request_type: str = Field(..., description="Type of communication (email, slack, teams)")
    recipient: str = Field(..., description="Recipient identifier")
    template_name: str = Field(..., description="Message template to use")
    template_data: Dict = Field(default_factory=dict, description="Data for template rendering")
    priority: str = Field("normal", description="Message priority (low, normal, high, urgent)")
    transaction_id: Optional[str] = Field(None, description="Related transaction ID")
    
    class Config:
        use_enum_values = True


class HealthResponse(BaseModel):
    """
    Standard health check response model
    Used by all services for health endpoints
    """
    status: str = Field(..., description="Service health status")
    service: str = Field(..., description="Service name")
    timestamp: float = Field(..., description="Unix timestamp")
    details: Optional[Dict] = Field(None, description="Additional health details")
    
    class Config:
        use_enum_values = True