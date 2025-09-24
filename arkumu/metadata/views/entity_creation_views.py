"""Views and forms for creating metadata-backed entities (projects, events)."""

from __future__ import annotations

from django import forms
from django.contrib.auth.decorators import login_required
from django.forms import formset_factory
from django.http import HttpResponseRedirect
from django.shortcuts import render
import logging

from arkumu.metadata.services.vocabulary_options_service import (
    get_default_metadata_option_map,
)
from arkumu.metadata.models.resources import (
    ClassResource,
    PropertyResource,
    EntityResource
)


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
    beschreibung = forms.CharField(
        label="Beschreibung",
        widget=forms.Textarea,
        required=False,
        help_text="Detailed description of the project",
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
    vorschaubild_uri = forms.CharField(
        label="Vorschaubild",
        required=False,
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


class EventForm(BaseEntityForm):
    project_uri = forms.ChoiceField(
        label="Associated Project",
        required=True,
        choices=[],
    )
    ereignisbeginn = forms.DateTimeField(
        label="Ereignisbeginn",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        required=True,
        help_text="Start date and time of the event",
    )
    ereignisende = forms.DateTimeField(
        label="Ereignisende",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        required=False,
        help_text="End date and time of the event (optional)",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)
        options = self.metadata_options
        self.fields["project_uri"].choices = [
            ("", "Select a project")
        ] + options.get("project", [])


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
    metadata_options = get_default_metadata_option_map(organization=organization)

    # Initialize base URI for resource creation
    base_uri = "https://arkumu.example.org/data/"

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
                uri=f"{base_uri}/Project",
                name="Project"
            )

            # Create property resources
            title_prop, _ = PropertyResource.get_or_create(
                uri=f"{base_uri}/title",
                name="title"
            )

            description_prop, _ = PropertyResource.get_or_create(
                uri=f"{base_uri}/description",
                name="description"
            )

            # Create project entity
            project_uri = f"{base_uri}/project_{project_form.cleaned_data.get('bevorzugter_titel', 'unknown').replace(' ', '_')[:50]}"
            project_entity, created = EntityResource.get_or_create(
                uri=project_uri
            )

            # Set the type of the entity
            project_entity.set_type(project_class)

            # Set properties from form data
            project_title = project_form.cleaned_data.get('bevorzugter_titel', '')
            if project_title:
                project_entity.set_property(title_prop, project_title)

            project_description = project_form.cleaned_data.get('beschreibung', '')
            if project_description:
                project_entity.set_property(description_prop, project_description)

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
    metadata_options = get_default_metadata_option_map(organization=organization)

    # Initialize base URI for resource creation
    base_uri = "https://arkumu.example.org/data/"

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
            logger.info(f"🔄 TEST1")
            event_class, created = ClassResource.get_or_create(
                uri=f"{base_uri}/Event",
                name="Event"
            )

            # Create property resources
            begin_date_prop, _ = PropertyResource.get_or_create(
                uri=f"{base_uri}/beginDate",
                name="beginDate"
            )

            end_date_prop, _ = PropertyResource.get_or_create(
                uri=f"{base_uri}/endDate",
                name="endDate"
            )

            # Create event entity
            event_uri = f"{base_uri}/event_{event_form.cleaned_data.get('ereignisbeginn', '').isoformat()[:20]}"
            event_entity, created = EntityResource.get_or_create(
                uri=event_uri
            )

            # Set the type of the entity
            event_entity.set_type(event_class)

            # Set event properties from form data
            begin_date = event_form.cleaned_data.get('ereignisbeginn', '')
            if begin_date:
                event_entity.set_property(begin_date_prop, begin_date.isoformat())

            end_date = event_form.cleaned_data.get('ereignisende', '')
            if end_date:
                event_entity.set_property(end_date_prop, end_date.isoformat())

            # Link to the associated project
            project_uri = event_form.cleaned_data.get('project_uri', '')
            if project_uri:
                project_prop, _ = PropertyResource.get_or_create(
                    uri=f"{base_uri}/project",
                    name="project"
                )
                event_entity.set_property(project_prop, project_uri)

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
