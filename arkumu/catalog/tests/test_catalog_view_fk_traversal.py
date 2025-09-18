"""Tests for card extraction using triple relationships."""

import pytest

from arkumu.catalog.tests.sample_card_data import create_sample_catalog_triples
from arkumu.catalog.views.catalog_view import CatalogView


@pytest.mark.django_db
def test_catalog_view_triple_relationships_builds_complete_card():
    data = create_sample_catalog_triples()
    project_id = data['project_id']
    edges_by_subject = data['edges_by_subject']

    view = CatalogView()
    card = view._extract_card_from_graph(
        subject_id=project_id,
        subject_edges=edges_by_subject[project_id],
        all_edges=data['edges'],
        card_schema=data['schema'],
        edges_by_subject=edges_by_subject,
    )

    assert card is not None
    assert card['title'] == 'Project Title'
    assert card['institution'] == 'Test Institution'
    assert card['categories'] == ['Category']
    assert card['year_range'] == '2020 bis 2021'
    assert card['contributor1_name'] == 'Alice Example'
    assert card['contributor1_role'] == 'Designer'
    assert card['digital_objects'] == ['path/to/file.jpg']
    assert card['image'] == 'path/to/file.jpg'
