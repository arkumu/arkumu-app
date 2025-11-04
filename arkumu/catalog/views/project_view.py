"""Project detail view backed by cached project snapshots."""
import uuid
from functools import singledispatchmethod

from django.views.generic import View
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.http import HttpResponseBadRequest, HttpResponseNotFound
import logging
from typing import Any, Dict, List, Optional, Sequence

from arkumu.metadata.models import Resource, Triple, ResourceType
from arkumu.projects import ProjectEvent, ProjectRecord
from arkumu.projects.services import ProjectSnapshotService

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

    def get(self, request, *args, **kwargs):
        projekt_uri = request.GET.get('projekt')
        if not projekt_uri:
            logger.error("ProjectView: missing 'projekt' query parameter")
            return self._render_error(request, 'No project URI provided')

        try:
            record = self._load_record(projekt_uri)
        except LookupError:
            logger.warning("ProjectView: project not found in snapshot: %s", projekt_uri)
            return self._render_error(request, f'Project not found: {projekt_uri}')
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("ProjectView: error loading project %s", projekt_uri)
            return self._render_error(request, f'Error loading project: {exc}')

        project_context = self._build_context(record)
        metadata = self._build_metadata(record)

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

    @classmethod
    def _load_record(cls, projekt_uri: str) -> ProjectRecord:
        snapshot_service = cls.snapshot_service_class()
        snapshot = snapshot_service.get_cross_institutional_snapshot()

        record = cls._find_record(snapshot.projects, projekt_uri)
        logger.info(
            "ProjectView: using snapshot %s (project_found=%s)",
            snapshot.generated_at.isoformat(),
            bool(record),
        )

        if not record:
            raise LookupError(projekt_uri)

        return record

    @staticmethod
    def _find_record(records: List[ProjectRecord], uri: str) -> Optional[ProjectRecord]:
        for record in records:
            if record.uri == uri:
                return record
        return None

    @staticmethod
    def _build_context(record: ProjectRecord) -> Dict[str, Any]:
        image = record.image
        if not image and record.digital_objects:
            image = record.digital_objects[0].path
        image = image or 'images/main/card_1.png'

        alternative_title = record.alternative_titles[0].value if record.alternative_titles else ''
        catchphrases = [item.label for item in record.catchphrases if item.label]
        categories = [item.label for item in record.categories if item.label]
        digital_objects = [item.path for item in record.digital_objects if item.path]
        actors = []
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
    def _build_metadata(record: ProjectRecord) -> List[Dict[str, Any]]:
        def _entry(label: str, value: Any) -> Dict[str, Any]:
            if isinstance(value, (list, tuple, set)):
                values = [item for item in value if item]
                return {'key': label, 'values': values} if values else {'key': label, 'value': '—'}
            return {'key': label, 'value': value or '—'}

        institution_label = record.institution.label if record.institution and record.institution.label else ''
        project_type = record.project_type.label if record.project_type and record.project_type.label else ''
        rights_status = record.project_type.label if record.rights_status and record.project_type.label else ''
        catchphrase_labels = [item.label for item in record.catchphrases if item.label]
        category_labels = [item.label for item in record.categories if item.label]
        digital_object_paths = [item.path for item in record.digital_objects if item.path]
        alternative_titles = [item.value for item in record.alternative_titles if item.value]

        # neu
        ent = Entity(record.uri)
        comment_de = ent.resources.get("comment_de")[0].value if ent.resources.get("comment_de") else ''
        comment_en = ent.resources.get("comment_en")[0].value if ent.resources.get("comment_en") else ''
        lang_title = ent.resources.get("Sprache des bevorzugten Titels")[0].value if ent.resources.get(
            "Sprache des bevorzugten Titels") else ''
        lang_sub_title = ent.resources.get("Sprache des bevorzugten Untertitels")[0].value if ent.resources.get(
            "Sprache des bevorzugten Untertitels") else ''

        # Mappe CSV-Spalten auf ProjectRecord-Eigenschaften
        metadata_entries = [
            _entry('Projekt URI', record.uri),
            _entry('Institution', institution_label),
            _entry('Projektart', project_type),
            _entry('Schlagworte', catchphrase_labels),
            _entry('Kategorien', category_labels),
            _entry('Digitale Objekte', digital_object_paths),
            _entry('Alternative Titel', alternative_titles),
            _entry('Kommentar DE', comment_de),
            _entry('Kommentar EN', comment_en),
            _entry('Sprache Titel', lang_title),
            _entry('Sprache Untertitel', lang_sub_title),
            _entry("Rechtsstatus",rights_status),
        ]

        if record.events:
            metadata_entries.append(_entry('Anzahl Ereignisse', len(record.events)))

        return metadata_entries

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

        try:
            record = ProjectView._load_record(projekt_uri)
        except LookupError:
            return HttpResponseNotFound("Project not found")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("ProjectTabView: error loading project %s", projekt_uri)
            return HttpResponseNotFound("Project not found")

        project_context = ProjectView._build_context(record)
        metadata = ProjectView._build_metadata(record)

        if tab == 'events':
            return render(request, 'catalog/partials/project_events.html', {'events': project_context['events']})

        if tab == 'metadata':
            return render(request, 'catalog/partials/project_metadata.html', {'metadata': metadata})

        return render(request, 'catalog/partials/project_overview.html', {'project': project_context})
