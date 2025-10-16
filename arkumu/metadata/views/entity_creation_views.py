"""Views and forms for creating metadata-backed entities (projects, events)."""

from __future__ import annotations

from django import forms
from django.db import models
from django.contrib.auth.decorators import login_required
from django.forms import formset_factory, inlineformset_factory
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
import logging

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple

from arkumu.metadata.services.vocabulary_options_service import (
    get_default_metadata_option_map,
)
from arkumu.metadata.models.resources import (
    ClassResource,
    PropertyResource,
    EntityResource,
)
from arkumu.users.models import Organization

logger = logging.getLogger(__name__)
prt = ""


class BaseEntityForm(forms.Form):
    """Base form for both projects and events."""

    def __init__(self, *args, metadata_options=None, **kwargs):
        self.metadata_options = metadata_options or {}
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name.endswith("_uri"):
                field.widget.attrs.update(
                    {"class": "select select-bordered w-full uri-field"}
                )
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs.update(
                    {"class": "textarea textarea-bordered w-full", "rows": "4"}
                )
            elif (
                isinstance(field.widget, forms.DateTimeInput)
                and field.widget.attrs.get("type") == "datetime-local"
            ):
                field.widget.attrs.update({"class": "input input-bordered w-full"})
            else:
                field.widget.attrs.update({"class": "input input-bordered w-full"})


class ProjectForm(BaseEntityForm):
    uri = forms.ChoiceField(
        label="choose an existing project, or create one",
        required=False,
        choices=[],
    )
    bevorzugter_titel = forms.CharField(
        label="Bevorzugter Titel",
        required=True,
        help_text="Primary title of the project",
    )
    bevorzugter_untertitel = forms.CharField(
        label="Bevorzugter Untertitel",
        required=False,
        help_text="Optional subtitle for the project",
    )
    einliefernde_hochschule_uri = forms.ChoiceField(
        label="Einliefernde Hochschule",
        required=True,
        choices=[],
    )
    projektkategorie_uri = forms.ChoiceField(
        label="Projektkategorie",
        required=True,
        choices=[],
    )
    beschreibung_uri = forms.ChoiceField(
        label="Beschreibung",
        required=False,
        choices=[],
    )
    schlagwort_uris = forms.MultipleChoiceField(
        label="Schlagwörter",
        required=False,
        choices=[],
        widget=forms.SelectMultiple,
    )
    projektart_uri = forms.ChoiceField(
        label="Projektart",
        required=True,
        choices=[],
    )
    vorschaubild_uri = forms.ChoiceField(
        label="Vorschaubild",
        required=False,
        choices=[],
        help_text="URI of the preview image",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = [("", "Select a project")] + options.get(
            "project", []
        )
        self.fields["einliefernde_hochschule_uri"].choices = [
            ("", "Select an institution")
        ] + options.get("institution", [])
        self.fields["projektkategorie_uri"].choices = [
            ("", "Select a category")
        ] + options.get("project_category", [])
        self.fields["schlagwort_uris"].choices = options.get("catchphrase", [])
        self.fields["projektart_uri"].choices = [
            ("", "Select a project type")
        ] + options.get("project_type", [])
        self.fields["vorschaubild_uri"].choices = [
            ("", "Select the URI of a preview image")
        ] + options.get("digital_object", [])
        self.fields["beschreibung_uri"].choices = [
            ("", "Select the description of the project")
        ] + options.get("description", [])


class EventForm(BaseEntityForm):
    uri = forms.ChoiceField(
        label="choose an existing event, or create one",
        required=False,
        choices=[],
    )
    ereignisname = forms.CharField(
        label="Ereignisname",
        required=True,
        help_text="Name of the event",
    )
    project_uri = forms.ChoiceField(
        label="Associated Project",
        required=True,
        choices=[],
    )
    ereignisbeschreibung_uri = forms.ChoiceField(
        label="Beschreibung",
        required=False,
        choices=[],
    )
    ereignisort = forms.CharField(
        label="Ereignisort",
        required=False,
        help_text="WikidataID of the place of the event",
    )
    ereignisbeginn = forms.DateField(
        label="Ereignisbeginn",
        widget=forms.DateTimeInput(attrs={"type": "date"}),
        required=False,
        help_text="Start date of the event",
    )
    ereignisende = forms.DateField(
        label="Ereignisende",
        widget=forms.DateTimeInput(attrs={"type": "date"}),
        required=False,
        help_text="End date of the event (optional)",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = [("", "Select an event")] + options.get(
            "event", []
        )
        self.fields["project_uri"].choices = [("", "Select a project")] + options.get(
            "project", []
        )
        self.fields["ereignisbeschreibung_uri"].choices = [
            ("", "Select the description of the event")
        ] + options.get("event_description", [])


class ActorForm(BaseEntityForm):
    uri = forms.ChoiceField(
        label="choose an existing actor, or create one",
        required=False,
        choices=[],
    )
    deutscher_name = forms.CharField(
        label="Deutscher Name",
        required=True,
        help_text="Deutscher Name des Akteurs",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = [("", "Select an actor")] + options.get(
            "actor", []
        )


class DescriptionForm(BaseEntityForm):
    beschreibung = forms.CharField(
        label="Beschreibung",
        required=True,
        help_text="Description",
        widget=forms.Textarea,
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)


class CatchphraseForm(BaseEntityForm):
    uri = forms.ChoiceField(
        label="choose an existing catchphrase, or create one",
        required=False,
        choices=[],
    )
    deutsches_wikidata_label = forms.CharField(
        label="Wikidata Label",
        required=True,
        help_text="German Wikidata label for the catchphrase",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = [("", "Select a catchphrase")] + options.get(
            "catchphrase", []
        )


class RoleForm(BaseEntityForm):
    uri = forms.ChoiceField(
        label="choose an existing role, or create one",
        required=False,
        choices=[],
    )
    deutscher_name_der_rolle_breadcrumb = forms.CharField(
        label="Deutscher Name",
        required=True,
        help_text="Deutscher Name der Rolle",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = [("", "Select a role")] + options.get("role", [])


class DigitalObjectForm(BaseEntityForm):
    uri = forms.ChoiceField(
        label="choose an existing digital object, or create one",
        required=False,
        choices=[],
    )
    dateipfad = forms.CharField(
        label="Dateipfad",
        required=True,
        help_text="Dateipfad des digitalen Objekts",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = [("", "Select a digital object")] + options.get(
            "digital_object", []
        )


class InstitutionForm(BaseEntityForm):
    uri = forms.ChoiceField(
        label="choose an existing institution, or create one",
        required=False,
        choices=[],
    )
    deutscher_name_der_einliefernden_hochschule = forms.CharField(
        label="Deutscher name",
        required=True,
        help_text="Deutscher Name der einliefernden Hochschule",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = [("", "Select an institution")] + options.get(
            "institution", []
        )


class ProjectCategoryForm(BaseEntityForm):
    uri = forms.ChoiceField(
        label="choose an existing project category, or create one",
        required=False,
        choices=[],
    )
    deutscher_name_der_projektkategorie_breadcrumb = forms.CharField(
        label="Deutscher name",
        required=True,
        help_text="Deutscher Name der Projektkategorie als Breadcrumb",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = [("", "Select a project category")] + options.get(
            "project_category", []
        )


class ProjectTypeForm(BaseEntityForm):
    uri = forms.ChoiceField(
        label="choose an existing project type, or create one",
        required=False,
        choices=[],
    )
    deutscher_name_der_projektart = forms.CharField(
        label="Deutscher name",
        required=True,
        help_text="Deutscher Name der Projektart",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = [("", "Select a project type")] + options.get(
            "project_type", []
        )


class AlternateTitleForm(BaseEntityForm):
    alternativer_titel = forms.CharField(
        label="Alternativer Titel",
        required=True,
        help_text="Alternative title",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)


ActorFormSet = formset_factory(ActorForm, extra=0, min_num=0, validate_min=False)
RoleFormSet = formset_factory(RoleForm, extra=0, min_num=0, validate_min=False)


def from_form_set_property_literal(
    form: BaseEntityForm,
    form_entity: EntityResource,
    property_str: str,
    property_entity: PropertyResource,
):
    property_value = form.cleaned_data.get(property_str, "")
    if property_value:
        form_entity.set_property(property_entity, property_value)


def from_form_set_property_entity(
    form: BaseEntityForm,
    form_entity: EntityResource,
    property_str: str,
    property_entity: PropertyResource,
):
    property_uri = form.cleaned_data.get(property_str, "")
    if property_uri:
        prop, _ = EntityResource.get_or_create(property_uri)
        form_entity.set_property(property_entity, prop)


def from_form_set_property_entity_multi_value(
    form: BaseEntityForm,
    form_entity: EntityResource,
    property_str: str,
    property_entity: PropertyResource,
):
    property_uris = form.cleaned_data.get(property_str, "")
    if property_uris:
        for property_uri in property_uris:
            prop, _ = EntityResource.get_or_create(property_uri)
            form_entity.set_property(property_entity, prop)


def form_init_resources(base_uri, dataset_name, organization):
    match dataset_name:
        case "Projekt":
            entity, _ = EntityResource.create_by_organization_and_dataset_name(
                dataset_name=dataset_name, organization=organization
            )
            cls, _ = ClassResource.get_or_create(
                uri=f"{base_uri}/types/projekt", name=dataset_name
            )
            properties = {
                "title_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/bevorzugter-titel",
                    name="Bevorzugter Titel",
                )[0],
                "subtitle_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/bevorzugter-untertitel",
                    name="Bevorzugter Untertitel",
                )[0],
                "institution_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/einliefernde-hochschule",
                    name="Einliefernde Hochschule",
                )[0],
                "category_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/projektkategorie",
                    name="Projektkategorie",
                )[0],
                "description_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/beschreibung", name="Beschreibung"
                )[0],
                "catchphrase_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/schlagwort", name="Schlagwort"
                )[0],
                "project_type_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/projektart", name="Projektart"
                )[0],
                "preview_image_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/vorschaubild", name="Vorschaubild"
                )[0],
            }
            return (entity, cls, properties)
        case "Ereignis":
            entity, _ = EntityResource.create_by_organization_and_dataset_name(
                dataset_name=dataset_name, organization=organization
            )
            cls, _ = ClassResource.get_or_create(
                uri=f"{base_uri}/types/ereignis", name=dataset_name
            )
            properties = {
                "event_name_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/ereignisname", name="Ereignisname"
                )[0],
                "event_place_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/ereignisort", name="Ereignisort"
                )[0],
                "description_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/beschreibung", name="Beschreibung"
                )[0],
                "begin_date_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/ereignisbeginn", name="Ereignisbeginn"
                )[0],
                "end_date_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/ereignisende", name="Ereignisende"
                )[0],
            }
            return (entity, cls, properties)
        case "Akteurin":
            entity, _ = EntityResource.create_by_organization_and_dataset_name(
                dataset_name=dataset_name, organization=organization
            )
            cls, _ = ClassResource.get_or_create(
                uri=f"{base_uri}/types/akteurin", name=dataset_name
            )
            properties = {
                "german_name_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/deutscher-name", name="Deutscher Name"
                )[0],
            }
            return (entity, cls, properties)
        case "Rolle":
            entity, _ = EntityResource.create_by_organization_and_dataset_name(
                dataset_name=dataset_name, organization=organization
            )
            cls, _ = ClassResource.get_or_create(
                uri=f"{base_uri}/types/rolle", name=dataset_name
            )
            properties = {
                "german_name_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/deutscher-name-der-rolle-breadcrumb",
                    name="Deutscher Name der Rolle Breadcrumb",
                )[0],
            }
            return (entity, cls, properties)


def entity_set_values_from_form(
    form: BaseEntityForm, dataset_name, organization, entity, **kwargs
):
    match dataset_name:
        case "Projekt":
            from_form_set_property_literal(
                form, entity, "bevorzugter_titel", kwargs["title_prop"]
            )
            from_form_set_property_literal(
                form, entity, "bevorzugter_untertitel", kwargs["subtitle_prop"]
            )
            from_form_set_property_entity(
                form, entity, "einliefernde_hochschule_uri", kwargs["institution_prop"]
            )
            from_form_set_property_entity(
                form, entity, "projektkategorie_uri", kwargs["category_prop"]
            )
            from_form_set_property_entity(
                form, entity, "beschreibung_uri", kwargs["description_prop"]
            )
            from_form_set_property_entity(
                form, entity, "projektart_uri", kwargs["project_type_prop"]
            )
            from_form_set_property_entity_multi_value(
                form, entity, "schlagwort_uris", kwargs["catchphrase_prop"]
            )
            from_form_set_property_entity(
                form, entity, "vorschaubild_uri", kwargs["preview_image_prop"]
            )
        case "Ereignis":
            from_form_set_property_literal(
                form, entity, "ereignisname", kwargs["event_name_prop"]
            )
            from_form_set_property_literal(
                form, entity, "ereignisort", kwargs["event_place_prop"]
            )
            from_form_set_property_literal(
                form, entity, "ereignisbeginn", kwargs["begin_date_prop"]
            )
            from_form_set_property_literal(
                form, entity, "ereignisende", kwargs["end_date_prop"]
            )
        case "Akteurin":
            from_form_set_property_literal(
                form, entity, "deutscher-name", kwargs["german_name_prop"]
            )
        case "Rolle":
            from_form_set_property_literal(
                form, entity, "deutscher-name-der-rolle-breadcrumb", kwargs["german_name_prop"]
            )


def form_to_entity(form: BaseEntityForm, dataset_name, organization):
    base_uri = f"http://arkumu.org/data/{organization.code}"
    if form.is_valid():
        if uri := form.cleaned_data.get("uri", ""):
            logger.info(f"🔄✅✅✅ {uri=} truesy")
            return EntityResource.get_or_create(uri)
        logger.info(f"🔄❌❌❌ {uri=} falsy")
        entity, cls, properties = form_init_resources(
            base_uri, dataset_name, organization
        )
        entity.set_type(cls)
        entity_set_values_from_form(
            form, dataset_name, organization, entity, **properties
        )
        return entity


@login_required
def create_project(request):
    organization = getattr(request.user, "organization", None)
    # logger.info(f"🔄 {request.user._wrapped.__dict__}")
    # logger.info(f"🔄 {organization}")
    if organization:
        metadata_options = get_default_metadata_option_map(organization=organization)

        if request.method == "POST":
            project_form = ProjectForm(
                request.POST,
                metadata_options=metadata_options,
            )

            if project_form.is_valid():
                project_entity = form_to_entity(project_form, "Projekt", organization)
                # The RDF resources are now created and linked automatically
                # Continue with the rest of the project creation workflow
                return HttpResponseRedirect("/metadata/metadata-entry/")
        else:
            project_form = ProjectForm(metadata_options=metadata_options)

        return render(
            request,
            "metadata/entity_creation/create_project.html",
            {
                "project_form": project_form,
                "entity_type": "project",
                "title": "Create New Project",
                "description": "Fill in the details to create a new archival project",
            },
        )


@login_required
def create_event(request):
    organization = getattr(request.user, "organization", None)

    if organization:
        metadata_options = get_default_metadata_option_map(organization=organization)

        if request.method == "POST":
            base_uri = f"http://arkumu.org/data/{organization.code}"
            event_form = EventForm(
                request.POST,
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
            event_entity = form_to_entity(event_form, "Ereignis", organization)

            event_prop, _ = PropertyResource.get_or_create(
                uri=f"{base_uri}/properties/ereignis", name="Ereignis"
            )
            project_uri = event_form.cleaned_data.get("project_uri", "")
            if project_uri:
                project_entity, _ = EntityResource.get_or_create(uri=project_uri)
                project_entity.set_property(event_prop, event_entity)

            for actor_form, role_form in zip(actor_formset, role_formset):
                if actor_form.is_valid() and role_form.is_valid():
                    actor_entity = form_to_entity(actor_form, "Akteurin", organization)
                    role_entity = form_to_entity(role_form, "Rolle", organization)
                    actor_event_entity, _ = (
                        EntityResource.create_by_organization_and_dataset_name(
                            dataset_name="AkteurIn_Ereignis_Kreuztabelle",
                            organization=organization,
                        )
                    )

                    cls, _ = ClassResource.get_or_create(
                        uri=f"{base_uri}/types/akteurin-ereignis-kreuztabelle",
                        name="AkteurIn_Ereignis_Kreuztabelle",
                    )

                    actor_event_actor_prop, _ = PropertyResource.get_or_create(
                        uri=f"{base_uri}/properties/akteurin-im-ereignis",
                        name="AkteurIn im Ereignis",
                    )
                    actor_event_event_prop, _ = PropertyResource.get_or_create(
                        uri=f"{base_uri}/properties/im-ereignis", name="im Ereignis"
                    )
                    actor_event_role_prop, _ = PropertyResource.get_or_create(
                        uri=f"{base_uri}/properties/rollen-der-akteurin-im-ereignis",
                        name="Rollen der AkteurIn im Ereignis",
                    )

                    actor_event_entity.set_type(cls)

                    actor_event_entity.set_property(
                        actor_event_actor_prop, actor_entity
                    )
                    actor_event_entity.set_property(
                        actor_event_event_prop, event_entity
                    )
                    actor_event_entity.set_property(
                        actor_event_role_prop, role_entity
                    )

            # The RDF resources are now created and linked automatically
            # Continue with the rest of the event creation workflow

            return HttpResponseRedirect("/metadata/metadata-entry/")
        else:
            event_form = EventForm(metadata_options=metadata_options)
            actor_formset = ActorFormSet(
                prefix="actors",
                form_kwargs={"metadata_options": metadata_options},
            )
            role_formset = RoleFormSet(
                prefix="roles",
                form_kwargs={"metadata_options": metadata_options},
            )

        return render(
            request,
            "metadata/entity_creation/create_event.html",
            {
                "event_form": event_form,
                "actor_formset": actor_formset,
                "role_formset": role_formset,
                "entity_type": "event",
                "title": "Create New Event",
                "description": "Fill in the details to create a new archival event",
            },
        )


@login_required
def create_actor(request):
    organization = getattr(request.user, "organization", None)

    if organization:
        metadata_options = get_default_metadata_option_map(organization=organization)

        # Initialize base URI for resource creation
        base_uri = f"http://arkumu.org/data/{organization.code}"

        if request.method == "POST":
            actor_form = ActorForm(request.POST, metadata_options=metadata_options)

            if actor_form.is_valid():
                # Create RDF resources for the actor
                # Create Actor class resource
                actor_class, created = ClassResource.get_or_create(
                    uri=f"{base_uri}/types/akteurin", name="Akteurin"
                )

                # Create property resources
                german_name_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/deutscher-name", name="Deutscher Name"
                )

                # Create actor entity
                actor_entity, created = (
                    EntityResource.create_by_organization_and_dataset_name(
                        organization=organization, dataset_name="Akteurin"
                    )
                )

                # Set the type of the entity
                actor_entity.set_type(actor_class)

                # Set properties from form data
                german_name = actor_form.cleaned_data.get("deutscher_name", "")
                if german_name:
                    actor_entity.set_property(german_name_prop, german_name)

                # The RDF resources are now created and linked automatically
                return HttpResponseRedirect("/metadata/metadata-entry/")
        else:
            actor_form = ActorForm(metadata_options=metadata_options)

        return render(
            request,
            "metadata/entity_creation/create_actor.html",
            {
                "actor_form": actor_form,
                "entity_type": "actor",
                "title": "Create New Actor",
                "description": "Fill in the details to create a new archival actor",
            },
        )


@login_required
def create_role(request):
    organization = getattr(request.user, "organization", None)

    if organization:
        metadata_options = get_default_metadata_option_map(organization=organization)

        # Initialize base URI for resource creation
        base_uri = f"http://arkumu.org/data/{organization.code}"

        if request.method == "POST":
            role_form = RoleForm(request.POST, metadata_options=metadata_options)

            if role_form.is_valid():
                # Create RDF resources for the role
                # Create Role class resource
                role_class, created = ClassResource.get_or_create(
                    uri=f"{base_uri}/types/rolle", name="Rolle"
                )

                # Create property resources
                german_name_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/deutscher-name-der-rolle-breadcrumb",
                    name="Deutscher Name der Rolle Breadcrumb",
                )

                # Create role entity
                role_entity, created = (
                    EntityResource.create_by_organization_and_dataset_name(
                        organization=organization, dataset_name="Rolle"
                    )
                )

                # Set the type of the entity
                role_entity.set_type(role_class)

                # Set properties from form data
                german_name = role_form.cleaned_data.get(
                    "deutscher_name_der_rolle_breadcrumb", ""
                )
                if german_name:
                    role_entity.set_property(german_name_prop, german_name)

                # The RDF resources are now created and linked automatically
                return HttpResponseRedirect("/metadata/metadata-entry/")
        else:
            role_form = RoleForm(metadata_options=metadata_options)

        return render(
            request,
            "metadata/entity_creation/create_role.html",
            {
                "role_form": role_form,
                "entity_type": "role",
                "title": "Create New Role",
                "description": "Fill in the details to create a new archival role",
            },
        )


@login_required
def create_digital_object(request):
    organization = getattr(request.user, "organization", None)

    if organization:
        metadata_options = get_default_metadata_option_map(organization=organization)

        # Initialize base URI for resource creation
        base_uri = f"http://arkumu.org/data/{organization.code}"

        if request.method == "POST":
            digital_object_form = DigitalObjectForm(
                request.POST, metadata_options=metadata_options
            )

            if digital_object_form.is_valid():
                # Create RDF resources for the digital object
                # Create Digital Object class resource
                digital_object_class, created = ClassResource.get_or_create(
                    uri=f"{base_uri}/types/digitales-objekt", name="Digitales Objekt"
                )

                # Create property resources
                path_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/dateipfad", name="Dateipfad"
                )

                # Create digital object entity
                digital_object_entity, created = (
                    EntityResource.create_by_organization_and_dataset_name(
                        organization=organization, dataset_name="Digitales Objekt"
                    )
                )

                # Set the type of the entity
                digital_object_entity.set_type(digital_object_class)

                # Set properties from form data
                path = digital_object_form.cleaned_data.get("dateipfad", "")
                if path:
                    digital_object_entity.set_property(path_prop, path)

                # The RDF resources are now created and linked automatically
                return HttpResponseRedirect("/metadata/metadata-entry/")
        else:
            digital_object_form = DigitalObjectForm(metadata_options=metadata_options)

        return render(
            request,
            "metadata/entity_creation/create_digital_object.html",
            {
                "digital_object_form": digital_object_form,
                "entity_type": "digital_object",
                "title": "Create New Digital Object",
                "description": "Fill in the details to create a new digital object",
            },
        )


@login_required
def create_institution(request):
    organization = getattr(request.user, "organization", None)

    if organization:
        metadata_options = get_default_metadata_option_map(organization=organization)

        # Initialize base URI for resource creation
        base_uri = f"http://arkumu.org/data/{organization.code}"

        if request.method == "POST":
            institution_form = InstitutionForm(
                request.POST, metadata_options=metadata_options
            )

            if institution_form.is_valid():
                # Create RDF resources for the institution
                # Create Institution class resource
                institution_class, created = ClassResource.get_or_create(
                    uri=f"{base_uri}/types/einliefernde-hochschule",
                    name="Einliefernde Hochschule",
                )

                # Create property resources
                german_name_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/deutscher-name-der-einliefernden-hochschule",
                    name="Deutscher Name der Einliefernden Hochschule",
                )

                # Create institution entity
                institution_entity, created = (
                    EntityResource.create_by_organization_and_dataset_name(
                        organization=organization,
                        dataset_name="Einliefernde Hochschule",
                    )
                )

                # Set the type of the entity
                institution_entity.set_type(institution_class)

                # Set properties from form data
                german_name = institution_form.cleaned_data.get(
                    "deutscher_name_der_einliefernden_hochschule", ""
                )
                if german_name:
                    institution_entity.set_property(german_name_prop, german_name)

                # The RDF resources are now created and linked automatically
                return HttpResponseRedirect("/metadata/metadata-entry/")
        else:
            institution_form = InstitutionForm(metadata_options=metadata_options)

        return render(
            request,
            "metadata/entity_creation/create_institution.html",
            {
                "institution_form": institution_form,
                "entity_type": "institution",
                "title": "Create New Institution",
                "description": "Fill in the details to create a new institutional affiliation",
            },
        )


@login_required
def create_project_category(request):
    organization = getattr(request.user, "organization", None)

    if organization:
        metadata_options = get_default_metadata_option_map(organization=organization)

        # Initialize base URI for resource creation
        base_uri = f"http://arkumu.org/data/{organization.code}"

        if request.method == "POST":
            project_category_form = ProjectCategoryForm(
                request.POST, metadata_options=metadata_options
            )

            if project_category_form.is_valid():
                # Create RDF resources for the project category
                # Create Project Category class resource
                project_category_class, created = ClassResource.get_or_create(
                    uri=f"{base_uri}/types/projektkategorie", name="Projektkategorie"
                )

                # Create property resources
                german_name_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/deutscher-name-der-projektkategorie-breadcrumb",
                    name="Deutscher Name der Projektkategorie Breadcrumb",
                )

                # Create project category entity
                project_category_entity, created = (
                    EntityResource.create_by_organization_and_dataset_name(
                        organization=organization, dataset_name="Projektkategorie"
                    )
                )

                # Set the type of the entity
                project_category_entity.set_type(project_category_class)

                # Set properties from form data
                german_name = project_category_form.cleaned_data.get(
                    "deutscher_name_der_projektkategorie_breadcrumb", ""
                )
                if german_name:
                    project_category_entity.set_property(german_name_prop, german_name)

                # The RDF resources are now created and linked automatically
                return HttpResponseRedirect("/metadata/metadata-entry/")
        else:
            project_category_form = ProjectCategoryForm(
                metadata_options=metadata_options
            )

        return render(
            request,
            "metadata/entity_creation/create_project_category.html",
            {
                "project_category_form": project_category_form,
                "entity_type": "project_category",
                "title": "Create New Project Category",
                "description": "Fill in the details to create a new project category",
            },
        )


@login_required
def create_project_type(request):
    organization = getattr(request.user, "organization", None)

    if organization:
        metadata_options = get_default_metadata_option_map(organization=organization)

        # Initialize base URI for resource creation
        base_uri = f"http://arkumu.org/data/{organization.code}"

        if request.method == "POST":
            project_type_form = ProjectTypeForm(
                request.POST, metadata_options=metadata_options
            )

            if project_type_form.is_valid():
                # Create RDF resources for the project type
                # Create Project Type class resource
                project_type_class, created = ClassResource.get_or_create(
                    uri=f"{base_uri}/types/projektart", name="Projektart"
                )

                # Create property resources
                german_name_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/deutscher-name-der-projektart",
                    name="Deutscher Name der Projektart",
                )

                # Create project type entity
                project_type_entity, created = (
                    EntityResource.create_by_organization_and_dataset_name(
                        organization=organization, dataset_name="Projektart"
                    )
                )

                # Set the type of the entity
                project_type_entity.set_type(project_type_class)

                # Set properties from form data
                german_name = project_type_form.cleaned_data.get(
                    "deutscher_name_der_projektart", ""
                )
                if german_name:
                    project_type_entity.set_property(german_name_prop, german_name)

                # The RDF resources are now created and linked automatically
                return HttpResponseRedirect("/metadata/metadata-entry/")
        else:
            project_type_form = ProjectTypeForm(metadata_options=metadata_options)

        return render(
            request,
            "metadata/entity_creation/create_project_type.html",
            {
                "project_type_form": project_type_form,
                "entity_type": "project_type",
                "title": "Create New Project Type",
                "description": "Fill in the details to create a new project type",
            },
        )


@login_required
def create_alternate_title(request):
    organization = getattr(request.user, "organization", None)

    if organization:
        metadata_options = get_default_metadata_option_map(organization=organization)

        # Initialize base URI for resource creation
        base_uri = f"http://arkumu.org/data/{organization.code}"

        if request.method == "POST":
            alternate_title_form = AlternateTitleForm(
                request.POST, metadata_options=metadata_options
            )

            if alternate_title_form.is_valid():
                # Create RDF resources for the alternate title
                # Create Alternate Title class resource
                alternate_title_class, created = ClassResource.get_or_create(
                    uri=f"{base_uri}/types/alternativer-titel",
                    name="Alternativer Titel",
                )

                # Create property resources
                title_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/alternativer-titel",
                    name="Alternativer Titel",
                )

                # Create alternate title entity
                alternate_title_entity, created = (
                    EntityResource.create_by_organization_and_dataset_name(
                        organization=organization, dataset_name="Alternativer Titel"
                    )
                )

                # Set the type of the entity
                alternate_title_entity.set_type(alternate_title_class)

                # Set properties from form data
                title = alternate_title_form.cleaned_data.get("alternativer_titel", "")
                if title:
                    alternate_title_entity.set_property(title_prop, title)

                # The RDF resources are now created and linked automatically
                return HttpResponseRedirect("/metadata/metadata-entry/")
        else:
            alternate_title_form = AlternateTitleForm(metadata_options=metadata_options)

        return render(
            request,
            "metadata/entity_creation/create_alternate_title.html",
            {
                "alternate_title_form": alternate_title_form,
                "entity_type": "alternate_title",
                "title": "Create New Alternate Title",
                "description": "Fill in the details to create a new alternate title",
            },
        )


@login_required
def create_description(request):
    organization = getattr(request.user, "organization", None)

    if organization:
        metadata_options = get_default_metadata_option_map(organization=organization)

        # Initialize base URI for resource creation
        base_uri = f"http://arkumu.org/data/{organization.code}"

        if request.method == "POST":
            description_form = DescriptionForm(
                request.POST, metadata_options=metadata_options
            )

            if description_form.is_valid():
                # Create RDF resources for the description
                # Create Description class resource
                description_class, created = ClassResource.get_or_create(
                    uri=f"{base_uri}/types/beschreibung", name="Beschreibung"
                )

                # Create property resources
                description_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/beschreibung", name="Beschreibung"
                )

                # Create description entity
                description_entity, created = (
                    EntityResource.create_by_organization_and_dataset_name(
                        organization=organization, dataset_name="Beschreibung"
                    )
                )

                # Set the type of the entity
                description_entity.set_type(description_class)

                # Set properties from form data
                description_text = description_form.cleaned_data.get("beschreibung", "")
                if description_text:
                    description_entity.set_property(description_prop, description_text)

                # The RDF resources are now created and linked automatically
                return HttpResponseRedirect("/metadata/metadata-entry/")
        else:
            description_form = DescriptionForm(metadata_options=metadata_options)

        return render(
            request,
            "metadata/entity_creation/create_description.html",
            {
                "description_form": description_form,
                "entity_type": "description",
                "title": "Create New Description",
                "description": "Fill in the details to create a new description",
            },
        )


@login_required
def create_catchphrase(request):
    organization = getattr(request.user, "organization", None)

    if organization:
        metadata_options = get_default_metadata_option_map(organization=organization)

        # Initialize base URI for resource creation
        base_uri = f"http://arkumu.org/data/{organization.code}"

        if request.method == "POST":
            catchphrase_form = CatchphraseForm(
                request.POST, metadata_options=metadata_options
            )

            if catchphrase_form.is_valid():
                # Create RDF resources for the catchphrase
                # Create Catchphrase class resource
                catchphrase_class, created = ClassResource.get_or_create(
                    uri=f"{base_uri}/types/schlagwort", name="Schlagwort"
                )

                # Create property resources
                wikidata_label_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/deutsches-wikidata-label",
                    name="Deutsches Wikidata Label",
                )

                # Create catchphrase entity
                catchphrase_entity, created = (
                    EntityResource.create_by_organization_and_dataset_name(
                        organization=organization, dataset_name="Schlagwort"
                    )
                )

                # Set the type of the entity
                catchphrase_entity.set_type(catchphrase_class)

                # Set properties from form data
                wikidata_label = catchphrase_form.cleaned_data.get(
                    "deutsches_wikidata_label", ""
                )
                if wikidata_label:
                    catchphrase_entity.set_property(wikidata_label_prop, wikidata_label)

                # The RDF resources are now created and linked automatically
                return HttpResponseRedirect("/metadata/metadata-entry/")
        else:
            catchphrase_form = CatchphraseForm(metadata_options=metadata_options)

        return render(
            request,
            "metadata/entity_creation/create_catchphrase.html",
            {
                "catchphrase_form": catchphrase_form,
                "entity_type": "catchphrase",
                "title": "Create New Catchphrase",
                "description": "Fill in the details to create a new catchphrase",
            },
        )


@login_required
def get_actor_details(request):
    """
    Returns actor details as JSON for auto-filling form fields.
    """
    actor_uri = request.GET.get("uri","")
    try:

        # Find the resource with this URI
        try:
            actor, _ = EntityResource.get_or_create(uri=actor_uri)
            organization = getattr(request.user, "organization", None)
            base_uri = f"http://arkumu.org/data/{organization.code}"
            german_name_prop, _ = PropertyResource.get_or_create(
                uri=f"{base_uri}/properties/deutscher-name", name="Deutscher Name"
            )
            deutscher_name = actor.get_property(german_name_prop)[0]

            return JsonResponse({"deutscher_name": deutscher_name})

        except Resource.DoesNotExist:
            return JsonResponse({"error": "Actor not found"}, status=404)

    except Exception as e:
        logger.error(f"Error retrieving actor details for {actor_uri}: {str(e)}")
        return JsonResponse({"error": "Internal server error"}, status=500)
    
@login_required
def get_role_details(request):
    """
    Returns role details as JSON for auto-filling form fields.
    """
    role_uri = request.GET.get("uri","")
    try:

        # Find the resource with this URI
        try:
            role, _ = EntityResource.get_or_create(uri=role_uri)
            organization = getattr(request.user, "organization", None)
            base_uri = f"http://arkumu.org/data/{organization.code}"
            german_name_prop, _ = PropertyResource.get_or_create(
                uri=f"{base_uri}/properties/deutscher-name-der-rolle-breadcrumb",
                name="Deutscher Name der Rolle Breadcrumb",
            )
            deutscher_name = role.get_property(german_name_prop)[0]

            return JsonResponse({"deutscher_name": deutscher_name})

        except Resource.DoesNotExist:
            return JsonResponse({"error": "Actor not found"}, status=404)

    except Exception as e:
        logger.error(f"Error retrieving actor details for {role_uri}: {str(e)}")
        return JsonResponse({"error": "Internal server error"}, status=500)

@login_required
def get_project_details(request):
    """
    Returns project details as JSON for auto-filling form fields.
    """

    project_uri = request.GET.get("uri","")
    try:

        # Find the resource with this URI
        try:
            project, _ = EntityResource.get_or_create(uri=project_uri)
            organization = getattr(request.user, "organization", None)
            base_uri = f"http://arkumu.org/data/{organization.code}"
            properties = {
                "title_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/bevorzugter-titel",
                    name="Bevorzugter Titel",
                )[0],
                "subtitle_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/bevorzugter-untertitel",
                    name="Bevorzugter Untertitel",
                )[0],
                "institution_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/einliefernde-hochschule",
                    name="Einliefernde Hochschule",
                )[0],
                "category_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/projektkategorie",
                    name="Projektkategorie",
                )[0],
                "description_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/beschreibung", name="Beschreibung"
                )[0],
                "catchphrase_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/schlagwort", name="Schlagwort"
                )[0],
                "project_type_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/projektart", name="Projektart"
                )[0],
                "preview_image_prop": PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/vorschaubild", name="Vorschaubild"
                )[0],
            }
            json = {
                "bevorzugter_titel" : project.get_property(properties["title_prop"]),
                "bevorzugter_untertitel" : project.get_property(properties["subtitle_prop"]),
                "einliefernde_hochschule_uri" : project.get_property(properties["institution_prop"])[0].uri if len(project.get_property(properties["institution_prop"])) > 0 and type(project.get_property(properties["institution_prop"])[0]) == EntityResource else '',
                "projektkategorie_uri" : project.get_property(properties["category_prop"])[0].uri if len(project.get_property(properties["category_prop"])) > 0 and type(project.get_property(properties["category_prop"])[0]) == EntityResource else '',
                "beschreibung_uri" : project.get_property(properties["description_prop"])[0].uri if len(project.get_property(properties["description_prop"])) > 0 and type(project.get_property(properties["description_prop"])[0]) == EntityResource else '',
                "schlagwort_uris" : [catchphrase.uri if type(catchphrase) == EntityResource else '' for catchphrase in project.get_property(properties["catchphrase_prop"])] if len(project.get_property(properties["catchphrase_prop"])) > 0 else '',
                "projektart_uri" : project.get_property(properties["project_type_prop"])[0].uri if len(project.get_property(properties["project_type_prop"])) > 0 and type(project.get_property(properties["project_type_prop"])[0]) == EntityResource else '',
                "vorschaubild_uri" : project.get_property(properties["preview_image_prop"])[0].uri if len(project.get_property(properties["preview_image_prop"])) > 0 and type(project.get_property(properties["institution_prop"])[0]) == EntityResource else '',
            }

            return JsonResponse(json)

        except Resource.DoesNotExist:
            return JsonResponse({"error": "Actor not found"}, status=404)

    except Exception as e:
        logger.error(f"Error retrieving actor details for {project_uri}: {str(e)}")
        return JsonResponse({"error": "Internal server error"}, status=500)
