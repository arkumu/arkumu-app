"""
Catalog services for business logic abstraction and code reuse.

This module contains service classes that handle the business logic 
for catalog operations, decoupling it from views and enabling reuse
between the catalog app and REST API.
"""

from .base import BaseService
from .search_service import SearchService
from .catalog_navigation_service import CatalogNavigationService
from .faceted_search_service import FacetedSearchService
from .flexible_catalog_service import FlexibleCatalogService

__all__ = [
    'BaseService',
    'SearchService',
    'CatalogNavigationService', 
    'FacetedSearchService',
    'FlexibleCatalogService',
]