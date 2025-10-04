from django.core.cache import cache
from django.test import TestCase
from unittest.mock import patch

from arkumu.cache.services.base_cache_service import BaseCacheService


class BaseCacheServiceTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_project_snapshot_bypasses_memory_guard(self):
        service = BaseCacheService('projects')
        data = {'foo': 'bar'}

        with patch.object(BaseCacheService, '_should_skip_cache', return_value=True):
            service.set_cached('snapshot', data, 'project_snapshot', scope='cross_institutional')

        key = service._get_cache_key('snapshot', scope='cross_institutional')
        self.assertEqual(cache.get(key), data)

    def test_other_cache_respects_memory_guard(self):
        service = BaseCacheService('projects')
        with patch.object(BaseCacheService, '_should_skip_cache', return_value=True):
            service.set_cached('snapshot', {'foo': 'bar'}, 'catalog_search', scope='cross_institutional')

        key = service._get_cache_key('snapshot', scope='cross_institutional')
        self.assertIsNone(cache.get(key))
