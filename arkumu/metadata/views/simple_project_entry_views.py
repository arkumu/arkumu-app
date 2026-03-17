"""
Views for the simple project entry page.
Single-page form for creating projects with Ereignis/Akteure links and file uploads.
"""
from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View
from django.views.decorators.http import require_GET

from arkumu.metadata.controlled_vocabularies.service import ControlledVocabularyService
from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.simple_project_entry_service import SimpleProjectEntryService
from arkumu.users.mixins import general_login_required
from arkumu.users.models import Organization

logger = logging.getLogger(__name__)


def _get_active_organization(request: HttpRequest) -> Organization | None:
    """Get the active organization from session, falling back to user's organization."""
    session_org = request.session.get("current_organization")
    if session_org and session_org.get("id"):
        try:
            return Organization.objects.get(id=session_org["id"])
        except Organization.DoesNotExist:
            pass
    return getattr(request.user, "organization", None)


class SimpleProjectEntryView(LoginRequiredMixin, View):
    template_name = "metadata/simple_project_entry/entry.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        organization = _get_active_organization(request)
        if not organization:
            messages.error(request, "Keine Organisation zugeordnet.")
            return redirect("metadata:metadata_entry")

        mapping = Mapping.get_active_for_organization(organization)
        if not mapping:
            messages.warning(
                request,
                "Kein aktives Mapping gefunden. Bitte kontaktieren Sie Ihren Administrator.",
            )

        projektart_choices = self._get_projektart_choices()
        return render(request, self.template_name, {
            "projektart_choices": projektart_choices,
            "organization": organization,
        })

    def post(self, request: HttpRequest) -> HttpResponse:
        organization = _get_active_organization(request)
        if not organization:
            messages.error(request, "Keine Organisation zugeordnet.")
            return redirect("metadata:metadata_entry")

        title = request.POST.get("titel", "").strip()
        alternativer_titel = request.POST.get("alternativer_titel", "").strip()
        projektart_uri = request.POST.get("projektart_uri", "").strip()
        ereignis_uris = request.POST.getlist("ereignis_uris")
        akteure_uris = request.POST.getlist("akteure_uris")

        if not title:
            messages.error(request, "Titel ist erforderlich.")
            return self.get(request)

        service = SimpleProjectEntryService(organization=organization)
        try:
            entity = service.create_project(
                title=title,
                alternativer_titel=alternativer_titel or None,
                projektart_uri=projektart_uri or None,
                ereignis_uris=ereignis_uris or None,
                akteure_uris=akteure_uris or None,
            )

            # Handle file uploads (multiple digital objects)
            upload_s3_keys = request.POST.getlist("upload_s3_keys")
            upload_file_names = request.POST.getlist("upload_file_names")
            upload_content_types = request.POST.getlist("upload_content_types")
            upload_file_sizes = request.POST.getlist("upload_file_sizes")
            for i, s3_key in enumerate(upload_s3_keys):
                if not s3_key.strip():
                    continue
                service.create_digital_object(
                    project=entity,
                    s3_key=s3_key.strip(),
                    file_name=upload_file_names[i] if i < len(upload_file_names) else "",
                    content_type=upload_content_types[i] if i < len(upload_content_types) else "",
                    file_size=int(upload_file_sizes[i]) if i < len(upload_file_sizes) else 0,
                )

            messages.success(request, f"Projekt '{title}' wurde erfolgreich erstellt.")
            return redirect("metadata:entity_creation_workspace")
        except Exception:
            logger.exception("Failed to create project")
            messages.error(request, "Fehler beim Erstellen des Projekts.")
            return self.get(request)

    def _get_projektart_choices(self):
        try:
            cv_service = ControlledVocabularyService("project_types")
            entries = cv_service.list_entries()
            return [(e.resource.uri, e.label) for e in entries]
        except Exception:
            logger.exception("Failed to load Projektart choices")
            return []


@general_login_required
@require_GET
def search_entities(request: HttpRequest, dataset_name: str) -> HttpResponse:
    """HTMX endpoint: search existing Ereignis or Akteure by name.

    Fully mapping-aware: reads the active mapping's schema_manifest to find
    which datasets match the requested entity type and which property holds
    the entity name. Works for all orgs.
    """
    query = request.GET.get("q", "").strip()
    organization = _get_active_organization(request)
    search_config = _ENTITY_SEARCH_CONFIG.get(dataset_name)

    if not query or len(query) < 2 or not organization or not search_config:
        return render(request, "metadata/simple_project_entry/partials/_search_results.html", {
            "results": [],
            "dataset_name": dataset_name,
            "query": query,
        })

    # Read the active mapping to resolve org-specific URIs
    mapping = Mapping.get_active_for_organization(organization)
    if not mapping or not mapping.mapping_config:
        return render(request, "metadata/simple_project_entry/partials/_search_results.html", {
            "results": [],
            "dataset_name": dataset_name,
            "query": query,
        })

    # From the schema_manifest, find datasets whose entity_type.canonical_uri
    # matches our target, and collect the name property URIs
    canonical_type_uri = search_config["canonical_type_uri"]
    canonical_name_uri = search_config["canonical_name_uri"]
    manifest = mapping.mapping_config.get("schema_manifest", {})

    type_uris = set()   # org-specific rdf:type URIs for this entity type
    name_pred_uris = set()  # org-specific name predicate URIs

    for ds_name, ds_config in manifest.items():
        if not isinstance(ds_config, dict):
            continue
        entity_type = ds_config.get("entity_type", {})
        if entity_type.get("canonical_uri") != canonical_type_uri:
            continue

        # This dataset matches our entity type
        type_uris.add(entity_type.get("uri", ""))

        # Find the name property in this dataset's properties
        for prop_name, prop_config in ds_config.get("properties", {}).items():
            if prop_config.get("canonical_uri") == canonical_name_uri:
                name_pred_uris.add(prop_config.get("uri", ""))

    if not type_uris or not name_pred_uris:
        return render(request, "metadata/simple_project_entry/partials/_search_results.html", {
            "results": [],
            "dataset_name": dataset_name,
            "query": query,
        })

    from django.db.models import Q

    # Get entities with the correct rdf:type
    rdf_type_uri = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    typed_entity_uris = (
        Triple.objects.filter(
            predicate__uri=rdf_type_uri,
            object__uri__in=type_uris,
            source=organization,
        )
        .values_list("subject__uri", flat=True)
    )

    # Search by the name predicate URIs from the mapping
    matching_triples = (
        Triple.objects.filter(
            predicate__uri__in=name_pred_uris,
            subject__uri__in=typed_entity_uris,
            source=organization,
            object__resource_type=ResourceType.LITERAL,
            object__value__icontains=query,
        )
        .select_related("subject", "object")
        .order_by("object__value")[:20]
    )

    results = []
    seen_uris = set()
    for triple in matching_triples:
        uri = triple.subject.uri
        if uri in seen_uris:
            continue
        seen_uris.add(uri)
        results.append({"uri": uri, "label": triple.object.value or uri.rsplit("/", 1)[-1]})

    return render(request, "metadata/simple_project_entry/partials/_search_results.html", {
        "results": results,
        "dataset_name": dataset_name,
        "query": query,
    })


# Canonical URIs for entity type + name property — used to look up
# the org-specific URIs from the mapping's schema_manifest
_ENTITY_SEARCH_CONFIG = {
    "Ereignis": {
        "canonical_type_uri": "http://arkumu.org/data/types/ereignis",
        "canonical_name_uri": "http://arkumu.org/data/properties/ereignisname",
    },
    "Akteurin": {
        "canonical_type_uri": "http://arkumu.org/data/types/akteurin",
        "canonical_name_uri": "http://arkumu.org/data/properties/deutscher-name",
    },
}
