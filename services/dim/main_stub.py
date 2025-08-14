# services/dim/main_stub.py
"""
DIM Service - E2E Testing Stub Version
Simple stub for testing without heavy ML dependencies
"""

import time
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict, Any

app = FastAPI(title="DIM Service - E2E Stub")

class HealthResponse(BaseModel):
    status: str
    service: str
    timestamp: float
    details: Dict[str, Any] = {}

class DocumentParseRequest(BaseModel):
    document_uris: List[str]
    client_id: str = None

class DocumentParseResponse(BaseModel):
    request_id: str
    invoice_ids: List[str]
    confidence_score: float
    processing_duration_ms: int
    warnings: List[str] = []

@app.get("/health")
async def health_check():
    return HealthResponse(
        status="healthy",
        service="dim-stub",
        timestamp=time.time(),
        details={
            "mode": "e2e_test_stub",
            "database": "healthy", 
            "document_intelligence": "healthy",
            "tier_status": {
                "pattern_matching": True,
                "layoutlm": False,
                "azure_form_recognizer": False
            }
        }
    )

@app.post("/api/v1/parse_document")
async def parse_document(request: DocumentParseRequest):
    # Mock response for E2E testing
    return DocumentParseResponse(
        request_id=f"test-{int(time.time())}",
        invoice_ids=["INV-123456", "PO-789012"],
        confidence_score=0.95,
        processing_duration_ms=50,
        warnings=["E2E test mode - mock results"]
    )

@app.get("/api/v1/models/status")
async def model_status():
    return {
        "engine_initialized": True,
        "mode": "e2e_test_stub",
        "enabled_tiers": ["pattern_matching"],
        "tier_status": {"pattern_matching": True}
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)