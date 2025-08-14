# services/dim/config/model_config.py
"""
DIM Model Configuration - Three-Tier Architecture
"""
import os
from typing import Dict, List, Optional
from enum import Enum

class DIMMode(Enum):
    """DIM Service modes"""
    PRODUCTION = "production"
    E2E_TEST = "e2e_test"
    DEVELOPMENT = "development"

class ModelTier(Enum):
    """Model processing tiers"""
    PATTERN_MATCHING = "pattern_matching"
    LAYOUTLM = "layoutlm"
    AZURE_FORM_RECOGNIZER = "azure_form_recognizer"

# Invoice ID Patterns for Tier 1
INVOICE_PATTERNS = [
    # Standard formats
    r"INV[-\s]?(\d{4,10})",
    r"Invoice\s*#?\s*:?\s*(\d{4,10})",
    r"Bill\s*Number\s*:?\s*(\d{4,10})",
    r"Doc\s*(?:No|Number)\s*:?\s*(\d{4,10})",
    
    # Unilever specific patterns
    r"UNI[-\s]?(\d{6,10})",
    r"UNILEVER\s*[-\s]?(\d{6,10})",
    r"PO\s*[-\s]?(\d{6,12})",
    r"Purchase\s*Order\s*:?\s*(\d{6,12})",
    
    # Generic alphanumeric
    r"([A-Z]{2,4}[-\s]?\d{6,10})",
    r"(\d{8,12})",  # Pure numeric IDs
]

# Model Configuration
DIM_MODEL_CONFIG = {
    "mode": os.getenv("DIM_MODE", "e2e_test"),  # Default to E2E for testing
    
    "tiers": [
        {
            "name": ModelTier.PATTERN_MATCHING.value,
            "enabled": True,
            "confidence_threshold": 0.9,
            "cost_per_document": 0.0,
            "model": None,  # No model, just regex
            "patterns": INVOICE_PATTERNS,
            "timeout_seconds": 1.0
        },
        {
            "name": ModelTier.LAYOUTLM.value,
            "enabled": os.getenv("DIM_MODE") == "production",
            "confidence_threshold": 0.7,
            "cost_per_document": 0.001,
            "model_path": "models/layoutlmv3-base.onnx",
            "tokenizer": "microsoft/layoutlmv3-base",
            "max_length": 512,
            "timeout_seconds": 10.0
        },
        {
            "name": ModelTier.AZURE_FORM_RECOGNIZER.value,
            "enabled": os.getenv("AZURE_FORM_RECOGNIZER_ENDPOINT") is not None,
            "confidence_threshold": 0.0,  # Fallback
            "cost_per_document": 0.001,
            "model": "prebuilt-invoice",
            "endpoint": os.getenv("AZURE_FORM_RECOGNIZER_ENDPOINT"),
            "api_key": os.getenv("AZURE_FORM_RECOGNIZER_KEY"),
            "timeout_seconds": 30.0
        }
    ],
    
    "e2e_test": {
        "mock_responses": [
            {"invoice_ids": ["INV-123456"], "confidence": 0.95},
            {"invoice_ids": ["UNI-789012", "PO-345678"], "confidence": 0.88},
            {"invoice_ids": ["DOC-567890"], "confidence": 0.92},
        ]
    },
    
    "performance": {
        "max_concurrent_requests": 10,
        "request_timeout_seconds": 60,
        "model_warmup_timeout": 120,
        "cache_results": True,
        "cache_ttl_seconds": 3600
    }
}

def get_model_config() -> Dict:
    """Get model configuration based on environment"""
    return DIM_MODEL_CONFIG

def get_enabled_tiers() -> List[Dict]:
    """Get only enabled processing tiers"""
    return [tier for tier in DIM_MODEL_CONFIG["tiers"] if tier["enabled"]]

def is_production_mode() -> bool:
    """Check if running in production mode"""
    return DIM_MODEL_CONFIG["mode"] == DIMMode.PRODUCTION.value

def is_e2e_mode() -> bool:
    """Check if running in E2E test mode"""
    return DIM_MODEL_CONFIG["mode"] == DIMMode.E2E_TEST.value