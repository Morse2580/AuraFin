# services/dim/app/config.py

import os
from typing import Optional
from pydantic_settings import BaseSettings

class DIMSettings(BaseSettings):
    """DIM service configuration"""
    
    # Service Configuration
    SERVICE_NAME: str = "dim"
    SERVICE_VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    # API Configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8002
    WORKERS: int = 1  # Single worker for GPU models
    
    # Azure Storage Configuration
    AZURE_STORAGE_CONNECTION_STRING: str
    AZURE_STORAGE_CONTAINER: str = "documents"
    
    # ML Model Configuration
    LAYOUTLM_MODEL_PATH: str = "microsoft/layoutlmv3-base"
    LLAMA_MODEL_PATH: str = "meta-llama/Meta-Llama-3-8B-Instruct"
    MODEL_CACHE_DIR: str = "/app/models"
    
    # GPU Configuration
    CUDA_VISIBLE_DEVICES: Optional[str] = None
    MAX_GPU_MEMORY_FRACTION: float = 0.9
    
    # Processing Configuration
    MAX_DOCUMENTS_PER_REQUEST: int = 10
    MAX_BATCH_SIZE: int = 100
    PROCESSING_TIMEOUT_SECONDS: int = 300  # 5 minutes
    
    # Model Performance Tuning
    TORCH_COMPILE: bool = False  # Enable for PyTorch 2.0+
    ENABLE_ATTENTION_SLICING: bool = True
    ENABLE_CPU_OFFLOAD: bool = True
    
    # Monitoring Configuration
    METRICS_ENABLED: bool = True
    HEALTH_CHECK_INTERVAL: int = 30
    
    class Config:
        env_file = ".env"
        case_sensitive = True