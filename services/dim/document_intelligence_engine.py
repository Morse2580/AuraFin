# services/dim/document_intelligence_engine.py
"""
Main Document Intelligence Engine - Three-Tier Architecture
Orchestrates pattern matching, LayoutLM, and Azure Form Recognizer
"""
import logging
import asyncio
import time
from typing import List, Dict, Optional, Any, Union
from dataclasses import dataclass
from enum import Enum
import random

from .config.model_config import get_model_config, get_enabled_tiers, is_e2e_mode, is_production_mode, ModelTier
from .tiers.pattern_matcher import PatternMatcher, PatternMatchResult
from .tiers.layoutlm_onnx import LayoutLMONNX, LayoutLMResult
from .tiers.azure_form_recognizer import AzureFormRecognizer, AzureFormResult

logger = logging.getLogger(__name__)

@dataclass
class DocumentIntelligenceResult:
    """Final result from document intelligence processing"""
    invoice_ids: List[str]
    confidence: float
    processing_tier: str
    processing_time_ms: int
    cost_estimate: float
    tier_results: Dict[str, Any]
    warnings: List[str]

class DocumentIntelligenceEngine:
    """
    Main Document Intelligence Engine
    
    Implements three-tier processing:
    1. Pattern Matching (Free, Fast) - 70% of documents
    2. LayoutLM ONNX (Low Cost, Medium) - 25% of documents  
    3. Azure Form Recognizer (Higher Cost, Slow) - 5% of documents
    """
    
    def __init__(self):
        self.config = get_model_config()
        self.enabled_tiers = get_enabled_tiers()
        
        # Initialize tier processors
        self.pattern_matcher: Optional[PatternMatcher] = None
        self.layoutlm: Optional[LayoutLMONNX] = None
        self.azure_form_recognizer: Optional[AzureFormRecognizer] = None
        
        self._initialized = False
        self._initialization_error = None
        
        logger.info(f"Document Intelligence Engine configured for {self.config['mode']} mode")
        logger.info(f"Enabled tiers: {[tier['name'] for tier in self.enabled_tiers]}")
    
    async def initialize(self) -> bool:
        """Initialize all enabled processing tiers"""
        try:
            logger.info("Initializing Document Intelligence Engine...")
            
            initialization_tasks = []
            
            # Initialize enabled tiers
            for tier_config in self.enabled_tiers:
                tier_name = tier_config['name']
                
                if tier_name == ModelTier.PATTERN_MATCHING.value:
                    self.pattern_matcher = PatternMatcher(tier_config.get('patterns'))
                    logger.info("Pattern matching tier initialized")
                
                elif tier_name == ModelTier.LAYOUTLM.value:
                    self.layoutlm = LayoutLMONNX(
                        model_path=tier_config['model_path'],
                        tokenizer_name=tier_config['tokenizer']
                    )
                    initialization_tasks.append(
                        self._initialize_layoutlm()
                    )
                
                elif tier_name == ModelTier.AZURE_FORM_RECOGNIZER.value:
                    if tier_config.get('endpoint') and tier_config.get('api_key'):
                        self.azure_form_recognizer = AzureFormRecognizer(
                            endpoint=tier_config['endpoint'],
                            api_key=tier_config['api_key']
                        )
                        initialization_tasks.append(
                            self._initialize_azure_form_recognizer()
                        )
                    else:
                        logger.warning("Azure Form Recognizer credentials not provided")
            
            # Run async initializations
            if initialization_tasks:
                await asyncio.gather(*initialization_tasks, return_exceptions=True)
            
            self._initialized = True
            logger.info("Document Intelligence Engine initialized successfully")
            
            # Log tier availability
            await self._log_tier_status()
            return True
            
        except Exception as e:
            self._initialization_error = str(e)
            logger.error(f"Failed to initialize Document Intelligence Engine: {e}")
            return False
    
    async def extract_invoice_ids(
        self, 
        document_content: Union[str, bytes], 
        document_type: str = "text",
        correlation_id: Optional[str] = None
    ) -> DocumentIntelligenceResult:
        """
        Extract invoice IDs using three-tier approach
        
        Args:
            document_content: Document content (text or binary)
            document_type: Type of document ("text", "pdf", "image")
            correlation_id: Request correlation ID for tracking
            
        Returns:
            DocumentIntelligenceResult with extracted invoice IDs
        """
        start_time = time.time()
        warnings = []
        tier_results = {}
        
        if not self._initialized:
            logger.warning("Engine not initialized, attempting to initialize...")
            if not await self.initialize():
                return self._create_error_result(start_time, "Engine initialization failed")
        
        # Handle E2E test mode
        if is_e2e_mode():
            return self._create_mock_result(start_time, correlation_id)
        
        try:
            # Convert document to text if needed
            text_content = await self._prepare_text_content(document_content, document_type)
            
            # Tier 1: Pattern Matching (always try first if available)
            if self.pattern_matcher:
                logger.info("Trying Tier 1: Pattern Matching")
                pattern_result = self.pattern_matcher.extract_invoice_ids(text_content)
                tier_results['pattern_matching'] = pattern_result.__dict__
                
                # Check if pattern matching confidence is high enough
                pattern_threshold = self._get_tier_threshold(ModelTier.PATTERN_MATCHING.value)
                if pattern_result.confidence >= pattern_threshold:
                    logger.info(f"Pattern matching successful with confidence {pattern_result.confidence:.2f}")
                    return self._create_success_result(
                        pattern_result.invoice_ids,
                        pattern_result.confidence,
                        "pattern_matching",
                        start_time,
                        0.0,  # Free
                        tier_results,
                        warnings
                    )
                else:
                    warnings.append(f"Pattern matching confidence too low: {pattern_result.confidence:.2f}")
            
            # Tier 2: LayoutLM ONNX (if pattern matching wasn't confident enough)
            if self.layoutlm and self.layoutlm.is_available():
                logger.info("Trying Tier 2: LayoutLM ONNX")
                layoutlm_result = await self.layoutlm.extract_invoice_ids(text_content)
                tier_results['layoutlm'] = layoutlm_result.__dict__
                
                layoutlm_threshold = self._get_tier_threshold(ModelTier.LAYOUTLM.value)
                if layoutlm_result.confidence >= layoutlm_threshold:
                    logger.info(f"LayoutLM successful with confidence {layoutlm_result.confidence:.2f}")
                    cost = self._get_tier_cost(ModelTier.LAYOUTLM.value)
                    return self._create_success_result(
                        layoutlm_result.invoice_ids,
                        layoutlm_result.confidence,
                        "layoutlm",
                        start_time,
                        cost,
                        tier_results,
                        warnings
                    )
                else:
                    warnings.append(f"LayoutLM confidence too low: {layoutlm_result.confidence:.2f}")
            
            # Tier 3: Azure Form Recognizer (last resort)
            if self.azure_form_recognizer and self.azure_form_recognizer.is_available():
                logger.info("Trying Tier 3: Azure Form Recognizer")
                
                # Convert text back to document content if needed for Azure
                document_bytes = self._prepare_document_bytes(document_content, document_type)
                azure_result = await self.azure_form_recognizer.extract_invoice_ids(document_bytes)
                tier_results['azure_form_recognizer'] = azure_result.__dict__
                
                logger.info(f"Azure Form Recognizer completed with confidence {azure_result.confidence:.2f}")
                cost = self._get_tier_cost(ModelTier.AZURE_FORM_RECOGNIZER.value)
                return self._create_success_result(
                    azure_result.invoice_ids,
                    azure_result.confidence,
                    "azure_form_recognizer",
                    start_time,
                    cost,
                    tier_results,
                    warnings
                )
            
            # If all tiers failed or unavailable
            warnings.append("All processing tiers failed or returned low confidence")
            best_result = self._get_best_tier_result(tier_results)
            if best_result:
                return best_result
                
            return self._create_error_result(start_time, "No invoice IDs found with sufficient confidence")
            
        except Exception as e:
            logger.error(f"Error during invoice ID extraction: {e}")
            return self._create_error_result(start_time, f"Processing error: {str(e)}")
    
    async def _initialize_layoutlm(self):
        """Initialize LayoutLM tier"""
        if self.layoutlm:
            success = await self.layoutlm.initialize()
            if success:
                logger.info("LayoutLM tier initialized successfully")
            else:
                logger.warning("LayoutLM tier initialization failed")
    
    async def _initialize_azure_form_recognizer(self):
        """Initialize Azure Form Recognizer tier"""
        if self.azure_form_recognizer:
            success = await self.azure_form_recognizer.initialize()
            if success:
                logger.info("Azure Form Recognizer tier initialized successfully")
            else:
                logger.warning("Azure Form Recognizer tier initialization failed")
    
    async def _log_tier_status(self):
        """Log the status of all tiers"""
        status = {
            "pattern_matching": self.pattern_matcher is not None,
            "layoutlm": self.layoutlm.is_available() if self.layoutlm else False,
            "azure_form_recognizer": self.azure_form_recognizer.is_available() if self.azure_form_recognizer else False
        }
        logger.info(f"Tier availability: {status}")
    
    def _create_mock_result(self, start_time: float, correlation_id: Optional[str]) -> DocumentIntelligenceResult:
        """Create mock result for E2E testing"""
        mock_responses = self.config.get('e2e_test', {}).get('mock_responses', [])
        
        if mock_responses:
            # Select a random mock response
            mock_data = random.choice(mock_responses)
            processing_time_ms = int((time.time() - start_time) * 1000)
            
            logger.info(f"Returning mock result for E2E testing: {mock_data['invoice_ids']}")
            
            return DocumentIntelligenceResult(
                invoice_ids=mock_data['invoice_ids'],
                confidence=mock_data['confidence'],
                processing_tier="mock_e2e",
                processing_time_ms=processing_time_ms,
                cost_estimate=0.0,
                tier_results={"mock": mock_data},
                warnings=["E2E test mode - mock results"]
            )
        
        # Default mock if no mock responses configured
        return DocumentIntelligenceResult(
            invoice_ids=["E2E-TEST-123"],
            confidence=0.95,
            processing_tier="mock_e2e",
            processing_time_ms=10,
            cost_estimate=0.0,
            tier_results={},
            warnings=["E2E test mode - default mock result"]
        )
    
    async def _prepare_text_content(self, document_content: Union[str, bytes], document_type: str) -> str:
        """Prepare text content from various document types"""
        if isinstance(document_content, str):
            return document_content
        
        # Handle binary content (PDF, images, etc.)
        if document_type.lower() in ['pdf', 'image', 'png', 'jpg', 'jpeg']:
            # For now, return a placeholder - in production you'd use OCR
            logger.warning(f"Binary document type {document_type} - using placeholder text")
            return "Sample invoice document content for processing"
        
        # Try to decode bytes to string
        try:
            return document_content.decode('utf-8')
        except UnicodeDecodeError:
            logger.warning("Could not decode document content to text")
            return "Unable to decode document content"
    
    def _prepare_document_bytes(self, document_content: Union[str, bytes], document_type: str) -> bytes:
        """Prepare binary content for Azure Form Recognizer"""
        if isinstance(document_content, bytes):
            return document_content
        
        # Convert string to bytes
        return document_content.encode('utf-8')
    
    def _get_tier_threshold(self, tier_name: str) -> float:
        """Get confidence threshold for a tier"""
        for tier in self.enabled_tiers:
            if tier['name'] == tier_name:
                return tier['confidence_threshold']
        return 0.8  # Default threshold
    
    def _get_tier_cost(self, tier_name: str) -> float:
        """Get cost per document for a tier"""
        for tier in self.enabled_tiers:
            if tier['name'] == tier_name:
                return tier.get('cost_per_document', 0.0)
        return 0.0
    
    def _get_best_tier_result(self, tier_results: Dict[str, Any]) -> Optional[DocumentIntelligenceResult]:
        """Get the best result from available tier results"""
        best_confidence = 0.0
        best_result = None
        
        for tier_name, result_data in tier_results.items():
            if isinstance(result_data, dict) and 'confidence' in result_data:
                if result_data['confidence'] > best_confidence:
                    best_confidence = result_data['confidence']
                    best_result = (tier_name, result_data)
        
        if best_result:
            tier_name, result_data = best_result
            return DocumentIntelligenceResult(
                invoice_ids=result_data.get('invoice_ids', []),
                confidence=result_data.get('confidence', 0.0),
                processing_tier=tier_name,
                processing_time_ms=result_data.get('processing_time_ms', 0),
                cost_estimate=self._get_tier_cost(tier_name),
                tier_results=tier_results,
                warnings=["Using best available result with low confidence"]
            )
        
        return None
    
    def _create_success_result(
        self,
        invoice_ids: List[str],
        confidence: float,
        tier: str,
        start_time: float,
        cost: float,
        tier_results: Dict[str, Any],
        warnings: List[str]
    ) -> DocumentIntelligenceResult:
        """Create successful processing result"""
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        return DocumentIntelligenceResult(
            invoice_ids=invoice_ids,
            confidence=confidence,
            processing_tier=tier,
            processing_time_ms=processing_time_ms,
            cost_estimate=cost,
            tier_results=tier_results,
            warnings=warnings
        )
    
    def _create_error_result(self, start_time: float, error_message: str) -> DocumentIntelligenceResult:
        """Create error result"""
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        return DocumentIntelligenceResult(
            invoice_ids=[],
            confidence=0.0,
            processing_tier="error",
            processing_time_ms=processing_time_ms,
            cost_estimate=0.0,
            tier_results={},
            warnings=[error_message]
        )
    
    def get_engine_status(self) -> Dict[str, Any]:
        """Get current engine status"""
        return {
            "initialized": self._initialized,
            "mode": self.config['mode'],
            "enabled_tiers": [tier['name'] for tier in self.enabled_tiers],
            "tier_status": {
                "pattern_matching": self.pattern_matcher is not None,
                "layoutlm": self.layoutlm.is_available() if self.layoutlm else False,
                "azure_form_recognizer": self.azure_form_recognizer.is_available() if self.azure_form_recognizer else False
            },
            "initialization_error": self._initialization_error
        }