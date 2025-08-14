# services/dim/document_processor.py
"""
Document Processor - Orchestration layer for document processing
Handles document download, format conversion, and ML pipeline orchestration
"""

import asyncio
import hashlib
import logging
import mimetypes
import tempfile
import time
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import io

import aiohttp
from PIL import Image
import pdf2image
import fitz  # PyMuPDF for PDF processing

from shared.logging import setup_logging, log_context
from shared.exceptions import DocumentProcessingError, ValidationError
from shared.models import DocumentParseResult, DocumentAnalysisResult
from ml_pipeline import MLPipeline, InvoiceExtractionResult
from azure_storage import AzureBlobStorageClient

logger = setup_logging("dim-document-processor")


class DocumentProcessor:
    """Orchestrates document processing workflow."""
    
    def __init__(self, ml_pipeline: MLPipeline, storage_client: AzureBlobStorageClient, db_manager=None):
        self.ml_pipeline = ml_pipeline
        self.storage_client = storage_client
        self.db_manager = db_manager
        
        # Processing configuration
        self.max_file_size_mb = 50
        self.supported_formats = {'.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.bmp'}
        self.max_pages_per_document = 10
        self.processing_timeout_seconds = 120
        
    async def process_documents(
        self,
        document_uris: List[str],
        client_id: Optional[str] = None,
        processing_options: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None
    ) -> DocumentParseResult:
        """Process multiple documents and extract invoice IDs."""
        start_time = time.time()
        
        try:
            with log_context(correlation_id=correlation_id, service="dim-processor"):
                logger.info(
                    f"Processing {len(document_uris)} documents",
                    extra={
                        "document_count": len(document_uris),
                        "client_id": client_id,
                        "correlation_id": correlation_id
                    }
                )
                
                # Process documents concurrently
                semaphore = asyncio.Semaphore(3)  # Limit concurrent processing
                tasks = [
                    self._process_single_document(uri, semaphore, correlation_id)
                    for uri in document_uris
                ]
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Aggregate results
                all_invoice_ids = []
                document_analysis = []
                warnings = []
                confidence_scores = []
                
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.error(
                            f"Failed to process document {document_uris[i]}: {result}",
                            extra={"correlation_id": correlation_id}
                        )
                        warnings.append(f"Failed to process document {i+1}: {str(result)}")
                        document_analysis.append({
                            "document_uri": document_uris[i],
                            "status": "error",
                            "error": str(result)
                        })
                    else:
                        # Extract results
                        invoice_ids, analysis, confidence = result
                        all_invoice_ids.extend(invoice_ids)
                        document_analysis.append(analysis)
                        confidence_scores.append(confidence)
                
                # Calculate overall confidence
                overall_confidence = (
                    sum(confidence_scores) / len(confidence_scores) 
                    if confidence_scores else 0.0
                )
                
                # Remove duplicates while preserving order
                unique_invoice_ids = list(dict.fromkeys(all_invoice_ids))
                
                processing_duration_ms = int((time.time() - start_time) * 1000)
                
                # Log processing summary
                logger.info(
                    f"Document processing completed",
                    extra={
                        "total_documents": len(document_uris),
                        "successful_documents": len([r for r in results if not isinstance(r, Exception)]),
                        "unique_invoice_ids": len(unique_invoice_ids),
                        "overall_confidence": overall_confidence,
                        "processing_duration_ms": processing_duration_ms,
                        "correlation_id": correlation_id
                    }
                )
                
                return DocumentParseResult(
                    invoice_ids=unique_invoice_ids,
                    confidence_score=overall_confidence,
                    document_analysis=document_analysis,
                    warnings=warnings,
                    processing_duration_ms=processing_duration_ms
                )
                
        except Exception as e:
            logger.error(
                f"Document processing failed: {e}",
                extra={"correlation_id": correlation_id}
            )
            raise DocumentProcessingError(f"Document processing failed: {e}")
    
    async def extract_invoice_ids_only(
        self,
        document_uris: List[str],
        correlation_id: Optional[str] = None
    ) -> DocumentParseResult:
        """Simplified extraction - invoice IDs only without detailed analysis."""
        try:
            # Use streamlined processing
            result = await self.process_documents(
                document_uris=document_uris,
                processing_options={"detailed_analysis": False},
                correlation_id=correlation_id
            )
            
            return DocumentParseResult(
                invoice_ids=result.invoice_ids,
                confidence_score=result.confidence_score,
                document_analysis=[],
                warnings=[],
                processing_duration_ms=result.processing_duration_ms
            )
            
        except Exception as e:
            logger.error(f"Invoice ID extraction failed: {e}")
            raise DocumentProcessingError(f"Extraction failed: {e}")
    
    async def _process_single_document(
        self,
        document_uri: str,
        semaphore: asyncio.Semaphore,
        correlation_id: Optional[str] = None
    ) -> Tuple[List[str], Dict[str, Any], float]:
        """Process a single document."""
        async with semaphore:
            start_time = time.time()
            
            try:
                logger.debug(
                    f"Processing document: {document_uri}",
                    extra={"correlation_id": correlation_id}
                )
                
                # Download document
                document_data, file_info = await self._download_document(document_uri)
                
                # Validate document
                self._validate_document(document_data, file_info)
                
                # Convert to images
                images = await self._convert_to_images(document_data, file_info)
                
                # Process through ML pipeline
                all_invoice_ids = []
                confidence_scores = []
                
                for i, image in enumerate(images):
                    logger.debug(f"Processing page {i+1}/{len(images)}")
                    
                    # Run ML pipeline
                    extraction_result = await self.ml_pipeline.process_document(image)
                    
                    all_invoice_ids.extend(extraction_result.invoice_ids)
                    confidence_scores.append(extraction_result.confidence_score)
                
                # Calculate document-level confidence
                avg_confidence = (
                    sum(confidence_scores) / len(confidence_scores)
                    if confidence_scores else 0.0
                )
                
                # Remove duplicates
                unique_invoice_ids = list(dict.fromkeys(all_invoice_ids))
                
                processing_time_ms = int((time.time() - start_time) * 1000)
                
                # Create analysis result
                analysis = DocumentAnalysisResult(
                    document_uri=document_uri,
                    status="success",
                    pages_processed=len(images),
                    invoice_ids_found=len(unique_invoice_ids),
                    confidence_score=avg_confidence,
                    processing_time_ms=processing_time_ms,
                    file_info=file_info
                )
                
                logger.debug(
                    f"Document processed successfully: {len(unique_invoice_ids)} invoice IDs found",
                    extra={
                        "invoice_count": len(unique_invoice_ids),
                        "confidence": avg_confidence,
                        "correlation_id": correlation_id
                    }
                )
                
                return unique_invoice_ids, analysis.__dict__, avg_confidence
                
            except Exception as e:
                processing_time_ms = int((time.time() - start_time) * 1000)
                logger.error(
                    f"Single document processing failed: {e}",
                    extra={"document_uri": document_uri, "correlation_id": correlation_id}
                )
                
                analysis = DocumentAnalysisResult(
                    document_uri=document_uri,
                    status="error",
                    error=str(e),
                    processing_time_ms=processing_time_ms
                )
                
                raise DocumentProcessingError(f"Document processing failed: {e}")
    
    async def _download_document(self, document_uri: str) -> Tuple[bytes, Dict[str, Any]]:
        """Download document from URI."""
        try:
            if document_uri.startswith('https://') and 'blob.core.windows.net' in document_uri:
                # Azure Blob Storage
                return await self.storage_client.download_blob(document_uri)
            else:
                # Generic HTTP download
                return await self._download_http(document_uri)
                
        except Exception as e:
            logger.error(f"Failed to download document from {document_uri}: {e}")
            raise DocumentProcessingError(f"Document download failed: {e}")
    
    async def _download_http(self, url: str) -> Tuple[bytes, Dict[str, Any]]:
        """Download document via HTTP."""
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        raise DocumentProcessingError(f"HTTP {response.status}: Failed to download")
                    
                    # Get file info
                    content_type = response.headers.get('Content-Type', 'application/octet-stream')
                    content_length = int(response.headers.get('Content-Length', 0))
                    
                    # Read content
                    document_data = await response.read()
                    
                    file_info = {
                        "content_type": content_type,
                        "size_bytes": len(document_data),
                        "reported_size_bytes": content_length,
                        "source": "http_download"
                    }
                    
                    return document_data, file_info
                    
        except Exception as e:
            raise DocumentProcessingError(f"HTTP download failed: {e}")
    
    def _validate_document(self, document_data: bytes, file_info: Dict[str, Any]):
        """Validate document before processing."""
        # Size validation
        size_mb = len(document_data) / (1024 * 1024)
        if size_mb > self.max_file_size_mb:
            raise ValidationError(
                f"Document too large: {size_mb:.1f}MB (max: {self.max_file_size_mb}MB)"
            )
        
        # Format validation
        file_extension = self._detect_file_format(document_data, file_info.get('content_type'))
        if file_extension not in self.supported_formats:
            raise ValidationError(
                f"Unsupported file format: {file_extension} "
                f"(supported: {', '.join(self.supported_formats)})"
            )
        
        # Content validation
        if len(document_data) == 0:
            raise ValidationError("Empty document")
    
    def _detect_file_format(self, data: bytes, content_type: str = None) -> str:
        """Detect file format from data and content type."""
        # Check magic bytes
        if data.startswith(b'%PDF'):
            return '.pdf'
        elif data.startswith(b'\x89PNG'):
            return '.png'
        elif data.startswith(b'\xff\xd8\xff'):
            return '.jpg'
        elif data.startswith(b'II*\x00') or data.startswith(b'MM\x00*'):
            return '.tiff'
        elif data.startswith(b'BM'):
            return '.bmp'
        
        # Fallback to content type
        if content_type:
            extension = mimetypes.guess_extension(content_type)
            if extension:
                return extension
        
        return '.unknown'
    
    async def _convert_to_images(self, document_data: bytes, file_info: Dict[str, Any]) -> List[Image.Image]:
        """Convert document to images for processing."""
        file_extension = self._detect_file_format(document_data, file_info.get('content_type'))
        
        try:
            if file_extension == '.pdf':
                return await self._convert_pdf_to_images(document_data)
            else:
                # Already an image
                image = Image.open(io.BytesIO(document_data))
                return [image.convert('RGB')]
                
        except Exception as e:
            logger.error(f"Failed to convert document to images: {e}")
            raise DocumentProcessingError(f"Document conversion failed: {e}")
    
    async def _convert_pdf_to_images(self, pdf_data: bytes) -> List[Image.Image]:
        """Convert PDF to images using PyMuPDF for better performance."""
        try:
            # Use PyMuPDF for better performance and memory usage
            doc = fitz.open(stream=pdf_data, filetype="pdf")
            images = []
            
            page_count = min(len(doc), self.max_pages_per_document)
            logger.debug(f"Converting {page_count} pages from PDF")
            
            for page_num in range(page_count):
                # Get page
                page = doc.load_page(page_num)
                
                # Render to pixmap (high resolution for better OCR)
                mat = fitz.Matrix(2.0, 2.0)  # 2x scaling for better quality
                pix = page.get_pixmap(matrix=mat)
                
                # Convert to PIL Image
                img_data = pix.tobytes("ppm")
                image = Image.open(io.BytesIO(img_data))
                images.append(image.convert('RGB'))
                
                logger.debug(f"Converted page {page_num + 1} ({image.size})")
            
            doc.close()
            
            if not images:
                raise DocumentProcessingError("No pages found in PDF")
            
            return images
            
        except Exception as e:
            logger.error(f"PDF conversion failed: {e}")
            # Fallback to pdf2image
            try:
                return await self._convert_pdf_fallback(pdf_data)
            except:
                raise DocumentProcessingError(f"PDF conversion failed: {e}")
    
    async def _convert_pdf_fallback(self, pdf_data: bytes) -> List[Image.Image]:
        """Fallback PDF conversion using pdf2image."""
        try:
            with tempfile.NamedTemporaryFile(suffix='.pdf') as temp_file:
                temp_file.write(pdf_data)
                temp_file.flush()
                
                # Convert with pdf2image
                images = pdf2image.convert_from_path(
                    temp_file.name,
                    dpi=200,  # Good balance of quality and processing speed
                    first_page=1,
                    last_page=min(self.max_pages_per_document, 50)  # Safety limit
                )
                
                return [img.convert('RGB') for img in images]
                
        except Exception as e:
            raise DocumentProcessingError(f"Fallback PDF conversion failed: {e}")


class DocumentAnalysisResult:
    """Result of document analysis."""
    
    def __init__(
        self,
        document_uri: str,
        status: str,
        pages_processed: int = 0,
        invoice_ids_found: int = 0,
        confidence_score: float = 0.0,
        processing_time_ms: int = 0,
        file_info: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ):
        self.document_uri = document_uri
        self.status = status
        self.pages_processed = pages_processed
        self.invoice_ids_found = invoice_ids_found
        self.confidence_score = confidence_score
        self.processing_time_ms = processing_time_ms
        self.file_info = file_info or {}
        self.error = error
        self.timestamp = time.time()
    
    def __dict__(self):
        return {
            "document_uri": self.document_uri,
            "status": self.status,
            "pages_processed": self.pages_processed,
            "invoice_ids_found": self.invoice_ids_found,
            "confidence_score": self.confidence_score,
            "processing_time_ms": self.processing_time_ms,
            "file_info": self.file_info,
            "error": self.error,
            "timestamp": self.timestamp
        }
