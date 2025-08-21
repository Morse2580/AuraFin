#!/bin/bash

# Check EABL Demo Deployment Status
# Usage: ./check-deployment-status.sh

set -e

echo "🔍 EABL MVP Demo - Deployment Status"
echo "====================================="

# Check Terraform deployment
echo "1️⃣  Infrastructure Deployment:"
RESOURCE_COUNT=$(terraform state list 2>/dev/null | wc -l | xargs)
EXPECTED_RESOURCES=60  # Approximate expected resource count

echo "   📊 Resources: $RESOURCE_COUNT/$EXPECTED_RESOURCES"

if [ "$RESOURCE_COUNT" -ge 40 ]; then
    echo "   ✅ Core infrastructure ready"
    INFRA_READY=true
else
    echo "   ⏳ Infrastructure still deploying..."
    INFRA_READY=false
fi

# Check if Terraform is still running
TERRAFORM_PID=$(ps aux | grep "terraform apply" | grep -v grep | awk '{print $2}' | head -1)
if [ -n "$TERRAFORM_PID" ]; then
    RUNTIME=$(ps -p $TERRAFORM_PID -o etime | tail -1 | xargs)
    echo "   ⏰ Running for: $RUNTIME (PID: $TERRAFORM_PID)"
else
    echo "   🏁 Infrastructure deployment complete"
fi

echo ""

# Check Azure resources
echo "2️⃣  Azure Resources:"
if command -v az >/dev/null 2>&1; then
    if $INFRA_READY; then
        RG_NAME=$(terraform output -raw resource_group_name 2>/dev/null || echo "rg-cashappagent-demo")
        
        # Check resource group
        if az group show --name "$RG_NAME" >/dev/null 2>&1; then
            echo "   ✅ Resource Group: $RG_NAME"
            
            # Check key resources
            echo "   🔍 Key Resources:"
            az resource list --resource-group "$RG_NAME" --query "[].{Name:name, Type:type, Status:provisioningState}" --output table 2>/dev/null | head -10
        else
            echo "   ❌ Resource Group not found: $RG_NAME"
        fi
    else
        echo "   ⏳ Waiting for infrastructure..."
    fi
else
    echo "   ❌ Azure CLI not available"
fi

echo ""

# Check Docker images
echo "3️⃣  Docker Images:"
SERVICES=("dim" "eic" "cm")
for service in "${SERVICES[@]}"; do
    if docker images | grep -q "cashappagent/$service"; then
        echo "   ✅ $service image built"
    else
        echo "   ⏳ $service image not built"
    fi
done

echo ""

# Next steps recommendation
echo "4️⃣  Next Steps:"
if [ "$RESOURCE_COUNT" -ge 50 ]; then
    echo "   🚀 Ready to deploy services:"
    echo "      ./scripts/deploy-services.sh"
elif [ "$RESOURCE_COUNT" -ge 30 ]; then
    echo "   ⏳ Infrastructure 80% complete, prepare for service deployment"
    echo "   💡 Build Docker images: docker compose build"
else
    echo "   ⏳ Wait for infrastructure deployment to progress further"
    echo "   📊 Monitor: ./terraform/monitor-deployment.sh"
fi

echo ""
echo "5️⃣  Monitoring:"
echo "   📊 Watch resources: watch 'terraform state list 2>/dev/null | wc -l'"
echo "   🔍 Monitor deployment: ./terraform/monitor-deployment.sh"
echo "   ☁️  Check Azure portal: https://portal.azure.com/"

# Check if deployment is complete
if [ "$RESOURCE_COUNT" -ge 50 ] && [ -z "$TERRAFORM_PID" ]; then
    echo ""
    echo "🎉 DEPLOYMENT COMPLETE!"
    echo "   Ready for EABL enterprise demo"
    
    # Show key URLs if available
    if terraform output >/dev/null 2>&1; then
        echo ""
        echo "🌐 Demo URLs:"
        terraform output | grep -E "(frontend|api|dashboard)" || true
    fi
fi