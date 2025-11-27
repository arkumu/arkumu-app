from __future__ import annotations

import types

import pytest

from django.conf import settings

from arkumu.oaipmh import path_mapping
from arkumu.oaipmh.models import OAIDcpPathIndex
from arkumu.oaipmh.services import dcp_index


@pytest.mark.django_db
def test_get_bundle_members_uses_db_index_when_available(settings):
    settings.OAI_EXTERNAL_ROSETTA_ROOTS = {"khm": "/rosetta/khm/sandbox/input/arkumu/daten"}

    OAIDcpPathIndex.objects.create(
        org_code="khm",
        bundle_key="2265_auf_der_strecke_dcp",
        folder_name="2265_auf_der_strecke_dcp",
        relative_file_path="2265_auf_der_strecke_dcp/CPL_abc.xml",
        file_name="CPL_abc.xml",
    )
    OAIDcpPathIndex.objects.create(
        org_code="khm",
        bundle_key="2265_auf_der_strecke_dcp",
        folder_name="2265_auf_der_strecke_dcp",
        relative_file_path="2265_auf_der_strecke_dcp/asset.mxf",
        file_name="asset.mxf",
    )

    result = dcp_index.get_bundle_members("khm", "2265_auf_der_strecke_dcp")

    assert result.org_code == "khm"
    assert result.folder_name == "2265_auf_der_strecke_dcp"
    assert set(result.relative_file_paths) == {
        "2265_auf_der_strecke_dcp/CPL_abc.xml",
        "2265_auf_der_strecke_dcp/asset.mxf",
    }


@pytest.mark.django_db
def test_get_bundle_members_falls_back_to_path_index(settings, monkeypatch):
    root = "/rosetta/khm/sandbox/input/arkumu/daten"
    settings.OAI_EXTERNAL_ROSETTA_ROOTS = {"khm": root}

    # Ensure DB is empty so fallback is exercised
    OAIDcpPathIndex.objects.all().delete()

    class DummyIndex:
        def __init__(self, paths):
            self.full_paths = frozenset(paths)
            self.by_basename = {}

    fake_paths = [
        f"{root}/2265_auf_der_strecke_dcp/CPL_abc.xml",
        f"{root}/2265_auf_der_strecke_dcp/asset.mxf",
        f"{root}/other_folder/ignore.txt",
    ]

    monkeypatch.setattr(path_mapping, "_load_index", lambda org: DummyIndex(fake_paths))

    result = dcp_index.get_bundle_members("khm", "2265_auf_der_strecke_dcp")

    assert set(result.relative_file_paths) == {
        "2265_auf_der_strecke_dcp/CPL_abc.xml",
        "2265_auf_der_strecke_dcp/asset.mxf",
    }

