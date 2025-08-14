from temporalio import activity
import httpx
import os
from typing import Dict, List, Any
import logging

logger = logging.getLogger(__name__)

@activity.defn
async def extract_invoice_ids(transaction: Dict[str, Any]) -> List[str]:
    """
    Extract invoice IDs from transaction document using DIM service
    """
    activity.logger.info(f"Extracting invoice IDs for transaction: {transaction.get('id')}")
    
    dim_base_url = os.getenv('DIM_BASE_URL', 'http://dim:8002')
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Call DIM service to extract invoice IDs
            response = await client.post(
                f"{dim_base_url}/api/v1/extract/invoice-ids",
                json={
                    "document_url": transaction.get("document_url"),
                    "document_content": transaction.get("document_content"),
                    "transaction_id": transaction.get("id"),
                    "client_id": transaction.get("client_id")
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                invoice_ids = result.get("invoice_ids", [])
                
                activity.logger.info(f"Extracted {len(invoice_ids)} invoice IDs: {invoice_ids}")
                
                # Record metrics
                activity.heartbeat(f"Extracted {len(invoice_ids)} invoice IDs")
                
                return invoice_ids
            
            else:
                activity.logger.error(f"DIM service returned status {response.status_code}: {response.text}")
                raise Exception(f"DIM service failed with status {response.status_code}")
                
        except httpx.TimeoutException:
            activity.logger.error("DIM service request timed out")
            raise Exception("DIM service timeout")
        
        except Exception as e:
            activity.logger.error(f"Error calling DIM service: {str(e)}")
            raise


@activity.defn
async def extract_document_metadata(document_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract metadata and structure from document using DIM service
    """
    activity.logger.info(f"Extracting document metadata for: {document_info.get('document_id')}")
    
    dim_base_url = os.getenv('DIM_BASE_URL', 'http://dim:8002')
    
    async with httpx.AsyncClient(timeout=45.0) as client:
        try:
            response = await client.post(
                f"{dim_base_url}/api/v1/extract/metadata",
                json=document_info,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                metadata = response.json()
                
                activity.logger.info(f"Extracted metadata: {list(metadata.keys())}")
                return metadata
            
            else:
                activity.logger.error(f"Metadata extraction failed: {response.status_code}")
                raise Exception(f"Metadata extraction failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error extracting metadata: {str(e)}")
            raise


@activity.defn
async def process_document_batch(batch_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a batch of documents using DIM service
    """
    activity.logger.info(f"Processing document batch: {batch_info.get('batch_id')}")
    
    dim_base_url = os.getenv('DIM_BASE_URL', 'http://dim:8002')
    
    async with httpx.AsyncClient(timeout=300.0) as client:  # 5 minute timeout for batch processing
        try:
            response = await client.post(
                f"{dim_base_url}/api/v1/process/batch",
                json=batch_info,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # Send periodic heartbeats during long processing
                activity.heartbeat(f"Batch processing: {result.get('progress', 0)}% complete")
                
                activity.logger.info(f"Batch processed: {result.get('processed_count', 0)} documents")
                return result
            
            else:
                activity.logger.error(f"Batch processing failed: {response.status_code}")
                raise Exception(f"Batch processing failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error processing batch: {str(e)}")
            raise


@activity.defn
async def validate_document_quality(document_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate document quality using DIM service before processing
    """
    activity.logger.info(f"Validating document quality: {document_info.get('document_id')}")
    
    dim_base_url = os.getenv('DIM_BASE_URL', 'http://dim:8002')
    
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.post(
                f"{dim_base_url}/api/v1/validate/quality",
                json=document_info,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                quality_result = response.json()
                
                activity.logger.info(f"Quality score: {quality_result.get('quality_score', 0)}")
                return quality_result
            
            else:
                activity.logger.error(f"Quality validation failed: {response.status_code}")
                raise Exception(f"Quality validation failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error validating document quality: {str(e)}")
            raise