from unittest.mock import Mock

import arkumu.catalog

from arkumu.catalog.apps import CatalogConfig


def test_catalog_ready_skips_warmup_for_compilemessages(monkeypatch):
    monkeypatch.setattr("arkumu.catalog.apps.sys.argv", ["manage.py", "compilemessages"])

    thread_mock = Mock()
    monkeypatch.setattr("arkumu.catalog.apps.threading.Thread", thread_mock)

    CatalogConfig("arkumu.catalog", arkumu.catalog).ready()

    thread_mock.assert_not_called()
