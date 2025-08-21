# 🚀 CashAppAgent E2E Testing - Complete Step-by-Step Guide

## Overview
This guide walks you through comprehensive End-to-End testing of your CashAppAgent system. Follow each step carefully and document the results.

## 🎯 What This E2E Test Validates

**Critical Business Workflows:**
- ✅ Perfect payment matching (95% automation target)
- ✅ Overpayment detection and handling
- ✅ Short payment processing
- ✅ Unmatched payment routing
- ✅ Document intelligence (OCR/AI)
- ✅ ERP integration (NetSuite, SAP, Oracle)
- ✅ Communication module (alerts/notifications)
- ✅ Concurrent processing capability
- ✅ Error handling and recovery
- ✅ Complete workflow orchestration

**Success Criteria:**
- All services start successfully
- At least 10/12 test scenarios pass
- End-to-end payment processing completes in <60 seconds
- System handles concurrent transactions
- Error scenarios are caught and routed correctly

---

## 📋 Pre-Requisites Checklist

**Before starting, ensure you have:**

□ **Docker & Docker Compose installed**
```bash
docker --version
docker compose version
```

□ **At least 8GB RAM available**
```bash
free -h  # Linux
system_profiler SPHardwareDataType | grep Memory  # macOS
```

□ **Required ports are free (5433, 6380, 5673, 7234, 8006-8014)**
```bash
netstat -an | grep -E ":(5433|6380|5673|7234|800[6-9]|801[0-4])" | grep LISTEN
# Should return empty if ports are free
```

□ **Python 3.8+ installed**
```bash
python3 --version
```

□ **Internet connection for Docker pulls**

---

## 🔧 Step 1: Environment Preparation

### 1.1 Clean Any Existing Services
```bash
# Stop any running CashApp services
docker compose down --volumes --remove-orphans

# Clean up Docker system
docker system prune -f

# Verify clean state
docker ps  # Should show no CashApp containers
```

**Expected Result:** No CashApp containers running

### 1.2 Check Available Resources
```bash
# Check disk space (need at least 5GB free)
df -h

# Check memory
free -h  # Linux
vm_stat | head -5  # macOS
```

**Document:** Available disk space and memory

---

## 🏗️ Step 2: Build E2E Test Environment

### 2.1 Build Services (Expected: 10-15 minutes)
```bash
# Navigate to project directory
cd /path/to/cashup-agent

# Start the build process
./run_e2e_tests.sh build-only
```

**What's Happening:**
- Building 5 microservice Docker images
- Installing Python dependencies
- Setting up ML models for document processing
- Configuring test environment

**Expected Output:**
```
🚀 CashAppAgent E2E Testing Pipeline
ℹ️  Checking prerequisites...
✅ Prerequisites check passed
ℹ️  Building E2E services...
Building services......
✅ Services built successfully
```

**If Build Fails:**
1. Check `build.log` for error details
2. Ensure sufficient disk space
3. Check internet connection
4. Try: `docker compose -f docker-compose.e2e.yml build --no-cache`

### 2.2 Verify Built Images
```bash
docker images | grep cashup-agent
```

**Expected Result:** 5 images listed (orchestrator, cle, dim, eic, cm)

---

## 🚀 Step 3: Start Infrastructure Services

### 3.1 Start Database & Messaging (Expected: 2-3 minutes)
```bash
# Start infrastructure only
docker compose -f docker-compose.e2e.yml up -d postgres-e2e redis-e2e rabbitmq-e2e temporal-e2e

# Watch startup logs
docker compose -f docker-compose.e2e.yml logs -f postgres-e2e redis-e2e rabbitmq-e2e temporal-e2e
```

**What's Starting:**
- PostgreSQL database (port 5433)
- Redis cache (port 6380) 
- RabbitMQ message queue (port 5673)
- Temporal workflow engine (port 7234)

**Expected Logs:**
- PostgreSQL: "database system is ready to accept connections"
- Redis: "Ready to accept connections"
- RabbitMQ: "Server startup complete"
- Temporal: "Started"

### 3.2 Verify Infrastructure Health
```bash
# Test database connectivity
docker compose -f docker-compose.e2e.yml exec postgres-e2e pg_isready -U cashapp_user -d cashapp_e2e

# Test Redis
docker compose -f docker-compose.e2e.yml exec redis-e2e redis-cli ping

# Test RabbitMQ
curl -u admin:admin123 http://localhost:15673/api/overview

# Test Temporal (gRPC service - use correct method)
# Method 1: Test connection
nc -z localhost 7234 && echo "✅ Temporal port accessible" || echo "❌ Temporal port not accessible"

# Method 2: Test via orchestrator (recommended)
curl http://localhost:8006/health  # Should show "temporal_connected": true

# Method 3: Use grpcurl (if available)
# grpcurl -plaintext localhost:7234 temporal.api.workflowservice.v1.WorkflowService/GetSystemInfo
```

**Expected Results:**
- PostgreSQL: "accepting connections"
- Redis: "PONG"
- RabbitMQ: JSON response with status
- Temporal: "✅ Temporal port accessible" OR orchestrator health shows `"temporal_connected": true`

**Document:** Which services started successfully

---

## 🔧 Step 4: Start Application Services

### 4.1 Start Core Services (Expected: 3-5 minutes)
```bash
# Start application services
docker compose -f docker-compose.e2e.yml up -d orchestrator-e2e cle-e2e dim-e2e eic-e2e cm-e2e

# Monitor startup
docker compose -f docker-compose.e2e.yml logs -f orchestrator-e2e cle-e2e dim-e2e eic-e2e cm-e2e
```

**What's Starting:**
- Orchestrator (Temporal workflows) - port 8006
- CLE (Core Logic Engine) - port 8011  
- DIM (Document Intelligence) - port 8012
- EIC (ERP Integration) - port 8013
- CM (Communication Manager) - port 8014

**Expected Startup Order:**
1. Orchestrator connects to Temporal
2. CLE initializes matching algorithms
3. DIM loads ML models (takes longest)
4. EIC configures ERP connectors
5. CM sets up communication channels

### 4.2 Health Check All Services
```bash
# Check each service health endpoint
curl http://localhost:8006/health  # Orchestrator
curl http://localhost:8011/health  # CLE
curl http://localhost:8012/health  # DIM (may take 2-3 minutes)
curl http://localhost:8013/health  # EIC
curl http://localhost:8014/health  # CM
```

**Expected Response for Each:**
```json
{
  "status": "healthy",
  "service": "service-name",
  "timestamp": 1234567890
}
```

**Document:** Which services are healthy and response times

### 4.3 Verify Service Integration
```bash
# Check service logs for successful connections
docker compose -f docker-compose.e2e.yml logs | grep -E "(Connected to|Successfully|Ready)"
```

**Expected Messages:**
- "Connected to Temporal server"
- "Database connection established"
- "RabbitMQ connection ready"
- "Service initialization complete"

---

## 🧪 Step 5: Run E2E Test Scenarios

### 5.1 Execute Test Suite (Expected: 5-10 minutes)
```bash
# Run comprehensive E2E tests
cd tests/e2e
python3 test_scenarios.py
```

**What's Being Tested:**
1. **Service Health Checks** - All services responding
2. **Database Connectivity** - Data persistence working
3. **Perfect Match Workflow** - €1500 payment → INV-12345 (€1500)
4. **Overpayment Workflow** - €2500 payment → 2 invoices (€2200 total)
5. **Short Payment Workflow** - €800 payment → INV (€1000) 
6. **Unmatched Payment** - Payment with invalid invoice reference
7. **Document Processing** - OCR extraction of invoice numbers
8. **ERP Integration** - Fetch invoices from mock ERP
9. **Communication Module** - Send notifications
10. **Concurrent Processing** - 5 simultaneous transactions
11. **Error Handling** - Invalid transaction data
12. **Workflow Orchestration** - Temporal workflow management

### 5.2 Monitor Test Execution
```bash
# In another terminal, watch service activity
docker compose -f docker-compose.e2e.yml logs -f --tail=50

# Check Temporal workflow execution
curl http://localhost:7234/api/v1/workflows
```

**Expected Test Flow for Perfect Match:**
1. Submit transaction via Orchestrator API
2. Orchestrator starts Temporal workflow
3. DIM extracts invoice ID from remittance data
4. EIC fetches invoice details from ERP
5. CLE matches payment to invoice
6. EIC updates ERP with payment application
7. CM sends completion notification
8. Workflow returns success

### 5.3 Document Test Results
The test will generate a results file: `e2e_test_results_[timestamp].json`

**Key Metrics to Document:**
- Total tests run: ___
- Tests passed: ___
- Tests failed: ___
- Success rate: ___%
- Average processing time per transaction: ___ms
- Failed test names and error messages

---

## 📊 Step 6: Analyze Results

### 6.1 Review Test Output
```bash
# View latest results file
ls -la e2e_test_results_*.json | tail -1
cat e2e_test_results_[timestamp].json | jq '.'
```

### 6.2 Critical Success Indicators

**✅ PRODUCTION READY if:**
- Service health checks: 100% pass
- Perfect match workflow: PASS
- Error handling: PASS  
- At least 10/12 total tests pass
- No system crashes or timeouts

**⚠️ NEEDS ATTENTION if:**
- Less than 8/12 tests pass
- Perfect match workflow fails
- System performance issues
- Service connectivity problems

### 6.3 Common Issues and Solutions

**If DIM (Document Intelligence) fails:**
- Issue: ML model loading timeout
- Solution: Increase startup timeout, check memory

**If Temporal workflows timeout:**
- Issue: Workflow engine connectivity
- Solution: Check Temporal logs, restart temporal service

**If ERP integration fails:**
- Issue: Mock ERP endpoints not responding
- Solution: Expected in test environment, check logs

**If concurrent processing fails:**
- Issue: Resource constraints
- Solution: Check system resources, reduce concurrent load

---

## 📝 Step 7: Generate Final Report

### 7.1 Create Test Report
```bash
# Generate comprehensive test report
./run_e2e_tests.sh  # This will create final report
```

### 7.2 Document Your Findings

**Create a summary document with:**

1. **Test Environment:**
   - Docker version: ___
   - System specs: ___ RAM, ___ CPU cores
   - OS: ___

2. **Service Startup Results:**
   - Infrastructure startup time: ___ minutes
   - Application startup time: ___ minutes
   - Services that failed to start: ___

3. **Test Execution Results:**
   - Total execution time: ___ minutes
   - Tests passed: ___ / 12
   - Success rate: ___%

4. **Performance Metrics:**
   - Perfect match processing time: ___ms
   - Overpayment detection time: ___ms
   - Concurrent processing capability: ___

5. **Issues Encountered:**
   - List any failures and error messages
   - Steps taken to resolve issues
   - Remaining problems

6. **Production Readiness Assessment:**
   - ✅ Ready for production / ⚠️ Needs work / ❌ Not ready
   - Confidence level in system stability: ___/10
   - Recommended next steps

---

## 🎯 Step 8: Clean Up

### 8.1 Stop All Services
```bash
# Stop E2E environment
docker compose -f docker-compose.e2e.yml down --volumes

# Clean up resources
docker system prune -f
```

### 8.2 Preserve Test Results
```bash
# Archive test results
mkdir -p test_archives/$(date +%Y%m%d)
cp e2e_test_results_*.json test_archives/$(date +%Y%m%d)/
cp tests/e2e/results/* test_archives/$(date +%Y%m%d)/ 2>/dev/null || true
```

---

## 🚨 Troubleshooting Guide

### Build Issues
```bash
# If build fails, check:
docker system df  # Disk space
docker system prune -f --volumes  # Clean space
docker compose -f docker-compose.e2e.yml build --no-cache  # Force rebuild
```

### Startup Issues
```bash
# Check service logs
docker compose -f docker-compose.e2e.yml logs [service-name]

# Check port conflicts
netstat -an | grep [port-number]

# Check resource usage
docker stats
```

### Test Failures
```bash
# Check individual service health
curl -v http://localhost:8006/health

# Check database connectivity
docker compose -f docker-compose.e2e.yml exec postgres-e2e psql -U cashapp_user -d cashapp_e2e -c "SELECT 1;"

# Check workflow engine
curl http://localhost:7234/api/v1/namespaces
```

---

## 📋 Final Checklist

Before declaring the system ready:

□ All infrastructure services started successfully
□ All 5 application services are healthy  
□ Perfect match workflow completes end-to-end
□ System handles error scenarios gracefully
□ Performance is acceptable (< 60s per transaction)
□ No memory leaks or resource issues observed
□ Test results are documented and preserved

**Success means your CashAppAgent is ready for the Unilever demo! 🎉**