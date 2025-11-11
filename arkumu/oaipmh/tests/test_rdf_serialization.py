from __future__ import annotations

import textwrap

import pytest
from lxml import etree as ET

from arkumu.metadata.models.resource import Resource, PublicAccessLevel, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization
from arkumu.oaipmh.formats.mets_source_metadata import build_rdf_graph, RDF_NS
from arkumu.oaipmh.views import _build_institutional_rdf_element


def _normalize(xml: str) -> str:
    element = ET.fromstring(xml.encode("utf-8"))
    return ET.tostring(element, encoding="unicode", pretty_print=True).strip()


@pytest.mark.django_db
def test_serializes_canonical_and_institutional_rdf_for_khm_and_hmt():
    canonical_predicate, _ = Resource.objects.get_or_create(
        uri="http://arkumu.org/data/properties/bevorzugter-titel",
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "canonical_uri": "http://arkumu.org/data/properties/bevorzugter-titel",
            "name": "Preferred Title",
        },
    )

    results = {}
    for org_code in ("khm", "hmt"):
        org = Organization.objects.create(
            name=f"{org_code.upper()} Test Org",
            code=org_code,
            domain=f"{org_code}.arkumu.test",
            is_active=True,
        )
        project = Resource.objects.create(
            uri=f"http://arkumu.org/data/{org_code}/entities/projekt/test-1",
            organization=org,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True,
        )

        canonical_literal = Resource.objects.create(
            resource_type=ResourceType.LITERAL,
            value=f"{org_code.upper()} Canonical Title",
        )
        Triple.objects.create(
            subject=project,
            predicate=canonical_predicate,
            object=canonical_literal,
            source=org,
        )

        local_predicate = Resource.objects.create(
            uri=f"http://arkumu.org/data/{org_code}/properties/projekttitel",
            resource_type=ResourceType.PROPERTY,
            name=f"{org_code.upper()} Local Title",
        )
        local_literal = Resource.objects.create(
            resource_type=ResourceType.LITERAL,
            value=f"{org_code.upper()} Institutional Title",
        )
        Triple.objects.create(
            subject=project,
            predicate=local_predicate,
            object=local_literal,
            source=org,
        )
        event = Resource.objects.create(
            uri=f"http://arkumu.org/data/{org_code}/entities/ereignis/test-event",
            organization=org,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True,
        )
        event_link_pred = Resource.objects.create(
            uri=f"http://arkumu.org/data/{org_code}/properties/ereignis",
            resource_type=ResourceType.PROPERTY,
            name=f"{org_code.upper()} Event Link",
        )
        Triple.objects.create(
            subject=project,
            predicate=event_link_pred,
            object=event,
            source=org,
        )
        event_title_pred = Resource.objects.create(
            uri=f"http://arkumu.org/data/{org_code}/properties/ereignistitel",
            resource_type=ResourceType.PROPERTY,
            name=f"{org_code.upper()} Event Title",
        )
        event_title_literal = Resource.objects.create(
            resource_type=ResourceType.LITERAL,
            value=f"{org_code.upper()} Event Title",
        )
        Triple.objects.create(
            subject=event,
            predicate=event_title_pred,
            object=event_title_literal,
            source=org,
        )

        graph_data = {
            "root_id": str(project.id),
            "nodes": {
                str(project.id): {
                    "id": str(project.id),
                    "uri": project.uri,
                    "resource_type": ResourceType.ENTITY.value,
                },
                str(canonical_literal.id): {
                    "id": str(canonical_literal.id),
                    "uri": None,
                    "value": canonical_literal.value,
                    "resource_type": ResourceType.LITERAL.value,
                },
            },
            "edges": [
                {
                    "subject_id": str(project.id),
                    "object_id": str(canonical_literal.id),
                    "predicate_uri": canonical_predicate.uri,
                    "predicate_canonical": canonical_predicate.canonical_uri,
                }
            ],
        }

        class _StubGraph:
            def __init__(self, payload):
                self.payload = payload

            def get_entity_graph(self, **_):
                return self.payload

        canonical_xml = ET.tostring(
            build_rdf_graph(project, graph_service=_StubGraph(graph_data)),
            encoding="unicode",
        ).strip()

        institutional_element = _build_institutional_rdf_element(project)
        institutional_xml = ET.tostring(institutional_element, encoding="unicode").strip()
        results[org_code] = (project.uri, canonical_xml, institutional_xml)

    khm_uri, khm_canonical, khm_institutional = results["khm"]
    hmt_uri, hmt_canonical, hmt_institutional = results["hmt"]

    assert f'rdf:about="{khm_uri}"' in khm_canonical
    assert "<arkumu:bevorzugter-titel>KHM Canonical Title</arkumu:bevorzugter-titel>" in khm_canonical
    assert f'rdf:about="{khm_uri}"' in khm_institutional
    assert "<khm:projekttitel>KHM Institutional Title</khm:projekttitel>" in khm_institutional
    assert '<khm:ereignis rdf:resource="http://arkumu.org/data/khm/entities/ereignis/test-event"/>' in khm_institutional
    assert "<khm:ereignistitel>KHM Event Title</khm:ereignistitel>" in khm_institutional

    assert f'rdf:about="{hmt_uri}"' in hmt_canonical
    assert "<arkumu:bevorzugter-titel>HMT Canonical Title</arkumu:bevorzugter-titel>" in hmt_canonical
    assert f'rdf:about="{hmt_uri}"' in hmt_institutional
    assert "<hmt:projekttitel>HMT Institutional Title</hmt:projekttitel>" in hmt_institutional
    assert '<hmt:ereignis rdf:resource="http://arkumu.org/data/hmt/entities/ereignis/test-event"/>' in hmt_institutional
    assert "<hmt:ereignistitel>HMT Event Title</hmt:ereignistitel>" in hmt_institutional
