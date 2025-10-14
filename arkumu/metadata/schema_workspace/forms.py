from __future__ import annotations

from typing import Any, Dict, Iterable, List

from django import forms


def _humanize_label(raw: str) -> str:
    raw = raw or ""
    if not raw:
        return raw
    label = raw.replace("_", " ").replace("-", " ").strip()
    if not label:
        return raw
    return label[0].upper() + label[1:]


class DatasetEntityForm(forms.Form):
    """
    Dynamic form that renders fields based on schema metadata.
    """

    def __init__(
        self,
        *args,
        field_metadata: Dict[str, Dict[str, Any]],
        initial: Dict[str, Any] | None = None,
        disable_anchors: bool = False,
        **kwargs,
    ) -> None:
        kwargs.setdefault("initial", initial or {})
        super().__init__(*args, **kwargs)
        self.field_metadata = field_metadata
        self.anchor_fields: List[str] = []
        self.property_fields: List[str] = []

        for column_name, meta in field_metadata.items():
            field = self._build_field(column_name, meta, disable_anchors)
            self.fields[column_name] = field
            self.property_fields.append(column_name)
            if meta.get("is_anchor"):
                self.anchor_fields.append(column_name)

    # ------------------------------------------------------------------ #
    def _build_field(
        self, column_name: str, meta: Dict[str, Any], disable_anchor: bool
    ) -> forms.Field:
        label = meta.get("property_label") or meta.get("arkumu_type") or column_name
        field_label = _humanize_label(label)

        help_bits: List[str] = []
        if meta.get("is_anchor"):
            help_bits.append("Anchor field (unique identifier)")
        if meta.get("is_multi_value"):
            separator = meta.get("multi_value_separator", ",")
            help_bits.append(f"Multiple values separated by “{separator}”")
        if meta.get("is_external_ontology"):
            help_bits.append("Linked to an external identifier")
        if meta.get("has_fk"):
            help_bits.append("References another entity")

        required = bool(meta.get("is_required")) or bool(meta.get("is_anchor"))

        if meta.get("is_multi_value"):
            field = forms.CharField(
                label=field_label,
                required=required,
                help_text=" · ".join(help_bits) if help_bits else None,
                widget=forms.Textarea(
                    attrs={
                        "rows": 3,
                        "class": "textarea textarea-bordered",
                        "data-column": column_name,
                        "data-column-type": meta.get("column_type"),
                    }
                ),
            )
        else:
            field = forms.CharField(
                label=field_label,
                required=required,
                help_text=" · ".join(help_bits) if help_bits else None,
                widget=forms.TextInput(
                    attrs={
                        "class": "input input-bordered",
                        "data-column": column_name,
                        "data-column-type": meta.get("column_type"),
                    }
                ),
            )

        if meta.get("is_anchor") and disable_anchor:
            field.widget.attrs["readonly"] = True
            field.widget.attrs["class"] = (
                field.widget.attrs.get("class", "") + " input-disabled"
            ).strip()

        return field

    # ------------------------------------------------------------------ #
    def cleaned_entity_data(self) -> Dict[str, Any]:
        if not self.is_valid():
            raise ValueError("Form must be valid before extracting entity data")
        return {key: self.cleaned_data.get(key) for key in self.property_fields}

    def anchor_values(self) -> Dict[str, Any]:
        if not self.is_valid():
            raise ValueError("Form must be valid before accessing anchor values")
        return {key: self.cleaned_data.get(key) for key in self.anchor_fields}

    def visible_fields_in_order(self) -> Iterable[forms.BoundField]:
        for name in self.property_fields:
            yield self[name]
