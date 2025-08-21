#!/bin/bash

# Monitor current Terraform deployment
# Usage: ./monitor-deployment.sh

PID=$(ps aux | grep "terraform apply" | grep -v grep | awk '{print $2}' | head -1)

if [ -n "$PID" ]; then
    echo "🔍 Found running terraform deployment (PID: $PID)"
    echo ""
    echo "📊 Process status:"
    ps -p $PID -o pid,ppid,pgid,time,command
    echo ""
    echo "💾 Memory usage:"
    ps -p $PID -o pid,rss,vsz,pmem
    echo ""
    echo "⏰ Deployment has been running for:"
    ps -p $PID -o etime | tail -1
    echo ""
    echo "🎯 To monitor real-time:"
    echo "   watch 'ps -p $PID -o pid,etime,command'"
    echo ""
    echo "🛑 To stop deployment:"
    echo "   kill $PID"
    echo ""
    echo "💡 Terraform state:"
    terraform state list 2>/dev/null | wc -l | xargs printf "   %s resources created so far\n"
else
    echo "❌ No terraform deployment currently running"
    echo ""
    echo "🚀 Start new deployment with:"
    echo "   ./deploy-background.sh"
fi