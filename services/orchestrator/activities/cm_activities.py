from temporalio import activity
import httpx
import os
from typing import Dict, List, Any

@activity.defn
async def send_completion_notifications(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send completion notifications for successful cash application
    """
    transaction = data.get("transaction", {})
    matching_result = data.get("matching_result", {})
    erp_result = data.get("erp_result", {})
    
    activity.logger.info(f"Sending completion notifications for transaction: {transaction.get('id')}")
    
    cm_base_url = os.getenv('CM_BASE_URL', 'http://cm:8004')
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            notification_payload = {
                "transaction_id": transaction.get("id"),
                "client_id": transaction.get("client_id"),
                "notification_type": "cash_application_completed",
                "recipients": {
                    "primary": transaction.get("notification_email"),
                    "cc": transaction.get("cc_emails", []),
                    "internal": ["cashapp-team@company.com"]
                },
                "data": {
                    "amount": transaction.get("amount"),
                    "reference": transaction.get("reference"),
                    "matched_invoices": matching_result.get("matched_invoices", []),
                    "confidence": matching_result.get("confidence"),
                    "processing_time": data.get("processing_time"),
                    "erp_systems_updated": erp_result.get("updated_systems", [])
                },
                "channels": ["email", "slack", "webhook"]
            }
            
            response = await client.post(
                f"{cm_base_url}/api/v1/notifications/send",
                json=notification_payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                notification_result = response.json()
                
                activity.logger.info(f"Notifications sent: {len(notification_result.get('sent_notifications', []))} successful")
                
                # Send heartbeat with notification results
                activity.heartbeat(f"Sent {len(notification_result.get('sent_notifications', []))} notifications")
                
                return notification_result
            
            else:
                activity.logger.error(f"Notification service returned status {response.status_code}: {response.text}")
                # Don't fail the workflow for notification failures
                return {"status": "failed", "error": f"Notification failed with status {response.status_code}"}
                
        except Exception as e:
            activity.logger.error(f"Error sending notifications: {str(e)}")
            # Don't fail the workflow for notification failures
            return {"status": "failed", "error": str(e)}


@activity.defn
async def route_for_manual_review(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Route transaction for manual review with appropriate context
    """
    transaction = data.get("transaction", {})
    reason = data.get("reason", "unknown")
    details = data.get("details", {})
    
    activity.logger.info(f"Routing transaction {transaction.get('id')} for manual review: {reason}")
    
    cm_base_url = os.getenv('CM_BASE_URL', 'http://cm:8004')
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            review_payload = {
                "transaction_id": transaction.get("id"),
                "client_id": transaction.get("client_id"),
                "review_reason": reason,
                "priority": "high" if reason == "workflow_error" else "medium",
                "context": {
                    "transaction": transaction,
                    "failure_details": details,
                    "routing_timestamp": data.get("timestamp"),
                    "assigned_reviewer": None  # Will be auto-assigned
                },
                "notification_required": True,
                "escalation_hours": 24
            }
            
            response = await client.post(
                f"{cm_base_url}/api/v1/manual-review/create",
                json=review_payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                review_result = response.json()
                
                activity.logger.info(f"Manual review created: {review_result.get('review_id')} - Assigned to: {review_result.get('assigned_to')}")
                return review_result
            
            else:
                activity.logger.error(f"Manual review routing failed: {response.status_code}")
                raise Exception(f"Manual review routing failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error routing for manual review: {str(e)}")
            raise


@activity.defn
async def send_collection_notice(invoice: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send collection notice for overdue invoice
    """
    activity.logger.info(f"Sending collection notice for invoice: {invoice.get('id')}")
    
    cm_base_url = os.getenv('CM_BASE_URL', 'http://cm:8004')
    
    async with httpx.AsyncClient(timeout=45.0) as client:
        try:
            collection_payload = {
                "invoice_id": invoice.get("id"),
                "customer_id": invoice.get("customer_id"),
                "amount_due": invoice.get("amount_due"),
                "days_overdue": invoice.get("days_overdue"),
                "collection_stage": invoice.get("collection_stage", 1),
                "notice_type": "standard",
                "urgency": "high" if invoice.get("days_overdue", 0) > 60 else "medium",
                "include_payment_options": True,
                "escalation_required": invoice.get("days_overdue", 0) > 90
            }
            
            response = await client.post(
                f"{cm_base_url}/api/v1/collections/send-notice",
                json=collection_payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                notice_result = response.json()
                
                activity.logger.info(f"Collection notice sent: {notice_result.get('notice_id')} - Channel: {notice_result.get('channel')}")
                return notice_result
            
            else:
                activity.logger.error(f"Collection notice failed: {response.status_code}")
                raise Exception(f"Collection notice failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error sending collection notice: {str(e)}")
            raise


@activity.defn
async def assess_credit_risk(customer: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assess customer credit risk using CM service analytics
    """
    activity.logger.info(f"Assessing credit risk for customer: {customer.get('id')}")
    
    cm_base_url = os.getenv('CM_BASE_URL', 'http://cm:8004')
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            risk_payload = {
                "customer_id": customer.get("id"),
                "assessment_type": "comprehensive",
                "include_external_data": True,
                "include_payment_history": True,
                "include_industry_benchmarks": True,
                "risk_factors": {
                    "payment_history_weight": 0.4,
                    "credit_utilization_weight": 0.3,
                    "industry_trends_weight": 0.2,
                    "financial_stability_weight": 0.1
                }
            }
            
            response = await client.post(
                f"{cm_base_url}/api/v1/credit/assess-risk",
                json=risk_payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                risk_result = response.json()
                
                activity.logger.info(f"Credit risk assessed: {risk_result.get('risk_score')}/100 - Grade: {risk_result.get('risk_grade')}")
                
                # Send heartbeat with assessment progress
                activity.heartbeat(f"Risk assessment completed: {risk_result.get('risk_grade')} grade")
                
                return risk_result
            
            else:
                activity.logger.error(f"Credit risk assessment failed: {response.status_code}")
                raise Exception(f"Credit risk assessment failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error assessing credit risk: {str(e)}")
            raise


@activity.defn
async def send_payment_reminder(reminder_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send automated payment reminder to customers
    """
    activity.logger.info(f"Sending payment reminder: {reminder_data.get('reminder_id')}")
    
    cm_base_url = os.getenv('CM_BASE_URL', 'http://cm:8004')
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{cm_base_url}/api/v1/reminders/send",
                json=reminder_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                reminder_result = response.json()
                
                activity.logger.info(f"Payment reminder sent: {reminder_result.get('delivery_status')}")
                return reminder_result
            
            else:
                activity.logger.error(f"Payment reminder failed: {response.status_code}")
                # Don't fail workflow for reminder failures
                return {"status": "failed", "error": f"Reminder failed with status {response.status_code}"}
                
        except Exception as e:
            activity.logger.error(f"Error sending payment reminder: {str(e)}")
            return {"status": "failed", "error": str(e)}


@activity.defn
async def generate_customer_statement(statement_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate and send customer account statement
    """
    activity.logger.info(f"Generating customer statement: {statement_data.get('customer_id')}")
    
    cm_base_url = os.getenv('CM_BASE_URL', 'http://cm:8004')
    
    async with httpx.AsyncClient(timeout=90.0) as client:
        try:
            response = await client.post(
                f"{cm_base_url}/api/v1/statements/generate",
                json=statement_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                statement_result = response.json()
                
                activity.logger.info(f"Customer statement generated: {statement_result.get('statement_id')}")
                return statement_result
            
            else:
                activity.logger.error(f"Statement generation failed: {response.status_code}")
                raise Exception(f"Statement generation failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error generating customer statement: {str(e)}")
            raise


@activity.defn
async def escalate_to_supervisor(escalation_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Escalate issue to supervisor level
    """
    activity.logger.info(f"Escalating to supervisor: {escalation_data.get('issue_type')}")
    
    cm_base_url = os.getenv('CM_BASE_URL', 'http://cm:8004')
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{cm_base_url}/api/v1/escalations/create",
                json=escalation_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                escalation_result = response.json()
                
                activity.logger.info(f"Escalation created: {escalation_result.get('escalation_id')}")
                return escalation_result
            
            else:
                activity.logger.error(f"Escalation creation failed: {response.status_code}")
                raise Exception(f"Escalation creation failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error creating escalation: {str(e)}")
            raise