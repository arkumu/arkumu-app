"""Service for fetching project data using institution adapters.

Replaces the complex snapshot_service with a simpler adapter-based approach.
Each institution's patterns (junctions, predicates) are handled by adapters.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from arkumu.projects.adapters import (
    get_adapter,
    ProjectGraph,
    EventData,
    DigitalObjectData,
    ProjectPropertiesData,
)
from arkumu.projects.models import (
    ProjectRecord,
    ProjectEvent,
    ProjectEventActor,
    ProjectActor,
    ProjectDigitalObject,
    ProjectDigitalObjectLicense,
    ProjectInstitution,
    ProjectCategory,
)

logger = logging.getLogger(__name__)


class ProjectDataService:
    """Service for fetching project data using institution adapters.

    Uses the adapter pattern to handle institution-specific data patterns:
    - FUK: Direct predicates (canonical pattern)
    - HMT: Junction tables for project-event and event-digital object
    - KHM: Grundereignis pattern for events

    Example:
        service = ProjectDataService("fuk")
        record = service.get_project_record(project_id)
        graph = service.get_project_graph(project_id)
    """

    def __init__(self, org_code: str):
        self.org_code = org_code
        self.adapter = get_adapter(org_code)

    def get_project_graph(self, project_id: str) -> Optional[ProjectGraph]:
        """Get complete project graph for RDF serialization."""
        return self.adapter.get_project_graph(project_id)

    def get_project_record(self, project_id: str) -> Optional[ProjectRecord]:
        """Get ProjectRecord for a project.

        Converts adapter data to ProjectRecord format.
        """
        graph = self.adapter.get_project_graph(project_id)
        if not graph:
            return None

        return self._build_project_record(project_id, graph)

    def get_project_records(self, project_ids: List[str]) -> List[ProjectRecord]:
        """Get ProjectRecords for multiple projects."""
        records = []
        for pid in project_ids:
            record = self.get_project_record(pid)
            if record:
                records.append(record)
        return records

    def _build_project_record(self, project_id: str, graph: ProjectGraph) -> ProjectRecord:
        """Build ProjectRecord from ProjectGraph."""
        props = graph.properties

        # Build institution
        institution = None
        if props.institution_uri or props.institution_label:
            institution = ProjectInstitution(
                label=props.institution_label,
                uri=props.institution_uri,
                code=self.org_code,
            )

        # Build categories
        categories = []
        for i, uri in enumerate(props.category_uris):
            label = props.category_labels[i] if i < len(props.category_labels) else None
            categories.append(ProjectCategory(label=label, uri=uri))

        # Build events with actors
        events = [self._build_project_event(e) for e in graph.events]
        main_event = events[0] if events else None

        # Build flat actor list
        actors = [
            ProjectActor(
                name=a.actor_name,
                roles=list(a.roles),
                uri=a.actor_id,
            )
            for a in graph.actors
        ]

        # Build digital objects
        digital_objects = [
            self._build_digital_object(do) for do in graph.digital_objects
        ]

        # Derive year range from events
        year_range = self._derive_year_range(events)

        return ProjectRecord(
            subject_id=project_id,
            uri=graph.project_uri,
            title=props.title,
            subtitle=props.subtitle,
            description=props.description,
            image=props.image,
            institution=institution,
            categories=categories,
            main_event=main_event,
            events=events,
            actors=actors,
            digital_objects=digital_objects,
            year_range=year_range,
            institution_codes=[self.org_code] if self.org_code else [],
        )

    def _build_project_event(self, event: EventData) -> ProjectEvent:
        """Build ProjectEvent from EventData."""
        actors = [
            ProjectEventActor(
                name=a.actor_name,
                roles=list(a.roles),
                is_copyright_holder=a.is_copyright_holder,
                is_neighbouring_rights_holder=a.is_neighbouring_rights_holder,
            )
            for a in event.actors
        ]

        return ProjectEvent(
            id=event.event_id,
            uri=event.event_uri,
            name=event.name,
            description=event.description,
            location=event.location,
            start=event.start,
            end=event.end,
            type=event.event_type,
            actors=actors,
        )

    def _build_digital_object(self, do: DigitalObjectData) -> ProjectDigitalObject:
        """Build ProjectDigitalObject from DigitalObjectData."""
        license_obj = None
        if do.license_uri:
            license_obj = ProjectDigitalObjectLicense(
                uri=do.license_uri,
                label_de=do.license_label,
            )

        return ProjectDigitalObject(
            path=do.path or "",
            uri=do.object_uri,
            file_name=do.file_name,
            content_type=do.content_type,
            license=license_obj,
            source_event_ids=list(do.source_event_ids),
        )

    def _derive_year_range(self, events: List[ProjectEvent]) -> Optional[str]:
        """Derive year range from event dates."""
        years = set()
        for event in events:
            if event.start:
                try:
                    year = int(event.start[:4])
                    years.add(year)
                except (ValueError, TypeError):
                    pass
            if event.end:
                try:
                    year = int(event.end[:4])
                    years.add(year)
                except (ValueError, TypeError):
                    pass

        if not years:
            return None

        min_year = min(years)
        max_year = max(years)

        if min_year == max_year:
            return str(min_year)
        return f"{min_year}-{max_year}"


def get_project_data_service(org_code: str) -> ProjectDataService:
    """Factory function for ProjectDataService."""
    return ProjectDataService(org_code)
