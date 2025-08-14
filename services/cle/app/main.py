# core-logic-engine/main.py
"""
CashAppAgent Core Logic Engine (CLE)
The "brain" of the autonomous financial processing system
Implements the cascading payment matching algorithm
"""

import asyncio
import time
from typing import List, Dict, Optional
from decimal import Decimal
from datetime import datetime, timezone
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel
import httpx
import asyncpg

# Import shared utilities
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '../../..'))

from shared.models import (
    PaymentTransaction, Invoice, MatchResult, DocumentParsingResult, 
    CommunicationRequest, TransactionStatus, DiscrepancyCode
)
from shared.request_models import ProcessTransactionRequest, ProcessTransactionResponse
from shared.logging_config import get_logger, set_correlation_id, get_correlation_id
from shared.exception import ProcessingError, ERPIntegrationError, DocumentIntelligenceError
from shared.database import get_db_manager
from shared.monitoring import MetricsCollector, BusinessMetricsTracker
from shared.health import HealthChecker, check_database_connection, check_http_service
from shared.auth import auth_middleware, require_transaction_access, AuthenticatedHttpClient
from shared.security import (
    setup_security_middleware, get_current_user, require_permission,
    validate_financial_amount, validate_currency_code
)
import os


# Initialize logging
logger = get_logger("core-logic-engine")

# Minimal config adapter for security middleware
class EnvConfig:
    def get(self, key: str, default=None):
        return os.getenv(key, default)

config_manager = EnvConfig()

class CLEConfig:
    """Core Logic Engine Configuration"""
    
    # Service endpoints
    DOCUMENT_INTELLIGENCE_URL = os.getenv('DIM_BASE_URL', 'http://dim:8002')
    ERP_INTEGRATION_URL = os.getenv('EIC_BASE_URL', 'http://eic:8003')
    COMMUNICATION_URL = os.getenv('CM_BASE_URL', 'http://cm:8004')
    
    # Database
    DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://cashapp_user:password@localhost:5432/cashapp')
    
    # Processing limits
    MAX_PROCESSING_TIME_SECONDS = int(os.getenv('MAX_PROCESSING_TIME', '300'))  # 5 minutes
    MAX_CONCURRENT_TRANSACTIONS = int(os.getenv('MAX_CONCURRENT', '10'))
    
    # Business rules
    MIN_MATCH_CONFIDENCE = float(os.getenv('MIN_MATCH_CONFIDENCE', '0.8'))
    AUTO_APPLY_THRESHOLD = Decimal(os.getenv('AUTO_APPLY_THRESHOLD', '10000'))  # €10k limit


config = CLEConfig()

# Global clients and managers
auth_http_client = AuthenticatedHttpClient("cle")
processing_semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_TRANSACTIONS)
health_checker = HealthChecker("core-logic-engine")
metrics_collector = MetricsCollector("cle")
business_tracker = BusinessMetricsTracker(metrics_collector)


# =============================================================================
# CORE MATCHING ALGORITHM
# =============================================================================

class PaymentMatchingEngine:
    """
    Core payment matching algorithm implementation
    Implements the cascading logic from the specification
    """
    
    def __init__(self):
        self.db = None
    
    async def initialize(self):
        """Initialize database connection"""
        self.db = await get_db_manager()
    
    async def match_payment_to_invoices(self, payment: PaymentTransaction) -> MatchResult:
        """
        Core matching algorithm - implements cascading matching logic
        
        Args:
            payment: PaymentTransaction to process
            
        Returns:
            MatchResult with matching outcome
        """
        start_time = time.time()
        correlation_id = set_correlation_id()
        
        logger.info(f"Starting payment matching", extra={
            'transaction_id': payment.transaction_id,
            'amount': float(payment.amount),
            'currency': payment.currency,
            'correlation_id': correlation_id
        })
        
        try:
            # Step 1: Remittance Analysis
            potential_invoice_ids = await self._analyze_remittance_data(payment)
            
            if not potential_invoice_ids:
                logger.warning("No invoice IDs found in remittance analysis", extra={
                    'transaction_id': payment.transaction_id
                })
                return await self._create_unmatched_result(payment, "No invoice references found")
            
            # Step 2: ERP Data Fetch
            invoices = await self._fetch_invoices_from_erp(potential_invoice_ids, payment.currency)
            
            if not invoices:
                logger.warning("No valid invoices found in ERP", extra={
                    'transaction_id': payment.transaction_id,
                    'potential_invoices': potential_invoice_ids
                })
                return await self._create_unmatched_result(payment, "No valid open invoices found")
            
            # Step 3: Matching Logic Cascade
            match_result = await self._execute_matching_cascade(payment, invoices)
            
            # Step 4: Action Dispatch
            await self._dispatch_actions(match_result, payment)
            
            # Step 5: Persist Results
            await self._persist_match_result(match_result)
            
            processing_time = (time.time() - start_time) * 1000  # Convert to milliseconds
            match_result.processing_time_ms = int(processing_time)
            
            # Track business metrics
            business_tracker.track_transaction_processed(
                match_result.transaction_id,
                float(payment.amount),
                payment.currency,
                int(processing_time),
                match_result.status.value
            )
            
            logger.info("Payment matching completed", extra={
                'transaction_id': payment.transaction_id,
                'status': match_result.status,
                'processing_time_ms': processing_time,
                'matched_invoices': len(match_result.matched_pairs)
            })
            
            return match_result
            
        except Exception as e:
            processing_time = (time.time() - start_time) * 1000
            logger.error("Payment matching failed", extra={
                'transaction_id': payment.transaction_id,
                'error': str(e),
                'processing_time_ms': processing_time
            })
            
            # Track error metrics
            business_tracker.track_transaction_processed(
                payment.transaction_id,
                float(payment.amount),
                payment.currency,
                int(processing_time),
                "error"
            )
            
            return await self._create_error_result(payment, str(e))
    
    async def _analyze_remittance_data(self, payment: PaymentTransaction) -> List[str]:
        """
        Analyze remittance data to extract potential invoice IDs
        
        Args:
            payment: Payment transaction to analyze
            
        Returns:
            List of potential invoice IDs
        """
        invoice_ids = []
        
        # Direct parsing from structured remittance data
        if payment.raw_remittance_data:
            invoice_ids.extend(self._extract_invoice_ids_from_text(payment.raw_remittance_data))
        
        # Document Intelligence processing for unstructured data
        if payment.associated_document_uris:
            try:
                dim_result = await self._call_document_intelligence(payment.associated_document_uris)
                invoice_ids.extend(dim_result.invoice_ids)
                
                # Update customer identifier if found
                if dim_result.customer_identifiers:
                    payment.customer_identifier = dim_result.customer_identifiers[0]
                    
            except DocumentIntelligenceError as e:
                logger.warning("Document intelligence processing failed", extra={
                    'transaction_id': payment.transaction_id,
                    'error': str(e)
                })
        
        # Remove duplicates and validate format
        unique_invoice_ids = list(set(invoice_ids))
        validated_ids = [id for id in unique_invoice_ids if self._validate_invoice_id_format(id)]
        
        logger.info("Remittance analysis completed", extra={
            'transaction_id': payment.transaction_id,
            'extracted_ids': len(validated_ids),
            'ids': validated_ids
        })
        
        return validated_ids
    
    def _extract_invoice_ids_from_text(self, text: str) -> List[str]:
        """Extract invoice IDs from structured remittance text"""
        import re
        
        # Common invoice ID patterns
        patterns = [
            r'INV[-_]?(\d{4,8})',  # INV-12345, INV_12345, INV12345
            r'INVOICE[-_]?(\d{4,8})',  # INVOICE-12345
            r'PO[-_]?(\d{4,8})',   # PO-12345 (Purchase Order references)
            r'REF[-_]?(\d{4,8})',  # REF-12345 (General references)
        ]
        
        invoice_ids = []
        text_upper = text.upper()
        
        for pattern in patterns:
            matches = re.findall(pattern, text_upper)
            for match in matches:
                # Reconstruct full invoice ID
                if 'INV' in pattern:
                    invoice_ids.append(f"INV-{match}")
                elif 'PO' in pattern:
                    invoice_ids.append(f"PO-{match}")
                else:
                    invoice_ids.append(f"REF-{match}")
        
        return invoice_ids
    
    def _validate_invoice_id_format(self, invoice_id: str) -> bool:
        """Validate invoice ID format"""
        import re
        
        # Basic validation - alphanumeric with hyphens/underscores, 4-20 chars
        pattern = r'^[A-Z0-9\-_]{4,20}$'
        return bool(re.match(pattern, invoice_id.upper()))
    
    async def _call_document_intelligence(self, document_uris: List[str]) -> DocumentParsingResult:
        """
        Call Document Intelligence Module for document parsing
        
        Args:
            document_uris: List of document URIs to process
            
        Returns:
            DocumentParsingResult with extracted data
        """
        try:
            response = await auth_http_client.request(
                "POST",
                f"{config.DOCUMENT_INTELLIGENCE_URL}/api/v1/parse_document",
                json={"document_uris": document_uris},
                headers={"X-Correlation-ID": get_correlation_id()}
            )
            response.raise_for_status()
            
            data = response.json()
            return DocumentParsingResult(**data)
            
        except httpx.RequestError as e:
            raise DocumentIntelligenceError(f"DIM service unavailable: {e}")
        except httpx.HTTPStatusError as e:
            raise DocumentIntelligenceError(f"DIM processing failed: {e.response.text}")
    
    async def _fetch_invoices_from_erp(self, invoice_ids: List[str], currency: str) -> List[Invoice]:
        """
        Fetch invoice data from ERP Integration Connectors
        
        Args:
            invoice_ids: List of invoice IDs to fetch
            currency: Expected currency for filtering
            
        Returns:
            List of valid, open invoices
        """
        try:
            response = await auth_http_client.request(
                "POST",
                f"{config.ERP_INTEGRATION_URL}/api/v1/get_invoices",
                json={
                    "invoice_ids": invoice_ids,
                    "currency_filter": currency,
                    "status_filter": ["open", "overdue"]  # Only fetch open invoices
                },
                headers={"X-Correlation-ID": get_correlation_id()}
            )
            response.raise_for_status()
            
            data = response.json()
            invoices = [Invoice(**invoice_data) for invoice_data in data.get("invoices", [])]
            
            # Filter for valid invoices (open, correct currency, positive amount)
            valid_invoices = [
                inv for inv in invoices 
                if inv.currency == currency 
                and inv.amount_due > 0 
                and inv.status in ['open', 'overdue']
            ]
            
            logger.info("ERP invoice fetch completed", extra={
                'requested_ids': len(invoice_ids),
                'found_invoices': len(invoices),
                'valid_invoices': len(valid_invoices)
            })
            
            return valid_invoices
            
        except httpx.RequestError as e:
            raise ERPIntegrationError(f"ERP service unavailable: {e}")
        except httpx.HTTPStatusError as e:
            raise ERPIntegrationError(f"ERP invoice fetch failed: {e.response.text}")
    
    async def _execute_matching_cascade(self, payment: PaymentTransaction, invoices: List[Invoice]) -> MatchResult:
        """
        Execute the cascading matching logic from specification
        
        Args:
            payment: Payment to match
            invoices: List of valid invoices
            
        Returns:
            MatchResult with matching outcome
        """
        # Sort invoices by due date (oldest first) for sequential matching
        sorted_invoices = sorted(invoices, key=lambda inv: inv.due_date or datetime.min)
        
        # Calculate total amount due
        total_amount_due = sum(inv.amount_due for inv in sorted_invoices)
        
        logger.info("Executing matching cascade", extra={
            'payment_amount': float(payment.amount),
            'total_invoice_amount': float(total_amount_due),
            'invoice_count': len(sorted_invoices)
        })
        
        # 1. Attempt Perfect 1:Many Match
        if total_amount_due == payment.amount:
            logger.info("Perfect match found - closing all invoices")
            return await self._create_perfect_match_result(payment, sorted_invoices)
        
        # 2. Attempt Sequential Match (Short Payment)
        elif total_amount_due > payment.amount:
            logger.info("Short payment detected - applying sequentially")
            return await self._create_sequential_match_result(payment, sorted_invoices)
        
        # 3. Handle Overpayment  
        else:  # total_amount_due < payment.amount
            logger.info("Overpayment detected - closing all invoices with excess")
            return await self._create_overpayment_match_result(payment, sorted_invoices)
    
    async def _create_perfect_match_result(self, payment: PaymentTransaction, invoices: List[Invoice]) -> MatchResult:
        """Create result for perfect amount match"""
        matched_pairs = {inv.invoice_id: inv.amount_due for inv in invoices}
        
        return MatchResult(
            transaction_id=payment.transaction_id,
            status=TransactionStatus.MATCHED,
            matched_pairs=matched_pairs,
            unapplied_amount=Decimal('0'),
            discrepancy_code=None,
            log_entry=f"Perfect match: {len(invoices)} invoices totaling {payment.amount} {payment.currency}",
            confidence_score=1.0,
            requires_human_review=False
        )
    
    async def _create_sequential_match_result(self, payment: PaymentTransaction, invoices: List[Invoice]) -> MatchResult:
        """Create result for short payment sequential matching"""
        matched_pairs = {}
        remaining_amount = payment.amount
        
        for invoice in invoices:
            if remaining_amount <= 0:
                break
                
            if remaining_amount >= invoice.amount_due:
                # Fully pay this invoice
                matched_pairs[invoice.invoice_id] = invoice.amount_due
                remaining_amount -= invoice.amount_due
            else:
                # Partially pay this invoice
                matched_pairs[invoice.invoice_id] = remaining_amount
                remaining_amount = Decimal('0')
        
        return MatchResult(
            transaction_id=payment.transaction_id,
            status=TransactionStatus.PARTIALLY_MATCHED,
            matched_pairs=matched_pairs,
            unapplied_amount=Decimal('0'),
            discrepancy_code=DiscrepancyCode.SHORT_PAYMENT,
            log_entry=f"Short payment: {len(matched_pairs)} invoices matched, {len(invoices) - len(matched_pairs)} remaining open",
            confidence_score=0.95,
            requires_human_review=payment.amount > config.AUTO_APPLY_THRESHOLD
        )
    
    async def _create_overpayment_match_result(self, payment: PaymentTransaction, invoices: List[Invoice]) -> MatchResult:
        """Create result for overpayment matching"""
        matched_pairs = {inv.invoice_id: inv.amount_due for inv in invoices}
        total_applied = sum(matched_pairs.values())
        unapplied_amount = payment.amount - total_applied
        
        return MatchResult(
            transaction_id=payment.transaction_id,
            status=TransactionStatus.MATCHED,
            matched_pairs=matched_pairs,
            unapplied_amount=unapplied_amount,
            discrepancy_code=DiscrepancyCode.OVER_PAYMENT,
            log_entry=f"Overpayment: {len(invoices)} invoices closed, {unapplied_amount} {payment.currency} excess",
            confidence_score=0.90,
            requires_human_review=unapplied_amount > config.AUTO_APPLY_THRESHOLD / 10  # €1k threshold for review
        )
    
    async def _create_unmatched_result(self, payment: PaymentTransaction, reason: str) -> MatchResult:
        """Create result for unmatched payment"""
        return MatchResult(
            transaction_id=payment.transaction_id,
            status=TransactionStatus.UNMATCHED,
            matched_pairs={},
            unapplied_amount=payment.amount,
            discrepancy_code=DiscrepancyCode.INVALID_INVOICE,
            log_entry=f"Unmatched: {reason}",
            confidence_score=0.0,
            requires_human_review=True
        )
    
    async def _create_error_result(self, payment: PaymentTransaction, error: str) -> MatchResult:
        """Create result for processing error"""
        return MatchResult(
            transaction_id=payment.transaction_id,
            status=TransactionStatus.ERROR,
            matched_pairs={},
            unapplied_amount=payment.amount,
            discrepancy_code=None,
            log_entry=f"Processing error: {error}",
            confidence_score=0.0,
            requires_human_review=True
        )
    
    async def _dispatch_actions(self, match_result: MatchResult, payment: PaymentTransaction):
        """
        Dispatch actions based on match result
        
        Args:
            match_result: Result of matching process
            payment: Original payment transaction
        """
        actions = []
        
        # ERP Updates for successful matches
        if match_result.status in [TransactionStatus.MATCHED, TransactionStatus.PARTIALLY_MATCHED]:
            if match_result.matched_pairs:
                actions.append(self._update_erp_system(match_result))
        
        # Communications for discrepancies
        if match_result.discrepancy_code:
            actions.append(self._send_discrepancy_communication(match_result, payment))
        
        # Internal alerts for human review
        if match_result.requires_human_review:
            actions.append(self._send_internal_alert(match_result, payment))
        
        # Execute actions concurrently
        if actions:
            await asyncio.gather(*actions, return_exceptions=True)
    
    async def _update_erp_system(self, match_result: MatchResult):
        """Update ERP system with payment applications"""
        try:
            response = await auth_http_client.request(
                "POST",
                f"{config.ERP_INTEGRATION_URL}/api/v1/post_application",
                json={
                    "transaction_id": match_result.transaction_id,
                    "matched_pairs": {k: float(v) for k, v in match_result.matched_pairs.items()},
                    "idempotency_key": match_result.transaction_id
                },
                headers={"X-Correlation-ID": get_correlation_id()}
            )
            response.raise_for_status()
            
            logger.info("ERP system updated successfully", extra={
                'transaction_id': match_result.transaction_id,
                'invoices_updated': len(match_result.matched_pairs)
            })
            
        except Exception as e:
            logger.error("ERP system update failed", extra={
                'transaction_id': match_result.transaction_id,
                'error': str(e)
            })
            # Don't raise - this is a background action
    
    async def _send_discrepancy_communication(self, match_result: MatchResult, payment: PaymentTransaction):
        """Send communication for payment discrepancies"""
        try:
            template_name = {
                DiscrepancyCode.SHORT_PAYMENT: "short_payment",
                DiscrepancyCode.OVER_PAYMENT: "over_payment",
                DiscrepancyCode.CURRENCY_MISMATCH: "currency_mismatch"
            }.get(match_result.discrepancy_code, "general_discrepancy")
            
            comm_request = CommunicationRequest(
                request_type="email",
                recipient=payment.customer_identifier or "unknown",
                template_name=template_name,
                template_data={
                    "transaction_id": payment.transaction_id,
                    "payment_amount": float(payment.amount),
                    "currency": payment.currency,
                    "matched_invoices": [k for k in match_result.matched_pairs.keys()],
                    "unapplied_amount": float(match_result.unapplied_amount)
                },
                transaction_id=payment.transaction_id
            )
            
            response = await auth_http_client.request(
                "POST",
                f"{config.COMMUNICATION_URL}/api/v1/send_clarification_email",
                json=comm_request.dict(),
                headers={"X-Correlation-ID": get_correlation_id()}
            )
            response.raise_for_status()
            
            logger.info("Discrepancy communication sent", extra={
                'transaction_id': match_result.transaction_id,
                'template': template_name
            })
            
        except Exception as e:
            logger.error("Discrepancy communication failed", extra={
                'transaction_id': match_result.transaction_id,
                'error': str(e)
            })
    
    async def _send_internal_alert(self, match_result: MatchResult, payment: PaymentTransaction):
        """Send internal alert for human review"""
        try:
            comm_request = CommunicationRequest(
                request_type="slack",
                recipient="#cashapp-alerts",
                template_name="human_review_required",
                template_data={
                    "transaction_id": payment.transaction_id,
                    "amount": float(payment.amount),
                    "currency": payment.currency,
                    "status": match_result.status.value,
                    "reason": match_result.log_entry,
                    "confidence": match_result.confidence_score
                },
                priority="high",
                transaction_id=payment.transaction_id
            )
            
            response = await auth_http_client.request(
                "POST",
                f"{config.COMMUNICATION_URL}/api/v1/send_internal_alert",
                json=comm_request.dict(),
                headers={"X-Correlation-ID": get_correlation_id()}
            )
            response.raise_for_status()
            
            logger.info("Internal alert sent", extra={
                'transaction_id': match_result.transaction_id
            })
            
        except Exception as e:
            logger.error("Internal alert failed", extra={
                'transaction_id': match_result.transaction_id,
                'error': str(e)
            })
    
    async def _persist_match_result(self, match_result: MatchResult):
        """Persist match result to database"""
        try:
            # Insert match result
            insert_query = """
                INSERT INTO match_results (
                    transaction_id, status, unapplied_amount, discrepancy_code,
                    log_entry, confidence_score, processing_time_ms, requires_human_review
                ) VALUES (
                    (SELECT id FROM payment_transactions WHERE transaction_id = $1),
                    $2, $3, $4, $5, $6, $7, $8
                ) RETURNING id
            """
            
            result = await self.db.execute_query(
                insert_query,
                match_result.transaction_id,
                match_result.status.value,
                match_result.unapplied_amount,
                match_result.discrepancy_code.value if match_result.discrepancy_code else None,
                match_result.log_entry,
                match_result.confidence_score,
                match_result.processing_time_ms,
                match_result.requires_human_review
            )
            
            if result:
                match_result_id = result[0]['id']
                
                # Insert invoice matches
                if match_result.matched_pairs:
                    for invoice_id, amount in match_result.matched_pairs.items():
                        await self.db.execute_command(
                            """
                            INSERT INTO invoice_payment_matches (
                                match_result_id, invoice_id, amount_applied, external_invoice_id
                            ) VALUES (
                                $1,
                                (SELECT id FROM invoices WHERE invoice_id = $2 LIMIT 1),
                                $3, $2
                            )
                            """,
                            match_result_id, invoice_id, amount
                        )
                
                logger.info("Match result persisted", extra={
                    'transaction_id': match_result.transaction_id,
                    'match_result_id': str(match_result_id)
                })
        
        except Exception as e:
            logger.error("Failed to persist match result", extra={
                'transaction_id': match_result.transaction_id,
                'error': str(e)
            })
            # Don't raise - this is a background operation


# Global matching engine instance
matching_engine = PaymentMatchingEngine()


# =============================================================================
# FASTAPI APPLICATION SETUP
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management"""
    
    # Startup
    logger.info("Starting Core Logic Engine")
    
    # Initialize database
    await matching_engine.initialize()
    
    # Setup health checks
    health_checker.add_check("database", lambda: check_database_connection(config.DATABASE_URL))
    health_checker.add_check("dim_service", lambda: check_http_service(f"{config.DOCUMENT_INTELLIGENCE_URL}/health"))
    health_checker.add_check("eic_service", lambda: check_http_service(f"{config.ERP_INTEGRATION_URL}/health"))
    health_checker.add_check("cm_service", lambda: check_http_service(f"{config.COMMUNICATION_URL}/health"))
    
    logger.info("Core Logic Engine startup complete")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Core Logic Engine")
    await auth_http_client.close()
    logger.info("Core Logic Engine shutdown complete")


# Create FastAPI application
app = FastAPI(
    title="CashAppAgent Core Logic Engine",
    description="The brain of the autonomous financial processing system",
    version="1.0.0",
    lifespan=lifespan
)

# Add middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup security middleware
security_middleware = setup_security_middleware(app, config_manager)
app.middleware("http")(auth_middleware)


# =============================================================================
# API ENDPOINTS
# =============================================================================

# Request/Response models are now imported from shared.request_models


@app.post("/api/v1/process_transaction", response_model=ProcessTransactionResponse)
@validate_financial_amount("amount")
@validate_currency_code("currency")
async def process_transaction(
    request: ProcessTransactionRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict = Depends(require_permission("process_transactions"))
) -> ProcessTransactionResponse:
    """
    Process a payment transaction through the matching engine
    
    This is the primary endpoint for the CLE service
    """
    
    # Acquire processing semaphore to limit concurrency
    async with processing_semaphore:
        correlation_id = set_correlation_id()
        
        logger.info("Received transaction processing request", extra={
            'transaction_id': request.payment_transaction.transaction_id,
            'correlation_id': correlation_id
        })
        
        try:
            # Execute the core matching algorithm
            match_result = await matching_engine.match_payment_to_invoices(request.payment_transaction)
            
            # Generate response summary and next steps
            processing_summary = f"Transaction {request.payment_transaction.transaction_id} processed with status: {match_result.status.value}"
            
            next_steps = []
            if match_result.status == TransactionStatus.MATCHED:
                if match_result.discrepancy_code:
                    next_steps.append("Customer notification sent regarding discrepancy")
                next_steps.append("ERP system updated with payment applications")
                
            elif match_result.status == TransactionStatus.PARTIALLY_MATCHED:
                next_steps.append("Partial payment applied to invoices")
                next_steps.append("Customer notification sent regarding short payment")
                
            elif match_result.requires_human_review:
                next_steps.append("Human review required - alert sent to operations team")
                
            return ProcessTransactionResponse(
                match_result=match_result,
                processing_summary=processing_summary,
                next_steps=next_steps
            )
            
        except Exception as e:
            logger.error("Transaction processing failed", extra={
                'transaction_id': request.payment_transaction.transaction_id,
                'error': str(e)
            })
            raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return await health_checker.check_health()


@app.get("/metrics")
async def metrics():
    """Metrics endpoint"""
    return metrics_collector.get_metrics_summary()


@app.get("/api/v1/status")
async def get_service_status():
    """Get detailed service status"""
    return {
        "service": "core-logic-engine",
        "version": "1.0.0",
        "status": "running",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "max_concurrent_transactions": config.MAX_CONCURRENT_TRANSACTIONS,
            "max_processing_time_seconds": config.MAX_PROCESSING_TIME_SECONDS,
            "min_match_confidence": config.MIN_MATCH_CONFIDENCE,
            "auto_apply_threshold": float(config.AUTO_APPLY_THRESHOLD)
        }
    }


# =============================================================================
# AUTHENTICATION ENDPOINTS
# =============================================================================

@app.post("/auth/create_api_key")
async def create_api_key(
    request: Dict,
    current_user: Dict = Depends(require_permission("admin"))
):
    """Create new API key for client or service"""
    from shared.security import create_service_api_key
    
    try:
        key_info = await create_service_api_key(
            client_id=request['client_id'],
            service_name=request['service_name'],
            config=config_manager
        )
        
        logger.info(f"API key created for {request['client_id']}/{request['service_name']}")
        
        return {
            "success": True,
            "key_id": key_info['key_id'],
            "api_key": key_info['api_key'],
            "expires_at": key_info['expires_at'],
            "permissions": key_info['permissions']
        }
        
    except Exception as e:
        logger.error(f"Failed to create API key: {e}")
        raise HTTPException(status_code=500, detail="Failed to create API key")


@app.get("/auth/validate_token")
async def validate_token(current_user: Dict = Depends(get_current_user)):
    """Validate current authentication token"""
    return {
        "valid": True,
        "auth_method": current_user.get('auth_method'),
        "client_id": current_user.get('client_id'),
        "permissions": current_user.get('permissions', [])
    }


# =============================================================================
# STARTUP
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_config=None,  # Use our custom logging
        access_log=False  # Disable uvicorn access logs (we have our own)
    )
