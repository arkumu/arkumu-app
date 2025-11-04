import pytest
from django.urls import reverse

from arkumu.metadata.controlled_vocabularies.registry import (
    column_to_field_name,
)
from arkumu.metadata.controlled_vocabularies.service import ControlledVocabularyService
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple


def create_staff_user(django_user_model):
    return django_user_model.objects.create_user(
        username="staff",
        email="staff@example.com",
        password="test1234",
        is_staff=True,
    )


@pytest.mark.django_db
def test_overview_requires_login(client, django_user_model):
    user = create_staff_user(django_user_model)
    client.force_login(user)

    response = client.get(reverse("metadata:controlled_vocab_overview"))
    assert response.status_code == 200
    assert b"Controlled Vocabularies" in response.content


@pytest.mark.django_db
def test_create_role_entry(client, django_user_model):
    user = create_staff_user(django_user_model)
    client.force_login(user)

    vocab_key = "roles"
    config = ControlledVocabularyService(vocab_key).config

    form_data = {
        "slug": "role-test",
        column_to_field_name("German Name"): "Testrolle",
        column_to_field_name("English Name"): "Test Role",
        column_to_field_name('Pre-selects "ist Urheber:in" automatically'): "on",
    }

    response = client.post(
        reverse("metadata:controlled_vocab_create", args=[vocab_key]),
        data=form_data,
    )

    assert response.status_code == 302
    resource = Resource.objects.get(uri=config.class_uri.rstrip("/") + "/role-test")
    assert resource.resource_type == ResourceType.ENTITY
    assert resource.name == "Testrolle"

    rdf_type_exists = Triple.objects.filter(
        subject=resource,
        predicate__uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        object__uri=config.class_uri,
    ).exists()
    assert rdf_type_exists

    boolean_triple = Triple.objects.get(
        subject=resource,
        predicate__uri="http://arkumu.org/data/properties/waehlt-ist-urheber-in-automatisch-aus",
    )
    assert boolean_triple.object.value == "true"


@pytest.mark.django_db
def test_edit_project_category_updates_filmportal(client, django_user_model):
    user = create_staff_user(django_user_model)
    client.force_login(user)

    service = ControlledVocabularyService("project_categories")

    # Create parent category
    parent_resource = service.save(
        {
            "slug": "project-category-parent",
            column_to_field_name("German Name"): "Überkategorie",
            column_to_field_name("English Name"): "Parent Category",
            column_to_field_name("filmportal.de Category ID"): "fp-parent",
        }
    )

    # Create child category
    child_resource = service.save(
        {
            "slug": "project-category-child",
            column_to_field_name("German Name"): "Kindkategorie",
            column_to_field_name("English Name"): "Child Category",
            column_to_field_name("filmportal.de Category ID"): "fp-old",
            column_to_field_name("Parent Project Category"): str(parent_resource.id),
        }
    )

    form_data = {
        "slug": "project-category-child",
        column_to_field_name("German Name"): "Kindkategorie",
        column_to_field_name("English Name"): "Child Category",
        column_to_field_name("filmportal.de Category ID"): "fp-updated",
        column_to_field_name("Parent Project Category"): str(parent_resource.id),
    }

    response = client.post(
        reverse("metadata:controlled_vocab_edit", args=["project_categories", child_resource.id]),
        data=form_data,
    )

    assert response.status_code == 302

    triple = Triple.objects.get(
        subject=child_resource,
        predicate__uri="http://arkumu.org/data/properties/filmportal-kategorie-id",
    )
    assert triple.object.value == "fp-updated"

