"""
OAI-PMH Cache Warming Tasks

Huey background tasks for pre-generating and caching OAI-PMH responses
to improve harvesting performance for external services.
"""

import logging
from typing import Dict, Optional, List, Any
from huey.contrib.djhuey import db_task
from django.core.cache import cache
from django.utils import timezone
from .cache_service import OAIPMHCacheService

try:
    from huey.contrib.djhuey import db_periodic_task, crontab
    HUEY_PERIODIC_AVAILABLE = True
except ImportError:
    HUEY_PERIODIC_AVAILABLE = False

logger = logging.getLogger(__name__)


def _get_cache_key(cache_type: str, **kwargs) -> str:
    """Generate consistent cache keys for OAI-PMH responses."""
    if cache_type == "record":
        return f"oai:record:{kwargs['uri']}:{kwargs['metadata_prefix']}:{kwargs['timestamp']}"
    elif cache_type == "graph":
        return f"oai:graph:{kwargs['uri']}:{kwargs['timestamp']}"
    elif cache_type == "page":
        return f"oai:page:{kwargs['verb']}:{kwargs['metadata_prefix']}:{kwargs.get('set_spec', '')}:{kwargs.get('from_date', '')}:{kwargs.get('until_date', '')}:{kwargs['offset']}"
    elif cache_type == "list":
        return f"oai:list:{kwargs['verb']}:{kwargs['metadata_prefix']}:{kwargs.get('set_spec', '')}:{kwargs.get('from_date', '')}:{kwargs.get('until_date', '')}:{kwargs['offset']}"
    return f"oai:{cache_type}:{':'.join(str(v) for v in kwargs.values())}"


@db_task(retries=2, retry_delay=60)
def warm_resource_cache(resource_uri: str, organization_code: str):
    """
    Pre-generate and cache OAI-PMH metadata for a single resource.
    This warms both the graph data and formatted metadata.
    """
    try:
        from arkumu.metadata.models.resource import Resource

        logger.info(f"🔥 CACHE WARM: Starting for resource {resource_uri}")

        # Get the resource
        resource = Resource.objects.filter(
            uri=resource_uri,
            organization__code=organization_code,
            uri__regex=r'/entities/projekt/[0-9]+$'
        ).select_related('organization').first()

        if not resource:
            logger.warning(f"⚠️ CACHE WARM: Resource not found: {resource_uri}")
            return

        timestamp = int(resource.updated_at.timestamp())

        # Warm cache for both metadata formats using centralized service
        for metadata_prefix in ['oai_dc', 'mets']:
            OAIPMHCacheService.warm_record(resource, metadata_prefix)

        logger.info(f"✅ CACHE WARM: Completed for resource {resource_uri}")

    except Exception as e:
        logger.error(f"❌ CACHE WARM: Error warming cache for {resource_uri}: {str(e)}")
        raise


@db_task(retries=2, retry_delay=30)
def warm_page_cache(metadata_prefix: str = 'oai_dc', set_spec: str = '',
                   from_date: str = '', until_date: str = '', offset: int = 0):
    """
    Pre-generate and cache a complete OAI-PMH page response.
    This caches the entire XML response for immediate serving.
    """
    try:
        from arkumu.metadata.models.resource import Resource
        from arkumu.oaipmh.views import _get_resources_queryset
        from arkumu.oaipmh.resumption import ResumptionTokenService

        logger.info(f"🔥 PAGE CACHE: Warming page {offset//100 + 1} for {metadata_prefix}")

        # Build cache key
        page_cache_key = _get_cache_key(
            "page",
            verb="ListRecords",
            metadata_prefix=metadata_prefix,
            set_spec=set_spec,
            from_date=from_date,
            until_date=until_date,
            offset=offset
        )

        if cache.get(page_cache_key):
            logger.debug(f"⚡ Page cache already exists for offset {offset}")
            return

        # Get resources for this page
        queryset = _get_resources_queryset(set_spec, from_date, until_date, metadata_prefix)
        page_size = 100
        resources = list(queryset[offset:offset + page_size + 1])

        has_more = len(resources) > page_size
        if has_more:
            resources = resources[:-1]

        if not resources:
            logger.debug(f"⚠️ No resources found for page at offset {offset}")
            return

        # Build page response
        records_data = []
        for resource in resources:
            # Use centralized cache service to get/warm record
            cached_record = OAIPMHCacheService.get_cached_record(resource, metadata_prefix)
            if cached_record:
                records_data.append(cached_record)
            else:
                # Warm cache using centralized service and get result
                OAIPMHCacheService.warm_record(resource, metadata_prefix)
                cached_record = OAIPMHCacheService.get_cached_record(resource, metadata_prefix)
                if cached_record:
                    records_data.append(cached_record)

        # Build resumption token if needed
        resumption_token = None
        if has_more:
            resumption_service = ResumptionTokenService(page_size=100)
            next_offset = offset + page_size
            resumption_token = resumption_service.create_token(
                offset=next_offset,
                verb="ListRecords",
                metadata_prefix=metadata_prefix,
                set_spec=set_spec,
                from_date=from_date,
                until_date=until_date
            )

        # Cache the complete page
        page_data = {
            'records': records_data,
            'resumption_token': resumption_token,
            'count': len(records_data),
            'cached_at': timezone.now().isoformat()
        }

        # Cache for 2 hours (shorter than individual records)
        cache.set(page_cache_key, page_data, 2 * 3600)

        logger.info(f"✅ PAGE CACHE: Cached page with {len(records_data)} records at offset {offset}")

    except Exception as e:
        logger.error(f"❌ PAGE CACHE: Error warming page cache at offset {offset}: {str(e)}")
        raise


@db_task(retries=1, retry_delay=120)
def warm_popular_records():
    """
    Warm cache for the most frequently accessed records.
    Prioritizes recent updates and active organizations.
    """
    try:
        from arkumu.metadata.models.resource import Resource
        from arkumu.users.models import Organization

        logger.info("🔥 POPULAR RECORDS: Starting cache warming for popular records")

        # Get active organizations
        active_orgs = Organization.objects.filter(is_active=True)

        for org in active_orgs:
            # Get 20 most recently updated project resources per org
            recent_resources = (
                Resource.objects
                .filter(
                    organization=org,
                    uri__regex=r'/entities/projekt/[0-9]+$'
                )
                .order_by('-updated_at')[:20]
            )

            for resource in recent_resources:
                # Schedule individual resource cache warming
                warm_resource_cache.schedule(
                    args=(resource.uri, org.code),
                    delay=5  # Small delay between resources
                )

        logger.info("✅ POPULAR RECORDS: Scheduled cache warming for popular records")

    except Exception as e:
        logger.error(f"❌ POPULAR RECORDS: Error warming popular records cache: {str(e)}")


# Periodic cache warming tasks (only if periodic tasks are available)
if HUEY_PERIODIC_AVAILABLE:

    @db_periodic_task(crontab(minute=0, hour=2))  # 2 AM daily
    def refresh_oai_cache():
        """
        Daily cache refresh during low-traffic hours.
        Warms the first 10 pages (1000 most recent records).
        """
        try:
            logger.info("🕐 PERIODIC: Starting daily OAI-PMH cache refresh")

            # Warm popular individual records first
            warm_popular_records.schedule(delay=5)

            # Warm first 10 pages for both formats
            for metadata_prefix in ['oai_dc', 'mets']:
                for page_num in range(10):  # First 10 pages = 1000 records
                    offset = page_num * 100
                    warm_page_cache.schedule(
                        args=(metadata_prefix, '', '', '', offset),
                        delay=page_num * 10  # Stagger page warming
                    )

            logger.info("✅ PERIODIC: Scheduled daily OAI-PMH cache refresh")

        except Exception as e:
            logger.error(f"❌ PERIODIC: Error scheduling cache refresh: {str(e)}")

    @db_periodic_task(crontab(minute=30, hour='*/6'))  # Every 6 hours at :30
    def refresh_recent_records():
        """
        Refresh cache for recently updated records every 6 hours.
        """
        try:
            logger.info("🕕 PERIODIC: Refreshing recent records cache")

            from arkumu.metadata.models.resource import Resource
            from django.utils import timezone

            # Get records updated in the last 6 hours
            six_hours_ago = timezone.now() - timezone.timedelta(hours=6)
            recent_resources = (
                Resource.objects
                .filter(
                    uri__regex=r'/entities/projekt/[0-9]+$',
                    updated_at__gte=six_hours_ago
                )
                .select_related('organization')
                .order_by('-updated_at')[:50]  # Limit to 50 most recent
            )

            for i, resource in enumerate(recent_resources):
                warm_resource_cache.schedule(
                    args=(resource.uri, resource.organization.code),
                    delay=i * 2  # 2 second delay between resources
                )

            logger.info(f"✅ PERIODIC: Scheduled cache refresh for {len(recent_resources)} recent records")

        except Exception as e:
            logger.error(f"❌ PERIODIC: Error refreshing recent records: {str(e)}")

else:
    # Manual triggers for installations without periodic task support
    @db_task()
    def manual_refresh_oai_cache():
        """Manual trigger for OAI-PMH cache refresh"""
        refresh_oai_cache()

    @db_task()
    def manual_refresh_recent_records():
        """Manual trigger for recent records refresh"""
        refresh_recent_records()


@db_task(retries=1, retry_delay=60)
def clear_expired_cache():
    """
    Clear expired OAI-PMH cache entries.
    This is a fallback cleanup task.
    """
    try:
        logger.info("🧹 CLEANUP: Starting OAI-PMH cache cleanup")

        # Django's cache framework handles TTL automatically,
        # but we can add custom cleanup logic here if needed

        # For now, just log that cleanup was triggered
        logger.info("✅ CLEANUP: OAI-PMH cache cleanup completed")

    except Exception as e:
        logger.error(f"❌ CLEANUP: Error during cache cleanup: {str(e)}")


@db_task(retries=2, retry_delay=30)
def batch_link_files_task(file_ids, organization_code, user_id):
    """
    Background task for batch linking files to resources.
    """
    try:
        from arkumu.storage.models import S3FileObject
        from arkumu.metadata.models.resource import Resource
        from arkumu.metadata.services.resource_traversal_service import ResourceTraversalService
        from django.db.models import Q

        logger.info(f"🔗 BATCH LINK TASK: Starting for {len(file_ids)} files (org: {organization_code})")

        # Get the files
        selected_files = S3FileObject.objects.filter(id__in=file_ids)

        processed = 0
        linked = 0
        ambiguous = 0
        errors = 0
        affected_resources = set()

        for s3_file in selected_files:
            processed += 1
            try:
                query = s3_file.file_name
                logger.debug(f"🔗 Processing file {s3_file.file_name}")

                # Use precise endswith matching
                matching_resources = Resource.objects.filter(
                    Q(value__iendswith=query) | Q(uri__iendswith=query)
                ).distinct()

                if matching_resources.count() == 1:
                    # Single match - find project entity
                    resource = matching_resources.first()
                    traversal_service = ResourceTraversalService()
                    project_entity = traversal_service.get_project_entity_for_resource(resource)

                    if project_entity:
                        s3_file.related_resource = project_entity
                        s3_file.save()
                        linked += 1
                        affected_resources.add((project_entity.uri, project_entity.organization.code))
                        logger.info(f"Linked {s3_file.file_name} to {project_entity.uri}")

                elif matching_resources.count() > 1:
                    # Multiple matches - try deduplication
                    traversal_service = ResourceTraversalService()
                    project_entities = []
                    for matched_resource in matching_resources:
                        project_entity = traversal_service.get_project_entity_for_resource(matched_resource)
                        if project_entity:
                            project_entities.append(project_entity)

                    # Deduplicate project entities
                    unique_projects = list({p.id: p for p in project_entities}.values())

                    if len(unique_projects) == 1:
                        project_entity = unique_projects[0]
                        s3_file.related_resource = project_entity
                        s3_file.save()
                        linked += 1
                        affected_resources.add((project_entity.uri, project_entity.organization.code))
                        logger.info(f"Resolved {s3_file.file_name} to {project_entity.uri}")
                    else:
                        ambiguous += 1
                        logger.info(f"Ambiguous match for {s3_file.file_name}: {len(unique_projects)} projects")

            except Exception as e:
                errors += 1
                logger.error(f"Error processing {s3_file.file_name}: {str(e)}")

        # Warm cache for affected resources
        if linked > 0:
            logger.info(f"🔥 Warming cache for {len(affected_resources)} resources")
            for uri, org_code in affected_resources:
                try:
                    resource = Resource.objects.get(uri=uri, organization__code=org_code)
                    for metadata_prefix in ['oai_dc', 'mets']:
                        OAIPMHCacheService.warm_record(resource, metadata_prefix)
                except Exception as e:
                    logger.error(f"Cache warming error for {uri}: {str(e)}")

        logger.info(f"✅ BATCH LINK TASK: Complete. Processed: {processed}, Linked: {linked}, Ambiguous: {ambiguous}, Errors: {errors}")

        return {
            'processed': processed,
            'linked': linked,
            'ambiguous': ambiguous,
            'errors': errors,
            'resources_warmed': len(affected_resources)
        }

    except Exception as e:
        logger.error(f"❌ BATCH LINK TASK: Failed - {str(e)}")
        raise