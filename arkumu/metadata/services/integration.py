"""
Integration Layer Services

Functions for creating derived triples that link entities across archives.
These are system-generated triples that represent integration/federation
relationships rather than original archival data.

Includes canonical URI mapping services for harmonizing local resources
with Arkumu canonical ontology.
"""

import csv
from typing import Dict, List, Optional, Tuple
from django.db import transaction
from django.db.models import Q
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization
from arkumu.metadata.utils.rdf_helpers import get_or_create_resource


def create_sameas_link(entity1: Resource, entity2: Resource) -> Optional[Triple]:
    """
    Create a derived owl:sameAs triple linking two entities.
    
    This is used to indicate that two entities from different archives
    represent the same real-world object.
    
    Args:
        entity1: First entity resource
        entity2: Second entity resource
        
    Returns:
        Created Triple instance or None if creation failed
    """
    # Get or create the owl:sameAs property
    owl_sameas, _ = get_or_create_resource(
        uri='http://www.w3.org/2002/07/owl#sameAs',
        resource_type=ResourceType.PROPERTY,
        name='sameAs'
    )
    
    # Create the derived triple
    triple, created = Triple.objects.get_or_create(
        subject=entity1,
        predicate=owl_sameas,
        object=entity2,
        defaults={
            'source': None,  # No source - this is derived
            'is_derived': True
        }
    )
    
    return triple if created else None


def create_skos_mapping(concept1: Resource, concept2: Resource, 
                       mapping_type: str = 'exactMatch') -> Optional[Triple]:
    """
    Create a SKOS mapping relationship between concepts from different vocabularies.
    
    Args:
        concept1: First concept resource
        concept2: Second concept resource
        mapping_type: Type of SKOS mapping (exactMatch, closeMatch, broadMatch, etc.)
        
    Returns:
        Created Triple instance or None if creation failed
    """
    # Map of SKOS mapping properties
    skos_mappings = {
        'exactMatch': 'http://www.w3.org/2004/02/skos/core#exactMatch',
        'closeMatch': 'http://www.w3.org/2004/02/skos/core#closeMatch',
        'broadMatch': 'http://www.w3.org/2004/02/skos/core#broadMatch',
        'narrowMatch': 'http://www.w3.org/2004/02/skos/core#narrowMatch',
        'relatedMatch': 'http://www.w3.org/2004/02/skos/core#relatedMatch'
    }
    
    mapping_uri = skos_mappings.get(mapping_type)
    if not mapping_uri:
        raise ValueError(f"Invalid SKOS mapping type: {mapping_type}")
    
    # Get or create the SKOS mapping property
    skos_property, _ = get_or_create_resource(
        uri=mapping_uri,
        resource_type=ResourceType.PROPERTY,
        name=mapping_type
    )
    
    # Create the derived triple
    triple, created = Triple.objects.get_or_create(
        subject=concept1,
        predicate=skos_property,
        object=concept2,
        defaults={
            'source': None,
            'is_derived': True
        }
    )
    
    return triple if created else None


def link_to_external_authority(local_entity: Resource, 
                              authority_uri: str,
                              link_type: str = 'sameAs') -> Optional[Triple]:
    """
    Link a local entity to an external authority (e.g., Wikidata, VIAF, GND).
    
    Args:
        local_entity: Local entity resource
        authority_uri: URI of the external authority record
        link_type: Type of link (sameAs, seeAlso, etc.)
        
    Returns:
        Created Triple instance or None if creation failed
    """
    # Map of common linking properties
    link_properties = {
        'sameAs': 'http://www.w3.org/2002/07/owl#sameAs',
        'seeAlso': 'http://www.w3.org/2000/01/rdf-schema#seeAlso',
        'isDefinedBy': 'http://www.w3.org/2000/01/rdf-schema#isDefinedBy',
        'isPrimaryTopicOf': 'http://xmlns.com/foaf/0.1/isPrimaryTopicOf'
    }
    
    property_uri = link_properties.get(link_type)
    if not property_uri:
        raise ValueError(f"Invalid link type: {link_type}")
    
    # Get or create the linking property
    link_property, _ = get_or_create_resource(
        uri=property_uri,
        resource_type=ResourceType.PROPERTY,
        name=link_type
    )
    
    # Get or create the external authority resource
    authority_resource, _ = get_or_create_resource(
        uri=authority_uri,
        resource_type=ResourceType.IRI,
        name=authority_uri.split('/')[-1]  # Use last part of URI as name
    )
    
    # Create the derived triple
    triple, created = Triple.objects.get_or_create(
        subject=local_entity,
        predicate=link_property,
        object=authority_resource,
        defaults={
            'source': None,
            'is_derived': True
        }
    )
    
    return triple if created else None


# Canonical URI Mapping Services
class CanonicalUriMappingService:
    """
    Service for mapping canonical URIs to organizational resources.
    
    Processes CSV files that map resource names to canonical Arkumu URIs.
    Finds resources by exact name match and updates their canonical_uri field.
    """
    
    def __init__(self, organization_code: str):
        """Initialize service for specific organization."""
        try:
            self.organization = Organization.objects.get(code=organization_code)
        except Organization.DoesNotExist:
            raise ValueError(f"Organization with code '{organization_code}' not found")
    
    def process_canonical_mappings(self, csv_file_path: str, dry_run: bool = False) -> Dict[str, int]:
        """
        Process canonical URI mappings from CSV file.
        
        CSV Format:
        - Type: 'Class' or 'Property'
        - Target: Canonical URI to assign
        - Label: Human-readable label (informational only)
        - Name: Comma-separated resource names to find and update
        
        Args:
            csv_file_path: Path to mapping CSV file
            dry_run: Preview changes without applying
            
        Returns:
            Statistics dict with updated, not_found, skipped, errors counts
        """
        stats = {'updated': 0, 'not_found': [], 'skipped': 0, 'errors': 0}
        
        with open(csv_file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            with transaction.atomic():
                for row_num, row in enumerate(reader, 1):
                    try:
                        self._process_mapping_row(row, row_num, dry_run, stats)
                    except Exception as e:
                        print(f"Row {row_num}: Error - {e}")
                        stats['errors'] += 1
                
                if dry_run:
                    # Rollback transaction for dry run
                    transaction.set_rollback(True)
        
        return stats
    
    def _process_mapping_row(self, row: Dict[str, str], row_num: int, dry_run: bool, stats: Dict) -> None:
        """Process single CSV row for canonical URI mapping."""
        resource_type_str = row.get('Type', '').strip()
        canonical_uri = row.get('Target', '').strip()
        label = row.get('Label', '').strip()
        names_str = row.get('Name', '').strip()
        
        # Validate required fields
        if not resource_type_str or not canonical_uri:
            print(f"Row {row_num}: Missing Type or Target - skipping")
            stats['skipped'] += 1
            return
        
        if not names_str:
            # No names to process, skip silently
            return
        
        # Parse resource type
        resource_type = self._parse_resource_type(resource_type_str)
        if not resource_type:
            print(f"Row {row_num}: Invalid resource type '{resource_type_str}' - skipping")
            stats['skipped'] += 1
            return
        
        # Split names by comma and process each
        names = [name.strip() for name in names_str.split(',') if name.strip()]
        
        for name in names:
            matched_resources = self._locate_resources_by_name_or_uri(name, resource_type)

            if matched_resources:
                for resource in matched_resources:
                    if dry_run:
                        print(f"Row {row_num}: Would update {name} ({resource.uri}) → {canonical_uri}")
                    else:
                        old_canonical = resource.canonical_uri
                        resource.canonical_uri = canonical_uri
                        resource.save(update_fields=['canonical_uri'])

                        if old_canonical and old_canonical != canonical_uri:
                            print(f"Row {row_num}: Updated {name} (was: {old_canonical})")
                        else:
                            print(f"Row {row_num}: Updated {name} → {canonical_uri}")

                    stats['updated'] += 1
            else:
                print(f"Row {row_num}: Resource not found - Type: {resource_type_str}, Name: '{name}'")
                stats['not_found'].append(f"{resource_type_str}: {name}")

    def _locate_resources_by_name_or_uri(
        self,
        name: str,
        resource_type: ResourceType,
    ) -> List[Resource]:
        """Return resources matching the given name or inferred local URI."""

        resources = list(
            Resource.objects.filter(
                organization=self.organization,
                resource_type=resource_type,
                name=name,
                is_placeholder=False,
            )
        )

        if resources:
            return resources

        # Fall back to URI matching using slugified representation of the name
        from arkumu.common.uri_utils import slugify_uri_part

        slug = slugify_uri_part(name)
        if not slug:
            return []

        # Build candidate URI endings based on resource type
        uri_suffixes = [f"/{slug}"]
        # Allow hyphen/underscore variants commonly seen in historic mappings
        uri_suffixes.append(f"/{slug.replace('-', '_')}")

        query = Q(organization=self.organization, resource_type=resource_type, is_placeholder=False)
        uri_match_q = Q()
        for suffix in uri_suffixes:
            uri_match_q |= Q(uri__iendswith=suffix)

        if not uri_match_q:
            return []

        resources = list(Resource.objects.filter(query & uri_match_q))
        return resources
    
    def _parse_resource_type(self, type_str: str) -> Optional[ResourceType]:
        """Parse resource type string."""
        if not type_str:
            return None
            
        type_mapping = {
            'class': ResourceType.CLASS,
            'property': ResourceType.PROPERTY,
            'column': ResourceType.IRI  # Support for imported column resources
        }
        return type_mapping.get(type_str.lower())
    
    def get_unmapped_resources(self, resource_type: Optional[ResourceType] = None) -> List[Resource]:
        """Get resources without canonical URIs."""
        query = Resource.objects.filter(
            organization=self.organization,
            canonical_uri__isnull=True,
            is_placeholder=False
        )
        if resource_type:
            query = query.filter(resource_type=resource_type)
        return list(query)
    
    def validate_mapping_csv(self, csv_file_path: str) -> Tuple[bool, List[str]]:
        """Validate CSV format for canonical URI mapping."""
        errors = []
        
        try:
            with open(csv_file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
                
                # Check required columns
                required = ['Type', 'Target', 'Label', 'Name']
                missing = [col for col in required if col not in headers]
                if missing:
                    errors.append(f"Missing required columns: {', '.join(missing)}")
                
                # Validate first few rows
                for row_num, row in enumerate(reader, 1):
                    if row_num > 5:  # Only check first 5 rows
                        break
                    
                    resource_type = row.get('Type', '').strip().lower()
                    if resource_type and resource_type not in ['class', 'property']:
                        errors.append(f"Row {row_num}: Invalid Type '{resource_type}' (must be 'Class' or 'Property')")
                    
                    target = row.get('Target', '').strip()
                    if target and not target.startswith('http'):
                        errors.append(f"Row {row_num}: Target must be a valid HTTP URI")
        
        except Exception as e:
            errors.append(f"Error reading CSV: {e}")
        
        return len(errors) == 0, errors


def map_canonical_uris(organization_code: str, csv_file_path: str, 
                      dry_run: bool = False) -> Dict[str, int]:
    """
    Convenience function to map canonical URIs for an organization.
    
    Args:
        organization_code: Organization code (e.g., 'hfm', 'rsh')
        csv_file_path: Path to CSV with canonical mappings
        dry_run: Preview changes without applying
        
    Returns:
        Statistics dict with processing results
    """
    service = CanonicalUriMappingService(organization_code)
    return service.process_canonical_mappings(csv_file_path, dry_run)
