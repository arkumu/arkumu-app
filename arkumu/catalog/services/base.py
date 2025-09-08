"""
Base service class providing common functionality for all catalog services.
"""

import logging
from typing import Any, Dict, Optional
from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger(__name__)


class BaseService:
    """
    Base class for all catalog services.
    Provides common functionality like caching, logging, and error handling.
    """
    
    def __init__(self):
        self.cache_timeout = getattr(settings, 'CATALOG_CACHE_TIMEOUT', 300)  # 5 minutes
        self.logger = logger.getChild(self.__class__.__name__)
    
    def _get_cache_key(self, *parts: str) -> str:
        """
        Generate a consistent cache key for this service.
        
        Args:
            *parts: Parts to include in the cache key
            
        Returns:
            Formatted cache key string
        """
        service_name = self.__class__.__name__.lower()
        cache_parts = [service_name] + list(parts)
        return ":".join(str(part) for part in cache_parts)
    
    def _cache_get(self, cache_key: str) -> Any:
        """
        Get value from cache with logging.
        
        Args:
            cache_key: Cache key to retrieve
            
        Returns:
            Cached value or None if not found
        """
        value = cache.get(cache_key)
        if value is not None:
            self.logger.debug(f"Cache hit for key: {cache_key}")
        else:
            self.logger.debug(f"Cache miss for key: {cache_key}")
        return value
    
    def _cache_set(self, cache_key: str, value: Any, timeout: Optional[int] = None) -> None:
        """
        Set value in cache with logging.
        
        Args:
            cache_key: Cache key to set
            value: Value to cache
            timeout: Cache timeout in seconds (uses default if None)
        """
        timeout = timeout or self.cache_timeout
        cache.set(cache_key, value, timeout)
        self.logger.debug(f"Cached value for key: {cache_key} (timeout: {timeout}s)")
    
    def _log_performance(self, operation: str, duration: float, **kwargs) -> None:
        """
        Log performance metrics for service operations.
        
        Args:
            operation: Name of the operation
            duration: Duration in seconds
            **kwargs: Additional context to log
        """
        context = " ".join(f"{k}={v}" for k, v in kwargs.items())
        self.logger.info(
            f"Performance: {operation} took {duration:.3f}s {context}"
        )
    
    def _handle_error(self, operation: str, error: Exception, **context) -> None:
        """
        Handle and log service errors consistently.
        
        Args:
            operation: Name of the operation that failed
            error: The exception that occurred
            **context: Additional context for the error
        """
        context_str = " ".join(f"{k}={v}" for k, v in context.items())
        self.logger.error(
            f"Error in {operation}: {str(error)} {context_str}",
            exc_info=True
        )
        
    def _validate_user_access(self, user) -> bool:
        """
        Validate that user has access to perform operations.
        
        Args:
            user: User object to validate
            
        Returns:
            True if user has access, False otherwise
        """
        if not user or not user.is_authenticated:
            self.logger.warning("Unauthenticated user attempted service access")
            return False
        
        if not hasattr(user, 'organization') or not user.organization:
            self.logger.warning(f"User {user.id} has no organization")
            return False
            
        return True