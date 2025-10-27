from arkumu.projects.services.schema_manifest_dataclass_generator import (
    ManifestClass,
    ManifestField,
    SchemaManifestDataclassGenerator,
)


def test_build_module_from_manifest_dict(monkeypatch):
    generator = SchemaManifestDataclassGenerator()

    manifest = {
        'Project': ManifestClass(
            class_name='Project',
            dataset_key='00_hfm_Projekte',
            canonical_uri='http://arkumu.org/data/hmt/types/00-hfm-projekte',
            fields=[
                ManifestField(
                    name='uuid',
                    canonical_uri='http://arkumu.org/data/hmt/properties/uuid',
                    dataset_property='UUID',
                    metadata={'vocabulary': 'example'},
                ),
                ManifestField(
                    name='title',
                    canonical_uri='http://arkumu.org/data/hmt/properties/bevorzugter-titel',
                    dataset_property='Bevorzugter Titel',
                    metadata={},
                ),
            ],
        )
    }

    module = generator.build_module(manifest)

    assert 'class Project' in module
    assert "uuid: list[str]" in module
    assert "'dataset_property': 'Bevorzugter Titel'" in module
