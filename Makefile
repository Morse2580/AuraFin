# CashAppAgent Development Makefile
# Streamlined commands for development and deployment

.PHONY: help setup start stop restart status logs clean test build deploy health security

# Default target
.DEFAULT_GOAL := help

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[1;33m
RED := \033[0;31m
NC := \033[0m

# Project configuration
PROJECT_NAME := cashappagent
SERVICES := cle dim eic cm
COMPOSE_FILE := docker-compose.yml

help: ## Show this help message
	@echo "$(BLUE)CashAppAgent Development Commands$(NC)"
	@echo "=================================="
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "$(GREEN)%-20s$(NC) %s\n", $$1, $$2}'

# =============================================================================
# DEVELOPMENT ENVIRONMENT
# =============================================================================

setup: ## Initial project setup and environment creation
	@echo "$(BLUE)Setting up CashAppAgent development environment...$(NC)"
	@mkdir -p logs config
	@if [ ! -f .env ]; then cp .env.example .env; echo "$(YELLOW)Created .env file - please update with actual values$(NC)"; fi
	@echo "$(GREEN)Setup complete!$(NC)"

start: ## Start all services in development mode
	@echo "$(BLUE)Starting CashAppAgent services...$(NC)"
	@docker-compose up -d
	@sleep 15
	@make health

stop: ## Stop all services
	@echo "$(BLUE)Stopping CashAppAgent services...$(NC)"
	@docker-compose down

restart: ## Restart all services
	@echo "$(BLUE)Restarting CashAppAgent services...$(NC)"
	@docker-compose restart
	@sleep 10
	@make health

status: ## Show status of all services
	@echo "$(BLUE)Service Status:$(NC)"
	@docker-compose ps

logs: ## Show logs for all services (use 'make logs SERVICE=cle' for specific service)
ifdef SERVICE
	@docker-compose logs -f $(SERVICE)
else
	@docker-compose logs -f
endif

# =============================================================================
# HEALTH AND MONITORING
# =============================================================================

health: ## Check health of all services
	@echo "$(BLUE)Health Check Results:$(NC)"
	@curl -s http://localhost:8080/health && echo "$(GREEN)✅ Gateway healthy$(NC)" || echo "$(RED)❌ Gateway unhealthy$(NC)"
	@curl -s http://localhost:8001/health && echo "$(GREEN)✅ CLE healthy$(NC)" || echo "$(RED)❌ CLE unhealthy$(NC)"
	@curl -s http://localhost:8002/health && echo "$(GREEN)✅ DIM healthy$(NC)" || echo "$(RED)❌ DIM unhealthy$(NC)"
	@curl -s http://localhost:8003/health && echo "$(GREEN)✅ EIC healthy$(NC)" || echo "$(RED)❌ EIC unhealthy$(NC)"
	@curl -s http://localhost:8004/health && echo "$(GREEN)✅ CM healthy$(NC)" || echo "$(RED)❌ CM unhealthy$(NC)"

monitor: ## Open monitoring dashboards
	@echo "$(BLUE)Monitoring Dashboards:$(NC)"
	@echo "Grafana: http://localhost:3000 (admin/admin123)"
	@echo "Prometheus: http://localhost:9090"

api-docs: ## Show API documentation URLs
	@echo "$(BLUE)API Documentation URLs:$(NC)"
	@echo "Gateway: http://localhost:8080/docs"
	@echo "CLE (Core Logic Engine): http://localhost:8001/docs"
	@echo "DIM (Document Intelligence): http://localhost:8002/docs"
	@echo "EIC (ERP Integration): http://localhost:8003/docs"
	@echo "CM (Communication Module): http://localhost:8004/docs"

# =============================================================================
# TESTING
# =============================================================================

test: ## Run all tests
	@echo "$(BLUE)Running tests...$(NC)"
	@python -m pytest tests/ -v
	@echo "$(GREEN)All tests completed!$(NC)"

test-integration: ## Run integration tests
	@echo "$(BLUE)Running integration tests...$(NC)"
	@python -m pytest tests/test_integration.py -v

test-service: ## Run tests for specific service (use 'make test-service SERVICE=cle')
ifndef SERVICE
	@echo "$(YELLOW)Usage: make test-service SERVICE=<service_name>$(NC)"
	@echo "Available services: $(SERVICES)"
else
	@echo "$(BLUE)Running tests for $(SERVICE)...$(NC)"
	@docker-compose exec $(SERVICE) python -m pytest tests/ -v
endif

test-data: ## Generate test data
	@echo "$(BLUE)Generating test data...$(NC)"
	@python -c "from shared.test_data import setup_test_database; setup_test_database()"
	@echo "$(GREEN)Test data generated!$(NC)"

# =============================================================================
# CODE QUALITY
# =============================================================================

lint: ## Run code linting
	@echo "$(BLUE)Running linting...$(NC)"
	@python -m flake8 shared/ services/ --max-line-length=120 --ignore=E203,W503
	@echo "$(GREEN)Linting complete!$(NC)"

format: ## Format code using black
	@echo "$(BLUE)Formatting code...$(NC)"
	@python -m black shared/ services/ tests/ scripts/
	@echo "$(GREEN)Code formatting complete!$(NC)"

security-scan: ## Run security vulnerability scan
	@echo "$(BLUE)Running security scan...$(NC)"
	@python -m bandit -r shared/ services/ || true
	@python -m safety check || true
	@echo "$(GREEN)Security scan complete!$(NC)"

# =============================================================================
# BUILD AND DEPLOYMENT
# =============================================================================

build: ## Build all service images
	@echo "$(BLUE)Building service images...$(NC)"
	@docker-compose build
	@echo "$(GREEN)Build complete!$(NC)"

build-service: ## Build specific service image (use 'make build-service SERVICE=cle')
ifndef SERVICE
	@echo "$(YELLOW)Usage: make build-service SERVICE=<service_name>$(NC)"
	@echo "Available services: $(SERVICES)"
else
	@echo "$(BLUE)Building $(SERVICE) image...$(NC)"
	@docker-compose build $(SERVICE)
	@echo "$(GREEN)Build complete for $(SERVICE)!$(NC)"
endif

deploy: ## Deploy using simple deployment script
	@echo "$(BLUE)Starting CashAppAgent deployment...$(NC)"
	@python scripts/simple_deploy.py deploy
	@echo "$(GREEN)Deployment completed!$(NC)"

deploy-clean: ## Clean deployment
	@echo "$(BLUE)Cleaning up deployment...$(NC)"
	@python scripts/simple_deploy.py cleanup
	@echo "$(GREEN)Cleanup completed!$(NC)"

# =============================================================================
# SECURITY
# =============================================================================

security-setup: ## Initialize security (API keys, etc.)
	@echo "$(BLUE)Setting up security...$(NC)"
	@python scripts/setup_security.py setup
	@echo "$(GREEN)Security setup completed!$(NC)"

security-reset: ## Reset security configuration
	@echo "$(YELLOW)Resetting security...$(NC)"
	@python scripts/setup_security.py reset
	@echo "$(GREEN)Security reset completed!$(NC)"

# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

db-shell: ## Open PostgreSQL shell
	@docker-compose exec postgres psql -U cashapp_user -d cashapp

redis-shell: ## Open Redis CLI
	@docker-compose exec redis redis-cli

db-backup: ## Create database backup
	@echo "$(BLUE)Creating database backup...$(NC)"
	@mkdir -p backups
	@docker-compose exec postgres pg_dump -U cashapp_user cashapp > backups/cashapp_$(shell date +%Y%m%d_%H%M%S).sql
	@echo "$(GREEN)Database backup created!$(NC)"

db-reset: ## Reset database (WARNING: This will destroy all data)
	@echo "$(RED)⚠️  WARNING: This will destroy all database data!$(NC)"
	@echo "Are you sure? [y/N]"
	@read -r REPLY; if [ "$$REPLY" != "y" ] && [ "$$REPLY" != "Y" ]; then echo "Operation cancelled."; exit 1; fi
	@docker-compose down postgres
	@docker volume rm cashup-agent_postgres_data || true
	@docker-compose up -d postgres
	@sleep 10
	@echo "$(GREEN)Database reset complete!$(NC)"

# =============================================================================
# DEVELOPMENT UTILITIES
# =============================================================================

shell: ## Open shell in service container (use 'make shell SERVICE=cle')
ifndef SERVICE
	@echo "$(YELLOW)Usage: make shell SERVICE=<service_name>$(NC)"
	@echo "Available services: $(SERVICES) postgres redis"
else
	@docker-compose exec $(SERVICE) /bin/bash
endif

clean: ## Clean up containers, volumes, and images
	@echo "$(YELLOW)Cleaning up CashAppAgent environment...$(NC)"
	@docker-compose down -v --remove-orphans
	@docker system prune -f
	@echo "$(GREEN)Cleanup complete!$(NC)"

clean-all: ## Clean up everything including images (DESTRUCTIVE)
	@echo "$(RED)⚠️  This will remove ALL Docker data including images!$(NC)"
	@echo "Are you sure? [y/N]"
	@read -r REPLY; if [ "$$REPLY" != "y" ] && [ "$$REPLY" != "Y" ]; then echo "Cleanup cancelled."; exit 1; fi
	@docker-compose down -v --remove-orphans
	@docker system prune -a -f --volumes
	@echo "$(GREEN)Everything cleaned!$(NC)"

# =============================================================================
# COMPLETE WORKFLOWS
# =============================================================================

dev: ## Complete development setup and start
	@make setup
	@make build
	@make start
	@make security-setup
	@make test-data
	@echo "$(GREEN)🎉 Development environment ready!$(NC)"
	@make api-docs

prod-check: ## Check if ready for production
	@echo "$(BLUE)Production readiness check...$(NC)"
	@make lint
	@make test
	@make security-scan
	@make build
	@echo "$(GREEN)Production readiness check complete!$(NC)"

info: ## Show deployment and service information
	@python scripts/simple_deploy.py info

# =============================================================================
# QUICK COMMANDS
# =============================================================================

quick-start: ## Quick start (build and deploy)
	@make build && make deploy

quick-test: ## Quick test run
	@make test-integration

quick-clean: ## Quick cleanup and restart
	@make stop && make clean && make start