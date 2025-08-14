# shared/queue.py
"""
Azure Service Bus integration for reliable message processing
Provides error handling, retry logic, and dead letter queue management
"""

import asyncio
import json
import time
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from azure.servicebus.aio import ServiceBusClient, ServiceBusReceiver, ServiceBusSender
from azure.servicebus import ServiceBusMessage, ServiceBusReceiveMode
from azure.core.exceptions import AzureError
import backoff

from .logging import setup_logging
from .exception import CashAppException
from .models import PaymentTransaction, MatchResult

logger = setup_logging("queue")

@dataclass
class QueueMessage:
    """Standard message format for queue operations"""
    message_id: str
    message_type: str
    payload: Dict[str, Any]
    correlation_id: str
    created_at: datetime
    retry_count: int = 0
    max_retries: int = 3
    delay_seconds: int = 0

@dataclass
class ProcessingResult:
    """Result of message processing"""
    success: bool
    error_message: Optional[str] = None
    retry_recommended: bool = False
    processing_time_ms: int = 0

class ServiceBusManager:
    """
    Manages Azure Service Bus operations with retry logic
    Handles transaction processing, failure recovery, and dead letter queues
    """
    
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.client = None
        self.senders = {}
        self.receivers = {}
        self.message_handlers = {}
        
        # Queue names
        self.queues = {
            'transactions': 'cashapp-transactions',
            'erp_operations': 'cashapp-erp-operations',
            'communications': 'cashapp-communications',
            'document_processing': 'cashapp-document-processing',
            'retry': 'cashapp-retry',
            'dead_letter': 'cashapp-dead-letter'
        }
    
    async def initialize(self):
        """Initialize Service Bus client and connections"""
        try:
            self.client = ServiceBusClient.from_connection_string(
                self.connection_string,
                retry_total=3,
                retry_backoff_factor=0.8,
                retry_backoff_max=120
            )
            
            # Initialize senders for all queues
            for queue_name, queue_key in self.queues.items():
                self.senders[queue_name] = self.client.get_queue_sender(queue_key)
            
            logger.info("Service Bus client initialized")
            
        except AzureError as e:
            logger.error(f"Failed to initialize Service Bus: {e}")
            raise CashAppException(f"Queue initialization failed: {e}", "QUEUE_INIT_ERROR")
    
    async def close(self):
        """Close all Service Bus connections"""
        try:
            # Close senders
            for sender in self.senders.values():
                await sender.close()
            
            # Close receivers
            for receiver in self.receivers.values():
                await receiver.close()
            
            # Close client
            if self.client:
                await self.client.close()
            
            logger.info("Service Bus connections closed")
            
        except Exception as e:
            logger.warning(f"Error closing Service Bus connections: {e}")
    
    async def send_message(self, 
                          queue_name: str, 
                          message: QueueMessage, 
                          delay_seconds: int = 0) -> bool:
        """
        Send message to queue with optional delay
        
        Args:
            queue_name: Target queue name
            message: Message to send
            delay_seconds: Delay before message becomes available
            
        Returns:
            True if message sent successfully
        """
        try:
            sender = self.senders.get(queue_name)
            if not sender:
                raise ValueError(f"No sender configured for queue: {queue_name}")
            
            # Create Service Bus message
            sb_message = ServiceBusMessage(
                body=json.dumps(asdict(message)),
                message_id=message.message_id,
                correlation_id=message.correlation_id,
                content_type="application/json"
            )
            
            # Add custom properties
            sb_message.application_properties = {
                'message_type': message.message_type,
                'retry_count': message.retry_count,
                'max_retries': message.max_retries,
                'created_at': message.created_at.isoformat()
            }
            
            # Schedule delivery if delay specified
            if delay_seconds > 0:
                scheduled_time = datetime.utcnow() + timedelta(seconds=delay_seconds)
                sb_message.scheduled_enqueue_time_utc = scheduled_time
            
            # Send message
            await sender.send_messages(sb_message)
            
            logger.info(f"Message sent to {queue_name}", extra={
                'message_id': message.message_id,
                'message_type': message.message_type,
                'delay_seconds': delay_seconds
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to send message to {queue_name}: {e}")
            return False
    
    async def send_transaction_for_processing(self, transaction: PaymentTransaction) -> bool:
        """
        Send transaction to processing queue
        
        Args:
            transaction: Payment transaction to process
            
        Returns:
            True if queued successfully
        """
        message = QueueMessage(
            message_id=f"txn-{transaction.transaction_id}-{int(time.time())}",
            message_type="process_transaction",
            payload=transaction.dict(),
            correlation_id=transaction.transaction_id,
            created_at=datetime.utcnow()
        )
        
        return await self.send_message('transactions', message)
    
    async def send_erp_operation(self, operation_type: str, payload: Dict[str, Any], 
                                correlation_id: str) -> bool:
        """
        Send ERP operation to processing queue
        
        Args:
            operation_type: Type of ERP operation
            payload: Operation payload
            correlation_id: Correlation ID for tracking
            
        Returns:
            True if queued successfully
        """
        message = QueueMessage(
            message_id=f"erp-{operation_type}-{int(time.time())}",
            message_type=f"erp_{operation_type}",
            payload=payload,
            correlation_id=correlation_id,
            created_at=datetime.utcnow()
        )
        
        return await self.send_message('erp_operations', message)
    
    async def send_communication_request(self, comm_type: str, payload: Dict[str, Any],
                                       correlation_id: str, priority: str = "normal") -> bool:
        """
        Send communication request to queue
        
        Args:
            comm_type: Type of communication
            payload: Communication payload
            correlation_id: Correlation ID for tracking
            priority: Message priority
            
        Returns:
            True if queued successfully
        """
        message = QueueMessage(
            message_id=f"comm-{comm_type}-{int(time.time())}",
            message_type=f"communication_{comm_type}",
            payload=payload,
            correlation_id=correlation_id,
            created_at=datetime.utcnow()
        )
        
        # Prioritize urgent messages
        delay = 0 if priority in ['high', 'urgent'] else 30
        
        return await self.send_message('communications', message, delay_seconds=delay)
    
    def register_message_handler(self, message_type: str, handler: Callable):
        """
        Register handler function for specific message type
        
        Args:
            message_type: Type of message to handle
            handler: Async function to handle the message
        """
        self.message_handlers[message_type] = handler
        logger.info(f"Registered handler for message type: {message_type}")
    
    async def start_message_processor(self, queue_name: str, max_concurrent: int = 5):
        """
        Start processing messages from queue
        
        Args:
            queue_name: Queue to process messages from
            max_concurrent: Maximum concurrent message processing
        """
        if queue_name not in self.queues:
            raise ValueError(f"Unknown queue: {queue_name}")
        
        queue_key = self.queues[queue_name]
        
        try:
            # Create receiver
            receiver = self.client.get_queue_receiver(
                queue_name=queue_key,
                receive_mode=ServiceBusReceiveMode.PEEK_LOCK,
                max_wait_time=30
            )
            self.receivers[queue_name] = receiver
            
            # Start processing loop
            semaphore = asyncio.Semaphore(max_concurrent)
            
            logger.info(f"Started message processor for {queue_name}")
            
            async with receiver:
                while True:
                    try:
                        # Receive messages
                        messages = await receiver.receive_messages(max_message_count=10, max_wait_time=10)
                        
                        if messages:
                            # Process messages concurrently
                            tasks = [
                                self._process_message_with_semaphore(semaphore, receiver, msg)
                                for msg in messages
                            ]
                            await asyncio.gather(*tasks, return_exceptions=True)
                        
                        await asyncio.sleep(1)  # Brief pause between batches
                        
                    except Exception as e:
                        logger.error(f"Error in message processing loop: {e}")
                        await asyncio.sleep(5)  # Wait before retrying
                        
        except Exception as e:
            logger.error(f"Failed to start message processor: {e}")
            raise CashAppException(f"Message processor failed: {e}", "QUEUE_PROCESSOR_ERROR")
    
    async def _process_message_with_semaphore(self, semaphore: asyncio.Semaphore, 
                                             receiver: ServiceBusReceiver, 
                                             message) -> ProcessingResult:
        """Process single message with concurrency control"""
        async with semaphore:
            return await self._process_message(receiver, message)
    
    async def _process_message(self, receiver: ServiceBusReceiver, message) -> ProcessingResult:
        """
        Process individual message with retry logic
        
        Args:
            receiver: Service Bus receiver
            message: Service Bus message to process
            
        Returns:
            Processing result
        """
        start_time = time.time()
        
        try:
            # Parse message
            body = json.loads(str(message))
            queue_message = QueueMessage(**body)
            
            logger.info(f"Processing message: {queue_message.message_id}", extra={
                'message_type': queue_message.message_type,
                'correlation_id': queue_message.correlation_id,
                'retry_count': queue_message.retry_count
            })
            
            # Get message handler
            handler = self.message_handlers.get(queue_message.message_type)
            if not handler:
                logger.warning(f"No handler for message type: {queue_message.message_type}")
                await receiver.complete_message(message)
                return ProcessingResult(
                    success=False,
                    error_message=f"No handler for message type: {queue_message.message_type}",
                    processing_time_ms=int((time.time() - start_time) * 1000)
                )
            
            # Process message with exponential backoff retry
            result = await self._execute_with_retry(handler, queue_message)
            
            if result.success:
                # Complete message on success
                await receiver.complete_message(message)
                logger.info(f"Message processed successfully: {queue_message.message_id}")
            else:
                # Handle failure
                await self._handle_message_failure(receiver, message, queue_message, result)
            
            result.processing_time_ms = int((time.time() - start_time) * 1000)
            return result
            
        except Exception as e:
            processing_time = int((time.time() - start_time) * 1000)
            logger.error(f"Message processing failed: {e}")
            
            # Abandon message to retry later
            await receiver.abandon_message(message)
            
            return ProcessingResult(
                success=False,
                error_message=str(e),
                processing_time_ms=processing_time
            )
    
    @backoff.on_exception(
        backoff.expo,
        Exception,
        max_tries=3,
        base=2,
        max_value=60
    )
    async def _execute_with_retry(self, handler: Callable, message: QueueMessage) -> ProcessingResult:
        """Execute message handler with exponential backoff retry"""
        try:
            await handler(message)
            return ProcessingResult(success=True)
            
        except Exception as e:
            logger.warning(f"Handler execution failed: {e}")
            return ProcessingResult(
                success=False,
                error_message=str(e),
                retry_recommended=message.retry_count < message.max_retries
            )
    
    async def _handle_message_failure(self, receiver: ServiceBusReceiver, 
                                     message, queue_message: QueueMessage, 
                                     result: ProcessingResult):
        """
        Handle failed message processing
        
        Args:
            receiver: Service Bus receiver
            message: Original Service Bus message
            queue_message: Parsed queue message
            result: Processing result with error details
        """
        if queue_message.retry_count < queue_message.max_retries and result.retry_recommended:
            # Retry with exponential backoff
            queue_message.retry_count += 1
            delay_seconds = min(2 ** queue_message.retry_count, 300)  # Max 5 minutes
            
            logger.info(f"Retrying message {queue_message.message_id} in {delay_seconds} seconds", extra={
                'retry_count': queue_message.retry_count,
                'max_retries': queue_message.max_retries
            })
            
            # Send to retry queue
            await self.send_message('retry', queue_message, delay_seconds=delay_seconds)
            await receiver.complete_message(message)
            
        else:
            # Send to dead letter queue
            logger.error(f"Message {queue_message.message_id} exceeded max retries, sending to DLQ")
            
            dlq_message = QueueMessage(
                message_id=f"dlq-{queue_message.message_id}",
                message_type="dead_letter",
                payload={
                    'original_message': asdict(queue_message),
                    'final_error': result.error_message,
                    'processing_attempts': queue_message.retry_count + 1
                },
                correlation_id=queue_message.correlation_id,
                created_at=datetime.utcnow()
            )
            
            await self.send_message('dead_letter', dlq_message)
            await receiver.complete_message(message)

class TransactionProcessor:
    """
    Transaction processing with queue-based reliability
    Handles the core transaction processing workflow
    """
    
    def __init__(self, service_bus_manager: ServiceBusManager):
        self.queue_manager = service_bus_manager
        self.processing_stats = {
            'total_processed': 0,
            'successful': 0,
            'failed': 0,
            'retried': 0
        }
    
    async def initialize(self):
        """Initialize transaction processor"""
        # Register message handlers
        self.queue_manager.register_message_handler('process_transaction', self._handle_transaction)
        self.queue_manager.register_message_handler('erp_get_invoices', self._handle_erp_operation)
        self.queue_manager.register_message_handler('erp_post_application', self._handle_erp_operation)
        self.queue_manager.register_message_handler('communication_email', self._handle_communication)
        self.queue_manager.register_message_handler('communication_slack', self._handle_communication)
        
        logger.info("Transaction processor initialized")
    
    async def queue_transaction(self, transaction: PaymentTransaction, priority: str = "normal") -> bool:
        """
        Queue transaction for processing
        
        Args:
            transaction: Payment transaction to process
            priority: Processing priority
            
        Returns:
            True if queued successfully
        """
        message = QueueMessage(
            message_id=f"txn-{transaction.transaction_id}-{int(time.time())}",
            message_type="process_transaction",
            payload=transaction.dict(),
            correlation_id=transaction.transaction_id,
            created_at=datetime.utcnow(),
            max_retries=5 if priority == "high" else 3
        )
        
        # High priority messages get processed immediately
        delay = 0 if priority in ['high', 'urgent'] else 10
        
        return await self.queue_manager.send_message('transactions', message, delay_seconds=delay)
    
    async def _handle_transaction(self, message: QueueMessage):
        """
        Handle transaction processing message
        
        Args:
            message: Transaction message to process
        """
        try:
            # Parse transaction from payload
            transaction = PaymentTransaction(**message.payload)
            
            logger.info(f"Processing transaction: {transaction.transaction_id}")
            
            # Simulate core logic engine processing
            # In real implementation, this would call the actual CLE logic
            await self._simulate_transaction_processing(transaction)
            
            self.processing_stats['successful'] += 1
            self.processing_stats['total_processed'] += 1
            
        except Exception as e:
            logger.error(f"Transaction processing failed: {e}")
            self.processing_stats['failed'] += 1
            self.processing_stats['total_processed'] += 1
            raise
    
    async def _simulate_transaction_processing(self, transaction: PaymentTransaction):
        """Simulate transaction processing (placeholder for actual logic)"""
        # This is a placeholder - in real implementation, this would:
        # 1. Call document intelligence
        # 2. Fetch invoices from ERP
        # 3. Execute matching algorithm
        # 4. Update ERP systems
        # 5. Send communications
        
        await asyncio.sleep(0.1)  # Simulate processing time
        
        if transaction.amount > 50000:  # Simulate occasional failures
            raise Exception("Amount exceeds processing limit")
    
    async def _handle_erp_operation(self, message: QueueMessage):
        """Handle ERP operation message"""
        try:
            operation_type = message.message_type.replace('erp_', '')
            logger.info(f"Processing ERP operation: {operation_type}")
            
            # Simulate ERP operation
            await self._simulate_erp_operation(operation_type, message.payload)
            
        except Exception as e:
            logger.error(f"ERP operation failed: {e}")
            raise
    
    async def _simulate_erp_operation(self, operation_type: str, payload: Dict[str, Any]):
        """Simulate ERP operation"""
        await asyncio.sleep(0.2)  # Simulate ERP call time
        
        # Simulate occasional ERP timeouts
        if payload.get('simulate_timeout'):
            raise Exception("ERP system timeout")
    
    async def _handle_communication(self, message: QueueMessage):
        """Handle communication message"""
        try:
            comm_type = message.message_type.replace('communication_', '')
            logger.info(f"Processing communication: {comm_type}")
            
            # Simulate communication
            await self._simulate_communication(comm_type, message.payload)
            
        except Exception as e:
            logger.error(f"Communication failed: {e}")
            raise
    
    async def _simulate_communication(self, comm_type: str, payload: Dict[str, Any]):
        """Simulate communication sending"""
        await asyncio.sleep(0.1)  # Simulate email/slack send time
        
        # Simulate occasional communication failures
        if payload.get('simulate_failure'):
            raise Exception("Communication service unavailable")
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """Get processing statistics"""
        total = self.processing_stats['total_processed']
        return {
            **self.processing_stats,
            'success_rate': self.processing_stats['successful'] / total if total > 0 else 0,
            'failure_rate': self.processing_stats['failed'] / total if total > 0 else 0
        }

class DeadLetterQueueManager:
    """Manages dead letter queue processing and analysis"""
    
    def __init__(self, service_bus_manager: ServiceBusManager):
        self.queue_manager = service_bus_manager
        self.dlq_stats = {
            'total_messages': 0,
            'processed': 0,
            'requeued': 0,
            'permanently_failed': 0
        }
    
    async def process_dead_letter_queue(self) -> Dict[str, Any]:
        """
        Process messages in dead letter queue
        
        Returns:
            Processing summary
        """
        try:
            # Get dead letter receiver
            receiver = self.queue_manager.client.get_queue_receiver(
                queue_name=self.queue_manager.queues['dead_letter'],
                receive_mode=ServiceBusReceiveMode.PEEK_LOCK
            )
            
            processed_count = 0
            requeued_count = 0
            
            async with receiver:
                while True:
                    messages = await receiver.receive_messages(max_message_count=10, max_wait_time=5)
                    
                    if not messages:
                        break
                    
                    for message in messages:
                        try:
                            # Parse dead letter message
                            body = json.loads(str(message))
                            dlq_message = QueueMessage(**body)
                            
                            # Analyze if message can be reprocessed
                            if await self._can_reprocess_message(dlq_message):
                                # Requeue original message
                                original_message = QueueMessage(**dlq_message.payload['original_message'])
                                original_message.retry_count = 0  # Reset retry count
                                
                                await self.queue_manager.send_message('retry', original_message)
                                requeued_count += 1
                                logger.info(f"Requeued message: {original_message.message_id}")
                            
                            # Complete dead letter message
                            await receiver.complete_message(message)
                            processed_count += 1
                            
                        except Exception as e:
                            logger.error(f"Failed to process dead letter message: {e}")
                            await receiver.abandon_message(message)
            
            self.dlq_stats['processed'] += processed_count
            self.dlq_stats['requeued'] += requeued_count
            self.dlq_stats['total_messages'] += processed_count
            
            logger.info(f"Dead letter queue processing completed", extra={
                'processed': processed_count,
                'requeued': requeued_count
            })
            
            return {
                'processed_messages': processed_count,
                'requeued_messages': requeued_count,
                'stats': self.dlq_stats
            }
            
        except Exception as e:
            logger.error(f"Dead letter queue processing failed: {e}")
            raise CashAppException(f"DLQ processing failed: {e}", "DLQ_PROCESSING_ERROR")
    
    async def _can_reprocess_message(self, dlq_message: QueueMessage) -> bool:
        """
        Determine if a dead letter message can be reprocessed
        
        Args:
            dlq_message: Dead letter queue message
            
        Returns:
            True if message can be safely reprocessed
        """
        try:
            original = dlq_message.payload.get('original_message', {})
            error_message = dlq_message.payload.get('final_error', '')
            
            # Don't reprocess validation errors
            if 'validation' in error_message.lower():
                return False
            
            # Don't reprocess messages older than 24 hours
            created_at = datetime.fromisoformat(original.get('created_at', ''))
            if datetime.utcnow() - created_at > timedelta(hours=24):
                return False
            
            # Reprocess timeout and connection errors
            retriable_errors = ['timeout', 'connection', 'unavailable', 'temporary']
            return any(error in error_message.lower() for error in retriable_errors)
            
        except Exception as e:
            logger.warning(f"Error analyzing DLQ message: {e}")
            return False

# Global queue manager instance
_queue_manager = None
_transaction_processor = None
_dlq_manager = None

async def initialize_queue_system(connection_string: str) -> ServiceBusManager:
    """
    Initialize global queue system
    
    Args:
        connection_string: Azure Service Bus connection string
        
    Returns:
        Initialized Service Bus manager
    """
    global _queue_manager, _transaction_processor, _dlq_manager
    
    if not _queue_manager:
        _queue_manager = ServiceBusManager(connection_string)
        await _queue_manager.initialize()
        
        _transaction_processor = TransactionProcessor(_queue_manager)
        await _transaction_processor.initialize()
        
        _dlq_manager = DeadLetterQueueManager(_queue_manager)
        
        logger.info("Queue system initialized")
    
    return _queue_manager

async def get_queue_manager() -> ServiceBusManager:
    """Get initialized queue manager"""
    if not _queue_manager:
        raise CashAppException("Queue manager not initialized", "QUEUE_NOT_INITIALIZED")
    return _queue_manager

async def get_transaction_processor() -> TransactionProcessor:
    """Get initialized transaction processor"""
    if not _transaction_processor:
        raise CashAppException("Transaction processor not initialized", "PROCESSOR_NOT_INITIALIZED")
    return _transaction_processor

async def queue_health_check() -> Dict[str, Any]:
    """
    Check queue system health
    
    Returns:
        Health status of queue components
    """
    try:
        if not _queue_manager:
            return {"status": "not_initialized"}
        
        # Test queue connectivity
        test_message = QueueMessage(
            message_id=f"health-check-{int(time.time())}",
            message_type="health_check",
            payload={"test": True},
            correlation_id="health-check",
            created_at=datetime.utcnow()
        )
        
        # Try to send to retry queue (least critical)
        success = await _queue_manager.send_message('retry', test_message)
        
        stats = _transaction_processor.get_processing_stats() if _transaction_processor else {}
        
        return {
            "status": "healthy" if success else "degraded",
            "components": {
                "service_bus": "connected" if success else "failed",
                "message_handlers": len(_queue_manager.message_handlers),
                "active_receivers": len(_queue_manager.receivers)
            },
            "processing_stats": stats
        }
        
    except Exception as e:
        logger.error(f"Queue health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }