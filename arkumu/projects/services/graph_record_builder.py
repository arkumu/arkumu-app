"""Build ProjectRecord from graph triples.

Converts ProjectGraphs to ProjectRecord using modular extractors.
"""

from __future__ import annotations

from typing import List, Optional, Set

from arkumu.projects import (
    ProjectRecord,
    ProjectInstitution,
    ProjectCategory,
    ProjectType,
    ProjectEvent,
    ProjectEventActor,
    ProjectDigitalObject,
    ProjectDigitalObjectLicense,
    ProjectAlternateTitle,
    ProjectCatchphrase,
)
from arkumu.projects.services.graph_extractors import (
    TripleIndex,
    Predicates,
    get_literal,
    get_all_literals,
    get_object_uri,
    get_all_object_uris,
    extract_code_from_uri,
    is_truthy,
    is_junction_uri,
    find_subjects_by_type_pattern,
)
from arkumu.projects.services.graph_service import ProjectGraphs


def extract_institution(index: TripleIndex, project_uri: str) -> Optional[ProjectInstitution]:
    """Extract institution from graph."""
    inst_uri = get_object_uri(index, project_uri, Predicates.INSTITUTION)
    if not inst_uri:
        return None

    # Get institution name from the linked entity
    inst_name = get_literal(index, inst_uri, Predicates.INSTITUTION_NAME)
    if not inst_name:
        inst_name = get_literal(index, inst_uri, Predicates.ACTOR_NAME)

    code = extract_code_from_uri(inst_uri)

    return ProjectInstitution(
        label=inst_name,
        uri=inst_uri,
        code=code,
    )


def extract_categories(index: TripleIndex, project_uri: str) -> List[ProjectCategory]:
    """Extract categories from graph."""
    cat_uris = get_all_object_uris(index, project_uri, Predicates.CATEGORY)
    categories = []

    for cat_uri in cat_uris:
        cat_name = get_literal(index, cat_uri, Predicates.CATEGORY_NAME)
        if not cat_name:
            cat_name = get_literal(index, cat_uri, Predicates.ACTOR_NAME)

        slug = cat_uri.rstrip("/").split("/")[-1] if cat_uri else None

        categories.append(ProjectCategory(
            label=cat_name,
            uri=cat_uri,
            slug=slug,
        ))

    return categories


def extract_project_type(index: TripleIndex, project_uri: str) -> Optional[ProjectType]:
    """Extract project type from graph."""
    type_uri = get_object_uri(index, project_uri, Predicates.PROJECT_TYPE)
    if not type_uri:
        return None

    type_name = get_literal(index, type_uri, Predicates.ACTOR_NAME)

    return ProjectType(
        label=type_name,
        uri=type_uri,
    )


def extract_alternative_titles(index: TripleIndex, project_uri: str) -> List[ProjectAlternateTitle]:
    """Extract alternative titles from graph."""
    alt_titles = get_all_literals(index, project_uri, Predicates.ALT_TITLE)
    return [ProjectAlternateTitle(value=t) for t in alt_titles if t]


def extract_catchphrases(index: TripleIndex, project_uri: str) -> List[ProjectCatchphrase]:
    """Extract catchphrases/schlagworte from graph."""
    schlagwort_uris = get_all_object_uris(index, project_uri, Predicates.SCHLAGWORT)
    catchphrases = []

    for sw_uri in schlagwort_uris:
        label = get_literal(index, sw_uri, Predicates.SCHLAGWORT_LABEL)
        if not label:
            label = get_literal(index, sw_uri, Predicates.ACTOR_NAME)
        if label:
            catchphrases.append(ProjectCatchphrase(label=label, uri=sw_uri))

    return catchphrases


def extract_event_actors(index: TripleIndex, event_uri: str) -> List[ProjectEventActor]:
    """Extract actors for an event from junction entities."""
    actors = []
    seen_names: Set[str] = set()

    # Find junctions pointing to this event
    for subject in index.all_subjects:
        if not is_junction_uri(subject):
            continue

        # Check if junction links to this event
        junction_event = get_object_uri(index, subject, Predicates.IM_EREIGNIS)
        if not junction_event:
            junction_event = get_object_uri(index, subject, Predicates.EVENT)

        # Also check for institutional FK predicates (ereignis-nr-fk, etc.)
        if not junction_event:
            for t in index.by_subject.get(subject, []):
                pred = t.predicate_canonical_uri or t.predicate_uri
                if pred and ("ereignis" in pred.lower() and "fk" in pred.lower()):
                    junction_event = t.object_uri
                    break

        if junction_event != event_uri:
            continue

        # Get actor from junction
        actor_uri = get_object_uri(index, subject, Predicates.ACTOR_LINK)
        if not actor_uri:
            # Try institutional predicate
            for t in index.by_subject.get(subject, []):
                pred = t.predicate_canonical_uri or t.predicate_uri
                if pred and ("akteur" in pred.lower() and "fk" in pred.lower()):
                    actor_uri = t.object_uri
                    break

        if not actor_uri:
            continue

        # Get actor name
        actor_name = get_literal(index, actor_uri, Predicates.ACTOR_NAME)
        if not actor_name:
            continue

        # Skip duplicates
        if actor_name in seen_names:
            continue
        seen_names.add(actor_name)

        # Get roles
        role_uris = get_all_object_uris(index, subject, Predicates.ROLE_LINK)
        roles = []
        for role_uri in role_uris:
            role_name = get_literal(index, role_uri, Predicates.ROLE_NAME)
            if not role_name:
                role_name = get_literal(index, role_uri, Predicates.ACTOR_NAME)
            if role_name:
                roles.append(role_name)

        # Get rights flags
        is_copyright = is_truthy(get_literal(index, subject, Predicates.IST_URHEBERIN))
        is_neighbouring = is_truthy(get_literal(index, subject, Predicates.LEISTUNGSSCHUTZRECHTE))

        actors.append(ProjectEventActor(
            name=actor_name,
            roles=roles,
            is_copyright_holder=is_copyright,
            is_neighbouring_rights_holder=is_neighbouring,
        ))

    return actors


def extract_events(index: TripleIndex, project_uri: str) -> List[ProjectEvent]:
    """Extract events from graph."""
    events = []

    # Direct event links
    event_uris = get_all_object_uris(index, project_uri, Predicates.EVENT)

    # Also find events via pattern matching in subjects
    for subject in index.all_subjects:
        if "/ereignis/" in subject.lower() or "/event/" in subject.lower():
            if subject not in event_uris:
                # Check if this event is linked to our project
                project_link = get_object_uri(index, subject, Predicates.IM_EREIGNIS)
                if project_link == project_uri:
                    event_uris.append(subject)

    for event_uri in event_uris:
        event_id = event_uri.rstrip("/").split("/")[-1] if event_uri else None

        event = ProjectEvent(
            id=event_id,
            uri=event_uri,
            name=get_literal(index, event_uri, Predicates.EVENT_NAME),
            description=get_literal(index, event_uri, Predicates.EVENT_DESCRIPTION),
            location=get_literal(index, event_uri, Predicates.EVENT_LOCATION),
            type=get_literal(index, event_uri, Predicates.EVENT_TYPE),
            start=get_literal(index, event_uri, Predicates.EVENT_START),
            end=get_literal(index, event_uri, Predicates.EVENT_END),
            actors=extract_event_actors(index, event_uri),
        )
        events.append(event)

    return events


def extract_digital_objects(
    index: TripleIndex,
    project_uri: str,
    event_uris: List[str],
) -> List[ProjectDigitalObject]:
    """Extract digital objects from graph."""
    digital_objects = []
    seen_uris: Set[str] = set()

    # Direct links from project
    do_uris = get_all_object_uris(index, project_uri, Predicates.DIGITAL_OBJECT)

    # Links from events
    for event_uri in event_uris:
        event_do_uris = get_all_object_uris(index, event_uri, Predicates.DIGITAL_OBJECT)
        do_uris.extend(event_do_uris)

    # Also find via junctions
    for subject in index.all_subjects:
        if not is_junction_uri(subject):
            continue
        if "digitales" not in subject.lower() and "digital" not in subject.lower():
            continue

        # Check if junction links to our events
        junction_event = None
        for t in index.by_subject.get(subject, []):
            pred = t.predicate_canonical_uri or t.predicate_uri
            if pred and "ereignis" in pred.lower() and t.object_uri in event_uris:
                junction_event = t.object_uri
                break

        if not junction_event:
            continue

        # Get digital object from junction
        for t in index.by_subject.get(subject, []):
            pred = t.predicate_canonical_uri or t.predicate_uri
            if pred and ("digital" in pred.lower() or "objekt" in pred.lower()) and t.object_uri:
                if t.object_uri not in do_uris:
                    do_uris.append(t.object_uri)

    for do_uri in do_uris:
        if do_uri in seen_uris:
            continue
        seen_uris.add(do_uri)

        path = get_literal(index, do_uri, Predicates.FILE_PATH)
        if not path:
            # Try institutional predicate
            for t in index.by_subject.get(do_uri, []):
                pred = t.predicate_canonical_uri or t.predicate_uri
                if pred and "dateipfad" in pred.lower() and t.object_value:
                    path = t.object_value
                    break

        if not path:
            continue

        file_name = get_literal(index, do_uri, Predicates.FILE_NAME)
        license_label = get_literal(index, do_uri, Predicates.LICENSE)

        license_obj = None
        if license_label:
            license_obj = ProjectDigitalObjectLicense(label_de=license_label)

        digital_objects.append(ProjectDigitalObject(
            path=path,
            uri=do_uri,
            file_name=file_name,
            license=license_obj,
        ))

    return digital_objects


def extract_year_range(events: List[ProjectEvent]) -> Optional[str]:
    """Extract year range from events."""
    years: Set[str] = set()

    for event in events:
        if event.start:
            year = event.start[:4] if len(event.start) >= 4 else event.start
            if year.isdigit():
                years.add(year)
        if event.end:
            year = event.end[:4] if len(event.end) >= 4 else event.end
            if year.isdigit():
                years.add(year)

    if not years:
        return None

    sorted_years = sorted(years)
    if len(sorted_years) == 1:
        return sorted_years[0]
    return f"{sorted_years[0]}-{sorted_years[-1]}"


def build_project_record(graphs: ProjectGraphs, subject_id: str) -> ProjectRecord:
    """Build ProjectRecord from ProjectGraphs.

    Args:
        graphs: The graph data from get_project_graphs()
        subject_id: The resource ID (UUID) of the project

    Returns:
        Populated ProjectRecord
    """
    index = TripleIndex.from_triples(graphs.triples)
    project_uri = graphs.project_uri

    # Extract core properties
    title = get_literal(index, project_uri, Predicates.TITLE)
    subtitle = get_literal(index, project_uri, Predicates.SUBTITLE)
    description = get_literal(index, project_uri, Predicates.DESCRIPTION)
    if not description:
        description = get_literal(index, project_uri, Predicates.DESCRIPTION_DE)
    image = get_literal(index, project_uri, Predicates.IMAGE)

    # Extract related entities
    institution = extract_institution(index, project_uri)
    categories = extract_categories(index, project_uri)
    project_type = extract_project_type(index, project_uri)
    alternative_titles = extract_alternative_titles(index, project_uri)
    catchphrases = extract_catchphrases(index, project_uri)
    events = extract_events(index, project_uri)

    # Extract digital objects (needs event URIs)
    event_uris = [e.uri for e in events if e.uri]
    digital_objects = extract_digital_objects(index, project_uri, event_uris)

    # Derive year range from events
    year_range = extract_year_range(events)

    # Build institution codes list
    institution_codes = []
    if institution and institution.code:
        institution_codes.append(institution.code.upper())

    # Build category slugs list
    category_slugs = [c.slug for c in categories if c.slug]

    # Determine main event (first one, or one with most actors)
    main_event = None
    if events:
        main_event = max(events, key=lambda e: len(e.actors)) if events else events[0]

    return ProjectRecord(
        subject_id=subject_id,
        uri=project_uri,
        title=title,
        subtitle=subtitle,
        description=description,
        image=image,
        institution=institution,
        categories=categories,
        main_event=main_event,
        events=events,
        alternative_titles=alternative_titles,
        catchphrases=catchphrases,
        project_type=project_type,
        digital_objects=digital_objects,
        year_range=year_range,
        institution_codes=institution_codes,
        category_slugs=category_slugs,
    )
