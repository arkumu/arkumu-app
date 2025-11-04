from __future__ import annotations

from typing import Optional

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from arkumu.metadata.controlled_vocabularies.forms import ControlledVocabularyForm
from arkumu.metadata.controlled_vocabularies.registry import (
    get_vocabulary_config,
    list_vocabulary_keys,
)
from arkumu.metadata.controlled_vocabularies.service import ControlledVocabularyService
from arkumu.metadata.models.resource import Resource
from arkumu.metadata.models.triples import Triple
from arkumu.users.mixins import GeneralLoginRequiredMixin


def user_can_edit_vocabularies(user) -> bool:
    return getattr(user, "is_staff", False) or (
        hasattr(user, "has_role") and user.has_role("researcher")
    )


class ControlledVocabularyPermissionMixin(GeneralLoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not user_can_edit_vocabularies(request.user):
            raise PermissionDenied("Insufficient permissions to manage controlled vocabularies.")
        return super().dispatch(request, *args, **kwargs)


class ControlledVocabularyOverviewView(ControlledVocabularyPermissionMixin, TemplateView):
    template_name = "metadata/controlled_vocabularies/overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        vocabularies = []
        for key in list_vocabulary_keys():
            config = get_vocabulary_config(key)
            count = Triple.objects.filter(
                predicate__uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
                object__uri=config.class_uri,
                source__isnull=True,
            ).count()
            vocabularies.append(
                {
                    "key": key,
                    "config": config,
                    "count": count,
                }
            )
        vocabularies.sort(key=lambda item: item["config"].display_name.lower())
        context["vocabularies"] = vocabularies
        return context


class ControlledVocabularyEntryListView(ControlledVocabularyPermissionMixin, TemplateView):
    template_name = "metadata/controlled_vocabularies/list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        vocab_key = self.kwargs["vocab_key"]
        config = get_vocabulary_config(vocab_key)
        service = ControlledVocabularyService(vocab_key)

        search_query = self.request.GET.get("q")
        entries = service.list_entries(search=search_query)

        context.update(
            {
                "config": config,
                "vocab_key": vocab_key,
                "entries": entries,
                "search_query": search_query or "",
            }
        )
        return context


class ControlledVocabularyEntryManageView(ControlledVocabularyPermissionMixin, View):
    template_name = "metadata/controlled_vocabularies/form.html"

    def get(self, request, *args, **kwargs):
        vocab_key = kwargs["vocab_key"]
        config = get_vocabulary_config(vocab_key)
        service = ControlledVocabularyService(vocab_key)

        resource = self._get_resource(kwargs.get("resource_id"))
        if resource and resource.canonical_uri and not resource.canonical_uri.startswith(config.class_uri):
            raise PermissionDenied("Resource does not belong to this vocabulary.")

        if resource:
            initial = service.get_initial(resource)
        else:
            initial = {}
            if config.slug_prefix:
                initial.setdefault("slug", config.slug_prefix)

        form = ControlledVocabularyForm(
            config=config,
            service=service,
            entry=resource,
            initial=initial,
        )
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "config": config,
                "resource": resource,
                "vocab_key": vocab_key,
            },
        )

    def post(self, request, *args, **kwargs):
        vocab_key = kwargs["vocab_key"]
        config = get_vocabulary_config(vocab_key)
        service = ControlledVocabularyService(vocab_key)
        resource = self._get_resource(kwargs.get("resource_id"))

        form = ControlledVocabularyForm(
            data=request.POST,
            config=config,
            service=service,
            entry=resource,
        )
        if form.is_valid():
            try:
                service.save(form.cleaned_data, resource=resource)
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                if resource:
                    messages.success(request, "Vocabulary entry updated.")
                else:
                    messages.success(request, "Vocabulary entry created.")
                return redirect(reverse("metadata:controlled_vocab_list", args=[vocab_key]))

        return render(
            request,
            self.template_name,
            {
                "form": form,
                "config": config,
                "resource": resource,
                "vocab_key": vocab_key,
            },
        )

    def _get_resource(self, resource_id: Optional[str]) -> Optional[Resource]:
        if not resource_id:
            return None
        return get_object_or_404(Resource, pk=resource_id)
