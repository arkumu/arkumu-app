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

logger = logging.getLogger(__name__)


class SimpleProjectEntryView(LoginRequiredMixin, View):
    template_name = "metadata/simple_project_entry/entry.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        organization = request.user.organization
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
        })

    def post(self, request: HttpRequest) -> HttpResponse:
        organization = request.user.organization
        if not organization:
            messages.error(request, "Keine Organisation zugeordnet.")
            return redirect("metadata:metadata_entry")

        title = request.POST.get("titel", "").strip()
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
                projektart_uri=projektart_uri or None,
                ereignis_uris=ereignis_uris or None,
                akteure_uris=akteure_uris or None,
            )

            # Handle file upload digital object
            upload_s3_key = request.POST.get("upload_s3_key", "").strip()
            if upload_s3_key:
                service.create_digital_object(
                    project=entity,
                    s3_key=upload_s3_key,
                    file_name=request.POST.get("upload_file_name", ""),
                    content_type=request.POST.get("upload_content_type", ""),
                    file_size=int(request.POST.get("upload_file_size", 0)),
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
    """HTMX endpoint: search existing Ereignis or Akteure by name."""
    query = request.GET.get("q", "").strip()
    organization = request.user.organization
    if not query or len(query) < 2 or not organization:
        return render(request, "metadata/simple_project_entry/partials/_search_results.html", {
            "results": [],
            "dataset_name": dataset_name,
            "query": query,
        })

    # Find entities in the given dataset via isPartOf
    dataset_resources = Resource.objects.filter(
        name__iexact=dataset_name,
        resource_type=ResourceType.IRI,
    )
    entity_ids = (
        Triple.objects.filter(
            predicate__uri="http://purl.org/dc/terms/isPartOf",
            object__in=dataset_resources,
        )
        .values_list("subject_id", flat=True)
    )

    results = (
        Resource.objects.filter(
            id__in=entity_ids,
            resource_type=ResourceType.ENTITY,
        )
        .filter(name__icontains=query)
        .order_by("name")[:20]
    )

    return render(request, "metadata/simple_project_entry/partials/_search_results.html", {
        "results": results,
        "dataset_name": dataset_name,
        "query": query,
    })
