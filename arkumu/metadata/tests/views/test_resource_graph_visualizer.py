import graphviz
import pytest
from django.urls import reverse

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.views.resource_graph_visualizer import ResourceGraphService


@pytest.mark.django_db
def test_resource_graph_nodes_link_to_graph_view():
    resource = Resource.objects.create(
        uri="http://arkumu.org/data/resources/test",
        resource_type=ResourceType.IRI,
        name="Test Resource",
    )

    graph_service = ResourceGraphService()
    dot = graphviz.Digraph(format="svg")
    graph_data = {
        "nodes": {
            resource.id: {
                "resource": resource,
                "depth": 0,
                "is_central": True,
            }
        },
        "edges": [],
    }

    graph_service._add_nodes_to_graph(dot, graph_data, resource)

    expected_url = reverse("metadata:resource_graph", args=[resource.id])
    assert f'URL="{expected_url}"' in dot.source
    assert "target=_top" in dot.source
