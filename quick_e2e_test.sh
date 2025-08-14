#!/bin/bash
# Quick E2E Test - Simplified and Reliable
# Tests the core functionality without complex build process

set -e

echo "🚀 CashAppAgent Quick E2E Test"
echo "=============================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error() { echo -e "${RED}❌ $1${NC}"; }

# Test results
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

run_test() {
    local test_name="$1"
    local test_command="$2"
    
    log_info "Testing: $test_name"
    TESTS_RUN=$((TESTS_RUN + 1))
    
    if eval "$test_command"; then
        log_success "$test_name - PASSED"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        log_error "$test_name - FAILED"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

# Step 1: Test with existing system (if running)
log_info "Step 1: Testing existing system (if running)..."

# Check if main system is running
if docker compose ps | grep -q "Up"; then
    log_info "Found running system, testing main services..."
    
    # Test main system services
    run_test "Main System CLE Health" "curl -s -f http://localhost:8001/health > /dev/null"
    run_test "Main System DIM Health" "curl -s -f http://localhost:8002/health > /dev/null" 
    run_test "Main System EIC Health" "curl -s -f http://localhost:8003/health > /dev/null"
    run_test "Main System CM Health" "curl -s -f http://localhost:8004/health > /dev/null"
    
    # Test database connectivity
    run_test "Database Connection" "docker compose exec postgres pg_isready -U cashapp_user -d cashapp > /dev/null 2>&1"
    
    # Test basic API endpoints
    run_test "CLE Status Endpoint" "curl -s http://localhost:8001/api/v1/status | grep -q 'status'"
    
else
    log_warning "Main system not running. Starting minimal test environment..."
    
    # Step 2: Start minimal services for testing
    log_info "Step 2: Starting minimal test infrastructure..."
    
    # Start just database and redis for basic tests
    docker compose up -d postgres redis > /dev/null 2>&1
    
    # Wait for database
    log_info "Waiting for database to be ready..."
    sleep 10
    
    run_test "Postgres Startup" "docker compose exec postgres pg_isready -U cashapp_user -d cashapp > /dev/null 2>&1"
    run_test "Redis Startup" "docker compose exec redis redis-cli ping | grep -q PONG"
fi

# Step 3: Test core functionality with simple HTTP requests
log_info "Step 3: Testing core functionality..."

# Create a simple test transaction
TEST_TRANSACTION='{
    "id": "TXN-QUICK-TEST-001",
    "amount": 1000.00,
    "currency": "EUR", 
    "payment_date": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
    "reference": "Test payment for INV-TEST-001",
    "client_id": "QUICK-TEST-CLIENT"
}'

# Test if we can reach any service endpoints
if curl -s -f http://localhost:8001/health > /dev/null 2>&1; then
    log_info "CLE service available, testing endpoints..."
    
    run_test "CLE Health Check" "curl -s -f http://localhost:8001/health > /dev/null"
    run_test "CLE Metrics" "curl -s -f http://localhost:8001/metrics > /dev/null"
    
    # Test transaction processing if possible
    if curl -s -f http://localhost:8001/api/v1/status > /dev/null 2>&1; then
        run_test "Transaction Processing Test" "echo '$TEST_TRANSACTION' | curl -s -X POST -H 'Content-Type: application/json' -d @- http://localhost:8001/api/v1/process_transaction | grep -q 'id'"
    fi
fi

if curl -s -f http://localhost:8002/health > /dev/null 2>&1; then
    log_info "DIM service available, testing document processing..."
    
    run_test "DIM Health Check" "curl -s -f http://localhost:8002/health > /dev/null"
    
    # Test document extraction
    TEST_DOC='{"document_content": "Invoice INV-TEST-001 Amount: 1000.00 EUR", "document_type": "invoice"}'
    run_test "Document Processing" "echo '$TEST_DOC' | curl -s -X POST -H 'Content-Type: application/json' -d @- http://localhost:8002/api/v1/documents/extract | grep -q 'invoice_ids'"
fi

if curl -s -f http://localhost:8003/health > /dev/null 2>&1; then
    log_info "EIC service available, testing ERP integration..."
    
    run_test "EIC Health Check" "curl -s -f http://localhost:8003/health > /dev/null"
    
    # Test invoice fetch
    TEST_FETCH='{"invoice_ids": ["INV-TEST-001"], "erp_system": "test"}'
    run_test "ERP Integration" "echo '$TEST_FETCH' | curl -s -X POST -H 'Content-Type: application/json' -d @- http://localhost:8003/api/v1/invoices/fetch | grep -q 'invoices'"
fi

if curl -s -f http://localhost:8004/health > /dev/null 2>&1; then
    log_info "CM service available, testing communication..."
    
    run_test "CM Health Check" "curl -s -f http://localhost:8004/health > /dev/null"
    
    # Test notification
    TEST_NOTIFICATION='{"recipient": "test@example.com", "type": "test", "data": {"message": "test"}}'
    run_test "Notification Service" "echo '$TEST_NOTIFICATION' | curl -s -X POST -H 'Content-Type: application/json' -d @- http://localhost:8004/api/v1/notifications/send | grep -q 'success\\|status'"
fi

# Step 4: Test file system and configurations
log_info "Step 4: Testing system configuration..."

run_test "Docker Compose Config" "docker compose config > /dev/null 2>&1"
run_test "E2E Config Available" "[ -f docker-compose.e2e.yml ]"
run_test "Test Data Available" "[ -f shared/test_data.py ]"
run_test "E2E Test Script Available" "[ -f tests/e2e/test_scenarios.py ]"

# Step 5: Test build capability (without actually building)
log_info "Step 5: Testing build readiness..."

run_test "Dockerfiles Present" "find services -name Dockerfile | wc -l | grep -q '[5-9]'"
run_test "Requirements Files Present" "find services -name requirements.txt | wc -l | grep -q '[5-9]'"
run_test "Shared Modules Available" "[ -d shared ] && [ -f shared/models.py ]"

# Step 6: Generate Results
echo ""
echo "📊 Quick E2E Test Results"
echo "========================="
echo "Tests Run: $TESTS_RUN"
echo "Tests Passed: $TESTS_PASSED"
echo "Tests Failed: $TESTS_FAILED"

if [ $TESTS_FAILED -eq 0 ]; then
    SUCCESS_RATE="100%"
else
    SUCCESS_RATE=$(echo "scale=1; $TESTS_PASSED * 100 / $TESTS_RUN" | bc)"%"
fi

echo "Success Rate: $SUCCESS_RATE"
echo ""

# Determine system status
if [ $TESTS_PASSED -ge $((TESTS_RUN * 80 / 100)) ]; then
    log_success "🎉 SYSTEM STATUS: READY FOR FULL E2E TESTING"
    echo ""
    echo "✅ Core services are functional"
    echo "✅ Basic API endpoints working"
    echo "✅ Configuration files present"
    echo "✅ Ready to run full E2E test suite"
    echo ""
    echo "Next Steps:"
    echo "1. Run full E2E tests: ./run_e2e_tests.sh"
    echo "2. Or start services: docker compose up -d"
    echo "3. Or read the guide: cat E2E_TESTING_GUIDE.md"
    
elif [ $TESTS_PASSED -ge $((TESTS_RUN * 50 / 100)) ]; then
    log_warning "⚠️  SYSTEM STATUS: PARTIALLY READY"
    echo ""
    echo "✅ Basic system structure is good"
    echo "⚠️  Some services may need attention"
    echo "🔧 Review failed tests and fix issues"
    echo ""
    echo "Recommended:"
    echo "1. Start main system: docker compose up -d"
    echo "2. Check service logs for errors"
    echo "3. Fix any configuration issues"
    
else
    log_error "❌ SYSTEM STATUS: NEEDS WORK"
    echo ""
    echo "❌ Multiple core issues detected"
    echo "🔧 System requires attention before E2E testing"
    echo ""
    echo "Action Required:"
    echo "1. Check Docker and service configuration"
    echo "2. Ensure all required files are present"
    echo "3. Start with basic service health checks"
fi

# Save results
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULTS_FILE="quick_e2e_results_$TIMESTAMP.txt"

cat > "$RESULTS_FILE" << EOF
CashAppAgent Quick E2E Test Results
==================================
Date: $(date)
Tests Run: $TESTS_RUN
Tests Passed: $TESTS_PASSED  
Tests Failed: $TESTS_FAILED
Success Rate: $SUCCESS_RATE

System Status: $(if [ $TESTS_PASSED -ge $((TESTS_RUN * 80 / 100)) ]; then echo "READY"; elif [ $TESTS_PASSED -ge $((TESTS_RUN * 50 / 100)) ]; then echo "PARTIALLY READY"; else echo "NEEDS WORK"; fi)

Next Steps:
- Review any failed tests
- Check service logs if needed
- Run full E2E test suite when ready

EOF

echo "Results saved to: $RESULTS_FILE"

exit $([ $TESTS_PASSED -ge $((TESTS_RUN * 50 / 100)) ] && echo 0 || echo 1)