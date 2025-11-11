from __future__ import annotations

from typing import Optional

from django import forms

from arkumu.metadata.controlled_vocabularies.registry import (
    ColumnConfig,
    VocabularyConfig,
    column_to_field_name,
)
from arkumu.metadata.controlled_vocabularies.service import ControlledVocabularyService


class ControlledVocabularyForm(forms.Form):
    """
    Dynamic form generated from the vocabulary configuration.

    The form exposes a ``slug`` field used for canonical URI minting and one
    field per configured column.
    """

    def __init__(
        self,
        *,
        config: VocabularyConfig,
        service: ControlledVocabularyService,
        entry=None,
        **kwargs,
    ):
        self.config = config
        self.service = service
        self.entry = entry
        super().__init__(**kwargs)

        self.fields["slug"] = forms.SlugField(
            label="Identifier",
            help_text="Used to build the canonical URI; must be unique within the vocabulary.",
        )

        for column, column_config in self.config.columns.items():
            field_name = column_to_field_name(column)
            self.fields[field_name] = self._build_field(column, column_config)

        self._apply_widget_styles()

    @property
    def field_to_column(self) -> dict[str, str]:
        return {column_to_field_name(column): column for column in self.config.columns.keys()}

    def _build_field(self, column: str, column_config: ColumnConfig) -> forms.Field:
        label = column_config.form_label(column)
        help_text = column_config.help_text

        if column_config.value_type == "boolean":
            return forms.BooleanField(
                label=label,
                help_text=help_text,
                required=False,
            )

        if column_config.value_type == "reference":
            choices = [("", "— Keine —")] + self.service.get_reference_choices(exclude=self.entry)
            return forms.ChoiceField(
                label=label,
                help_text=help_text,
                required=column_config.required,
                choices=choices,
            )

        if column_config.value_type == "iri":
            return forms.URLField(
                label=label,
                help_text=help_text,
                required=column_config.required,
            )

        if column_config.split:
            return forms.CharField(
                label=label,
                help_text=help_text or "Ein Wert pro Zeile.",
                required=column_config.required,
                widget=forms.Textarea(attrs={"rows": 3}),
            )

        return forms.CharField(
            label=label,
            help_text=help_text,
            required=column_config.required,
        )

    def _apply_widget_styles(self) -> None:
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("class", "textarea textarea-bordered w-full")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "select select-bordered w-full")
            elif isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "toggle toggle-primary")
            else:
                widget.attrs.setdefault("class", "input input-bordered w-full")
