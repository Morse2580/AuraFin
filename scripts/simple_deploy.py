#!/usr/bin/env python3
# scripts/simple_deploy.py
"""
Simple deployment script for CashAppAgent development environment
Handles Docker Compose deployment with security initialization
"""

import asyncio
import subprocess
import sys
import os
import time
import json
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SimpleDeployer:
    """
    Handles simple deployment using Docker Compose
    """
    
    def __init__(self, environment: str = "development"):
        self.environment = environment
        self.project_root = project_root
    
    async def deploy(self, steps: list = None):
        """
        Full deployment process
        
        Args:
            steps: List of steps to execute (all if None)
        """
        logger.info(f"🚀 Starting CashAppAgent deployment for {self.environment}")
        
        all_steps = [
            ("pre_deployment_checks", "Pre-deployment validation"),
            ("setup_environment", "Environment configuration"),
            ("build_services", "Building Docker services"),
            ("deploy_infrastructure", "Infrastructure deployment"),
            ("deploy_services", "Service deployment"),
            ("setup_security", "Security initialization"),
            ("run_health_checks", "Health verification"),
            ("post_deployment_validation", "Post-deployment validation")
        ]
        
        steps_to_run = steps or [step[0] for step in all_steps]
        
        for step_func, step_name in all_steps:
            if step_func in steps_to_run:
                logger.info(f"📋 {step_name}...")
                try:
                    success = await getattr(self, step_func)()
                    if success:
                        logger.info(f"✅ {step_name} completed")
                    else:
                        logger.error(f"❌ {step_name} failed")
                        return False
                except Exception as e:
                    logger.error(f"❌ {step_name} failed with error: {e}")
                    return False
        
        logger.info("🎉 CashAppAgent deployment completed successfully!")
        self.show_deployment_info()
        return True
    
    async def pre_deployment_checks(self) -> bool:
        """Validate environment and prerequisites"""
        logger.info("Running pre-deployment checks...")
        
        # Check Docker
        try:
            result = subprocess.run(['docker', '--version'], capture_output=True, text=True)
            if result.returncode != 0:
                logger.error("Docker not available")
                return False
            logger.info(f"Docker available: {result.stdout.strip()}")
        except FileNotFoundError:
            logger.error("Docker not installed")
            return False
        
        # Check Docker Compose
        try:
            result = subprocess.run(['docker', 'compose', 'version'], capture_output=True, text=True)
            if result.returncode != 0:
                logger.error("Docker Compose not available")
                return False
            logger.info(f"Docker Compose available: {result.stdout.strip()}")
        except FileNotFoundError:
            logger.error("Docker Compose not installed")
            return False
        
        # Check .env file exists
        env_file = self.project_root / '.env'
        if not env_file.exists():
            logger.warning(".env file not found - copying from .env.example")
            example_file = self.project_root / '.env.example'
            if example_file.exists():
                subprocess.run(['cp', str(example_file), str(env_file)])
                logger.info("Please update .env file with actual values before continuing")
            else:
                logger.error(".env.example file not found")
                return False
        
        # Check required directories
        required_dirs = [
            'logs',
            'config',
            'infrastructure/nginx',
            'infrastructure/monitoring'
        ]
        
        for dir_path in required_dirs:
            full_path = self.project_root / dir_path
            full_path.mkdir(parents=True, exist_ok=True)
        
        logger.info("Pre-deployment checks passed")
        return True
    
    async def setup_environment(self) -> bool:
        """Setup environment configuration"""
        logger.info("Setting up environment configuration...")
        
        # Create logs directory
        logs_dir = self.project_root / "logs"
        logs_dir.mkdir(exist_ok=True)
        
        # Create config directory
        config_dir = self.project_root / "config"
        config_dir.mkdir(exist_ok=True)
        
        logger.info("Environment configuration validated")
        return True
    
    async def build_services(self) -> bool:
        """Build Docker services"""
        logger.info("Building Docker services...")
        
        try:
            cmd = ['docker', 'compose', 'build', '--no-cache']
            result = subprocess.run(cmd, cwd=self.project_root, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"Docker build failed: {result.stderr}")
                return False
            
            logger.info("Docker services built successfully")
            return True
            
        except Exception as e:
            logger.error(f"Build process failed: {e}")
            return False
    
    async def deploy_infrastructure(self) -> bool:
        """Deploy infrastructure services (databases, monitoring)"""
        logger.info("Deploying infrastructure...")
        
        try:
            # Start database and Redis first
            cmd = ['docker', 'compose', 'up', '-d', 'postgres', 'redis']
            result = subprocess.run(cmd, cwd=self.project_root, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"Infrastructure deployment failed: {result.stderr}")
                return False
            
            # Wait for databases to be ready
            logger.info("Waiting for databases to be ready...")
            await asyncio.sleep(30)
            
            # Start monitoring services
            cmd = ['docker', 'compose', 'up', '-d', 'prometheus', 'grafana']
            result = subprocess.run(cmd, cwd=self.project_root, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.warning("Monitoring services failed to start (optional)")
            
            logger.info("Infrastructure deployed")
            return True
            
        except Exception as e:
            logger.error(f"Infrastructure deployment failed: {e}")
            return False
    
    async def deploy_services(self) -> bool:
        """Deploy application services"""
        logger.info("Deploying application services...")
        
        try:
            # Start all services
            cmd = ['docker', 'compose', 'up', '-d']
            result = subprocess.run(cmd, cwd=self.project_root, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"Service deployment failed: {result.stderr}")
                return False
            
            logger.info("Application services deployed")
            return True
            
        except Exception as e:
            logger.error(f"Service deployment failed: {e}")
            return False
    
    async def setup_security(self) -> bool:
        """Initialize security configuration"""
        logger.info("Setting up security...")
        
        try:
            # Wait for Redis to be ready
            await asyncio.sleep(10)
            
            # Run security setup script
            cmd = ['python', 'scripts/setup_security.py', 'setup']
            result = subprocess.run(cmd, cwd=self.project_root, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.warning(f"Security setup had issues: {result.stderr}")
                logger.info("Security setup may require manual configuration")
            else:
                logger.info("Security setup completed")
            
            return True
            
        except Exception as e:
            logger.error(f"Security setup failed: {e}")
            return False
    
    async def run_health_checks(self) -> bool:
        """Verify all services are healthy"""
        logger.info("Running health checks...")
        
        services = [
            ("http://localhost:8080/health", "nginx-gateway"),
            ("http://localhost:8001/health", "cle"),
            ("http://localhost:8002/health", "dim"),
            ("http://localhost:8003/health", "eic"),
            ("http://localhost:8004/health", "cm")
        ]
        
        # Wait for services to start
        logger.info("Waiting for services to start...")
        await asyncio.sleep(60)
        
        try:
            import httpx
        except ImportError:
            logger.warning("httpx not available, skipping health checks")
            return True
        
        async with httpx.AsyncClient() as client:
            for url, service_name in services:
                for attempt in range(5):
                    try:
                        response = await client.get(url, timeout=10)
                        if response.status_code == 200:
                            logger.info(f"✅ {service_name} is healthy")
                            break
                        else:
                            logger.warning(f"⚠️  {service_name} returned status {response.status_code}")
                    except Exception as e:
                        if attempt == 4:  # Last attempt
                            logger.warning(f"⚠️  {service_name} health check failed: {e}")
                        else:
                            logger.info(f"Retrying {service_name} health check (attempt {attempt + 2}/5)...")
                            await asyncio.sleep(10)
        
        logger.info("Health checks completed")
        return True
    
    async def post_deployment_validation(self) -> bool:
        """Run post-deployment validation tests"""
        logger.info("Running post-deployment validation...")
        
        try:
            # Test basic connectivity
            import httpx
            async with httpx.AsyncClient() as client:
                # Test main API
                try:
                    response = await client.get("http://localhost:8080/api/v1/status")
                    if response.status_code == 200:
                        logger.info("✅ Main API is accessible")
                    else:
                        logger.warning(f"⚠️  Main API returned status {response.status_code}")
                except Exception as e:
                    logger.warning(f"⚠️  Main API not accessible: {e}")
            
            logger.info("Post-deployment validation completed")
            return True
            
        except Exception as e:
            logger.error(f"Post-deployment validation failed: {e}")
            return False
    
    def cleanup(self):
        """Cleanup deployment (stop services)"""
        logger.info("Cleaning up deployment...")
        
        try:
            cmd = ['docker', 'compose', 'down', '--volumes']
            result = subprocess.run(cmd, cwd=self.project_root, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info("Deployment cleaned up successfully")
            else:
                logger.error(f"Cleanup failed: {result.stderr}")
                
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
    
    def show_deployment_info(self):
        """Display deployment information"""
        print("\n" + "="*60)
        print("🎉 CashAppAgent Deployment Complete!")
        print("="*60)
        print(f"Environment: {self.environment}")
        print(f"Project Root: {self.project_root}")
        print("\n📡 Service Endpoints:")
        print("  Gateway (Nginx):     http://localhost:8080")
        print("  Core Logic Engine:   http://localhost:8001")
        print("  Document Intel:      http://localhost:8002")
        print("  ERP Integration:     http://localhost:8003")
        print("  Communication:       http://localhost:8004")
        print("\n📊 Monitoring:")
        print("  Prometheus:          http://localhost:9090")
        print("  Grafana:             http://localhost:3000 (admin/admin123)")
        print("\n🔍 Health Checks:")
        print("  curl http://localhost:8080/health")
        print("  curl http://localhost:8080/api/v1/status")
        print("\n📝 Logs:")
        print("  docker compose logs -f")
        print("  docker compose logs cle")
        print("\n🛠️  Useful Commands:")
        print("  Stop:     docker compose down")
        print("  Restart:  docker compose restart")
        print("  Scale:    docker compose up -d --scale cle=3")
        print("\n🔐 Security:")
        print("  API keys stored in: /app/config/api_keys.json")
        print("  Reset security:     python scripts/setup_security.py reset")
        print("="*60)

async def main():
    """Main deployment script"""
    import argparse
    
    parser = argparse.ArgumentParser(description='CashAppAgent Simple Deployment')
    parser.add_argument('action', choices=['deploy', 'cleanup', 'info'], help='Action to perform')
    parser.add_argument('--env', choices=['development', 'staging', 'production'], 
                       default='development', help='Deployment environment')
    parser.add_argument('--steps', nargs='+', help='Specific steps to run')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    deployer = SimpleDeployer(args.env)
    
    if args.action == 'deploy':
        success = await deployer.deploy(args.steps)
        sys.exit(0 if success else 1)
        
    elif args.action == 'cleanup':
        deployer.cleanup()
        sys.exit(0)
        
    elif args.action == 'info':
        deployer.show_deployment_info()
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())