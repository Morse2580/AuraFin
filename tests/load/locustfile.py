"""
CashUp Agent Load Testing with Locust
Tests the three-tier ML document processing system under load
"""

import json
import random
from locust import HttpUser, task, between
from locust.contrib.fasthttp import FastHttpUser

class CashUpMLUser(FastHttpUser):
    """Simulate users sending documents for ML processing"""
    
    wait_time = between(1, 3)  # Wait 1-3 seconds between requests
    
    def on_start(self):
        """Setup test data"""
        self.test_documents = [
            # Tier 1: Pattern Matching (should be fast)
            {
                "document_content": "Invoice #: INV-123456\nAmount: $1,500.00\nDate: 2024-01-15",
                "document_type": "text",
                "expected_tier": "pattern_matching"
            },
            {
                "document_content": "UNI-789012\nVendor: Unilever Corp\nTotal: $2,300.50",
                "document_type": "text", 
                "expected_tier": "pattern_matching"
            },
            # Tier 2: Complex documents (would go to LayoutLM)
            {
                "document_content": "Complex invoice with unclear format...",
                "document_type": "pdf",
                "expected_tier": "layoutlm_onnx"
            },
            # Tier 3: Unstructured documents (would go to Azure)
            {
                "document_content": "Handwritten invoice receipt with unclear text",
                "document_type": "image",
                "expected_tier": "azure_form_recognizer"
            }
        ]
    
    @task(7)  # 70% of requests - should hit Tier 1
    def test_pattern_matching_documents(self):
        """Test documents that should be processed by Tier 1 (Pattern Matching)"""
        doc = random.choice([d for d in self.test_documents if d["expected_tier"] == "pattern_matching"])
        
        with self.client.post(
            "/api/v1/extract",
            json=doc,
            headers={"Content-Type": "application/json"},
            catch_response=True
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if data.get("tier_used") == "pattern_matching":
                    response.success()
                else:
                    response.failure(f"Expected pattern_matching tier, got {data.get('tier_used')}")
            else:
                response.failure(f"Got status code {response.status_code}")
    
    @task(2)  # 20% of requests - should hit Tier 2
    def test_layoutlm_documents(self):
        """Test documents that should be processed by Tier 2 (LayoutLM ONNX)"""
        doc = random.choice([d for d in self.test_documents if d["expected_tier"] == "layoutlm_onnx"])
        
        with self.client.post(
            "/api/v1/extract",
            json=doc,
            headers={"Content-Type": "application/json"},
            catch_response=True
        ) as response:
            if response.status_code == 200:
                # LayoutLM processing should take longer but still be reasonable
                if response.elapsed.total_seconds() > 2.0:
                    response.failure("LayoutLM processing took too long")
                else:
                    response.success()
            else:
                response.failure(f"Got status code {response.status_code}")
    
    @task(1)  # 10% of requests - should hit Tier 3
    def test_azure_form_recognizer_documents(self):
        """Test documents that should be processed by Tier 3 (Azure Form Recognizer)"""
        doc = random.choice([d for d in self.test_documents if d["expected_tier"] == "azure_form_recognizer"])
        
        with self.client.post(
            "/api/v1/extract",
            json=doc,
            headers={"Content-Type": "application/json"},
            catch_response=True
        ) as response:
            if response.status_code == 200:
                # Azure processing can take longer
                if response.elapsed.total_seconds() > 10.0:
                    response.failure("Azure Form Recognizer processing took too long")
                else:
                    response.success()
            else:
                response.failure(f"Got status code {response.status_code}")
    
    @task(1)
    def test_health_endpoint(self):
        """Test service health endpoint"""
        self.client.get("/health")
    
    @task(1)
    def test_metrics_endpoint(self):
        """Test metrics endpoint"""
        self.client.get("/metrics")


class CashUpInfrastructureUser(HttpUser):
    """Test infrastructure services health"""
    
    wait_time = between(5, 10)
    
    @task
    def test_cle_health(self):
        """Test Core Logic Engine health"""
        with self.client.get("http://localhost:8011/health", catch_response=True) as response:
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "healthy":
                    response.success()
                else:
                    response.failure(f"CLE not healthy: {data}")
            else:
                response.failure(f"CLE health check failed: {response.status_code}")
    
    @task
    def test_orchestrator_health(self):
        """Test Orchestrator health"""
        with self.client.get("http://localhost:8006/health", catch_response=True) as response:
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "healthy":
                    response.success()
                else:
                    response.failure(f"Orchestrator not healthy: {data}")
            else:
                response.failure(f"Orchestrator health check failed: {response.status_code}")


# Load testing scenarios
class LightLoad(CashUpMLUser):
    """Light load testing - 10 users"""
    weight = 1

class MediumLoad(CashUpMLUser):
    """Medium load testing - 50 users"""
    weight = 3

class HeavyLoad(CashUpMLUser):
    """Heavy load testing - 100 users"""
    weight = 1