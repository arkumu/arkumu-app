"""
Harmonization Service Package

This package implements a semantic alignment layer on top of archive-specific data,
enabling unified queries across multiple archives with different schemas.

DEPRECATED: Most harmonization functionality has been replaced by canonical URIs.
Only the CatalogUriGenerator is still actively used.
"""

# Only import the still-active components
from .catalog_uri_generator import CatalogUriGenerator

# Other components are disabled pending migration to canonical URI system
# from .harmonization_service import HarmonizationService  # DISABLED
# from .alignment_generator import AlignmentGenerator        # DISABLED
# from .mapping_rules import RuleMatcher                     # DISABLED
# from .bulk_processor import HarmonizationBulkProcessor     # DISABLED
# from .conflict_resolver import ConflictResolver            # DISABLED

__all__ = [
    'CatalogUriGenerator',
]