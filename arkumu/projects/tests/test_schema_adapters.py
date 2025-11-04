import pytest

from arkumu.projects import schema_adapters
from arkumu.projects.schema_manifest_model_rsh import Akteurin as RshAkteurin, Projekt as RshProjekt
from arkumu.projects.schema_manifest_model_fuk import Akteurin as FukAkteurin


@pytest.mark.parametrize(
    "org_code, dataset_cls, sample_values",
    [
        (
            "rsh",
            RshProjekt,
            {
                "bevorzugter_titel": ["Projekt Titel"],
                "bevorzugter_untertitel": ["Untertitel"],
                "wikidata_id": ["Q123"],
                "schlagwort": ["Schlagwort"],
            },
        ),
        (
            "rsh",
            RshAkteurin,
            {
                "deutscher_name": ["Alice Beispiel"],
                "gnd_nummer": ["1234567"],
                "wikidata_id": ["Q765"],
            },
        ),
        (
            "fuk",
            FukAkteurin,
            {
                "deutscher_name": ["FUK Artist"],
                "wikidata_id": ["Q98765"],
            },
        ),
    ],
)
def test_org_to_canonical_round_trip(org_code, dataset_cls, sample_values):
    dataset_obj = dataset_cls()
    for field_name, value in sample_values.items():
        setattr(dataset_obj, field_name, value)

    canonical_obj = schema_adapters.org_to_canonical(org_code, dataset_obj)

    for field_name, expected in sample_values.items():
        assert getattr(canonical_obj, field_name) == expected

    reconstructed = schema_adapters.canonical_to_org(org_code, canonical_obj)
    assert reconstructed == dataset_obj


def test_canonical_to_org_rejects_unknown_dataset():
    dataset_obj = RshProjekt()
    dataset_obj.bevorzugter_titel = ["Titel"]
    canonical_obj = schema_adapters.org_to_canonical("rsh", dataset_obj)

    with pytest.raises(ValueError):
        schema_adapters.canonical_to_org("rsh", canonical_obj, dataset_name="NonexistentDataset")


def test_org_to_canonical_requires_dataclass():
    with pytest.raises(TypeError):
        schema_adapters.org_to_canonical("rsh", {"bevorzugter_titel": ["Titel"]})
