"""Views and forms for creating metadata-backed entities (projects, events)."""

from __future__ import annotations

from django import forms
from django.db import models
from django.contrib.auth.decorators import login_required
from django.forms import formset_factory, inlineformset_factory
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
import logging

from arkumu.metadata.models.resource import Resource, ResourceType, PublicAccessLevel
from arkumu.metadata.models.triples import Triple

from arkumu.metadata.services.vocabulary_options_service import (
    get_default_metadata_option_map,
)
from arkumu.metadata.models.resources import (
    ClassResource,
    PropertyResource,
    EntityResource,
)
from arkumu.metadata.entity_creation import EntityCreationService
from arkumu.users.models import Organization

logger = logging.getLogger(__name__)

BASE_URI = "http://arkumu.org/data"
def get_properties(org_code):
    return {
    "Projekt":{
                "title_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/bevorzugter-titel",
                    name="Bevorzugter Titel",
                )[0],
                "subtitle_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/bevorzugter-untertitel",
                    name="Bevorzugter Untertitel",
                )[0],
                "event_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/ereignis",
                    name="Ereignis",
                )[0],
                "institution_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/einliefernde-hochschule",
                    name="Einliefernde Hochschule",
                )[0],
                "category_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/projektkategorie",
                    name="Projektkategorie",
                )[0],
                "catchphrase_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/schlagwort", name="Schlagwort"
                )[0],
                "project_type_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/projektart", name="Projektart"
                )[0],
                "preview_image_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/vorschaubild", name="Vorschaubild"
                )[0],
                "hochschule_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/properties/hochschule",
                    name="Hochschule",
                )[0],
                "organisationseinheit_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/organisationseinheit",
                    name="Organisationseinheit",
                )[0],
                "erstellungsdatum_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/erstellungsdatum",
                    name="Erstellungsdatum",
                )[0],
                "letzteModifikation_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/letzteModifikation",
                    name="Letzte Modifikation",
                )[0],
                "projektStatus_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/projektStatus",
                    name="Projekt Status",
                )[0],
                "signatur_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/signatur",
                    name="Signatur",
                )[0],
                "signaturEinlieferer_prop": PropertyResource.get_or_create(  
                    uri=f"{BASE_URI}/{org_code}/properties/signaturEinlieferer",
                    name="Signatur beim Einlieferer",
                )[0],
                "verzeichnisnummern": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/verzeichnisnummern",
                    name="Werkverzeichnis-Nr",
                )[0],
            },
    "Ereignis":{
                "event_name_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/ereignisname", name="Ereignisname"
                )[0],
                "event_place_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/ereignisort", name="Ereignisort"
                )[0],
                "description_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/beschreibung", name="Beschreibung"
                )[0],
                "begin_date_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/ereignisbeginn", name="Ereignisbeginn"
                )[0],
                "end_date_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/ereignisende", name="Ereignisende"
                )[0],
            },
    "Akteurin":{
                "german_name_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/deutscher-name", name="Deutscher Name"
                )[0],
            },
    "Rolle":{
                "german_name_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/deutscher-name-der-rolle-breadcrumb",
                    name="Deutscher Name der Rolle Breadcrumb",
                )[0],
            },
    "Beschreibung":{
                "description_prop": PropertyResource.get_or_create(
                    uri=f"{BASE_URI}/{org_code}/properties/beschreibung", name="Beschreibung"
                )[0],
            },
}


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
    """Single project form shared by create and edit flows."""

    MODE_CREATE = "create"
    MODE_EDIT = "edit"

    uri = forms.ChoiceField(
        label="Projekt",
        required=False,
        choices=[],
    )
    bevorzugter_titel = forms.CharField(
        label="Bevorzugter Titel",
        required=True,
        help_text="Primary title of the project",
    )
    titel_sprache = forms.CharField(
        label="Sprache Titel",
        required=False,
        help_text="Language of the preferred title",
    )
    bevorzugter_untertitel = forms.CharField(
        label="Bevorzugter Untertitel",
        required=False,
        help_text="Optional subtitle for the project",
    )
    beschreibung = forms.CharField(
        label="Beschreibung",
        required=False,
        widget=forms.Textarea,
    )
    einliefernde_hochschule_uri = forms.ChoiceField(
        label="Einliefernde Hochschule",
        required=True,
        choices=[],
    )
    hochschule_uri = forms.ChoiceField(
        label="Hochschule",
        required=True,
        choices=[],
    )
    organisationseinheit_uri = forms.ChoiceField(
        label="Organisationseinheit",
        required=False,
        choices=[],
    )
    ereignis_uri = forms.ChoiceField(
        label="Zugehöriges Ereignis",
        required=False,
        choices=[],
    )
    projektkategorie_uri = forms.ChoiceField(
        label="Projektkategorie",
        required=True,
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
    erstellungsdatum = forms.DateField(
        label="Erstellungsdatum",
        widget=forms.DateInput(attrs={"type": "date"}),
        required=False,
        help_text="Erstellungsdatum beim Einlieferer",
    )
    letzteModifikation = forms.DateField(
        label="Letzte Projektmodifikation beim Einlieferer",
        widget=forms.DateInput(attrs={"type": "date"}),
        required=False,
        help_text="Letzte Modifikation beim Einlieferer",
    )
    projektStatus_uri = forms.ChoiceField(
        label="Status",
        required=True,
        choices=[],
    )
    signatur = forms.CharField(
        label="Signatur",
        required=False,
        help_text="Eine vom System automatisch erstellte Signatur für das Projekt.",
    )
    signaturEinlieferer = forms.CharField(
        label="Signatur beim Einlieferer",
        required=False,
        help_text="Eine vom Einlieferer vergebene Signatur für das Projekt.",
    )
    verzeichnisnummern = forms.CharField(
        label="Werkverzeichnis-Nr",
        required=False,
        help_text="Mehrere Nummern mit Semikolon trennen, z. B. „BWV 1010; BWV 1011“.",
    )

    def __init__(self, *args, metadata_options=None, mode: str = MODE_CREATE, **kwargs):
        if mode not in {self.MODE_CREATE, self.MODE_EDIT}:
            raise ValueError(f"Unsupported project form mode '{mode}'")
        self.mode = mode
        super().__init__(*args, metadata_options=metadata_options, **kwargs)

        options = self.metadata_options or {}
        project_choices = list(options.get("project", []))

        if self.mode == self.MODE_EDIT:
            self.fields["uri"].required = True
            self.fields["uri"].choices = [("", "Bitte Projekt wählen"), *project_choices]
        else:
            self.fields["uri"].required = False
            self.fields["uri"].choices = [("", "Select a project"), *project_choices]

        def _set_choices(field_name: str, placeholder: str | None, option_key: str) -> None:
            if field_name not in self.fields:
                return
            choices = list(options.get(option_key, []))
            if placeholder is not None:
                self.fields[field_name].choices = [("", placeholder), *choices]
            else:
                self.fields[field_name].choices = choices

        if "einliefernde_hochschule_uri" in self.fields:
            placeholder = "Select an institution" if self.mode == self.MODE_CREATE else "Bitte Institution wählen"
            _set_choices("einliefernde_hochschule_uri", placeholder, "institution")
        if "hochschule_uri" in self.fields:
            placeholder = "Select an institution" if self.mode == self.MODE_CREATE else "Bitte Institution wählen"
            _set_choices("hochschule_uri", placeholder, "institution")
        _set_choices("organisationseinheit_uri", "Select an organisationseinheit", "organisationseinheit")
        _set_choices("ereignis_uri", "Select an event", "event")
        _set_choices("projektkategorie_uri", "Select a category", "project_category")
        _set_choices("projektart_uri", "Select a project type", "project_type")
        _set_choices("vorschaubild_uri", "Select the URI of a preview image", "digital_object")

        status_choices = list(options.get("projektStatus") or options.get("project_status") or [])
        self.fields["projektStatus_uri"].choices = [("", "Select the status of the project"), *status_choices]

        schlagwort_choices = list(options.get("catchphrase", []))
        self.fields["schlagwort_uris"].choices = schlagwort_choices
        self.fields["schlagwort_uris"].widget.attrs.setdefault("class", "select select-bordered w-full")
        self.fields["schlagwort_uris"].widget.attrs.setdefault("size", "6")

        if self.mode == self.MODE_EDIT:
            for field_name in (
                "einliefernde_hochschule_uri",
                "hochschule_uri",
                "projektkategorie_uri",
                "projektart_uri",
                "projektStatus_uri",
            ):
                if field_name in self.fields:
                    self.fields[field_name].required = False


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

    def __init__(self, *args, metadata_options=None, uri = None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = [("", "Select an event")] + options.get(
            "event", []
        )
        self.fields["ereignisbeschreibung_uri"].choices = [
            ("", "Select the description of the event")
        ] + options.get("event_description", [])

        if uri:
            entity, created = EntityResource.get_or_create(uri)
            if created:
                return
            
            org_code = entity.uri.split("/")[4]
            properties = get_properties(org_code)["Ereignis"]

            # Pre-fill form fields with existing entity data
            self.fields["uri"].initial = uri
            self.fields["ereignisname"].initial = entity.get_property(properties["event_name_prop"])[0] if entity.get_property(properties["event_name_prop"]) else ""
            self.fields["ereignisbeschreibung_uri"].initial = entity.get_property(properties["description_prop"])[0].uri if entity.get_property(properties["description_prop"]) else ""
            self.fields["ereignisort"].initial = entity.get_property(properties["event_place_prop"])[0] if entity.get_property(properties["event_place_prop"]) else ""
            self.fields["ereignisbeginn"].initial = entity.get_property(properties["begin_date_prop"])[0] if entity.get_property(properties["begin_date_prop"]) else ""
            self.fields["ereignisende"].initial = entity.get_property(properties["end_date_prop"])[0] if entity.get_property(properties["end_date_prop"]) else ""


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


class EventEditForm(BaseEntityForm):
    uri = forms.ChoiceField(
        label="Ereignis auswählen",
        required=True,
        choices=[],
    )
    ereignisname = forms.CharField(
        label="Titel",
        required=True,
    )
    ereignisbeschreibung = forms.CharField(
        label="Ereignisbeschreibung",
        required=False,
        widget=forms.Textarea,
    )
    ereignisort = forms.CharField(
        label="Ort",
        required=False,
    )
    ereignisbeginn = forms.DateField(
        label="Beginn",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    ereignisende = forms.DateField(
        label="Ende",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = [("", "Bitte Ereignis wählen")] + options.get("event", [])

class AlternateTitleForm(BaseEntityForm):
    alternativer_titel = forms.CharField(
        label="Alternativer Titel",
        required=True,
        help_text="Alternative title",
    )

    def __init__(self, *args, metadata_options=None, **kwargs):
        super().__init__(*args, metadata_options=metadata_options, **kwargs)


DescriptionFormSet = formset_factory(DescriptionForm, extra=0, min_num=1, validate_min=False)

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
                dataset_name=dataset_name, organization=organization, public_access_level=PublicAccessLevel.PRIVATE
            )
            cls, _ = ClassResource.get_or_create(
                uri=f"{base_uri}/types/projekt", name=dataset_name
            )
            properties = get_properties(organization.code)["Projekt"]
            return (entity, cls, properties)
        case "Ereignis":
            entity, _ = EntityResource.create_by_organization_and_dataset_name(
                dataset_name=dataset_name, organization=organization
            )
            cls, _ = ClassResource.get_or_create(
                uri=f"{base_uri}/types/ereignis", name=dataset_name
            )
            properties = get_properties(organization.code)["Ereignis"]
            return (entity, cls, properties)
        case "Akteurin":
            entity, _ = EntityResource.create_by_organization_and_dataset_name(
                dataset_name=dataset_name, organization=organization
            )
            cls, _ = ClassResource.get_or_create(
                uri=f"{base_uri}/types/akteurin", name=dataset_name
            )
            properties = get_properties(organization.code)["Akteurin"]
            return (entity, cls, properties)
        case "Rolle":
            entity, _ = EntityResource.create_by_organization_and_dataset_name(
                dataset_name=dataset_name, organization=organization
            )
            cls, _ = ClassResource.get_or_create(
                uri=f"{base_uri}/types/rolle", name=dataset_name
            )
            properties = get_properties(organization.code)["Rolle"]
            return (entity, cls, properties)
        case "Beschreibung":
            entity, _ = EntityResource.create_by_organization_and_dataset_name(
                dataset_name=dataset_name, organization=organization
            )
            cls, _ = ClassResource.get_or_create(
                uri=f"{base_uri}/types/beschreibung", name=dataset_name
            )
            properties = get_properties(organization.code)["Beschreibung"]
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
                form, entity, "ereignis_uri", kwargs["event_prop"]
            )
            from_form_set_property_entity(
                form, entity, "projektkategorie_uri", kwargs["category_prop"]
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
            from_form_set_property_entity(
                form, entity, "hochschule_prop", kwargs["hochschule_prop"]
            )
            from_form_set_property_entity(
                form, entity, "organisationseinheit_prop", kwargs["organisationseinheit_prop"]
            )
            from_form_set_property_entity(
                form, entity, "erstellungsdatum", kwargs["erstellungsdatum"]
            )
            from_form_set_property_entity(
                form, entity, "letzteModifikation", kwargs["letzteModifikation"]
            )

            from_form_set_property_entity(
                form, entity, "projektStatus_uri", kwargs["projektStatus_uri"]
            )
            from_form_set_property_literal(
                form, entity, "signatur", kwargs["signatur"]
            )   
            from_form_set_property_literal(
                form, entity, "signaturEinlieferer", kwargs["signaturEinlieferer"]
            )   
            from_form_set_property_literal(
                form, entity, "verzeichnisnummern", kwargs["verzeichnisnummern"]
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
                form, entity, "deutscher_name", kwargs["german_name_prop"]
            )
        case "Rolle":
            from_form_set_property_literal(
                form, entity, "deutscher_name_der_rolle_breadcrumb", kwargs["german_name_prop"]
            )
        case "Beschreibung":
            from_form_set_property_literal(
                form, entity, "beschreibung", kwargs["description_prop"]
            )


def form_to_entity(form: BaseEntityForm, dataset_name, organization):
    base_uri = f"http://arkumu.org/data/{organization.code}"
    if form.is_valid():
        if uri := form.cleaned_data.get("uri", ""):
            # logger.info(f"🔄✅✅✅ {uri=} truesy")
            return EntityResource.get_or_create(uri)
        # logger.info(f"🔄❌❌❌ {uri=} falsy")
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
            base_uri = f"http://arkumu.org/data/{organization.code}"
            project_form = ProjectForm(
                request.POST,
                metadata_options=metadata_options,
                mode=ProjectForm.MODE_CREATE,
            )

            description_formset = DescriptionFormSet(
                request.POST,
                prefix="descriptions",
                form_kwargs={"metadata_options": metadata_options},
            )

            if project_form.is_valid():
                project_entity = form_to_entity(project_form, "Projekt", organization)

                for description_form in description_formset:
                    if description_form.is_valid():
                        description_entity = form_to_entity(description_form, "Beschreibung", organization)
                        description_prop, _ = PropertyResource.get_or_create(
                            uri=f"{base_uri}/properties/beschreibung", name="Beschreibung"
                        )
                        project_entity.set_property(description_prop, description_entity)
                # The RDF resources are now created and linked automatically
                # Continue with the rest of the project creation workflow
                return HttpResponseRedirect("/metadata/metadata-entry/")
        else:
            project_form = ProjectForm(metadata_options=metadata_options, mode=ProjectForm.MODE_CREATE)
            description_formset = DescriptionFormSet(
                prefix="descriptions",
                form_kwargs={"metadata_options": metadata_options},
            )

        return render(
            request,
            "metadata/entity_creation/create_project.html",
            {
                "project_form": project_form,
                "description_formset": description_formset,
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
            if event_form.is_valid():
                event_entity = form_to_entity(event_form, "Ereignis", organization)


                ####THIS SHOULD BE REPLACED BY THE ENTITY URI FIELD IN PROJECT
                # event_prop, _ = PropertyResource.get_or_create(
                #     uri=f"{base_uri}/properties/ereignis", name="Ereignis"
                # )
                # project_uri = event_form.cleaned_data.get("project_uri", "")
                # if project_uri:
                #     project_entity, _ = EntityResource.get_or_create(uri=project_uri)
                #     project_entity.set_property(event_prop, event_entity)


            # The RDF resources are now created and linked automatically
            # Continue with the rest of the event creation workflow

            return HttpResponseRedirect("/metadata/metadata-entry/")
        else:
            event_form = EventForm(metadata_options=metadata_options)

        return render(
            request,
            "metadata/entity_creation/create_event.html",
            {
                "event_form": event_form,
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
                actor_entity = form_to_entity(actor_form, "Akteurin", organization)

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
                role_entity = form_to_entity(role_form, "Rolle", organization)

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
                description_entity = form_to_entity(description_form, "Beschreibung", organization)

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
def edit_project(request):
    organization = getattr(request.user, "organization", None)
    if not organization:
        return HttpResponseRedirect("/metadata/metadata-entry/")

    metadata_options = get_default_metadata_option_map(organization=organization)
    service = EntityCreationService.for_key("project", organization)

    def _resolve_resource(uri: str) -> Resource | None:
        if not uri:
            return None
        try:
            resource = Resource.objects.get(uri=uri)
        except Resource.DoesNotExist:
            return None
        if resource.organization_id and resource.organization_id != organization.id:
            return None
        return resource

    def _build_initial(uri: str) -> dict:
        resource = _resolve_resource(uri)
        if resource is None:
            return {}
        entity = EntityResource(resource)
        initial = service.build_initial_data(entity) or {}
        initial["uri"] = uri
        if initial.get("schlagwort_uris") and not isinstance(initial["schlagwort_uris"], (list, tuple)):
            initial["schlagwort_uris"] = [initial["schlagwort_uris"]]
        for key in (
            "einliefernde_hochschule_uri",
            "projektkategorie_uri",
            "projektart_uri",
            "vorschaubild_uri",
            "projektStatus_uri",
        ):
            value = initial.get(key)
            if isinstance(value, (list, tuple)):
                initial[key] = value[0] if value else ""
        return initial

    if request.method == "POST":
        project_form = ProjectForm(
            request.POST,
            metadata_options=metadata_options,
            mode=ProjectForm.MODE_EDIT,
        )
        if project_form.is_valid():
            selected_uri = project_form.cleaned_data.get("uri")
            if not selected_uri:
                project_form.add_error("uri", "Bitte ein Projekt auswählen.")
            else:
                resource = _resolve_resource(selected_uri)
                if resource is None:
                    project_form.add_error("uri", "Projekt konnte nicht gefunden werden.")
                else:
                    entity = EntityResource(resource)
                    service.update_entity_from_form(entity=entity, form=project_form)
                    return HttpResponseRedirect("/metadata/metadata-entry/")
    else:
        selected_uri = request.GET.get("uri") or ""
        initial = _build_initial(selected_uri) if selected_uri else {}
        project_form = ProjectForm(
            metadata_options=metadata_options,
            initial=initial,
            mode=ProjectForm.MODE_EDIT,
        )

    return render(
        request,
        "metadata/entity_editing/edit_project.html",
        {
            "project_form": project_form,
            "entity_type": "project",
            "title": "Projekt bearbeiten",
            "description": "Felder ausfüllen, um das Projekt zu aktualisieren.",
        },
    )


@login_required
def edit_event(request):
    organization = getattr(request.user, "organization", None)

    if not organization:
        return HttpResponseRedirect("/metadata/metadata-entry/")

    metadata_options = get_default_metadata_option_map(organization=organization)
    service = EntityCreationService.for_key("event", organization)

    def _resolve_resource(uri: str) -> Resource | None:
        if not uri:
            return None
        try:
            resource = Resource.objects.get(uri=uri)
        except Resource.DoesNotExist:
            return None
        if resource.organization_id and resource.organization_id != organization.id:
            return None
        return resource

    def _parse_date(value: object):
        if not value:
            return value
        if isinstance(value, (str,)):
            try:
                from datetime import date

                return date.fromisoformat(value)
            except ValueError:
                return value
        return value

    def _build_initial(uri: str) -> dict:
        resource = _resolve_resource(uri)
        if resource is None:
            return {}
        entity = EntityResource(resource)
        initial = service.build_initial_data(entity) or {}
        initial["uri"] = uri
        for key in ("ereignisbeginn", "ereignisende"):
            initial[key] = _parse_date(initial.get(key))
        return initial

    if request.method == "POST":
        event_form = EventEditForm(
            request.POST,
            metadata_options=metadata_options,
        )
        if event_form.is_valid():
            selected_uri = event_form.cleaned_data.get("uri")
            if not selected_uri:
                event_form.add_error("uri", "Bitte ein Ereignis auswählen.")
            else:
                resource = _resolve_resource(selected_uri)
                if resource is None:
                    event_form.add_error("uri", "Ereignis konnte nicht gefunden werden.")
                else:
                    entity = EntityResource(resource)
                    service.update_entity_from_form(entity=entity, form=event_form)
                    return HttpResponseRedirect("/metadata/metadata-entry/")
    else:
        selected_uri = request.GET.get("uri") or ""
        initial = _build_initial(selected_uri) if selected_uri else {}
        event_form = EventEditForm(
            metadata_options=metadata_options,
            initial=initial,
        )

    return render(
        request,
        "metadata/entity_editing/edit_event.html",
        {
            "event_form": event_form,
            "entity_type": "event",
            "title": "Ereignis bearbeiten",
            "description": "Felder ausfüllen, um das Ereignis zu aktualisieren.",
        },
    )


@login_required
def edit_actor(request):
    organization = getattr(request.user, "organization", None)

    if organization:
        metadata_options = get_default_metadata_option_map(organization=organization)

        # Initialize base URI for resource creation
        base_uri = f"http://arkumu.org/data/{organization.code}"

        if request.method == "POST":
            actor_form = ActorForm(request.POST, metadata_options=metadata_options)

            if actor_form.is_valid():
                actor_entity = form_to_entity(actor_form, "Akteurin", organization)

                # The RDF resources are now created and linked automatically
                return HttpResponseRedirect("/metadata/metadata-entry/")
        else:
            actor_form = ActorForm(metadata_options=metadata_options)

        return render(
            request,
            "metadata/entity_editing/edit_actor.html",
            {
                "actor_form": actor_form,
                "entity_type": "actor",
                "title": "edit New Actor",
                "description": "Fill in the details to edit a new archival actor",
            },
        )


@login_required
def edit_role(request):
    organization = getattr(request.user, "organization", None)

    if organization:
        metadata_options = get_default_metadata_option_map(organization=organization)

        # Initialize base URI for resource creation
        base_uri = f"http://arkumu.org/data/{organization.code}"

        if request.method == "POST":
            role_form = RoleForm(request.POST, metadata_options=metadata_options)

            if role_form.is_valid():
                role_entity = form_to_entity(role_form, "Rolle", organization)

                # The RDF resources are now created and linked automatically
                return HttpResponseRedirect("/metadata/metadata-entry/")
        else:
            role_form = RoleForm(metadata_options=metadata_options)

        return render(
            request,
            "metadata/entity_editing/edit_role.html",
            {
                "role_form": role_form,
                "entity_type": "role",
                "title": "edit New Role",
                "description": "Fill in the details to edit a new archival role",
            },
        )


@login_required
def edit_digital_object(request):
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
            "metadata/entity_editing/edit_digital_object.html",
            {
                "digital_object_form": digital_object_form,
                "entity_type": "digital_object",
                "title": "edit New Digital Object",
                "description": "Fill in the details to edit a new digital object",
            },
        )


@login_required
def edit_institution(request):
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
            "metadata/entity_editing/edit_institution.html",
            {
                "institution_form": institution_form,
                "entity_type": "institution",
                "title": "edit New Institution",
                "description": "Fill in the details to edit a new institutional affiliation",
            },
        )


@login_required
def edit_project_category(request):
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
            "metadata/entity_editing/edit_project_category.html",
            {
                "project_category_form": project_category_form,
                "entity_type": "project_category",
                "title": "edit New Project Category",
                "description": "Fill in the details to edit a new project category",
            },
        )


@login_required
def edit_project_type(request):
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
            "metadata/entity_editing/edit_project_type.html",
            {
                "project_type_form": project_type_form,
                "entity_type": "project_type",
                "title": "edit New Project Type",
                "description": "Fill in the details to edit a new project type",
            },
        )


@login_required
def edit_alternate_title(request):
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
            "metadata/entity_editing/edit_alternate_title.html",
            {
                "alternate_title_form": alternate_title_form,
                "entity_type": "alternate_title",
                "title": "edit New Alternate Title",
                "description": "Fill in the details to edit a new alternate title",
            },
        )


@login_required
def edit_description(request):
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
                description_entity = form_to_entity(description_form, "Beschreibung", organization)

                # The RDF resources are now created and linked automatically
                return HttpResponseRedirect("/metadata/metadata-entry/")
        else:
            description_form = DescriptionForm(metadata_options=metadata_options)

        return render(
            request,
            "metadata/entity_editing/edit_description.html",
            {
                "description_form": description_form,
                "entity_type": "description",
                "title": "edit New Description",
                "description": "Fill in the details to edit a new description",
            },
        )


@login_required
def edit_catchphrase(request):
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
            "metadata/entity_editing/edit_catchphrase.html",
            {
                "catchphrase_form": catchphrase_form,
                "entity_type": "catchphrase",
                "title": "edit New Catchphrase",
                "description": "Fill in the details to edit a new catchphrase",
            },
        )
