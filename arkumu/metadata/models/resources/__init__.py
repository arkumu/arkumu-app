"""
Resource wrapper classes for RDF-style entity management.
These classes provide a convenient interface for creating and managing
RDF resources with proper URI handling and relationship establishment.
"""

# Import all resource wrapper classes
from .base import BaseResource
from .class_resource import ClassResource
from .property import PropertyResource
from .entity import EntityResource
from .literal import LiteralResource

# Export the classes for easy importing
__all__ = [
    'BaseResource',
    'ClassResource',
    'PropertyResource',
    'EntityResource',
    'LiteralResource'
]
