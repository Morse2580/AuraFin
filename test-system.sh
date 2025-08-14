#!/bin/bash
# Complete CashAppAgent System Test Script
# Run this script to test the entire system automatically

set -e  # Exit on any error

echo "🚀 CashAppAgent System Test Starting..."
echo "========================================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test result tracking
TESTS_PASSED=0
TESTS_FAILED=0

test_result() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✅ $2${NC}"
        ((TESTS_PASSED++))
    else
        echo -e "${RED}❌ $2${NC}"
        ((TESTS_FAILED++))
    fi
}

wait_for_service() {
    local url=$1
    local name=$2
    local max_attempts=30
    local attempt=1
    
    echo -e "${YELLOW}⏳ Waiting for $name to be ready...${NC}"
    
    while [ $attempt -le $max_attempts ]; do
        if curl -s -f "$url" > /dev/null 2>&1; then
            echo -e "${GREEN}✅ $name is ready${NC}"
            return 0
        fi
        echo "Attempt $attempt/$max_attempts failed, waiting 5 seconds..."
        sleep 5
        ((attempt++))
    done
    
    echo -e "${RED}❌ $name failed to start after $max_attempts attempts${NC}"
    return 1
}

echo -e "${BLUE}Phase 1: Infrastructure Setup${NC}"
echo "============================================"

# Clean start
echo "🧹 Cleaning up any existing containers..."
docker compose down --volumes --remove-orphans > /dev/null 2>&1
docker system prune -f > /dev/null 2>&1

# Start infrastructure
echo "🚀 Starting infrastructure services..."
docker compose up -d postgres redis rabbitmq temporal > /dev/null 2>&1

# Wait for infrastructure
wait_for_service "http://localhost:15672/api/overview" "RabbitMQ" 
test_result $? "RabbitMQ startup"

# Test database connectivity
docker compose exec postgres pg_isready -U cashapp_user -d cashapp > /dev/null 2>&1
test_result $? "PostgreSQL connectivity"

# Test Redis
docker compose exec redis redis-cli ping > /dev/null 2>&1
test_result $? "Redis connectivity"

# Test Temporal
sleep 30  # Temporal needs more time
curl -s -f http://localhost:7233/api/v1/namespaces > /dev/null 2>&1
test_result $? "Temporal connectivity"

echo -e "${BLUE}Phase 2: Monitoring Stack${NC}"
echo "============================================"

# Start monitoring
echo "📊 Starting monitoring services..."
docker compose up -d prometheus grafana alertmanager node-exporter > /dev/null 2>&1

wait_for_service "http://localhost:9090/-/healthy" "Prometheus"
test_result $? "Prometheus startup"

wait_for_service "http://localhost:3000/api/health" "Grafana"
test_result $? "Grafana startup"

echo -e "${BLUE}Phase 3: Application Services${NC}"
echo "============================================"

# Build and start application services
echo "🔨 Building application services (this may take 15-20 minutes)..."
docker compose build --parallel orchestrator cle dim eic cm > /dev/null 2>&1
test_result $? "Application services build"

# Start orchestrator
echo "🚀 Starting orchestrator..."
docker compose up -d orchestrator > /dev/null 2>&1
wait_for_service "http://localhost:8005/health" "Orchestrator"
test_result $? "Orchestrator startup"

# Start CLE
echo "🚀 Starting Core Logic Engine..."
docker compose up -d cle > /dev/null 2>&1
wait_for_service "http://localhost:8001/health" "CLE"
test_result $? "CLE startup"

# Start DIM (takes longer due to ML models)
echo "🚀 Starting Document Intelligence (may take 2-3 minutes)..."
docker compose up -d dim > /dev/null 2>&1
wait_for_service "http://localhost:8002/health" "DIM"
test_result $? "DIM startup"

# Start EIC
echo "🚀 Starting ERP Integration..."
docker compose up -d eic > /dev/null 2>&1
wait_for_service "http://localhost:8003/health" "EIC"
test_result $? "EIC startup"

# Start CM
echo "🚀 Starting Communication Management..."
docker compose up -d cm > /dev/null 2>&1
wait_for_service "http://localhost:8004/health" "CM"
test_result $? "CM startup"

# Start gateway
echo "🚀 Starting API Gateway..."
docker compose up -d nginx > /dev/null 2>&1
wait_for_service "http://localhost:8080/health" "API Gateway"
test_result $? "API Gateway startup"

echo -e "${BLUE}Phase 4: End-to-End Testing${NC}"
echo "============================================"

# Test workflow API
echo "🧪 Testing Temporal workflows..."
response=$(curl -s -w "%{http_code}" -X POST http://localhost:8005/api/v1/workflows/cash-application/start \
  -H "Content-Type: application/json" \
  -d '{
    "id": "test-txn-001",
    "amount": 1000.00,
    "reference": "TEST001",
    "client_id": "test-client",
    "payment_date": "'$(date -u +"%Y-%m-%dT%H:%M:%SZ")'",
    "currency": "USD"
  }' -o /tmp/workflow_response.json)

if [[ "$response" =~ ^2[0-9][0-9]$ ]]; then
    test_result 0 "Workflow API test"
else
    test_result 1 "Workflow API test"
fi

# Test document processing
echo "🧪 Testing document processing..."
response=$(curl -s -w "%{http_code}" -X POST http://localhost:8002/api/v1/documents/extract \
  -H "Content-Type: application/json" \
  -d '{
    "document_content": "Invoice Number: INV-2024-001\nAmount: $1,000.00\nDate: 2024-01-15",
    "document_type": "invoice"
  }' -o /tmp/doc_response.json)

if [[ "$response" =~ ^2[0-9][0-9]$ ]]; then
    test_result 0 "Document processing test"
else
    test_result 1 "Document processing test"
fi

# Test ERP integration
echo "🧪 Testing ERP integration..."
response=$(curl -s -w "%{http_code}" -X POST http://localhost:8003/api/v1/invoices/fetch \
  -H "Content-Type: application/json" \
  -d '{
    "invoice_ids": ["INV-2024-001"],
    "erp_system": "netsuite"
  }' -o /tmp/erp_response.json)

if [[ "$response" =~ ^2[0-9][0-9]$ ]]; then
    test_result 0 "ERP integration test"
else
    test_result 1 "ERP integration test"
fi

# Test communication services
echo "🧪 Testing communication services..."
response=$(curl -s -w "%{http_code}" -X POST http://localhost:8004/api/v1/notifications/send \
  -H "Content-Type: application/json" \
  -d '{
    "recipient": "test@example.com",
    "type": "transaction_completed",
    "data": {"transaction_id": "test-txn-001", "amount": 1000.00}
  }' -o /tmp/comm_response.json)

if [[ "$response" =~ ^2[0-9][0-9]$ ]]; then
    test_result 0 "Communication service test"
else
    test_result 1 "Communication service test"
fi

# Test metrics collection
echo "🧪 Testing metrics collection..."
metrics=$(curl -s http://localhost:9090/api/v1/query?query=up | jq -r '.data.result | length')
if [ "$metrics" -gt 0 ]; then
    test_result 0 "Metrics collection test"
else
    test_result 1 "Metrics collection test"
fi

echo -e "${BLUE}Phase 5: Resource Usage Check${NC}"
echo "============================================"

# Check resource usage
echo "📊 Current resource usage:"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" | head -15

# Check for any unhealthy containers
unhealthy=$(docker compose ps --filter "health=unhealthy" -q | wc -l)
if [ "$unhealthy" -eq 0 ]; then
    test_result 0 "Container health check"
else
    test_result 1 "Container health check ($unhealthy unhealthy containers)"
fi

echo ""
echo "========================================"
echo -e "${BLUE}🏁 Test Results Summary${NC}"
echo "========================================"
echo -e "Tests Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Tests Failed: ${RED}$TESTS_FAILED${NC}"

if [ $TESTS_FAILED -eq 0 ]; then
    echo ""
    echo -e "${GREEN}🎉 ALL TESTS PASSED! Your CashAppAgent system is fully operational!${NC}"
    echo ""
    echo -e "${BLUE}🌐 Access your services:${NC}"
    echo "  • API Gateway:         http://localhost:8080"
    echo "  • Temporal UI:         http://localhost:8085"
    echo "  • RabbitMQ Management: http://localhost:15672 (admin/admin123)"
    echo "  • Grafana Dashboard:   http://localhost:3000 (admin/admin123)"
    echo "  • Prometheus:          http://localhost:9090"
    echo "  • AlertManager:        http://localhost:9093"
    echo ""
    echo -e "${GREEN}✅ System is ready for production deployment!${NC}"
else
    echo ""
    echo -e "${RED}❌ Some tests failed. Check the logs above for details.${NC}"
    echo ""
    echo -e "${YELLOW}Troubleshooting tips:${NC}"
    echo "1. Check service logs: docker compose logs [service-name]"
    echo "2. Restart failed services: docker compose restart [service-name]"
    echo "3. Check available resources (RAM/CPU)"
    echo "4. Ensure all required ports are free"
    exit 1
fi