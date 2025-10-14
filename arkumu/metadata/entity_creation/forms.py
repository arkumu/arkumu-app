"""
Forms used by the metadata entity creation workflow.

They mirror the previous hand-written forms but live in a dedicated module so
the views can remain lean and rely on shared configuration.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from django import forms


def _with_placeholder(placeholder: str, options: Iterable[tuple[str, str]]) -> List[tuple[str, str]]:
    """Add a blank option with a placeholder label to the beginning of choices."""
    return [("", placeholder)] + list(options)


class BaseEntityForm(forms.Form):
    """Base form that applies consistent styling and optional disabling."""

    uri_field_name: str = "uri"

    def __init__(
        self,
        *args,
        metadata_options: Optional[dict] = None,
        disable_fields: bool = False,
        **kwargs,
    ):
        self.metadata_options = metadata_options or {}
        self.disable_fields = disable_fields
        super().__init__(*args, **kwargs)
        self._apply_default_widget_classes()
        if self.disable_fields:
            self._disable_data_fields()

    def _apply_default_widget_classes(self) -> None:
        for field_name, field in self.fields.items():
            widget = field.widget
            if field_name.endswith("_uri") or isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "select select-bordered w-full uri-field")
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("class", "textarea textarea-bordered w-full")
                widget.attrs.setdefault("rows", "4")
            elif (
                isinstance(widget, forms.DateInput)
                or isinstance(widget, forms.DateTimeInput)
            ):
                widget.attrs.setdefault("class", "input input-bordered w-full")
                if getattr(widget, "input_type", "") == "":
                    widget.input_type = "date"
            else:
                widget.attrs.setdefault("class", "input input-bordered w-full")

    def _disable_data_fields(self) -> None:
        for field_name, field in self.fields.items():
            if field_name == self.uri_field_name:
                # The selector stays enabled so the user can switch back to "new"
                continue
            field.widget.attrs["disabled"] = True
            field.required = False


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = _with_placeholder(
            "Select a project", options.get("project", [])
        )
        self.fields["einliefernde_hochschule_uri"].choices = _with_placeholder(
            "Select an institution", options.get("institution", [])
        )
        self.fields["projektkategorie_uri"].choices = _with_placeholder(
            "Select a category", options.get("project_category", [])
        )
        self.fields["beschreibung_uri"].choices = _with_placeholder(
            "Select the description of the project", options.get("description", [])
        )
        self.fields["schlagwort_uris"].choices = options.get("catchphrase", [])
        self.fields["projektart_uri"].choices = _with_placeholder(
            "Select a project type", options.get("project_type", [])
        )
        self.fields["vorschaubild_uri"].choices = _with_placeholder(
            "Select the URI of a preview image", options.get("digital_object", [])
        )


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
        required=False,
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
        widget=forms.DateInput(attrs={"type": "date"}),
        required=False,
        help_text="Start date of the event",
    )
    ereignisende = forms.DateField(
        label="Ereignisende",
        widget=forms.DateInput(attrs={"type": "date"}),
        required=False,
        help_text="End date of the event (optional)",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = _with_placeholder(
            "Select an event", options.get("event", [])
        )
        self.fields["project_uri"].choices = _with_placeholder(
            "Select a project", options.get("project", [])
        )
        self.fields["ereignisbeschreibung_uri"].choices = _with_placeholder(
            "Select the description of the event", options.get("event_description", [])
        )


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = _with_placeholder(
            "Select an actor", options.get("actor", [])
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = _with_placeholder(
            "Select a role", options.get("role", [])
        )


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = _with_placeholder(
            "Select a digital object", options.get("digital_object", [])
        )


class InstitutionForm(BaseEntityForm):
    uri = forms.ChoiceField(
        label="choose an existing institution, or create one",
        required=False,
        choices=[],
    )
    deutscher_name_der_einliefernden_hochschule = forms.CharField(
        label="Deutscher Name",
        required=True,
        help_text="Deutscher Name der einliefernden Hochschule",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = _with_placeholder(
            "Select an institution", options.get("institution", [])
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = _with_placeholder(
            "Select a project category", options.get("project_category", [])
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = _with_placeholder(
            "Select a project type", options.get("project_type", [])
        )


class AlternateTitleForm(BaseEntityForm):
    uri_field_name = "__missing__"

    alternativer_titel = forms.CharField(
        label="Alternativer Titel",
        required=True,
        help_text="Alternative title",
    )


class DescriptionForm(BaseEntityForm):
    uri_field_name = "__missing__"

    beschreibung = forms.CharField(
        label="Beschreibung",
        required=True,
        help_text="Description",
        widget=forms.Textarea,
    )


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        options = self.metadata_options
        self.fields["uri"].choices = _with_placeholder(
            "Select a catchphrase", options.get("catchphrase", [])
        )

