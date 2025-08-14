"""
Azure Form Recognizer Engine for CashApp Document Intelligence
Provides high-accuracy OCR for complex documents using Azure Cognitive Services
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import time
import os
from azure.ai.formrecognizer.aio import DocumentAnalysisClient
from azure.ai.formrecognizer import DocumentAnalysisFeature
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import AzureError
import httpx

logger = logging.getLogger(__name__)

@dataclass
class AzureOCRResult:
    """Result from Azure Form Recognizer processing"""
    text: str
    confidence: float
    tables: List[Dict]
    key_value_pairs: List[Dict]
    processing_time_ms: int
    pages: int
    cost_estimate: float

@dataclass
class AzureInvoiceData:
    """Structured invoice data from Azure"""
    invoice_ids: List[str]
    amounts: List[float]
    dates: List[str]
    vendors: List[str]
    line_items: List[Dict]
    confidence: float
    raw_result: Dict
    cost_estimate: float

class AzureFormRecognizerEngine:
    """
    Azure Form Recognizer engine for high-accuracy document processing
    """
    
    def __init__(self, endpoint: str, api_key: str, model_id: str = "prebuilt-invoice"):
        """
        Initialize Azure Form Recognizer engine
        
        Args:
            endpoint: Azure Form Recognizer endpoint
            api_key: Azure API key
            model_id: Model to use (prebuilt-invoice, prebuilt-document, etc.)
        """
        self.endpoint = endpoint
        self.api_key = api_key
        self.model_id = model_id
        
        # Initialize client
        self.client = DocumentAnalysisClient(
            endpoint=self.endpoint,
            credential=AzureKeyCredential(self.api_key)
        )
        
        # Pricing (approximate, per page)
        self.pricing = {
            'prebuilt-invoice': 0.01,   # $0.01 per page
            'prebuilt-document': 0.005,  # $0.005 per page
            'prebuilt-receipt': 0.01,    # $0.01 per page
            'read': 0.001               # $0.001 per page for basic OCR
        }
        
        # Features to enable
        self.features = [
            DocumentAnalysisFeature.OCR_HIGH_RESOLUTION,
            DocumentAnalysisFeature.LANGUAGES,
            DocumentAnalysisFeature.KEY_VALUE_PAIRS,
            DocumentAnalysisFeature.TABLES
        ]
    
    async def extract_text(self, document_url: str = None, document_bytes: bytes = None) -> AzureOCRResult:
        """
        Extract text using Azure Form Recognizer
        
        Args:
            document_url: URL to document
            document_bytes: Document bytes (if not using URL)
            
        Returns:
            Azure OCR result
        """
        start_time = time.time()
        
        try:
            # Start analysis
            if document_url:
                poller = await self.client.begin_analyze_document_from_url(
                    model_id=self.model_id,
                    document_url=document_url,
                    features=self.features
                )
            elif document_bytes:
                poller = await self.client.begin_analyze_document(
                    model_id=self.model_id,
                    document=document_bytes,
                    features=self.features
                )
            else:
                raise ValueError("Either document_url or document_bytes must be provided")
            
            # Wait for completion
            result = await poller.result()
            
            # Extract text content
            text_content = []
            overall_confidence = 0.0
            confidence_count = 0
            
            for page in result.pages:
                for line in page.lines:
                    text_content.append(line.content)
                    if line.confidence:
                        overall_confidence += line.confidence
                        confidence_count += 1
            
            # Calculate average confidence
            avg_confidence = overall_confidence / confidence_count if confidence_count > 0 else 0.0
            
            # Extract tables
            tables = []
            for table in result.tables:
                table_data = {
                    'rows': table.row_count,
                    'columns': table.column_count,
                    'cells': []
                }
                
                for cell in table.cells:
                    table_data['cells'].append({
                        'content': cell.content,
                        'row_index': cell.row_index,
                        'column_index': cell.column_index,
                        'confidence': cell.confidence
                    })
                
                tables.append(table_data)
            
            # Extract key-value pairs
            key_value_pairs = []
            for kv_pair in result.key_value_pairs:
                if kv_pair.key and kv_pair.value:
                    key_value_pairs.append({
                        'key': kv_pair.key.content,
                        'value': kv_pair.value.content,
                        'confidence': min(kv_pair.key.confidence or 0, kv_pair.value.confidence or 0)
                    })
            
            processing_time = int((time.time() - start_time) * 1000)
            pages = len(result.pages)
            cost_estimate = pages * self.pricing.get(self.model_id, 0.01)
            
            azure_result = AzureOCRResult(
                text='\n'.join(text_content),
                confidence=avg_confidence,
                tables=tables,
                key_value_pairs=key_value_pairs,
                processing_time_ms=processing_time,
                pages=pages,
                cost_estimate=cost_estimate
            )
            
            logger.info(f"Azure OCR completed: {pages} pages, {avg_confidence:.2f} confidence", extra={
                'processing_time_ms': processing_time,
                'cost_estimate': cost_estimate,
                'model': self.model_id
            })
            
            return azure_result
            
        except AzureError as e:
            logger.error(f"Azure Form Recognizer error: {e}")
            return AzureOCRResult(
                text="",
                confidence=0.0,
                tables=[],
                key_value_pairs=[],
                processing_time_ms=int((time.time() - start_time) * 1000),
                pages=0,
                cost_estimate=0.0
            )
        except Exception as e:
            logger.error(f"Error in Azure text extraction: {e}")
            return AzureOCRResult(
                text="",
                confidence=0.0,
                tables=[],
                key_value_pairs=[],
                processing_time_ms=int((time.time() - start_time) * 1000),
                pages=0,
                cost_estimate=0.0
            )
    
    async def extract_invoice_data(self, document_url: str = None, document_bytes: bytes = None) -> AzureInvoiceData:
        """
        Extract structured invoice data using Azure's prebuilt invoice model
        
        Args:
            document_url: URL to document
            document_bytes: Document bytes
            
        Returns:
            Structured invoice data
        """
        start_time = time.time()
        
        try:
            # Use invoice-specific model
            original_model = self.model_id
            self.model_id = "prebuilt-invoice"
            
            # Start analysis
            if document_url:
                poller = await self.client.begin_analyze_document_from_url(
                    model_id="prebuilt-invoice",
                    document_url=document_url
                )
            elif document_bytes:
                poller = await self.client.begin_analyze_document(
                    model_id="prebuilt-invoice",
                    document=document_bytes
                )
            else:
                raise ValueError("Either document_url or document_bytes must be provided")
            
            result = await poller.result()
            
            invoice_ids = []
            amounts = []
            dates = []
            vendors = []
            line_items = []
            overall_confidence = 0.0
            confidence_count = 0
            
            # Process each document
            for document in result.documents:
                # Extract invoice number
                if "InvoiceId" in document.fields:
                    field = document.fields["InvoiceId"]
                    if field.value:
                        invoice_ids.append(str(field.value))
                        if field.confidence:
                            overall_confidence += field.confidence
                            confidence_count += 1
                
                # Extract invoice total
                if "InvoiceTotal" in document.fields:
                    field = document.fields["InvoiceTotal"]
                    if field.value:
                        amounts.append(float(field.value.amount))
                        if field.confidence:
                            overall_confidence += field.confidence
                            confidence_count += 1
                
                # Extract invoice date
                if "InvoiceDate" in document.fields:
                    field = document.fields["InvoiceDate"]
                    if field.value:
                        dates.append(str(field.value))
                        if field.confidence:
                            overall_confidence += field.confidence
                            confidence_count += 1
                
                # Extract vendor information
                if "VendorName" in document.fields:
                    field = document.fields["VendorName"]
                    if field.value:
                        vendors.append(str(field.value))
                        if field.confidence:
                            overall_confidence += field.confidence
                            confidence_count += 1
                
                # Extract line items
                if "Items" in document.fields:
                    items_field = document.fields["Items"]
                    if items_field.value:
                        for item in items_field.value:
                            line_item = {}
                            
                            if "Description" in item.value:
                                line_item["description"] = str(item.value["Description"].value)
                            
                            if "Quantity" in item.value:
                                line_item["quantity"] = float(item.value["Quantity"].value)
                            
                            if "UnitPrice" in item.value:
                                line_item["unit_price"] = float(item.value["UnitPrice"].value.amount)
                            
                            if "Amount" in item.value:
                                line_item["amount"] = float(item.value["Amount"].value.amount)
                            
                            if line_item:
                                line_items.append(line_item)
            
            # Calculate average confidence
            avg_confidence = overall_confidence / confidence_count if confidence_count > 0 else 0.0
            
            # Calculate cost
            pages = len(result.pages)
            cost_estimate = pages * self.pricing.get("prebuilt-invoice", 0.01)
            
            # Restore original model
            self.model_id = original_model
            
            invoice_data = AzureInvoiceData(
                invoice_ids=invoice_ids,
                amounts=amounts,
                dates=dates,
                vendors=vendors,
                line_items=line_items,
                confidence=avg_confidence,
                raw_result=result.to_dict() if hasattr(result, 'to_dict') else {},
                cost_estimate=cost_estimate
            )
            
            logger.info(f"Azure invoice extraction completed", extra={
                'invoice_ids': len(invoice_ids),
                'amounts': len(amounts),
                'line_items': len(line_items),
                'confidence': avg_confidence,
                'cost_estimate': cost_estimate
            })
            
            return invoice_data
            
        except AzureError as e:
            logger.error(f"Azure invoice extraction error: {e}")
            return AzureInvoiceData([], [], [], [], [], 0.0, {}, 0.0)
        except Exception as e:
            logger.error(f"Error in Azure invoice extraction: {e}")
            return AzureInvoiceData([], [], [], [], [], 0.0, {}, 0.0)
    
    async def analyze_document_layout(self, document_url: str = None, document_bytes: bytes = None) -> Dict[str, Any]:
        """
        Analyze document layout using Azure's layout model
        
        Args:
            document_url: URL to document
            document_bytes: Document bytes
            
        Returns:
            Layout analysis results
        """
        try:
            # Use layout model
            if document_url:
                poller = await self.client.begin_analyze_document_from_url(
                    model_id="prebuilt-layout",
                    document_url=document_url
                )
            elif document_bytes:
                poller = await self.client.begin_analyze_document(
                    model_id="prebuilt-layout",
                    document=document_bytes
                )
            else:
                raise ValueError("Either document_url or document_bytes must be provided")
            
            result = await poller.result()
            
            layout_info = {
                'pages': len(result.pages),
                'paragraphs': len(result.paragraphs),
                'tables': len(result.tables),
                'styles': [],
                'reading_order': []
            }
            
            # Extract styles
            for style in result.styles:
                layout_info['styles'].append({
                    'is_handwritten': style.is_handwritten,
                    'confidence': style.confidence,
                    'spans': len(style.spans) if style.spans else 0
                })
            
            # Extract reading order
            for paragraph in result.paragraphs:
                layout_info['reading_order'].append({
                    'content': paragraph.content,
                    'role': paragraph.role,
                    'confidence': paragraph.confidence
                })
            
            return layout_info
            
        except Exception as e:
            logger.error(f"Error analyzing document layout: {e}")
            return {}
    
    async def get_model_info(self, model_id: str = None) -> Dict[str, Any]:
        """
        Get information about available models
        
        Args:
            model_id: Specific model to get info for
            
        Returns:
            Model information
        """
        try:
            target_model = model_id or self.model_id
            
            # Get model info
            model = await self.client.get_document_model(target_model)
            
            return {
                'model_id': model.model_id,
                'description': model.description,
                'created_on': model.created_on.isoformat() if model.created_on else None,
                'api_version': model.api_version,
                'document_types': list(model.document_types.keys()) if model.document_types else [],
                'pricing_per_page': self.pricing.get(target_model, 0.01)
            }
            
        except Exception as e:
            logger.error(f"Error getting model info: {e}")
            return {}
    
    async def batch_analyze_documents(self, document_urls: List[str]) -> List[AzureInvoiceData]:
        """
        Batch analyze multiple documents
        
        Args:
            document_urls: List of document URLs
            
        Returns:
            List of invoice data results
        """
        results = []
        semaphore = asyncio.Semaphore(5)  # Limit concurrent requests
        
        async def analyze_single(url: str) -> AzureInvoiceData:
            async with semaphore:
                try:
                    return await self.extract_invoice_data(document_url=url)
                except Exception as e:
                    logger.error(f"Error analyzing document {url}: {e}")
                    return AzureInvoiceData([], [], [], [], [], 0.0, {}, 0.0)
        
        # Process all documents concurrently
        tasks = [analyze_single(url) for url in document_urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions
        valid_results = [r for r in results if isinstance(r, AzureInvoiceData)]
        
        logger.info(f"Batch analysis completed: {len(valid_results)}/{len(document_urls)} successful")
        
        return valid_results
    
    def get_capabilities(self) -> Dict[str, Any]:
        """Get engine capabilities and configuration"""
        return {
            'name': 'AzureFormRecognizerEngine',
            'endpoint': self.endpoint,
            'supported_models': [
                'prebuilt-invoice',
                'prebuilt-document',
                'prebuilt-receipt',
                'prebuilt-layout',
                'prebuilt-read'
            ],
            'supported_formats': ['PDF', 'PNG', 'JPG', 'JPEG', 'TIFF', 'BMP'],
            'features': {
                'text_extraction': True,
                'invoice_parsing': True,
                'table_extraction': True,
                'key_value_pairs': True,
                'layout_analysis': True,
                'batch_processing': True,
                'high_accuracy': True,
                'multilingual': True
            },
            'pricing': self.pricing,
            'current_model': self.model_id,
            'cost_per_page': self.pricing.get(self.model_id, 0.01),
            'avg_processing_time_ms': 5000,  # Estimate
            'accuracy_rate': 0.95  # High accuracy for complex documents
        }
    
    async def close(self):
        """Close the Azure client"""
        try:
            await self.client.close()
            logger.info("Azure Form Recognizer client closed")
        except Exception as e:
            logger.warning(f"Error closing Azure client: {e}")
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()