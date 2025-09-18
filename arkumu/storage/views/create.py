from django import forms
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.forms import formset_factory

# Mock data for URI options - in a real app, this would come from your database or API
URI_OPTIONS = {
    'institution': [
        {'id': '1', 'uri': 'http://arkumu.org/data/instances/einliefernde-hochschule/hfmdk', 'label': 'Hochschule für Musik und Darstellende Kunst Frankfurt'},
        {'id': '2', 'uri': 'http://arkumu.org/data/instances/einliefernde-hochschule/hfmw', 'label': 'Hochschule für Musik Würzburg'},
        {'id': '3', 'uri': 'http://arkumu.org/data/instances/einliefernde-hochschule/hfmk', 'label': 'Hochschule für Musik Karlsruhe'},
        {'id': '4', 'uri': 'http://arkumu.org/data/instances/einliefernde-hochschule/hfmh', 'label': 'Hochschule für Musik und Theater Hannover'},
    ],
    'project_category': [
        {'id': '1', 'uri': 'http://arkumu.org/data/instances/projektkategorie/kunst', 'label': 'Kunst'},
        {'id': '2', 'uri': 'http://arkumu.org/data/instances/projektkategorie/musik', 'label': 'Musik'},
        {'id': '3', 'uri': 'http://arkumu.org/data/instances/projektkategorie/theater', 'label': 'Theater'},
        {'id': '4', 'uri': 'http://arkumu.org/data/instances/projektkategorie/tanz', 'label': 'Tanz'},
    ],
    'project_type': [
        {'id': '1', 'uri': 'http://arkumu.org/data/instances/projektart/forschungsprojekt', 'label': 'Forschungsprojekt'},
        {'id': '2', 'uri': 'http://arkumu.org/data/instances/projektart/studienprojekt', 'label': 'Studienprojekt'},
        {'id': '3', 'uri': 'http://arkumu.org/data/instances/projektart/kunstprojekt', 'label': 'Kunstprojekt'},
        {'id': '4', 'uri': 'http://arkumu.org/data/instances/projektart/kooperationsprojekt', 'label': 'Kooperationsprojekt'},
    ],
    'actor': [
        {'id': '1', 'uri': 'http://arkumu.org/data/instances/akteurin/anna-mueller', 'label': 'Anna Müller'},
        {'id': '2', 'uri': 'http://arkumu.org/data/instances/akteurin/hans-schmidt', 'label': 'Hans Schmidt'},
        {'id': '3', 'uri': 'http://arkumu.org/data/instances/akteurin/clara-wagner', 'label': 'Clara Wagner'},
        {'id': '4', 'uri': 'http://arkumu.org/data/instances/akteurin/thomas-becker', 'label': 'Thomas Becker'},
    ],
    'role': [
        {'id': '1', 'uri': 'http://arkumu.org/data/instances/rolle/projektleitung', 'label': 'Projektleitung'},
        {'id': '2', 'uri': 'http://arkumu.org/data/instances/rolle/mitarbeiterin', 'label': 'Mitarbeiterin'},
        {'id': '3', 'uri': 'http://arkumu.org/data/instances/rolle/studentin', 'label': 'Studentin'},
        {'id': '4', 'uri': 'http://arkumu.org/data/instances/rolle/gastdozentin', 'label': 'Gastdozentin'},
    ],
    'catchphrase': [
        {'id': '1', 'uri': 'http://arkumu.org/data/instances/schlagwort/kunstgeschichte', 'label': 'Kunstgeschichte'},
        {'id': '2', 'uri': 'http://arkumu.org/data/instances/schlagwort/musiktheorie', 'label': 'Musiktheorie'},
        {'id': '3', 'uri': 'http://arkumu.org/data/instances/schlagwort/performing-arts', 'label': 'Performing Arts'},
        {'id': '4', 'uri': 'http://arkumu.org/data/instances/schlagwort/digital-humanities', 'label': 'Digital Humanities'},
    ]
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
        event_form = EventForm(request.POST)
        actor_event_formset = ActorEventFormSet(request.POST, prefix='actors')
        
        if project_form.is_valid() and event_form.is_valid() and actor_event_formset.is_valid():
            # Process the form data (in a real app, save to database)
            return HttpResponseRedirect("/storage/dashboard/")
    else:
        project_form = ProjectForm()
        event_form = EventForm()
        actor_event_formset = ActorEventFormSet(prefix='actors')

    return render(request, "storage/create_entity.html", {
        "project_form": project_form,
        "event_form": event_form,
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

    return render(request, "storage/create_entity.html", {
        "event_form": event_form,
        "actor_event_formset": actor_event_formset,
        "entity_type": "event",
        "title": "Create New Event",
        "description": "Fill in the details to create a new archival event"
    })