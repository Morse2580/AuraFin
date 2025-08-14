import asyncio
import logging
import os
from temporalio.client import Client
from temporalio.worker import Worker

# Import workflows
from workflows.cash_application import (
    CashApplicationWorkflow,
    CollectionsWorkflow,
    CreditManagementWorkflow
)

# Import activities
from activities.dim_activities import (
    extract_invoice_ids,
    extract_document_metadata,
    process_document_batch,
    validate_document_quality
)
from activities.eic_activities import (
    fetch_invoice_details,
    update_erp_systems,
    sync_customer_data,
    update_credit_limits,
    fetch_customer_payment_history,
    reconcile_accounts
)
from activities.cle_activities import (
    match_payment_to_invoices,
    validate_matching_rules,
    calculate_matching_confidence,
    process_exception_handling,
    optimize_matching_parameters,
    generate_matching_report,
    train_matching_model
)
from activities.cm_activities import (
    send_completion_notifications,
    route_for_manual_review,
    send_collection_notice,
    assess_credit_risk,
    send_payment_reminder,
    generate_customer_statement,
    escalate_to_supervisor
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """
    Main function to start the Temporal worker
    """
    # Connect to Temporal server
    temporal_host = os.getenv('TEMPORAL_HOST', 'temporal:7233')
    client = await Client.connect(temporal_host)
    
    logger.info(f"Connected to Temporal server at {temporal_host}")
    
    # Create and start worker
    worker = Worker(
        client,
        task_queue="cashapp-task-queue",
        workflows=[
            CashApplicationWorkflow,
            CollectionsWorkflow,
            CreditManagementWorkflow
        ],
        activities=[
            # DIM activities
            extract_invoice_ids,
            extract_document_metadata,
            process_document_batch,
            validate_document_quality,
            
            # EIC activities
            fetch_invoice_details,
            update_erp_systems,
            sync_customer_data,
            update_credit_limits,
            fetch_customer_payment_history,
            reconcile_accounts,
            
            # CLE activities
            match_payment_to_invoices,
            validate_matching_rules,
            calculate_matching_confidence,
            process_exception_handling,
            optimize_matching_parameters,
            generate_matching_report,
            train_matching_model,
            
            # CM activities
            send_completion_notifications,
            route_for_manual_review,
            send_collection_notice,
            assess_credit_risk,
            send_payment_reminder,
            generate_customer_statement,
            escalate_to_supervisor
        ],
        # Worker configuration
        max_concurrent_activities=50,
        max_concurrent_workflow_tasks=100,
    )
    
    logger.info("Starting Temporal worker...")
    logger.info("Available workflows:")
    logger.info("  - CashApplicationWorkflow: End-to-end cash application processing")
    logger.info("  - CollectionsWorkflow: Automated collections and dunning")
    logger.info("  - CreditManagementWorkflow: Credit risk assessment and management")
    
    # Worker ready; activities and workflows registered
    
    try:
        await worker.run()
    except KeyboardInterrupt:
        logger.info("Worker shutdown requested...")
    except Exception as e:
        logger.error(f"Worker error: {str(e)}")
        raise
    finally:
        logger.info("Temporal worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
