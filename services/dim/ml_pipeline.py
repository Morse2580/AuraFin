# services/dim/ml_pipeline.py
"""
ML Pipeline for Document Intelligence
Implements 2-stage processing: LayoutLMv3 → Llama-3-8B

Stage 1: OCR & Layout Analysis (LayoutLMv3)
- Input: PDF/image binary
- Output: Structured JSON with text blocks, coordinates, entity types

Stage 2: Contextual Comprehension & Extraction (Llama-3-8B)  
- Input: Structured JSON from Stage 1
- Output: Invoice IDs with confidence scores
"""

import asyncio
import json
import logging
import re
import time
from typing import List, Dict, Any, Optional, Tuple
import io
from pathlib import Path

import torch
import torch.nn.functional as F
from transformers import (
    LayoutLMv3Processor, LayoutLMv3TokenizerFast, LayoutLMv3ForTokenClassification,
    AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
)
from PIL import Image
import pdf2image
import numpy as np
from dataclasses import dataclass

from shared.logging import setup_logging, log_context
from shared.exceptions import ModelLoadError, DocumentProcessingError
from shared.metrics import MODEL_INFERENCE_TIME

logger = setup_logging("dim-ml-pipeline")


@dataclass
class LayoutAnalysisResult:
    """Result from LayoutLMv3 analysis."""
    text_blocks: List[Dict[str, Any]]
    entities: List[Dict[str, Any]]
    confidence_scores: List[float]
    processing_time_ms: int
    image_dimensions: Tuple[int, int]


@dataclass
class InvoiceExtractionResult:
    """Result from Llama-3-8B extraction."""
    invoice_ids: List[str]
    confidence_score: float
    reasoning: str
    pattern_matches: Dict[str, List[str]]
    processing_time_ms: int


class LayoutLMv3Analyzer:
    """LayoutLMv3-based OCR and layout analysis."""
    
    def __init__(self, model_path: str = "microsoft/layoutlmv3-base"):
        self.model_path = model_path
        self.processor = None
        self.tokenizer = None
        self.model = None
        self.device = None
        
    async def initialize(self):
        """Initialize LayoutLMv3 model and processor."""
        try:
            logger.info(f"Loading LayoutLMv3 model from {self.model_path}")
            
            # Set device
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            logger.info(f"Using device: {self.device}")
            
            # Load processor and tokenizer
            self.processor = LayoutLMv3Processor.from_pretrained(
                self.model_path,
                cache_dir="/app/models/cache"
            )
            self.tokenizer = LayoutLMv3TokenizerFast.from_pretrained(
                self.model_path,
                cache_dir="/app/models/cache"
            )
            
            # Load model with optimization for inference
            self.model = LayoutLMv3ForTokenClassification.from_pretrained(
                self.model_path,
                cache_dir="/app/models/cache",
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                device_map="auto" if torch.cuda.is_available() else None
            )
            
            if torch.cuda.is_available():
                self.model = self.model.to(self.device)
            
            self.model.eval()  # Set to evaluation mode
            
            logger.info("LayoutLMv3 model loaded successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize LayoutLMv3: {e}")
            raise ModelLoadError(f"LayoutLMv3 initialization failed: {e}")
    
    async def analyze_document(self, image: Image.Image) -> LayoutAnalysisResult:
        """Analyze document layout and extract structured text."""
        start_time = time.time()
        
        try:
            with torch.no_grad():
                # Process image and extract text with OCR
                encoding = self.processor(
                    image, 
                    return_tensors="pt",
                    truncation=True,
                    max_length=512
                )
                
                # Move to device
                if self.device.type == "cuda":
                    encoding = {k: v.to(self.device) for k, v in encoding.items()}
                
                # Run inference
                with MODEL_INFERENCE_TIME.labels(
                    model_name="layoutlmv3", 
                    input_type="document_image"
                ).time():
                    outputs = self.model(**encoding)
                
                # Process predictions
                predictions = torch.nn.functional.softmax(outputs.logits, dim=-1)
                predicted_token_class = predictions.argmax(-1).squeeze().tolist()
                
                # Extract text blocks with positions
                text_blocks = self._extract_text_blocks(encoding, predicted_token_class, image.size)
                
                # Identify entities (tables, headers, etc.)
                entities = self._identify_entities(text_blocks, predicted_token_class)
                
                # Calculate confidence scores
                confidence_scores = self._calculate_confidence_scores(predictions)
                
                processing_time_ms = int((time.time() - start_time) * 1000)
                
                return LayoutAnalysisResult(
                    text_blocks=text_blocks,
                    entities=entities,
                    confidence_scores=confidence_scores,
                    processing_time_ms=processing_time_ms,
                    image_dimensions=image.size
                )
                
        except Exception as e:
            logger.error(f"LayoutLMv3 analysis failed: {e}")
            raise DocumentProcessingError(f"Layout analysis failed: {e}")
    
    def _extract_text_blocks(self, encoding, predictions, image_size) -> List[Dict[str, Any]]:
        """Extract text blocks with bounding boxes."""
        text_blocks = []
        
        # Get tokens and boxes
        tokens = self.tokenizer.convert_ids_to_tokens(encoding["input_ids"].squeeze())
        boxes = encoding["bbox"].squeeze().tolist()
        
        current_block = {"text": "", "bbox": None, "tokens": []}
        
        for token, box, pred in zip(tokens, boxes, predictions):
            if token in ["[CLS]", "[SEP]", "[PAD]"]:
                continue
                
            # Normalize coordinates to image size
            normalized_box = [
                box[0] / 1000 * image_size[0],
                box[1] / 1000 * image_size[1], 
                box[2] / 1000 * image_size[0],
                box[3] / 1000 * image_size[1]
            ]
            
            # Clean token (remove ## prefix from subwords)
            clean_token = token.replace("##", "")
            
            current_block["tokens"].append({
                "text": clean_token,
                "bbox": normalized_box,
                "prediction": pred
            })
            current_block["text"] += clean_token
            
            # Update block bounding box
            if current_block["bbox"] is None:
                current_block["bbox"] = normalized_box[:]
            else:
                current_block["bbox"][0] = min(current_block["bbox"][0], normalized_box[0])
                current_block["bbox"][1] = min(current_block["bbox"][1], normalized_box[1])
                current_block["bbox"][2] = max(current_block["bbox"][2], normalized_box[2])
                current_block["bbox"][3] = max(current_block["bbox"][3], normalized_box[3])
        
        if current_block["text"]:
            text_blocks.append(current_block)
        
        return text_blocks
    
    def _identify_entities(self, text_blocks, predictions) -> List[Dict[str, Any]]:
        """Identify document entities like tables, headers."""
        entities = []
        
        # Simple entity detection based on layout patterns
        for block in text_blocks:
            block_text = block["text"].strip()
            bbox = block["bbox"]
            
            # Header detection (top of page, large text)
            if bbox[1] < 100 and len(block_text) > 5:
                entities.append({
                    "type": "header",
                    "text": block_text,
                    "bbox": bbox,
                    "confidence": 0.8
                })
            
            # Table detection (structured layout)
            elif self._is_table_like(block_text):
                entities.append({
                    "type": "table",
                    "text": block_text,
                    "bbox": bbox,
                    "confidence": 0.7
                })
            
            # Invoice number patterns
            elif self._contains_invoice_pattern(block_text):
                entities.append({
                    "type": "invoice_reference",
                    "text": block_text,
                    "bbox": bbox,
                    "confidence": 0.9
                })
        
        return entities
    
    def _calculate_confidence_scores(self, predictions) -> List[float]:
        """Calculate confidence scores for predictions."""
        max_probs = predictions.max(dim=-1)[0]
        return max_probs.mean(dim=-1).tolist()
    
    def _is_table_like(self, text: str) -> bool:
        """Detect if text represents table data."""
        # Simple heuristics for table detection
        lines = text.split('\n')
        if len(lines) < 2:
            return False
        
        # Look for consistent column patterns
        tab_count = sum(1 for line in lines if '\t' in line)
        space_patterns = sum(1 for line in lines if len(re.findall(r'\s{2,}', line)) >= 2)
        
        return (tab_count / len(lines)) > 0.5 or (space_patterns / len(lines)) > 0.5
    
    def _contains_invoice_pattern(self, text: str) -> bool:
        """Check if text contains invoice number patterns."""
        invoice_patterns = [
            r'INV[#-]?\d+',
            r'Invoice\s*[#:]?\s*\d+',
            r'PO[#-]?\d+',
            r'Purchase\s*Order\s*[#:]?\s*\d+',
            r'\b\d{4,8}\b'  # Numeric sequences
        ]
        
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in invoice_patterns)


class LlamaInvoiceExtractor:
    """Llama-3-8B based invoice ID extraction."""
    
    def __init__(self, model_path: str = "meta-llama/Llama-3-8B"):
        self.model_path = model_path
        self.tokenizer = None
        self.model = None
        self.device = None
        
    async def initialize(self):
        """Initialize Llama-3-8B model."""
        try:
            logger.info(f"Loading Llama-3-8B model from {self.model_path}")
            
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            
            # Configure quantization for efficient inference
            if torch.cuda.is_available():
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_use_double_quant=True
                )
            else:
                quantization_config = None
            
            # Load tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_path,
                cache_dir="/app/models/cache"
            )
            
            # Ensure pad token exists
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token
            
            # Load model
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                cache_dir="/app/models/cache",
                quantization_config=quantization_config,
                device_map="auto" if torch.cuda.is_available() else None,
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                trust_remote_code=True
            )
            
            self.model.eval()
            
            logger.info("Llama-3-8B model loaded successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Llama-3-8B: {e}")
            raise ModelLoadError(f"Llama-3-8B initialization failed: {e}")
    
    async def extract_invoice_ids(self, layout_result: LayoutAnalysisResult) -> InvoiceExtractionResult:
        """Extract invoice IDs using contextual understanding."""
        start_time = time.time()
        
        try:
            # Prepare structured input for Llama
            structured_input = self._prepare_structured_input(layout_result)
            
            # Create extraction prompt
            prompt = self._create_extraction_prompt(structured_input)
            
            # Run inference
            with MODEL_INFERENCE_TIME.labels(
                model_name="llama3-8b",
                input_type="structured_document"
            ).time():
                result = await self._run_inference(prompt)
            
            # Parse and validate results
            invoice_ids, confidence, reasoning, patterns = self._parse_extraction_result(result)
            
            processing_time_ms = int((time.time() - start_time) * 1000)
            
            return InvoiceExtractionResult(
                invoice_ids=invoice_ids,
                confidence_score=confidence,
                reasoning=reasoning,
                pattern_matches=patterns,
                processing_time_ms=processing_time_ms
            )
            
        except Exception as e:
            logger.error(f"Invoice extraction failed: {e}")
            raise DocumentProcessingError(f"Invoice ID extraction failed: {e}")
    
    def _prepare_structured_input(self, layout_result: LayoutAnalysisResult) -> Dict[str, Any]:
        """Prepare structured input from LayoutLMv3 results."""
        # Extract high-confidence text blocks
        text_blocks = []
        for block in layout_result.text_blocks:
            if block["text"].strip():
                text_blocks.append({
                    "text": block["text"].strip(),
                    "position": "header" if block["bbox"][1] < 100 else "body"
                })
        
        # Extract entities with invoice patterns
        invoice_entities = [
            entity for entity in layout_result.entities 
            if entity["type"] == "invoice_reference"
        ]
        
        return {
            "text_blocks": text_blocks,
            "invoice_entities": invoice_entities,
            "document_structure": self._analyze_document_structure(layout_result)
        }
    
    def _create_extraction_prompt(self, structured_input: Dict[str, Any]) -> str:
        """Create extraction prompt for Llama."""
        prompt = """You are an expert at extracting invoice numbers from financial documents. 

Document Content:
"""
        
        # Add text blocks
        for i, block in enumerate(structured_input["text_blocks"][:10]):  # Limit context
            prompt += f"Block {i+1} ({block['position']}): {block['text']}\n"
        
        prompt += """
Task: Extract all invoice numbers from this document. Look for patterns like:
- INV-12345, Invoice #12345
- PO-67890, Purchase Order 67890  
- Numeric sequences that represent invoices
- References in remittance advice format

IMPORTANT: Return ONLY a valid JSON object with this exact structure:
{
    "invoice_ids": ["list", "of", "found", "invoice", "numbers"],
    "confidence": 0.95,
    "reasoning": "Brief explanation of findings",
    "patterns_found": {
        "inv_pattern": ["matches"],
        "po_pattern": ["matches"],
        "numeric_pattern": ["matches"]
    }
}

DO NOT OUTPUT ANYTHING OTHER THAN VALID JSON."""
        
        return prompt
    
    async def _run_inference(self, prompt: str) -> str:
        """Run Llama inference with the prompt."""
        try:
            # Tokenize input
            inputs = self.tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=2048,
                padding=True
            )
            
            if self.device.type == "cuda":
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            # Generate response
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=512,
                    do_sample=True,
                    temperature=0.1,  # Low temperature for consistency
                    top_p=0.9,
                    pad_token_id=self.tokenizer.eos_token_id,
                    eos_token_id=self.tokenizer.eos_token_id
                )
            
            # Decode response
            response = self.tokenizer.decode(
                outputs[0][inputs["input_ids"].shape[1]:], 
                skip_special_tokens=True
            )
            
            return response.strip()
            
        except Exception as e:
            logger.error(f"Llama inference failed: {e}")
            raise DocumentProcessingError(f"Model inference failed: {e}")
    
    def _parse_extraction_result(self, result: str) -> Tuple[List[str], float, str, Dict[str, List[str]]]:
        """Parse and validate the extraction result."""
        try:
            # Extract JSON from response (handle cases where model adds extra text)
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if not json_match:
                raise ValueError("No JSON found in response")
            
            json_str = json_match.group(0)
            parsed = json.loads(json_str)
            
            # Extract and validate fields
            invoice_ids = parsed.get("invoice_ids", [])
            confidence = float(parsed.get("confidence", 0.0))
            reasoning = parsed.get("reasoning", "No reasoning provided")
            patterns = parsed.get("patterns_found", {})
            
            # Validate invoice IDs
            validated_ids = self._validate_invoice_ids(invoice_ids)
            
            # Adjust confidence based on validation
            if len(validated_ids) < len(invoice_ids):
                confidence *= 0.8  # Reduce confidence if some IDs were invalid
            
            return validated_ids, min(confidence, 1.0), reasoning, patterns
            
        except Exception as e:
            logger.warning(f"Failed to parse extraction result: {e}, falling back to regex")
            # Fallback to regex extraction
            return self._fallback_extraction(result)
    
    def _validate_invoice_ids(self, invoice_ids: List[str]) -> List[str]:
        """Validate extracted invoice IDs."""
        validated = []
        
        for inv_id in invoice_ids:
            if not isinstance(inv_id, str):
                continue
            
            inv_id = inv_id.strip()
            if not inv_id:
                continue
            
            # Basic validation patterns
            if (len(inv_id) >= 3 and 
                (re.match(r'^[A-Z]{2,4}[-#]?\d+$', inv_id, re.IGNORECASE) or
                 re.match(r'^\d{4,}$', inv_id))):
                validated.append(inv_id.upper())
        
        return list(set(validated))  # Remove duplicates
    
    def _fallback_extraction(self, text: str) -> Tuple[List[str], float, str, Dict[str, List[str]]]:
        """Fallback regex-based extraction."""
        patterns = {
            "inv_pattern": re.findall(r'INV[#-]?(\d+)', text, re.IGNORECASE),
            "po_pattern": re.findall(r'PO[#-]?(\d+)', text, re.IGNORECASE),
            "numeric_pattern": re.findall(r'\b(\d{4,8})\b', text)
        }
        
        all_ids = []
        for pattern_ids in patterns.values():
            all_ids.extend(pattern_ids)
        
        validated_ids = self._validate_invoice_ids(all_ids)
        confidence = 0.6 if validated_ids else 0.0
        
        return validated_ids, confidence, "Fallback regex extraction", patterns
    
    def _analyze_document_structure(self, layout_result: LayoutAnalysisResult) -> Dict[str, Any]:
        """Analyze document structure for context."""
        return {
            "has_header": any(e["type"] == "header" for e in layout_result.entities),
            "has_table": any(e["type"] == "table" for e in layout_result.entities),
            "text_block_count": len(layout_result.text_blocks),
            "avg_confidence": sum(layout_result.confidence_scores) / len(layout_result.confidence_scores) if layout_result.confidence_scores else 0.0
        }


class MLPipeline:
    """Main ML pipeline orchestrating both stages."""
    
    def __init__(self, model_manager=None):
        self.model_manager = model_manager
        self.layoutlmv3_analyzer = LayoutLMv3Analyzer()
        self.llama_extractor = LlamaInvoiceExtractor()
        self._initialized = False
        
    async def initialize(self):
        """Initialize the complete ML pipeline."""
        try:
            logger.info("Initializing ML Pipeline...")
            
            # Initialize both models
            await self.layoutlmv3_analyzer.initialize()
            await self.llama_extractor.initialize()
            
            self._initialized = True
            logger.info("ML Pipeline initialized successfully")
            
        except Exception as e:
            logger.error(f"ML Pipeline initialization failed: {e}")
            raise ModelLoadError(f"Pipeline initialization failed: {e}")
    
    async def process_document(self, image: Image.Image) -> InvoiceExtractionResult:
        """Process document through the complete 2-stage pipeline."""
        if not self._initialized:
            raise ModelLoadError("ML Pipeline not initialized")
        
        try:
            logger.info("Starting 2-stage document processing")
            
            # Stage 1: Layout analysis with LayoutLMv3
            logger.debug("Stage 1: Running LayoutLMv3 analysis")
            layout_result = await self.layoutlmv3_analyzer.analyze_document(image)
            
            # Stage 2: Invoice extraction with Llama-3-8B
            logger.debug("Stage 2: Running Llama-3-8B extraction")
            extraction_result = await self.llama_extractor.extract_invoice_ids(layout_result)
            
            logger.info(
                f"Document processing completed: {len(extraction_result.invoice_ids)} invoice IDs found "
                f"with confidence {extraction_result.confidence_score:.2f}"
            )
            
            return extraction_result
            
        except Exception as e:
            logger.error(f"Document processing pipeline failed: {e}")
            raise DocumentProcessingError(f"Pipeline processing failed: {e}")
    
    def is_healthy(self) -> bool:
        """Check if pipeline is healthy and ready."""
        return (self._initialized and 
                self.layoutlmv3_analyzer.model is not None and
                self.llama_extractor.model is not None)
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get detailed health status."""
        gpu_available = torch.cuda.is_available()
        gpu_memory = 0
        
        if gpu_available:
            try:
                gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)  # GB
            except:
                gpu_memory = 0
        
        return {
            "layoutlmv3_loaded": self.layoutlmv3_analyzer.model is not None,
            "llama_loaded": self.llama_extractor.model is not None,
            "gpu_available": gpu_available,
            "memory_usage_mb": gpu_memory * 1024,
            "model_versions": {
                "layoutlmv3": self.layoutlmv3_analyzer.model_path,
                "llama": self.llama_extractor.model_path
            }
        }
    
    async def reload_models(self):
        """Reload models (for updates/maintenance)."""
        logger.info("Reloading ML models...")
        
        try:
            # Cleanup existing models
            await self.cleanup()
            
            # Reinitialize
            await self.initialize()
            
            logger.info("Models reloaded successfully")
            
        except Exception as e:
            logger.error(f"Model reload failed: {e}")
            raise ModelLoadError(f"Model reload failed: {e}")
    
    async def cleanup(self):
        """Cleanup resources."""
        try:
            # Clear GPU memory
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            # Reset models
            self.layoutlmv3_analyzer.model = None
            self.llama_extractor.model = None
            self._initialized = False
            
            logger.info("ML Pipeline cleanup completed")
            
        except Exception as e:
            logger.warning(f"Cleanup warning: {e}")
