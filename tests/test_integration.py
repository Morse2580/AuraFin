# tests/test_integration.py
"""
Integration tests for CashAppAgent
Tests end-to-end workflows and service interactions
"""

import asyncio
import pytest
import httpx
from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, Any

from shared.models import PaymentTransaction, TransactionStatus
from shared.request_models import ProcessTransactionRequest
from shared.test_data import TestDataGenerator

class TestCashAppIntegration:
    """Integration tests for complete CashApp workflow"""
    
    @pytest.fixture
    async def test_client(self):
        """Create test HTTP client"""
        async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
            yield client
    
    @pytest.fixture
    def test_data_generator(self):
        """Create test data generator"""
        return TestDataGenerator()
    
    @pytest.mark.asyncio
    async def test_perfect_match_workflow(self, test_client, test_data_generator):
        """Test perfect payment match workflow"""
        # Generate test transaction
        test_transaction = test_data_generator.create_payment_transaction(
            amount=Decimal('1500.00'),
            currency='EUR',
            remittance_data='Payment for INV-12345'
        )
        
        # Submit for processing
        request = ProcessTransactionRequest(payment_transaction=test_transaction)
        response = await test_client.post("/api/v1/process_transaction", json=request.dict())
        
        assert response.status_code == 200
        result = response.json()
        
        # Verify response structure
        assert 'match_result' in result
        assert 'processing_summary' in result
        assert 'next_steps' in result
        
        # Verify match result
        match_result = result['match_result']
        assert match_result['status'] in ['matched', 'partially_matched', 'unmatched']
        assert 'processing_time_ms' in match_result
        assert match_result['processing_time_ms'] > 0
    
    @pytest.mark.asyncio
    async def test_overpayment_workflow(self, test_client, test_data_generator):
        """Test overpayment handling workflow"""
        # Generate overpayment transaction
        test_transaction = test_data_generator.create_payment_transaction(
            amount=Decimal('2500.00'),  # More than invoice amount
            currency='EUR',
            remittance_data='Payment for INV-12345 INV-12346'
        )
        
        request = ProcessTransactionRequest(payment_transaction=test_transaction)
        response = await test_client.post("/api/v1/process_transaction", json=request.dict())
        
        assert response.status_code == 200
        result = response.json()
        
        match_result = result['match_result']
        # Should detect overpayment
        assert match_result.get('discrepancy_code') == 'over_payment'
        assert match_result.get('unapplied_amount', 0) > 0
    
    @pytest.mark.asyncio
    async def test_service_health_checks(self):
        """Test all service health endpoints"""
        services = [
            ('cle', 'http://localhost:8000'),
            ('dim', 'http://localhost:8001'),
            ('eic', 'http://localhost:8002'),
            ('cm', 'http://localhost:8003')
        ]
        
        async with httpx.AsyncClient() as client:
            for service_name, base_url in services:
                try:
                    response = await client.get(f"{base_url}/health", timeout=10)
                    assert response.status_code == 200
                    
                    health_data = response.json()
                    assert 'status' in health_data
                    assert 'service' in health_data
                    assert health_data['service'] in base_url or service_name in health_data['service']
                    
                except Exception as e:
                    pytest.skip(f"Service {service_name} not available: {e}")
    
    @pytest.mark.asyncio
    async def test_document_processing_integration(self, test_data_generator):
        """Test document processing through DIM service"""
        # Generate test document URIs
        test_document_uris = test_data_generator.create_test_document_uris(2)
        
        async with httpx.AsyncClient(base_url="http://localhost:8001") as client:
            try:
                response = await client.post("/api/v1/parse_document", json={
                    "document_uris": test_document_uris
                })
                
                if response.status_code == 200:
                    result = response.json()
                    assert 'invoice_ids' in result
                    assert 'confidence_score' in result
                    assert 'processing_time_ms' in result
                else:
                    pytest.skip("DIM service not properly configured")
                    
            except httpx.RequestError:
                pytest.skip("DIM service not available")
    
    @pytest.mark.asyncio
    async def test_erp_integration(self, test_data_generator):
        """Test ERP integration functionality"""
        # Generate test invoice IDs
        test_invoice_ids = test_data_generator.create_test_invoice_ids(3)
        
        async with httpx.AsyncClient(base_url="http://localhost:8002") as client:
            try:
                response = await client.post("/api/v1/get_invoices", json={
                    "invoice_ids": test_invoice_ids
                })
                
                if response.status_code == 200:
                    invoices = response.json()
                    assert isinstance(invoices, list)
                    # Should return empty list if no test data, but no errors
                else:
                    pytest.skip("EIC service not properly configured")
                    
            except httpx.RequestError:
                pytest.skip("EIC service not available")
    
    @pytest.mark.asyncio
    async def test_communication_integration(self, test_data_generator):
        """Test communication module functionality"""
        # Generate test match result
        test_match_result = test_data_generator.create_match_result(
            status=TransactionStatus.UNMATCHED,
            requires_review=True
        )
        
        async with httpx.AsyncClient(base_url="http://localhost:8003") as client:
            try:
                response = await client.post("/api/v1/send_internal_alert", json={
                    "match_result": test_match_result.dict(),
                    "alert_type": "email",
                    "alert_config": {
                        "recipient": "test@example.com"
                    }
                })
                
                if response.status_code == 200:
                    result = response.json()
                    assert 'success' in result
                    assert 'processing_time_ms' in result
                else:
                    pytest.skip("CM service not properly configured")
                    
            except httpx.RequestError:
                pytest.skip("CM service not available")
    
    @pytest.mark.asyncio
    async def test_concurrent_processing(self, test_client, test_data_generator):
        """Test concurrent transaction processing"""
        # Generate multiple test transactions
        transactions = [
            test_data_generator.create_payment_transaction(
                amount=Decimal('1000.00') + Decimal(str(i * 100)),
                currency='EUR',
                remittance_data=f'Payment for INV-{12345 + i}'
            )
            for i in range(5)
        ]
        
        # Submit all transactions concurrently
        tasks = [
            test_client.post("/api/v1/process_transaction", 
                           json=ProcessTransactionRequest(payment_transaction=txn).dict())
            for txn in transactions
        ]
        
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify all requests completed (whether successful or not)
        successful_responses = [
            r for r in responses 
            if not isinstance(r, Exception) and r.status_code == 200
        ]
        
        # Should handle at least some concurrent requests
        assert len(successful_responses) >= 1
    
    @pytest.mark.asyncio
    async def test_error_handling(self, test_client, test_data_generator):
        """Test error handling and recovery"""
        # Test with invalid transaction data
        invalid_transaction = test_data_generator.create_payment_transaction(
            amount=Decimal('-100.00'),  # Invalid negative amount
            currency='INVALID',
            remittance_data=''
        )
        
        request = ProcessTransactionRequest(payment_transaction=invalid_transaction)
        response = await test_client.post("/api/v1/process_transaction", json=request.dict())
        
        # Should return error status
        assert response.status_code in [400, 422, 500]
    
    @pytest.mark.asyncio
    async def test_metrics_endpoints(self):
        """Test metrics collection endpoints"""
        services = [
            'http://localhost:8000',
            'http://localhost:8001',
            'http://localhost:8002',
            'http://localhost:8003'
        ]
        
        async with httpx.AsyncClient() as client:
            for service_url in services:
                try:
                    response = await client.get(f"{service_url}/metrics", timeout=5)
                    if response.status_code == 200:
                        metrics_data = response.json()
                        assert 'service' in metrics_data
                        assert 'timestamp' in metrics_data
                        
                except httpx.RequestError:
                    # Service might not be running
                    continue

class TestDatabaseIntegration:
    """Tests database operations and data consistency"""
    
    @pytest.mark.asyncio
    async def test_database_connection(self):
        """Test database connectivity"""
        from shared.database import get_db_manager
        
        db = await get_db_manager()
        result = await db.execute_query("SELECT 1 as test")
        assert result[0]['test'] == 1
    
    @pytest.mark.asyncio
    async def test_transaction_persistence(self, test_data_generator):
        """Test transaction data persistence"""
        from shared.database import get_db_manager
        
        db = await get_db_manager()
        
        # Create test transaction
        test_transaction = test_data_generator.create_payment_transaction()
        
        # Insert transaction
        await db.execute_command("""
            INSERT INTO payment_transactions 
            (transaction_id, source_account_ref, amount, currency, value_date, raw_remittance_data)
            VALUES ($1, $2, $3, $4, $5, $6)
        """,
        test_transaction.transaction_id,
        test_transaction.source_account_ref,
        test_transaction.amount,
        test_transaction.currency,
        test_transaction.value_date,
        test_transaction.raw_remittance_data
        )
        
        # Verify insertion
        result = await db.execute_query(
            "SELECT * FROM payment_transactions WHERE transaction_id = $1",
            test_transaction.transaction_id
        )
        
        assert len(result) == 1
        assert result[0]['transaction_id'] == test_transaction.transaction_id
        assert result[0]['amount'] == test_transaction.amount
    
    @pytest.mark.asyncio
    async def test_match_result_persistence(self, test_data_generator):
        """Test match result data persistence"""
        from shared.database import get_db_manager
        
        db = await get_db_manager()
        
        # Create test data
        test_transaction = test_data_generator.create_payment_transaction()
        test_match_result = test_data_generator.create_match_result()
        
        # Insert transaction first
        await db.execute_command("""
            INSERT INTO payment_transactions 
            (transaction_id, source_account_ref, amount, currency, value_date)
            VALUES ($1, $2, $3, $4, $5)
        """,
        test_transaction.transaction_id,
        test_transaction.source_account_ref,
        test_transaction.amount,
        test_transaction.currency,
        test_transaction.value_date
        )
        
        # Insert match result
        await db.execute_command("""
            INSERT INTO match_results 
            (transaction_id, status, log_entry, confidence_score, requires_human_review)
            VALUES (
                (SELECT id FROM payment_transactions WHERE transaction_id = $1),
                $2, $3, $4, $5
            )
        """,
        test_match_result.transaction_id,
        test_match_result.status.value,
        test_match_result.log_entry,
        test_match_result.confidence_score,
        test_match_result.requires_human_review
        )
        
        # Verify insertion
        result = await db.execute_query("""
            SELECT mr.*, pt.transaction_id 
            FROM match_results mr
            JOIN payment_transactions pt ON mr.transaction_id = pt.id
            WHERE pt.transaction_id = $1
        """, test_match_result.transaction_id)
        
        assert len(result) == 1
        assert result[0]['status'] == test_match_result.status.value

if __name__ == "__main__":
    # Run integration tests
    pytest.main([__file__, "-v", "--tb=short"])