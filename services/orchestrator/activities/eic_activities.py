from temporalio import activity
import httpx
import os
from typing import Dict, List, Any
import asyncio

@activity.defn
async def fetch_invoice_details(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Fetch invoice details from ERP systems via EIC service
    """
    invoice_ids = data.get("invoice_ids", [])
    transaction_id = data.get("transaction_id")
    
    activity.logger.info(f"Fetching details for {len(invoice_ids)} invoices (transaction: {transaction_id})")
    
    eic_base_url = os.getenv('EIC_BASE_URL', 'http://eic:8003')
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                f"{eic_base_url}/api/v1/invoices/fetch",
                json={
                    "invoice_ids": invoice_ids,
                    "transaction_id": transaction_id,
                    "include_details": True,
                    "include_history": False
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                invoices = result.get("invoices", [])
                
                activity.logger.info(f"Fetched details for {len(invoices)} invoices")
                
                # Send heartbeat with progress
                activity.heartbeat(f"Fetched {len(invoices)}/{len(invoice_ids)} invoice details")
                
                return invoices
            
            else:
                activity.logger.error(f"EIC service returned status {response.status_code}: {response.text}")
                raise Exception(f"EIC service failed with status {response.status_code}")
                
        except httpx.TimeoutException:
            activity.logger.error("EIC service request timed out")
            raise Exception("EIC service timeout")
        
        except Exception as e:
            activity.logger.error(f"Error calling EIC service: {str(e)}")
            raise


@activity.defn
async def update_erp_systems(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update ERP systems with cash application results
    """
    matching_result = data.get("matching_result", {})
    transaction = data.get("transaction", {})
    invoices = data.get("invoices", [])
    
    activity.logger.info(f"Updating ERP systems for transaction: {transaction.get('id')}")
    
    eic_base_url = os.getenv('EIC_BASE_URL', 'http://eic:8003')
    
    async with httpx.AsyncClient(timeout=120.0) as client:  # Longer timeout for ERP updates
        try:
            # Prepare update payload
            update_payload = {
                "transaction_id": transaction.get("id"),
                "client_id": transaction.get("client_id"),
                "matching_result": matching_result,
                "payment_amount": transaction.get("amount"),
                "payment_reference": transaction.get("reference"),
                "matched_invoices": matching_result.get("matched_invoices", []),
                "timestamp": transaction.get("timestamp")
            }
            
            response = await client.post(
                f"{eic_base_url}/api/v1/erp/update-cash-application",
                json=update_payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                
                activity.logger.info(f"ERP update successful: {result.get('updated_systems', [])}")
                
                # Send heartbeat with results
                activity.heartbeat(f"Updated {len(result.get('updated_systems', []))} ERP systems")
                
                return result
            
            else:
                activity.logger.error(f"ERP update failed: {response.status_code} - {response.text}")
                raise Exception(f"ERP update failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error updating ERP systems: {str(e)}")
            raise


@activity.defn
async def sync_customer_data(customer_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sync customer data across ERP systems
    """
    activity.logger.info(f"Syncing customer data: {customer_info.get('customer_id')}")
    
    eic_base_url = os.getenv('EIC_BASE_URL', 'http://eic:8003')
    
    async with httpx.AsyncClient(timeout=90.0) as client:
        try:
            response = await client.post(
                f"{eic_base_url}/api/v1/customers/sync",
                json=customer_info,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                sync_result = response.json()
                
                activity.logger.info(f"Customer sync completed: {sync_result.get('synced_systems', [])}")
                return sync_result
            
            else:
                activity.logger.error(f"Customer sync failed: {response.status_code}")
                raise Exception(f"Customer sync failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error syncing customer data: {str(e)}")
            raise


@activity.defn
async def update_credit_limits(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update customer credit limits in ERP systems
    """
    customer = data.get("customer", {})
    assessment = data.get("assessment", {})
    
    activity.logger.info(f"Updating credit limits for customer: {customer.get('id')}")
    
    eic_base_url = os.getenv('EIC_BASE_URL', 'http://eic:8003')
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            update_payload = {
                "customer_id": customer.get("id"),
                "new_credit_limit": assessment.get("recommended_limit"),
                "risk_score": assessment.get("risk_score"),
                "assessment_date": assessment.get("assessment_date"),
                "reason": assessment.get("reason"),
                "approver": "temporal_workflow"
            }
            
            response = await client.post(
                f"{eic_base_url}/api/v1/customers/update-credit-limit",
                json=update_payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                update_result = response.json()
                
                activity.logger.info(f"Credit limit updated: {update_result.get('new_limit')}")
                return update_result
            
            else:
                activity.logger.error(f"Credit limit update failed: {response.status_code}")
                raise Exception(f"Credit limit update failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error updating credit limits: {str(e)}")
            raise


@activity.defn
async def fetch_customer_payment_history(customer_id: str) -> Dict[str, Any]:
    """
    Fetch customer payment history from ERP systems
    """
    activity.logger.info(f"Fetching payment history for customer: {customer_id}")
    
    eic_base_url = os.getenv('EIC_BASE_URL', 'http://eic:8003')
    
    async with httpx.AsyncClient(timeout=45.0) as client:
        try:
            response = await client.get(
                f"{eic_base_url}/api/v1/customers/{customer_id}/payment-history",
                params={
                    "months": 12,
                    "include_disputes": True,
                    "include_adjustments": True
                },
                headers={
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                payment_history = response.json()
                
                activity.logger.info(f"Fetched {len(payment_history.get('payments', []))} payment records")
                return payment_history
            
            else:
                activity.logger.error(f"Payment history fetch failed: {response.status_code}")
                raise Exception(f"Payment history fetch failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error fetching payment history: {str(e)}")
            raise


@activity.defn
async def reconcile_accounts(reconciliation_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reconcile accounts across ERP systems
    """
    activity.logger.info(f"Starting account reconciliation: {reconciliation_data.get('reconciliation_id')}")
    
    eic_base_url = os.getenv('EIC_BASE_URL', 'http://eic:8003')
    
    async with httpx.AsyncClient(timeout=180.0) as client:  # Long timeout for reconciliation
        try:
            response = await client.post(
                f"{eic_base_url}/api/v1/reconciliation/run",
                json=reconciliation_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                reconciliation_result = response.json()
                
                # Send periodic heartbeats for long-running reconciliation
                activity.heartbeat(f"Reconciliation progress: {reconciliation_result.get('progress', 0)}%")
                
                activity.logger.info(f"Reconciliation completed: {reconciliation_result.get('status')}")
                return reconciliation_result
            
            else:
                activity.logger.error(f"Account reconciliation failed: {response.status_code}")
                raise Exception(f"Account reconciliation failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error during account reconciliation: {str(e)}")
            raise