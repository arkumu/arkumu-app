from unittest.mock import Mock

import arkumu.oaipmh

from arkumu.oaipmh.apps import OaipmhConfig


def test_oaipmh_ready_skips_cache_preload_for_compilemessages(monkeypatch):
    monkeypatch.setattr("arkumu.oaipmh.apps.sys.argv", ["manage.py", "compilemessages"])

    thread_mock = Mock()
    monkeypatch.setattr("arkumu.oaipmh.apps.threading.Thread", thread_mock)

    OaipmhConfig("arkumu.oaipmh", arkumu.oaipmh).ready()

    thread_mock.assert_not_called()
