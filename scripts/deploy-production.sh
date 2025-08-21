#!/bin/bash

# CashUp Agent Production Deployment Script
# This script deploys the complete ML system to production

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
ENVIRONMENT=${1:-production}
VERSION=${2:-latest}
NAMESPACE="cashup-${ENVIRONMENT}"

echo -e "${BLUE}🚀 Starting CashUp Agent Production Deployment${NC}"
echo -e "${BLUE}Environment: ${ENVIRONMENT}${NC}"
echo -e "${BLUE}Version: ${VERSION}${NC}"
echo ""

# Pre-deployment checks
echo -e "${YELLOW}📋 Running pre-deployment checks...${NC}"

# Check if required tools are installed
command -v docker >/dev/null 2>&1 || { echo -e "${RED}❌ Docker is required but not installed${NC}"; exit 1; }
command -v kubectl >/dev/null 2>&1 || { echo -e "${RED}❌ kubectl is required but not installed${NC}"; exit 1; }
command -v helm >/dev/null 2>&1 || { echo -e "${RED}❌ Helm is required but not installed${NC}"; exit 1; }

# Check if environment file exists
if [ ! -f ".env.${ENVIRONMENT}" ]; then
    echo -e "${RED}❌ Environment file .env.${ENVIRONMENT} not found${NC}"
    exit 1
fi

# Load environment variables
set -a
source ".env.${ENVIRONMENT}"
set +a

echo -e "${GREEN}✅ Pre-deployment checks passed${NC}"

# Create namespace if it doesn't exist
echo -e "${YELLOW}🔧 Setting up Kubernetes namespace...${NC}"
kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

# Create secrets from environment file
echo -e "${YELLOW}🔐 Creating Kubernetes secrets...${NC}"
kubectl create secret generic cashup-secrets \
    --from-env-file=".env.${ENVIRONMENT}" \
    --namespace="${NAMESPACE}" \
    --dry-run=client -o yaml | kubectl apply -f -

# Deploy infrastructure services first
echo -e "${YELLOW}🏗️  Deploying infrastructure services...${NC}"

# PostgreSQL
helm upgrade --install cashup-postgres bitnami/postgresql \
    --namespace="${NAMESPACE}" \
    --set auth.postgresPassword="${DATABASE_PASSWORD}" \
    --set auth.database=cashup_production \
    --set primary.persistence.size=100Gi \
    --set metrics.enabled=true \
    --wait

# Redis
helm upgrade --install cashup-redis bitnami/redis \
    --namespace="${NAMESPACE}" \
    --set auth.password="${REDIS_PASSWORD}" \
    --set master.persistence.size=20Gi \
    --set metrics.enabled=true \
    --wait

# RabbitMQ
helm upgrade --install cashup-rabbitmq bitnami/rabbitmq \
    --namespace="${NAMESPACE}" \
    --set auth.username=cashup \
    --set auth.password="${RABBITMQ_PASSWORD}" \
    --set persistence.size=20Gi \
    --set metrics.enabled=true \
    --wait

echo -e "${GREEN}✅ Infrastructure services deployed${NC}"

# Deploy application services
echo -e "${YELLOW}🚀 Deploying CashUp Agent services...${NC}"

# Apply Kubernetes manifests
kubectl apply -f k8s/production/ --namespace="${NAMESPACE}"

# Wait for deployments to be ready
echo -e "${YELLOW}⏳ Waiting for services to be ready...${NC}"

services=("cashup-cle" "cashup-orchestrator" "cashup-dim" "cashup-eic" "cashup-cm")

for service in "${services[@]}"; do
    echo -e "${BLUE}Waiting for ${service}...${NC}"
    kubectl rollout status deployment/"${service}" --namespace="${NAMESPACE}" --timeout=600s
    
    # Wait for pods to be ready
    kubectl wait --for=condition=ready pod -l app="${service}" --namespace="${NAMESPACE}" --timeout=300s
    
    echo -e "${GREEN}✅ ${service} is ready${NC}"
done

# Deploy monitoring stack
echo -e "${YELLOW}📊 Deploying monitoring stack...${NC}"

# Create monitoring namespace
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -

# Deploy Prometheus stack
helm upgrade --install prometheus-stack prometheus-community/kube-prometheus-stack \
    --namespace=monitoring \
    --set grafana.adminPassword="${GRAFANA_ADMIN_PASSWORD}" \
    --set grafana.persistence.enabled=true \
    --set grafana.persistence.size=10Gi \
    --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.resources.requests.storage=50Gi \
    --wait

echo -e "${GREEN}✅ Monitoring stack deployed${NC}"

# Deploy Nginx ingress
echo -e "${YELLOW}🌐 Setting up ingress...${NC}"

# Deploy Nginx ingress controller
helm upgrade --install nginx-ingress ingress-nginx/ingress-nginx \
    --namespace=ingress-nginx \
    --create-namespace \
    --set controller.service.type=LoadBalancer \
    --set controller.metrics.enabled=true \
    --wait

# Apply ingress rules
kubectl apply -f k8s/ingress/ --namespace="${NAMESPACE}"

echo -e "${GREEN}✅ Ingress configured${NC}"

# Run health checks
echo -e "${YELLOW}🏥 Running health checks...${NC}"

for service in "${services[@]}"; do
    echo -e "${BLUE}Health checking ${service}...${NC}"
    
    # Get service URL
    if [ "${service}" = "cashup-cle" ]; then
        port=8001
    elif [ "${service}" = "cashup-orchestrator" ]; then
        port=8005
    elif [ "${service}" = "cashup-dim" ]; then
        port=8002
    elif [ "${service}" = "cashup-eic" ]; then
        port=8003
    elif [ "${service}" = "cashup-cm" ]; then
        port=8004
    fi
    
    # Port forward for health check
    kubectl port-forward -n "${NAMESPACE}" "deployment/${service}" "${port}:${port}" &
    PORT_FORWARD_PID=$!
    
    sleep 5
    
    # Health check
    if curl -f "http://localhost:${port}/health" >/dev/null 2>&1; then
        echo -e "${GREEN}✅ ${service} health check passed${NC}"
    else
        echo -e "${RED}❌ ${service} health check failed${NC}"
        kubectl logs -n "${NAMESPACE}" "deployment/${service}" --tail=20
    fi
    
    # Kill port forward
    kill $PORT_FORWARD_PID 2>/dev/null || true
done

# Run load tests
echo -e "${YELLOW}🔥 Running load tests...${NC}"

cd load-testing
pip install -r requirements.txt

# Run a quick load test
locust -f locustfile.py --headless \
    --users 20 --spawn-rate 2 --run-time 60s \
    --host "https://api.cashup.yourdomain.com" \
    --html "deployment-load-test-${VERSION}.html"

cd ..

echo -e "${GREEN}✅ Load tests completed${NC}"

# Final deployment summary
echo ""
echo -e "${GREEN}🎉 CashUp Agent Production Deployment Complete!${NC}"
echo ""
echo -e "${BLUE}📊 Deployment Summary:${NC}"
echo -e "Environment: ${ENVIRONMENT}"
echo -e "Version: ${VERSION}"
echo -e "Namespace: ${NAMESPACE}"
echo ""
echo -e "${BLUE}🔗 Access URLs:${NC}"
echo -e "API: https://api.cashup.yourdomain.com"
echo -e "Grafana: https://grafana.cashup.yourdomain.com (admin/${GRAFANA_ADMIN_PASSWORD})"
echo -e "Prometheus: https://prometheus.cashup.yourdomain.com"
echo ""
echo -e "${BLUE}📈 Monitoring:${NC}"
echo -e "kubectl get pods -n ${NAMESPACE}"
echo -e "kubectl logs -f -n ${NAMESPACE} deployment/cashup-dim"
echo ""
echo -e "${YELLOW}⚠️  Remember to:${NC}"
echo -e "1. Update DNS records to point to the LoadBalancer IP"
echo -e "2. Configure SSL certificates"
echo -e "3. Set up backup schedules"
echo -e "4. Configure alerting rules"
echo ""
echo -e "${GREEN}✨ Happy ML processing! 🤖${NC}"