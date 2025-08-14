# shared/queue_rabbitmq.py
"""
RabbitMQ integration for reliable message processing
Replaces Azure Service Bus with self-hosted, cost-effective solution
Provides error handling, retry logic, and dead letter queue management
"""

import asyncio
import json
import time
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import pika
from kombu import Connection, Queue, Exchange, Producer, Consumer
from kombu.exceptions import ConnectionError, ChannelError
import backoff

from .logging import setup_logging
from .exception import CashAppException
from .models import PaymentTransaction, MatchResult

logger = setup_logging("queue_rabbitmq")

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

class RabbitMQManager:
    """
    Manages RabbitMQ operations with retry logic
    Handles transaction processing, failure recovery, and dead letter queues
    """
    
    def __init__(self, rabbitmq_url: str = "amqp://admin:admin@rabbitmq:5672/"):
        self.rabbitmq_url = rabbitmq_url
        self.connection = None
        self.producers = {}
        self.consumers = {}
        self.message_handlers = {}
        
        # Exchange and queue configuration
        self.exchanges = {
            'transactions': Exchange('cashapp.transactions', type='direct', durable=True),
            'erp_operations': Exchange('cashapp.erp', type='direct', durable=True),
            'communications': Exchange('cashapp.communications', type='direct', durable=True),
            'document_processing': Exchange('cashapp.documents', type='direct', durable=True),
            'retry': Exchange('cashapp.retry', type='direct', durable=True),
            'dlx': Exchange('cashapp.dlx', type='direct', durable=True)  # Dead Letter Exchange
        }
        
        self.queues = {
            'transactions': Queue('cashapp-transactions', 
                                exchange=self.exchanges['transactions'], 
                                routing_key='process',
                                durable=True,
                                arguments={
                                    'x-dead-letter-exchange': 'cashapp.dlx',
                                    'x-dead-letter-routing-key': 'failed.transaction'
                                }),
            'erp_operations': Queue('cashapp-erp-operations', 
                                  exchange=self.exchanges['erp_operations'], 
                                  routing_key='operation',
                                  durable=True,
                                  arguments={
                                      'x-dead-letter-exchange': 'cashapp.dlx',
                                      'x-dead-letter-routing-key': 'failed.erp'
                                  }),
            'communications': Queue('cashapp-communications', 
                                  exchange=self.exchanges['communications'], 
                                  routing_key='send',
                                  durable=True,
                                  arguments={
                                      'x-message-ttl': 300000,  # 5 minutes TTL
                                      'x-dead-letter-exchange': 'cashapp.dlx',
                                      'x-dead-letter-routing-key': 'failed.communication'
                                  }),
            'document_processing': Queue('cashapp-document-processing', 
                                       exchange=self.exchanges['document_processing'], 
                                       routing_key='process',
                                       durable=True,
                                       arguments={
                                           'x-dead-letter-exchange': 'cashapp.dlx',
                                           'x-dead-letter-routing-key': 'failed.document'
                                       }),
            'retry': Queue('cashapp-retry', 
                          exchange=self.exchanges['retry'], 
                          routing_key='retry',
                          durable=True,
                          arguments={
                              'x-message-ttl': 60000,  # 1 minute TTL for retry
                              'x-dead-letter-exchange': 'cashapp.transactions',
                              'x-dead-letter-routing-key': 'process'
                          }),
            'dead_letter': Queue('cashapp-dead-letter', 
                               exchange=self.exchanges['dlx'], 
                               routing_key='failed.*',
                               durable=True)
        }
    
    async def initialize(self):
        """Initialize RabbitMQ connection and declare exchanges/queues"""
        try:
            # Create connection
            self.connection = Connection(self.rabbitmq_url)
            self.connection.connect()
            
            # Declare exchanges and queues
            with self.connection.channel() as channel:
                for exchange in self.exchanges.values():
                    exchange.declare(channel=channel)
                
                for queue in self.queues.values():
                    queue.declare(channel=channel)
            
            logger.info("RabbitMQ connection initialized")
            logger.info(f"Declared {len(self.exchanges)} exchanges and {len(self.queues)} queues")
            
        except ConnectionError as e:
            logger.error(f"Failed to initialize RabbitMQ: {e}")
            raise CashAppException(f"Queue initialization failed: {e}", "QUEUE_INIT_ERROR")
    
    async def close(self):
        """Close RabbitMQ connection"""
        try:
            if self.connection:
                self.connection.close()
            logger.info("RabbitMQ connection closed")
            
        except Exception as e:
            logger.warning(f"Error closing RabbitMQ connection: {e}")
    
    async def send_message(self, 
                          queue_name: str, 
                          message: QueueMessage, 
                          delay_seconds: int = 0,
                          priority: int = 0) -> bool:
        """
        Send message to queue with optional delay and priority
        
        Args:
            queue_name: Target queue name
            message: Message to send
            delay_seconds: Delay before message becomes available
            priority: Message priority (0-255)
            
        Returns:
            True if message sent successfully
        """
        try:
            if queue_name not in self.queues:
                raise ValueError(f"No queue configured for: {queue_name}")
            
            with self.connection.channel() as channel:
                producer = Producer(channel)
                
                # Prepare message properties
                message_properties = {
                    'message_id': message.message_id,
                    'correlation_id': message.correlation_id,
                    'content_type': 'application/json',
                    'priority': priority,
                    'timestamp': message.created_at.timestamp(),
                    'headers': {
                        'message_type': message.message_type,
                        'retry_count': message.retry_count,
                        'max_retries': message.max_retries,
                        'created_at': message.created_at.isoformat()
                    }
                }
                
                # Handle delayed messages using retry queue
                if delay_seconds > 0:
                    # Send to retry queue with TTL
                    retry_queue = Queue(f'cashapp-delay-{delay_seconds}', 
                                      exchange=self.exchanges['retry'], 
                                      routing_key='delay',
                                      durable=True,
                                      arguments={
                                          'x-message-ttl': delay_seconds * 1000,
                                          'x-dead-letter-exchange': self.queues[queue_name].exchange.name,
                                          'x-dead-letter-routing-key': self.queues[queue_name].routing_key
                                      })
                    retry_queue.declare(channel=channel)
                    target_queue = retry_queue
                else:
                    target_queue = self.queues[queue_name]
                
                # Publish message
                producer.publish(
                    asdict(message),
                    exchange=target_queue.exchange,
                    routing_key=target_queue.routing_key,
                    declare=[target_queue],
                    **message_properties
                )
                
            logger.info(f"Message sent to {queue_name}", extra={
                'message_id': message.message_id,
                'message_type': message.message_type,
                'delay_seconds': delay_seconds,
                'priority': priority
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
        
        # Map priority to RabbitMQ priority
        priority_map = {'low': 0, 'normal': 5, 'high': 8, 'urgent': 10}
        rabbitmq_priority = priority_map.get(priority, 5)
        
        return await self.send_message('communications', message, priority=rabbitmq_priority)
    
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
        
        try:
            # Create consumer with prefetch limit
            with self.connection.channel() as channel:
                channel.basic_qos(prefetch_count=max_concurrent)
                
                queue = self.queues[queue_name]
                
                # Define message callback
                def on_message(body, message):
                    try:
                        # Process message asynchronously
                        asyncio.create_task(self._process_message_wrapper(body, message))
                    except Exception as e:
                        logger.error(f"Error creating message processing task: {e}")
                        message.reject(requeue=True)
                
                # Start consuming
                consumer = Consumer(
                    channel,
                    queues=[queue],
                    callbacks=[on_message],
                    auto_declare=False
                )
                
                self.consumers[queue_name] = consumer
                
                logger.info(f"Started message processor for {queue_name}")
                
                # Start consuming messages
                with consumer:
                    while True:
                        try:
                            self.connection.drain_events(timeout=1)
                        except Exception as e:
                            if "timed out" not in str(e).lower():
                                logger.error(f"Error draining events: {e}")
                                await asyncio.sleep(5)
                                
        except Exception as e:
            logger.error(f"Failed to start message processor: {e}")
            raise CashAppException(f"Message processor failed: {e}", "QUEUE_PROCESSOR_ERROR")
    
    async def _process_message_wrapper(self, body, message):
        """Wrapper to handle message processing in async context"""
        try:
            result = await self._process_message(body, message)
            
            if result.success:
                message.ack()
            else:
                # Check if we should retry
                headers = message.headers or {}
                retry_count = headers.get('retry_count', 0)
                max_retries = headers.get('max_retries', 3)
                
                if retry_count < max_retries:
                    # Increment retry count and requeue with delay
                    headers['retry_count'] = retry_count + 1
                    delay_seconds = min(2 ** retry_count, 300)  # Exponential backoff, max 5 minutes
                    
                    # Create new message for retry
                    queue_message = QueueMessage(**json.loads(body))
                    queue_message.retry_count = retry_count + 1
                    
                    await self.send_message('retry', queue_message, delay_seconds=delay_seconds)
                    message.ack()  # Ack original message
                else:
                    # Send to dead letter queue
                    message.reject(requeue=False)
                    
        except Exception as e:
            logger.error(f"Message processing wrapper error: {e}")
            message.reject(requeue=True)
    
    async def _process_message(self, body, message) -> ProcessingResult:
        """
        Process individual message with error handling
        
        Args:
            body: Message body
            message: Message object
            
        Returns:
            Processing result
        """
        start_time = time.time()
        
        try:
            # Parse message
            queue_message = QueueMessage(**json.loads(body))
            
            logger.info(f"Processing message: {queue_message.message_id}", extra={
                'message_type': queue_message.message_type,
                'correlation_id': queue_message.correlation_id,
                'retry_count': queue_message.retry_count
            })
            
            # Get message handler
            handler = self.message_handlers.get(queue_message.message_type)
            if not handler:
                logger.warning(f"No handler for message type: {queue_message.message_type}")
                return ProcessingResult(
                    success=False,
                    error_message=f"No handler for message type: {queue_message.message_type}",
                    processing_time_ms=int((time.time() - start_time) * 1000)
                )
            
            # Execute handler
            result = await self._execute_with_retry(handler, queue_message)
            result.processing_time_ms = int((time.time() - start_time) * 1000)
            
            if result.success:
                logger.info(f"Message processed successfully: {queue_message.message_id}")
            
            return result
            
        except Exception as e:
            processing_time = int((time.time() - start_time) * 1000)
            logger.error(f"Message processing failed: {e}")
            
            return ProcessingResult(
                success=False,
                error_message=str(e),
                processing_time_ms=processing_time,
                retry_recommended=True
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

class TransactionProcessor:
    """
    Transaction processing with RabbitMQ-based reliability
    Handles the core transaction processing workflow
    """
    
    def __init__(self, rabbitmq_manager: RabbitMQManager):
        self.queue_manager = rabbitmq_manager
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
        
        # High priority messages get higher priority
        priority_map = {'low': 0, 'normal': 5, 'high': 8, 'urgent': 10}
        rabbitmq_priority = priority_map.get(priority, 5)
        
        return await self.queue_manager.send_message('transactions', message, priority=rabbitmq_priority)
    
    async def _handle_transaction(self, message: QueueMessage):
        """Handle transaction processing message"""
        try:
            # Parse transaction from payload
            transaction = PaymentTransaction(**message.payload)
            
            logger.info(f"Processing transaction: {transaction.transaction_id}")
            
            # Simulate core logic engine processing
            await self._simulate_transaction_processing(transaction)
            
            self.processing_stats['successful'] += 1
            self.processing_stats['total_processed'] += 1
            
        except Exception as e:
            logger.error(f"Transaction processing failed: {e}")
            self.processing_stats['failed'] += 1
            self.processing_stats['total_processed'] += 1
            raise
    
    async def _simulate_transaction_processing(self, transaction: PaymentTransaction):
        """Simulate transaction processing"""
        await asyncio.sleep(0.1)  # Simulate processing time
        
        if transaction.amount > 50000:  # Simulate occasional failures
            raise Exception("Amount exceeds processing limit")
    
    async def _handle_erp_operation(self, message: QueueMessage):
        """Handle ERP operation message"""
        try:
            operation_type = message.message_type.replace('erp_', '')
            logger.info(f"Processing ERP operation: {operation_type}")
            
            await self._simulate_erp_operation(operation_type, message.payload)
            
        except Exception as e:
            logger.error(f"ERP operation failed: {e}")
            raise
    
    async def _simulate_erp_operation(self, operation_type: str, payload: Dict[str, Any]):
        """Simulate ERP operation"""
        await asyncio.sleep(0.2)  # Simulate ERP call time
        
        if payload.get('simulate_timeout'):
            raise Exception("ERP system timeout")
    
    async def _handle_communication(self, message: QueueMessage):
        """Handle communication message"""
        try:
            comm_type = message.message_type.replace('communication_', '')
            logger.info(f"Processing communication: {comm_type}")
            
            await self._simulate_communication(comm_type, message.payload)
            
        except Exception as e:
            logger.error(f"Communication failed: {e}")
            raise
    
    async def _simulate_communication(self, comm_type: str, payload: Dict[str, Any]):
        """Simulate communication sending"""
        await asyncio.sleep(0.1)  # Simulate email/slack send time
        
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

# Global queue manager instance
_rabbitmq_manager = None
_transaction_processor = None

async def initialize_rabbitmq_system(rabbitmq_url: str = None) -> RabbitMQManager:
    """
    Initialize global RabbitMQ system
    
    Args:
        rabbitmq_url: RabbitMQ connection URL
        
    Returns:
        Initialized RabbitMQ manager
    """
    global _rabbitmq_manager, _transaction_processor
    
    if not _rabbitmq_manager:
        _rabbitmq_manager = RabbitMQManager(rabbitmq_url or "amqp://admin:admin@rabbitmq:5672/")
        await _rabbitmq_manager.initialize()
        
        _transaction_processor = TransactionProcessor(_rabbitmq_manager)
        await _transaction_processor.initialize()
        
        logger.info("RabbitMQ system initialized")
    
    return _rabbitmq_manager

async def get_rabbitmq_manager() -> RabbitMQManager:
    """Get initialized RabbitMQ manager"""
    if not _rabbitmq_manager:
        raise CashAppException("RabbitMQ manager not initialized", "QUEUE_NOT_INITIALIZED")
    return _rabbitmq_manager

async def get_transaction_processor() -> TransactionProcessor:
    """Get initialized transaction processor"""
    if not _transaction_processor:
        raise CashAppException("Transaction processor not initialized", "PROCESSOR_NOT_INITIALIZED")
    return _transaction_processor

async def rabbitmq_health_check() -> Dict[str, Any]:
    """
    Check RabbitMQ system health
    
    Returns:
        Health status of queue components
    """
    try:
        if not _rabbitmq_manager:
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
        success = await _rabbitmq_manager.send_message('retry', test_message)
        
        stats = _transaction_processor.get_processing_stats() if _transaction_processor else {}
        
        return {
            "status": "healthy" if success else "degraded",
            "components": {
                "rabbitmq": "connected" if success else "failed",
                "message_handlers": len(_rabbitmq_manager.message_handlers),
                "active_consumers": len(_rabbitmq_manager.consumers)
            },
            "processing_stats": stats
        }
        
    except Exception as e:
        logger.error(f"RabbitMQ health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }