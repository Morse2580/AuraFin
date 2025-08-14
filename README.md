CashAppAgent Development Environment
Aura Finance - Complete Docker-based development environment for autonomous cash application processing

🚀 Quick Start
bash
# 1. Clone and setup the environment
git clone <repository-url>
cd cashappagent
make setup

# 2. Start all services
make start

# 3. Check service health
make health

# 4. View API documentation
make api-docs
📋 Prerequisites
Docker 20.10+
Docker Compose 2.0+
Python 3.11+ (for local development)
Git 2.30+
Make (for simplified commands)
🏗️ Architecture Overview
The CashAppAgent is composed of four microservices running in a secure network:

┌─────────────────────────────────────────────────────────────┐
│                    Nginx Reverse Proxy                     │
│                        (Port 80)                           │
└─────────────────┬───────────────────────────────────────────┘
                  │
    ┌─────────────┼─────────────┐
    │             │             │
┌───▼───┐    ┌───▼───┐    ┌───▼───┐    ┌───────┐
│  CLE  │    │  DIM  │    │  EIC  │    │  CM   │
│ :8000 │    │ :8001 │    │ :8002 │    │ :8003 │
└───┬───┘    └───┬───┘    └───┬───┘    └───┬───┘
    │            │            │            │
    └────────────┼────────────┼────────────┘
                 │            │
            ┌────▼────┐  ┌────▼────┐
            │PostgreSQL│  │  Redis  │
            │  :5432  │  │  :6379  │
            └─────────┘  └─────────┘
Services
CLE (Core Logic Engine): The "brain" - payment matching and business logic
DIM (Document Intelligence Module): The "eyes" - ML-powered document parsing
EIC (ERP Integration Connectors): The "hands" - secure ERP API communication
CM (Communication Module): The "mouth" - automated notifications
🛠️ Development Commands
Essential Commands
bash
make help          # Show all available commands
make dev           # Complete development setup
make start         # Start all services
make stop          # Stop all services
make status        # Show service status
make health        # Health check all services
make logs          # View all logs (or make logs SERVICE=cle)
Database Operations
bash
make migrate       # Run database migrations
make reset-db      # Reset database (destroys all data)
make db-shell      # Open PostgreSQL shell
make backup-db     # Create database backup
make seed-data     # Load sample data
Development Tools
bash
make test          # Run all tests
make test-service SERVICE=cle  # Test specific service
make lint          # Run code linting
make format        # Format code with black
make shell SERVICE=cle         # Open shell in service
Monitoring & Debugging
bash
make monitor       # Show monitoring dashboard URLs
make api-docs      # Show API documentation URLs
🔧 Service Configuration
Environment Variables
Copy .env.development to .env and customize:

bash
# Database
DATABASE_URL=postgresql://cashapp_user:dev_password_123@localhost:5432/cashapp

# Services
CLE_SERVICE_URL=http://localhost:8000
DIM_SERVICE_URL=http://localhost:8001

# Azure (leave empty for local dev)
AZURE_KEY_VAULT_URL=
AZURE_BLOB_STORAGE_URL=

# ERP Integration
NETSUITE_CLIENT_ID=
SAP_BASE_URL=

# Feature Flags
ENABLE_AUTONOMOUS_ERP_UPDATES=false  # Start read-only
ENABLE_EMAIL_NOTIFICATIONS=false     # Disable in dev
Service-Specific Configuration
Core Logic Engine (CLE)
Port: 8000
API Docs: http://localhost:8000/docs
Health: http://localhost:8000/health
Metrics: http://localhost:8000/metrics
Document Intelligence Module (DIM)
Port: 8001
Requires: GPU support for ML models (optional)
Models: Cached in dim_models volume
ERP Integration Connectors (EIC)
Port: 8002
Supports: NetSuite, SAP, custom ERPs
Security: OAuth 2.0 with token rotation
Communication Module (CM)
Port: 8003
Integrates: Microsoft Graph, Slack API
Templates: Configurable email/message templates
📊 Monitoring & Observability
Dashboards
Grafana: http://localhost:3000 (admin/admin123)
Business metrics (transaction volume, success rates)
Technical metrics (latency, error rates)
System health (CPU, memory, disk)
Prometheus: http://localhost:9090
Raw metrics collection
Alerting rules configuration
pgAdmin: http://localhost:5050 (admin@aurafinance.com/admin123)
Database administration
Query performance analysis
Key Metrics
Business Metrics:

cashapp_transactions_processed_total
cashapp_perfect_matches_total
cashapp_short_payments_total
cashapp_processing_duration_seconds
Technical Metrics:

http_requests_total
http_request_duration_seconds
database_connections_active
redis_operations_total
🧪 Testing
Test Structure
tests/
├── unit/          # Fast, isolated tests
├── integration/   # Service interaction tests
├── performance/   # Load and performance tests
└── e2e/          # End-to-end workflow tests
Running Tests
bash
# All tests
make test

# Specific service
make test-service SERVICE=cle

# Performance tests
make performance-test

# With coverage
docker-compose exec cle python -m pytest tests/ --cov=. --cov-report=html
🔒 Security
Development Security
Non-root containers: All services run as non-root users
Network isolation: Services communicate via private network
Secret management: Environment variables (production uses Azure Key Vault)
Input validation: Pydantic models with strict typing
SQL injection prevention: SQLAlchemy ORM with parameterized queries
Security Scanning
bash
make security-scan    # Check for vulnerabilities
make prod-ready-check # Complete production readiness
🚀 Deployment Pipeline
Phase 1: Read-Only Analysis
bash
# Deploy in read-only mode
ENABLE_AUTONOMOUS_ERP_UPDATES=false make start
Phase 2: Limited Write Access
bash
# Enable limited ERP updates
ENABLE_AUTONOMOUS_ERP_UPDATES=true
PERFECT_MATCH_ONLY=true make restart
Phase 3: Full Autonomous Mode
bash
# Full autonomous operation
ENABLE_AUTONOMOUS_ERP_UPDATES=true
PERFECT_MATCH_ONLY=false make restart
📁 Project Structure
cashappagent/
├── services/              # Microservices
│   ├── cle/              # Core Logic Engine
│   ├── dim/              # Document Intelligence
│   ├── eic/              # ERP Integration
│   └── cm/               # Communication Module
├── shared/               # Shared utilities
│   ├── models/           # Pydantic models
│   ├── database/         # Database utilities
│   └── logging/          # Structured logging
├── database/             # Database schema & migrations
├── monitoring/           # Prometheus & Grafana config
├── nginx/                # Reverse proxy config
├── scripts/              # Development utilities
└── tests/                # Test suites
🔧 API Endpoints
Core Logic Engine (CLE)
http
POST /api/v1/process_transaction
GET  /health
GET  /metrics
Document Intelligence Module (DIM)
http
POST /api/v1/parse_document
POST /api/v1/extract_invoice_ids
GET  /health
ERP Integration Connectors (EIC)
http
POST /api/v1/get_invoices
POST /api/v1/post_application
GET  /api/v1/systems
GET  /health
Communication Module (CM)
http
POST /api/v1/send_clarification_email
POST /api/v1/send_internal_alert
GET  /api/v1/templates
GET  /health
🐛 Troubleshooting
Common Issues
Services won't start:

bash
# Check Docker resources
docker system df
docker system prune

# Restart with clean state
make clean
make start
Database connection errors:

bash
# Reset database
make reset-db
make migrate
Port conflicts:

bash
# Check port usage
netstat -tulpn | grep :8000

# Stop conflicting services
sudo systemctl stop <service>
Performance issues:

bash
# Check resource usage
docker stats

# Scale specific service
docker-compose up -d --scale cle=2
Logs and Debugging
bash
# Service-specific logs
make logs SERVICE=cle

# Database logs
docker-compose logs postgres

# Real-time monitoring
docker-compose logs -f

# Debug mode
LOG_LEVEL=DEBUG make restart
📚 Additional Resources
API Documentation: Available at /docs endpoint for each service
Database Schema: See database/schema.sql
Monitoring: Grafana dashboards in monitoring/grafana/dashboards/
Architecture: Complete specification in project documentation
🤝 Contributing
Create feature branch: git checkout -b feature/your-feature
Run tests: make test
Check code quality: make lint
Submit pull request
📞 Support
Development Issues: Check logs with make logs
Performance: Monitor with make monitor
Database: Access with make db-shell
Built with ❤️ by Aura Finance Engineering Team

