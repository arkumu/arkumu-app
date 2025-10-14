"""
Declarative configuration for metadata entity creation.

A central registry keeps the structural metadata for each entity type so the
views and services can operate generically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Literal, Sequence, Type

from .forms import (
    ActorForm,
    AlternateTitleForm,
    CatchphraseForm,
    DescriptionForm,
    DigitalObjectForm,
    EventForm,
    InstitutionForm,
    ProjectCategoryForm,
    ProjectForm,
    ProjectTypeForm,
    RoleForm,
    BaseEntityForm,
)


ValueType = Literal["literal", "entity", "entity_multi"]


@dataclass(frozen=True)
class FieldConfig:
    """Mapping between a form field and the RDF property it controls."""

    field_name: str
    property_path: str
    property_label: str
    value_type: ValueType = "literal"


@dataclass(frozen=True)
class EntityCreationConfig:
    """Configuration entry describing how to create a given entity type."""

    key: str
    dataset_name: str
    class_path: str
    class_label: str
    form_class: Type[BaseEntityForm]
    template_name: str
    form_partial: str
    title: str
    description: str
    fields: Sequence[FieldConfig] = field(default_factory=tuple)
    success_url_name: str = "metadata:metadata_entry"


ENTITY_CREATION_CONFIG: Dict[str, EntityCreationConfig] = {
    "project": EntityCreationConfig(
        key="project",
        dataset_name="Projekt",
        class_path="types/projekt",
        class_label="Projekt",
        form_class=ProjectForm,
        template_name="metadata/entity_creation/create_project.html",
        form_partial="metadata/entity_creation/partials/_project_form_fields.html",
        title="Create New Project",
        description="Fill in the details to create a new archival project",
        fields=(
            FieldConfig(
                field_name="bevorzugter_titel",
                property_path="properties/bevorzugter-titel",
                property_label="Bevorzugter Titel",
            ),
            FieldConfig(
                field_name="bevorzugter_untertitel",
                property_path="properties/bevorzugter-untertitel",
                property_label="Bevorzugter Untertitel",
            ),
            FieldConfig(
                field_name="einliefernde_hochschule_uri",
                property_path="properties/einliefernde-hochschule",
                property_label="Einliefernde Hochschule",
                value_type="entity",
            ),
            FieldConfig(
                field_name="projektkategorie_uri",
                property_path="properties/projektkategorie",
                property_label="Projektkategorie",
                value_type="entity",
            ),
            FieldConfig(
                field_name="beschreibung_uri",
                property_path="properties/beschreibung",
                property_label="Beschreibung",
                value_type="entity",
            ),
            FieldConfig(
                field_name="schlagwort_uris",
                property_path="properties/schlagwort",
                property_label="Schlagwort",
                value_type="entity_multi",
            ),
            FieldConfig(
                field_name="projektart_uri",
                property_path="properties/projektart",
                property_label="Projektart",
                value_type="entity",
            ),
            FieldConfig(
                field_name="vorschaubild_uri",
                property_path="properties/vorschaubild",
                property_label="Vorschaubild",
                value_type="entity",
            ),
        ),
    ),
    "event": EntityCreationConfig(
        key="event",
        dataset_name="Ereignis",
        class_path="types/ereignis",
        class_label="Ereignis",
        form_class=EventForm,
        template_name="metadata/entity_creation/create_event.html",
        form_partial="metadata/entity_creation/partials/_event_form_fields.html",
        title="Create New Event",
        description="Fill in the details to create a new archival event",
        fields=(
            FieldConfig(
                field_name="ereignisname",
                property_path="properties/ereignisname",
                property_label="Ereignisname",
            ),
            FieldConfig(
                field_name="ereignisort",
                property_path="properties/ereignisort",
                property_label="Ereignisort",
            ),
            FieldConfig(
                field_name="ereignisbeschreibung_uri",
                property_path="properties/beschreibung",
                property_label="Beschreibung",
                value_type="entity",
            ),
            FieldConfig(
                field_name="ereignisbeginn",
                property_path="properties/ereignisbeginn",
                property_label="Ereignisbeginn",
            ),
            FieldConfig(
                field_name="ereignisende",
                property_path="properties/ereignisende",
                property_label="Ereignisende",
            ),
        ),
    ),
    "actor": EntityCreationConfig(
        key="actor",
        dataset_name="Akteurin",
        class_path="types/akteurin",
        class_label="Akteurin",
        form_class=ActorForm,
        template_name="metadata/entity_creation/create_actor.html",
        form_partial="metadata/entity_creation/partials/_actor_form_fields.html",
        title="Create New Actor",
        description="Fill in the details to create a new archival actor",
        fields=(
            FieldConfig(
                field_name="deutscher_name",
                property_path="properties/deutscher-name",
                property_label="Deutscher Name",
            ),
        ),
    ),
    "role": EntityCreationConfig(
        key="role",
        dataset_name="Rolle",
        class_path="types/rolle",
        class_label="Rolle",
        form_class=RoleForm,
        template_name="metadata/entity_creation/create_role.html",
        form_partial="metadata/entity_creation/partials/_role_form_fields.html",
        title="Create New Role",
        description="Fill in the details to create a new archival role",
        fields=(
            FieldConfig(
                field_name="deutscher_name_der_rolle_breadcrumb",
                property_path="properties/deutscher-name-der-rolle-breadcrumb",
                property_label="Deutscher Name der Rolle Breadcrumb",
            ),
        ),
    ),
    "digital_object": EntityCreationConfig(
        key="digital_object",
        dataset_name="Digitales Objekt",
        class_path="types/digitales-objekt",
        class_label="Digitales Objekt",
        form_class=DigitalObjectForm,
        template_name="metadata/entity_creation/create_digital_object.html",
        form_partial="metadata/entity_creation/partials/_digital_object_form_fields.html",
        title="Create New Digital Object",
        description="Fill in the details to create a new digital object",
        fields=(
            FieldConfig(
                field_name="dateipfad",
                property_path="properties/dateipfad",
                property_label="Dateipfad",
            ),
        ),
    ),
    "institution": EntityCreationConfig(
        key="institution",
        dataset_name="Einliefernde Hochschule",
        class_path="types/einliefernde-hochschule",
        class_label="Einliefernde Hochschule",
        form_class=InstitutionForm,
        template_name="metadata/entity_creation/create_institution.html",
        form_partial="metadata/entity_creation/partials/_institution_form_fields.html",
        title="Create New Institution",
        description="Fill in the details to create a new institutional affiliation",
        fields=(
            FieldConfig(
                field_name="deutscher_name_der_einliefernden_hochschule",
                property_path="properties/deutscher-name-der-einliefernden-hochschule",
                property_label="Deutscher Name der Einliefernden Hochschule",
            ),
        ),
    ),
    "project_category": EntityCreationConfig(
        key="project_category",
        dataset_name="Projektkategorie",
        class_path="types/projektkategorie",
        class_label="Projektkategorie",
        form_class=ProjectCategoryForm,
        template_name="metadata/entity_creation/create_project_category.html",
        form_partial="metadata/entity_creation/partials/_project_category_form_fields.html",
        title="Create New Project Category",
        description="Fill in the details to create a new project category",
        fields=(
            FieldConfig(
                field_name="deutscher_name_der_projektkategorie_breadcrumb",
                property_path="properties/deutscher-name-der-projektkategorie-breadcrumb",
                property_label="Deutscher Name der Projektkategorie Breadcrumb",
            ),
        ),
    ),
    "project_type": EntityCreationConfig(
        key="project_type",
        dataset_name="Projektart",
        class_path="types/projektart",
        class_label="Projektart",
        form_class=ProjectTypeForm,
        template_name="metadata/entity_creation/create_project_type.html",
        form_partial="metadata/entity_creation/partials/_project_type_form_fields.html",
        title="Create New Project Type",
        description="Fill in the details to create a new project type",
        fields=(
            FieldConfig(
                field_name="deutscher_name_der_projektart",
                property_path="properties/deutscher-name-der-projektart",
                property_label="Deutscher Name der Projektart",
            ),
        ),
    ),
    "alternate_title": EntityCreationConfig(
        key="alternate_title",
        dataset_name="Alternativer Titel",
        class_path="types/alternativer-titel",
        class_label="Alternativer Titel",
        form_class=AlternateTitleForm,
        template_name="metadata/entity_creation/create_alternate_title.html",
        form_partial="metadata/entity_creation/partials/_alternate_title_form_fields.html",
        title="Create New Alternate Title",
        description="Fill in the details to create a new alternate title",
        fields=(
            FieldConfig(
                field_name="alternativer_titel",
                property_path="properties/alternativer-titel",
                property_label="Alternativer Titel",
            ),
        ),
    ),
    "description": EntityCreationConfig(
        key="description",
        dataset_name="Beschreibung",
        class_path="types/beschreibung",
        class_label="Beschreibung",
        form_class=DescriptionForm,
        template_name="metadata/entity_creation/create_description.html",
        form_partial="metadata/entity_creation/partials/_description_form_fields.html",
        title="Create New Description",
        description="Fill in the details to create a new description",
        fields=(
            FieldConfig(
                field_name="beschreibung",
                property_path="properties/beschreibung",
                property_label="Beschreibung",
            ),
        ),
    ),
    "catchphrase": EntityCreationConfig(
        key="catchphrase",
        dataset_name="Schlagwort",
        class_path="types/schlagwort",
        class_label="Schlagwort",
        form_class=CatchphraseForm,
        template_name="metadata/entity_creation/create_catchphrase.html",
        form_partial="metadata/entity_creation/partials/_catchphrase_form_fields.html",
        title="Create New Catchphrase",
        description="Fill in the details to create a new catchphrase",
        fields=(
            FieldConfig(
                field_name="deutsches_wikidata_label",
                property_path="properties/deutsches-wikidata-label",
                property_label="Deutsches Wikidata Label",
            ),
        ),
    ),
}

