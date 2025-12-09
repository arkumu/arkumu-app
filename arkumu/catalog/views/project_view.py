"""Project detail view.

In snapshot-backed mode, this view uses ProjectSnapshotService to load a
ProjectRecord for the requested URI. In graph-backed mode (when
PROJECT_INDEX_BACKEND is set to 'graph'), it falls back to the lighter
triple-based ProjectView service from arkumu.catalog.services.project_views
to avoid rebuilding the full cross-institutional snapshot.
"""
import json
import uuid
from functools import singledispatchmethod

from django.views.generic import View
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.http import HttpResponseBadRequest, HttpResponseNotFound
from django.conf import settings
import logging
from typing import Any, Dict, List, Optional, Sequence, Mapping, Tuple

from arkumu.catalog.models import PreviewImages, ProjectDetailIndex
from arkumu.catalog.services.wikidata_service import WikidataService
from arkumu.catalog.services.project_views import get_project_view_data
from arkumu.catalog.services.project_detail_loader import ProjectDetailLoader
from arkumu.metadata.models import Resource, Triple, ResourceType
from arkumu.projects import ProjectEvent, ProjectRecord
from arkumu.projects.services import ProjectSnapshotService
from arkumu.catalog.services.project_detail_index_service import ProjectDetailIndexService
from arkumu.catalog.services import ProjectIndexService

logger = logging.getLogger(__name__)


# Copy from arkumu-app/arkumu/catalog/views.py. You may need to remove the file.
class Entity:
    @singledispatchmethod
    def __init__(self, arg):
        raise NotImplementedError("Not implemented for these arguments")

    @__init__.register
    def _(self, arg: Resource):
        self.uri = arg.uri
        self.init_helper(arg.id)

    @__init__.register
    def _(self, arg: Triple):
        self.uri = Resource.objects.get(id=arg.subject_id).uri
        self.init_helper(arg.subject_id)

    @__init__.register
    def _(self, arg: str):
        self.uri = arg
        subject = Resource.objects.get(uri=arg)
        self.init_helper(subject.id)

    @__init__.register
    def _(self, arg: uuid.UUID):
        self.uri = Resource.objects.get(id=arg).uri
        self.init_helper(arg)

    def init_helper(self, subject_id):
        self.id = subject_id
        self.name = Resource.objects.get(id=subject_id).name
        self.resources = {}
        for entity_field_triple in Triple.objects.filter(subject_id=subject_id):
            if Resource.objects.get(id=entity_field_triple.predicate_id).name not in self.resources:
                self.resources[Resource.objects.get(id=entity_field_triple.predicate_id).name] = [
                    Resource.objects.get(id=entity_field_triple.object_id)]
            else:
                self.resources[Resource.objects.get(id=entity_field_triple.predicate_id).name].append(
                    Resource.objects.get(id=entity_field_triple.object_id))
        self.properties = {}
        for entity_field_triple in Triple.objects.filter(subject_id=subject_id):
            if Resource.objects.get(id=entity_field_triple.predicate_id).name not in self.properties:
                self.properties[Resource.objects.get(id=entity_field_triple.predicate_id).name] = [
                    Resource.objects.get(id=entity_field_triple.predicate_id)]
            else:
                self.properties[Resource.objects.get(id=entity_field_triple.predicate_id).name].append(
                    Resource.objects.get(id=entity_field_triple.predicate_id))
        self.field_names = []
        for entity_field_triple in Triple.objects.filter(subject_id=subject_id):
            if Resource.objects.get(id=entity_field_triple.predicate_id).name not in self.field_names:
                self.field_names.append(Resource.objects.get(id=entity_field_triple.predicate_id).name)

    def __repr__(self):
        ret = {field_name: [resource.value for resource in self.resources[field_name]] if self.resources[field_name][
                                                                                              0].resource_type == ResourceType.LITERAL else [
            resource.uri for resource in self.resources[field_name]] for field_name in self.field_names}
        return f"Entity with id: {self.id} \nvalues: {ret}"

class ProjectView(LoginRequiredMixin, View):
    """Render a single project using the shared snapshot."""

    snapshot_service_class = ProjectSnapshotService
    detail_service_class = ProjectDetailIndexService

    # Canonical URI mappings for metadata sections
    # Format: (field_key, display_label, canonical_uri)
    ALLGEMEIN_CANONICAL: Sequence[Tuple[str, str, str]] = (
        ("kommentar_de", "Kommentar DE", "http://arkumu.org/data/properties/deutscher-kommentar"),
        ("kommentar_en", "Kommentar EN", "http://arkumu.org/data/properties/englischer-kommentar"),
        ("sprache_titel", "Sprache Titel", "http://arkumu.org/data/properties/sprache-des-bevorzugten-titels"),
        ("sprache_untertitel", "Sprache Untertitel", "http://arkumu.org/data/properties/sprache-des-bevorzugten-untertitels"),
    )

    EIGENSCHAFTEN_CANONICAL: Sequence[Tuple[str, str, str]] = (
        ("dauer_hms", "Dauer (HH:MM:SS)", "http://arkumu.org/data/properties/dauer-hms"),
        ("dauer_freitext", "Dauer (Freitext)", "http://arkumu.org/data/properties/dauer-freitext"),
        ("tonarten", "Tonarten", "http://arkumu.org/data/properties/tonart"),
        ("produktionsformat", "Produktionsformat", "http://arkumu.org/data/properties/produktionsformat"),
        ("instrumentierung", "Instrumentierung", "http://arkumu.org/data/properties/instrumentierung"),
        ("aspect_ratio", "Bildseitenverhältnis", "http://arkumu.org/data/properties/aspect-ratio-bildseitenverhaeltnis"),
        ("stimmung_hz", "Stimmung (Hz)", "http://arkumu.org/data/properties/stimmung-hz"),
        ("sprachen", "Sprachen", "http://arkumu.org/data/properties/originalsprache"),
        ("abspielgeschwindigkeit", "Abspielgeschwindigkeit", "http://arkumu.org/data/properties/abspielgeschwindigkeit"),
        ("equalizer", "Equalizer", "http://arkumu.org/data/properties/equalizer"),
        ("bandbreite", "Bandbreite", "http://arkumu.org/data/properties/bandbreite"),
        ("tonaufnahme", "Tonaufnahme", "http://arkumu.org/data/properties/tonaufnahme"),
        ("werkverzeichnis", "Werkverzeichnis", "http://arkumu.org/data/properties/werkverzeichnis"),
        ("musikgattungen", "Musikgattungen", "http://arkumu.org/data/properties/musikgattung"),
        ("tonformate", "Tonformate", "http://arkumu.org/data/properties/tonformat"),
        ("bildfrequenz", "Bildfrequenz", "http://arkumu.org/data/properties/bildfrequenz"),
        ("filmentwicklung", "Filmentwicklung", "http://arkumu.org/data/properties/filmentwicklung"),
        ("tonmischfassungen", "Tonmischfassungen", "http://arkumu.org/data/properties/tonmischfassung"),
        ("fernsehnorm", "Fernsehnorm", "http://arkumu.org/data/properties/fernsehnorm"),
        ("spurausrichtung", "Spurausrichtung", "http://arkumu.org/data/properties/spurausrichtung"),
        ("ton_kanaele", "Tonkanäle", "http://arkumu.org/data/properties/ton-kanaele"),
        ("audio_aufnahmetechnik", "Audio-Aufnahmetechnik", "http://arkumu.org/data/properties/audio-aufnahmetechnik"),
    )

    STATUS_CANONICAL: Sequence[Tuple[str, str, str]] = (
        ("signatur", "Signatur", "http://arkumu.org/data/properties/signatur"),
        ("signatur_beim_einlieferer", "Signatur beim Einlieferer", "http://arkumu.org/data/properties/signatur-beim-einlieferer"),
        ("werkverzeichnis_nummer", "Werkverzeichnisnummer", "http://arkumu.org/data/properties/werkverzeichnis-nummer"),
    )

    NORMDATEN_CANONICAL: Sequence[Tuple[str, str, str]] = (
        ("wikidata_ids", "Wikidata ID", "http://arkumu.org/data/properties/wikidata-id"),
        ("gnd_ids", "GND ID", "http://arkumu.org/data/properties/gnd-nummer"),
        ("viaf_ids", "VIAF ID", "http://arkumu.org/data/properties/viaf-id"),
        ("aat_ids", "AAT ID", "http://arkumu.org/data/properties/aat-id"),
        ("weitere_normdaten", "Weitere Normdaten", "http://arkumu.org/data/properties/andere-normdaten"),
        ("externe_webseiten", "Externe Projekt Webseiten", "http://arkumu.org/data/properties/externe-projektwebseite"),
    )

    ERSTELLER_CANONICAL: Sequence[Tuple[str, str, str]] = (
        ("hochschule", "Hochschule", "http://arkumu.org/data/properties/einliefernde-hochschule"),
        ("organisationseinheit", "Organisationseinheit", "http://arkumu.org/data/properties/organisationseinheit"),
        ("erstellungsdatum", "Erstellungsdatum beim Einlieferer", "http://arkumu.org/data/properties/projekterstellung-beim-einlieferer"),
        ("letzte_modifikation", "Letzte Projektmodifikation beim Einlieferer", "http://arkumu.org/data/properties/letzte-projektmodifikation-beim-einlieferer"),
    )

    KATEGORISIERUNG_CANONICAL: Sequence[Tuple[str, str, str]] = (
        ("projektkategorien", "Projektkategorien", "http://arkumu.org/data/properties/projektkategorie"),
        ("schlagworte", "Schlagworte", "http://arkumu.org/data/properties/schlagwort"),
    )

    RECHTE_CANONICAL: Sequence[Tuple[str, str, str]] = (
        ("rechtsstatus", "Rechtsstatus", "http://arkumu.org/data/properties/rechtsstatus"),
        ("art_lizenzvertrag", "Art des Lizenzvertrages", "http://arkumu.org/data/properties/art-des-lizenzvertrages"),
        ("bestehender_lizenzvertrag", "Bestehender Lizenzvertrag", "http://arkumu.org/data/properties/bestehender-lizenzvertrag"),
        ("neuer_lizenzvertrag", "Neuer Lizenzvertrag (Digi-Kunst-Formular)", "http://arkumu.org/data/properties/neuer-lizenzvertrag-digi-kunst-formular"),
        ("angegebene_nutzungsrechte", "Angegebene Nutzungsrechte", "http://arkumu.org/data/properties/angegebene-nutzungsrechte"),
        ("sonderregelung", "Sonderregelung", "http://arkumu.org/data/properties/sonderregelung"),
        ("weitere_rechtsdokumente", "Weitere Rechtsdokumente", "http://arkumu.org/data/properties/weiteres-rechtsdokument"),
        ("dateiabfrage_dokument", "Dateiabfrage-Dokument", "http://arkumu.org/data/properties/dateiabfragedokument"),
    )

    RELATION_CANONICAL: Sequence[Tuple[str, str, str]] = (
        ("ist_teil_von", "Ist Teil von", "http://arkumu.org/data/properties/projekt-ist-teil-von"),
        ("hat_teil", "Hat Teil", "http://arkumu.org/data/properties/projekt-hat-teil"),
        ("basiert_auf", "Basiert auf", "http://arkumu.org/data/properties/projekt-basiert-auf"),
        ("hat_bezug_zu", "Hat Bezug zu", "http://arkumu.org/data/properties/projekt-hat-bezug-zu"),
        ("ist_vorbereitend_fuer", "Ist vorbereitend für", "http://arkumu.org/data/properties/projekt-ist-vorbereitend-fuer"),
    )

    # Legacy field mappings for backward compatibility with dataclass properties
    PROPERTY_METADATA_FIELDS: Sequence[Tuple[str, str]] = (
        ("dauer_hms", "Dauer (HH:MM:SS)"),
        ("dauer_freitext", "Dauer (Freitext)"),
        ("tonarten", "Tonarten"),
        ("produktionsformat", "Produktionsformat"),
        ("instrumentierung", "Instrumentierung"),
        ("aspect_ratio", "Bildseitenverhältnis"),
        ("stimmung_hz", "Stimmung (Hz)"),
        ("sprachen", "Sprachen"),
        ("abspielgeschwindigkeit", "Abspielgeschwindigkeit"),
        ("equalizer", "Equalizer"),
        ("bandbreite", "Bandbreite"),
        ("tonaufnahme", "Tonaufnahme"),
        ("werkverzeichnis", "Werkverzeichnis"),
        ("musikgattungen", "Musikgattungen"),
        ("tonformate", "Tonformate"),
        ("bildfrequenz", "Bildfrequenz"),
        ("filmentwicklung", "Filmentwicklung"),
        ("tonmischfassungen", "Tonmischfassungen"),
        ("fernsehnorm", "Fernsehnorm"),
        ("spurausrichtung", "Spurausrichtung"),
        ("ton_kanaele", "Tonkanäle"),
        ("audio_aufnahmetechnik", "Audio-Aufnahmetechnik"),
    )
    STATUS_METADATA_FIELDS: Sequence[Tuple[str, str]] = (
        ("signatur", "Signatur"),
        ("signatur_beim_einlieferer", "Signatur beim Einlieferer"),
        ("werkverzeichnis_nummer", "Werkverzeichnisnummer"),
    )
    AUTHORITY_METADATA_FIELDS: Sequence[Tuple[str, str]] = (
        ("wikidata_ids", "Wikidata IDs"),
        ("gnd_ids", "GND IDs"),
        ("weitere_normdaten", "Weitere Normdaten"),
        ("externe_webseiten", "Externe Webseiten"),
    )
    SUBMITTER_METADATA_FIELDS: Sequence[Tuple[str, str]] = (
        ("hochschule", "Einliefernde Hochschule"),
        ("hochschule_uri", "Hochschul-URI"),
        ("organisationseinheiten", "Organisationseinheiten"),
        ("erstellungsdatum", "Erstellungsdatum"),
        ("letzte_modifikation", "Letzte Modifikation"),
    )
    LICENSE_METADATA_FIELDS: Sequence[Tuple[str, str]] = (
        ("bestehende_vertraege", "Bestehende Verträge"),
        ("neuer_lizenzvertrag", "Neuer Lizenzvertrag"),
        ("angegebene_nutzungsrechte", "Angegebene Nutzungsrechte"),
        ("sonderregelungen", "Sonderregelungen"),
        ("weitere_rechtsdokumente", "Weitere Rechtsdokumente"),
        ("dateiabfrage_dokument", "Dateiabfrage (Dokument)"),
    )

    def get(self, request, *args, **kwargs):
        projekt_uri = request.GET.get('projekt')
        if not projekt_uri:
            logger.error("ProjectView: missing 'projekt' query parameter")
            return self._render_error(request, 'No project URI provided')

        backend = self._backend()

        # For db/graph backends, prefer ProjectDetailIndex for fast structured access
        if backend in ("db", "graph"):
            detail_entry = self._load_detail_from_index(projekt_uri)
            if detail_entry:
                project_context = detail_entry.to_view_context()
                metadata = self._build_metadata_from_detail_index(detail_entry)
                context = {
                    'project': project_context,
                    'metadata': metadata,
                    'tab_endpoint': reverse('catalog:projekt_tab'),
                }
                logger.info("ProjectView: served via ProjectDetailIndex (project_found=True)")
                return render(request, 'catalog/projekt.html', context)

        # Fallback to ProjectRecord for non-db backends or missing detail index
        try:
            if backend == "db":
                record = self._load_record_from_index(projekt_uri)
            else:
                record = self._load_record(projekt_uri)
        except LookupError:
            logger.warning("ProjectView: project not found via backend '%s': %s", backend, projekt_uri)
            return self._render_error(request, f'Project not found: {projekt_uri}')
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("ProjectView: error loading project %s", projekt_uri)
            return self._render_error(request, f'Error loading project: {exc}')

        project_context = self._build_context(record)
        metadata = self._build_metadata(record)
        self._log_project_record_debug(record, project_context, metadata)

        logger.debug(
            "ProjectView: resolved project %s with institution_codes=%s category_slugs=%s",
            projekt_uri,
            record.institution_codes,
            record.category_slugs,
        )

        context = {
            'project': project_context,
            'metadata': metadata,
            'tab_endpoint': reverse('catalog:projekt_tab'),
        }
        return render(request, 'catalog/projekt.html', context)

    @staticmethod
    def _backend() -> str:
        return getattr(settings, "PROJECT_INDEX_BACKEND", "snapshot")

    def _render_graph_detail(self, request, projekt_uri: str):
        """Render project detail using the triple-based ProjectView service."""

        project_data = get_project_view_data(projekt_uri)
        if not project_data:
            logger.warning("ProjectView[graph]: project not found via triple-based view: %s", projekt_uri)
            return self._render_error(request, f'Project not found: {projekt_uri}')

        project_context = self._build_context_from_project_data(project_data)
        metadata: List[Dict[str, Any]] = []

        context = {
            'project': project_context,
            'metadata': metadata,
            'tab_endpoint': reverse('catalog:projekt_tab'),
        }
        return render(request, 'catalog/projekt.html', context)

    @classmethod
    def _load_record(cls, projekt_uri: str) -> ProjectRecord:
        # Prefer the snapshot-free detail index to avoid global rebuilds
        detail_service = cls.detail_service_class()
        detail_record = detail_service.get_record(projekt_uri)
        if detail_record:
            logger.info("ProjectView: served via detail index (project_found=True)")
            return detail_record

        logger.warning("ProjectView: project not found via detail index: %s", projekt_uri)
        raise LookupError(projekt_uri)

    def _load_record_from_index(self, projekt_uri: str) -> ProjectRecord:
        index_service = ProjectIndexService(backend="db")
        indexed = index_service.get_record_by_uri(projekt_uri)
        if indexed:
            logger.info("ProjectView: served via project_records index (project_found=True)")
            return indexed

        # Fallback to on-demand detail assembly to avoid snapshot rebuilds.
        detail_service = self.detail_service_class()
        detail_record = detail_service.get_record(projekt_uri)
        if detail_record:
            logger.info(
                "ProjectView: detail index fallback for missing project_records entry (project_found=True)",
            )
            return detail_record

        logger.warning("ProjectView: project not found via project_records index: %s", projekt_uri)
        raise LookupError(projekt_uri)

    def _load_detail_from_index(self, projekt_uri: str) -> Optional[ProjectDetailIndex]:
        """Load detail data from ProjectDetailIndex table."""
        try:
            return ProjectDetailIndex.objects.get(uri=projekt_uri)
        except ProjectDetailIndex.DoesNotExist:
            logger.debug("ProjectView: ProjectDetailIndex not found for %s", projekt_uri)
            return None
        except Exception:
            logger.exception("ProjectView: error loading ProjectDetailIndex for %s", projekt_uri)
            return None

    @staticmethod
    def _metadata_entry(label: str, value: Any) -> Dict[str, Any]:
        """Create metadata entry dict, using 'value_list' for lists and 'value' for singles."""
        if isinstance(value, (list, tuple, set)):
            value_list = [item for item in value if item]
            return {'key': label, 'label': label, 'value_list': value_list} if value_list else {'key': label, 'label': label, 'value': '—'}
        return {'key': label, 'label': label, 'value': value or '—'}

    @staticmethod
    def _build_metadata_from_detail_index(entry: ProjectDetailIndex) -> Dict[str, Any]:
        """Build grouped metadata dict from ProjectDetailIndex."""
        from arkumu.catalog.services.wikidata_service import WikidataService

        wikidata_service = WikidataService()

        # Resolve Wikidata IDs to labels for catchphrases
        catchphrase_labels_raw = [c.get('label', '') for c in (entry.catchphrases or []) if c.get('label')]
        schlagworte = []
        for label in catchphrase_labels_raw:
            name = wikidata_service.get_entity_label(wikidata_id=label)
            if name:
                schlagworte.append({'id': label, 'name': name})

        # Categories with breadcrumbs
        kategorien = []
        for cat in (entry.categories or []):
            label = cat.get('label', '')
            if label:
                name = wikidata_service.get_entity_label(wikidata_id=label) or label
                kategorien.append({'id': label, 'name': name, 'breadcrumbs': [name]})

        # Rights status
        rights_label = entry.rights_status.get('label', '') if entry.rights_status else ''

        # Build grouped structure
        metadata = {
            'allgemein': ProjectView._filter_empty([
                ProjectView._metadata_entry('Kommentar DE', entry.properties.get('comment_de') if entry.properties else ''),
                ProjectView._metadata_entry('Kommentar EN', entry.properties.get('comment_en') if entry.properties else ''),
                ProjectView._metadata_entry('Sprache Titel', entry.properties.get('sprache_titel') if entry.properties else ''),
                ProjectView._metadata_entry('Sprache Untertitel', entry.properties.get('sprache_untertitel') if entry.properties else ''),
            ]),
            'eigenschaften': ProjectView._filter_empty(
                ProjectView._dict_metadata_entries_simple(
                    entry.properties,
                    ProjectView.PROPERTY_METADATA_FIELDS,
                )
            ),
            'status': ProjectView._filter_empty(
                ProjectView._dict_metadata_entries_simple(
                    entry.status,
                    ProjectView.STATUS_METADATA_FIELDS,
                )
            ),
            'normdaten': ProjectView._filter_empty(
                ProjectView._dict_metadata_entries_simple(
                    entry.authority,
                    ProjectView.AUTHORITY_METADATA_FIELDS,
                )
            ),
            'ersteller': ProjectView._filter_empty(
                ProjectView._dict_metadata_entries_simple(
                    entry.submitter,
                    ProjectView.SUBMITTER_METADATA_FIELDS,
                )
            ),
            'kategorien': kategorien,
            'schlagworte': schlagworte,
            'rechte': ProjectView._filter_empty([
                ProjectView._metadata_entry('Rechtsstatus', rights_label),
            ] + ProjectView._dict_metadata_entries_simple(
                entry.licenses,
                ProjectView.LICENSE_METADATA_FIELDS,
            )),
            'related_projects': [],  # Placeholder for future implementation
        }

        return metadata

    @classmethod
    def _dict_metadata_entries_simple(
        cls,
        source: Optional[Dict[str, Any]],
        field_map: Sequence[Tuple[str, str]],
    ) -> List[Dict[str, Any]]:
        """Create metadata entries from a dict source without prefix."""
        if not source:
            return []

        entries: List[Dict[str, Any]] = []
        for field_name, label in field_map:
            value = source.get(field_name)
            entry = cls._metadata_entry(label, value)
            entries.append(entry)
        return entries

    @staticmethod
    def _filter_empty(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter out entries with empty values."""
        return [e for e in entries if e.get('value') != '—' or 'value_list' in e]

    @classmethod
    def _build_metadata_from_graph(cls, projekt_uri: str, org_code: str) -> Dict[str, Any]:
        """Build grouped metadata dict directly from graph using canonical URIs.

        Uses graph_service to traverse the project graph and extract values
        by canonical predicate URI - fully schema-driven approach.
        """
        from arkumu.projects.services.graph_service import get_project_graphs
        from arkumu.metadata.models import Resource
        from arkumu.catalog.services.wikidata_service import WikidataService

        wikidata_service = WikidataService()

        # Get project resource ID
        try:
            project_resource = Resource.objects.get(uri=projekt_uri)
            project_id = str(project_resource.id)
        except Resource.DoesNotExist:
            logger.warning("_build_metadata_from_graph: project not found: %s", projekt_uri)
            return cls._empty_metadata()

        # Get project graph with canonical URIs
        graphs = get_project_graphs(project_id, org_code)
        if not graphs:
            logger.warning("_build_metadata_from_graph: no graph for project: %s", projekt_uri)
            return cls._empty_metadata()

        # Build lookup: canonical_uri -> list of values
        canonical_values: Dict[str, List[str]] = {}
        # Build lookup: subject_uri -> predicate_uri -> value (for label resolution)
        # Uses both canonical_uri and predicate_uri as keys
        entity_properties: Dict[str, Dict[str, str]] = {}

        for triple in graphs.triples:
            canonical_uri = triple.predicate_canonical_uri
            predicate_uri = triple.predicate_uri
            value = triple.object_value or triple.object_uri

            if canonical_uri and value:
                canonical_values.setdefault(canonical_uri, []).append(value)
            # Also index by predicate_uri (for properties without canonical mapping)
            if predicate_uri and value:
                canonical_values.setdefault(predicate_uri, []).append(value)

            # Build entity property lookup for label resolution (both canonical and institutional URIs)
            if triple.subject_uri and value:
                if canonical_uri:
                    entity_properties.setdefault(triple.subject_uri, {})[canonical_uri] = value
                if predicate_uri:
                    entity_properties.setdefault(triple.subject_uri, {})[predicate_uri] = value

        # Label predicates in priority order
        LABEL_PREDICATES = [
            'http://arkumu.org/data/properties/deutscher-name',
            'http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule',
            'http://arkumu.org/data/properties/deutscher-name-der-sprache',
            'http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb',
            'http://arkumu.org/data/properties/deutscher-name-der-projektart',
            'http://arkumu.org/data/properties/deutscher-anzeigetext',
            'http://arkumu.org/data/properties/bevorzugter-titel',
        ]

        def resolve_uri_to_label(uri: str) -> str:
            """Resolve a URI to its label/name using graph data."""
            if not uri or not uri.startswith('http'):
                return uri
            # Check if it's a Wikidata ID pattern
            if uri.startswith('Q') or '/Q' in uri:
                wikidata_id = uri.split('/')[-1] if '/' in uri else uri
                label = wikidata_service.get_entity_label(wikidata_id=wikidata_id)
                if label:
                    return label
            # Try to resolve from graph data first (no DB query)
            if uri in entity_properties:
                props = entity_properties[uri]
                for label_pred in LABEL_PREDICATES:
                    if label_pred in props:
                        return props[label_pred]
            # Fallback: try Resource name
            try:
                resource = Resource.objects.only('name', 'value').get(uri=uri)
                if resource.name:
                    return resource.name
                if resource.value:
                    return resource.value
            except Resource.DoesNotExist:
                pass
            # Return last segment of URI as fallback
            return uri.split('/')[-1] if '/' in uri else uri

        def resolve_uri_with_link(uri: str) -> Dict[str, Any]:
            """Resolve URI to label and optional Wikipedia link."""
            label = resolve_uri_to_label(uri)
            result = {'label': label, 'link': None}

            if not uri or not uri.startswith('http'):
                return result

            # Check if it's a Sprache entity - construct Wikipedia link
            if '/sprache/' in uri.lower() and uri in entity_properties:
                props = entity_properties[uri]
                # Try to get ISO code for Wikipedia link
                iso_code = props.get('http://arkumu.org/data/det/properties/iso-639-1-code')
                if iso_code and label:
                    # Link to Wikipedia article about the language
                    result['link'] = f'https://de.wikipedia.org/wiki/{label}_(Sprache)'

            return result

        # Fields that should be rendered as links
        LINK_FIELDS = {
            'http://arkumu.org/data/properties/originalsprache',  # Sprache in Projekteigenschaften
            'http://arkumu.org/data/properties/externe-projektwebseite',
        }

        # Normdaten fields with URL templates
        NORMDATEN_URL_TEMPLATES = {
            'http://arkumu.org/data/properties/wikidata-id': 'https://www.wikidata.org/wiki/{}',
            'http://arkumu.org/data/properties/gnd-nummer': 'https://d-nb.info/gnd/{}',
            'http://arkumu.org/data/properties/viaf-id': 'https://viaf.org/viaf/{}',
            'http://arkumu.org/data/properties/aat-id': 'https://www.getty.edu/vow/AATFullDisplay?find=&logic=AND&note=&subjectid={}',
            'http://arkumu.org/data/properties/externe-projektwebseite': None,  # URL is the value itself
        }

        def extract_entries(canonical_fields: Sequence[Tuple[str, str, str]], resolve_uris: bool = True, as_links: bool = False) -> List[Dict[str, Any]]:
            """Extract metadata entries for a list of canonical field definitions."""
            entries = []
            for field_key, label, canonical_uri in canonical_fields:
                values = canonical_values.get(canonical_uri, [])
                is_link_field = canonical_uri in LINK_FIELDS
                url_template = NORMDATEN_URL_TEMPLATES.get(canonical_uri)

                # Handle Normdaten fields with URL templates
                if as_links and (url_template is not None or canonical_uri in NORMDATEN_URL_TEMPLATES):
                    if values:
                        # Build entries with links as list of {value, url} dicts
                        linked_items = []
                        for v in values:
                            if url_template:
                                url = url_template.format(v)
                            else:
                                # externe-projektwebseite: URL is the value itself
                                url = v
                            linked_items.append({'value': v, 'url': url})

                        entry = {'key': label, 'label': label, 'is_link': True, 'linked_items': linked_items}
                        entries.append(entry)
                    else:
                        entries.append(cls._metadata_entry(label, None))
                elif resolve_uris and is_link_field:
                    # Resolve with link support (e.g., Sprache)
                    resolved = [resolve_uri_with_link(v) for v in values]
                    if len(resolved) == 1:
                        entry = cls._metadata_entry(label, resolved[0]['label'])
                        if resolved[0]['link']:
                            entry['is_link'] = True
                            entry['url'] = resolved[0]['link']
                        entries.append(entry)
                    elif len(resolved) > 1:
                        entry = cls._metadata_entry(label, [r['label'] for r in resolved])
                        links = [r['link'] for r in resolved if r['link']]
                        if links:
                            entry['is_link'] = True
                            entry['urls'] = links
                        entries.append(entry)
                    else:
                        entries.append(cls._metadata_entry(label, None))
                elif resolve_uris:
                    values = [resolve_uri_to_label(v) for v in values]
                    if len(values) == 1:
                        entries.append(cls._metadata_entry(label, values[0]))
                    elif len(values) > 1:
                        entries.append(cls._metadata_entry(label, values))
                    else:
                        entries.append(cls._metadata_entry(label, None))
                else:
                    if len(values) == 1:
                        entries.append(cls._metadata_entry(label, values[0]))
                    elif len(values) > 1:
                        entries.append(cls._metadata_entry(label, values))
                    else:
                        entries.append(cls._metadata_entry(label, None))
            return entries

        # Extract schlagworte - use deutsches-wikidata-label from graph or Wikidata API
        schlagwort_uri = "http://arkumu.org/data/properties/schlagwort"
        schlagworte = []
        seen_schlagworte = set()  # Deduplicate
        LABEL_PROP = 'http://arkumu.org/data/properties/deutsches-wikidata-label'

        for value in canonical_values.get(schlagwort_uri, []):
            # First try to get label from graph (deutsches-wikidata-label)
            if value in entity_properties and LABEL_PROP in entity_properties[value]:
                name = entity_properties[value][LABEL_PROP]
                if name and name not in seen_schlagworte:
                    seen_schlagworte.add(name)
                    schlagworte.append({'id': value, 'name': name})
                continue

            # Extract Wikidata ID - handle both "Q123456" and ".../schlagwort/q123456" patterns
            wikidata_id = value.split('/')[-1].upper() if '/' in value else value.upper()
            if wikidata_id.startswith('Q') and wikidata_id[1:].isdigit():
                name = wikidata_service.get_entity_label(wikidata_id=wikidata_id)
                if name and name not in seen_schlagworte:
                    seen_schlagworte.add(name)
                    schlagworte.append({'id': wikidata_id, 'name': name})
                continue

            # Fallback: resolve as URI
            name = resolve_uri_to_label(value)
            if name and name != value and name not in seen_schlagworte:
                seen_schlagworte.add(name)
                schlagworte.append({'id': value, 'name': name})

        # Extract kategorien with breadcrumb support
        kategorie_uri = "http://arkumu.org/data/properties/projektkategorie"
        kategorien = []
        seen_kategorien = set()  # Deduplicate
        BREADCRUMB_PROP = 'http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb'

        for value in canonical_values.get(kategorie_uri, []):
            if value in seen_kategorien:
                continue
            seen_kategorien.add(value)

            # Try to get breadcrumb from graph
            breadcrumb_str = None
            if value in entity_properties and BREADCRUMB_PROP in entity_properties[value]:
                breadcrumb_str = entity_properties[value][BREADCRUMB_PROP]

            if breadcrumb_str and ' > ' in breadcrumb_str:
                # Parse breadcrumb string like "Darstellende Kunst > Theater > Musiktheater"
                breadcrumbs = [b.strip() for b in breadcrumb_str.split(' > ')]
                name = breadcrumbs[-1]  # Last segment is the category name
            else:
                # Fallback: resolve label
                name = resolve_uri_to_label(value)
                breadcrumbs = [name]

            kategorien.append({'id': value, 'name': name, 'breadcrumbs': breadcrumbs})

        # Extract related projects
        related_projects = []
        for rel_field_key, rel_label, rel_uri in cls.RELATION_CANONICAL:
            for related_uri in canonical_values.get(rel_uri, []):
                # Try to get the title of the related project
                try:
                    related_resource = Resource.objects.get(uri=related_uri)
                    title = related_resource.name or related_uri
                except Resource.DoesNotExist:
                    title = related_uri
                related_projects.append({
                    'uri': related_uri,
                    'title': title,
                    'relation_type': rel_label,
                })

        return {
            'allgemein': cls._filter_empty(extract_entries(cls.ALLGEMEIN_CANONICAL)),
            'eigenschaften': cls._filter_empty(extract_entries(cls.EIGENSCHAFTEN_CANONICAL)),
            'status': cls._filter_empty(extract_entries(cls.STATUS_CANONICAL, resolve_uris=False)),  # Keep raw values
            'normdaten': cls._filter_empty(extract_entries(cls.NORMDATEN_CANONICAL, resolve_uris=False, as_links=True)),  # IDs as links
            'ersteller': cls._filter_empty(extract_entries(cls.ERSTELLER_CANONICAL)),
            'kategorien': kategorien,
            'schlagworte': schlagworte,
            'rechte': cls._filter_empty(extract_entries(cls.RECHTE_CANONICAL)),
            'related_projects': related_projects,
        }

    @staticmethod
    def _empty_metadata() -> Dict[str, Any]:
        """Return empty metadata structure."""
        return {
            'allgemein': [],
            'eigenschaften': [],
            'status': [],
            'normdaten': [],
            'ersteller': [],
            'kategorien': [],
            'schlagworte': [],
            'rechte': [],
            'related_projects': [],
        }

    @staticmethod
    def _find_record(records: List[ProjectRecord], uri: str) -> Optional[ProjectRecord]:
        for record in records:
            if record.uri == uri:
                return record
        return None

    @staticmethod
    def _build_context(record: ProjectRecord) -> Dict[str, Any]:

        image = []

        # image = record.image
        # if not image and record.digital_objects:
        #     image = record.digital_objects[0].path
        # image = image or 'images/main/card_1.png'

        for obj in record.digital_objects:
            image.append(obj.path)


        image_preview = []
        for candidate in image:
            if PreviewImages.objects.filter(path=candidate).exists():
                image_preview.append(candidate)
        image = image_preview
        #
        # if valid_preview:
        #     card["image"] = valid_preview
        # else:
        #     fallback_path = _object_display_path(self.digital_objects[0])
        #     if fallback_path:
        #         card["image"] = fallback_path

        alternative_title = record.alternative_titles[0].value if record.alternative_titles else ''
        catchphrases = [item.label for item in record.catchphrases if item.label]
        categories = [item.label for item in record.categories if item.label]
        digital_objects = [item.path for item in record.digital_objects if item.path]
        actors = []

        categories_name = []
        for i,w in enumerate(categories):
            categories_name.append(WikidataService().get_entity_label(wikidata_id=w))
        categories = [
            {"id": cid, "name": cname}
            for cid, cname in zip(categories, categories_name)
        ]

        catchphrases_name = []
        for i,w in enumerate(catchphrases):
            catchphrases_name.append(WikidataService().get_entity_label(wikidata_id=w))
        catchphrases = [
            {"id": cid, "name": cname}
            for cid, cname in zip(catchphrases, catchphrases_name)
        ]


        for actor in record.actors or []:
            if not actor:
                continue
            if isinstance(actor, dict):
                name = actor.get('name')
                roles = actor.get('roles') or []
            else:
                name = getattr(actor, 'name', None)
                roles = list(getattr(actor, 'roles', []) or [])
            if not name:
                continue
            actors.append({'name': name, 'roles': roles})
        events = [ProjectView._serialize_event(event) for event in record.events]

        if record.year_range:
            year_range = record.year_range
        else:
            year_range = ProjectView._derive_year_range(events)

        return {
            'uri': record.uri,
            'title': record.title or 'Untitled Project',
            'subtitle': record.subtitle or '',
            'alternative_title': alternative_title,
            'descriptions': [record.description] if record.description else [],
            'image': image,
            'institution': record.institution.label if record.institution and record.institution.label else '',
            'projektart': record.project_type.label if record.project_type and record.project_type.label else '',
            'year_range': year_range or '',
            'categories': categories,
            'actors': actors,
            'catchphrases': catchphrases,
            'digital_objects': digital_objects,
            'events': events,
        }

    @staticmethod
    def _build_context_from_project_data(project_data: Any) -> Dict[str, Any]:
        """Build project context dict from ProjectData (triple-based service)."""

        # Images: prefer any associated digital object paths that have previews.
        image_candidates: List[str] = []
        if getattr(project_data, "image", None):
            image_candidates.append(project_data.image)
        for path in getattr(project_data, "digital_objects", []) or []:
            if path:
                image_candidates.append(path)

        image_preview: List[str] = []
        for candidate in image_candidates:
            if not candidate:
                continue
            if PreviewImages.objects.filter(path=candidate).exists():
                image_preview.append(candidate)
        image = image_preview or image_candidates

        alternative_titles = getattr(project_data, "alternative_titles", []) or []
        alternative_title = alternative_titles[0] if alternative_titles else ""

        raw_catchphrases = getattr(project_data, "catchphrases", []) or []
        catchphrases: List[Dict[str, str]] = []
        for cid in raw_catchphrases:
            if not cid:
                continue
            name = WikidataService().get_entity_label(wikidata_id=cid) or cid
            catchphrases.append({"id": cid, "name": name})

        raw_categories = getattr(project_data, "categories", []) or []
        categories: List[Dict[str, str]] = []
        for label in raw_categories:
            if not label:
                continue
            # For graph-backed local mode we treat category labels as plain
            # text and do not resolve them against Wikidata.
            categories.append({"id": "", "name": label})

        digital_objects = list(getattr(project_data, "digital_objects", []) or [])

        actors = []
        for actor in getattr(project_data, "actors", []) or []:
            if not actor:
                continue
            name = actor.get('name')
            roles = actor.get('roles') or []
            if not name:
                continue
            actors.append({'name': name, 'roles': roles})

        events = []
        for event in getattr(project_data, "events", []) or []:
            events.append(ProjectView._serialize_event(event))

        year_range = ProjectView._derive_year_range(events)

        return {
            'uri': getattr(project_data, "uri", ""),
            'title': getattr(project_data, "title", "") or 'Untitled Project',
            'subtitle': getattr(project_data, "subtitle", "") or "",
            'alternative_title': alternative_title,
            'descriptions': [getattr(project_data, "description", "")] if getattr(project_data, "description", None) else [],
            'image': image,
            'institution': getattr(project_data, "institution", "") or "",
            'projektart': getattr(project_data, "project_type", "") or "",
            'year_range': year_range or "",
            'categories': categories,
            'actors': actors,
            'catchphrases': catchphrases,
            'digital_objects': digital_objects,
            'events': events,
        }

    @staticmethod
    def _serialize_event(event: ProjectEvent | Dict[str, Any]) -> Dict[str, Any]:
        """Normalize event payload coming from dataclass snapshots or legacy dicts."""

        def _attr(source: ProjectEvent | Dict[str, Any], key: str) -> Any:
            if isinstance(source, dict):
                return source.get(key)
            return getattr(source, key, None)

        actors_raw = _attr(event, 'actors') or []
        actor_entries: List[Dict[str, Any]] = []
        for actor in actors_raw:
            if not actor:
                continue
            if isinstance(actor, dict):
                name = actor.get('name')
                roles = actor.get('roles') or []
            else:
                name = getattr(actor, 'name', None)
                roles = list(getattr(actor, 'roles', []) or [])
            if not name:
                continue
            actor_entries.append({'name': name, 'roles': roles})

        uri = _attr(event, 'uri')
        name = _attr(event, 'name')
        start_value = _attr(event, 'start')
        end_value = _attr(event, 'end')
        if start_value and end_value:
            display_date = start_value if start_value == end_value else f"{start_value} – {end_value}"
        else:
            display_date = start_value or end_value or None

        primary_actor = actor_entries[0]['name'] if len(actor_entries) > 0 else ''
        secondary_actor = actor_entries[1]['name'] if len(actor_entries) > 1 else ''

        return {
            'id': _attr(event, 'id'),
            'uri': name or uri,
            'raw_uri': uri,
            'name': name,
            'description': _attr(event, 'description'),
            'location': _attr(event, 'location'),
            'location_id': _attr(event, 'location_id'),
            'country': _attr(event, 'country'),
            'type': _attr(event, 'type'),
            'start': _attr(event, 'start'),
            'end': _attr(event, 'end'),
            'latitude': _attr(event, 'latitude'),
            'longitude': _attr(event, 'longitude'),
            'actors': actor_entries,
            'display_date': display_date,
            'primary_actor': primary_actor,
            'secondary_actor': secondary_actor,
        }

    @staticmethod
    def _derive_year_range(events: Sequence[Dict[str, Any]]) -> Optional[str]:
        for event in events:
            start = event.get('start')
            end = event.get('end')
            if start and end:
                start_year = start.split('-')[0] if '-' in start else start
                end_year = end.split('-')[0] if '-' in end else end
                return start_year if start_year == end_year else f"{start_year} bis {end_year}"
            if start:
                return start.split('-')[0] if '-' in start else start
            if end:
                return end.split('-')[0] if '-' in end else end
        return None

    @staticmethod
    def _build_metadata(record: ProjectRecord) -> Dict[str, Any]:
        """Build grouped metadata dict from ProjectRecord."""
        rights_status_raw = record.rights_status
        rights_status = ''
        if rights_status_raw:
            if isinstance(rights_status_raw, Mapping):
                rights_status = rights_status_raw.get('label') or rights_status_raw.get('value') or ''
            else:
                candidate = getattr(rights_status_raw, 'label', rights_status_raw)
                if isinstance(candidate, (list, tuple, set)):
                    rights_status = ', '.join([item for item in candidate if item])
                elif isinstance(candidate, str):
                    rights_status = candidate
                else:
                    rights_status = str(candidate) if candidate else ''

        catchphrase_labels = [item.label for item in record.catchphrases if item.label]
        category_labels = [item.label for item in record.categories if item.label]

        # Resolve Wikidata IDs
        wikidata_service = WikidataService()
        schlagworte = []
        for label in catchphrase_labels:
            name = wikidata_service.get_entity_label(wikidata_id=label)
            if name:
                schlagworte.append({'id': label, 'name': name})

        kategorien = []
        for label in category_labels:
            name = wikidata_service.get_entity_label(wikidata_id=label) or label
            kategorien.append({'id': label, 'name': name, 'breadcrumbs': [name]})

        # Extract comments and language info from Entity
        ent = Entity(record.uri)
        comment_de = ent.resources.get("Deutscher Kommentar")[0].value if ent.resources.get("Deutscher Kommentar") else ''
        comment_en = ent.resources.get("Englischer Kommentar")[0].value if ent.resources.get("Englischer Kommentar") else ''
        lang_title = ent.resources.get("Sprache des bevorzugten Titels")[0].uri if ent.resources.get("Sprache des bevorzugten Titels") else ''
        lang_sub_title = ent.resources.get("Sprache des bevorzugten Untertitels")[0].uri if ent.resources.get("Sprache des bevorzugten Untertitels") else ''

        # Build grouped structure
        metadata = {
            'allgemein': ProjectView._filter_empty([
                ProjectView._metadata_entry('Kommentar DE', comment_de),
                ProjectView._metadata_entry('Kommentar EN', comment_en),
                ProjectView._metadata_entry('Sprache Titel', lang_title),
                ProjectView._metadata_entry('Sprache Untertitel', lang_sub_title),
            ]),
            'eigenschaften': ProjectView._filter_empty(
                ProjectView._dataclass_metadata_entries_simple(
                    record.properties,
                    ProjectView.PROPERTY_METADATA_FIELDS,
                )
            ),
            'status': ProjectView._filter_empty(
                ProjectView._dataclass_metadata_entries_simple(
                    record.status,
                    ProjectView.STATUS_METADATA_FIELDS,
                )
            ),
            'normdaten': ProjectView._filter_empty(
                ProjectView._dataclass_metadata_entries_simple(
                    record.authority,
                    ProjectView.AUTHORITY_METADATA_FIELDS,
                )
            ),
            'ersteller': ProjectView._filter_empty(
                ProjectView._dataclass_metadata_entries_simple(
                    record.submitter,
                    ProjectView.SUBMITTER_METADATA_FIELDS,
                )
            ),
            'kategorien': kategorien,
            'schlagworte': schlagworte,
            'rechte': ProjectView._filter_empty([
                ProjectView._metadata_entry('Rechtsstatus', rights_status),
            ] + ProjectView._dataclass_metadata_entries_simple(
                record.licenses,
                ProjectView.LICENSE_METADATA_FIELDS,
            )),
            'related_projects': [],  # Placeholder for future implementation
        }

        return metadata

    @classmethod
    def _dataclass_metadata_entries_simple(
        cls,
        source: Any,
        field_map: Sequence[Tuple[str, str]],
    ) -> List[Dict[str, Any]]:
        """Create metadata entries from a dataclass source without prefix."""
        if not source:
            return []

        entries: List[Dict[str, Any]] = []
        for field_name, label in field_map:
            value = getattr(source, field_name, None)
            entry = cls._metadata_entry(label, value)
            entries.append(entry)
        return entries

    @staticmethod
    def _log_project_record_debug(
        record: ProjectRecord,
        project_context: Dict[str, Any],
        metadata_entries: List[Dict[str, Any]],
    ) -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return

        institution_label = record.institution.label if record.institution and record.institution.label else ''
        summary = {
            'uri': record.uri,
            'title': record.title,
            'institution': institution_label,
            'project_type': record.project_type.label if record.project_type and record.project_type.label else '',
            'category_slugs': record.category_slugs,
            'catchphrase_labels': [item.label for item in record.catchphrases if item.label],
            'digital_object_count': len(record.digital_objects),
            'event_count': len(record.events),
            'reference_only': record.reference_only,
            'harvestable': record.harvestable,
            'ownership_filtered': record.ownership_filtered,
        }
        logger.debug("ProjectView: project record summary %s", summary)

        bundles = {
            'properties': record.properties,
            'status': record.status,
            'authority': record.authority,
            'submitter': record.submitter,
            'licenses': record.licenses,
        }
        for label, payload in bundles.items():
            populated, empty = ProjectView._dataclass_field_breakdown(payload)
            logger.debug(
                "ProjectView: %s bundle for %s | populated_fields=%s | empty_fields=%s",
                label,
                record.uri,
                populated,
                empty,
            )

        try:
            raw_payload = record.to_dict()
        except Exception:  # pragma: no cover - defensive
            raw_payload = {}
        pretty_record = json.dumps(raw_payload, indent=2, sort_keys=True, default=str)

        logger.debug("ProjectView: render context for %s -> %s", record.uri, project_context)
        logger.debug("ProjectView: metadata entries for %s -> %s", record.uri, metadata_entries)
        logger.debug("ProjectView: raw ProjectRecord payload for %s\n%s", record.uri, pretty_record)

    @staticmethod
    def _dataclass_field_breakdown(payload: Any) -> Tuple[Dict[str, Any], List[str]]:
        if not payload:
            return {}, []
        populated: Dict[str, Any] = {}
        empty: List[str] = []
        for field_name, value in vars(payload).items():
            if ProjectView._is_empty_value(value):
                empty.append(field_name)
            else:
                populated[field_name] = value
        return populated, sorted(empty)

    @staticmethod
    def _is_empty_value(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, (list, tuple, set, dict)):
            return len(value) == 0
        if isinstance(value, str):
            return not value.strip()
        return False

    @staticmethod
    def _render_error(request, message: str):
        return render(request, 'catalog/design_error.html', {'error': message})


class ProjectTabView(LoginRequiredMixin, View):
    """Serve tab content for project detail via HTMX."""

    def get(self, request, *args, **kwargs):
        projekt_uri = request.GET.get('projekt')
        tab = request.GET.get('tab', 'overview').lower()

        if not projekt_uri:
            return HttpResponseBadRequest("Missing project URI")

        backend = ProjectView._backend()

        # For db/graph backends, prefer ProjectDetailIndex for fast structured access
        if backend in ("db", "graph"):
            try:
                detail_entry = ProjectDetailIndex.objects.get(uri=projekt_uri)
                project_context = detail_entry.to_view_context()
                metadata = ProjectView._build_metadata_from_detail_index(detail_entry)
                return self._render_tab(request, tab, project_context, metadata)
            except ProjectDetailIndex.DoesNotExist:
                pass  # Fall through to other backends

        # Fallback for graph backend without detail index entry
        if backend == "graph":
            project_data = get_project_view_data(projekt_uri)
            if not project_data:
                return HttpResponseNotFound("Project not found")
            project_context = ProjectView._build_context_from_project_data(project_data)
            metadata: Dict[str, Any] = {
                'allgemein': [], 'eigenschaften': [], 'status': [], 'normdaten': [],
                'ersteller': [], 'kategorien': [], 'schlagworte': [], 'rechte': [],
                'related_projects': [],
            }
        else:
            try:
                record = ProjectView._load_record(projekt_uri)
            except LookupError:
                return HttpResponseNotFound("Project not found")
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception("ProjectTabView: error loading project %s", projekt_uri)
                return HttpResponseNotFound("Project not found")

            project_context = ProjectView._build_context(record)
            metadata = ProjectView._build_metadata(record)

        return self._render_tab(request, tab, project_context, metadata)

    def _render_tab(self, request, tab: str, project_context: Dict[str, Any], metadata: Dict[str, Any]):
        """Render the appropriate tab partial."""
        if tab == 'events':
            return render(request, 'catalog/partials/project_events.html', {'events': project_context['events']})

        if tab == 'metadata':
            # Use graph-based extraction for metadata tab - fully schema-driven
            projekt_uri = project_context.get('uri', '')
            org_code = self._get_org_code_for_uri(projekt_uri)
            if org_code:
                metadata = ProjectView._build_metadata_from_graph(projekt_uri, org_code)
            return render(request, 'catalog/partials/project_metadata.html', {'metadata': metadata})

        return render(request, 'catalog/partials/project_overview.html', {'project': project_context})

    @staticmethod
    def _get_org_code_for_uri(projekt_uri: str) -> Optional[str]:
        """Get organization code for a project URI."""
        from arkumu.metadata.models import Resource
        try:
            resource = Resource.objects.select_related('organization').get(uri=projekt_uri)
            return resource.organization.code if resource.organization else None
        except Resource.DoesNotExist:
            return None
