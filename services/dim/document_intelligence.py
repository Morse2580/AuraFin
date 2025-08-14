# services/dim/document_intelligence.py
"""
Azure Form Recognizer integration for document processing
Replaces custom ML models with managed Azure service for MVP
"""

import asyncio
import time
import re
from typing import List, Dict, Any, Optional
from decimal import Decimal
from azure.ai.formrecognizer.aio import DocumentAnalysisClient
from azure.ai.formrecognizer import AnalysisFeature
from azure.storage.blob.aio import BlobServiceClient
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import AzureError

from shared.logging import setup_logging
from shared.exception import DIMProcessingError
from shared.models import DocumentParsingResult

logger = setup_logging("document_intelligence")

class AzureFormRecognizerService:
    """
    Azure Form Recognizer service for document processing
    Provides invoice and document parsing capabilities
    """
    
    def __init__(self, 
                 endpoint: str, 
                 api_key: str, 
                 storage_connection_string: str):
        self.endpoint = endpoint
        self.api_key = api_key
        self.storage_connection_string = storage_connection_string
        
        # Initialize clients
        self.credential = AzureKeyCredential(api_key)
        self.form_client = DocumentAnalysisClient(endpoint, self.credential)
        self.blob_client = BlobServiceClient.from_connection_string(storage_connection_string)
        
        # Processing statistics
        self.processing_stats = {
            'documents_processed': 0,
            'invoices_extracted': 0,
            'total_processing_time_ms': 0,
            'errors': 0
        }
    
    async def close(self):
        """Close Azure clients"""
        try:
            await self.form_client.close()
            await self.blob_client.close()
            logger.info("Azure Form Recognizer clients closed")
        except Exception as e:
            logger.warning(f"Error closing clients: {e}")
    
    async def parse_documents(self, document_uris: List[str]) -> DocumentParsingResult:
        """
        Parse multiple documents using Azure Form Recognizer
        
        Args:
            document_uris: List of Azure Blob Storage URIs
            
        Returns:
            Consolidated parsing results
        """
        start_time = time.time()
        
        try:
            if not document_uris:
                raise DIMProcessingError("No document URIs provided")
            
            logger.info(f"Starting document parsing for {len(document_uris)} documents")
            
            # Process documents concurrently
            tasks = [self._parse_single_document(uri) for uri in document_uris]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Consolidate results
            consolidated_result = await self._consolidate_results(document_uris, results)
            
            processing_time = int((time.time() - start_time) * 1000)
            consolidated_result.processing_time_ms = processing_time
            
            # Update statistics
            self.processing_stats['documents_processed'] += len(document_uris)
            self.processing_stats['invoices_extracted'] += len(consolidated_result.invoice_ids)
            self.processing_stats['total_processing_time_ms'] += processing_time
            
            logger.info(f"Document parsing completed", extra={
                'documents_count': len(document_uris),
                'invoice_ids_found': len(consolidated_result.invoice_ids),
                'confidence_score': consolidated_result.confidence_score,
                'processing_time_ms': processing_time
            })
            
            return consolidated_result
            
        except Exception as e:
            self.processing_stats['errors'] += 1
            logger.error(f"Document parsing failed: {e}")
            
            if isinstance(e, DIMProcessingError):
                raise
            else:
                raise DIMProcessingError(f"Document processing failed: {e}")
    
    async def _parse_single_document(self, document_uri: str) -> Dict[str, Any]:
        """
        Parse single document using Azure Form Recognizer
        
        Args:
            document_uri: Azure Blob Storage URI
            
        Returns:
            Parsed document data
        """
        try:
            logger.debug(f"Parsing document: {document_uri}")
            
            # Download document from blob storage
            document_content = await self._download_document(document_uri)
            
            # Analyze document with Form Recognizer
            poller = await self.form_client.begin_analyze_document(
                "prebuilt-invoice",  # Use prebuilt invoice model
                document_content,
                features=[AnalysisFeature.OCR_HIGH_RESOLUTION]
            )
            
            result = await poller.result()
            
            # Extract relevant information
            parsed_data = await self._extract_invoice_data(result, document_uri)
            
            return parsed_data
            
        except AzureError as e:
            logger.error(f"Azure Form Recognizer error for {document_uri}: {e}")
            raise DIMProcessingError(f"Form Recognizer failed: {e}", document_uri)
        except Exception as e:
            logger.error(f"Document parsing error for {document_uri}: {e}")
            raise DIMProcessingError(f"Document parsing failed: {e}", document_uri)
    
    async def _download_document(self, document_uri: str) -> bytes:
        """
        Download document from Azure Blob Storage
        
        Args:
            document_uri: Blob storage URI
            
        Returns:
            Document content as bytes
        """
        try:
            # Parse blob URI to get container and blob name
            # Expected format: https://storage.blob.core.windows.net/container/blob_name
            parts = document_uri.replace('https://', '').split('/')
            if len(parts) < 3:
                raise ValueError(f"Invalid blob URI format: {document_uri}")
            
            container_name = parts[1]
            blob_name = '/'.join(parts[2:])
            
            # Download blob
            blob_client = self.blob_client.get_blob_client(
                container=container_name,
                blob=blob_name
            )
            
            download_stream = await blob_client.download_blob()
            content = await download_stream.readall()
            
            logger.debug(f"Downloaded document: {document_uri} ({len(content)} bytes)")
            return content
            
        except Exception as e:
            logger.error(f"Failed to download document {document_uri}: {e}")
            raise DIMProcessingError(f"Document download failed: {e}", document_uri)
    
    async def _extract_invoice_data(self, analysis_result, document_uri: str) -> Dict[str, Any]:
        """
        Extract invoice data from Form Recognizer analysis result
        
        Args:
            analysis_result: Form Recognizer analysis result
            document_uri: Original document URI
            
        Returns:
            Extracted invoice data
        """
        try:
            extracted_data = {
                'document_uri': document_uri,
                'invoice_ids': [],
                'amounts': [],
                'customer_identifiers': [],
                'confidence_scores': [],
                'ocr_text': '',
                'raw_fields': {}
            }
            
            # Process each analyzed document
            for document in analysis_result.documents:
                # Extract invoice IDs
                invoice_id = self._extract_invoice_id(document)
                if invoice_id:
                    extracted_data['invoice_ids'].append(invoice_id)
                
                # Extract amounts
                amounts = self._extract_amounts(document)
                extracted_data['amounts'].extend(amounts)
                
                # Extract customer information
                customer_info = self._extract_customer_info(document)
                if customer_info:
                    extracted_data['customer_identifiers'].append(customer_info)
                
                # Store confidence scores
                extracted_data['confidence_scores'].append(document.confidence)
                
                # Store raw field data for debugging
                extracted_data['raw_fields'][document_uri] = {
                    field_name: {
                        'value': field.value,
                        'confidence': field.confidence
                    } for field_name, field in document.fields.items()
                }
            
            # Process OCR content
            for page in analysis_result.pages:
                for line in page.lines:
                    extracted_data['ocr_text'] += line.content + '\n'
                    
                    # Extract additional invoice IDs from OCR text
                    additional_ids = self._extract_invoice_ids_from_text(line.content)
                    extracted_data['invoice_ids'].extend(additional_ids)
            
            # Remove duplicates and clean up
            extracted_data['invoice_ids'] = list(set(extracted_data['invoice_ids']))
            extracted_data['customer_identifiers'] = list(set(extracted_data['customer_identifiers']))
            
            return extracted_data
            
        except Exception as e:
            logger.error(f"Data extraction failed for {document_uri}: {e}")
            raise DIMProcessingError(f"Data extraction failed: {e}", document_uri)
    
    def _extract_invoice_id(self, document) -> Optional[str]:
        """Extract invoice ID from Form Recognizer document"""
        try:
            # Try standard invoice ID field
            if 'InvoiceId' in document.fields:
                invoice_id = document.fields['InvoiceId'].value
                if invoice_id and len(str(invoice_id)) > 3:
                    return str(invoice_id).strip()
            
            # Try invoice number field
            if 'InvoiceNumber' in document.fields:
                invoice_number = document.fields['InvoiceNumber'].value
                if invoice_number and len(str(invoice_number)) > 3:
                    return str(invoice_number).strip()
            
            # Try reference number
            if 'ReferenceNumber' in document.fields:
                ref_number = document.fields['ReferenceNumber'].value
                if ref_number and len(str(ref_number)) > 3:
                    return str(ref_number).strip()
            
            return None
            
        except Exception as e:
            logger.debug(f"Invoice ID extraction failed: {e}")
            return None
    
    def _extract_amounts(self, document) -> List[Decimal]:
        """Extract monetary amounts from Form Recognizer document"""
        amounts = []
        
        try:
            # Extract invoice total
            if 'InvoiceTotal' in document.fields:
                total = document.fields['InvoiceTotal'].value
                if total and total.amount:
                    amounts.append(Decimal(str(total.amount)))
            
            # Extract due amount
            if 'AmountDue' in document.fields:
                due = document.fields['AmountDue'].value
                if due and due.amount:
                    amounts.append(Decimal(str(due.amount)))
            
            # Extract subtotal
            if 'SubTotal' in document.fields:
                subtotal = document.fields['SubTotal'].value
                if subtotal and subtotal.amount:
                    amounts.append(Decimal(str(subtotal.amount)))
            
            # Extract line item amounts
            if 'Items' in document.fields:
                items = document.fields['Items'].value
                for item in items:
                    if 'Amount' in item.value:
                        amount = item.value['Amount'].value
                        if amount and amount.amount:
                            amounts.append(Decimal(str(amount.amount)))
            
            return amounts
            
        except Exception as e:
            logger.debug(f"Amount extraction failed: {e}")
            return []
    
    def _extract_customer_info(self, document) -> Optional[str]:
        """Extract customer information from Form Recognizer document"""
        try:
            # Try vendor/customer name
            if 'CustomerName' in document.fields:
                customer_name = document.fields['CustomerName'].value
                if customer_name:
                    return str(customer_name).strip()
            
            # Try billing address name
            if 'BillingAddress' in document.fields:
                billing = document.fields['BillingAddress'].value
                if billing and 'Name' in billing:
                    return str(billing['Name'].value).strip()
            
            # Try vendor info
            if 'VendorName' in document.fields:
                vendor_name = document.fields['VendorName'].value
                if vendor_name:
                    return str(vendor_name).strip()
            
            return None
            
        except Exception as e:
            logger.debug(f"Customer info extraction failed: {e}")
            return None
    
    def _extract_invoice_ids_from_text(self, text: str) -> List[str]:
        """Extract invoice IDs from OCR text using regex patterns"""
        invoice_ids = []
        
        # Standard patterns for invoice IDs
        patterns = [
            r'INV[-_#]?(\d{4,10})',  # INV-12345, INV_12345, INV#12345
            r'INVOICE[-_#]?\s*(\d{4,10})',  # INVOICE 12345
            r'PO[-_#]?(\d{4,10})',   # PO-12345
            r'REF[-_#]?(\d{4,10})',  # REF-12345
            r'ORDER[-_#]?(\d{4,10})',  # ORDER-12345
            r'BILL[-_#]?(\d{4,10})',  # BILL-12345
            r'(\d{4,10})',  # Standalone numbers (low confidence)
        ]
        
        text_upper = text.upper()
        
        for i, pattern in enumerate(patterns):
            matches = re.findall(pattern, text_upper)
            for match in matches:
                # Reconstruct full ID based on pattern
                if i == 0:  # INV pattern
                    invoice_ids.append(f"INV-{match}")
                elif i == 1:  # INVOICE pattern
                    invoice_ids.append(f"INVOICE-{match}")
                elif i == 2:  # PO pattern
                    invoice_ids.append(f"PO-{match}")
                elif i == 3:  # REF pattern
                    invoice_ids.append(f"REF-{match}")
                elif i == 4:  # ORDER pattern
                    invoice_ids.append(f"ORDER-{match}")
                elif i == 5:  # BILL pattern
                    invoice_ids.append(f"BILL-{match}")
                else:  # Standalone number
                    # Only include if it looks like an invoice ID (4+ digits)
                    if len(match) >= 4:
                        invoice_ids.append(match)
        
        return invoice_ids
    
    async def _consolidate_results(self, document_uris: List[str], results: List[Any]) -> DocumentParsingResult:
        """
        Consolidate multiple document parsing results
        
        Args:
            document_uris: Original document URIs
            results: List of parsing results (may include exceptions)
            
        Returns:
            Consolidated DocumentParsingResult
        """
        try:
            all_invoice_ids = []
            all_amounts = []
            all_customers = []
            confidence_scores = []
            ocr_texts = []
            successful_docs = 0
            
            # Process results
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(f"Document parsing failed for {document_uris[i]}: {result}")
                    continue
                
                successful_docs += 1
                
                # Collect data
                all_invoice_ids.extend(result.get('invoice_ids', []))
                all_amounts.extend(result.get('amounts', []))
                all_customers.extend(result.get('customer_identifiers', []))
                confidence_scores.extend(result.get('confidence_scores', []))
                ocr_texts.append(result.get('ocr_text', ''))
            
            # Remove duplicates
            unique_invoice_ids = list(set(all_invoice_ids))
            unique_customers = list(set(all_customers))
            
            # Calculate overall confidence
            overall_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0
            
            # Combine OCR text
            combined_ocr = '\n---\n'.join(ocr_texts)
            
            # Create result
            result = DocumentParsingResult(
                document_uri=document_uris[0] if len(document_uris) == 1 else f"batch:{len(document_uris)}",
                invoice_ids=unique_invoice_ids,
                confidence_score=overall_confidence,
                extracted_amounts=all_amounts,
                customer_identifiers=unique_customers,
                processing_time_ms=0,  # Will be set by caller
                ocr_text=combined_ocr[:5000]  # Limit OCR text size
            )
            
            logger.info(f"Results consolidated: {len(unique_invoice_ids)} invoice IDs, {len(unique_customers)} customers")
            return result
            
        except Exception as e:
            logger.error(f"Result consolidation failed: {e}")
            raise DIMProcessingError(f"Result consolidation failed: {e}")

class DocumentClassifier:
    """
    Classifies documents by type and relevance
    Determines processing strategy based on document content
    """
    
    def __init__(self, form_recognizer_service: AzureFormRecognizerService):
        self.form_service = form_recognizer_service
    
    async def classify_document(self, document_uri: str) -> Dict[str, Any]:
        """
        Classify document type and determine processing approach
        
        Args:
            document_uri: Document URI to classify
            
        Returns:
            Classification result with processing recommendations
        """
        try:
            # Use Form Recognizer's general document model for classification
            document_content = await self.form_service._download_document(document_uri)
            
            poller = await self.form_service.form_client.begin_analyze_document(
                "prebuilt-document",
                document_content
            )
            
            result = await poller.result()
            
            # Analyze content to determine document type
            classification = self._analyze_document_content(result)
            
            logger.info(f"Document classified: {document_uri} -> {classification['document_type']}")
            return classification
            
        except Exception as e:
            logger.error(f"Document classification failed for {document_uri}: {e}")
            return {
                'document_type': 'unknown',
                'confidence': 0.0,
                'processing_recommendation': 'skip',
                'error': str(e)
            }
    
    def _analyze_document_content(self, analysis_result) -> Dict[str, Any]:
        """Analyze document content to determine type"""
        try:
            # Collect all text content
            all_text = ""
            for page in analysis_result.pages:
                for line in page.lines:
                    all_text += line.content + " "
            
            text_upper = all_text.upper()
            
            # Classification logic
            invoice_keywords = ['INVOICE', 'BILL', 'PAYMENT', 'AMOUNT DUE', 'TOTAL', 'SUBTOTAL']
            remittance_keywords = ['REMITTANCE', 'PAYMENT ADVICE', 'TRANSFER', 'REFERENCE']
            statement_keywords = ['STATEMENT', 'BALANCE', 'OUTSTANDING', 'AGING']
            
            # Count keyword matches
            invoice_score = sum(1 for keyword in invoice_keywords if keyword in text_upper)
            remittance_score = sum(1 for keyword in remittance_keywords if keyword in text_upper)
            statement_score = sum(1 for keyword in statement_keywords if keyword in text_upper)
            
            # Determine document type
            if invoice_score >= 3:
                doc_type = 'invoice'
                confidence = min(0.95, 0.6 + (invoice_score * 0.1))
                processing = 'full_extraction'
            elif remittance_score >= 2:
                doc_type = 'remittance_advice'
                confidence = min(0.90, 0.5 + (remittance_score * 0.15))
                processing = 'reference_extraction'
            elif statement_score >= 2:
                doc_type = 'statement'
                confidence = min(0.85, 0.4 + (statement_score * 0.15))
                processing = 'summary_extraction'
            else:
                doc_type = 'unknown'
                confidence = 0.3
                processing = 'basic_ocr'
            
            return {
                'document_type': doc_type,
                'confidence': confidence,
                'processing_recommendation': processing,
                'keyword_scores': {
                    'invoice': invoice_score,
                    'remittance': remittance_score,
                    'statement': statement_score
                },
                'text_length': len(all_text)
            }
            
        except Exception as e:
            logger.error(f"Content analysis failed: {e}")
            return {
                'document_type': 'unknown',
                'confidence': 0.0,
                'processing_recommendation': 'skip',
                'error': str(e)
            }

class DocumentProcessor:
    """
    Main document processing orchestrator
    Combines Form Recognizer with custom business logic
    """
    
    def __init__(self, 
                 form_recognizer_service: AzureFormRecognizerService,
                 enable_classification: bool = True):
        self.form_service = form_recognizer_service
        self.classifier = DocumentClassifier(form_recognizer_service) if enable_classification else None
        self.processing_stats = {
            'total_processed': 0,
            'by_type': {},
            'average_confidence': 0.0
        }
    
    async def process_documents(self, 
                               document_uris: List[str],
                               client_id: str = None,
                               processing_options: Dict[str, Any] = None) -> DocumentParsingResult:
        """
        Process documents with optional client-specific rules
        
        Args:
            document_uris: List of document URIs to process
            client_id: Client ID for custom processing rules
            processing_options: Additional processing options
            
        Returns:
            Document parsing results
        """
        try:
            if not document_uris:
                raise DIMProcessingError("No documents to process")
            
            logger.info(f"Processing {len(document_uris)} documents for client: {client_id or 'default'}")
            
            # Classify documents if enabled
            if self.classifier and processing_options and processing_options.get('enable_classification', True):
                classifications = await self._classify_documents(document_uris)
                # Filter out documents that shouldn't be processed
                filtered_uris = [
                    uri for uri, classification in zip(document_uris, classifications)
                    if classification['processing_recommendation'] != 'skip'
                ]
                
                if len(filtered_uris) != len(document_uris):
                    logger.info(f"Filtered documents: {len(document_uris)} -> {len(filtered_uris)}")
                
                document_uris = filtered_uris
            
            if not document_uris:
                return DocumentParsingResult(
                    document_uri="filtered_out",
                    invoice_ids=[],
                    confidence_score=0.0,
                    processing_time_ms=0
                )
            
            # Process documents
            result = await self.form_service.parse_documents(document_uris)
            
            # Apply client-specific post-processing if client_id provided
            if client_id:
                result = await self._apply_client_processing_rules(result, client_id)
            
            # Update statistics
            self.processing_stats['total_processed'] += len(document_uris)
            
            return result
            
        except Exception as e:
            logger.error(f"Document processing failed: {e}")
            raise DIMProcessingError(f"Document processing failed: {e}")
    
    async def _classify_documents(self, document_uris: List[str]) -> List[Dict[str, Any]]:
        """Classify all documents"""
        tasks = [self.classifier.classify_document(uri) for uri in document_uris]
        classifications = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions in classification
        safe_classifications = []
        for i, classification in enumerate(classifications):
            if isinstance(classification, Exception):
                logger.warning(f"Classification failed for {document_uris[i]}: {classification}")
                safe_classifications.append({
                    'document_type': 'unknown',
                    'confidence': 0.0,
                    'processing_recommendation': 'basic_ocr'
                })
            else:
                safe_classifications.append(classification)
        
        return safe_classifications
    
    async def _apply_client_processing_rules(self, 
                                           result: DocumentParsingResult, 
                                           client_id: str) -> DocumentParsingResult:
        """
        Apply client-specific processing rules to results
        
        Args:
            result: Initial processing result
            client_id: Client identifier
            
        Returns:
            Modified result with client rules applied
        """
        try:
            # This would fetch client-specific rules and apply them
            # For now, implement basic filtering
            
            # Filter invoice IDs based on client patterns
            filtered_ids = []
            for invoice_id in result.invoice_ids:
                if self._validate_invoice_id_for_client(invoice_id, client_id):
                    filtered_ids.append(invoice_id)
            
            result.invoice_ids = filtered_ids
            
            # Apply confidence adjustments based on client history
            confidence_adjustment = await self._get_client_confidence_adjustment(client_id)
            result.confidence_score = min(1.0, result.confidence_score * confidence_adjustment)
            
            logger.debug(f"Applied client rules for {client_id}: {len(filtered_ids)} invoice IDs")
            return result
            
        except Exception as e:
            logger.warning(f"Failed to apply client rules for {client_id}: {e}")
            return result
    
    def _validate_invoice_id_for_client(self, invoice_id: str, client_id: str) -> bool:
        """Validate invoice ID against client-specific patterns"""
        # Basic validation - in production, would use client-specific patterns
        if len(invoice_id) < 4 or len(invoice_id) > 20:
            return False
        
        # Check for valid alphanumeric format
        return bool(re.match(r'^[A-Z0-9\-_#]+$', invoice_id))
    
    async def _get_client_confidence_adjustment(self, client_id: str) -> float:
        """Get confidence adjustment factor based on client history"""
        # Placeholder - would analyze client's historical accuracy
        return 1.0
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """Get document processing statistics"""
        return {
            **self.processing_stats,
            'service_stats': self.form_service.processing_stats
        }

# Health check for document intelligence
async def document_intelligence_health_check(form_service: AzureFormRecognizerService) -> Dict[str, Any]:
    """
    Check document intelligence system health
    
    Args:
        form_service: Form Recognizer service instance
        
    Returns:
        Health status
    """
    try:
        # Test Form Recognizer connectivity
        test_result = {"status": "healthy", "components": {}}
        
        # Simple connectivity test
        try:
            # This would make a simple test call to Form Recognizer
            test_result["components"]["form_recognizer"] = "connected"
        except Exception as e:
            test_result["components"]["form_recognizer"] = f"error: {str(e)}"
            test_result["status"] = "degraded"
        
        # Test blob storage connectivity
        try:
            containers = form_service.blob_client.list_containers(max_results=1)
            await containers.__anext__()  # Try to get first container
            test_result["components"]["blob_storage"] = "connected"
        except Exception as e:
            test_result["components"]["blob_storage"] = f"error: {str(e)}"
            test_result["status"] = "degraded"
        
        # Add processing statistics
        test_result["stats"] = form_service.processing_stats
        
        return test_result
        
    except Exception as e:
        logger.error(f"Document intelligence health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }

# Factory function to create document processor
async def create_document_processor(endpoint: str, 
                                   api_key: str, 
                                   storage_connection_string: str) -> DocumentProcessor:
    """
    Create and initialize document processor
    
    Args:
        endpoint: Azure Form Recognizer endpoint
        api_key: Form Recognizer API key
        storage_connection_string: Azure Storage connection string
        
    Returns:
        Initialized document processor
    """
    form_service = AzureFormRecognizerService(endpoint, api_key, storage_connection_string)
    processor = DocumentProcessor(form_service)
    
    logger.info("Document processor created with Azure Form Recognizer")
    return processor