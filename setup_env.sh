#!/bin/bash

# CashAppAgent Development Environment Setup
# Aura Finance - Complete setup script for local development

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Project configuration
PROJECT_NAME="cashappagent"
SERVICES=("cle" "dim" "eic" "cm")

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check prerequisites
check_prerequisites() {
    print_status "Checking prerequisites..."
    
    local missing_deps=()
    
    if ! command_exists docker; then
        missing_deps+=("docker")
    fi
    
    if ! command_exists docker-compose; then
        missing_deps+=("docker-compose")
    fi
    
    if ! command_exists python3; then
        missing_deps+=("python3")
    fi
    
    if ! command_exists git; then
        missing_deps+=("git")
    fi
    
    if [ ${#missing_deps[@]} -ne 0 ]; then
        print_error "Missing required dependencies: ${missing_deps[*]}"
        print_error "Please install the missing dependencies and run this script again."
        exit 1
    fi
    
    print_success "All prerequisites are installed"
}

# Create project directory structure
create_project_structure() {
    print_status "Creating project directory structure..."
    
    # Main directories
    mkdir -p {services,shared,database,monitoring,nginx,tests,docs,scripts}
    
    # Service directories
    for service in "${SERVICES[@]}"; do
        mkdir -p "services/$service/tests"
        mkdir -p "services/$service/alembic/versions"
    done
    
    # Database directories
    mkdir -p database/{migrations,seeds}
    
    # Monitoring directories
    mkdir -p monitoring/{prometheus,grafana/{dashboards,provisioning}}
    mkdir -p monitoring/grafana/provisioning/{dashboards,datasources}
    
    # Nginx directories
    mkdir -p nginx/{ssl,conf.d}
    
    # Shared directories
    mkdir -p shared/{models,utils,exceptions,logging,database,metrics}
    
    print_success "Project directory structure created"
}

# Create environment file
create_environment_file() {
    print_status "Creating environment configuration..."
    
    cat > .env.development << 'EOF'
# CashAppAgent Development Environment Configuration
# Copy this to .env and customize for your environment

# Database Configuration
DATABASE_URL=postgresql://cashapp_user:dev_password_123@localhost:5432/cashapp
POSTGRES_DB=cashapp
POSTGRES_USER=cashapp_user
POSTGRES_PASSWORD=dev_password_123

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# Service URLs (for inter-service communication)
CLE_SERVICE_URL=http://localhost:8000
DIM_SERVICE_URL=http://localhost:8001
EIC_SERVICE_URL=http://localhost:8002
CM_SERVICE_URL=http://localhost:8003

# Azure Configuration (leave empty for local development)
AZURE_KEY_VAULT_URL=
AZURE_BLOB_STORAGE_URL=
AZURE_STORAGE_ACCOUNT_KEY=
AZURE_TENANT_ID=
AZURE_CLIENT_ID=
AZURE_CLIENT_SECRET=

# ERP Configuration (development/testing credentials)
NETSUITE_CLIENT_ID=
NETSUITE_CLIENT_SECRET=
NETSUITE_ACCOUNT_ID=
SAP_BASE_URL=
SAP_USERNAME=
SAP_PASSWORD=

# Communication Configuration
MICROSOFT_GRAPH_CLIENT_ID=
MICROSOFT_GRAPH_CLIENT_SECRET=
MICROSOFT_GRAPH_TENANT_ID=
SLACK_BOT_TOKEN=
EMAIL_FROM_ADDRESS=dev@aurafinance.com

# Monitoring & Logging
LOG_LEVEL=DEBUG
ENVIRONMENT=development
PROMETHEUS_ENABLED=true
METRICS_PORT=8090

# Processing Configuration
MAX_CONCURRENT_TRANSACTIONS=10
PAYMENT_MATCHING_CONFIDENCE_THRESHOLD=0.8
DOCUMENT_PROCESSING_TIMEOUT=30
ERP_API_TIMEOUT=15

# Security Configuration (development only - use Azure Key Vault in production)
JWT_SECRET_KEY=development_secret_key_change_in_production
ENCRYPTION_KEY=development_encryption_key_32_chars

# Feature Flags
ENABLE_ML_DOCUMENT_PROCESSING=true
ENABLE_AUTONOMOUS_ERP_UPDATES=false  # Start with read-only mode
ENABLE_EMAIL_NOTIFICATIONS=false     # Disable in development
ENABLE_SLACK_NOTIFICATIONS=true
EOF

    cp .env.development .env
    
    print_success "Environment file created (.env)"
    print_warning "Please review and customize the .env file with your specific configuration"
}

# Create Prometheus configuration
create_monitoring_config() {
    print_status "Creating monitoring configuration..."
    
    cat > monitoring/prometheus.yml << 'EOF'
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  # Add alerting rules here if needed

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'cashapp-cle'
    static_configs:
      - targets: ['cle:8000']
    metrics_path: '/metrics'
    scrape_interval: 10s

  - job_name: 'cashapp-dim'
    static_configs:
      - targets: ['dim:8001']
    metrics_path: '/metrics'
    scrape_interval: 10s

  - job_name: 'cashapp-eic'
    static_configs:
      - targets: ['eic:8002']
    metrics_path: '/metrics'
    scrape_interval: 10s

  - job_name: 'cashapp-cm'
    static_configs:
      - targets: ['cm:8003']
    metrics_path: '/metrics'
    scrape_interval: 10s

  - job_name: 'postgres'
    static_configs:
      - targets: ['postgres:5432']
    scrape_interval: 30s

  - job_name: 'redis'
    static_configs:
      - targets: ['redis:6379']
    scrape_interval: 30s
EOF

    # Create Grafana datasource configuration
    cat > monitoring/grafana/provisioning/datasources/prometheus.yml << 'EOF'
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: true
EOF

    # Create Grafana dashboard configuration
    cat > monitoring/grafana/provisioning/dashboards/dashboard.yml << 'EOF'
apiVersion: 1

providers:
  - name: 'CashAppAgent Dashboards'
    orgId: 1
    folder: ''
    folderUid: ''
    type: file
    disableDeletion: false
    updateIntervalSeconds: 10
    allowUiUpdates: true
    options:
      path: /var/lib/grafana/dashboards
EOF

    print_success "Monitoring configuration created"
}

# Create Nginx configuration
create_nginx_config() {
    print_status "Creating Nginx reverse proxy configuration..."
    
    cat > nginx/nginx.conf << 'EOF'
events {
    worker_connections 1024;
}

http {
    upstream cle_service {
        server cle:8000;
    }
    
    upstream dim_service {
        server dim:8001;
    }
    
    upstream eic_service {
        server eic:8002;
    }
    
    upstream cm_service {
        server cm:8003;
    }
    
    upstream prometheus {
        server prometheus:9090;
    }
    
    upstream grafana {
        server grafana:3000;
    }

    server {
        listen 80;
        server_name localhost;

        # Core Logic Engine
        location /api/cle/ {
            proxy_pass http://cle_service/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Document Intelligence Module
        location /api/dim/ {
            proxy_pass http://dim_service/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # ERP Integration Connectors
        location /api/eic/ {
            proxy_pass http://eic_service/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Communication Module
        location /api/cm/ {
            proxy_pass http://cm_service/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Prometheus monitoring
        location /prometheus/ {
            proxy_pass http://prometheus/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Grafana dashboard
        location /grafana/ {
            proxy_pass http://grafana/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Health check endpoint
        location /health {
            return 200 'CashAppAgent Development Environment is running';
            add_header Content-Type text/plain;
        }
    }
}
EOF

    print_success "Nginx configuration created"
}

# Create development scripts
create_dev_scripts() {
    print_status "Creating development utility scripts..."
    
    # Quick start script
    cat > scripts/start.sh << 'EOF'
#!/bin/bash
echo "Starting CashAppAgent development environment..."
docker-compose up -d
echo "Services starting... checking health:"
sleep 10
./scripts/health-check.sh
EOF

    # Stop script
    cat > scripts/stop.sh << 'EOF'
#!/bin/bash
echo "Stopping CashAppAgent development environment..."
docker-compose down
EOF

    # Health check script
    cat > scripts/health-check.sh << 'EOF'
#!/bin/bash
echo "Checking service health..."
services=("cle:8000" "dim:8001" "eic:8002" "cm:8003")
for service in "${services[@]}"; do
    if curl -f -s "http://localhost:${service#*:}/health" > /dev/null; then
        echo "✅ ${service%:*} is healthy"
    else
        echo "❌ ${service%:*} is not responding"
    fi
done
EOF

    # Logs script
    cat > scripts/logs.sh << 'EOF'
#!/bin/bash
if [ -z "$1" ]; then
    echo "Usage: ./scripts/logs.sh <service>"
    echo "Available services: cle, dim, eic, cm, postgres, redis"
    exit 1
fi
docker-compose logs -f "$1"
EOF

    # Reset database script
    cat > scripts/reset-db.sh << 'EOF'
#!/bin/bash
echo "Resetting database..."
docker-compose stop postgres
docker-compose rm -f postgres
docker volume rm cashappagent_postgres_data 2>/dev/null || true
docker-compose up -d postgres
echo "Database reset complete"
EOF

    # Make scripts executable
    chmod +x scripts/*.sh
    
    print_success "Development utility scripts created"
}

# Create requirements files for services
create_requirements() {
    print_status "Creating requirements files..."
    
    # Shared requirements
    cat > shared/requirements.txt << 'EOF'
# Shared dependencies for all CashAppAgent services
fastapi==0.104.1
pydantic==2.5.0
sqlalchemy==2.0.23
asyncpg==0.29.0
alembic==1.12.1
redis==5.0.1
prometheus-client==0.19.0
structlog==23.2.0
uvicorn[standard]==0.24.0
pytest==7.4.3
pytest-asyncio==0.21.1
httpx==0.25.2
EOF

    # CLE specific requirements
    cat > services/cle/requirements.txt << 'EOF'
-r ../../shared/requirements.txt

# CLE-specific dependencies
aiofiles==23.2.1
asyncio-semaphore==0.2.0
decimal==1.70
python-multipart==0.0.6
EOF

    print_success "Requirements files created"
}

# Main execution function
main() {
    print_status "Starting CashAppAgent development environment setup..."
    
    check_prerequisites
    create_project_structure
    create_environment_file
    create_monitoring_config
    create_nginx_config
    create_dev_scripts
    create_requirements
    
    print_success "Development environment setup complete!"
    print_status "Next steps:"
    echo "1. Review and customize the .env file with your configuration"
    echo "2. Start the development environment: ./scripts/start.sh"
    echo "3. Check service health: ./scripts/health-check.sh"
    echo "4. View logs: ./scripts/logs.sh <service-name>"
    echo ""
    print_status "Access points:"
    echo "• CLE API: http://localhost:8000"
    echo "• Grafana Dashboard: http://localhost:3000 (admin/admin123)"
    echo "• Prometheus: http://localhost:9090"
    echo "• pgAdmin: http://localhost:5050 (admin@aurafinance.com/admin123)"
    echo "• API Gateway: http://localhost (Nginx reverse proxy)"
}

# Run main function
main "$@"

