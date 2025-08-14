# shared/database.py
"""
Database utilities and connection management
Centralized database operations for CashAppAgent
"""

import asyncio
import asyncpg
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager
import os
from .logging import setup_logging
from .exception import CashAppException

logger = setup_logging("database-utils")


class DatabaseManager:
    """
    Centralized database connection and operation manager
    Handles connection pooling and common database operations
    """
    
    def __init__(self, connection_string: str, min_connections: int = 5, max_connections: int = 20):
        self.connection_string = connection_string
        self.min_connections = min_connections
        self.max_connections = max_connections
        self.pool = None
    
    async def initialize(self):
        """Initialize database connection pool"""
        try:
            self.pool = await asyncpg.create_pool(
                self.connection_string,
                min_size=self.min_connections,
                max_size=self.max_connections,
                command_timeout=60
            )
            logger.info("Database connection pool initialized", 
                       extra={"min_connections": self.min_connections, 
                             "max_connections": self.max_connections})
        except Exception as e:
            logger.error("Failed to initialize database pool", 
                        extra={"error": str(e)})
            raise CashAppException(f"Database initialization failed: {e}", "DATABASE_INIT_ERROR")
    
    async def close(self):
        """Close database connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("Database connection pool closed")
    
    @asynccontextmanager
    async def get_connection(self):
        """Get database connection from pool"""
        if not self.pool:
            raise CashAppException("Database pool not initialized", "DATABASE_POOL_ERROR")
        
        async with self.pool.acquire() as connection:
            yield connection
    
    async def execute_query(self, query: str, *args) -> List[Dict[str, Any]]:
        """
        Execute a SELECT query and return results
        
        Args:
            query: SQL query string
            *args: Query parameters
        
        Returns:
            List of dictionaries representing rows
        """
        async with self.get_connection() as conn:
            try:
                rows = await conn.fetch(query, *args)
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error("Query execution failed", 
                            extra={"query": query, "error": str(e)})
                raise CashAppException(f"Query failed: {e}", "DATABASE_QUERY_ERROR")
    
    async def execute_command(self, command: str, *args) -> str:
        """
        Execute an INSERT/UPDATE/DELETE command
        
        Args:
            command: SQL command string
            *args: Command parameters
        
        Returns:
            Command result status
        """
        async with self.get_connection() as conn:
            try:
                result = await conn.execute(command, *args)
                return result
            except Exception as e:
                logger.error("Command execution failed", 
                            extra={"command": command, "error": str(e)})
                raise CashAppException(f"Command failed: {e}", "DATABASE_COMMAND_ERROR")
    
    async def execute_transaction(self, commands: List[tuple]) -> bool:
        """
        Execute multiple commands in a single transaction
        
        Args:
            commands: List of (command, *args) tuples
        
        Returns:
            True if transaction successful
        """
        async with self.get_connection() as conn:
            async with conn.transaction():
                try:
                    for command, *args in commands:
                        await conn.execute(command, *args)
                    return True
                except Exception as e:
                    logger.error("Transaction failed", 
                                extra={"commands_count": len(commands), "error": str(e)})
                    raise CashAppException(f"Transaction failed: {e}", "DATABASE_TRANSACTION_ERROR")


def get_database_url() -> str:
    """
    Get database connection URL from environment variables
    
    Returns:
        PostgreSQL connection string
    """
    # Prefer a full DATABASE_URL if provided
    full_url = os.getenv('DATABASE_URL')
    if full_url:
        return full_url
    
    host = os.getenv('DB_HOST', 'localhost')
    port = os.getenv('DB_PORT', '5432')
    database = os.getenv('DB_NAME', 'cashapp')
    username = os.getenv('DB_USER', 'cashapp_user')
    password = os.getenv('DB_PASSWORD', 'password')
    
    return f"postgresql://{username}:{password}@{host}:{port}/{database}"


# Initialize global database manager
db_manager = None

async def initialize_database():
    """Initialize global database manager"""
    global db_manager
    if db_manager is None:
        db_manager = DatabaseManager(get_database_url())
        await db_manager.initialize()

async def get_db_manager() -> DatabaseManager:
    """Get initialized database manager"""
    if db_manager is None:
        await initialize_database()
    return db_manager
