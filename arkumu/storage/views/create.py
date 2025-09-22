from django import forms
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.forms import formset_factory

from arkumu.metadata.models import Resource, Triple


prt = ""

def get_objects_from_type_can_uri(type_can_uri):
    type = Resource.objects.get(canonical_uri=type_can_uri)
    if not type:
        return []
    triples = Triple.objects.filter(object=type)
    resources = list(set([triple.subject for triple in triples]))
    return resources

def get_objects_from_predicate_can_uri(predicate_can_uri):
    predicate = Resource.objects.get(canonical_uri=predicate_can_uri)
    if not predicate:
        return []
    triples = Triple.objects.filter(predicate=predicate)
    resources = list(set([triple.object for triple in triples]))
    return resources

def get_object_from_predicate_and_subject_can_uri(predicate_can_uri, subject):
    predicate = Resource.objects.get(canonical_uri=predicate_can_uri)
    if not predicate:
        return []
    triple = Triple.objects.filter(subject=subject, predicate=predicate).first()
    if not triple:
        return None
    resource = triple.object
    return resource

def get_uri_options(predicate_uri):
    resources = get_objects_from_type_can_uri(predicate_uri)
    options = []
    for resource in resources:
        label = get_label(predicate_uri, resource)
        if label == "fehlendes Label":
            label = "Unbekannter Eintrag (" + resource.uri + ")"
        options.append({'uri': resource.uri, 'label': label})
    return options

def get_label(predicate_uri, resource :Resource):
    object = None
    match predicate_uri :
        case "http://arkumu.org/data/types/einliefernde-hochschule":
            object = get_object_from_predicate_and_subject_can_uri("http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule", resource)
        case "http://arkumu.org/data/types/projektkategorie":
            object = get_object_from_predicate_and_subject_can_uri("http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb", resource)
        case "http://arkumu.org/data/types/projektart":
            object = get_object_from_predicate_and_subject_can_uri("http://arkumu.org/data/properties/deutscher-name-der-projektart", resource)
        case "http://arkumu.org/data/types/akteurin":
            object = get_object_from_predicate_and_subject_can_uri("http://arkumu.org/data/properties/deutscher-name", resource)
        case "http://arkumu.org/data/types/rolle":
            object = get_object_from_predicate_and_subject_can_uri("http://arkumu.org/data/properties/deutscher-name-der-rolle-breadcrumb", resource)
        case "http://arkumu.org/data/types/schlagwort":
            object = get_object_from_predicate_and_subject_can_uri("http://arkumu.org/data/properties/deutsches-wikidata-label", resource)
        case "http://arkumu.org/data/types/projekt":
            object = get_object_from_predicate_and_subject_can_uri("http://arkumu.org/data/properties/bevorzugter-titel", resource)
    return object.value if object else "fehlendes Label"

#[{"uri": "uri", "label": "label"}],#

URI_OPTIONS = {
    'institution': get_uri_options("http://arkumu.org/data/types/einliefernde-hochschule"),
    'project_category': get_uri_options("http://arkumu.org/data/types/projektkategorie"),
    'project_type': get_uri_options("http://arkumu.org/data/types/projektart"),
    'actor': get_uri_options("http://arkumu.org/data/types/akteurin"),
    'role': get_uri_options("http://arkumu.org/data/types/rolle"),
    'catchphrase': get_uri_options("http://arkumu.org/data/types/schlagwort"),
    'project': get_uri_options("http://arkumu.org/data/types/projekt"),  # Add project options for event creation
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
        choices=[('', 'Select an institution')] + [(opt['uri'], opt['label']) for opt in URI_OPTIONS['institution']]
    )
    projektkategorie_uri = forms.ChoiceField(
        label="Projektkategorie",
        required=True,
        choices=[('', 'Select a category')] + [(opt['uri'], opt['label']) for opt in URI_OPTIONS['project_category']]
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
        choices=[(opt['uri'], opt['label']) for opt in URI_OPTIONS['catchphrase']],
        widget=forms.SelectMultiple
    )
    projektart_uri = forms.ChoiceField(
        label="Projektart",
        required=True,
        choices=[('', 'Select a project type')] + [(opt['uri'], opt['label']) for opt in URI_OPTIONS['project_type']]
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
        choices=[('', 'Select a project')] + [(opt['uri'], opt['label']) for opt in URI_OPTIONS['project']]
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
        choices=[('', 'Select an actor')] + [(opt['uri'], opt['label']) for opt in URI_OPTIONS['actor']]
    )
    rollen_uri = forms.ChoiceField(
        label="Rolle",
        required=True,
        choices=[('', 'Select a role')] + [(opt['uri'], opt['label']) for opt in URI_OPTIONS['role']]
    )

# Create formsets for nested forms
ActorEventFormSet = formset_factory(ActorEventForm, extra=1, min_num=1, validate_min=True)

@login_required
def create_project(request):
    if request.method == "POST":
        project_form = ProjectForm(request.POST)

        if project_form.is_valid():
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
        "description": "Fill in the details to create a new archival project",
        "prt" : prt
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
