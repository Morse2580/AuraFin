#!/bin/bash

# Background Terraform Deployment Script
# Usage: ./deploy-background.sh

set -e

LOGFILE="deployment-$(date +%Y%m%d-%H%M%S).log"
PIDFILE="terraform.pid"

echo "🚀 Starting Azure deployment in background..."
echo "📝 Log file: $LOGFILE"
echo "🔧 PID file: $PIDFILE"

# Run terraform in background with logging
nohup terraform apply -var-file="terraform.tfvars.demo" -auto-approve > "$LOGFILE" 2>&1 &

# Save process ID
echo $! > "$PIDFILE"

echo "✅ Deployment started with PID: $(cat $PIDFILE)"
echo ""
echo "📊 Monitor deployment with:"
echo "   tail -f $LOGFILE"
echo ""
echo "🔍 Check status with:"
echo "   ps -p \$(cat $PIDFILE)"
echo ""
echo "🛑 Stop deployment with:"
echo "   kill \$(cat $PIDFILE)"
echo ""
echo "🎯 Wait for completion:"
echo "   wait \$(cat $PIDFILE)"