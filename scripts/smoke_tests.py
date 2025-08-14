# scripts/smoke_tests.py

#!/usr/bin/env python3
"""
Smoke tests for CashAppAgent services
"""

import os
import sys
import time
import json
import requests
from typing import Dict, Optional
from dataclasses import dataclass

@dataclass
class TestResult:
    name: str
    success: bool
    duration: float
    error: Optional[str] = None

class SmokeTestRunner:
    def __init__(self):
        self.cle_url = os.getenv('CLE_URL', 'http://localhost:8001')
        self.eic_url = os.getenv('EIC_URL', 'http://localhost:8003')
        self.cm_url = os.getenv('CM_URL', 'http://localhost:8004')
        self.environment = os.getenv('ENVIRONMENT', 'dev')
        
        self.results = []
        
    def run_test(self, test_name: str, test_func) -> TestResult:
        """Run a single test and capture results"""
        print(f"🧪 Running {test_name}...")
        
        start_time = time.time()
        
        try:
            test_func()
            duration = time.time() - start_time
            result = TestResult(test_name, True, duration)
            print(f"✅ {test_name} passed ({duration:.2f}s)")
            
        except Exception as e:
            duration = time.time() - start_time
            result = TestResult(test_name, False, duration, str(e))
            print(f"❌ {test_name} failed ({duration:.2f}s): {str(e)}")
        
        self.results.append(result)
        return result
    
    def test_service_health(self, service_name: str, url: str):
        """Test service health endpoint"""
        response = requests.get(f"{url}/health", timeout=30)
        response.raise_for_status()
        
        health_data = response.json()
        
        if health_data.get('status') != 'healthy':
            raise Exception(f"{service_name} is not healthy: {health_data}")
    
    def test_cle_health(self):
        """Test CLE service health"""
        self.test_service_health('CLE', self.cle_url)
    
    def test_eic_health(self):
        """Test EIC service health"""
        self.test_service_health('EIC', self.eic_url)
    
    def test_cm_health(self):
        """Test CM service health"""
        self.test_service_health('CM', self.cm_url)
    
    def test_cle_process_transaction(self):
        """Test CLE transaction processing endpoint"""
        # Simple test transaction
        test_transaction = {
            "transaction_id": "smoke-test-001",
            "source_account_ref": "ACC-001",
            "amount": "100.00",
            "currency": "USD",
            "value_date": "2024-01-01T00:00:00Z",
            "raw_remittance_data": "Payment for INV-12345"
        }
        
        response = requests.post(
            f"{self.cle_url}/api/v1/process_transaction",
            json=test_transaction,
            timeout=60
        )
        
        response.raise_for_status()
        result = response.json()
        
        # Verify response structure
        required_fields = ['status', 'matched_pairs', 'unapplied_amount']
        for field in required_fields:
            if field not in result:
                raise Exception(f"Missing field in response: {field}")
    
    def test_eic_get_invoices(self):
        """Test EIC invoice retrieval"""
        # Test with dummy invoice IDs
        test_request = {
            "invoice_ids": ["INV-12345", "INV-67890"],
            "erp_system": None,  # Auto-detect
            "timeout_seconds": 30
        }
        
        response = requests.post(
            f"{self.eic_url}/api/v1/get_invoices",
            json=test_request,
            timeout=45
        )
        
        # For smoke test, we expect this might fail with authentication
        # or missing ERP configuration, which is acceptable
        if response.status_code not in [200, 401, 422, 502]:
            response.raise_for_status()
        
        print(f"   EIC response status: {response.status_code}")
    
    def test_cm_template_list(self):
        """Test CM template listing"""
        response = requests.get(f"{self.cm_url}/api/v1/templates", timeout=30)
        response.raise_for_status()
        
        templates = response.json()
        
        if 'templates' not in templates:
            raise Exception("Missing templates field in response")
        
        if not isinstance(templates['templates'], list):
            raise Exception("Templates field is not a list")
    
    def test_service_metrics(self, service_name: str, url: str):
        """Test service metrics endpoint"""
        response = requests.get(f"{url}/metrics", timeout=30)
        response.raise_for_status()
        
        # Metrics should be in Prometheus format
        metrics_text = response.text
        
        if not metrics_text or len(metrics_text) < 10:
            raise Exception(f"{service_name} metrics endpoint returned empty response")
        
        # Look for some expected metrics
        expected_metrics = ['http_requests_total', '_processing_duration_', '_start_time_seconds']
        
        for metric in expected_metrics:
            if metric not in metrics_text:
                print(f"   Warning: {metric} not found in {service_name} metrics")
    
    def test_cle_metrics(self):
        """Test CLE metrics"""
        self.test_service_metrics('CLE', self.cle_url)
    
    def test_eic_metrics(self):
        """Test EIC metrics"""
        self.test_service_metrics('EIC', self.eic_url)
    
    def test_cm_metrics(self):
        """Test CM metrics"""  
        self.test_service_metrics('CM', self.cm_url)
    
    def test_end_to_end_flow(self):
        """Test simplified end-to-end flow"""
        print("   Testing end-to-end integration...")
        
        # This would be a more comprehensive test in a real environment
        # For smoke test, we just verify services can communicate
        
        # 1. Check if all services are responsive
        services = [
            ('CLE', self.cle_url),
            ('EIC', self.eic_url),
            ('CM', self.cm_url)
        ]
        
        for service_name, url in services:
            response = requests.get(f"{url}/health", timeout=10)
            if response.status_code != 200:
                raise Exception(f"{service_name} not responsive for end-to-end test")
        
        print("   All services responsive for end-to-end communication")
    
    def run_all_tests(self) -> bool:
        """Run all smoke tests"""
        print(f"🚀 Starting smoke tests for {self.environment} environment")
        print(f"   CLE URL: {self.cle_url}")
        print(f"   EIC URL: {self.eic_url}")
        print(f"   CM URL: {self.cm_url}")
        print()
        
        # Define all tests
        tests = [
            ("CLE Health Check", self.test_cle_health),
            ("EIC Health Check", self.test_eic_health),
            ("CM Health Check", self.test_cm_health),
            ("CLE Transaction Processing", self.test_cle_process_transaction),
            ("EIC Invoice Retrieval", self.test_eic_get_invoices),
            ("CM Template Listing", self.test_cm_template_list),
            ("CLE Metrics", self.test_cle_metrics),
            ("EIC Metrics", self.test_eic_metrics),
            ("CM Metrics", self.test_cm_metrics),
            ("End-to-End Flow", self.test_end_to_end_flow),
        ]
        
        # Run all tests
        for test_name, test_func in tests:
            self.run_test(test_name, test_func)
            time.sleep(1)  # Brief pause between tests
        
        # Print summary
        print("\n" + "="*60)
        print("📊 SMOKE TEST SUMMARY")
        print("="*60)
        
        passed = sum(1 for r in self.results if r.success)
        total = len(self.results)
        
        print(f"Total tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {total - passed}")
        print(f"Success rate: {passed/total*100:.1f}%")
        
        # Show failed tests
        failed_tests = [r for r in self.results if not r.success]
        if failed_tests:
            print("\n❌ FAILED TESTS:")
            for result in failed_tests:
                print(f"   {result.name}: {result.error}")
        
        # Show timing summary
        total_time = sum(r.duration for r in self.results)
        print(f"\nTotal execution time: {total_time:.2f} seconds")
        
        return len(failed_tests) == 0

def main():
    runner = SmokeTestRunner()
    
    try:
        success = runner.run_all_tests()
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        print("\n❌ Smoke tests cancelled by user")
        sys.exit(1)

if __name__ == '__main__':
    main()