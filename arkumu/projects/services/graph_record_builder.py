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


def extract_description(
    index: TripleIndex,
    project_uri: str,
    org_code: Optional[str] = None,
    events: Optional[List[ProjectEvent]] = None,
) -> Optional[str]:
    """Extract description from graph based on organization.

    Each org stores descriptions differently:
    - FUK/RSH/DET: Project -> beschreibung -> entity -> beschreibung literal
    - KHM: Project -> ereignisbeschreibung -> literal directly
    - HMT: No project description, use first event's deutsche-beschreibung
    """
    org = (org_code or "").lower()

    # HMT: description is on events, not projects
    if org == "hmt":
        if events:
            for event in events:
                if event.description:
                    return event.description
        return None

    # KHM: ereignisbeschreibung directly on project
    if org == "khm":
        desc = get_literal(index, project_uri, Predicates.EVENT_DESCRIPTION)
        if desc and not desc.startswith("http"):
            return desc
        return None

    # FUK/RSH/DET (canonicals): beschreibung links to entity with literal
    # First check if beschreibung is a direct literal
    desc = get_literal(index, project_uri, Predicates.DESCRIPTION)
    if desc and not desc.startswith("http"):
        return desc

    # Follow link to beschreibung entity
    desc_uri = get_object_uri(index, project_uri, Predicates.DESCRIPTION)
    if desc_uri:
        # Get literal from the linked entity
        desc = get_literal(index, desc_uri, Predicates.DESCRIPTION)
        if desc:
            return desc
        # Also try deutsche-beschreibung on the linked entity
        desc = get_literal(index, desc_uri, Predicates.DESCRIPTION_DE)
        if desc:
            return desc

    return None


def extract_categories(index: TripleIndex, project_uri: str) -> List[ProjectCategory]:
    """Extract categories from graph."""
    cat_uris = get_all_object_uris(index, project_uri, Predicates.CATEGORY)
    categories = []

    for cat_uri in cat_uris:
        # Try deutscher-name first (leaf label), fall back to breadcrumb
        cat_name = get_literal(index, cat_uri, Predicates.ACTOR_NAME)
        if not cat_name:
            cat_name = get_literal(index, cat_uri, Predicates.CATEGORY_NAME)

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


def _get_role_property_uris_from_schema(event_uri: str) -> Set[str]:
    """Extract role property URIs from schema manifest based on org code."""
    role_uris = set()

    # Extract org code from URI (e.g., "hmt" from "http://arkumu.org/data/hmt/...")
    if not event_uri or "/data/" not in event_uri:
        return role_uris

    try:
        parts = event_uri.split("/data/")
        if len(parts) < 2:
            return role_uris
        org_code = parts[1].split("/")[0]

        from arkumu.metadata.models import Mapping
        mapping = Mapping.get_active_for_organization(org_code)
        if not mapping:
            return role_uris

        schema = mapping.mapping_config.get('schema_manifest', {})
        for ds_config in schema.values():
            rel_contexts = ds_config.get('relationship_contexts', [])
            for ctx in rel_contexts:
                # Add both context_property_uri and secondary_property_uri
                ctx_uri = ctx.get('context_property_uri')
                if ctx_uri and 'rolle' in ctx_uri.lower():
                    role_uris.add(ctx_uri)
                sec_uri = ctx.get('secondary_property_uri')
                if sec_uri and 'rolle' in sec_uri.lower():
                    role_uris.add(sec_uri)
    except Exception:
        # Silently fail if schema extraction fails
        pass

    return role_uris


def extract_event_actors(index: TripleIndex, event_uri: str) -> List[ProjectEventActor]:
    """Extract actors for an event from junction entities."""
    actors = []
    seen_names: Set[str] = set()

    # Extract org code and get role property URIs from schema manifest
    role_property_uris = _get_role_property_uris_from_schema(event_uri)

    # Find junctions pointing to this event
    for subject in index.all_subjects:
        if not is_junction_uri(subject):
            continue

        # Check if junction links to this event
        junction_event = get_object_uri(index, subject, Predicates.IM_EREIGNIS)
        if not junction_event:
            junction_event = get_object_uri(index, subject, Predicates.EVENT)
        # KHM: junctions link to Grundereignis via projekt predicate
        if not junction_event:
            junction_event = get_object_uri(index, subject, Predicates.PROJEKT)

        # Also check for institutional FK predicates (ereignis-nr-fk, projekt-fk, etc.)
        if not junction_event:
            for t in index.by_subject.get(subject, []):
                pred = t.predicate_canonical_uri or t.predicate_uri
                if pred and (
                    ("ereignis" in pred.lower() and "fk" in pred.lower())
                    or ("proj" in pred.lower() and "fk" in pred.lower())
                ):
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

        # Get roles - try both URI links (FUK/RSH/DET) and literal values (HMT/KHM)
        roles = []

        # Method 1: Role URIs (canonical - FUK/RSH/DET)
        role_uris = get_all_object_uris(index, subject, Predicates.ROLE_LINK)
        for role_uri in role_uris:
            role_name = get_literal(index, role_uri, Predicates.ROLE_NAME)
            if not role_name:
                role_name = get_literal(index, role_uri, Predicates.ACTOR_NAME)
            if role_name:
                roles.append(role_name)

        # Method 2: Role literals from org-specific properties (HMT/KHM)
        if not roles and role_property_uris:
            for t in index.by_subject.get(subject, []):
                pred_uri = t.predicate_uri or t.predicate_canonical_uri
                if pred_uri in role_property_uris and t.object_value:
                    roles.append(t.object_value)

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

    # Direct event links from project
    event_uris = get_all_object_uris(index, project_uri, Predicates.EVENT)

    # Find events that link TO this project (incoming links via PROJEKT predicate)
    # This handles KHM Grundereignis which links to project, not the other way around
    for subject in index.all_subjects:
        if subject in event_uris or subject == project_uri:
            continue
        # Check if this entity links to our project via PROJEKT predicate
        project_link = get_object_uri(index, subject, Predicates.PROJEKT)
        if project_link == project_uri:
            event_uris.append(subject)

    for event_uri in event_uris:
        event_id = event_uri.rstrip("/").split("/")[-1] if event_uri else None

        # Get event description - try ereignisbeschreibung first, then deutsche-beschreibung (HMT)
        event_desc = get_literal(index, event_uri, Predicates.EVENT_DESCRIPTION)
        if not event_desc:
            event_desc = get_literal(index, event_uri, Predicates.DESCRIPTION_DE)

        event = ProjectEvent(
            id=event_id,
            uri=event_uri,
            name=get_literal(index, event_uri, Predicates.EVENT_NAME),
            description=event_desc,
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

    # Batch fetch S3 metadata for all digital objects
    from arkumu.storage.models import S3FileObject
    s3_by_uri = {}
    if do_uris:
        s3_objects = S3FileObject.objects.filter(
            related_resource__uri__in=do_uris
        ).select_related('related_resource')
        for s3_obj in s3_objects:
            if s3_obj.related_resource and s3_obj.related_resource.uri:
                s3_by_uri[s3_obj.related_resource.uri] = s3_obj

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

        # Enrich with S3 metadata if available
        s3_obj = s3_by_uri.get(do_uri)
        storage_key = None
        storage_status = None
        resource_id = None
        content_type = None
        size_bytes = None
        checksum = None
        access_url = None

        if s3_obj:
            storage_key = s3_obj.s3_key
            storage_status = s3_obj.status
            resource_id = str(s3_obj.related_resource_id) if s3_obj.related_resource_id else None
            content_type = s3_obj.content_type
            size_bytes = s3_obj.file_size_bytes
            checksum = s3_obj.sha256_checksum
            access_url = s3_obj.s3_url
            if not file_name:
                file_name = s3_obj.file_name

        digital_objects.append(ProjectDigitalObject(
            path=path,
            uri=do_uri,
            file_name=file_name,
            license=license_obj,
            storage_key=storage_key,
            storage_status=storage_status,
            resource_id=resource_id,
            content_type=content_type,
            size_bytes=size_bytes,
            checksum=checksum,
            access_url=access_url,
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

    # Extract institution first (needed for org-specific logic)
    institution = extract_institution(index, project_uri)
    org_code = institution.code if institution else extract_code_from_uri(project_uri)

    # Extract events (needed for HMT description extraction)
    events = extract_events(index, project_uri)

    # Extract core properties
    title = get_literal(index, project_uri, Predicates.TITLE)
    subtitle = get_literal(index, project_uri, Predicates.SUBTITLE)
    description = extract_description(index, project_uri, org_code=org_code, events=events)
    image = get_literal(index, project_uri, Predicates.IMAGE)

    # Extract remaining related entities
    categories = extract_categories(index, project_uri)
    project_type = extract_project_type(index, project_uri)
    alternative_titles = extract_alternative_titles(index, project_uri)
    catchphrases = extract_catchphrases(index, project_uri)

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
