import pytest
from datetime import timedelta
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization
from arkumu.catalog.services.project_views import CardURIs, ProjectURIs
from arkumu.metadata.views.tabular_views import (
    AUDIT_COLUMN_DEFINITIONS,
    _build_column_specs,
    _build_rows_for_subjects,
)


@pytest.mark.django_db
def test_project_tabular_maps_digikunst_columns(client):
    org = Organization.objects.create(name="FUK", code="fuk")

    session = client.session
    session["current_organization"] = {"id": org.id, "code": org.code, "name": org.name}
    session.save()

    subject = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/projekt/proj-1",
        resource_type=ResourceType.ENTITY,
        name="Projekt Alpha",
        organization=org,
    )

    def add_predicate(uri: str, name: str, canonical: str):
        return Resource.objects.create(
            uri=uri,
            resource_type=ResourceType.PROPERTY,
            name=name,
            canonical_uri=canonical,
            organization=org,
        )

    def add_literal(value: str):
        return Resource.objects.create(
            resource_type=ResourceType.LITERAL,
            value=value,
            organization=org,
        )

    def add_entity(uri: str, name: str | None):
        return Resource.objects.create(
            uri=uri,
            resource_type=ResourceType.ENTITY,
            name=name,
            organization=org,
        )

    # Title uses local property URI but canonical mapping
    title_pred = add_predicate(
        "http://arkumu.org/data/fuk/properties/bevorzugter-titel",
        "Bevorzugter Titel",
        CardURIs.TITLE,
    )
    Triple.objects.create(
        subject=subject,
        predicate=title_pred,
        object=add_literal("Projekt Alpha"),
        source=org,
    )

    # Project type literal
    project_type_pred = add_predicate(
        ProjectURIs.PROJECT_TYPE_FIELD,
        "Projektart",
        ProjectURIs.PROJECT_TYPE_FIELD,
    )
    Triple.objects.create(
        subject=subject,
        predicate=project_type_pred,
        object=add_literal("Ausstellung"),
        source=org,
    )

    # Category as FK
    category_pred = add_predicate(
        "http://arkumu.org/data/fuk/properties/projektkategorie",
        "Projektkategorie",
        CardURIs.CATEGORY,
    )
    category_entity = add_entity(
        "http://arkumu.org/data/fuk/entities/projektkategorie/kategorie-a",
        name=None,
    )
    Triple.objects.create(
        subject=subject,
        predicate=category_pred,
        object=category_entity,
        source=org,
    )
    category_label_pred = add_predicate(
        "http://arkumu.org/data/fuk/properties/deutscher-name-der-projektkategorie-breadcrumb",
        "Deutscher Name der Projektkategorie",
        CardURIs.CATEGORY_GERMAN_NAME,
    )
    Triple.objects.create(
        subject=category_entity,
        predicate=category_label_pred,
        object=add_literal("Kategorie A"),
        source=org,
    )

    # Institution as FK with canonical property
    institution_pred = add_predicate(
        CardURIs.INSTITUTION,
        "Einliefernde Hochschule",
        CardURIs.INSTITUTION,
    )
    institution_entity = add_entity(
        "http://arkumu.org/data/fuk/entities/institution/fuk",
        name=None,
    )
    Triple.objects.create(
        subject=subject,
        predicate=institution_pred,
        object=institution_entity,
        source=org,
    )
    institution_label_pred = add_predicate(
        "http://arkumu.org/data/fuk/properties/deutscher-name-der-einliefernden-hochschule",
        "Deutscher Name der einliefernden Hochschule",
        CardURIs.INSTITUTION_GERMAN_NAME,
    )
    Triple.objects.create(
        subject=institution_entity,
        predicate=institution_label_pred,
        object=add_literal("Folkwang Universität der Künste"),
        source=org,
    )

    # Signatur with local variant
    signatur_pred = add_predicate(
        "http://arkumu.org/data/fuk/properties/signatur-beim-einlieferer",
        "Signatur beim Einlieferer",
        "http://arkumu.org/data/properties/signatur-beim-einlieferer",
    )
    Triple.objects.create(
        subject=subject,
        predicate=signatur_pred,
        object=add_literal("FUK-123"),
        source=org,
    )

    # Status using Anzeigestatus alias
    status_pred = add_predicate(
        "http://arkumu.org/data/fuk/properties/anzeigestatus",
        "Anzeigestatus",
        "http://arkumu.org/data/properties/anzeigestatus",
    )
    Triple.objects.create(
        subject=subject,
        predicate=status_pred,
        object=add_literal("Aktiv"),
        source=org,
    )

    # Schlagwort literal for new column
    keyword_pred = add_predicate(
        "http://arkumu.org/data/fuk/properties/schlagwort",
        "Schlagwort",
        ProjectURIs.CATCHPHRASE,
    )
    Triple.objects.create(
        subject=subject,
        predicate=keyword_pred,
        object=add_literal("Theater"),
        source=org,
    )

    # Usage rights literal for dedicated column
    usage_pred = add_predicate(
        "http://arkumu.org/data/fuk/properties/angegebene-nutzungsrechte",
        "Angegebene Nutzungsrechte",
        "http://arkumu.org/data/properties/angegebene-nutzungsrechte",
    )
    Triple.objects.create(
        subject=subject,
        predicate=usage_pred,
        object=add_literal("CC BY 4.0"),
        source=org,
    )

    url = reverse("metadata:tabular_projects")
    response = client.get(f"{url}?embed=1")
    assert response.status_code == 200

    content = response.content.decode("utf-8")
    assert "Projekt Alpha" in content
    assert "Ausstellung" in content
    assert "Kategorie A" in content
    assert "Folkwang Universität der Künste" in content
    assert "FUK-123" in content
    assert "Aktiv" in content
    assert "CC BY 4.0" in content
    # Ensure column headers surface human-friendly labels
    assert "Bevorzugter Titel" in content


@pytest.mark.django_db
def test_tabular_rows_include_audit_timestamps():
    org = Organization.objects.create(name="FUK", code="fuk")
    subject = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/projekt/proj-3",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )

    # Set deterministic timestamps to compare formatted output
    created_at = timezone.now() - timedelta(days=2)
    updated_at = timezone.now() - timedelta(hours=1)
    Resource.objects.filter(id=subject.id).update(
        created_at=created_at,
        updated_at=updated_at,
    )
    subject.refresh_from_db()

    column_specs = _build_column_specs(
        [
            {
                "label": "Dummy",
                "matchers": ["http://arkumu.org/data/fuk/properties/dummy"],
            }
        ]
    )
    column_specs.extend(_build_column_specs(AUDIT_COLUMN_DEFINITIONS))

    rows, columns_meta = _build_rows_for_subjects(
        [subject],
        column_specs,
        entity_type="project",
        org=org,
    )

    expected_created = date_format(timezone.localtime(subject.created_at), "SHORT_DATETIME_FORMAT")
    expected_updated = date_format(timezone.localtime(subject.updated_at), "SHORT_DATETIME_FORMAT")

    row = rows[0]
    assert row["Erstellt am"] == expected_created
    assert row["Aktualisiert am"] == expected_updated

    column_names = [meta["name"] for meta in columns_meta]
    assert "Erstellt am" in column_names
    assert "Aktualisiert am" in column_names


@pytest.mark.django_db
def test_build_rows_uses_label_resolver_for_entity_fk():
    org = Organization.objects.create(name="FUK", code="fuk")

    subject = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/projekt/proj-2",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )

    predicate = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/properties/related-entity",
        resource_type=ResourceType.PROPERTY,
        name="Related Entity",
        organization=org,
    )

    related_entity = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/akteurin/actor-1",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )

    Triple.objects.create(
        subject=subject,
        predicate=predicate,
        object=related_entity,
        source=org,
    )

    desired_columns = [
        {
            "label": "related",
            "matchers": {"http://arkumu.org/data/fuk/properties/related-entity"},
        }
    ]

    class StubResolver:
        def __init__(self):
            self.calls = []

        def label_for_resource(self, resource, display_property_uri=None):
            self.calls.append(resource.uri)
            return "Resolved Label"

    resolver = StubResolver()

    column_specs = _build_column_specs(desired_columns)

    rows, columns_meta = _build_rows_for_subjects(
        [subject],
        column_specs,
        entity_type="project",
        org=org,
        label_resolver=resolver,
    )

    assert rows[0]["related"] == "Resolved Label"
    assert resolver.calls == ["http://arkumu.org/data/fuk/entities/akteurin/actor-1"]
    related_meta = next((meta for meta in columns_meta if meta["name"] == "related"), None)
    assert related_meta is not None
    assert related_meta["is_fk"] is True
