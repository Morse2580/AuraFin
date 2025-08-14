#!/usr/bin/env python3
"""
End-to-End Test Scenarios for CashAppAgent
Tests critical business workflows to validate system readiness
"""

import asyncio
import httpx
import json
import time
import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class TestResult:
    name: str
    success: bool
    duration_ms: int
    details: Dict[str, Any]
    error: Optional[str] = None

class E2ETestRunner:
    """
    Comprehensive E2E test runner for CashAppAgent
    Tests the complete system end-to-end with real data flows
    """
    
    def __init__(self, base_url: str = "http://localhost"):
        self.base_url = base_url
        self.results: List[TestResult] = []
        
        # Service endpoints (using E2E ports)
        self.endpoints = {
            'orchestrator': f"{base_url}:8006",
            'cle': f"{base_url}:8011", 
            'dim': f"{base_url}:8012",
            'eic': f"{base_url}:8013",
            'cm': f"{base_url}:8014",
            'temporal': f"{base_url}:7234"
        }
        
        # Test data
        self.test_client_id = "TEST-CLIENT-001"
        self.test_transaction_counter = 1000
    
    async def run_all_tests(self) -> Dict[str, Any]:
        """
        Run complete E2E test suite
        Returns comprehensive test results
        """
        logger.info("🚀 Starting CashAppAgent E2E Test Suite")
        start_time = time.time()
        
        # Test scenarios in order of complexity
        test_scenarios = [
            self.test_service_health_checks,
            self.test_database_connectivity,
            self.test_perfect_match_workflow,
            self.test_overpayment_workflow, 
            self.test_short_payment_workflow,
            self.test_unmatched_payment_workflow,
            self.test_document_processing,
            self.test_erp_integration,
            self.test_communication_module,
            self.test_concurrent_processing,
            self.test_error_handling,
            self.test_workflow_orchestration
        ]
        
        for scenario in test_scenarios:
            try:
                logger.info(f"Running: {scenario.__name__}")
                await scenario()
            except Exception as e:
                logger.error(f"Test scenario {scenario.__name__} failed: {str(e)}")
                self.results.append(TestResult(
                    name=scenario.__name__,
                    success=False,
                    duration_ms=0,
                    details={},
                    error=str(e)
                ))
        
        total_time = time.time() - start_time
        
        # Compile results
        passed = sum(1 for r in self.results if r.success)
        failed = len(self.results) - passed
        success_rate = (passed / len(self.results)) * 100 if self.results else 0
        
        summary = {
            "total_tests": len(self.results),
            "passed": passed,
            "failed": failed,
            "success_rate": f"{success_rate:.1f}%",
            "total_duration_seconds": round(total_time, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": [
                {
                    "name": r.name,
                    "success": r.success,
                    "duration_ms": r.duration_ms,
                    "error": r.error,
                    "details": r.details
                }
                for r in self.results
            ]
        }
        
        logger.info(f"✅ E2E Tests Complete: {passed}/{len(self.results)} passed ({success_rate:.1f}%)")
        return summary
    
    async def test_service_health_checks(self):
        """Test all service health endpoints"""
        start_time = time.time()
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            health_results = {}
            
            for service, endpoint in self.endpoints.items():
                if service == 'temporal':
                    continue  # Temporal doesn't have standard health endpoint
                    
                try:
                    response = await client.get(f"{endpoint}/health")
                    health_results[service] = {
                        "status_code": response.status_code,
                        "healthy": response.status_code == 200,
                        "response": response.json() if response.status_code == 200 else None
                    }
                except Exception as e:
                    health_results[service] = {
                        "status_code": 0,
                        "healthy": False,
                        "error": str(e)
                    }
            
            all_healthy = all(result["healthy"] for result in health_results.values())
            duration_ms = int((time.time() - start_time) * 1000)
            
            self.results.append(TestResult(
                name="service_health_checks",
                success=all_healthy,
                duration_ms=duration_ms,
                details=health_results,
                error=None if all_healthy else "One or more services unhealthy"
            ))
    
    async def test_database_connectivity(self):
        """Test database connectivity through services"""
        start_time = time.time()
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                # Test through CLE service database operations
                response = await client.get(f"{self.endpoints['cle']}/api/v1/status")
                
                success = response.status_code == 200
                duration_ms = int((time.time() - start_time) * 1000)
                
                self.results.append(TestResult(
                    name="database_connectivity",
                    success=success,
                    duration_ms=duration_ms,
                    details={"status_code": response.status_code, "response": response.json() if success else None},
                    error=None if success else f"Database connection failed: {response.status_code}"
                ))
                
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                self.results.append(TestResult(
                    name="database_connectivity",
                    success=False,
                    duration_ms=duration_ms,
                    details={},
                    error=str(e)
                ))
    
    async def test_perfect_match_workflow(self):
        """Test perfect payment matching workflow"""
        start_time = time.time()
        
        # Create test transaction with perfect match scenario
        transaction = self._create_test_transaction(
            amount=1500.00,
            currency="EUR",
            remittance_data="Payment for INV-12345 - Amount: 1500.00 EUR",
            invoices_to_create=[{
                "invoice_id": "INV-12345",
                "amount": 1500.00,
                "currency": "EUR"
            }]
        )
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                # Start workflow through orchestrator
                response = await client.post(
                    f"{self.endpoints['orchestrator']}/api/v1/workflows/cash-application/start",
                    json=transaction
                )
                
                if response.status_code != 200:
                    raise Exception(f"Workflow start failed: {response.status_code}")
                
                workflow_result = response.json()
                workflow_id = workflow_result.get("workflow_id")
                
                # Monitor workflow completion (with timeout)
                final_result = await self._wait_for_workflow_completion(client, workflow_id, timeout_seconds=60)
                
                success = (
                    final_result.get("status") == "completed" and
                    final_result.get("matching_result", {}).get("status") == "matched"
                )
                
                duration_ms = int((time.time() - start_time) * 1000)
                
                self.results.append(TestResult(
                    name="perfect_match_workflow",
                    success=success,
                    duration_ms=duration_ms,
                    details={
                        "workflow_id": workflow_id,
                        "transaction_id": transaction["id"],
                        "final_result": final_result
                    },
                    error=None if success else f"Workflow failed: {final_result}"
                ))
                
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                self.results.append(TestResult(
                    name="perfect_match_workflow",
                    success=False,
                    duration_ms=duration_ms,
                    details={"transaction": transaction},
                    error=str(e)
                ))
    
    async def test_overpayment_workflow(self):
        """Test overpayment handling workflow"""
        start_time = time.time()
        
        transaction = self._create_test_transaction(
            amount=2500.00,
            currency="EUR", 
            remittance_data="Payment for INV-12346 INV-12347 - Total: 2500.00 EUR",
            invoices_to_create=[
                {"invoice_id": "INV-12346", "amount": 1000.00, "currency": "EUR"},
                {"invoice_id": "INV-12347", "amount": 1200.00, "currency": "EUR"}
            ]
        )
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    f"{self.endpoints['orchestrator']}/api/v1/workflows/cash-application/start",
                    json=transaction
                )
                
                workflow_result = response.json()
                workflow_id = workflow_result.get("workflow_id")
                
                final_result = await self._wait_for_workflow_completion(client, workflow_id, timeout_seconds=60)
                
                # Should detect overpayment
                success = (
                    final_result.get("matching_result", {}).get("discrepancy_code") == "over_payment" or
                    final_result.get("matching_result", {}).get("unapplied_amount", 0) > 0
                )
                
                duration_ms = int((time.time() - start_time) * 1000)
                
                self.results.append(TestResult(
                    name="overpayment_workflow",
                    success=success,
                    duration_ms=duration_ms,
                    details={
                        "workflow_id": workflow_id,
                        "final_result": final_result,
                        "expected_overpayment": 300.00
                    },
                    error=None if success else "Overpayment not detected correctly"
                ))
                
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                self.results.append(TestResult(
                    name="overpayment_workflow",
                    success=False,
                    duration_ms=duration_ms,
                    details={},
                    error=str(e)
                ))
    
    async def test_short_payment_workflow(self):
        """Test short payment handling"""
        start_time = time.time()
        
        transaction = self._create_test_transaction(
            amount=800.00,
            currency="EUR",
            remittance_data="Partial payment for INV-12348 - Amount: 800.00 EUR",
            invoices_to_create=[{
                "invoice_id": "INV-12348",
                "amount": 1000.00,
                "currency": "EUR"
            }]
        )
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    f"{self.endpoints['orchestrator']}/api/v1/workflows/cash-application/start",
                    json=transaction
                )
                
                workflow_result = response.json()
                workflow_id = workflow_result.get("workflow_id")
                
                final_result = await self._wait_for_workflow_completion(client, workflow_id)
                
                success = (
                    final_result.get("matching_result", {}).get("status") == "partially_matched" or
                    final_result.get("matching_result", {}).get("discrepancy_code") == "short_payment"
                )
                
                duration_ms = int((time.time() - start_time) * 1000)
                
                self.results.append(TestResult(
                    name="short_payment_workflow",
                    success=success,
                    duration_ms=duration_ms,
                    details={"workflow_id": workflow_id, "final_result": final_result},
                    error=None if success else "Short payment not detected correctly"
                ))
                
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                self.results.append(TestResult(
                    name="short_payment_workflow",
                    success=False,
                    duration_ms=duration_ms,
                    details={},
                    error=str(e)
                ))
    
    async def test_unmatched_payment_workflow(self):
        """Test unmatched payment handling"""
        start_time = time.time()
        
        transaction = self._create_test_transaction(
            amount=1000.00,
            currency="EUR",
            remittance_data="Payment for UNKNOWN-INVOICE-999",
            invoices_to_create=[]  # No matching invoices
        )
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    f"{self.endpoints['orchestrator']}/api/v1/workflows/cash-application/start",
                    json=transaction
                )
                
                workflow_result = response.json()
                workflow_id = workflow_result.get("workflow_id")
                
                final_result = await self._wait_for_workflow_completion(client, workflow_id)
                
                success = (
                    final_result.get("status") == "manual_review" or
                    final_result.get("matching_result", {}).get("status") == "unmatched"
                )
                
                duration_ms = int((time.time() - start_time) * 1000)
                
                self.results.append(TestResult(
                    name="unmatched_payment_workflow", 
                    success=success,
                    duration_ms=duration_ms,
                    details={"workflow_id": workflow_id, "final_result": final_result},
                    error=None if success else "Unmatched payment not routed to manual review"
                ))
                
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                self.results.append(TestResult(
                    name="unmatched_payment_workflow",
                    success=False,
                    duration_ms=duration_ms,
                    details={},
                    error=str(e)
                ))
    
    async def test_document_processing(self):
        """Test document intelligence processing"""
        start_time = time.time()
        
        # Create test document content
        test_document_content = """
        INVOICE INV-DOC-001
        
        Bill To: Test Company Ltd
        Date: 2024-01-15
        Due Date: 2024-02-15
        
        Description                     Amount
        Professional Services          1,250.00 EUR
        
        Subtotal:                      1,250.00 EUR
        Tax:                           250.00 EUR
        Total:                         1,500.00 EUR
        
        Please reference invoice INV-DOC-001 with your payment.
        """
        
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                response = await client.post(
                    f"{self.endpoints['dim']}/api/v1/documents/extract",
                    json={
                        "document_content": test_document_content,
                        "document_type": "invoice"
                    }
                )
                
                success = response.status_code == 200
                result_data = response.json() if success else {}
                
                # Check if invoice ID was extracted
                if success:
                    invoice_ids = result_data.get("invoice_ids", [])
                    success = "INV-DOC-001" in invoice_ids
                
                duration_ms = int((time.time() - start_time) * 1000)
                
                self.results.append(TestResult(
                    name="document_processing",
                    success=success,
                    duration_ms=duration_ms,
                    details={
                        "status_code": response.status_code,
                        "extracted_data": result_data
                    },
                    error=None if success else "Document processing failed or invoice ID not extracted"
                ))
                
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                self.results.append(TestResult(
                    name="document_processing",
                    success=False,
                    duration_ms=duration_ms,
                    details={},
                    error=str(e)
                ))
    
    async def test_erp_integration(self):
        """Test ERP integration functionality"""
        start_time = time.time()
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                # Test invoice fetch
                response = await client.post(
                    f"{self.endpoints['eic']}/api/v1/invoices/fetch",
                    json={
                        "invoice_ids": ["INV-ERP-001", "INV-ERP-002"],
                        "erp_system": "netsuite"
                    }
                )
                
                success = response.status_code == 200
                result_data = response.json() if success else {}
                
                duration_ms = int((time.time() - start_time) * 1000)
                
                self.results.append(TestResult(
                    name="erp_integration",
                    success=success,
                    duration_ms=duration_ms,
                    details={
                        "status_code": response.status_code,
                        "result": result_data
                    },
                    error=None if success else "ERP integration failed"
                ))
                
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                self.results.append(TestResult(
                    name="erp_integration",
                    success=False,
                    duration_ms=duration_ms,
                    details={},
                    error=str(e)
                ))
    
    async def test_communication_module(self):
        """Test communication module functionality"""
        start_time = time.time()
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                # Test notification sending
                response = await client.post(
                    f"{self.endpoints['cm']}/api/v1/notifications/send",
                    json={
                        "recipient": "test@example.com",
                        "type": "transaction_completed",
                        "data": {
                            "transaction_id": "TXN-TEST-001",
                            "amount": 1000.00,
                            "status": "completed"
                        }
                    }
                )
                
                success = response.status_code == 200
                result_data = response.json() if success else {}
                
                duration_ms = int((time.time() - start_time) * 1000)
                
                self.results.append(TestResult(
                    name="communication_module",
                    success=success,
                    duration_ms=duration_ms,
                    details={
                        "status_code": response.status_code,
                        "result": result_data
                    },
                    error=None if success else "Communication module failed"
                ))
                
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                self.results.append(TestResult(
                    name="communication_module",
                    success=False,
                    duration_ms=duration_ms,
                    details={},
                    error=str(e)
                ))
    
    async def test_concurrent_processing(self):
        """Test concurrent transaction processing"""
        start_time = time.time()
        
        # Create multiple test transactions
        transactions = [
            self._create_test_transaction(
                amount=1000.00 + (i * 100),
                currency="EUR",
                remittance_data=f"Payment for INV-CONCURRENT-{i:03d}",
                invoices_to_create=[{
                    "invoice_id": f"INV-CONCURRENT-{i:03d}",
                    "amount": 1000.00 + (i * 100),
                    "currency": "EUR"
                }]
            )
            for i in range(5)
        ]
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                # Submit all transactions concurrently
                tasks = [
                    client.post(
                        f"{self.endpoints['orchestrator']}/api/v1/workflows/cash-application/start",
                        json=txn
                    )
                    for txn in transactions
                ]
                
                responses = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Count successful submissions
                successful_submissions = sum(
                    1 for r in responses 
                    if not isinstance(r, Exception) and r.status_code == 200
                )
                
                success = successful_submissions >= 3  # At least 60% success rate
                
                duration_ms = int((time.time() - start_time) * 1000)
                
                self.results.append(TestResult(
                    name="concurrent_processing",
                    success=success,
                    duration_ms=duration_ms,
                    details={
                        "total_transactions": len(transactions),
                        "successful_submissions": successful_submissions,
                        "success_rate": f"{(successful_submissions/len(transactions)*100):.1f}%"
                    },
                    error=None if success else f"Only {successful_submissions}/{len(transactions)} transactions processed successfully"
                ))
                
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                self.results.append(TestResult(
                    name="concurrent_processing",
                    success=False,
                    duration_ms=duration_ms,
                    details={},
                    error=str(e)
                ))
    
    async def test_error_handling(self):
        """Test error handling and recovery"""
        start_time = time.time()
        
        # Create invalid transaction
        invalid_transaction = {
            "id": f"TXN-INVALID-{int(time.time())}",
            "amount": -100.00,  # Invalid negative amount
            "currency": "INVALID",
            "payment_date": "invalid-date",
            "reference": "",
            "client_id": self.test_client_id
        }
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(
                    f"{self.endpoints['orchestrator']}/api/v1/workflows/cash-application/start",
                    json=invalid_transaction
                )
                
                # Should return error status but not crash
                success = response.status_code in [400, 422, 500]
                
                duration_ms = int((time.time() - start_time) * 1000)
                
                self.results.append(TestResult(
                    name="error_handling",
                    success=success,
                    duration_ms=duration_ms,
                    details={
                        "status_code": response.status_code,
                        "response": response.json() if response.status_code != 500 else None
                    },
                    error=None if success else "System didn't handle invalid input correctly"
                ))
                
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                self.results.append(TestResult(
                    name="error_handling",
                    success=False,
                    duration_ms=duration_ms,
                    details={},
                    error=str(e)
                ))
    
    async def test_workflow_orchestration(self):
        """Test workflow orchestration functionality"""
        start_time = time.time()
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                # Test workflow stats endpoint
                response = await client.get(f"{self.endpoints['orchestrator']}/api/v1/workflows/stats")
                
                success = response.status_code == 200
                result_data = response.json() if success else {}
                
                duration_ms = int((time.time() - start_time) * 1000)
                
                self.results.append(TestResult(
                    name="workflow_orchestration",
                    success=success,
                    duration_ms=duration_ms,
                    details={
                        "status_code": response.status_code,
                        "stats": result_data
                    },
                    error=None if success else "Workflow orchestration failed"
                ))
                
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                self.results.append(TestResult(
                    name="workflow_orchestration",
                    success=False,
                    duration_ms=duration_ms,
                    details={},
                    error=str(e)
                ))
    
    def _create_test_transaction(self, amount: float, currency: str, remittance_data: str, invoices_to_create: List[Dict] = None) -> Dict[str, Any]:
        """Create test transaction data"""
        transaction_id = f"TXN-E2E-{self.test_transaction_counter}"
        self.test_transaction_counter += 1
        
        return {
            "id": transaction_id,
            "amount": amount,
            "currency": currency,
            "payment_date": datetime.now(timezone.utc).isoformat(),
            "reference": remittance_data,
            "client_id": self.test_client_id,
            "remittance_data": remittance_data,
            "test_invoices": invoices_to_create or []  # For test setup
        }
    
    async def _wait_for_workflow_completion(self, client: httpx.AsyncClient, workflow_id: str, timeout_seconds: int = 30) -> Dict[str, Any]:
        """Wait for workflow to complete and return final result"""
        start_time = time.time()
        
        while time.time() - start_time < timeout_seconds:
            try:
                response = await client.get(f"{self.endpoints['orchestrator']}/api/v1/workflows/{workflow_id}/status")
                
                if response.status_code == 200:
                    status_data = response.json()
                    
                    if status_data.get("status") in ["completed", "failed"]:
                        return status_data.get("result", status_data)
                
                await asyncio.sleep(2)  # Check every 2 seconds
                
            except Exception as e:
                logger.warning(f"Error checking workflow status: {e}")
                await asyncio.sleep(2)
        
        # Timeout
        return {"status": "timeout", "error": f"Workflow {workflow_id} did not complete within {timeout_seconds} seconds"}


async def main():
    """Run E2E tests and save results"""
    runner = E2ETestRunner()
    results = await runner.run_all_tests()
    
    # Save results to file
    results_file = f"e2e_test_results_{int(time.time())}.json"
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n📊 E2E Test Results saved to: {results_file}")
    print(f"📈 Success Rate: {results['success_rate']}")
    print(f"⏱️  Total Duration: {results['total_duration_seconds']} seconds")
    
    # Print summary
    if results['failed'] == 0:
        print("\n🎉 ALL TESTS PASSED! Your system is E2E ready!")
    else:
        print(f"\n⚠️  {results['failed']} tests failed. Check results for details.")
        
        # Print failed tests
        for result in results['results']:
            if not result['success']:
                print(f"❌ {result['name']}: {result['error']}")
    
    return results['failed'] == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)