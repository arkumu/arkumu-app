"""Quick performance test for tailored OAI batch fetching."""
import os
import sys
import django
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
django.setup()

from arkumu.oaipmh.views.tailored import _tailored_resources_queryset, _tailored_harvestable_page

def main():
    print("Testing tailored OAI harvestable page performance...")

    queryset = _tailored_resources_queryset()
    total = queryset.count()
    print(f"Total tailored resources: {total}")

    if total == 0:
        print("No resources to test")
        return

    # Time the first page fetch
    start = time.time()
    page = _tailored_harvestable_page(
        queryset,
        cursor_position=None,
        page_size=100,
        include_hints=True,
    )
    elapsed = time.time() - start

    print(f"First page fetch took: {elapsed:.2f}s")
    print(f"Resources in page: {len(page.resources)}")
    print(f"Has more: {page.has_more}")

    if page.resources:
        print(f"First resource: {page.resources[0].uri}")

if __name__ == "__main__":
    main()
