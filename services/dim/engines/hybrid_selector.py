"""
Hybrid OCR Engine Selector for CashApp Document Intelligence
Intelligently routes documents to Tesseract (free) or Azure (paid) based on complexity and quality
Optimizes costs while maintaining accuracy
"""

import logging
import asyncio
import time
from typing import Dict, List, Any, Optional, Union, Tuple
from dataclasses import dataclass
from enum import Enum
import os
import cv2
import numpy as np
from pathlib import Path

from .tesseract_engine import TesseractEngine, InvoiceData as TesseractInvoiceData, OCRResult
from .azure_engine import AzureFormRecognizerEngine, AzureInvoiceData, AzureOCRResult

logger = logging.getLogger(__name__)

class ProcessingStrategy(Enum):
    """OCR processing strategies"""
    TESSERACT_ONLY = "tesseract_only"
    AZURE_ONLY = "azure_only" 
    TESSERACT_FIRST = "tesseract_first"
    AZURE_FALLBACK = "azure_fallback"
    PARALLEL_VALIDATION = "parallel_validation"
    COST_OPTIMIZED = "cost_optimized"

@dataclass
class DocumentComplexity:
    """Document complexity assessment"""
    quality_score: float
    text_density: float
    table_count: int
    handwriting_detected: bool
    language_complexity: float
    overall_complexity: float
    recommended_engine: str
    confidence: float

@dataclass
class ProcessingResult:
    """Combined processing result from hybrid engine"""
    invoice_ids: List[str]
    amounts: List[float]
    dates: List[str]
    vendors: List[str]
    line_items: List[Dict]
    confidence: float
    processing_time_ms: int
    cost_estimate: float
    engine_used: str
    fallback_used: bool
    raw_text: str

class HybridDocumentIntelligence:
    """
    Hybrid OCR engine that intelligently selects between Tesseract and Azure
    based on document complexity, quality, and cost optimization settings
    """
    
    def __init__(self, 
                 azure_endpoint: str = None,
                 azure_api_key: str = None,
                 strategy: ProcessingStrategy = ProcessingStrategy.COST_OPTIMIZED,
                 cost_budget_per_page: float = 0.005,
                 quality_threshold: float = 0.7,
                 confidence_threshold: float = 0.8):
        """
        Initialize hybrid engine
        
        Args:
            azure_endpoint: Azure Form Recognizer endpoint
            azure_api_key: Azure API key
            strategy: Processing strategy to use
            cost_budget_per_page: Maximum cost per page for Azure processing
            quality_threshold: Quality threshold for engine selection
            confidence_threshold: Confidence threshold for fallback decisions
        """
        self.strategy = strategy
        self.cost_budget_per_page = cost_budget_per_page
        self.quality_threshold = quality_threshold
        self.confidence_threshold = confidence_threshold
        
        # Initialize engines
        self.tesseract_engine = TesseractEngine()
        
        self.azure_engine = None
        if azure_endpoint and azure_api_key:
            self.azure_engine = AzureFormRecognizerEngine(
                endpoint=azure_endpoint,
                api_key=azure_api_key
            )
        
        # Statistics tracking
        self.stats = {
            'total_processed': 0,
            'tesseract_used': 0,
            'azure_used': 0,
            'fallback_triggered': 0,
            'total_cost': 0.0,
            'cost_savings': 0.0,
            'accuracy_rate': 0.0
        }
        
        logger.info(f"Hybrid engine initialized with strategy: {strategy.value}")
        if self.azure_engine:
            logger.info("Azure Form Recognizer available")
        else:
            logger.warning("Azure Form Recognizer not configured - Tesseract only mode")
    
    def assess_document_complexity(self, image_path: str) -> DocumentComplexity:
        """
        Assess document complexity to determine optimal processing engine
        
        Args:
            image_path: Path to document image
            
        Returns:
            Document complexity assessment
        """
        try:
            # Load image
            image = cv2.imread(image_path)
            if image is None:
                return DocumentComplexity(0.0, 0.0, 0, False, 0.0, 1.0, "azure", 0.0)
            
            # Convert to grayscale for analysis
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            
            # 1. Quality assessment (reuse from Tesseract engine)
            quality_score = self.tesseract_engine.assess_document_quality(image_path)
            
            # 2. Text density analysis
            text_density = self._analyze_text_density(gray)
            
            # 3. Table detection
            table_count = self._detect_tables(gray)
            
            # 4. Handwriting detection
            handwriting_detected = self._detect_handwriting(gray)
            
            # 5. Language complexity (simplified)
            language_complexity = self._assess_language_complexity(gray)
            
            # Calculate overall complexity
            complexity_factors = [
                1.0 - quality_score,           # Poor quality = high complexity
                text_density,                   # High density = high complexity
                min(table_count * 0.2, 1.0),  # Tables = high complexity
                0.5 if handwriting_detected else 0.0,  # Handwriting = high complexity
                language_complexity             # Non-English = high complexity
            ]
            
            weights = [0.3, 0.25, 0.2, 0.15, 0.1]
            overall_complexity = sum(factor * weight for factor, weight in zip(complexity_factors, weights))
            
            # Determine recommended engine
            if overall_complexity < 0.3 and quality_score > self.quality_threshold:
                recommended_engine = "tesseract"
                confidence = 0.9
            elif overall_complexity < 0.6:
                recommended_engine = "tesseract" if self.strategy == ProcessingStrategy.TESSERACT_FIRST else "azure"
                confidence = 0.7
            else:
                recommended_engine = "azure"
                confidence = 0.8
            
            # Override if Azure not available
            if not self.azure_engine:
                recommended_engine = "tesseract"
                confidence = min(confidence, 0.6)
            
            complexity = DocumentComplexity(
                quality_score=quality_score,
                text_density=text_density,
                table_count=table_count,
                handwriting_detected=handwriting_detected,
                language_complexity=language_complexity,
                overall_complexity=overall_complexity,
                recommended_engine=recommended_engine,
                confidence=confidence
            )
            
            logger.info(f"Document complexity assessed", extra={
                'quality_score': quality_score,
                'text_density': text_density,
                'table_count': table_count,
                'handwriting': handwriting_detected,
                'overall_complexity': overall_complexity,
                'recommended_engine': recommended_engine
            })
            
            return complexity
            
        except Exception as e:
            logger.error(f"Error assessing document complexity: {e}")
            # Default to Azure for safety
            return DocumentComplexity(0.0, 0.0, 0, False, 0.0, 1.0, "azure", 0.5)
    
    def _analyze_text_density(self, gray_image: np.ndarray) -> float:
        """Analyze text density in image"""
        try:
            # Edge detection to find text regions
            edges = cv2.Canny(gray_image, 50, 150)
            
            # Count edge pixels as proxy for text density
            edge_pixels = np.sum(edges > 0)
            total_pixels = edges.shape[0] * edges.shape[1]
            
            density = edge_pixels / total_pixels
            return min(density * 10, 1.0)  # Normalize
            
        except Exception:
            return 0.5  # Default medium density
    
    def _detect_tables(self, gray_image: np.ndarray) -> int:
        """Detect presence of tables in image"""
        try:
            # Use Hough line detection to find table structure
            edges = cv2.Canny(gray_image, 50, 150)
            
            # Detect horizontal lines
            horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 1))
            horizontal_lines = cv2.morphologyEx(edges, cv2.MORPH_OPEN, horizontal_kernel)
            
            # Detect vertical lines
            vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 25))
            vertical_lines = cv2.morphologyEx(edges, cv2.MORPH_OPEN, vertical_kernel)
            
            # Count line intersections as proxy for tables
            combined = cv2.addWeighted(horizontal_lines, 0.5, vertical_lines, 0.5, 0)
            contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Filter contours by size to get potential tables
            table_contours = [c for c in contours if cv2.contourArea(c) > 1000]
            
            return len(table_contours)
            
        except Exception:
            return 0
    
    def _detect_handwriting(self, gray_image: np.ndarray) -> bool:
        """Detect handwriting in image (simplified heuristic)"""
        try:
            # Look for irregular, non-uniform text patterns
            # This is a simplified approach - real handwriting detection is complex
            
            # Apply morphological operations to find text regions
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            morph = cv2.morphologyEx(gray_image, cv2.MORPH_CLOSE, kernel)
            
            # Calculate variance in text regions
            variance = cv2.Laplacian(morph, cv2.CV_64F).var()
            
            # High variance might indicate handwriting
            return variance > 1000
            
        except Exception:
            return False
    
    def _assess_language_complexity(self, gray_image: np.ndarray) -> float:
        """Assess language complexity (simplified - assumes English)"""
        # In a real implementation, this would:
        # 1. Detect language from text samples
        # 2. Assess character complexity (CJK vs Latin)
        # 3. Return complexity score
        return 0.1  # Assume English (low complexity)
    
    async def extract_invoice_data(self, 
                                 image_path: str,
                                 document_url: str = None,
                                 force_engine: str = None) -> ProcessingResult:
        """
        Extract invoice data using hybrid approach
        
        Args:
            image_path: Path to image file
            document_url: URL to document (for Azure)
            force_engine: Force specific engine ('tesseract' or 'azure')
            
        Returns:
            Processing result with extracted data
        """
        start_time = time.time()
        
        try:
            # Assess document complexity unless engine is forced
            if not force_engine:
                complexity = self.assess_document_complexity(image_path)
                selected_engine = complexity.recommended_engine
            else:
                selected_engine = force_engine
                complexity = None
            
            # Apply strategy-specific logic
            if self.strategy == ProcessingStrategy.TESSERACT_ONLY:
                selected_engine = "tesseract"
            elif self.strategy == ProcessingStrategy.AZURE_ONLY:
                selected_engine = "azure"
            elif self.strategy == ProcessingStrategy.COST_OPTIMIZED:
                # Check budget constraint
                azure_cost = self.azure_engine.pricing.get('prebuilt-invoice', 0.01) if self.azure_engine else 0.01
                if azure_cost > self.cost_budget_per_page:
                    selected_engine = "tesseract"
            
            # Process with selected engine
            result = await self._process_with_engine(
                selected_engine, 
                image_path, 
                document_url,
                complexity
            )
            
            # Update statistics
            self.stats['total_processed'] += 1
            if result.engine_used == 'tesseract':
                self.stats['tesseract_used'] += 1
            else:
                self.stats['azure_used'] += 1
            
            if result.fallback_used:
                self.stats['fallback_triggered'] += 1
            
            self.stats['total_cost'] += result.cost_estimate
            
            # Calculate cost savings (vs always using Azure)
            azure_cost = self.azure_engine.pricing.get('prebuilt-invoice', 0.01) if self.azure_engine else 0.01
            if result.engine_used == 'tesseract':
                self.stats['cost_savings'] += azure_cost
            
            return result
            
        except Exception as e:
            logger.error(f"Error in hybrid processing: {e}")
            return ProcessingResult(
                invoice_ids=[],
                amounts=[],
                dates=[],
                vendors=[],
                line_items=[],
                confidence=0.0,
                processing_time_ms=int((time.time() - start_time) * 1000),
                cost_estimate=0.0,
                engine_used="error",
                fallback_used=False,
                raw_text=""
            )
    
    async def _process_with_engine(self,
                                 engine: str,
                                 image_path: str,
                                 document_url: str = None,
                                 complexity: DocumentComplexity = None) -> ProcessingResult:
        """
        Process document with specific engine, including fallback logic
        
        Args:
            engine: Engine to use ('tesseract' or 'azure')
            image_path: Path to image file
            document_url: URL to document
            complexity: Document complexity assessment
            
        Returns:
            Processing result
        """
        start_time = time.time()
        fallback_used = False
        
        try:
            if engine == "tesseract":
                # Process with Tesseract
                ocr_result = self.tesseract_engine.extract_text(image_path, preprocess=True)
                
                if ocr_result.confidence > 0.3:
                    invoice_data = self.tesseract_engine.extract_invoice_data(ocr_result.text)
                    
                    # Check if fallback is needed
                    needs_fallback = (
                        self.strategy == ProcessingStrategy.AZURE_FALLBACK and
                        self.azure_engine and
                        (ocr_result.confidence < self.confidence_threshold or 
                         invoice_data.confidence < self.confidence_threshold)
                    )
                    
                    if needs_fallback:
                        logger.info(f"Triggering Azure fallback - Tesseract confidence: {ocr_result.confidence:.2f}")
                        return await self._process_with_engine("azure", image_path, document_url, complexity)
                    
                    return ProcessingResult(
                        invoice_ids=invoice_data.invoice_ids,
                        amounts=invoice_data.amounts,
                        dates=invoice_data.dates,
                        vendors=invoice_data.vendors,
                        line_items=[],
                        confidence=invoice_data.confidence,
                        processing_time_ms=int((time.time() - start_time) * 1000),
                        cost_estimate=0.0,  # Tesseract is free
                        engine_used="tesseract",
                        fallback_used=False,
                        raw_text=ocr_result.text
                    )
                else:
                    # Low confidence, try Azure if available
                    if self.azure_engine:
                        logger.info("Low Tesseract confidence, falling back to Azure")
                        fallback_used = True
                        return await self._process_with_engine("azure", image_path, document_url, complexity)
                    else:
                        # Return low-confidence Tesseract result
                        return ProcessingResult(
                            invoice_ids=[],
                            amounts=[],
                            dates=[],
                            vendors=[],
                            line_items=[],
                            confidence=ocr_result.confidence,
                            processing_time_ms=int((time.time() - start_time) * 1000),
                            cost_estimate=0.0,
                            engine_used="tesseract",
                            fallback_used=False,
                            raw_text=ocr_result.text
                        )
            
            elif engine == "azure" and self.azure_engine:
                # Process with Azure
                if document_url:
                    azure_result = await self.azure_engine.extract_invoice_data(document_url=document_url)
                else:
                    # Convert image to bytes for Azure
                    with open(image_path, 'rb') as f:
                        document_bytes = f.read()
                    azure_result = await self.azure_engine.extract_invoice_data(document_bytes=document_bytes)
                
                return ProcessingResult(
                    invoice_ids=azure_result.invoice_ids,
                    amounts=azure_result.amounts,
                    dates=azure_result.dates,
                    vendors=azure_result.vendors,
                    line_items=azure_result.line_items,
                    confidence=azure_result.confidence,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                    cost_estimate=azure_result.cost_estimate,
                    engine_used="azure",
                    fallback_used=fallback_used,
                    raw_text=""  # Azure provides structured data
                )
            
            else:
                raise ValueError(f"Invalid engine or Azure not configured: {engine}")
                
        except Exception as e:
            logger.error(f"Error processing with {engine}: {e}")
            
            # Try fallback if not already attempted
            if not fallback_used:
                if engine == "tesseract" and self.azure_engine:
                    logger.info("Tesseract failed, falling back to Azure")
                    return await self._process_with_engine("azure", image_path, document_url, complexity)
                elif engine == "azure":
                    logger.info("Azure failed, falling back to Tesseract")
                    return await self._process_with_engine("tesseract", image_path, document_url, complexity)
            
            # Return empty result if all else fails
            return ProcessingResult(
                invoice_ids=[],
                amounts=[],
                dates=[],
                vendors=[],
                line_items=[],
                confidence=0.0,
                processing_time_ms=int((time.time() - start_time) * 1000),
                cost_estimate=0.0,
                engine_used="error",
                fallback_used=fallback_used,
                raw_text=""
            )
    
    async def process_batch(self, 
                          image_paths: List[str],
                          document_urls: List[str] = None,
                          max_concurrent: int = 5) -> List[ProcessingResult]:
        """
        Process multiple documents in batch
        
        Args:
            image_paths: List of image file paths
            document_urls: List of document URLs (optional)
            max_concurrent: Maximum concurrent processing
            
        Returns:
            List of processing results
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def process_single(i: int) -> ProcessingResult:
            async with semaphore:
                image_path = image_paths[i]
                document_url = document_urls[i] if document_urls and i < len(document_urls) else None
                return await self.extract_invoice_data(image_path, document_url)
        
        tasks = [process_single(i) for i in range(len(image_paths))]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions
        valid_results = [r for r in results if isinstance(r, ProcessingResult)]
        
        logger.info(f"Batch processing completed: {len(valid_results)}/{len(image_paths)} successful")
        
        return valid_results
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get processing statistics"""
        total = self.stats['total_processed']
        
        return {
            **self.stats,
            'tesseract_usage_rate': self.stats['tesseract_used'] / total if total > 0 else 0,
            'azure_usage_rate': self.stats['azure_used'] / total if total > 0 else 0,
            'fallback_rate': self.stats['fallback_triggered'] / total if total > 0 else 0,
            'avg_cost_per_document': self.stats['total_cost'] / total if total > 0 else 0,
            'cost_savings_percentage': (self.stats['cost_savings'] / (self.stats['cost_savings'] + self.stats['total_cost'])) * 100 if (self.stats['cost_savings'] + self.stats['total_cost']) > 0 else 0
        }
    
    def get_capabilities(self) -> Dict[str, Any]:
        """Get hybrid engine capabilities"""
        tesseract_caps = self.tesseract_engine.get_capabilities()
        azure_caps = self.azure_engine.get_capabilities() if self.azure_engine else {}
        
        return {
            'name': 'HybridDocumentIntelligence',
            'strategy': self.strategy.value,
            'engines': {
                'tesseract': tesseract_caps,
                'azure': azure_caps
            },
            'features': {
                'cost_optimization': True,
                'intelligent_routing': True,
                'fallback_processing': True,
                'batch_processing': True,
                'complexity_assessment': True,
                'statistics_tracking': True
            },
            'cost_budget_per_page': self.cost_budget_per_page,
            'quality_threshold': self.quality_threshold,
            'confidence_threshold': self.confidence_threshold
        }
    
    async def close(self):
        """Close the hybrid engine"""
        if self.azure_engine:
            await self.azure_engine.close()
        logger.info("Hybrid engine closed")