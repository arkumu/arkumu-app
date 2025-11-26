from __future__ import annotations

import pytest

from arkumu.metadata.canonical import canonical_uri
from arkumu.metadata.services.junction_pattern_service import JunctionPatternService


PROJECT = canonical_uri("project")
EVENT = canonical_uri("event")


def make_config(patterns):
    return {"junction_patterns": patterns}


@pytest.mark.parametrize("dataset_key", ["01_kreuz", "01_Kreuz.csv", "01_KREUZ"])
def test_manifest_patterns_match_dataset(dataset_key):
    config = make_config(
        {
            dataset_key: [
                {
                    "name": "custom_project_event",
                    "required_properties": [PROJECT, EVENT],
                    "recipes": [
                        {
                            "subject_property": PROJECT,
                            "object_property": EVENT,
                            "predicate_uri": EVENT,
                        }
                    ],
                }
            ]
        }
    )

    service = JunctionPatternService(mapping_config=config, organization_code="khm", include_static_patterns=False)
    patterns = service.iter_patterns(dataset_name="01_Kreuz", canonical_predicates=[PROJECT, EVENT])

    assert len(patterns) == 1
    assert patterns[0].name == "custom_project_event"
    assert patterns[0].recipes[0].predicate_uri == EVENT


def test_manifest_patterns_override_static():
    config = make_config(
        {
            "dataset": [
                {
                    "name": "custom_override",
                    "required_properties": [PROJECT, EVENT],
                    "recipes": [
                        {
                            "subject_property": PROJECT,
                            "object_property": EVENT,
                            "predicate_uri": PROJECT,
                        }
                    ],
                }
            ]
        }
    )

    service = JunctionPatternService(mapping_config=config, organization_code="khm", include_static_patterns=True)
    patterns = service.iter_patterns(dataset_name="dataset", canonical_predicates=[PROJECT, EVENT])

    assert patterns[0].name == "custom_override"
    # ensure fallback pattern still included after custom one
    assert any(pattern.name == "project_event" for pattern in patterns[1:])


def test_describe_patterns_returns_sources():
    config = make_config(
        {
            "dataset": [
                {
                    "name": "pattern_a",
                    "required_properties": [PROJECT],
                    "recipes": [
                        {
                            "subject_property": PROJECT,
                            "object_property": PROJECT,
                            "predicate_uri": PROJECT,
                        }
                    ],
                }
            ]
        }
    )

    service = JunctionPatternService(mapping_config=config)
    descriptions = service.describe_patterns()

    assert len(descriptions) == 1
    assert descriptions[0].name == "pattern_a"
    assert descriptions[0].origin == "manifest"
