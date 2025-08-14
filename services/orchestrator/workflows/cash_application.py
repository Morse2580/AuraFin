from datetime import timedelta
from temporalio import workflow, activity
from temporalio.common import RetryPolicy
from typing import Dict, List, Any
import asyncio

@workflow.defn
class CashApplicationWorkflow:
    """
    Temporal workflow for cash application processing.
    Handles the complete end-to-end transaction flow with automatic retries,
    state persistence, and failure recovery.
    """
    
    @workflow.run
    async def run(self, transaction: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main workflow execution - orchestrates the complete cash application process
        """
        workflow.logger.info(f"Starting cash application workflow for transaction: {transaction.get('id')}")
        
        try:
            # Step 1: Extract invoice IDs from document
            invoice_ids = await workflow.execute_activity(
                extract_invoice_ids,
                transaction,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(minutes=1),
                    backoff_coefficient=2.0,
                    maximum_attempts=3
                )
            )
            
            if not invoice_ids:
                workflow.logger.warning("No invoice IDs extracted, routing for manual review")
                await workflow.execute_activity(
                    route_for_manual_review,
                    {"transaction": transaction, "reason": "no_invoice_ids"},
                    start_to_close_timeout=timedelta(minutes=2)
                )
                return {"status": "manual_review", "reason": "no_invoice_ids"}
            
            # Step 2: Fetch invoice details from ERP
            invoices = await workflow.execute_activity(
                fetch_invoice_details,
                {"invoice_ids": invoice_ids, "transaction_id": transaction.get('id')},
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=2),
                    maximum_interval=timedelta(minutes=2),
                    backoff_coefficient=2.0,
                    maximum_attempts=5
                )
            )
            
            # Step 3: Match payment to invoices using CLE
            matching_result = await workflow.execute_activity(
                match_payment_to_invoices,
                {
                    "transaction": transaction,
                    "invoices": invoices,
                    "invoice_ids": invoice_ids
                },
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(maximum_attempts=2)
            )
            
            # Step 4: Update ERP systems with matched results
            if matching_result.get("status") == "matched":
                erp_update_result = await workflow.execute_activity(
                    update_erp_systems,
                    {
                        "matching_result": matching_result,
                        "transaction": transaction,
                        "invoices": invoices
                    },
                    start_to_close_timeout=timedelta(minutes=15),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=5),
                        maximum_interval=timedelta(minutes=3),
                        maximum_attempts=3
                    )
                )
                
                # Step 5: Send notifications
                await workflow.execute_activity(
                    send_completion_notifications,
                    {
                        "transaction": transaction,
                        "matching_result": matching_result,
                        "erp_result": erp_update_result
                    },
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=3)
                )
                
                workflow.logger.info(f"Cash application completed successfully for transaction: {transaction.get('id')}")
                return {
                    "status": "completed",
                    "matching_result": matching_result,
                    "erp_result": erp_update_result,
                    "processing_time": workflow.now().isoformat()
                }
            
            else:
                # Route for manual review if matching failed
                await workflow.execute_activity(
                    route_for_manual_review,
                    {
                        "transaction": transaction,
                        "reason": "matching_failed",
                        "details": matching_result
                    },
                    start_to_close_timeout=timedelta(minutes=2)
                )
                
                return {
                    "status": "manual_review",
                    "reason": "matching_failed",
                    "details": matching_result
                }
                
        except Exception as e:
            workflow.logger.error(f"Workflow failed for transaction {transaction.get('id')}: {str(e)}")
            
            # Route to manual review on any unhandled errors
            await workflow.execute_activity(
                route_for_manual_review,
                {
                    "transaction": transaction,
                    "reason": "workflow_error",
                    "error": str(e)
                },
                start_to_close_timeout=timedelta(minutes=2)
            )
            
            return {
                "status": "failed",
                "error": str(e),
                "routed_for_manual_review": True
            }


@workflow.defn  
class CollectionsWorkflow:
    """
    Workflow for collections and dunning processes
    """
    
    @workflow.run
    async def run(self, overdue_invoices: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Execute collections workflow for overdue invoices"""
        
        workflow.logger.info(f"Starting collections workflow for {len(overdue_invoices)} overdue invoices")
        
        results = []
        
        for invoice in overdue_invoices:
            # Send collection notice
            notice_result = await workflow.execute_activity(
                send_collection_notice,
                invoice,
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(maximum_attempts=3)
            )
            
            results.append({
                "invoice_id": invoice.get("id"),
                "notice_sent": notice_result.get("success", False),
                "next_action": notice_result.get("next_action")
            })
            
            # Wait before processing next invoice (rate limiting)
            await asyncio.sleep(1)
        
        return {
            "status": "completed",
            "processed_count": len(overdue_invoices),
            "results": results
        }


@workflow.defn
class CreditManagementWorkflow:
    """
    Workflow for credit management and risk assessment
    """
    
    @workflow.run
    async def run(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute credit management workflow"""
        
        # Assess credit risk
        risk_assessment = await workflow.execute_activity(
            assess_credit_risk,
            customer_data,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2)
        )
        
        # Update credit limits if needed
        if risk_assessment.get("update_required"):
            credit_update = await workflow.execute_activity(
                update_credit_limits,
                {
                    "customer": customer_data,
                    "assessment": risk_assessment
                },
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=3)
            )
            
            return {
                "status": "completed",
                "risk_assessment": risk_assessment,
                "credit_update": credit_update
            }
        
        return {
            "status": "no_action_required",
            "risk_assessment": risk_assessment
        }


# Activity definitions will be in separate files
@activity.defn
async def extract_invoice_ids(transaction: Dict[str, Any]) -> List[str]:
    """Activity placeholder - implemented in activities/dim_activities.py"""
    pass

@activity.defn  
async def fetch_invoice_details(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Activity placeholder - implemented in activities/eic_activities.py"""
    pass

@activity.defn
async def match_payment_to_invoices(data: Dict[str, Any]) -> Dict[str, Any]:
    """Activity placeholder - implemented in activities/cle_activities.py"""
    pass

@activity.defn
async def update_erp_systems(data: Dict[str, Any]) -> Dict[str, Any]:
    """Activity placeholder - implemented in activities/eic_activities.py"""
    pass

@activity.defn
async def send_completion_notifications(data: Dict[str, Any]) -> Dict[str, Any]:
    """Activity placeholder - implemented in activities/cm_activities.py"""
    pass

@activity.defn
async def route_for_manual_review(data: Dict[str, Any]) -> Dict[str, Any]:
    """Activity placeholder - implemented in activities/cm_activities.py"""
    pass

@activity.defn
async def send_collection_notice(invoice: Dict[str, Any]) -> Dict[str, Any]:
    """Activity placeholder - implemented in activities/cm_activities.py"""
    pass

@activity.defn
async def assess_credit_risk(customer: Dict[str, Any]) -> Dict[str, Any]:
    """Activity placeholder - implemented in activities/cm_activities.py"""
    pass

@activity.defn
async def update_credit_limits(data: Dict[str, Any]) -> Dict[str, Any]:
    """Activity placeholder - implemented in activities/eic_activities.py"""
    pass