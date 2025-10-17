"""
HTMX-enabled views for the metadata entity creation workflow.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, Optional

from django.contrib.auth.mixins import LoginRequiredMixin
from django.forms import formset_factory
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseRedirect,
)
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views import View

from arkumu.metadata.entity_creation import (
    ENTITY_CREATION_CONFIG,
    EntityCreationConfig,
    EntityCreationService,
    EntityInitialDataBuilder,
)
from arkumu.metadata.entity_creation.forms import (
    ActorForm,
    EventForm,
    RoleForm,
)
from arkumu.metadata.models.resources import (
    ClassResource,
    EntityResource,
    PropertyResource,
)
from arkumu.metadata.services.vocabulary_options_service import (
    get_default_metadata_option_map,
)
from arkumu.metadata.views.csv_mapping.mixins.template_helpers import (
    CSVMappingTemplateHelperMixin,
)

logger = logging.getLogger(__name__)


ActorFormSet = formset_factory(ActorForm, extra=0, min_num=0, validate_min=False)
RoleFormSet = formset_factory(RoleForm, extra=0, min_num=0, validate_min=False)

FIELD_OPTION_LOOKUP: Dict[str, Dict[str, str]] = {
    "project": {
        "einliefernde_hochschule_uri": "institution",
        "projektkategorie_uri": "project_category",
        "projektart_uri": "project_type",
        "vorschaubild_uri": "digital_object",
    },
    "event": {
        "project_uri": "project",
    },
}


def configure_uri_widget(form, fragment_url: str) -> None:
    if "uri" not in form.fields:
        return
    widget = form.fields["uri"].widget
    attrs = widget.attrs
    attrs["hx-get"] = fragment_url
    attrs["hx-trigger"] = "change"
    attrs["hx-target"] = "closest form"
    attrs["hx-swap"] = "outerHTML"
    attrs["hx-include"] = "closest form"
    attrs["data-autocomplete"] = "off"


def _render_form_container(
    request,
    *,
    config: EntityCreationConfig,
    form,
    fragment_url: str,
    is_existing: bool,
    success_message: Optional[str] = None,
    error_message: Optional[str] = None,
    submit_label: Optional[str] = None,
    extra_context: Optional[Dict[str, object]] = None,
):
    configure_uri_widget(form, fragment_url)
    form_action = reverse(f"metadata:create_{config.key}")
    context = {
        "form": form,
        "form_action": form_action,
        "form_partial": config.form_partial,
        "entity_type": config.key,
        "entity_title": config.title,
        "is_existing": is_existing,
        "success_message": success_message,
        "error_message": error_message,
        "submit_label": submit_label or f"Create {config.dataset_name}",
        "field_search_urls": {},
    }
    if extra_context:
        field_search_urls = extra_context.get("field_search_urls")
        if field_search_urls:
            context["field_search_urls"] = field_search_urls
        context.update(extra_context)
    return render_to_string(
        "metadata/entity_creation/partials/_form_container.html",
        context,
        request=request,
    )


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


def build_entity_extra_context(entity_key: str, metadata_options: dict) -> Dict[str, object]:
    if entity_key == "event":
        actor_formset = ActorFormSet(
            prefix="actors",
            form_kwargs={"metadata_options": metadata_options},
        )
        role_formset = RoleFormSet(
            prefix="roles",
            form_kwargs={"metadata_options": metadata_options},
        )
        return {
            "actor_formset": actor_formset,
            "role_formset": role_formset,
            "actor_role_forms": list(zip(actor_formset.forms, role_formset.forms)),
            "actor_row_url": reverse("metadata:event_actor_row"),
            "actor_fragment_url": reverse("metadata:entity_creation_fragment", args=["actor"]),
            "role_fragment_url": reverse("metadata:entity_creation_fragment", args=["role"]),
        }
    return {}


class EntityCreationBaseView(LoginRequiredMixin, View):
    """Base view for entity creation pages."""

    entity_key: str = ""

    @property
    def config(self) -> EntityCreationConfig:
        try:
            return ENTITY_CREATION_CONFIG[self.entity_key]
        except KeyError as exc:
            raise ValueError(f"Unknown entity creation key '{self.entity_key}'") from exc

    def get_success_url(self) -> str:
        return reverse(self.config.success_url_name)

    def get_fragment_url(self) -> str:
        return reverse("metadata:entity_creation_fragment", args=[self.entity_key])

    def get_metadata_options(self, organization) -> Dict:
        return get_default_metadata_option_map(organization=organization)

    def get_form(
        self,
        *,
        data=None,
        metadata_options: Optional[dict] = None,
        disable_fields: bool = False,
        initial: Optional[dict] = None,
    ):
        form_class = self.config.form_class
        return form_class(
            data=data,
            metadata_options=metadata_options,
            disable_fields=disable_fields,
            initial=initial,
        )

    def get_context_data(self, *, form, fragment_url: str, **extra):
        is_existing = extra.pop("is_existing", False)
        configure_uri_widget(form, fragment_url)
        context = {
            "form": form,
            "entity_type": self.entity_key,
            "title": self.config.title,
            "description": self.config.description,
            "fragment_url": fragment_url,
            "is_existing": is_existing,
            "field_search_urls": self._build_field_search_urls(),
        }
        context.update(extra)
        return context

    def _build_field_search_urls(self) -> Dict[str, str]:
        lookup = FIELD_OPTION_LOOKUP.get(self.entity_key, {})
        return {
            field_name: reverse(
                "metadata:entity_field_options", args=[self.entity_key, field_name]
            )
            for field_name in lookup
        }

    def get(self, request):
        organization = getattr(request.user, "organization", None)
        if organization is None:
            logger.warning("Entity creation requested without an organization on user.")
            return redirect("metadata:metadata_entry")

        metadata_options = self.get_metadata_options(organization)
        form = self.get_form(metadata_options=metadata_options)
        context = self.get_context_data(
            form=form,
            fragment_url=self.get_fragment_url(),
        )
        return render(request, self.config.template_name, context)

    def post(self, request):
        organization = getattr(request.user, "organization", None)
        if organization is None:
            logger.warning("Entity creation POST without organization.")
            return redirect("metadata:metadata_entry")

        metadata_options = self.get_metadata_options(organization)
        form = self.get_form(
            data=request.POST,
            metadata_options=metadata_options,
        )

        if form.is_valid():
            service = EntityCreationService.for_key(self.entity_key, organization)
            entity, created = service.create_or_update_from_form(form)
            post_response = self.form_valid(
                request,
                form=form,
                entity=entity,
                created=created,
                organization=organization,
                metadata_options=metadata_options,
            )
            if post_response is not None:
                return post_response

            if _is_htmx(request):
                success_message = f"{self.config.dataset_name} erfolgreich erstellt."
                fresh_form = self.get_form(metadata_options=metadata_options)
                html = _render_form_container(
                    request,
                    config=self.config,
                    form=fresh_form,
                    fragment_url=self.get_fragment_url(),
                    is_existing=False,
                    success_message=success_message,
                    extra_context={
                        "field_search_urls": self._build_field_search_urls(),
                    },
                )
                response = HttpResponse(html)
                trigger_payload = {
                    "entity-create-success": {
                        "entity": self.entity_key,
                        "created": created,
                    }
                }
                response["HX-Trigger"] = json.dumps(trigger_payload)
                return response

            return HttpResponseRedirect(self.get_success_url())

        if _is_htmx(request):
            html = _render_form_container(
                request,
                config=self.config,
                form=form,
                fragment_url=self.get_fragment_url(),
                is_existing=getattr(form, "disable_fields", False),
                error_message="Bitte korrigiere die markierten Felder.",
                extra_context={
                    "field_search_urls": self._build_field_search_urls(),
                },
            )
            return HttpResponse(html, status=400)

        context = self.get_context_data(
            form=form,
            fragment_url=self.get_fragment_url(),
        )
        return render(request, self.config.template_name, context)

    def form_valid(
        self,
        request,
        *,
        form,
        entity: EntityResource,
        created: bool,
        organization,
        metadata_options: dict,
    ) -> Optional[HttpResponse]:
        """Hook for subclasses."""
        return None


class ProjectCreationView(EntityCreationBaseView):
    entity_key = "project"


class ActorCreationView(EntityCreationBaseView):
    entity_key = "actor"


class RoleCreationView(EntityCreationBaseView):
    entity_key = "role"


class DigitalObjectCreationView(EntityCreationBaseView):
    entity_key = "digital_object"


class InstitutionCreationView(EntityCreationBaseView):
    entity_key = "institution"


class ProjectCategoryCreationView(EntityCreationBaseView):
    entity_key = "project_category"


class ProjectTypeCreationView(EntityCreationBaseView):
    entity_key = "project_type"


class AlternateTitleCreationView(EntityCreationBaseView):
    entity_key = "alternate_title"


class DescriptionCreationView(EntityCreationBaseView):
    entity_key = "description"


class CatchphraseCreationView(EntityCreationBaseView):
    entity_key = "catchphrase"


class EntityCreationWorkspaceView(LoginRequiredMixin, View):
    """Single-page workspace for managing entity creation forms."""

    template_name = "metadata/entity_creation/workspace.html"

    _preferred_order = [
        "project",
        "event",
        "actor",
        "role",
        "digital_object",
        "institution",
        "project_category",
        "project_type",
        "alternate_title",
        "description",
        "catchphrase",
    ]

    def get(self, request):
        organization = getattr(request.user, "organization", None)
        if organization is None:
            return render(
                request,
                self.template_name,
                {"organization_required": True},
            )

        metadata_options = get_default_metadata_option_map(organization=organization)
        ordered_keys = [key for key in self._preferred_order if key in ENTITY_CREATION_CONFIG]
        # include any additional keys not listed explicitly
        ordered_keys.extend(
            key for key in ENTITY_CREATION_CONFIG.keys() if key not in ordered_keys
        )

        entity_configs = [
            {
                "key": key,
                "title": ENTITY_CREATION_CONFIG[key].title,
                "label": ENTITY_CREATION_CONFIG[key].dataset_name,
            }
            for key in ordered_keys
        ]

        if not entity_configs:
            return render(
                request,
                self.template_name,
                {
                    "organization": organization,
                    "entity_configs": [],
                    "initial_form_html": "",
                },
            )

        active_key = request.GET.get("entity") or entity_configs[0]["key"]
        if active_key not in ENTITY_CREATION_CONFIG:
            active_key = entity_configs[0]["key"]

        config = ENTITY_CREATION_CONFIG[active_key]
        form = config.form_class(metadata_options=metadata_options)
        fragment_url = reverse("metadata:entity_creation_fragment", args=[active_key])
        extra_context = build_entity_extra_context(active_key, metadata_options)
        extra_context = {
            **extra_context,
            "field_search_urls": {
                field_name: reverse("metadata:entity_field_options", args=[active_key, field_name])
                for field_name in FIELD_OPTION_LOOKUP.get(active_key, {})
            },
        }

        initial_form_html = _render_form_container(
            request,
            config=config,
            form=form,
            fragment_url=fragment_url,
            is_existing=False,
            extra_context=extra_context,
        )

        context = {
            "organization": organization,
            "entity_configs": entity_configs,
            "active_key": active_key,
            "initial_form_html": initial_form_html,
        }
        return render(request, self.template_name, context)


class EventCreationView(EntityCreationBaseView):
    entity_key = "event"

    def get_context_data(
        self,
        *,
        form,
        fragment_url: str,
        actor_formset=None,
        role_formset=None,
        actor_row_url: Optional[str] = None,
        **extra,
    ):
        actor_role_forms = []
        if actor_formset is not None and role_formset is not None:
            actor_role_forms = list(zip(actor_formset.forms, role_formset.forms))

        context = super().get_context_data(
            form=form,
            fragment_url=fragment_url,
            actor_formset=actor_formset,
            role_formset=role_formset,
            actor_row_url=actor_row_url,
            actor_role_forms=actor_role_forms,
            **extra,
        )
        return context

    def get(self, request):
        organization = getattr(request.user, "organization", None)
        if organization is None:
            return redirect("metadata:metadata_entry")

        metadata_options = self.get_metadata_options(organization)
        form = self.get_form(metadata_options=metadata_options)
        actor_formset = ActorFormSet(
            prefix="actors",
            form_kwargs={"metadata_options": metadata_options},
        )
        role_formset = RoleFormSet(
            prefix="roles",
            form_kwargs={"metadata_options": metadata_options},
        )
        context = self.get_context_data(
            form=form,
            fragment_url=self.get_fragment_url(),
            actor_formset=actor_formset,
            role_formset=role_formset,
            actor_row_url=reverse("metadata:event_actor_row"),
            actor_fragment_url=reverse("metadata:entity_creation_fragment", args=["actor"]),
            role_fragment_url=reverse("metadata:entity_creation_fragment", args=["role"]),
        )
        return render(request, self.config.template_name, context)

    def post(self, request):
        organization = getattr(request.user, "organization", None)
        if organization is None:
            return redirect("metadata:metadata_entry")

        metadata_options = self.get_metadata_options(organization)
        form = self.get_form(
            data=request.POST,
            metadata_options=metadata_options,
        )
        actor_formset = ActorFormSet(
            request.POST,
            prefix="actors",
            form_kwargs={"metadata_options": metadata_options},
        )
        role_formset = RoleFormSet(
            request.POST,
            prefix="roles",
            form_kwargs={"metadata_options": metadata_options},
        )

        forms_valid = (
            form.is_valid()
            and actor_formset.is_valid()
            and role_formset.is_valid()
        )

        if forms_valid:
            service = EntityCreationService.for_key(self.entity_key, organization)
            event_entity, created = service.create_or_update_from_form(form)
            self._link_event_to_project(
                organization=organization,
                event_entity=event_entity,
                project_uri=form.cleaned_data.get("project_uri"),
            )
            self._persist_actor_roles(
                organization=organization,
                event_entity=event_entity,
                actor_formset=actor_formset,
                role_formset=role_formset,
            )
            post_response = self.form_valid(
                request,
                form=form,
                entity=event_entity,
                created=created,
                organization=organization,
                metadata_options=metadata_options,
            )
            if post_response is not None:
                return post_response

            if _is_htmx(request):
                fresh_form = self.get_form(metadata_options=metadata_options)
                extra_context = build_entity_extra_context("event", metadata_options)
                extra_context = {
                    **extra_context,
                    "field_search_urls": self._build_field_search_urls(),
                }
                html = _render_form_container(
                    request,
                    config=self.config,
                    form=fresh_form,
                    fragment_url=self.get_fragment_url(),
                    is_existing=False,
                    success_message="Ereignis erfolgreich gespeichert.",
                    extra_context=extra_context,
                )
                response = HttpResponse(html)
                trigger_payload = {
                    "entity-create-success": {
                        "entity": self.entity_key,
                        "created": created,
                    }
                }
                response["HX-Trigger"] = json.dumps(trigger_payload)
                return response
            return HttpResponseRedirect(self.get_success_url())

        if _is_htmx(request):
            extra_context = {
                "actor_formset": actor_formset,
                "role_formset": role_formset,
                "actor_role_forms": list(zip(actor_formset.forms, role_formset.forms)),
                "actor_row_url": reverse("metadata:event_actor_row"),
                "actor_fragment_url": reverse("metadata:entity_creation_fragment", args=["actor"]),
                "role_fragment_url": reverse("metadata:entity_creation_fragment", args=["role"]),
                "field_search_urls": self._build_field_search_urls(),
            }
            html = _render_form_container(
                request,
                config=self.config,
                form=form,
                fragment_url=self.get_fragment_url(),
                is_existing=getattr(form, "disable_fields", False),
                error_message="Bitte korrigiere die markierten Felder.",
                extra_context=extra_context,
            )
            return HttpResponse(html, status=400)

        context = self.get_context_data(
            form=form,
            fragment_url=self.get_fragment_url(),
            actor_formset=actor_formset,
            role_formset=role_formset,
            actor_row_url=reverse("metadata:event_actor_row"),
            actor_fragment_url=reverse("metadata:entity_creation_fragment", args=["actor"]),
            role_fragment_url=reverse("metadata:entity_creation_fragment", args=["role"]),
        )
        return render(request, self.config.template_name, context)

    def _link_event_to_project(self, *, organization, event_entity, project_uri: Optional[str]) -> None:
        if not project_uri:
            return

        base_uri = f"http://arkumu.org/data/{organization.code}"
        property_resource, _ = PropertyResource.get_or_create(
            uri=f"{base_uri}/properties/ereignis",
            name="Ereignis",
        )
        project_entity, _ = EntityResource.get_or_create(project_uri)
        project_entity.set_property(property_resource, event_entity)

    def _persist_actor_roles(
        self,
        *,
        organization,
        event_entity: EntityResource,
        actor_formset,
        role_formset,
    ) -> None:
        base_uri = f"http://arkumu.org/data/{organization.code}"
        actor_service = EntityCreationService.for_key("actor", organization)
        role_service = EntityCreationService.for_key("role", organization)

        actor_prop, _ = PropertyResource.get_or_create(
            uri=f"{base_uri}/properties/akteurin-im-ereignis",
            name="AkteurIn im Ereignis",
        )
        event_prop, _ = PropertyResource.get_or_create(
            uri=f"{base_uri}/properties/im-ereignis",
            name="im Ereignis",
        )
        role_prop, _ = PropertyResource.get_or_create(
            uri=f"{base_uri}/properties/rollen-der-akteurin-im-ereignis",
            name="Rollen der AkteurIn im Ereignis",
        )
        membership_class, _ = ClassResource.get_or_create(
            uri=f"{base_uri}/types/akteurin-ereignis-kreuztabelle",
            name="AkteurIn_Ereignis_Kreuztabelle",
        )

        for actor_form, role_form in zip(actor_formset, role_formset):
            if not (actor_form.has_changed() or role_form.has_changed()):
                continue
            if not (actor_form.is_valid() and role_form.is_valid()):
                continue

            actor_entity, _ = actor_service.create_or_update_from_form(actor_form)
            role_entity, _ = role_service.create_or_update_from_form(role_form)

            membership_entity, _ = EntityResource.create_by_organization_and_dataset_name(
                organization=organization,
                dataset_name="AkteurIn_Ereignis_Kreuztabelle",
            )
            membership_entity.set_type(membership_class)
            membership_entity.set_property(actor_prop, actor_entity)
            membership_entity.set_property(event_prop, event_entity)
            membership_entity.set_property(role_prop, role_entity)


class EntityFormFragmentView(LoginRequiredMixin, CSVMappingTemplateHelperMixin, View):
    """Render the form fields fragment for HTMX requests."""

    def get(self, request, entity_key: str):
        if request.headers.get("HX-Request", "").lower() != "true":
            return HttpResponseBadRequest("HTMX requests only")

        organization = getattr(request.user, "organization", None)
        if organization is None:
            return HttpResponseBadRequest("Organization required")

        try:
            config = ENTITY_CREATION_CONFIG[entity_key]
        except KeyError:
            return HttpResponseBadRequest("Unknown entity")

        metadata_options = get_default_metadata_option_map(organization=organization)
        service = EntityCreationService(config=config, organization=organization)
        initial = {}
        disable_fields = False

        selected_uri = request.GET.get("uri")
        if selected_uri:
            initial_builder = EntityInitialDataBuilder(service)
            initial_data = initial_builder.get_initial_for_uri(selected_uri)
            if initial_data is not None:
                initial = initial_data
                if "uri" not in initial:
                    initial["uri"] = selected_uri
                disable_fields = True
            else:
                initial = {"uri": selected_uri}

        if disable_fields:
            disable_fields = False

        form = config.form_class(
            metadata_options=metadata_options,
            disable_fields=disable_fields,
            initial=initial or None,
        )
        if selected_uri:
            form.initial["uri"] = selected_uri

        fragment_url = reverse("metadata:entity_creation_fragment", args=[entity_key])
        extra_context = build_entity_extra_context(entity_key, metadata_options)
        extra_context = {
            **extra_context,
            "field_search_urls": {
                field_name: reverse("metadata:entity_field_options", args=[entity_key, field_name])
                for field_name in FIELD_OPTION_LOOKUP.get(entity_key, {})
            },
        }

        html = _render_form_container(
            request,
            config=config,
            form=form,
            fragment_url=fragment_url,
            is_existing=disable_fields,
            extra_context=extra_context,
        )
        return HttpResponse(html)


class EntityFieldOptionsView(LoginRequiredMixin, View):
    """HTMX endpoint for filtering select options in entity creation forms."""

    def get(self, request: HttpRequest, entity_key: str, field_name: str) -> HttpResponse:
        if request.headers.get("HX-Request", "").lower() != "true":
            return HttpResponseBadRequest("HTMX request expected")

        option_lookup = FIELD_OPTION_LOOKUP.get(entity_key, {})
        option_key = option_lookup.get(field_name)
        if option_key is None:
            return HttpResponseBadRequest("Unsupported field")

        organization = getattr(request.user, "organization", None)
        if organization is None:
            return HttpResponseBadRequest("Organization required")

        metadata_options = get_default_metadata_option_map(organization).copy()
        options = list(metadata_options.get(option_key, []))

        query = (request.GET.get("q") or "").strip()
        if query:
            lowered = query.lower()
            options = [opt for opt in options if lowered in opt[1].lower()]

        metadata_options[option_key] = options

        config = ENTITY_CREATION_CONFIG.get(entity_key)
        if config is None:
            return HttpResponseBadRequest("Unknown entity")

        form_class = config.form_class
        form = form_class(metadata_options=metadata_options)

        if field_name in request.GET:
            selected_value = request.GET.get(field_name)
            if selected_value:
                form.fields[field_name].initial = selected_value
        else:
            selected_list = request.GET.getlist(field_name)
            if selected_list:
                form.fields[field_name].initial = selected_list

        field = form[field_name]
        context = {
            "field": field,
            "field_name": field_name,
            "query": query,
            "search_url": reverse(
                "metadata:entity_field_options", args=[entity_key, field_name]
            ),
        }
        return render(
            request,
            "metadata/entity_creation/partials/_searchable_select_field.html",
            context,
        )


class EventActorRowView(LoginRequiredMixin, CSVMappingTemplateHelperMixin, View):
    """Return a single actor/role row fragment for HTMX additions."""

    def get(self, request):
        if request.headers.get("HX-Request", "").lower() != "true":
            return HttpResponseBadRequest("HTMX requests only")

        organization = getattr(request.user, "organization", None)
        if organization is None:
            return HttpResponseBadRequest("Organization required")

        metadata_options = get_default_metadata_option_map(organization=organization)
        current_index = int(request.GET.get("actors-TOTAL_FORMS", 0))
        actor_prefix = f"actors-{current_index}"
        role_prefix = f"roles-{current_index}"

        actor_form = ActorForm(
            metadata_options=metadata_options,
            prefix=actor_prefix,
        )
        role_form = RoleForm(
            metadata_options=metadata_options,
            prefix=role_prefix,
        )

        context = {
            "actor_form": actor_form,
            "role_form": role_form,
            "index": current_index,
        }
        row_html = render_to_string(
            "metadata/entity_creation/partials/_event_actor_role_row.html",
            context,
            request=request,
        )
        new_total = current_index + 1
        oob_updates = {
            "id_actors-TOTAL_FORMS": f'<input type="hidden" name="actors-TOTAL_FORMS" value="{new_total}" id="id_actors-TOTAL_FORMS">',
            "id_roles-TOTAL_FORMS": f'<input type="hidden" name="roles-TOTAL_FORMS" value="{new_total}" id="id_roles-TOTAL_FORMS">',
        }
        html = self.build_oob_response(row_html, oob_updates)
        return HttpResponse(html)
