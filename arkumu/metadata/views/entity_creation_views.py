"""Views and forms for creating metadata-backed entities (projects, events)."""

from __future__ import annotations

from django import forms
from django.db import models
from django.contrib.auth.decorators import login_required
from django.forms import formset_factory, inlineformset_factory
from django.http import HttpResponseRedirect
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
        self.fields["project_uri"].choices = [
            ("", "Select a project")
        ] + options.get("project", [])
        self.fields["ereignisbeschreibung_uri"].choices = [
            ("", "Select the description of the event")
        ] + options.get("event_description", [])


class ActorForm(BaseEntityForm):
    deutscher_name = forms.CharField(
        label="Deutscher Name",
        required=True,
        help_text="Deutscher Name des Akteurs",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)


class ActorEventForm(BaseEntityForm):
    akteurin_uri = forms.ChoiceField(
        label="Akteurin",
        required=True,
        choices=[],
    )
    rollen_uri = forms.ChoiceField(
        label="Rolle",
        required=True,
        choices=[],
    )
    akteurin = ActorForm()

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)
        options = self.metadata_options
        self.fields["akteurin_uri"].choices = [
            ("", "Select an actor")
        ] + options.get("actor", [])
        self.fields["rollen_uri"].choices = [
            ("", "Select a role")
        ] + options.get("role", [])


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
    deutsches_wikidata_label = forms.CharField(
        label="Wikidata Label",
        required=True,
        help_text="German Wikidata label for the catchphrase",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)

class RoleForm(BaseEntityForm):
    deutscher_name_der_rolle_breadcrumb = forms.CharField(
        label="Deutscher Name",
        required=True,
        help_text="Deutscher Name der Rolle",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)

class DigitalObjectForm(BaseEntityForm):
    dateipfad = forms.CharField(
        label="Dateipfad",
        required=True,
        help_text="Dateipfad des digitalen Objekts",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)

class InstitutionForm(BaseEntityForm):
    deutscher_name_der_einliefernden_hochschule = forms.CharField(
        label="Deutscher name",
        required=True,
        help_text="Deutscher Name der einliefernden Hochschule",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)

class ProjectCategoryForm(BaseEntityForm):
    deutscher_name_der_projektkategorie_breadcrumb = forms.CharField(
        label="Deutscher name",
        required=True,
        help_text="Deutscher Name der Projektkategorie als Breadcrumb",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)

class ProjectTypeForm(BaseEntityForm):
    deutscher_name_der_projektart = forms.CharField(
        label="Deutscher name",
        required=True,
        help_text="Deutscher Name der Projektart",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)


class AlternateTitleForm(BaseEntityForm):
    alternativer_titel = forms.CharField(
        label="Alternativer Titel",
        required=True,
        help_text="Alternative title",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)


ActorEventFormSet = formset_factory(ActorEventForm, extra=0, min_num=0, validate_min=False)


@login_required
def create_project(request):
    organization = getattr(request.user, "organization", None)
    # logger.info(f"🔄 {request.user._wrapped.__dict__}")
    # logger.info(f"🔄 {organization}")
    if organization:
        metadata_options = get_default_metadata_option_map(organization=organization)

        # Initialize base URI for resource creation
        base_uri = f"http://arkumu.org/data/{organization.code}"

        if request.method == "POST":
            project_form = ProjectForm(
                request.POST,
                metadata_options=metadata_options,
            )
            actor_event_formset = ActorEventFormSet(
                request.POST,
                prefix="actors",
                form_kwargs={"metadata_options": metadata_options},
            )

            if project_form.is_valid():
                # Create RDF resources for the project using the wrapper classes
                # Create Project class resource
                project_class, created = ClassResource.get_or_create(
                    uri=f"{base_uri}/types/projekt",
                    name="Projekt"
                )

                # Create property resources
                title_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/bevorzugter-titel",
                    name="Bevorzugter Titel",
                )

                subtitle_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/bevorzugter-untertitel",
                    name="Bevorzugter Untertitel",
                )

                institution_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/einliefernde-hochschule",
                    name="Einliefernde Hochschule",
                )

                category_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/projektkategorie",
                    name="Projektkategorie",
                )

                description_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/beschreibung",
                    name="Beschreibung"
                )

                catchphrase_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/schlagwort",
                    name="Schlagwort"
                )

                project_type_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/projektart",
                    name="Projektart"
                )

                # Create project entity
                project_entity, created = EntityResource.create_by_organization_and_dataset_name(
                    dataset_name="Projekt", organization=organization
                )

                # Set the type of the entity
                project_entity.set_type(project_class)

                # Set properties from form data
                project_title = project_form.cleaned_data.get('bevorzugter_titel', '')
                if project_title:
                    project_entity.set_property(title_prop, project_title)

                project_subtitle = project_form.cleaned_data.get('bevorzugter_untertitel', '')
                if project_subtitle:
                    project_entity.set_property(subtitle_prop, project_subtitle)

                project_institution_uri = project_form.cleaned_data.get('einliefernde_hochschule_uri', '')
                if project_institution_uri:
                    project_institution, _ = EntityResource.get_or_create(project_institution_uri)
                    project_entity.set_property(institution_prop, project_institution)

                project_category_uri = project_form.cleaned_data.get('projektkategorie_uri', '')
                if project_category_uri:
                    project_category, _ = EntityResource.get_or_create(project_category_uri)
                    project_entity.set_property(category_prop, project_category)

                project_description_uri = project_form.cleaned_data.get('beschreibung_uri', '')
                if project_description_uri:
                    project_description, _ = EntityResource.get_or_create(project_description_uri)
                    project_entity.set_property(description_prop, project_description)

                project_catchprase_uris = project_form.cleaned_data.get('schlagwort_uris', '')
                if project_catchprase_uris:
                    for project_catchprase_uri in project_catchprase_uris:
                        project_catchprase, _ = EntityResource.get_or_create(project_catchprase_uri)
                        project_entity.set_property(catchphrase_prop, project_catchprase)

                project_type_uri = project_form.cleaned_data.get('projektart_uri', '')
                if project_type_uri:
                    project_type, _ = EntityResource.get_or_create(project_type_uri)
                    project_entity.set_property(project_type_prop, project_type)

                # The RDF resources are now created and linked automatically
                # Continue with the rest of the project creation workflow
                return HttpResponseRedirect("/metadata/metadata-entry/")
        else:
            project_form = ProjectForm(metadata_options=metadata_options)
            actor_event_formset = ActorEventFormSet(
                prefix="actors",
                form_kwargs={"metadata_options": metadata_options},
            )

        return render(
            request,
            "metadata/entity_creation/create_project.html",
            {
                "project_form": project_form,
                "actor_event_formset": actor_event_formset,
                "entity_type": "project",
                "title": "Create New Project",
                "description": "Fill in the details to create a new archival project",
                "prt": prt,
            },
        )


@login_required
def create_event(request):
    organization = getattr(request.user, "organization", None)

    if organization:
        metadata_options = get_default_metadata_option_map(organization=organization)

        # Initialize base URI for resource creation
        base_uri = f"http://arkumu.org/data/{organization.code}"

        if request.method == "POST":
            event_form = EventForm(
                request.POST,
                metadata_options=metadata_options,
            )
            actor_event_formset = ActorEventFormSet(
                request.POST,
                prefix="actors",
                form_kwargs={"metadata_options": metadata_options},
            )

            if event_form.is_valid() and actor_event_formset.is_valid():
                # Create RDF resources for the event using the wrapper classes
                # Create Event class resource
                event_class, created = ClassResource.get_or_create(
                    uri=f"{base_uri}/types/ereignis",
                    name="Ereignis"
                )

                # Create property resources
                event_name_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/ereignisname",
                    name="Ereignisname"
                )
                event_place_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/ereignisort",
                    name="Ereignisort"
                )
                description_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/beschreibung",
                    name="Beschreibung"
                )
                begin_date_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/ereignisbeginn",
                    name="Ereignisbeginn"
                )

                end_date_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/ereignisende",
                    name="Ereignisende"
                )

                # Create event entity
                event_entity, created = EntityResource.create_by_organization_and_dataset_name(organization=organization, dataset_name="Ereignis")

                # Set the type of the entity
                event_entity.set_type(event_class)

                # Set event properties from form data
                event_name = event_form.cleaned_data.get('ereignisname', '')
                if event_name:
                    event_entity.set_property(event_name_prop, event_name)

                event_place = event_form.cleaned_data.get('ereignisort', '')
                if event_name:
                    event_entity.set_property(event_place_prop, event_place)

                begin_date = event_form.cleaned_data.get('ereignisbeginn', '')
                if begin_date:
                    event_entity.set_property(begin_date_prop, begin_date.isoformat())

                end_date = event_form.cleaned_data.get('ereignisende', '')
                if end_date:
                    event_entity.set_property(end_date_prop, end_date.isoformat())

                # Link to the associated project
                project_uri = event_form.cleaned_data.get('project_uri', '')
                if project_uri:
                    event_prop, _ = PropertyResource.get_or_create(
                        uri=f"{base_uri}/properties/ereignis",
                        name="Ereignis"
                    )
                    project_entity, _ = EntityResource.get_or_create(
                        uri=project_uri
                    )
                    project_entity.set_property(event_prop, event_entity)

                for actor_event_form in actor_event_formset:
                    # Create Actor-Event class resource
                    actor_event_class, created = ClassResource.get_or_create(
                        uri=f"{base_uri}/types/akteurin-ereignis-kreuztabelle",
                        name="AkteurIn_Ereignis_Kreuztabelle",
                    )

                    # Create property resources
                    actor_event_actor_prop, _ = PropertyResource.get_or_create(
                        uri=f"{base_uri}/properties/akteurin-im-ereignis",
                        name="AkteurIn im Ereignis",
                    )

                    actor_event_event_prop, _ = PropertyResource.get_or_create(
                        uri=f"{base_uri}/properties/im-ereignis",
                        name="im Ereignis"
                    )
                    
                    actor_event_actor_role_prop, _ = PropertyResource.get_or_create(
                        uri=f"{base_uri}/properties/rollen-der-akteurin-im-ereignis",
                        name="Rollen der AkteurIn im Ereignis",
                    )

                    # Create event entity
                    actor_event_entity, created = EntityResource.create_by_organization_and_dataset_name(organization=organization, dataset_name="AkteurIn_Ereignis_Kreuztabelle")

                    # Set the type of the entity
                    actor_event_entity.set_type(actor_event_class)

                    # Set event properties from form data
                    actor_event_actor_uri = actor_event_form.cleaned_data.get('akteurin_uri', '')
                    if actor_event_actor_uri:
                        actor_event_actor, _ = EntityResource.get_or_create(actor_event_actor_uri)
                        actor_event_entity.set_property(actor_event_actor_prop, actor_event_actor)

                    actor_event_actor_role_uri = actor_event_form.cleaned_data.get('rollen_uri', '')
                    if actor_event_actor_role_uri:
                        actor_event_actor_role, _ = EntityResource.get_or_create(actor_event_actor_role_uri)
                        actor_event_entity.set_property(actor_event_actor_role_prop, actor_event_actor_role)

                    actor_event_entity.set_property(actor_event_event_prop, event_entity)

                # The RDF resources are now created and linked automatically
                # Continue with the rest of the event creation workflow

                return HttpResponseRedirect("/metadata/metadata-entry/")
        else:
            event_form = EventForm(metadata_options=metadata_options)
            actor_event_formset = ActorEventFormSet(
                prefix="actors",
                form_kwargs={"metadata_options": metadata_options},
            )

        return render(
            request,
            "metadata/entity_creation/create_event.html",
            {
                "event_form": event_form,
                "actor_event_formset": actor_event_formset,
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
