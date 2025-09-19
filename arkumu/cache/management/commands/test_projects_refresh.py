"""Management command to verify cross-institutional projects cache refresh."""

from django.core.cache import cache
from django.core.management.base import BaseCommand

from arkumu.cache.services.graph_cache_service import GraphCacheService


class Command(BaseCommand):
    help = "Test the cross-institutional projects cache refresh flow"

    def handle(self, *args, **options):
        self.stdout.write("=== Testing Projects Cache Refresh ===")

        graph_cache = GraphCacheService()
        resource_uri = "arkumu:cross_institutional:all_projects"
        params_hash = "cross_institutional_projects_canonical"

        timestamp = graph_cache._get_resource_timestamp(resource_uri)

        def cache_status(traversal_type: str):
            cache_params = {
                "uri": resource_uri,
                "type": traversal_type,
                "params": params_hash,
                "timestamp": timestamp,
            }
            cache_key = graph_cache._get_cache_key("traversal", **cache_params)
            payload = cache.get(cache_key)
            exists = payload is not None
            counts = {}
            if payload:
                result = payload.get("result") or payload
                if isinstance(result, dict):
                    counts = result.get("counts") or {
                        "projects": len(result.get("projects", [])),
                        "subjects": len(result.get("subjects", [])) if result.get("subjects") else 0,
                        "edges": len(result.get("edges", [])) if result.get("edges") else 0,
                    }
            return cache_key, exists, counts

        for traversal_type in ("catalog_search", "catalog_projects"):
            cache_key, exists, counts = cache_status(traversal_type)
            self.stdout.write(
                f"{traversal_type}: {'EXISTS' if exists else 'EMPTY'} -> {cache_key} (counts={counts})"
            )

        self.stdout.write("\nRefreshing cache via GraphCacheService...\n")
        refresh_result = graph_cache.refresh_cross_institutional_projects_cache(force_refresh=True)
        if refresh_result:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Refresh returned {len(refresh_result.get('projects', []))} cards, "
                    f"{refresh_result.get('counts', {}).get('edges')} edges"
                )
            )
        else:
            self.stdout.write(self.style.ERROR("Refresh returned no payload"))

        for traversal_type in ("catalog_search", "catalog_projects"):
            cache_key, exists, counts = cache_status(traversal_type)
            self.stdout.write(
                f"After refresh {traversal_type}: {'EXISTS' if exists else 'EMPTY'} -> {cache_key} (counts={counts})"
            )

        self.stdout.write("=== Test Complete ===")
