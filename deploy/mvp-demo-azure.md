# MVP Demo Environment - Azure Deployment Plan

## 🎯 EABL MVP Demo Environment using Existing Azure Infrastructure

### Why Azure (Great Choice!)
- ✅ **Already configured** with Terraform
- ✅ **Container Registry** ready for our Docker images
- ✅ **App Services** perfect for microservices
- ✅ **Cost-effective** for demo environment
- ✅ **Azure Form Recognizer** integration ready
- ✅ **Enterprise security** built-in

---

## 🏗️ Current Azure Infrastructure

Based on our Terraform configuration, we have:

```
Azure Resource Group: rg-cashappagent-demo
├── 🌐 Virtual Network (vnet-cashappagent-demo)
│   ├── App Subnet (for microservices)
│   ├── Data Subnet (for databases)
│   └── AI Subnet (for ML services)
├── 🐳 Container Registry (crcashappagentdemo)
├── 🖥️  App Service Plan (asp-cashappagent-demo)
├── 📊 PostgreSQL Server (psql-cashappagent-demo)
├── 🔐 Key Vault (kv-cashappagent-demo)
├── 📈 Application Insights (ai-cashappagent-demo)
└── 💾 Storage Account (sacashappagentdemo)
```

---

## 🚀 MVP Demo Deployment Plan

### Phase 1: Infrastructure Deployment (30 minutes)

```bash
# 1. Configure Terraform for demo environment
cd terraform
cp terraform.tfvars.example terraform.tfvars

# Edit terraform.tfvars for demo:
environment = "demo"
location = "East US 2"
app_service_sku_name = "B2"  # Basic tier for demo
postgresql_sku_name = "B_Gen5_1"  # Basic tier
business_owner = "eabl-demo@cashup.agent"
technical_owner = "devops@cashup.agent"

# 2. Deploy Azure infrastructure
terraform init
terraform plan -out=demo.tfplan
terraform apply demo.tfplan
```

### Phase 2: Application Deployment (45 minutes)

```bash
# 1. Build and push Docker images
./scripts/deploy.py --environment demo --build-images

# 2. Deploy services to Azure App Services
./scripts/deploy.py --environment demo --deploy-services

# 3. Configure custom domain (optional)
# Domain: demo.cashup.eabl.co.ke
```

### Phase 3: Demo Portal Creation (60 minutes)

Create a simple web interface for EABL testing:

```html
<!-- Demo Portal Features -->
🌐 Web Interface:
  ├── Document Upload Form
  ├── Real-time Processing Display  
  ├── Three-tier Routing Visualization
  ├── Cost Optimization Dashboard
  └── API Integration Examples

📱 Mobile Responsive Design
🔒 Basic Authentication (EABL credentials)  
📊 Live Processing Statistics
🎯 Interactive API Documentation
```

---

## 📊 Demo Environment Specifications

### **URLs for EABL Testing:**
- **Main Portal**: `https://demo-cashup-eabl.azurewebsites.net`
- **API Endpoint**: `https://api-demo-cashup-eabl.azurewebsites.net`
- **Monitoring**: `https://monitor-demo-cashup-eabl.azurewebsites.net`
- **API Docs**: `https://api-demo-cashup-eabl.azurewebsites.net/docs`

### **Services Deployed:**
- ✅ **DIM Service** (Document Intelligence) - Port 8012
- ✅ **EIC Service** (ERP Integration) - Port 8013  
- ✅ **CM Service** (Communication) - Port 8014
- ✅ **CLE Service** (Cash Ledger) - Port 8011
- ✅ **Orchestrator** (Workflow) - Port 8006

### **Demo Features:**
- 🔄 **Real three-tier ML processing**
- 💰 **Live cost optimization display**
- 📊 **Performance metrics dashboard**
- 🔗 **SAP integration testing**
- 📤 **Document upload interface**
- 🎛️ **Admin monitoring panel**

---

## 💰 Cost Breakdown (Demo Environment)

| Service | SKU | Monthly Cost (USD) |
|---------|-----|-------------------|
| App Service Plan (B2) | 2 vCPUs, 3.5GB RAM | $73 |
| PostgreSQL (B_Gen5_1) | 1 vCore, 2GB RAM | $25 |
| Container Registry (Basic) | 10GB storage | $5 |
| Application Insights | Basic monitoring | $10 |
| Storage Account | Standard LRS | $5 |
| **Total Demo Cost** | | **~$118/month** |

**vs Production**: ~$500-1000/month (when scaled)

---

## 🎯 EABL Testing Scenarios

### **Test Case 1: Document Upload**
```bash
# EABL can test with their own invoices
curl -X POST "https://api-demo-cashup-eabl.azurewebsites.net/api/v1/parse_document" \
  -H "Authorization: Bearer EABL_DEMO_TOKEN" \
  -F "document=@eabl_invoice.pdf"
```

### **Test Case 2: Batch Processing**
```bash
# Test month-end processing simulation
curl -X POST "https://api-demo-cashup-eabl.azurewebsites.net/api/v1/batch/process" \
  -H "Authorization: Bearer EABL_DEMO_TOKEN" \
  -d '{"documents": ["inv1.pdf", "inv2.pdf"], "client_id": "eabl_test"}'
```

### **Test Case 3: SAP Integration**
```bash
# Test ERP connection
curl -X GET "https://api-demo-cashup-eabl.azurewebsites.net/api/v1/erp/sap/connection" \
  -H "Authorization: Bearer EABL_DEMO_TOKEN"
```

---

## 🔐 Security Configuration

### **EABL Access:**
- **API Keys**: Dedicated EABL demo tokens
- **IP Restrictions**: EABL office IPs whitelisted
- **SSL/TLS**: Automatic HTTPS with Azure certificates
- **Key Vault**: All secrets secured in Azure Key Vault

### **Compliance:**
- **Data Retention**: 7 days only (demo environment)
- **Audit Logs**: Complete API access logging
- **Encryption**: Data encrypted at rest and in transit
- **GDPR**: Demo data automatically purged

---

## 📈 Success Metrics for EABL Demo

### **Performance Targets:**
- ⚡ **API Response**: < 200ms average
- 🎯 **Uptime**: 99.5% availability  
- 💰 **Cost Demo**: Show 60%+ savings vs current solution
- 🚀 **Processing**: 100+ documents/minute capacity

### **Business KPIs:**
- 📊 **EABL User Adoption**: Track usage patterns
- 🎯 **Accuracy Validation**: Test with EABL's real documents
- 💼 **Stakeholder Demos**: Enable EABL to show executives
- 🤝 **Integration Success**: Prove API compatibility

---

## 🚀 Deployment Timeline

### **Week 1: Infrastructure**
- **Day 1-2**: Configure Terraform for demo environment
- **Day 3-4**: Deploy Azure infrastructure  
- **Day 5**: Test base infrastructure

### **Week 2: Application Deployment**
- **Day 1-2**: Build and deploy Docker images
- **Day 3-4**: Configure services and databases
- **Day 5**: End-to-end system testing

### **Week 3: Demo Portal & Testing**
- **Day 1-3**: Build web interface for EABL
- **Day 4**: EABL access setup and security
- **Day 5**: Final testing and handover to EABL

### **Week 4: EABL Testing & Feedback**
- **Days 1-5**: EABL internal testing
- **Ongoing**: Collect feedback and iterate

---

## 🎯 Next Steps

1. **Confirm Azure subscription** and permissions
2. **Customize Terraform variables** for demo environment  
3. **Deploy infrastructure** using existing configuration
4. **Build demo portal** for EABL testing
5. **Schedule EABL demo session**

**Ready to deploy the MVP demo environment using our existing Azure infrastructure?**

This approach leverages everything we've already built and gets EABL testing quickly!