"""Views and forms for creating metadata-backed entities (projects, events)."""

from __future__ import annotations

from django import forms
from django.contrib.auth.decorators import login_required
from django.forms import formset_factory
from django.http import HttpResponseRedirect
from django.shortcuts import render

from arkumu.metadata.services.vocabulary_options_service import (
    get_default_metadata_option_map,
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
