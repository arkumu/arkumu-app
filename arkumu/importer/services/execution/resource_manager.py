"""
Resource management for efficient URI generation and bulk operations.
"""

import logging
from typing import Dict, List, Any, Optional, Set, Tuple
from django.db import transaction
import polars as pl

from arkumu.metadata.models import Resource
from arkumu.metadata.models.resource import ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.common.uri_utils import mint_uri, slugify_uri_part
from arkumu.common.enums import LiteralURIStrategy
from .statistics import ExecutionStatistics

logger = logging.getLogger(__name__)


class ResourceManager:
    """
    Manages resource creation, URI generation, and bulk operations.
    
    Handles efficient creation of RDF resources and their relationships
    with optimized database operations and memory usage.
    """
    
    def __init__(self, 
                 organization,
                 base_uri: str,
                 statistics: Optional[ExecutionStatistics] = None):
        """
        Initialize the resource manager.
        
        Args:
            organization: Organization object for ownership tracking
            base_uri: Base URI for resource generation
            statistics: Optional statistics tracker
        """
        self.organization = organization
        self.institution = slugify_uri_part(str(organization.code)) if organization else "default"
        self.base_uri = base_uri
        self.statistics = statistics or ExecutionStatistics()
        
        # Initialize and cache standard RDF properties
        self._init_standard_properties()
    
    def _init_standard_properties(self) -> None:
        """Initialize standard RDF properties."""
        try:
            with transaction.atomic():
                self.has_part_prop, _ = Resource.objects.get_or_create(
                    uri="http://purl.org/dc/terms/hasPart",
                    defaults={
                        "resource_type": ResourceType.PROPERTY,
                        "name": "hasPart",
                        "is_placeholder": False,
                        "organization": self.organization
                    }
                )
                self.rdf_value_prop, _ = Resource.objects.get_or_create(
                    uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#value",
                    defaults={
                        "resource_type": ResourceType.PROPERTY,
                        "name": "value",
                        "is_placeholder": False,
                        "organization": self.organization
                    }
                )
                self.dcterms_relation_prop, _ = Resource.objects.get_or_create(
                    uri="http://purl.org/dc/terms/relation",
                    defaults={
                        "resource_type": ResourceType.PROPERTY,
                        "name": "relation",
                        "is_placeholder": False,
                        "organization": self.organization
                    }
                )
                self.is_part_of_prop, _ = Resource.objects.get_or_create(
                    uri="http://purl.org/dc/terms/isPartOf",
                    defaults={
                        "resource_type": ResourceType.PROPERTY,
                        "name": "isPartOf",
                        "is_placeholder": False,
                        "organization": self.organization
                    }
                )
                self.owl_same_as_prop, _ = Resource.objects.get_or_create(
                    uri="http://www.w3.org/2002/07/owl#sameAs",
                    defaults={
                        "resource_type": ResourceType.PROPERTY,
                        "name": "sameAs",
                        "is_placeholder": False,
                        "organization": None  # OWL properties are standard, no organization
                    }
                )
        except Exception as e:
            logger.error(f"Failed to initialize standard RDF properties: {e}", exc_info=True)
            self.has_part_prop = None
            self.rdf_value_prop = None
            self.dcterms_relation_prop = None
            self.is_part_of_prop = None
            self.owl_same_as_prop = None
    
    def generate_dataset_uri(self, dataset_name: str) -> str:
        """Generate URI for a dataset."""
        safe_dataset_name = slugify_uri_part(dataset_name)
        return mint_uri(self.base_uri, self.institution, "datasets", safe_dataset_name)
    
    def generate_column_uri(self, dataset_name: str, column_name: str) -> str:
        """Generate URI for a column."""
        safe_dataset_name = slugify_uri_part(dataset_name)
        safe_column_name = slugify_uri_part(column_name)
        return mint_uri(self.base_uri, self.institution, "datasets", safe_dataset_name, "columns", safe_column_name)
    
    def generate_row_uri(self, dataset_name: str, row_id: str) -> str:
        """Generate URI for a row."""
        safe_dataset_name = slugify_uri_part(dataset_name)
        safe_row_id = slugify_uri_part(str(row_id))
        return mint_uri(self.base_uri, self.institution, "datasets", safe_dataset_name, "rows", safe_row_id)
    
    def create_canonical_literal_uri(self, value: str, datatype: str = None, strategy: LiteralURIStrategy = LiteralURIStrategy.CANONICAL) -> str:
        """
        Generate canonical URI for literal values using Blake2b hash.
        
        Args:
            value: The literal value
            datatype: Optional datatype URI
            strategy: URI generation strategy
            
        Returns:
            Canonical URI for the literal
        """
        # Use centralized hash function for URI generation
        from arkumu.common.hash_utils import generate_uri_hash
        value_hash = generate_uri_hash(value, digest_size=8)
        
        if strategy == LiteralURIStrategy.SEMANTIC and datatype:
            # Extract simple type name from URI for semantic URIs
            type_name = datatype.split('/')[-1].split('#')[-1]
            type_slug = slugify_uri_part(type_name)
            return f"{self.base_uri}/literals/{type_slug}/{value_hash}"
        elif strategy == LiteralURIStrategy.CANONICAL:
            return f"{self.base_uri}/literals/{value_hash}"
        else:
            # Legacy contextual URIs (existing behavior with Blake2b)
            legacy_hash = generate_uri_hash(value, digest_size=4)
            value_identifier = f"{slugify_uri_part(value[:50])}-{legacy_hash}"
            return mint_uri(self.base_uri, self.institution, "values", value_identifier)
    
    
    
    
    def create_dataset_resource(self, dataset_name: str) -> Resource:
        """Create a dataset resource."""
        dataset_uri = self.generate_dataset_uri(dataset_name)
        logger.debug(f"Creating dataset resource with URI: {dataset_uri}")
        
        try:
            dataset_resource, created = Resource.objects.get_or_create(
                uri=dataset_uri,
                defaults={
                    "resource_type": ResourceType.IRI,
                    "name": dataset_name,
                    "organization": self.organization
                }
            )
            
            if created:
                self.statistics.increment_resources_created()
                logger.debug(f"Dataset resource created successfully: {dataset_uri}")
            else:
                logger.debug(f"Dataset resource already exists: {dataset_uri}")
            
            logger.debug(f"Current resources_created count: {self.statistics.current_metrics.resources_created}")
            return dataset_resource
            
        except Exception as e:
            logger.error(f"Failed to create dataset resource {dataset_uri}: {e}", exc_info=True)
            raise
    
    def create_column_resources(self, dataset_name: str, column_names: List[str]) -> Dict[str, Resource]:
        """Create column resources in bulk."""
        column_resources = {}
        
        for column_name in column_names:
            column_uri = self.generate_column_uri(dataset_name, column_name)
            column_resource, created = Resource.objects.get_or_create(
                uri=column_uri,
                defaults={
                    "resource_type": ResourceType.IRI,
                    "name": column_name,
                    "organization": self.organization
                }
            )
            if created:
                self.statistics.increment_resources_created()
            column_resources[column_name] = column_resource
        
        return column_resources
    
    def create_row_resources(self, dataset_name: str, row_ids: Set[str]) -> Dict[str, Resource]:
        """Create row resources in bulk."""
        row_resources = {}
        
        for row_id in row_ids:
            row_uri = self.generate_row_uri(dataset_name, row_id)
            row_resource, created = Resource.objects.get_or_create(
                uri=row_uri,
                defaults={
                    "resource_type": ResourceType.IRI,
                    "name": f"Row {row_id}",
                    "organization": self.organization
                }
            )
            if created:
                self.statistics.increment_resources_created()
            row_resources[row_id] = row_resource
        
        return row_resources
    
    
    def create_value_resources_bulk(self, values: List[Tuple[str, str]]) -> Dict[str, Resource]:
        """
        Create literal value resources in bulk.
        
        Args:
            values: List of (value, datatype) tuples
            
        Returns:
            Dictionary mapping values to resources
        """
        value_resources_to_create = []
        value_map = {}
        
        for value, datatype in values:
            if not value or not value.strip():
                continue
                
            # Generate URI and hash using full value (no truncation for storage)
            canonical_uri = self.create_canonical_literal_uri(value, datatype)
            from arkumu.common.hash_utils import generate_value_hash_and_normalize
            value_hash, normalized_value = generate_value_hash_and_normalize(value)
            
            value_resource = Resource(
                uri=canonical_uri,
                value=normalized_value,  # Store normalized value for consistent searching
                value_hash=value_hash,
                resource_type=ResourceType.LITERAL,
                name=normalized_value[:100] if len(normalized_value) > 100 else normalized_value,  # Only truncate display name
                datatype=datatype,
                language="de",  # Default to German language
                organization=None  # Literals have no organization
            )
            value_resources_to_create.append(value_resource)
            value_map[value] = value_resource
        
        if value_resources_to_create:
            Resource.objects.bulk_create(
                value_resources_to_create,
                ignore_conflicts=True,
                batch_size=500
            )
            self.statistics.increment_resources_created(len(value_resources_to_create))
        
        return value_map
    
    
    def create_structural_triples_bulk(self, 
                                     dataset_resource: Resource,
                                     column_resources: Dict[str, Resource],
                                     row_resources: Optional[Dict[str, Resource]] = None) -> List[Triple]:
        """
        Create structural triples (dataset→column, dataset→row, etc.).
        
        Args:
            dataset_resource: The dataset resource
            column_resources: Dictionary of column resources
            row_resources: Optional dictionary of row resources
            
        Returns:
            List of created triples
        """
        structural_triples = []
        
        # Dataset → hasPart → Column
        for column_resource in column_resources.values():
            structural_triples.append(
                Triple(subject=dataset_resource, predicate=self.has_part_prop, object=column_resource, 
                      source=self.organization, is_derived=False)
            )
        
        # Dataset → hasPart → Row (if row topology is enabled)
        if row_resources:
            for row_resource in row_resources.values():
                structural_triples.append(
                    Triple(subject=dataset_resource, predicate=self.has_part_prop, object=row_resource,
                          source=self.organization, is_derived=False)
                )
        
        if structural_triples:
            # # Count before bulk create
            # count_before = Triple.objects.count()
            Triple.objects.bulk_create(structural_triples, ignore_conflicts=True)
            # # Count after and update metrics with actual created count
            # count_after = Triple.objects.count()
            # actually_created = count_after - count_before
            # self.statistics.current_metrics.triples_created += actually_created
            self.statistics.current_metrics.triples_created += len(structural_triples)
        
        return structural_triples
    
    def create_value_triples_bulk(self, cell_value_pairs: List[Tuple[Resource, Resource]]) -> List[Triple]:
        """
        Create value triples (cell→rdf:value→literal).
        
        Args:
            cell_value_pairs: List of (cell_resource, value_resource) tuples
            
        Returns:
            List of created triples
        """
        value_triples = [
            Triple(subject=cell_resource, predicate=self.rdf_value_prop, object=value_resource,
                  source=self.organization, is_derived=False)
            for cell_resource, value_resource in cell_value_pairs
        ]
        
        if value_triples:
            # # Count before bulk create
            # count_before = Triple.objects.count()
            Triple.objects.bulk_create(value_triples, ignore_conflicts=True)
            # # Count after and update metrics with actual created count
            # count_after = Triple.objects.count()
            # actually_created = count_after - count_before
            # self.statistics.current_metrics.triples_created += actually_created
            self.statistics.current_metrics.triples_created += len(value_triples)
        
        return value_triples
    
    def get_existing_resources_bulk(self, uris: List[str]) -> Dict[str, Resource]:
        """Efficiently fetch existing resources for a list of URIs."""
        existing = Resource.objects.filter(uri__in=uris).select_related()
        return {resource.uri: resource for resource in existing}
    
    def generate_entity_uri(self, dataset_name: str, entity_id: str) -> str:
        """Generate URI for an entity."""
        safe_dataset_name = slugify_uri_part(dataset_name)
        safe_entity_id = slugify_uri_part(str(entity_id))
        return mint_uri(self.base_uri, self.institution, "entities", safe_dataset_name, safe_entity_id)
    
    def generate_junction_uri(self, dataset_name: str, primary_value: str, secondary_value: str) -> str:
        """Generate URI for a junction entity."""
        safe_dataset_name = slugify_uri_part(dataset_name)
        safe_primary = slugify_uri_part(str(primary_value))
        safe_secondary = slugify_uri_part(str(secondary_value))
        return mint_uri(self.base_uri, self.institution, "junctions", safe_dataset_name, 
                       f"{safe_primary}_{safe_secondary}")
    
    def create_entity_resource(self, entity_uri: str, dataset_name: str, is_stub: bool = False) -> Resource:
        """Create or get an entity resource."""
        try:
            with transaction.atomic():
                entity_id = entity_uri.split('/')[-1]
                entity_resource, created = Resource.objects.get_or_create(
                    uri=entity_uri,
                    defaults={
                        "resource_type": ResourceType.IRI,
                        "name": entity_id[:100] if len(entity_id) > 100 else entity_id,
                        "is_placeholder": is_stub,
                        "organization": self.organization
                    }
                )
                
                if created and self.statistics:
                    self.statistics.current_metrics.resources_created += 1
                    if is_stub:
                        self.statistics.current_metrics.stub_entities_created += 1
                
                return entity_resource
                
        except Exception as e:
            logger.error(f"Failed to create entity resource {entity_uri}: {e}")
            raise
    
    def create_external_resource(self, external_uri: str, ontology_type: str) -> Resource:
        """Create or get an external ontology resource."""
        try:
            with transaction.atomic():
                external_resource, created = Resource.objects.get_or_create(
                    uri=external_uri,
                    defaults={
                        "resource_type": ResourceType.IRI,
                        "name": external_uri.split('/')[-1],
                        "is_placeholder": False,
                        "organization": None  # External resources have no organization
                    }
                )
                
                if created and self.statistics:
                    self.statistics.current_metrics.resources_created += 1
                
                return external_resource
                
        except Exception as e:
            logger.error(f"Failed to create external resource {external_uri}: {e}")
            raise
    
    def create_property_triple(self, subject_resource: Resource, property_uri: str, 
                             object_value: str, datatype: str) -> Triple:
        """Create a property triple (subject -> property -> literal value)."""
        try:
            with transaction.atomic():
                # Create or get property resource
                property_resource, _ = Resource.objects.get_or_create(
                    uri=property_uri,
                    defaults={
                        "resource_type": ResourceType.PROPERTY,
                        "name": property_uri.split('/')[-1],
                        "is_placeholder": False,
                        "organization": self.organization
                    }
                )
                
                # Create value resource if needed
                # Generate URI first to ensure uniqueness across different datatypes
                canonical_uri = self.create_canonical_literal_uri(object_value, datatype)
                
                # Use hash-based uniqueness without source to enable deduplication across archives
                # and prevent PostgreSQL btree index size limitations
                from arkumu.common.hash_utils import generate_value_hash_and_normalize
                value_hash, normalized_value = generate_value_hash_and_normalize(object_value)
                
                value_resource, created = Resource.objects.get_or_create(
                    uri=canonical_uri,  # Use URI for primary uniqueness
                    defaults={
                        "value_hash": value_hash,
                        "language": "de",  # Default to German language
                        "datatype": datatype,
                        "name": normalized_value[:100],  # Truncate for name
                        "resource_type": ResourceType.LITERAL,
                        "value": normalized_value,  # Store normalized value for consistent searching
                        "is_placeholder": False,
                        "organization": None  # Literals have no organization
                    }
                )
                
                # Create the triple
                triple, created = Triple.objects.get_or_create(
                    subject=subject_resource,
                    predicate=property_resource,
                    object=value_resource,
                    source=self.organization,
                    defaults={"is_derived": False}
                )
                
                if created and self.statistics:
                    self.statistics.current_metrics.triples_created += 1
                
                return triple
                
        except Exception as e:
            logger.error(f"Failed to create property triple: {e}")
            raise
    
    def create_relationship_triple(self, subject_resource: Resource, property_uri: str, 
                                 object_resource: Resource) -> Triple:
        """Create a relationship triple (subject -> property -> object resource)."""
        try:
            with transaction.atomic():
                # Create or get property resource
                property_resource, _ = Resource.objects.get_or_create(
                    uri=property_uri,
                    defaults={
                        "resource_type": ResourceType.PROPERTY,
                        "name": property_uri.split('/')[-1],
                        "is_placeholder": False,
                        "organization": self.organization
                    }
                )
                
                # Create the triple
                triple, created = Triple.objects.get_or_create(
                    subject=subject_resource,
                    predicate=property_resource,
                    object=object_resource,
                    source=self.organization,
                    defaults={"is_derived": False}
                )
                
                if created and self.statistics:
                    self.statistics.current_metrics.triples_created += 1
                    self.statistics.current_metrics.relationships_created += 1
                
                return triple
                
        except Exception as e:
            logger.error(f"Failed to create relationship triple: {e}")
            raise
    
    def create_owl_same_as_triple(self, subject_resource: Resource, object_resource: Resource) -> Triple:
        """Create an owl:sameAs triple for external ontology hard linking."""
        try:
            with transaction.atomic():
                if not self.owl_same_as_prop:
                    logger.error("owl:sameAs property not initialized")
                    raise ValueError("owl:sameAs property not available")
                
                # Create the owl:sameAs triple (marked as derived for semantic linking)
                triple, created = Triple.objects.get_or_create(
                    subject=subject_resource,
                    predicate=self.owl_same_as_prop,
                    object=object_resource,
                    source=self.organization,
                    defaults={"is_derived": True}  # Mark as derived for semantic reasoning
                )
                
                if created and self.statistics:
                    self.statistics.current_metrics.triples_created += 1
                    self.statistics.current_metrics.relationships_created += 1
                
                return triple
                
        except Exception as e:
            logger.error(f"Failed to create owl:sameAs triple: {e}")
            raise
    
    def create_entity_resources_bulk(self, entity_data: List[Tuple[str, str]]) -> Dict[str, Resource]:
        """
        Create entity resources in bulk.
        
        Args:
            entity_data: List of (dataset_name, entity_id) tuples
            
        Returns:
            Dict mapping entity URIs to Resource objects
        """
        logger.debug(f"Creating {len(entity_data)} entity resources in bulk")
        
        entity_resources_to_create = []
        entity_uri_map = {}
        
        for dataset_name, entity_id in entity_data:
            entity_uri = self.generate_entity_uri(dataset_name, entity_id)
            
            # Skip if we've already processed this URI in this batch
            if entity_uri in entity_uri_map:
                continue
                
            entity_resource = Resource(
                uri=entity_uri,
                resource_type=ResourceType.IRI,
                name=entity_id[:100] if len(entity_id) > 100 else entity_id,  # Truncate name to fit DB constraint
                is_placeholder=False,
                organization=self.organization
            )
            entity_resources_to_create.append(entity_resource)
            entity_uri_map[entity_uri] = entity_resource
        
        if entity_resources_to_create:
            try:
                Resource.objects.bulk_create(
                    entity_resources_to_create,
                    ignore_conflicts=True,
                    batch_size=500
                )
                self.statistics.increment_resources_created(len(entity_resources_to_create))
                logger.debug(f"Successfully created {len(entity_resources_to_create)} entity resources")
            except Exception as e:
                logger.error(f"Failed to bulk create entity resources: {e}", exc_info=True)
                raise
        
        # Fetch the created resources with their database IDs
        try:
            created_resources = Resource.objects.filter(
                uri__in=[res.uri for res in entity_resources_to_create]
            )
            result = {res.uri: res for res in created_resources}
            
            # If no resources found in database (e.g., in tests with mocked objects),
            # return the in-memory resources we created
            if not result and entity_resources_to_create:
                logger.debug("No resources found in database, using in-memory resources for testing")
                result = entity_uri_map
            
            logger.debug(f"Retrieved {len(result)} entity resources from database")
            return result
        except Exception as e:
            logger.error(f"Failed to retrieve created entity resources: {e}", exc_info=True)
            raise
    
    def create_property_triples_bulk(self, property_data: List[Tuple[Resource, str, str]]) -> List[Triple]:
        """
        Create property triples for entities in bulk.
        
        Args:
            property_data: List of (entity_resource, property_uri, value) tuples
            
        Returns:
            List of created Triple objects
        """
        logger.debug(f"Creating {len(property_data)} property triples in bulk")
        
        if not property_data:
            return []
        
        # Collect unique property URIs and values
        property_uris = set()
        values_to_create = set()
        
        for entity_resource, property_uri, value in property_data:
            property_uris.add(property_uri)
            values_to_create.add(value)
        
        # Create property resources
        property_resources = {}
        property_resources_to_create = []
        
        for property_uri in property_uris:
            property_resource = Resource(
                uri=property_uri,
                resource_type=ResourceType.PROPERTY,
                name=property_uri.split('/')[-1],
                is_placeholder=False,
                organization=self.organization
            )
            property_resources_to_create.append(property_resource)
            property_resources[property_uri] = property_resource
        
        if property_resources_to_create:
            try:
                Resource.objects.bulk_create(
                    property_resources_to_create,
                    ignore_conflicts=True,
                    batch_size=500
                )
                # Refresh property resources from database
                created_properties = Resource.objects.filter(
                    uri__in=list(property_uris)
                )
                property_resources = {res.uri: res for res in created_properties}
            except Exception as e:
                logger.error(f"Failed to create property resources: {e}", exc_info=True)
                raise
        
        # Create value resources
        value_resources = {}
        value_resources_to_create = []
        
        for value in values_to_create:
            if not value or not value.strip():
                continue
                
            # Generate hash manually since bulk_create doesn't call save()
            from arkumu.common.hash_utils import generate_value_hash_and_normalize
            
            # Normalize once and get both hash and normalized value
            value_hash, normalized_value = generate_value_hash_and_normalize(value)
                
            value_resource = Resource(
                value=normalized_value,  # Store normalized value since bulk_create doesn't call save()
                value_hash=value_hash,  # Set hash manually for bulk_create
                resource_type=ResourceType.LITERAL,
                name=normalized_value[:100] if len(normalized_value) > 100 else normalized_value,  # Only truncate display name
                datatype="http://www.w3.org/2001/XMLSchema#string",
                language="de",  # Default to German language
                organization=None  # Literals have no organization
            )
            value_resources_to_create.append(value_resource)
            value_resources[value] = value_resource
        
        if value_resources_to_create:
            try:
                Resource.objects.bulk_create(
                    value_resources_to_create,
                    ignore_conflicts=True,
                    batch_size=500
                )
                self.statistics.increment_resources_created(len(value_resources_to_create))
            except Exception as e:
                logger.error(f"Failed to create value resources: {e}", exc_info=True)
                raise
        
        # Create the triples
        triples_to_create = []
        
        for entity_resource, property_uri, value in property_data:
            if not value or not value.strip():
                continue
                
            property_resource = property_resources.get(property_uri)
            value_resource = value_resources.get(value)
            
            if property_resource and value_resource:
                triple = Triple(
                    subject=entity_resource,
                    predicate=property_resource,
                    object=value_resource,
                    source=self.organization,
                    is_derived=False
                )
                triples_to_create.append(triple)
        
        if triples_to_create:
            try:
                # # Count before bulk create
                # count_before = Triple.objects.count()
                Triple.objects.bulk_create(
                    triples_to_create,
                    ignore_conflicts=True,
                    batch_size=500
                )
                # # Count after and update metrics with actual created count
                # count_after = Triple.objects.count()
                # actually_created = count_after - count_before
                # self.statistics.current_metrics.triples_created += actually_created
                self.statistics.current_metrics.triples_created += len(triples_to_create)
                logger.debug(f"Successfully created {len(triples_to_create)} property triples")
            except Exception as e:
                logger.error(f"Failed to create property triples: {e}", exc_info=True)
                raise
        
        return triples_to_create 

    def create_dataset_entity_links_bulk(self, entity_resources: List[Resource], dataset_resource: Resource) -> List[Triple]:
        """
        Create dataset-entity linking triples (entity → dcterms:isPartOf → dataset).
        
        Args:
            entity_resources: List of entity resources to link to the dataset
            dataset_resource: The dataset resource to link entities to
            
        Returns:
            List of created triples
        """
        if not entity_resources or not dataset_resource or not self.is_part_of_prop:
            return []
        
        dataset_entity_triples = []
        for entity_resource in entity_resources:
            dataset_entity_triples.append(
                Triple(
                    subject=entity_resource,
                    predicate=self.is_part_of_prop,
                    object=dataset_resource,
                    source=self.organization,
                    is_derived=False
                )
            )
        
        if dataset_entity_triples:
            try:
                # # Count before bulk create
                # count_before = Triple.objects.count()
                Triple.objects.bulk_create(dataset_entity_triples, ignore_conflicts=True)
                # # Count after and update metrics with actual created count
                # count_after = Triple.objects.count()
                # actually_created = count_after - count_before
                # self.statistics.current_metrics.triples_created += actually_created
                self.statistics.current_metrics.triples_created += len(dataset_entity_triples)
                logger.debug(f"Created {len(dataset_entity_triples)} dataset-entity linking triples")
            except Exception as e:
                logger.error(f"Failed to create dataset-entity linking triples: {e}", exc_info=True)
                raise
        
        return dataset_entity_triples