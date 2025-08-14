"""
Tesseract OCR Engine for CashApp Document Intelligence
Provides free, open-source OCR capabilities with optimization for invoice processing
"""

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
import cv2
import numpy as np
import re
import logging
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
import os
from pathlib import Path
import io
import base64

logger = logging.getLogger(__name__)

@dataclass
class OCRResult:
    """Result from OCR processing"""
    text: str
    confidence: float
    bounding_boxes: List[Dict]
    processing_time_ms: int
    quality_score: float

@dataclass
class InvoiceData:
    """Extracted invoice data structure"""
    invoice_ids: List[str]
    amounts: List[float]
    dates: List[str]
    vendors: List[str]
    confidence: float
    raw_text: str

class TesseractEngine:
    """
    Tesseract-based OCR engine optimized for invoice processing
    """
    
    def __init__(self, tesseract_config: Dict[str, Any] = None):
        """
        Initialize Tesseract engine
        
        Args:
            tesseract_config: Configuration for Tesseract
        """
        self.config = tesseract_config or {
            'oem': 3,  # LSTM OCR Engine Mode
            'psm': 6,  # Uniform block of text
            'lang': 'eng',
            'dpi': 300,
            'timeout': 60
        }
        
        # Configure Tesseract command line options
        self.tesseract_cmd = self._build_tesseract_config()
        
        # Regex patterns for common invoice elements
        self.patterns = {
            'invoice_number': [
                r'invoice\s*#?\s*:?\s*([a-zA-Z0-9\-]+)',
                r'inv\s*#?\s*:?\s*([a-zA-Z0-9\-]+)',
                r'bill\s*#?\s*:?\s*([a-zA-Z0-9\-]+)',
                r'#\s*([0-9]{6,})',
                r'([a-zA-Z]{2,4}[0-9]{4,})'
            ],
            'amount': [
                r'\$\s*([0-9,]+\.?[0-9]*)',
                r'total\s*:?\s*\$?\s*([0-9,]+\.?[0-9]*)',
                r'amount\s*:?\s*\$?\s*([0-9,]+\.?[0-9]*)',
                r'([0-9,]+\.[0-9]{2})'
            ],
            'date': [
                r'([0-1]?[0-9]/[0-3]?[0-9]/[0-9]{2,4})',
                r'([0-1]?[0-9]-[0-3]?[0-9]-[0-9]{2,4})',
                r'([0-9]{2,4}-[0-1]?[0-9]-[0-3]?[0-9])',
                r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+[0-9]{1,2},?\s+[0-9]{2,4})'
            ],
            'vendor': [
                r'from\s*:?\s*([a-zA-Z\s&]+)',
                r'vendor\s*:?\s*([a-zA-Z\s&]+)',
                r'company\s*:?\s*([a-zA-Z\s&]+)'
            ]
        }
        
        # Initialize Tesseract (check if available)
        self._validate_tesseract_installation()
    
    def _build_tesseract_config(self) -> str:
        """Build Tesseract configuration string"""
        config_parts = []
        
        if 'oem' in self.config:
            config_parts.append(f"--oem {self.config['oem']}")
        
        if 'psm' in self.config:
            config_parts.append(f"--psm {self.config['psm']}")
        
        if 'lang' in self.config:
            config_parts.append(f"-l {self.config['lang']}")
        
        # Add whitelist for common characters in invoices
        config_parts.append("-c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!@#$%^&*()_+-=[]{}|;':\",./<>?`~ ")
        
        return " ".join(config_parts)
    
    def _validate_tesseract_installation(self):
        """Validate that Tesseract is properly installed"""
        try:
            version = pytesseract.get_tesseract_version()
            logger.info(f"Tesseract version: {version}")
        except Exception as e:
            logger.error(f"Tesseract not properly installed: {e}")
            raise RuntimeError("Tesseract OCR not available. Please install tesseract-ocr package.")
    
    def assess_document_quality(self, image_path: str) -> float:
        """
        Assess document quality for OCR processing
        
        Args:
            image_path: Path to image file
            
        Returns:
            Quality score from 0.0 to 1.0
        """
        try:
            image = cv2.imread(image_path)
            if image is None:
                return 0.0
            
            # Convert to grayscale
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            
            # Calculate various quality metrics
            scores = []
            
            # 1. Sharpness (Laplacian variance)
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            sharpness_score = min(laplacian_var / 1000, 1.0)  # Normalize
            scores.append(sharpness_score)
            
            # 2. Contrast (standard deviation)
            contrast_score = min(gray.std() / 100, 1.0)  # Normalize
            scores.append(contrast_score)
            
            # 3. Brightness (not too dark, not too bright)
            mean_brightness = gray.mean()
            brightness_score = 1.0 - abs(mean_brightness - 128) / 128
            scores.append(brightness_score)
            
            # 4. Resolution quality
            height, width = gray.shape
            resolution_score = min((height * width) / (1024 * 768), 1.0)  # Normalize to common resolution
            scores.append(resolution_score)
            
            # 5. Noise level (inverse of noise)
            noise_level = cv2.fastNlMeansDenoising(gray).var() / gray.var()
            noise_score = 1.0 - min(noise_level, 1.0)
            scores.append(noise_score)
            
            # Calculate weighted average
            weights = [0.3, 0.25, 0.2, 0.15, 0.1]  # Prioritize sharpness and contrast
            quality_score = sum(score * weight for score, weight in zip(scores, weights))
            
            logger.info(f"Document quality assessment: {quality_score:.2f}", extra={
                'sharpness': sharpness_score,
                'contrast': contrast_score,
                'brightness': brightness_score,
                'resolution': resolution_score,
                'noise': noise_score
            })
            
            return quality_score
            
        except Exception as e:
            logger.error(f"Error assessing document quality: {e}")
            return 0.0
    
    def preprocess_image(self, image_path: str, enhancement_level: str = 'medium') -> str:
        """
        Preprocess image for better OCR results
        
        Args:
            image_path: Path to input image
            enhancement_level: 'low', 'medium', or 'high'
            
        Returns:
            Path to preprocessed image
        """
        try:
            # Read image
            image = cv2.imread(image_path)
            
            if image is None:
                raise ValueError(f"Could not load image: {image_path}")
            
            # Convert to grayscale
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            
            # Apply preprocessing based on enhancement level
            if enhancement_level == 'low':
                processed = self._basic_preprocessing(gray)
            elif enhancement_level == 'medium':
                processed = self._medium_preprocessing(gray)
            else:  # high
                processed = self._advanced_preprocessing(gray)
            
            # Save preprocessed image
            base_name = Path(image_path).stem
            output_path = f"/tmp/{base_name}_preprocessed.png"
            cv2.imwrite(output_path, processed)
            
            return output_path
            
        except Exception as e:
            logger.error(f"Error preprocessing image: {e}")
            return image_path  # Return original if preprocessing fails
    
    def _basic_preprocessing(self, gray_image: np.ndarray) -> np.ndarray:
        """Basic image preprocessing"""
        # Resize if too small (improve OCR accuracy)
        height, width = gray_image.shape
        if width < 1000:
            scale_factor = 1000 / width
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            gray_image = cv2.resize(gray_image, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
        
        # Simple thresholding
        _, thresh = cv2.threshold(gray_image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        return thresh
    
    def _medium_preprocessing(self, gray_image: np.ndarray) -> np.ndarray:
        """Medium level preprocessing"""
        # Basic preprocessing first
        processed = self._basic_preprocessing(gray_image)
        
        # Noise removal
        denoised = cv2.fastNlMeansDenoising(processed)
        
        # Morphological operations to clean up
        kernel = np.ones((1, 1), np.uint8)
        cleaned = cv2.morphologyEx(denoised, cv2.MORPH_CLOSE, kernel)
        
        return cleaned
    
    def _advanced_preprocessing(self, gray_image: np.ndarray) -> np.ndarray:
        """Advanced preprocessing with multiple techniques"""
        # Start with medium preprocessing
        processed = self._medium_preprocessing(gray_image)
        
        # Additional enhancements
        # Contrast enhancement
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(processed)
        
        # Edge preservation smoothing
        smoothed = cv2.bilateralFilter(enhanced, 9, 75, 75)
        
        # Final thresholding
        _, final = cv2.threshold(smoothed, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        return final
    
    def extract_text(self, image_path: str, preprocess: bool = True) -> OCRResult:
        """
        Extract text from image using Tesseract
        
        Args:
            image_path: Path to image file
            preprocess: Whether to preprocess image
            
        Returns:
            OCR result with text and metadata
        """
        import time
        start_time = time.time()
        
        try:
            # Preprocess image if requested
            if preprocess:
                quality_score = self.assess_document_quality(image_path)
                enhancement_level = 'high' if quality_score < 0.6 else 'medium' if quality_score < 0.8 else 'low'
                processed_path = self.preprocess_image(image_path, enhancement_level)
            else:
                processed_path = image_path
                quality_score = 0.8  # Assume good quality if not assessed
            
            # Extract text using Tesseract
            image = Image.open(processed_path)
            
            # Get text with confidence data
            data = pytesseract.image_to_data(image, config=self.tesseract_cmd, output_type=pytesseract.Output.DICT)
            
            # Extract text
            text = pytesseract.image_to_string(image, config=self.tesseract_cmd).strip()
            
            # Calculate average confidence
            confidences = [int(conf) for conf in data['conf'] if int(conf) > 0]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0
            
            # Extract bounding boxes for high-confidence words
            bounding_boxes = []
            n_boxes = len(data['level'])
            for i in range(n_boxes):
                if int(data['conf'][i]) > 30:  # Only include confident detections
                    bounding_boxes.append({
                        'text': data['text'][i],
                        'confidence': int(data['conf'][i]),
                        'left': data['left'][i],
                        'top': data['top'][i],
                        'width': data['width'][i],
                        'height': data['height'][i]
                    })
            
            processing_time = int((time.time() - start_time) * 1000)
            
            # Clean up temporary files
            if preprocess and processed_path != image_path:
                try:
                    os.unlink(processed_path)
                except:
                    pass
            
            result = OCRResult(
                text=text,
                confidence=avg_confidence / 100.0,  # Convert to 0-1 scale
                bounding_boxes=bounding_boxes,
                processing_time_ms=processing_time,
                quality_score=quality_score
            )
            
            logger.info(f"Text extracted: {len(text)} characters, {avg_confidence:.1f}% confidence", extra={
                'processing_time_ms': processing_time,
                'quality_score': quality_score,
                'num_words': len(text.split())
            })
            
            return result
            
        except Exception as e:
            logger.error(f"Error extracting text: {e}")
            return OCRResult(
                text="",
                confidence=0.0,
                bounding_boxes=[],
                processing_time_ms=int((time.time() - start_time) * 1000),
                quality_score=0.0
            )
    
    def extract_invoice_data(self, text: str, confidence_threshold: float = 0.7) -> InvoiceData:
        """
        Extract structured invoice data from text
        
        Args:
            text: Raw text from OCR
            confidence_threshold: Minimum confidence for extraction
            
        Returns:
            Structured invoice data
        """
        try:
            # Clean text
            cleaned_text = self._clean_text(text)
            
            # Extract different fields
            invoice_ids = self._extract_invoice_numbers(cleaned_text)
            amounts = self._extract_amounts(cleaned_text)
            dates = self._extract_dates(cleaned_text)
            vendors = self._extract_vendors(cleaned_text)
            
            # Calculate overall confidence based on number of fields found
            found_fields = sum([
                len(invoice_ids) > 0,
                len(amounts) > 0,
                len(dates) > 0,
                len(vendors) > 0
            ])
            
            confidence = found_fields / 4.0  # 4 main fields
            
            result = InvoiceData(
                invoice_ids=invoice_ids,
                amounts=amounts,
                dates=dates,
                vendors=vendors,
                confidence=confidence,
                raw_text=text
            )
            
            logger.info(f"Invoice data extracted", extra={
                'invoice_ids': len(invoice_ids),
                'amounts': len(amounts),
                'dates': len(dates),
                'vendors': len(vendors),
                'confidence': confidence
            })
            
            return result
            
        except Exception as e:
            logger.error(f"Error extracting invoice data: {e}")
            return InvoiceData(
                invoice_ids=[],
                amounts=[],
                dates=[],
                vendors=[],
                confidence=0.0,
                raw_text=text
            )
    
    def _clean_text(self, text: str) -> str:
        """Clean and normalize text for better pattern matching"""
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text.strip())
        
        # Normalize currency symbols
        text = text.replace('$', '$').replace('USD', '$')
        
        # Normalize common OCR errors
        text = text.replace('0', 'O').replace('O', '0')  # Context-dependent
        text = text.replace('1', 'l').replace('l', '1')  # Context-dependent
        
        return text
    
    def _extract_invoice_numbers(self, text: str) -> List[str]:
        """Extract invoice numbers using patterns"""
        invoice_ids = []
        
        for pattern in self.patterns['invoice_number']:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if match and len(match) >= 4:  # Minimum length for invoice number
                    invoice_ids.append(match.strip())
        
        # Remove duplicates while preserving order
        return list(dict.fromkeys(invoice_ids))
    
    def _extract_amounts(self, text: str) -> List[float]:
        """Extract monetary amounts"""
        amounts = []
        
        for pattern in self.patterns['amount']:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    # Clean and convert to float
                    cleaned = match.replace(',', '').replace('$', '').strip()
                    amount = float(cleaned)
                    if 0.01 <= amount <= 1000000:  # Reasonable range
                        amounts.append(amount)
                except ValueError:
                    continue
        
        return sorted(list(set(amounts)), reverse=True)  # Return unique amounts, largest first
    
    def _extract_dates(self, text: str) -> List[str]:
        """Extract dates"""
        dates = []
        
        for pattern in self.patterns['date']:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if match:
                    dates.append(match.strip())
        
        return list(dict.fromkeys(dates))
    
    def _extract_vendors(self, text: str) -> List[str]:
        """Extract vendor names"""
        vendors = []
        
        for pattern in self.patterns['vendor']:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if match and len(match.strip()) > 2:
                    vendors.append(match.strip())
        
        return list(dict.fromkeys(vendors))
    
    def process_document_batch(self, image_paths: List[str]) -> List[InvoiceData]:
        """
        Process multiple documents in batch
        
        Args:
            image_paths: List of image file paths
            
        Returns:
            List of invoice data results
        """
        results = []
        
        for i, image_path in enumerate(image_paths):
            logger.info(f"Processing document {i+1}/{len(image_paths)}: {image_path}")
            
            try:
                # Extract text
                ocr_result = self.extract_text(image_path)
                
                # Extract invoice data
                if ocr_result.confidence > 0.3:  # Only process if OCR was reasonably successful
                    invoice_data = self.extract_invoice_data(ocr_result.text)
                    results.append(invoice_data)
                else:
                    logger.warning(f"Low OCR confidence for {image_path}: {ocr_result.confidence:.2f}")
                    results.append(InvoiceData([], [], [], [], 0.0, ocr_result.text))
                    
            except Exception as e:
                logger.error(f"Error processing document {image_path}: {e}")
                results.append(InvoiceData([], [], [], [], 0.0, ""))
        
        return results
    
    def get_capabilities(self) -> Dict[str, Any]:
        """Get engine capabilities and configuration"""
        return {
            'name': 'TesseractEngine',
            'version': pytesseract.get_tesseract_version(),
            'supported_formats': ['PNG', 'JPG', 'JPEG', 'TIFF', 'BMP', 'GIF'],
            'supported_languages': ['eng'],  # Can be expanded
            'features': {
                'text_extraction': True,
                'invoice_parsing': True,
                'quality_assessment': True,
                'batch_processing': True,
                'image_preprocessing': True,
                'confidence_scoring': True
            },
            'config': self.config,
            'cost': 0.0,  # Free!
            'avg_processing_time_ms': 2000,  # Estimate
            'accuracy_rate': 0.85  # Estimate for good quality documents
        }