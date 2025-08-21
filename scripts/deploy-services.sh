#!/bin/bash

# Deploy CashUp Agent Services to Azure
# Usage: ./deploy-services.sh

set -e

echo "🚀 CashUp Agent - Service Deployment"
echo "======================================"

# Check if terraform deployment is complete
echo "🔍 Checking infrastructure status..."
RESOURCE_COUNT=$(terraform state list 2>/dev/null | wc -l | xargs)
echo "📊 $RESOURCE_COUNT resources deployed"

if [ "$RESOURCE_COUNT" -lt 40 ]; then
    echo "⚠️  Infrastructure deployment still in progress"
    echo "💡 Wait for ~40+ resources to complete before deploying services"
    echo ""
    echo "🔍 Monitor with: ./terraform/monitor-deployment.sh"
    exit 1
fi

# Get deployment outputs
echo "📋 Getting deployment information..."
ACR_NAME=$(terraform output -raw container_registry_name 2>/dev/null || echo "")
RESOURCE_GROUP=$(terraform output -raw resource_group_name 2>/dev/null || echo "rg-cashappagent-demo")

if [ -z "$ACR_NAME" ]; then
    echo "❌ Container registry name not available yet"
    echo "💡 Infrastructure may still be deploying"
    exit 1
fi

echo "🏗️  Container Registry: $ACR_NAME"
echo "📦 Resource Group: $RESOURCE_GROUP"

# Login to Azure Container Registry
echo ""
echo "🔐 Logging into Azure Container Registry..."
az acr login --name "$ACR_NAME"

# Build and push Docker images
echo ""
echo "🐳 Building and pushing Docker images..."

# Build DIM service
echo "📦 Building DIM service..."
docker build -t "$ACR_NAME.azurecr.io/cashappagent/dim:latest" -f services/dim/Dockerfile .
docker push "$ACR_NAME.azurecr.io/cashappagent/dim:latest"

# Build EIC service  
echo "📦 Building EIC service..."
docker build -t "$ACR_NAME.azurecr.io/cashappagent/eic:latest" -f services/eic/Dockerfile .
docker push "$ACR_NAME.azurecr.io/cashappagent/eic:latest"

# Build CM service
echo "📦 Building CM service..."
docker build -t "$ACR_NAME.azurecr.io/cashappagent/cm:latest" -f services/cm/Dockerfile .
docker push "$ACR_NAME.azurecr.io/cashappagent/cm:latest"

# Deploy to AKS (DIM service)
echo ""
echo "☸️  Deploying DIM service to AKS..."
AKS_NAME=$(terraform output -raw aks_cluster_name 2>/dev/null)
az aks get-credentials --resource-group "$RESOURCE_GROUP" --name "$AKS_NAME" --overwrite-existing

# Create Kubernetes deployment manifests
cat > dim-deployment.yaml << EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dim-service
  labels:
    app: dim-service
spec:
  replicas: 2
  selector:
    matchLabels:
      app: dim-service
  template:
    metadata:
      labels:
        app: dim-service
    spec:
      containers:
      - name: dim
        image: $ACR_NAME.azurecr.io/cashappagent/dim:latest
        ports:
        - containerPort: 8002
        env:
        - name: SERVICE_NAME
          value: "dim"
        - name: ENVIRONMENT
          value: "demo"
        resources:
          requests:
            memory: "1Gi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
---
apiVersion: v1
kind: Service
metadata:
  name: dim-service
spec:
  selector:
    app: dim-service
  ports:
  - port: 80
    targetPort: 8002
  type: LoadBalancer
EOF

kubectl apply -f dim-deployment.yaml

# Update App Service images
echo ""
echo "🌐 Updating App Service container images..."

CLE_APP_NAME="app-cashappagent-cle-demo"
EIC_APP_NAME="app-cashappagent-eic-demo" 
CM_APP_NAME="app-cashappagent-cm-demo"

az webapp config container set \
  --name "$CLE_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --docker-custom-image-name "$ACR_NAME.azurecr.io/cashappagent/cle:latest"

az webapp config container set \
  --name "$EIC_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --docker-custom-image-name "$ACR_NAME.azurecr.io/cashappagent/eic:latest"

az webapp config container set \
  --name "$CM_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --docker-custom-image-name "$ACR_NAME.azurecr.io/cashappagent/cm:latest"

# Restart App Services
echo ""
echo "🔄 Restarting App Services..."
az webapp restart --name "$CLE_APP_NAME" --resource-group "$RESOURCE_GROUP"
az webapp restart --name "$EIC_APP_NAME" --resource-group "$RESOURCE_GROUP"
az webapp restart --name "$CM_APP_NAME" --resource-group "$RESOURCE_GROUP"

echo ""
echo "✅ Service deployment complete!"
echo ""
echo "🌐 Service URLs:"
echo "   CLE API: https://$CLE_APP_NAME.azurewebsites.net"
echo "   EIC API: https://$EIC_APP_NAME.azurewebsites.net" 
echo "   CM API:  https://$CM_APP_NAME.azurewebsites.net"
echo ""
echo "☸️  DIM Service:"
echo "   kubectl get svc dim-service"
echo "   kubectl get pods -l app=dim-service"
echo ""
echo "🎯 Next steps:"
echo "   1. Test health endpoints: curl https://$CLE_APP_NAME.azurewebsites.net/health"
echo "   2. Run end-to-end tests: ./test-production-tiers.py"
echo "   3. Set up monitoring dashboard"