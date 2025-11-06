from __future__ import annotations

from typing import Any, Dict, Iterable, List

from django import forms


def _humanize_label(raw: str) -> str:
    raw = raw or ""
    if not raw:
        return raw

    # Remove technical suffixes like _uri, _id before humanizing
    cleaned = raw
    if cleaned.endswith("_uri"):
        cleaned = cleaned[:-4]  # Remove "_uri"
    elif cleaned.endswith("_id"):
        cleaned = cleaned[:-3]  # Remove "_id"

    label = cleaned.replace("_", " ").replace("-", " ").strip()
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
        hide_anchors: bool = True,
        **kwargs,
    ) -> None:
        kwargs.setdefault("initial", initial or {})
        super().__init__(*args, **kwargs)
        self.field_metadata = field_metadata
        self.anchor_fields: List[str] = []
        self.property_fields: List[str] = []
        self.hide_anchors = hide_anchors

        sorted_fields = sorted(
            field_metadata.items(),
            key=lambda item: (str(item[1].get("property_label") or item[0]).lower(), item[0]),
        )

        for column_name, meta in sorted_fields:
            field = self._build_field(column_name, meta, disable_anchors, hide_anchors)
            self.fields[column_name] = field
            self.property_fields.append(column_name)
            if meta.get("is_anchor"):
                self.anchor_fields.append(column_name)

    # ------------------------------------------------------------------ #
    def _build_field(
        self, column_name: str, meta: Dict[str, Any], disable_anchor: bool, hide_anchor: bool
    ) -> forms.Field:
        label = meta.get("property_label") or meta.get("arkumu_type") or column_name
        field_label = _humanize_label(label)

        is_anchor = meta.get("is_anchor")

        # If hiding anchors, use HiddenInput widget
        if is_anchor and hide_anchor:
            return forms.CharField(
                required=False,
                widget=forms.HiddenInput(),
            )

        required = bool(meta.get("is_required")) or bool(meta.get("is_anchor"))

        # Multi-value fields use dynamic add/remove UI, not textarea splitting
        if meta.get("is_multi_value"):
            column_type = meta.get("column_type", "")

            # Multi-value fields render as a special widget with + button
            # The actual form field is just for validation
            field = forms.CharField(
                label=field_label,
                required=required,
                widget=forms.HiddenInput(
                    attrs={
                        "data-column": column_name,
                        "data-column-type": column_type,
                        "data-multi-value": "true",
                    }
                ),
            )
            # Template will render the dynamic add/remove UI
        else:
            field = forms.CharField(
                label=field_label,
                required=required,
                widget=forms.TextInput(
                    attrs={
                        "class": "input input-bordered w-full",
                        "data-column": column_name,
                        "data-column-type": meta.get("column_type"),
                    }
                ),
            )

        # Legacy support: disable anchor if requested (but anchors are usually hidden now)
        if is_anchor and disable_anchor:
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
