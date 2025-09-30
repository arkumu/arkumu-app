"""Views and forms for creating metadata-backed entities (projects, events)."""

from __future__ import annotations

from django import forms
from django.db import models
from django.contrib.auth.decorators import login_required
from django.forms import formset_factory
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
    EntityResource
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

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)
        options = self.metadata_options
        self.fields["akteurin_uri"].choices = [
            ("", "Select an actor")
        ] + options.get("actor", [])
        self.fields["rollen_uri"].choices = [
            ("", "Select a role")
        ] + options.get("role", [])


ActorEventFormSet = formset_factory(ActorEventForm, extra=1, min_num=1, validate_min=True)


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
                    name="Bevorzugter Titel"
                )

                subtitle_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/bevorzugter-untertitel",
                    name="Bevorzugter Untertitel"
                )

                institution_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/einliefernde-hochschule",
                    name="Einliefernde Hochschule"
                )

                category_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/properties/projektkategorie",
                    name="Projektkategorie"
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
                return HttpResponseRedirect("/storage/dashboard/")
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
                        name="AkteurIn_Ereignis_Kreuztabelle"
                    )

                    # Create property resources
                    actor_event_actor_prop, _ = PropertyResource.get_or_create(
                        uri=f"{base_uri}/properties/akteurin-im-ereignis",
                        name="AkteurIn im Ereignis"
                    )

                    actor_event_event_prop, _ = PropertyResource.get_or_create(
                        uri=f"{base_uri}/properties/im-ereignis",
                        name="im Ereignis"
                    )
                    
                    actor_event_actor_role_prop, _ = PropertyResource.get_or_create(
                        uri=f"{base_uri}/properties/rollen-der-akteurin-im-ereignis",
                        name="Rollen der AkteurIn im Ereignis"
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

                return HttpResponseRedirect("/storage/dashboard/")
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
