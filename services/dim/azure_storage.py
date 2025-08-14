# services/dim/azure_storage.py
"""
Azure Blob Storage Client for Document Intelligence Module
Handles secure document download from Azure Blob Storage
"""

import asyncio
import logging
import os
import re
from typing import Tuple, Dict, Any, Optional
from urllib.parse import urlparse

import aiohttp
from azure.storage.blob.aio import BlobServiceClient
from azure.identity.aio import DefaultAzureCredential, ClientSecretCredential
from azure.core.exceptions import AzureError

from shared.logging import setup_logging, log_context
from shared.exceptions import DocumentProcessingError, AuthenticationError

logger = setup_logging("dim-azure-storage")


class AzureBlobStorageClient:
    """Client for downloading documents from Azure Blob Storage."""
    
    def __init__(self):
        self.blob_service_client: Optional[BlobServiceClient] = None
        self.credential = None
        self._initialized = False
        
        # Configuration from environment
        self.storage_account_url = os.getenv("AZURE_BLOB_STORAGE_URL")
        self.account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
        self.tenant_id = os.getenv("AZURE_TENANT_ID")
        self.client_id = os.getenv("AZURE_CLIENT_ID") 
        self.client_secret = os.getenv("AZURE_CLIENT_SECRET")
        
        # Timeouts and limits
        self.download_timeout_seconds = 60
        self.max_file_size_mb = 100
        self.connection_timeout = 30
        
    async def initialize(self):
        """Initialize the Azure Blob Storage client."""
        try:
            logger.info("Initializing Azure Blob Storage client")
            
            if not self.storage_account_url:
                logger.info("No Azure Blob Storage URL configured, using HTTP fallback only")
                self._initialized = True
                return
            
            # Choose authentication method
            if self.account_key:
                # Use account key authentication
                logger.info("Using Azure Storage account key authentication")
                self.blob_service_client = BlobServiceClient(
                    account_url=self.storage_account_url,
                    credential=self.account_key
                )
            elif self.client_id and self.client_secret and self.tenant_id:
                # Use service principal authentication
                logger.info("Using Azure service principal authentication")
                self.credential = ClientSecretCredential(
                    tenant_id=self.tenant_id,
                    client_id=self.client_id,
                    client_secret=self.client_secret
                )
                self.blob_service_client = BlobServiceClient(
                    account_url=self.storage_account_url,
                    credential=self.credential
                )
            else:
                # Use default credential chain (managed identity, etc.)
                logger.info("Using Azure default credential authentication")
                self.credential = DefaultAzureCredential()
                self.blob_service_client = BlobServiceClient(
                    account_url=self.storage_account_url,
                    credential=self.credential
                )
            
            # Test connection
            await self._test_connection()
            
            self._initialized = True
            logger.info("Azure Blob Storage client initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Azure Blob Storage client: {e}")
            # Don't raise - allow fallback to HTTP download
            self._initialized = False
    
    async def download_blob(self, blob_uri: str) -> Tuple[bytes, Dict[str, Any]]:
        """Download a blob from Azure Blob Storage."""
        try:
            logger.debug(f"Downloading blob: {blob_uri}")
            
            if not self._initialized or not self.blob_service_client:
                logger.warning("Azure client not available, falling back to HTTP download")
                return await self._download_via_http(blob_uri)
            
            # Parse blob URI
            container_name, blob_name = self._parse_blob_uri(blob_uri)
            
            # Get blob client
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name,
                blob=blob_name
            )
            
            # Check if blob exists and get properties
            blob_properties = await blob_client.get_blob_properties()
            
            # Validate size
            blob_size_mb = blob_properties.size / (1024 * 1024)
            if blob_size_mb > self.max_file_size_mb:
                raise DocumentProcessingError(
                    f"Blob too large: {blob_size_mb:.1f}MB (max: {self.max_file_size_mb}MB)"
                )
            
            # Download blob data
            download_stream = await blob_client.download_blob()
            blob_data = await download_stream.readall()
            
            # Create file info
            file_info = {
                "content_type": blob_properties.content_settings.content_type or "application/octet-stream",
                "size_bytes": len(blob_data),
                "reported_size_bytes": blob_properties.size,
                "source": "azure_blob_storage",
                "container": container_name,
                "blob_name": blob_name,
                "last_modified": blob_properties.last_modified.isoformat() if blob_properties.last_modified else None,
                "etag": blob_properties.etag,
                "md5_hash": blob_properties.content_settings.content_md5
            }
            
            logger.debug(
                f"Blob downloaded successfully: {len(blob_data)} bytes",
                extra={"blob_uri": blob_uri, "size_bytes": len(blob_data)}
            )
            
            return blob_data, file_info
            
        except AzureError as e:
            logger.error(f"Azure Blob Storage error: {e}")
            # Fallback to HTTP if Azure-specific error
            if "authentication" in str(e).lower() or "authorization" in str(e).lower():
                raise AuthenticationError(f"Azure authentication failed: {e}")
            else:
                logger.warning("Azure error, attempting HTTP fallback")
                return await self._download_via_http(blob_uri)
        except Exception as e:
            logger.error(f"Blob download failed: {e}")
            raise DocumentProcessingError(f"Blob download failed: {e}")
    
    def _parse_blob_uri(self, blob_uri: str) -> Tuple[str, str]:
        """Parse Azure Blob Storage URI to extract container and blob name."""
        try:
            # Expected format: https://account.blob.core.windows.net/container/path/to/blob
            parsed = urlparse(blob_uri)
            path_parts = parsed.path.strip('/').split('/', 1)
            
            if len(path_parts) != 2:
                raise ValueError(f"Invalid blob URI format: {blob_uri}")
            
            container_name = path_parts[0]
            blob_name = path_parts[1]
            
            # Validate names
            if not container_name or not blob_name:
                raise ValueError(f"Invalid container or blob name in URI: {blob_uri}")
            
            return container_name, blob_name
            
        except Exception as e:
            raise DocumentProcessingError(f"Failed to parse blob URI: {e}")
    
    async def _download_via_http(self, blob_uri: str) -> Tuple[bytes, Dict[str, Any]]:
        """Fallback HTTP download method."""
        try:
            logger.debug(f"Downloading via HTTP: {blob_uri}")
            
            timeout = aiohttp.ClientTimeout(total=self.download_timeout_seconds)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(blob_uri) as response:
                    if response.status != 200:
                        raise DocumentProcessingError(
                            f"HTTP {response.status}: {response.reason}"
                        )
                    
                    # Check content length
                    content_length = response.headers.get('Content-Length')
                    if content_length:
                        size_mb = int(content_length) / (1024 * 1024)
                        if size_mb > self.max_file_size_mb:
                            raise DocumentProcessingError(
                                f"File too large: {size_mb:.1f}MB (max: {self.max_file_size_mb}MB)"
                            )
                    
                    # Download content
                    blob_data = await response.read()
                    
                    file_info = {
                        "content_type": response.headers.get('Content-Type', 'application/octet-stream'),
                        "size_bytes": len(blob_data),
                        "reported_size_bytes": int(content_length) if content_length else len(blob_data),
                        "source": "http_download",
                        "last_modified": response.headers.get('Last-Modified'),
                        "etag": response.headers.get('ETag')
                    }
                    
                    return blob_data, file_info
                    
        except aiohttp.ClientError as e:
            raise DocumentProcessingError(f"HTTP download failed: {e}")
        except Exception as e:
            raise DocumentProcessingError(f"Download failed: {e}")
    
    async def _test_connection(self):
        """Test Azure Blob Storage connection."""
        try:
            if self.blob_service_client:
                # Try to list containers (with limit to avoid large response)
                containers = []
                async for container in self.blob_service_client.list_containers():
                    containers.append(container.name)
                    if len(containers) >= 1:  # Just test connection, don't need all containers
                        break
                
                logger.debug(f"Connection test successful, found {len(containers)} containers")
        except Exception as e:
            logger.warning(f"Connection test failed (will use HTTP fallback): {e}")
            raise AuthenticationError(f"Azure connection test failed: {e}")
    
    async def list_blobs_in_container(self, container_name: str, prefix: str = None) -> list:
        """List blobs in a container (admin/debugging function)."""
        try:
            if not self._initialized or not self.blob_service_client:
                raise DocumentProcessingError("Azure client not initialized")
            
            container_client = self.blob_service_client.get_container_client(container_name)
            blobs = []
            
            async for blob in container_client.list_blobs(name_starts_with=prefix):
                blobs.append({
                    "name": blob.name,
                    "size": blob.size,
                    "last_modified": blob.last_modified.isoformat() if blob.last_modified else None,
                    "content_type": getattr(blob.content_settings, 'content_type', None) if blob.content_settings else None
                })
                
                # Limit results for safety
                if len(blobs) >= 100:
                    break
            
            return blobs
            
        except Exception as e:
            logger.error(f"Failed to list blobs: {e}")
            raise DocumentProcessingError(f"Failed to list blobs: {e}")
    
    async def get_blob_url_with_sas(self, container_name: str, blob_name: str, expiry_hours: int = 1) -> str:
        """Generate a SAS URL for a blob (if needed for secure access)."""
        try:
            from azure.storage.blob import generate_blob_sas, BlobSasPermissions
            from datetime import datetime, timedelta
            
            if not self.account_key:
                raise DocumentProcessingError("Account key required for SAS generation")
            
            # Parse account name from URL
            account_name = urlparse(self.storage_account_url).hostname.split('.')[0]
            
            # Generate SAS token
            sas_token = generate_blob_sas(
                account_name=account_name,
                container_name=container_name,
                blob_name=blob_name,
                account_key=self.account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.utcnow() + timedelta(hours=expiry_hours)
            )
            
            # Construct full URL
            sas_url = f"{self.storage_account_url}/{container_name}/{blob_name}?{sas_token}"
            
            return sas_url
            
        except Exception as e:
            logger.error(f"Failed to generate SAS URL: {e}")
            raise DocumentProcessingError(f"SAS URL generation failed: {e}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Health check for Azure Blob Storage connectivity."""
        health_status = {
            "azure_configured": bool(self.storage_account_url),
            "client_initialized": self._initialized,
            "authentication_method": "none"
        }
        
        if self.account_key:
            health_status["authentication_method"] = "account_key"
        elif self.client_id and self.client_secret:
            health_status["authentication_method"] = "service_principal"
        else:
            health_status["authentication_method"] = "default_credential"
        
        try:
            if self._initialized and self.blob_service_client:
                # Quick connectivity test
                account_info = await self.blob_service_client.get_account_information()
                health_status["connection_test"] = "success"
                health_status["account_kind"] = account_info.get("account_kind")
            else:
                health_status["connection_test"] = "not_tested"
                
        except Exception as e:
            health_status["connection_test"] = "failed"
            health_status["connection_error"] = str(e)
        
        return health_status
    
    async def cleanup(self):
        """Cleanup resources."""
        try:
            if self.blob_service_client:
                await self.blob_service_client.close()
            if self.credential:
                await self.credential.close()
            logger.debug("Azure Blob Storage client cleaned up")
        except Exception as e:
            logger.warning(f"Cleanup warning: {e}")
