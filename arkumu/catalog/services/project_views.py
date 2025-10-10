"""
Project View Services for Card and Detail Views

Provides CardView and ProjectView classes to extract literals from project data
based on the canonical URI mappings for different project properties and classes.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
import logging

from django.db.models import Q

from arkumu.metadata.models.triples import Triple
from arkumu.metadata.models.resource import Resource, ResourceType

logger = logging.getLogger(__name__)


# Canonical URI constants for Card View
class CardURIs:
    PROJECT_TYPE = "http://arkumu.org/data/types/projekt"
    TITLE = "http://arkumu.org/data/properties/bevorzugter-titel"
    SUBTITLE = "http://arkumu.org/data/properties/bevorzugter-untertitel"
    EVENT = "http://arkumu.org/data/properties/ereignis"
    IMAGE = "http://arkumu.org/data/properties/vorschaubild"
    INSTITUTION = "http://arkumu.org/data/properties/einliefernde-hochschule"
    CATEGORY = "http://arkumu.org/data/properties/projektkategorie"

    # Event type and properties
    EVENT_TYPE = "http://arkumu.org/data/types/ereignis"
    EVENT_START = "http://arkumu.org/data/properties/ereignisbeginn"
    EVENT_END = "http://arkumu.org/data/properties/ereignisende"

    # Actor-Event crosstable
    ACTOR_EVENT_TYPE = "http://arkumu.org/data/types/akteurin-ereignis-kreuztabelle"
    ACTOR_IN_EVENT = "http://arkumu.org/data/properties/akteurin-im-ereignis"
    ACTOR_ROLE = "http://arkumu.org/data/properties/rollen-der-akteurin-im-ereignis"

    # Actor and Role
    ACTOR_TYPE = "http://arkumu.org/data/types/akteurin"
    ACTOR_GERMAN_NAME = "http://arkumu.org/data/properties/deutscher-name"
    ROLE_TYPE = "http://arkumu.org/data/types/rolle"
    ROLE_GERMAN_NAME = "http://arkumu.org/data/properties/deutscher-name-der-rolle-breadcrumb"

    # Digital Object
    DIGITAL_OBJECT_TYPE = "http://arkumu.org/data/types/digitales-objekt"
    DIGITAL_OBJECT_LINK = "http://arkumu.org/data/properties/digitales-objekt"
    DIGITAL_OBJECT_PATH = "http://arkumu.org/data/properties/dateipfad"

    # Institution
    INSTITUTION_TYPE = "http://arkumu.org/data/types/einliefernde-hochschule"
    INSTITUTION_GERMAN_NAME = "http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule"

    # Project Category
    CATEGORY_TYPE = "http://arkumu.org/data/types/projektkategorie"
    CATEGORY_GERMAN_NAME = "http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb"
    CATEGORY_SYNONYMS = "http://arkumu.org/data/properties/synonyme"
    CATEGORY_WIKIDATA_ID = "http://arkumu.org/data/properties/wikidata-id"


# Additional URI constants for Project View (extends Card)
class ProjectURIs(CardURIs):
    PROJECT_TYPE_FUK = "http://arkumu.org/data/fuk/types/projekt"
    ALTERNATIVE_TITLE = "http://arkumu.org/data/fuk/properties/alternativer-titel-set"
    DESCRIPTION = "http://arkumu.org/data/properties/beschreibung"
    CATCHPHRASE = "http://arkumu.org/data/properties/schlagwort"
    PROJECT_TYPE_FIELD = "http://arkumu.org/data/properties/projektart"
    EVENT_NAME = "http://arkumu.org/data/properties/ereignisname"
    EVENT_DESCRIPTION = "http://arkumu.org/data/properties/ereignisbeschreibung"
    EVENT_LOCATION = "http://arkumu.org/data/properties/ereignisort"
    EVENT_LOCATION_WIKIDATA = "http://arkumu.org/data/properties/wikidata-id"
    EVENT_TYPE = "http://arkumu.org/data/properties/ereignistyp"

    # Alternative Title
    ALTERNATIVE_TITLE_TYPE = "http://arkumu.org/data/types/alternativer-titel"
    ALTERNATIVE_TITLE_VALUE = "http://arkumu.org/data/properties/alternativer-titel"

    # Catchphrase/Keyword
    CATCHPHRASE_TYPE = "http://arkumu.org/data/types/schlagwort"
    CATCHPHRASE_WIKIDATA = "http://arkumu.org/data/properties/deutsches-wikidata-label"


@dataclass
class CardData:
    """Data structure for card view"""
    uri: str
    title: Optional[str] = None
    subtitle: Optional[str] = None
    image: Optional[str] = None
    institution: str = ""
    event_start: Optional[str] = None
    event_end: Optional[str] = None
    categories: List[str] = None
    actors: List[Dict[str, str]] = None  # [{'name': str, 'roles': [str]}]

    def __post_init__(self):
        if self.categories is None:
            self.categories = []
        if self.actors is None:
            self.actors = []


@dataclass
class ProjectData(CardData):
    """Extended data structure for project detail view"""
    alternative_titles: List[str] = None
    description: Optional[str] = None
    catchphrases: List[str] = None
    project_type: Optional[str] = None
    digital_objects: List[str] = None  # File paths
    events: List[Dict[str, Any]] = None  # Event details

    def __post_init__(self):
        super().__post_init__()
        if self.alternative_titles is None:
            self.alternative_titles = []
        if self.catchphrases is None:
            self.catchphrases = []
        if self.digital_objects is None:
            self.digital_objects = []
        if self.events is None:
            self.events = []


class BaseProjectView:
    """Base class for project data extraction"""

    def __init__(self, project_uri: str):
        self.project_uri = project_uri
        self.project_resource = self._get_project_resource()

    def _get_project_resource(self) -> Optional[Resource]:
        """Get the project resource by URI"""
        try:
            return Resource.objects.get(uri=self.project_uri)
        except Resource.DoesNotExist:
            logger.error(f"Project resource not found: {self.project_uri}")
            return None

    def _get_literal_value(self, subject_uri: str, predicate_uri: str) -> Optional[str]:
        """Get literal value for a property using canonical URI"""
        try:
            predicate_filter = Q(predicate__canonical_uri=predicate_uri) | Q(
                predicate__uri=predicate_uri
            )
            triple = (
                Triple.objects.filter(
                    subject__uri=subject_uri,
                    object__resource_type=ResourceType.LITERAL,
                )
                .filter(predicate_filter)
                .first()
            )

            if triple and triple.object and hasattr(triple.object, 'literal_value'):
                logger.info(f"Found literal: {subject_uri} -> {predicate_uri} = '{triple.object.literal_value}'")
                return triple.object.literal_value
            else:
                logger.warning(f"No literal found: {subject_uri} -> {predicate_uri}")
                return None
        except Exception as e:
            logger.error(f"Error getting literal for {subject_uri} -> {predicate_uri}: {e}")
            return None

    def _get_related_resource_uri(self, subject_uri: str, predicate_uri: str) -> Optional[str]:
        """Get URI of related resource using canonical URI"""
        try:
            predicate_filter = Q(predicate__canonical_uri=predicate_uri) | Q(
                predicate__uri=predicate_uri
            )
            triple = (
                Triple.objects.filter(
                    subject__uri=subject_uri,
                    object__resource_type__in=[
                        ResourceType.CLASS,
                        ResourceType.PROPERTY,
                        ResourceType.ENTITY,
                    ],
                )
                .filter(predicate_filter)
                .first()
            )
            return triple.object.uri if triple and triple.object else None
        except Exception as e:
            logger.error(f"Error getting related resource for {subject_uri} -> {predicate_uri}: {e}")
            return None

    def _get_multiple_literal_values(self, subject_uri: str, predicate_uri: str) -> List[str]:
        """Get multiple literal values for a property using canonical URI"""
        try:
            predicate_filter = Q(predicate__canonical_uri=predicate_uri) | Q(
                predicate__uri=predicate_uri
            )
            triples = Triple.objects.filter(
                subject__uri=subject_uri,
                object__resource_type=ResourceType.LITERAL
            ).filter(predicate_filter)
            return [t.object.literal_value for t in triples if t.object and hasattr(t.object, 'literal_value') and t.object.literal_value]
        except Exception as e:
            logger.error(f"Error getting multiple literals for {subject_uri} -> {predicate_uri}: {e}")
            return []

    def _get_multiple_related_resource_uris(self, subject_uri: str, predicate_uri: str) -> List[str]:
        """Get URIs of multiple related resources using canonical URI"""
        try:
            predicate_filter = Q(predicate__canonical_uri=predicate_uri) | Q(
                predicate__uri=predicate_uri
            )
            triples = Triple.objects.filter(
                subject__uri=subject_uri,
                object__resource_type__in=[
                    ResourceType.CLASS,
                    ResourceType.PROPERTY,
                    ResourceType.ENTITY,
                ],
            ).filter(predicate_filter)
            return [t.object.uri for t in triples if t.object]
        except Exception as e:
            logger.error(f"Error getting multiple related resources for {subject_uri} -> {predicate_uri}: {e}")
            return []


class CardView(BaseProjectView):
    """Extract data for card view display"""

    def get_card_data(self) -> Optional[CardData]:
        """Extract all card view data"""
        if not self.project_resource:
            logger.error(f"No project resource found for URI: {self.project_uri}")
            return None

        logger.info(f"Extracting card data for project: {self.project_uri}")
        card_data = CardData(uri=self.project_uri)

        # Basic project properties
        logger.info("Extracting basic properties...")
        card_data.title = self._get_literal_value(self.project_uri, CardURIs.TITLE)
        card_data.subtitle = self._get_literal_value(self.project_uri, CardURIs.SUBTITLE)
        card_data.image = self._get_literal_value(self.project_uri, CardURIs.IMAGE)

        logger.info(f"Basic properties - Title: '{card_data.title}', Subtitle: '{card_data.subtitle}', Image: '{card_data.image}'")

        # Institution
        institution_uri = self._get_related_resource_uri(self.project_uri, CardURIs.INSTITUTION)
        if institution_uri:
            card_data.institution = self._get_literal_value(institution_uri, CardURIs.INSTITUTION_GERMAN_NAME) or ""

        # Event and dates
        event_uri = self._get_related_resource_uri(self.project_uri, CardURIs.EVENT)
        if event_uri:
            card_data.event_start = self._get_literal_value(event_uri, CardURIs.EVENT_START)
            card_data.event_end = self._get_literal_value(event_uri, CardURIs.EVENT_END)

            # Get actors from event
            card_data.actors = self._get_actors_from_event(event_uri)

        # Categories
        category_uris = self._get_multiple_related_resource_uris(self.project_uri, CardURIs.CATEGORY)
        for category_uri in category_uris:
            category_name = self._get_literal_value(category_uri, CardURIs.CATEGORY_GERMAN_NAME)
            if category_name:
                # Extract final part after '>' if breadcrumb format
                if '>' in category_name:
                    category_name = category_name.split('>')[-1].strip()
                card_data.categories.append(category_name)

        return card_data

    def _get_actors_from_event(self, event_uri: str) -> List[Dict[str, Any]]:
        """Get actors and their roles from an event"""
        actors = []

        # Find actor-event crosstable entries
        crosstable_triples = Triple.objects.filter(
            predicate__canonical_uri=CardURIs.EVENT,
            object__uri=event_uri,
            object__resource_type=ResourceType.ENTITY
        )

        for triple in crosstable_triples:
            crosstable_uri = triple.subject.uri

            # Get actor from crosstable
            actor_uri = self._get_related_resource_uri(crosstable_uri, CardURIs.ACTOR_IN_EVENT)
            if actor_uri:
                actor_name = self._get_literal_value(actor_uri, CardURIs.ACTOR_GERMAN_NAME)

                if actor_name:
                    # Get roles for this actor
                    role_uris = self._get_multiple_related_resource_uris(crosstable_uri, CardURIs.ACTOR_ROLE)
                    roles = []

                    for role_uri in role_uris:
                        role_name = self._get_literal_value(role_uri, CardURIs.ROLE_GERMAN_NAME)
                        if role_name:
                            # Extract final part after '>' if breadcrumb format
                            if '>' in role_name:
                                role_name = role_name.split('>')[-1].strip()
                            roles.append(role_name)

                    actors.append({
                        'name': actor_name,
                        'roles': roles
                    })

        return actors


class ProjectView(CardView):
    """Extract data for detailed project view"""

    def get_project_data(self) -> Optional[ProjectData]:
        """Extract all project view data (extends card data)"""
        card_data = self.get_card_data()
        if not card_data:
            return None

        # Convert CardData to ProjectData
        project_data = ProjectData(
            uri=card_data.uri,
            title=card_data.title,
            subtitle=card_data.subtitle,
            image=card_data.image,
            institution=card_data.institution,
            event_start=card_data.event_start,
            event_end=card_data.event_end,
            categories=card_data.categories,
            actors=card_data.actors
        )

        # Additional project-specific properties
        project_data.description = self._get_literal_value(self.project_uri, ProjectURIs.DESCRIPTION)

        # Get project type using proper resolution (not raw ID)
        from arkumu.catalog.services.triple_relationship_service import TripleRelationshipService
        triple_service = TripleRelationshipService(organization_code=None)
        project_data.project_type = triple_service.get_project_type(
            str(self.project_resource.id),
            project_type_predicate='http://arkumu.org/data/properties/projektart',
            organization_code=None,
        ) or self._get_literal_value(self.project_uri, ProjectURIs.PROJECT_TYPE_FIELD)  # Fallback to raw value

        # Alternative titles (from related resources)
        alt_title_uris = self._get_multiple_related_resource_uris(self.project_uri, ProjectURIs.ALTERNATIVE_TITLE)
        for alt_title_uri in alt_title_uris:
            alt_title = self._get_literal_value(alt_title_uri, ProjectURIs.ALTERNATIVE_TITLE_VALUE)
            if alt_title:
                project_data.alternative_titles.append(alt_title)

        # Catchphrases/Keywords (can be both literal values and from related resources)
        # Direct literal catchphrases
        direct_catchphrases = self._get_multiple_literal_values(self.project_uri, ProjectURIs.CATCHPHRASE)
        project_data.catchphrases.extend(direct_catchphrases)

        # Catchphrases from related resources
        catchphrase_uris = self._get_multiple_related_resource_uris(self.project_uri, ProjectURIs.CATCHPHRASE)
        for catchphrase_uri in catchphrase_uris:
            # Try wikidata label first
            wikidata_label = self._get_literal_value(catchphrase_uri, ProjectURIs.CATCHPHRASE_WIKIDATA)
            if wikidata_label:
                project_data.catchphrases.append(wikidata_label)

        # Digital objects
        digital_object_uris = self._get_multiple_related_resource_uris(
            self.project_uri,
            ProjectURIs.DIGITAL_OBJECT_LINK,
        )
        for obj_uri in digital_object_uris:
            file_path = self._get_literal_value(obj_uri, ProjectURIs.DIGITAL_OBJECT_PATH)
            if file_path:
                project_data.digital_objects.append(file_path)

        return project_data


def get_card_view_data(project_uri: str) -> Optional[CardData]:
    """Convenience function to get card view data"""
    view = CardView(project_uri)
    return view.get_card_data()


def get_project_view_data(project_uri: str) -> Optional[ProjectData]:
    """Convenience function to get project view data"""
    view = ProjectView(project_uri)
    return view.get_project_data()
