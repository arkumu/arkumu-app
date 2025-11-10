from __future__ import annotations

from typing import Dict, Tuple

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction

from arkumu.users.models import Organization
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.common.uri_utils import mint_uri, DEFAULT_INSTITUTION_BASE_URI, slugify_uri_part, normalize_text_input
from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin


ENTITY_MAP: Dict[str, Dict[str, object]] = {
    'project': {
        'dataset_slug': 'projekt',
        'fields': [
            ('signatur', 'signatur', 'literal'),
            ('bevorzugterTitel.titel', 'titel', 'literal'),
            ('projektArt', 'projektArt', 'literal'),
            ('hochschule', 'hochschule', 'literal'),
            ('status', 'status', 'literal'),
        ],
    },
    'event': {
        'dataset_slug': 'ereignis',
        'fields': [
            ('ereignisTyp', 'ereignisTyp', 'literal'),
            ('name', 'name', 'literal'),
            ('restricted', 'restricted', 'literal'),
        ],
    },
    'actor': {
        'dataset_slug': 'aktuerin',
        'fields': [
            ('name_de', 'name_de', 'literal'),
            ('geschlecht', 'geschlecht', 'literal'),
            ('geburtsort', 'geburtsort', 'literal'),
            ('gndID', 'gndID', 'literal'),
        ],
    },
    'digital_object': {
        'dataset_slug': 'digitales-objekt',
        'fields': [
            ('entstehungstyp', 'entstehungstyp', 'literal'),
            ('erhaltungstyp', 'erhaltungstyp', 'literal'),
            ('lizenzstatus', 'lizenzstatus', 'literal'),
            ('medientyp', 'medientyp', 'literal'),
        ],
    },
}


def _resolve_current_org(request: HttpRequest, override_code: str | None = None) -> Organization | None:
    coord = BaseCoordinatorMixin()
    if override_code:
        coord.set_current_organization(request, override_code.lower())
    current = coord.get_current_organization(request)
    if current and 'code' in current:
        try:
            return Organization.objects.get(code=current['code'])
        except Organization.DoesNotExist:
            pass
    # Fallback: FUK
    try:
        return Organization.objects.get(code__iexact='fuk')
    except Organization.DoesNotExist:
        return None


def _mint_entity_uri(org: Organization, dataset_slug: str, entity_id: str) -> str:
    base = DEFAULT_INSTITUTION_BASE_URI.rstrip('/')
    return mint_uri(base, org.code, 'entities', dataset_slug, entity_id)


def _mint_property_uri(org: Organization, label: str) -> str:
    base = DEFAULT_INSTITUTION_BASE_URI.rstrip('/')
    return mint_uri(base, org.code, 'properties', slugify_uri_part(label))


def _get_or_create_predicate(org: Organization, label: str) -> Resource:
    prop_uri = _mint_property_uri(org, label)
    predicate, _ = Resource.objects.get_or_create(
        uri=prop_uri,
        defaults={
            'resource_type': ResourceType.PROPERTY,
            'name': label,
            'organization': org,
        }
    )
    return predicate


def _get_or_create_literal(value: str) -> Resource:
    value = normalize_text_input(value, blank_to_none=True)
    if value is None:
        raise ValueError('Empty literal')
    # Let model save generate hash; language/datatype can be extended later
    obj, _ = Resource.objects.get_or_create(
        resource_type=ResourceType.LITERAL,
        value=value,
        defaults={'name': value[:100]}
    )
    return obj


def _get_or_create_iri(org: Organization | None, uri: str) -> Resource:
    obj, _ = Resource.objects.get_or_create(
        uri=uri,
        defaults={
            'resource_type': ResourceType.IRI,
            'name': uri.split('/')[-1],
            'organization': org,
        }
    )
    return obj


@require_POST
def quick_create_entity(request: HttpRequest, entity: str) -> HttpResponse:
    cfg = ENTITY_MAP.get(entity)
    if not cfg:
        return JsonResponse({'ok': False, 'error': 'Unknown entity'}, status=400)

    override_code = request.POST.get('organization')
    org = _resolve_current_org(request, override_code)
    if not org:
        return JsonResponse({'ok': False, 'error': 'Organization not selected'}, status=400)

    dataset_slug: str = cfg['dataset_slug']  # type: ignore
    fields: Tuple[Tuple[str, str, str], ...] | list = cfg['fields']  # type: ignore

    # Require an ID key for subject URI. Prefer domain-specific identifiers (project signatur, actor name_de fallback, etc.)
    provided_id = request.POST.get('signatur') or request.POST.get('id') or request.POST.get('name') or request.POST.get('name_de') or request.POST.get('Digitales Objekt-ID')
    if not provided_id:
        return JsonResponse({'ok': False, 'error': 'ID is required'}, status=400)

    subject_uri = _mint_entity_uri(org, dataset_slug, provided_id)

    try:
        with transaction.atomic():
            subject, _ = Resource.objects.get_or_create(
                uri=subject_uri,
                defaults={
                    'resource_type': ResourceType.ENTITY,
                    'name': str(provided_id)[:100],
                    'organization': org,
                }
            )

            # Create triples for provided human fields
            created = 0
            for human_label, form_key, mode in fields:
                raw_val = request.POST.get(form_key) or request.POST.get(human_label)
                if not raw_val:
                    continue
                predicate = _get_or_create_predicate(org, human_label)
                if mode == 'iri_or_literal' and (raw_val.startswith('http://') or raw_val.startswith('https://')):
                    obj = _get_or_create_iri(None, raw_val)
                else:
                    obj = _get_or_create_literal(raw_val)
                Triple.objects.get_or_create(
                    subject=subject,
                    predicate=predicate,
                    object=obj,
                    source=org,
                    defaults={'is_derived': False}
                )
                created += 1

    except Exception as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    # Tell client which entity list to refresh
    return JsonResponse({'ok': True, 'entity': entity, 'subject_uri': subject_uri})

