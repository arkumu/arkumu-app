from unittest.mock import Mock

import arkumu.cache

from arkumu.cache.apps import CacheConfig


def test_cache_ready_skips_warmup_for_compilemessages(monkeypatch):
    monkeypatch.setattr("arkumu.cache.apps.sys.argv", ["manage.py", "compilemessages"])

    thread_mock = Mock()
    monkeypatch.setattr("arkumu.cache.apps.threading.Thread", thread_mock)

    CacheConfig("arkumu.cache", arkumu.cache).ready()

    thread_mock.assert_not_called()
