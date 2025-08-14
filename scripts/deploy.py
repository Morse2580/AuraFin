# scripts/deploy.py

#!/usr/bin/env python3
"""
Complete deployment script for CashAppAgent
Handles infrastructure, application deployment, and verification
"""

import os
import sys
import json
import time
import subprocess
import argparse
from pathlib import Path
from typing import Dict, List, Optional
import requests
import yaml

class CashAppAgentDeployer:
    def __init__(self, environment: str, dry_run: bool = False):
        self.environment = environment
        self.dry_run = dry_run
        self.project_root = Path(__file__).parent.parent
        self.terraform_dir = self.project_root / "terraform"
        self.k8s_dir = self.project_root / "k8s"
        
        # Environment-specific configuration
        self.config = self._load_environment_config()
        
        print(f"🚀 Initializing CashAppAgent deployment for {environment}")
        if dry_run:
            print("🔍 DRY RUN MODE - No actual changes will be made")
    
    def _load_environment_config(self) -> Dict:
        """Load environment-specific configuration"""
        config_file = self.project_root / f"config/{self.environment}.json"
        
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
        
        with open(config_file, 'r') as f:
            config = json.load(f)
        
        # Validate required configuration
        required_keys = ['resource_group', 'location', 'container_registry']
        for key in required_keys:
            if key not in config:
                raise ValueError(f"Missing required configuration key: {key}")
        
        return config
    
    def run_command(self, cmd: List[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
        """Run a command with proper logging"""
        print(f"🔧 Running: {' '.join(cmd)}")
        
        if self.dry_run:
            print("   (skipped in dry run)")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        
        try:
            result = subprocess.run(
                cmd, 
                cwd=cwd or self.project_root,
                capture_output=True,
                text=True,
                check=check
            )
            
            if result.stdout:
                print(f"✅ Output: {result.stdout.strip()}")
            
            return result
            
        except subprocess.CalledProcessError as e:
            print(f"❌ Command failed with exit code {e.returncode}")
            print(f"   stdout: {e.stdout}")
            print(f"   stderr: {e.stderr}")
            raise
    
    def check_prerequisites(self) -> bool:
        """Check that all required tools are installed"""
        print("🔍 Checking prerequisites...")
        
        tools = {
            'az': 'Azure CLI',
            'terraform': 'Terraform',
            'kubectl': 'kubectl',
            'docker': 'Docker',
            'helm': 'Helm'
        }
        
        missing_tools = []
        
        for tool, description in tools.items():
            try:
                self.run_command([tool, '--version'], check=True)
                print(f"✅ {description} is installed")
            except (subprocess.CalledProcessError, FileNotFoundError):
                print(f"❌ {description} is not installed or not in PATH")
                missing_tools.append(tool)
        
        if missing_tools:
            print(f"❌ Missing required tools: {', '.join(missing_tools)}")
            return False
        
        # Check Azure login
        try:
            result = self.run_command(['az', 'account', 'show'], check=True)
            account_info = json.loads(result.stdout)
            print(f"✅ Logged into Azure as: {account_info['user']['name']}")
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            print("❌ Not logged into Azure. Run 'az login' first.")
            return False
        
        return True
    
    def deploy_infrastructure(self) -> Dict:
        """Deploy infrastructure using Terraform"""
        print("🏗️ Deploying infrastructure...")
        
        # Initialize Terraform
        self.run_command([
            'terraform', 'init',
            f'-backend-config=key=cashappagent-{self.environment}.tfstate'
        ], cwd=self.terraform_dir)
        
        # Plan Terraform changes
        tfvars_file = f"environments/{self.environment}.tfvars"
        plan_file = f"tfplan-{self.environment}"
        
        self.run_command([
            'terraform', 'plan',
            f'-var-file={tfvars_file}',
            f'-out={plan_file}'
        ], cwd=self.terraform_dir)
        
        # Apply Terraform changes
        if not self.dry_run:
            print("📋 Applying Terraform plan...")
            self.run_command([
                'terraform', 'apply', 
                '-auto-approve',
                plan_file
            ], cwd=self.terraform_dir)
        
        # Get Terraform outputs
        if not self.dry_run:
            result = self.run_command([
                'terraform', 'output', '-json'
            ], cwd=self.terraform_dir)
            
            outputs = json.loads(result.stdout)
            
            # Extract values from Terraform output format
            infrastructure = {}
            for key, value in outputs.items():
                infrastructure[key] = value['value']
            
            return infrastructure
        else:
            return {}  # Return empty dict for dry run
    
    def build_and_push_images(self, infrastructure: Dict) -> None:
        """Build and push Docker images to Azure Container Registry"""
        print("🐳 Building and pushing Docker images...")
        
        if not infrastructure:
            print("   (skipped in dry run)")
            return
        
        acr_name = infrastructure.get('container_registry_name')
        acr_server = infrastructure.get('container_registry_login_server')
        
        if not acr_name or not acr_server:
            raise ValueError("Missing Container Registry information from infrastructure")
        
        # Login to ACR
        self.run_command(['az', 'acr', 'login', '--name', acr_name])
        
        # Build and push each service
        services = ['cle', 'dim', 'eic', 'cm']
        
        for service in services:
            print(f"🔨 Building {service} service...")
            
            image_tag = f"{acr_server}/cashappagent/{service}:latest"
            
            # Build image
            self.run_command([
                'docker', 'build',
                '-t', image_tag,
                '-f', f'services/{service}/Dockerfile',
                '.'
            ])
            
            # Push image
            self.run_command(['docker', 'push', image_tag])
            
            print(f"✅ {service} image pushed successfully")
    
    def deploy_app_services(self, infrastructure: Dict) -> None:
        """Deploy App Services (CLE, EIC, CM)"""
        print("🌐 Deploying App Services...")
        
        if not infrastructure:
            print("   (skipped in dry run)")
            return
        
        resource_group = infrastructure.get('resource_group_name')
        acr_server = infrastructure.get('container_registry_login_server')
        
        app_services = {
            'cle': f"app-cashappagent-cle-{self.environment}",
            'eic': f"app-cashappagent-eic-{self.environment}",
            'cm': f"app-cashappagent-cm-{self.environment}"
        }
        
        for service, app_name in app_services.items():
            print(f"🚀 Deploying {service} to {app_name}...")
            
            # Update container image
            self.run_command([
                'az', 'webapp', 'config', 'container', 'set',
                '--name', app_name,
                '--resource-group', resource_group,
                '--docker-custom-image-name', f"{acr_server}/cashappagent/{service}:latest"
            ])
            
            # Restart the app
            self.run_command([
                'az', 'webapp', 'restart',
                '--name', app_name,
                '--resource-group', resource_group
            ])
            
            print(f"✅ {service} deployed successfully")
    
    def deploy_aks_services(self, infrastructure: Dict) -> None:
        """Deploy DIM service to AKS"""
        print("☸️ Deploying DIM service to AKS...")
        
        if not infrastructure:
            print("   (skipped in dry run)")
            return
        
        # Get AKS credentials
        resource_group = infrastructure.get('resource_group_name')
        aks_name = infrastructure.get('aks_cluster_name')
        
        self.run_command([
            'az', 'aks', 'get-credentials',
            '--resource-group', resource_group,
            '--name', aks_name,
            '--overwrite-existing'
        ])
        
        # Apply Kubernetes manifests
        manifest_files = [
            'namespace.yaml',
            'configmap.yaml',
            'secret.yaml',
            'pvc.yaml',
            'service-account.yaml',
            'deployment.yaml',
            'service.yaml',
            'hpa.yaml',
            'network-policy.yaml',
            'pod-disruption-budget.yaml',
            'ingress.yaml'
        ]
        
        for manifest in manifest_files:
            manifest_path = self.k8s_dir / manifest
            
            if manifest_path.exists():
                print(f"📋 Applying {manifest}...")
                self.run_command(['kubectl', 'apply', '-f', str(manifest_path)])
            else:
                print(f"⚠️ Warning: {manifest} not found")
        
        # Wait for deployment to be ready
        print("⏳ Waiting for DIM deployment to be ready...")
        self.run_command([
            'kubectl', 'rollout', 'status', 
            'deployment/dim-deployment',
            '--namespace=cashappagent',
            '--timeout=600s'
        ])
        
        print("✅ DIM service deployed successfully")
    
    def run_health_checks(self, infrastructure: Dict) -> bool:
        """Run health checks on all deployed services"""
        print("🔍 Running health checks...")
        
        if not infrastructure:
            print("   (skipped in dry run)")
            return True
        
        app_urls = infrastructure.get('app_service_urls', {})
        
        # Check App Services
        services_to_check = ['cle', 'eic', 'cm']
        
        for service in services_to_check:
            url = app_urls.get(service)
            if not url:
                print(f"❌ No URL found for {service}")
                continue
            
            health_url = f"{url}/health"
            
            try:
                print(f"🔍 Checking {service} at {health_url}...")
                response = requests.get(health_url, timeout=30)
                
                if response.status_code == 200:
                    health_data = response.json()
                    print(f"✅ {service} is healthy: {health_data.get('status', 'unknown')}")
                else:
                    print(f"❌ {service} health check failed: HTTP {response.status_code}")
                    return False
                    
            except requests.RequestException as e:
                print(f"❌ {service} health check failed: {str(e)}")
                return False
        
        # Check AKS service
        try:
            print("🔍 Checking DIM service in AKS...")
            result = self.run_command([
                'kubectl', 'get', 'pods',
                '--namespace=cashappagent',
                '--selector=app=dim',
                '--output=json'
            ])
            
            pods_data = json.loads(result.stdout)
            
            if not pods_data.get('items'):
                print("❌ No DIM pods found")
                return False
            
            ready_pods = 0
            for pod in pods_data['items']:
                status = pod.get('status', {})
                if status.get('phase') == 'Running':
                    ready_pods += 1
            
            if ready_pods > 0:
                print(f"✅ DIM service is healthy: {ready_pods} pods running")
            else:
                print("❌ No DIM pods are running")
                return False
                
        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            print(f"❌ DIM health check failed: {str(e)}")
            return False
        
        return True
    
    def run_smoke_tests(self, infrastructure: Dict) -> bool:
        """Run smoke tests against deployed services"""
        print("🧪 Running smoke tests...")
        
        if not infrastructure:
            print("   (skipped in dry run)")
            return True
        
        smoke_test_script = self.project_root / "tests" / "smoke_tests.py"
        
        if not smoke_test_script.exists():
            print("⚠️ Smoke test script not found, skipping")
            return True
        
        # Set environment variables for smoke tests
        app_urls = infrastructure.get('app_service_urls', {})
        env = os.environ.copy()
        env.update({
            'CLE_URL': app_urls.get('cle', ''),
            'EIC_URL': app_urls.get('eic', ''),
            'CM_URL': app_urls.get('cm', ''),
            'ENVIRONMENT': self.environment
        })
        
        try:
            result = subprocess.run([
                sys.executable, str(smoke_test_script)
            ], env=env, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                print("✅ Smoke tests passed")
                return True
            else:
                print(f"❌ Smoke tests failed:")
                print(f"   stdout: {result.stdout}")
                print(f"   stderr: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("❌ Smoke tests timed out")
            return False
        except Exception as e:
            print(f"❌ Smoke tests failed with error: {str(e)}")
            return False
    
    def full_deployment(self) -> bool:
        """Run full deployment pipeline"""
        print(f"🚀 Starting full deployment to {self.environment}")
        
        try:
            # Step 1: Check prerequisites
            if not self.check_prerequisites():
                return False
            
            # Step 2: Deploy infrastructure
            infrastructure = self.deploy_infrastructure()
            
            # Step 3: Build and push images
            self.build_and_push_images(infrastructure)
            
            # Step 4: Deploy App Services
            self.deploy_app_services(infrastructure)
            
            # Step 5: Deploy AKS services
            self.deploy_aks_services(infrastructure)
            
            # Step 6: Health checks
            if not self.run_health_checks(infrastructure):
                print("❌ Health checks failed")
                return False
            
            # Step 7: Smoke tests
            if not self.run_smoke_tests(infrastructure):
                print("❌ Smoke tests failed")
                return False
            
            print("🎉 Deployment completed successfully!")
            return True
            
        except Exception as e:
            print(f"❌ Deployment failed: {str(e)}")
            return False

def main():
    parser = argparse.ArgumentParser(description="Deploy CashAppAgent to Azure")
    parser.add_argument('environment', choices=['dev', 'staging', 'production'],
                       help='Target environment')
    parser.add_argument('--dry-run', action='store_true',
                       help='Perform a dry run without making changes')
    parser.add_argument('--infrastructure-only', action='store_true',
                       help='Deploy infrastructure only')
    parser.add_argument('--apps-only', action='store_true',
                       help='Deploy applications only (skip infrastructure)')
    
    args = parser.parse_args()
    
    deployer = CashAppAgentDeployer(args.environment, args.dry_run)
    
    try:
        if args.infrastructure_only:
            infrastructure = deployer.deploy_infrastructure()
            print("✅ Infrastructure deployment completed")
            
        elif args.apps_only:
            # Load infrastructure info from terraform state
            infrastructure = {}  # Would need to load from terraform output
            deployer.build_and_push_images(infrastructure)
            deployer.deploy_app_services(infrastructure)
            deployer.deploy_aks_services(infrastructure)
            print("✅ Application deployment completed")
            
        else:
            # Full deployment
            success = deployer.full_deployment()
            sys.exit(0 if success else 1)
            
    except KeyboardInterrupt:
        print("\n❌ Deployment cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Deployment failed: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main()