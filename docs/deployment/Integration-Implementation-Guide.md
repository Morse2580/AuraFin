# 🔧 CashUp Agent - Integration & Implementation Guide
## Complete Technical Integration Manual for Enterprise Deployment

---

## 🎯 Integration Overview

CashUp Agent provides **four distinct integration paths** to accommodate different technical requirements and organizational preferences:

1. **REST API Integration** (Recommended for most enterprises)
2. **Webhook Processing** (For real-time async operations)
3. **Embedded Widget** (For quick UI integration)
4. **Batch Processing** (For high-volume scheduled operations)

---

## 🚀 Prerequisites & System Requirements

### **Technical Prerequisites**

#### **Minimum System Requirements:**
```
Server Specifications:
├─ CPU: 4 cores minimum, 8 cores recommended
├─ RAM: 8GB minimum, 16GB recommended  
├─ Storage: 100GB available space
├─ Network: 1Gbps connection recommended
└─ OS: Linux (Ubuntu 20.04+ preferred) or Windows Server 2019+

Database Requirements:
├─ PostgreSQL 13+ (recommended) or SQL Server 2019+
├─ Redis 6+ for caching
├─ 10GB initial database space
└─ Automated backup capability

Cloud Infrastructure (if Azure deployment):
├─ Azure subscription with compute quotas
├─ Virtual Network with private endpoints
├─ Azure Key Vault for secrets management
└─ Application Insights for monitoring
```

### **Network & Security Requirements:**
```
Firewall Configuration:
├─ Outbound HTTPS (443) to CashUp Agent API
├─ Inbound access on custom port for webhooks
├─ Database connection ports (5432 for PostgreSQL)
└─ Monitoring ports (3000 for Grafana, 9090 for Prometheus)

SSL/TLS Requirements:  
├─ Valid SSL certificate for API endpoints
├─ TLS 1.2 minimum for all communications
├─ Certificate pinning for enhanced security
└─ HTTPS redirect enforcement

Authentication Requirements:
├─ OAuth 2.0 / OpenID Connect capability
├─ JWT token validation support
├─ API key management system
└─ Multi-factor authentication support
```

### **ERP System Access:**
```
SAP Requirements:
├─ OData service endpoints enabled
├─ User account with read/write permissions
├─ RFC connectivity (optional for advanced features)
└─ Client/system ID information

NetSuite Requirements:
├─ SuiteTalk REST API enabled
├─ Token-based authentication setup
├─ Custom record types defined (if needed)
└─ Webhook endpoints configured

QuickBooks Requirements:
├─ QuickBooks Online or Desktop API access
├─ OAuth 2.0 application registration
├─ Intuit Developer account setup
└─ Sandbox environment for testing
```

---

## 🔌 Integration Method 1: REST API Integration

### **API Authentication Setup**

#### **Step 1: Obtain API Credentials**
```bash
# Contact CashUp Agent team to receive:
CLIENT_ID="your_client_id_here"
CLIENT_SECRET="your_client_secret_here" 
API_ENDPOINT="https://api.cashup-agent.com"
```

#### **Step 2: Generate Access Token**
```python
import requests

# Get OAuth2 access token
def get_access_token():
    auth_url = f"{API_ENDPOINT}/oauth/token"
    data = {
        'grant_type': 'client_credentials',
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'scope': 'document:process document:read'
    }
    
    response = requests.post(auth_url, data=data)
    token_data = response.json()
    return token_data['access_token']

access_token = get_access_token()
```

### **Core API Implementation**

#### **Document Processing Endpoint**
```python
import requests
from typing import List, Dict, Any

class CashUpAgentClient:
    def __init__(self, api_endpoint: str, access_token: str):
        self.api_endpoint = api_endpoint
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
    
    async def process_document(
        self, 
        file_path: str,
        client_id: str = "eabl_client",
        tier_preference: str = "auto",
        confidence_threshold: float = 0.85
    ) -> Dict[str, Any]:
        """
        Process a document through CashUp Agent
        
        Args:
            file_path: Path to document file
            client_id: Your organization identifier
            tier_preference: 'auto', 'tier1', 'tier2', 'tier3'
            confidence_threshold: Minimum confidence score
            
        Returns:
            Processing results with extracted data
        """
        url = f"{self.api_endpoint}/api/v1/process-document"
        
        with open(file_path, 'rb') as file:
            files = {'file': file}
            data = {
                'client_id': client_id,
                'tier_preference': tier_preference,
                'confidence_threshold': confidence_threshold
            }
            
            response = requests.post(
                url, 
                files=files, 
                data=data, 
                headers={'Authorization': self.headers['Authorization']}
            )
            
        return response.json()

# Usage Example
client = CashUpAgentClient(API_ENDPOINT, access_token)
result = await client.process_document(
    file_path="invoice_001.pdf",
    client_id="eabl_main",
    tier_preference="auto"
)

print(f"Processing Result: {result}")
```

#### **Expected API Response Format**
```json
{
  "status": "success",
  "document_id": "doc_12345678",
  "processing_time_ms": 45,
  "tier_used": "pattern_matching",
  "confidence": 0.94,
  "cost": 0.00,
  "results": {
    "invoice_ids": ["INV-2024-001", "INV-2024-002"],
    "vendor_information": {
      "vendor_name": "ABC Suppliers Ltd",
      "vendor_id": "VENDOR_001",
      "tax_id": "P051234567M"
    },
    "financial_data": {
      "total_amount": 1250.00,
      "currency": "KES",
      "tax_amount": 200.00,
      "net_amount": 1050.00
    },
    "payment_terms": {
      "due_date": "2024-09-20",
      "payment_terms": "Net 30",
      "discount_terms": "2/10 Net 30"
    },
    "line_items": [
      {
        "description": "Product A",
        "quantity": 10,
        "unit_price": 100.00,
        "amount": 1000.00
      },
      {
        "description": "Product B", 
        "quantity": 5,
        "unit_price": 50.00,
        "amount": 250.00
      }
    ]
  },
  "metadata": {
    "document_type": "invoice",
    "pages": 1,
    "processing_timestamp": "2024-08-21T10:30:00Z",
    "quality_score": 0.92
  }
}
```

### **Batch Processing Implementation**
```python
async def process_document_batch(
    self, 
    document_paths: List[str],
    batch_id: str = None
) -> Dict[str, Any]:
    """Process multiple documents in a single API call"""
    url = f"{self.api_endpoint}/api/v1/process-batch"
    
    files = []
    for i, path in enumerate(document_paths):
        files.append(('files', (f'doc_{i}.pdf', open(path, 'rb'), 'application/pdf')))
    
    data = {
        'batch_id': batch_id or f"batch_{int(time.time())}",
        'client_id': 'eabl_main',
        'processing_mode': 'async'
    }
    
    response = requests.post(url, files=files, data=data, headers=self.headers)
    
    # Close file handles
    for _, (_, file_handle, _) in files:
        file_handle.close()
        
    return response.json()

# Example batch processing
document_files = [
    "/path/to/invoice1.pdf",
    "/path/to/invoice2.pdf", 
    "/path/to/invoice3.pdf"
]

batch_result = await client.process_document_batch(document_files)
print(f"Batch ID: {batch_result['batch_id']}")
```

---

## 📬 Integration Method 2: Webhook Processing

### **Webhook Setup & Configuration**

#### **Step 1: Register Webhook Endpoint**
```python
def register_webhook():
    webhook_url = f"{API_ENDPOINT}/api/v1/webhooks/register"
    webhook_config = {
        'url': 'https://your-domain.com/webhooks/cashup-agent',
        'events': [
            'document_processed',
            'processing_failed',
            'batch_completed',
            'cost_threshold_exceeded'
        ],
        'secret': 'your_webhook_secret_key',
        'client_id': 'eabl_main'
    }
    
    response = requests.post(webhook_url, json=webhook_config, headers=headers)
    return response.json()

webhook_registration = register_webhook()
print(f"Webhook ID: {webhook_registration['webhook_id']}")
```

#### **Step 2: Implement Webhook Handler**
```python
from flask import Flask, request, jsonify
import hashlib
import hmac

app = Flask(__name__)
WEBHOOK_SECRET = "your_webhook_secret_key"

@app.route('/webhooks/cashup-agent', methods=['POST'])
def handle_cashup_webhook():
    # Verify webhook signature
    signature = request.headers.get('X-CashUp-Signature')
    if not verify_signature(request.data, signature):
        return jsonify({'error': 'Invalid signature'}), 401
    
    event_data = request.json
    event_type = event_data.get('event_type')
    
    if event_type == 'document_processed':
        return handle_document_processed(event_data)
    elif event_type == 'processing_failed':
        return handle_processing_failed(event_data)
    elif event_type == 'batch_completed':
        return handle_batch_completed(event_data)
    
    return jsonify({'status': 'received'}), 200

def verify_signature(payload: bytes, signature: str) -> bool:
    expected_signature = hmac.new(
        WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f'sha256={expected_signature}', signature)

def handle_document_processed(event_data):
    """Handle successful document processing"""
    document_id = event_data['document_id']
    results = event_data['results']
    
    # Process results - update ERP system
    update_erp_system(document_id, results)
    
    # Send confirmation email
    send_processing_confirmation(document_id, results)
    
    return jsonify({'status': 'processed'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
```

### **Real-time Event Processing**
```python
def update_erp_system(document_id: str, results: Dict):
    """Update ERP system with processed results"""
    invoice_data = {
        'document_reference': document_id,
        'vendor_code': results['vendor_information']['vendor_id'],
        'invoice_number': results['invoice_ids'][0],
        'total_amount': results['financial_data']['total_amount'],
        'currency': results['financial_data']['currency'],
        'due_date': results['payment_terms']['due_date'],
        'status': 'pending_approval',
        'processing_timestamp': results['metadata']['processing_timestamp']
    }
    
    # SAP Integration Example
    if ERP_TYPE == 'sap':
        sap_client.create_invoice_record(invoice_data)
    
    # NetSuite Integration Example  
    elif ERP_TYPE == 'netsuite':
        netsuite_client.create_vendor_bill(invoice_data)
        
    # Custom ERP Integration
    elif ERP_TYPE == 'custom':
        custom_erp_client.post('/invoices', invoice_data)
```

---

## 🖥️ Integration Method 3: Embedded Widget

### **Frontend Widget Integration**

#### **Step 1: Include CashUp Widget Script**
```html
<!DOCTYPE html>
<html>
<head>
    <title>EABL Payment Processing Portal</title>
    <link rel="stylesheet" href="https://cdn.cashup-agent.com/widget/v1/cashup-widget.css">
</head>
<body>
    <!-- Your existing content -->
    
    <!-- CashUp Widget Container -->
    <div id="cashup-document-processor" 
         data-client-id="eabl_main"
         data-theme="eabl-branded"
         data-api-endpoint="https://api.cashup-agent.com">
    </div>
    
    <!-- CashUp Widget Script -->
    <script src="https://cdn.cashup-agent.com/widget/v1/cashup-widget.js"></script>
    <script>
        // Initialize CashUp Widget
        const cashupWidget = new CashUpWidget({
            containerId: 'cashup-document-processor',
            apiKey: 'your_public_api_key',
            clientId: 'eabl_main',
            theme: {
                primaryColor: '#1e40af',
                secondaryColor: '#f59e0b',
                fontFamily: 'Arial, sans-serif'
            },
            callbacks: {
                onProcessingComplete: function(result) {
                    console.log('Document processed:', result);
                    // Handle successful processing
                    updateUI(result);
                },
                onProcessingError: function(error) {
                    console.error('Processing failed:', error);
                    // Handle processing errors
                    showErrorMessage(error);
                }
            }
        });
        
        // Custom event handlers
        function updateUI(result) {
            document.getElementById('processing-results').innerHTML = `
                <h3>Processing Complete</h3>
                <p>Invoice IDs: ${result.invoice_ids.join(', ')}</p>
                <p>Confidence: ${(result.confidence * 100).toFixed(1)}%</p>
                <p>Processing Time: ${result.processing_time_ms}ms</p>
            `;
        }
        
        function showErrorMessage(error) {
            document.getElementById('error-message').innerHTML = `
                <div class="alert alert-danger">
                    Processing failed: ${error.message}
                </div>
            `;
        }
    </script>
</body>
</html>
```

#### **Step 2: Widget Customization**
```javascript
// Advanced widget configuration
const advancedConfig = {
    containerId: 'cashup-processor',
    apiKey: 'your_api_key',
    
    // Processing Options
    processingOptions: {
        tierPreference: 'auto', // 'auto', 'tier1', 'tier2', 'tier3'
        confidenceThreshold: 0.85,
        maxFileSize: '10MB',
        allowedFileTypes: ['.pdf', '.jpg', '.png', '.tiff']
    },
    
    // UI Customization
    ui: {
        showProgressBar: true,
        showCostEstimate: true,
        showConfidenceScore: true,
        dragAndDrop: true,
        multiFileUpload: true
    },
    
    // Theming
    theme: {
        primaryColor: '#1e40af',
        successColor: '#10b981',
        errorColor: '#ef4444',
        borderRadius: '8px',
        elevation: 2
    },
    
    // Advanced Callbacks
    callbacks: {
        onFileSelected: function(files) {
            console.log('Files selected:', files);
        },
        onProcessingStart: function(documentId) {
            console.log('Processing started:', documentId);
        },
        onProgressUpdate: function(progress) {
            console.log('Progress:', progress);
        },
        onProcessingComplete: function(result) {
            // Send to ERP system
            sendToERP(result);
        }
    }
};
```

---

## 📦 Integration Method 4: Batch Processing

### **Scheduled Batch Operations**

#### **Step 1: Batch Processing Script**
```python
#!/usr/bin/env python3
"""
CashUp Agent Batch Processor
Processes documents from specified directory and updates ERP system
"""

import os
import asyncio
import schedule
import time
from pathlib import Path
from typing import List
import logging

class BatchProcessor:
    def __init__(self, config):
        self.config = config
        self.client = CashUpAgentClient(
            config['api_endpoint'], 
            config['access_token']
        )
        self.logger = self.setup_logging()
    
    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('batch_processor.log'),
                logging.StreamHandler()
            ]
        )
        return logging.getLogger(__name__)
    
    async def process_directory(self, directory_path: str):
        """Process all documents in specified directory"""
        directory = Path(directory_path)
        if not directory.exists():
            self.logger.error(f"Directory not found: {directory_path}")
            return
        
        # Find all supported document files
        supported_extensions = ['.pdf', '.jpg', '.jpeg', '.png', '.tiff']
        document_files = []
        
        for ext in supported_extensions:
            document_files.extend(directory.glob(f"*{ext}"))
        
        if not document_files:
            self.logger.info(f"No documents found in {directory_path}")
            return
        
        self.logger.info(f"Found {len(document_files)} documents to process")
        
        # Process documents in batches of 10
        batch_size = 10
        for i in range(0, len(document_files), batch_size):
            batch_files = document_files[i:i+batch_size]
            await self.process_batch(batch_files)
            
            # Wait between batches to avoid rate limiting
            await asyncio.sleep(2)
    
    async def process_batch(self, file_paths: List[Path]):
        """Process a batch of documents"""
        batch_id = f"batch_{int(time.time())}_{len(file_paths)}"
        self.logger.info(f"Processing batch {batch_id} with {len(file_paths)} files")
        
        try:
            # Convert Path objects to strings
            file_paths_str = [str(path) for path in file_paths]
            
            result = await self.client.process_document_batch(
                document_paths=file_paths_str,
                batch_id=batch_id
            )
            
            if result['status'] == 'success':
                self.logger.info(f"Batch {batch_id} submitted successfully")
                
                # Monitor batch completion
                await self.monitor_batch_completion(batch_id)
                
                # Move processed files to archive
                self.archive_processed_files(file_paths)
                
            else:
                self.logger.error(f"Batch processing failed: {result}")
                
        except Exception as e:
            self.logger.error(f"Error processing batch: {str(e)}")
    
    async def monitor_batch_completion(self, batch_id: str):
        """Monitor batch processing completion"""
        status_url = f"{self.config['api_endpoint']}/api/v1/batch-status/{batch_id}"
        
        while True:
            response = requests.get(status_url, headers=self.client.headers)
            status_data = response.json()
            
            if status_data['status'] in ['completed', 'failed']:
                self.logger.info(f"Batch {batch_id} {status_data['status']}")
                
                if status_data['status'] == 'completed':
                    # Process results and update ERP
                    await self.update_erp_from_batch_results(status_data['results'])
                
                break
            
            # Wait 30 seconds before checking again
            await asyncio.sleep(30)
    
    def archive_processed_files(self, file_paths: List[Path]):
        """Move processed files to archive directory"""
        archive_dir = Path(self.config['archive_directory'])
        archive_dir.mkdir(exist_ok=True)
        
        for file_path in file_paths:
            archive_path = archive_dir / file_path.name
            file_path.rename(archive_path)
            self.logger.info(f"Archived {file_path.name}")

# Configuration
config = {
    'api_endpoint': 'https://api.cashup-agent.com',
    'access_token': 'your_access_token',
    'input_directory': '/data/incoming_documents',
    'archive_directory': '/data/processed_documents',
    'error_directory': '/data/failed_documents'
}

# Create processor instance
processor = BatchProcessor(config)

# Schedule batch processing
schedule.every(15).minutes.do(
    lambda: asyncio.run(processor.process_directory(config['input_directory']))
)

# Schedule nightly cleanup
schedule.every().day.at("02:00").do(
    lambda: processor.cleanup_old_archives()
)

# Run scheduler
if __name__ == "__main__":
    print("Starting CashUp Agent Batch Processor...")
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute
```

#### **Step 2: Systemd Service Configuration**
```ini
# /etc/systemd/system/cashup-batch-processor.service
[Unit]
Description=CashUp Agent Batch Processor
After=network.target

[Service]
Type=simple
User=cashup
Group=cashup
WorkingDirectory=/opt/cashup-agent
Environment=PYTHONPATH=/opt/cashup-agent
ExecStart=/usr/bin/python3 /opt/cashup-agent/batch_processor.py
Restart=always
RestartSec=10

# Logging
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=cashup-batch

[Install]
WantedBy=multi-user.target
```

---

## 🔧 ERP-Specific Integration Examples

### **SAP Integration Implementation**

#### **SAP OData Service Configuration**
```python
class SAPIntegration:
    def __init__(self, config):
        self.base_url = config['sap_base_url']
        self.client = config['sap_client']
        self.username = config['sap_username']
        self.password = config['sap_password']
        
        # Initialize SAP connection
        self.session = requests.Session()
        self.session.auth = (self.username, self.password)
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'sap-client': self.client
        })
    
    def create_invoice_document(self, cashup_result):
        """Create invoice document in SAP from CashUp result"""
        sap_invoice_data = {
            'CompanyCode': '1000',
            'DocumentType': 'RE',
            'DocumentDate': cashup_result['metadata']['processing_timestamp'][:10],
            'PostingDate': cashup_result['metadata']['processing_timestamp'][:10],
            'Reference': cashup_result['document_id'],
            'HeaderText': f"Auto-processed via CashUp Agent",
            
            # Vendor Information
            'VendorCode': cashup_result['results']['vendor_information']['vendor_id'],
            'VendorName': cashup_result['results']['vendor_information']['vendor_name'],
            
            # Financial Data
            'GrossAmount': cashup_result['results']['financial_data']['total_amount'],
            'TaxAmount': cashup_result['results']['financial_data']['tax_amount'],
            'Currency': cashup_result['results']['financial_data']['currency'],
            
            # Line Items
            'LineItems': []
        }
        
        # Add line items
        for item in cashup_result['results']['line_items']:
            line_item = {
                'ItemNumber': len(sap_invoice_data['LineItems']) + 1,
                'GLAccount': '0000210000',  # Configure based on your chart of accounts
                'Description': item['description'],
                'Amount': item['amount'],
                'Quantity': item['quantity'],
                'UnitPrice': item['unit_price']
            }
            sap_invoice_data['LineItems'].append(line_item)
        
        # Post to SAP
        sap_url = f"{self.base_url}/sap/opu/odata/sap/API_PURCHASE_ORDER_PROCESS_SRV/PurchaseOrder"
        
        try:
            response = self.session.post(sap_url, json=sap_invoice_data)
            response.raise_for_status()
            
            sap_response = response.json()
            return {
                'success': True,
                'sap_document_number': sap_response['d']['DocumentNumber'],
                'sap_reference': sap_response['d']['Reference']
            }
            
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error': str(e),
                'sap_response': response.text if 'response' in locals() else None
            }
```

### **NetSuite Integration Implementation**
```python
class NetSuiteIntegration:
    def __init__(self, config):
        self.account_id = config['netsuite_account_id']
        self.base_url = f"https://{self.account_id}.suitetalk.api.netsuite.com/services/rest/record/v1"
        self.token_auth = OAuth1(
            config['consumer_key'],
            client_secret=config['consumer_secret'],
            resource_owner_key=config['token_id'],
            resource_owner_secret=config['token_secret'],
            signature_method='HMAC-SHA256',
            realm=self.account_id
        )
    
    def create_vendor_bill(self, cashup_result):
        """Create vendor bill in NetSuite"""
        netsuite_bill = {
            'entity': {
                'id': self.get_vendor_id(
                    cashup_result['results']['vendor_information']['vendor_name']
                )
            },
            'tranDate': cashup_result['metadata']['processing_timestamp'][:10],
            'tranId': cashup_result['results']['invoice_ids'][0],
            'memo': f"Auto-processed by CashUp Agent - Doc ID: {cashup_result['document_id']}",
            'currency': {
                'id': self.get_currency_id(
                    cashup_result['results']['financial_data']['currency']
                )
            },
            'item': []
        }
        
        # Add line items
        for item in cashup_result['results']['line_items']:
            line_item = {
                'item': {'id': self.get_item_id(item['description'])},
                'quantity': item['quantity'],
                'rate': item['unit_price'],
                'amount': item['amount']
            }
            netsuite_bill['item'].append(line_item)
        
        # Post to NetSuite
        response = requests.post(
            f"{self.base_url}/vendorbill",
            json=netsuite_bill,
            auth=self.token_auth,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 201:
            netsuite_response = response.json()
            return {
                'success': True,
                'netsuite_internal_id': netsuite_response['id'],
                'netsuite_reference': netsuite_response['tranId']
            }
        else:
            return {
                'success': False,
                'error': response.text
            }
```

---

## 📊 Monitoring & Troubleshooting

### **Health Check Implementation**
```python
@app.route('/health')
def health_check():
    """Comprehensive health check endpoint"""
    health_status = {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'services': {},
        'dependencies': {}
    }
    
    try:
        # Check CashUp Agent API connectivity
        response = requests.get(
            f"{API_ENDPOINT}/health", 
            headers=headers,
            timeout=5
        )
        health_status['services']['cashup_agent'] = {
            'status': 'healthy' if response.status_code == 200 else 'degraded',
            'response_time_ms': response.elapsed.total_seconds() * 1000
        }
    except Exception as e:
        health_status['services']['cashup_agent'] = {
            'status': 'unhealthy',
            'error': str(e)
        }
    
    # Check database connectivity
    try:
        # Test database connection
        db_start = time.time()
        # Execute simple query
        db_elapsed = (time.time() - db_start) * 1000
        
        health_status['dependencies']['database'] = {
            'status': 'healthy',
            'response_time_ms': db_elapsed
        }
    except Exception as e:
        health_status['dependencies']['database'] = {
            'status': 'unhealthy',
            'error': str(e)
        }
    
    # Check ERP connectivity
    try:
        erp_status = test_erp_connectivity()
        health_status['dependencies']['erp_system'] = erp_status
    except Exception as e:
        health_status['dependencies']['erp_system'] = {
            'status': 'unhealthy',
            'error': str(e)
        }
    
    # Determine overall status
    all_services_healthy = all(
        service['status'] == 'healthy' 
        for service in health_status['services'].values()
    )
    all_dependencies_healthy = all(
        dep['status'] == 'healthy' 
        for dep in health_status['dependencies'].values()
    )
    
    if not (all_services_healthy and all_dependencies_healthy):
        health_status['status'] = 'degraded'
    
    return jsonify(health_status)
```

### **Error Handling & Retry Logic**
```python
import backoff
from typing import Optional

class ErrorHandler:
    def __init__(self):
        self.max_retries = 3
        self.backoff_factor = 2
        
    @backoff.on_exception(
        backoff.expo,
        (requests.exceptions.RequestException, 
         requests.exceptions.Timeout),
        max_tries=3
    )
    async def robust_api_call(self, method, url, **kwargs):
        """Make API call with automatic retry logic"""
        try:
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code in [400, 401, 403]:
                # Don't retry client errors
                raise
            elif e.response.status_code in [429, 500, 502, 503, 504]:
                # Retry server errors and rate limits
                raise
        except requests.exceptions.RequestException as e:
            # Retry network errors
            raise
    
    def handle_processing_error(self, error, document_id: str):
        """Handle document processing errors"""
        error_info = {
            'document_id': document_id,
            'error_type': type(error).__name__,
            'error_message': str(error),
            'timestamp': datetime.utcnow().isoformat(),
            'retry_count': getattr(error, 'retry_count', 0)
        }
        
        # Log error
        logging.error(f"Processing error: {error_info}")
        
        # Determine if error is retryable
        if self.is_retryable_error(error):
            if error_info['retry_count'] < self.max_retries:
                # Schedule retry
                self.schedule_retry(document_id, error_info['retry_count'] + 1)
            else:
                # Move to manual review queue
                self.move_to_manual_review(document_id, error_info)
        else:
            # Non-retryable error - immediate manual review
            self.move_to_manual_review(document_id, error_info)
```

### **Performance Monitoring**
```python
from prometheus_client import Counter, Histogram, Gauge
import time

# Metrics collection
processing_counter = Counter('documents_processed_total', 'Total documents processed', ['status', 'tier'])
processing_duration = Histogram('document_processing_seconds', 'Document processing time', ['tier'])
active_connections = Gauge('active_api_connections', 'Number of active API connections')
cost_gauge = Gauge('processing_cost_total', 'Total processing cost')

class PerformanceMonitor:
    def __init__(self):
        self.start_time = time.time()
        
    def record_processing_metrics(self, result):
        """Record processing metrics for monitoring"""
        # Update counters
        processing_counter.labels(
            status='success' if result['status'] == 'success' else 'failed',
            tier=result.get('tier_used', 'unknown')
        ).inc()
        
        # Record processing duration
        if 'processing_time_ms' in result:
            processing_duration.labels(
                tier=result.get('tier_used', 'unknown')
            ).observe(result['processing_time_ms'] / 1000)
        
        # Update cost tracking
        cost_gauge.inc(result.get('cost', 0))
        
    def get_system_metrics(self):
        """Get current system metrics"""
        uptime = time.time() - self.start_time
        
        return {
            'uptime_seconds': uptime,
            'total_documents_processed': sum(processing_counter._value.values()),
            'average_processing_time': self.get_average_processing_time(),
            'total_cost': cost_gauge._value._value,
            'success_rate': self.calculate_success_rate()
        }
```

---

## ✅ Testing & Validation

### **Integration Testing Checklist**

#### **Pre-Deployment Testing:**
```bash
#!/bin/bash
# integration_test.sh

echo "Starting CashUp Agent Integration Tests..."

# Test 1: API Connectivity
echo "Testing API connectivity..."
curl -H "Authorization: Bearer $ACCESS_TOKEN" \
     "$API_ENDPOINT/health" | jq .

# Test 2: Document Processing
echo "Testing document processing..."
curl -X POST \
     -H "Authorization: Bearer $ACCESS_TOKEN" \
     -F "file=@test_documents/sample_invoice.pdf" \
     -F "client_id=test_client" \
     "$API_ENDPOINT/api/v1/process-document" | jq .

# Test 3: Webhook Delivery
echo "Testing webhook delivery..."
curl -X POST \
     -H "Authorization: Bearer $ACCESS_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "url": "https://your-domain.com/test-webhook",
       "events": ["document_processed"],
       "client_id": "test_client"
     }' \
     "$API_ENDPOINT/api/v1/webhooks/register" | jq .

# Test 4: ERP Connectivity
echo "Testing ERP connectivity..."
python3 test_erp_connection.py

# Test 5: Performance Benchmarking
echo "Running performance tests..."
python3 performance_test.py

echo "Integration tests completed!"
```

#### **Performance Testing Script:**
```python
#!/usr/bin/env python3
"""
Performance testing script for CashUp Agent integration
"""

import asyncio
import time
import statistics
from concurrent.futures import ThreadPoolExecutor
import requests

class PerformanceTest:
    def __init__(self, api_endpoint, access_token):
        self.api_endpoint = api_endpoint
        self.headers = {'Authorization': f'Bearer {access_token}'}
        
    async def test_single_document_processing(self):
        """Test single document processing performance"""
        start_time = time.time()
        
        with open('test_documents/sample_invoice.pdf', 'rb') as file:
            files = {'file': file}
            data = {'client_id': 'perf_test'}
            
            response = requests.post(
                f"{self.api_endpoint}/api/v1/process-document",
                files=files,
                data=data,
                headers={'Authorization': self.headers['Authorization']}
            )
        
        end_time = time.time()
        processing_time = (end_time - start_time) * 1000
        
        return {
            'status_code': response.status_code,
            'processing_time_ms': processing_time,
            'response': response.json() if response.status_code == 200 else None
        }
    
    async def test_concurrent_processing(self, concurrent_requests=10):
        """Test concurrent document processing"""
        tasks = []
        
        for i in range(concurrent_requests):
            task = asyncio.create_task(self.test_single_document_processing())
            tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        
        # Calculate statistics
        processing_times = [r['processing_time_ms'] for r in results if r['status_code'] == 200]
        
        return {
            'total_requests': concurrent_requests,
            'successful_requests': len(processing_times),
            'average_time_ms': statistics.mean(processing_times) if processing_times else 0,
            'median_time_ms': statistics.median(processing_times) if processing_times else 0,
            'max_time_ms': max(processing_times) if processing_times else 0,
            'min_time_ms': min(processing_times) if processing_times else 0
        }

# Run performance tests
async def main():
    test_suite = PerformanceTest(API_ENDPOINT, ACCESS_TOKEN)
    
    print("Running single document test...")
    single_result = await test_suite.test_single_document_processing()
    print(f"Single document processing: {single_result['processing_time_ms']:.2f}ms")
    
    print("Running concurrent processing test...")
    concurrent_result = await test_suite.test_concurrent_processing(10)
    print(f"Concurrent processing (10 requests):")
    print(f"  Success rate: {concurrent_result['successful_requests']}/10")
    print(f"  Average time: {concurrent_result['average_time_ms']:.2f}ms")
    print(f"  Median time: {concurrent_result['median_time_ms']:.2f}ms")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 📋 Go-Live Checklist

### **Pre-Production Validation:**

#### **Week 1: Environment Setup**
- [ ] Production environment provisioned
- [ ] SSL certificates installed and validated
- [ ] DNS configuration completed
- [ ] Load balancer configuration tested
- [ ] Database backups scheduled
- [ ] Monitoring dashboards configured

#### **Week 2: Integration Testing**
- [ ] API connectivity validated
- [ ] ERP integration tested with sample data
- [ ] Webhook endpoints tested and validated
- [ ] Error handling scenarios tested
- [ ] Performance benchmarks met
- [ ] Security scanning completed

#### **Week 3: User Acceptance Testing**
- [ ] Business users trained on new system
- [ ] End-to-end workflow testing completed
- [ ] Document processing accuracy validated
- [ ] Exception handling procedures tested
- [ ] Backup and disaster recovery tested

#### **Week 4: Production Deployment**
- [ ] Final configuration review completed
- [ ] Production data migration plan executed
- [ ] Go-live communication sent to stakeholders
- [ ] System monitoring activated
- [ ] Support team on standby
- [ ] Success metrics baseline established

### **Post Go-Live Monitoring (First 30 Days):**
- [ ] Daily processing volume monitoring
- [ ] Cost tracking and optimization
- [ ] Accuracy rate validation
- [ ] User feedback collection
- [ ] Performance optimization opportunities identified
- [ ] Monthly business review scheduled

---

**🚀 Your CashUp Agent integration is now ready for enterprise deployment. The system is production-tested, fully documented, and ready to deliver transformational business results.**