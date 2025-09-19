from django import forms
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.forms import formset_factory

from arkumu.metadata.models import Resource, Triple

def get_uri_options(predicate_name):
    predicate = Resource.objects.filter(name=predicate_name).first()
    if not predicate:
        return []
    triples = Triple.objects.filter(predicate=predicate)
    options = []
    for triple in triples:
        obj = triple.object
        label = obj.name if obj.name else obj.value
        options.append({'id': str(obj.id), 'uri': obj.uri, 'label': label})
    return options

URI_OPTIONS = {
    'institution': get_uri_options("Einliefernde Hochschule"),
    'project_category': get_uri_options("Projektkategorie"),
    'project_type': get_uri_options("Projektart"),
    'actor': get_uri_options("Akteurin"),
    'role': get_uri_options("Rolle"),
    'catchphrase': get_uri_options("Schlagwort"),
    'project': get_uri_options("Projekt"),  # Add project options for event creation
}

class BaseEntityForm(forms.Form):
    """Base form for both projects and events"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add common CSS classes to all fields
        for field_name, field in self.fields.items():
            if field_name.endswith('_uri'):
                field.widget.attrs.update({'class': 'select select-bordered w-full uri-field'})
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs.update({'class': 'textarea textarea-bordered w-full', 'rows': '4'})
            elif isinstance(field.widget, forms.DateTimeInput) and 'type' in field.widget.attrs and field.widget.attrs['type'] == 'datetime-local':
                field.widget.attrs.update({'class': 'input input-bordered w-full'})
            else:
                field.widget.attrs.update({'class': 'input input-bordered w-full'})

class ProjectForm(BaseEntityForm):
    bevorzugter_titel = forms.CharField(
        label="Bevorzugter Titel",
        required=True,
        help_text="Primary title of the project"
    )
    bevorzugter_untertitel = forms.CharField(
        label="Bevorzugter Untertitel",
        required=False,
        help_text="Optional subtitle for the project"
    )
    einliefernde_hochschule_uri = forms.ChoiceField(
        label="Einliefernde Hochschule",
        required=True,
        choices=[('', 'Select an institution')] + [(opt['id'], f"{opt['label']} ({opt['uri']})") for opt in URI_OPTIONS['institution']]
    )
    projektkategorie_uri = forms.ChoiceField(
        label="Projektkategorie",
        required=True,
        choices=[('', 'Select a category')] + [(opt['id'], f"{opt['label']} ({opt['uri']})") for opt in URI_OPTIONS['project_category']]
    )
    beschreibung = forms.CharField(
        label="Beschreibung",
        widget=forms.Textarea,
        required=False,
        help_text="Detailed description of the project"
    )
    schlagwort_uris = forms.MultipleChoiceField(
        label="Schlagwörter",
        required=False,
        choices=[(opt['id'], f"{opt['label']} ({opt['uri']})") for opt in URI_OPTIONS['catchphrase']],
        widget=forms.SelectMultiple
    )
    projektart_uri = forms.ChoiceField(
        label="Projektart",
        required=True,
        choices=[('', 'Select a project type')] + [(opt['id'], f"{opt['label']} ({opt['uri']})") for opt in URI_OPTIONS['project_type']]
    )
    vorschaubild_uri = forms.CharField(
        label="Vorschaubild",
        required=False,
        help_text="URI of the preview image"
    )

class EventForm(BaseEntityForm):
    project_uri = forms.ChoiceField(
        label="Associated Project",
        required=True,
        choices=[('', 'Select a project')] + [(opt['id'], f"{opt['label']} ({opt['uri']})") for opt in URI_OPTIONS['project']]
    )
    ereignisbeginn = forms.DateTimeField(
        label="Ereignisbeginn",
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        required=True,
        help_text="Start date and time of the event"
    )
    ereignisende = forms.DateTimeField(
        label="Ereignisende",
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        required=False,
        help_text="End date and time of the event (optional)"
    )

class ActorEventForm(BaseEntityForm):
    akteurin_uri = forms.ChoiceField(
        label="Akteurin",
        required=True,
        choices=[('', 'Select an actor')] + [(opt['id'], f"{opt['label']} ({opt['uri']})") for opt in URI_OPTIONS['actor']]
    )
    rollen_uri = forms.ChoiceField(
        label="Rolle",
        required=True,
        choices=[('', 'Select a role')] + [(opt['id'], f"{opt['label']} ({opt['uri']})") for opt in URI_OPTIONS['role']]
    )

# Create formsets for nested forms
ActorEventFormSet = formset_factory(ActorEventForm, extra=1, min_num=1, validate_min=True)

@login_required
def create_project(request):
    if request.method == "POST":
        project_form = ProjectForm(request.POST)
        actor_event_formset = ActorEventFormSet(request.POST, prefix='actors')

        if project_form.is_valid() and actor_event_formset.is_valid():
            # Process the form data (in a real app, save to database)
            return HttpResponseRedirect("/storage/dashboard/")
    else:
        project_form = ProjectForm()
        actor_event_formset = ActorEventFormSet(prefix='actors')

    return render(request, "storage/create_project.html", {
        "project_form": project_form,
        "actor_event_formset": actor_event_formset,
        "entity_type": "project",
        "title": "Create New Project",
        "description": "Fill in the details to create a new archival project"
    })

@login_required
def create_event(request):
    if request.method == "POST":
        event_form = EventForm(request.POST)
        actor_event_formset = ActorEventFormSet(request.POST, prefix='actors')

        if event_form.is_valid() and actor_event_formset.is_valid():
            # Process the form data (in a real app, save to database)
            return HttpResponseRedirect("/storage/dashboard/")
    else:
        event_form = EventForm()
        actor_event_formset = ActorEventFormSet(prefix='actors')

    return render(request, "storage/create_event.html", {
        "event_form": event_form,
        "actor_event_formset": actor_event_formset,
        "entity_type": "event",
        "title": "Create New Event",
        "description": "Fill in the details to create a new archival event"
    })
