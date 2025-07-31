"""
Service for bulk mapping organizations to the Arkumu model.

This service automatically creates mappings from organization-specific IRIs
to the generic Arkumu model by removing the organization prefix from URLs.
"""

import logging
import re

from django.contrib.auth import get_user_model
from django.db import models
from django.db import transaction

from arkumu.metadata.models.harmonization import HarmonizationExecution
from arkumu.metadata.models.harmonization import HarmonizationRule
from arkumu.users.models import Organization

logger = logging.getLogger(__name__)
User = get_user_model()


class BulkArkumuMappingService:
    """Service for creating bulk mappings from organizations to Arkumu model."""

    def __init__(self):
        self.base_arkumu_url = "http://arkumu.org"
        self.org_pattern = re.compile(r"/data/([^/]+)/(types|properties)/")

    def transform_organization_iri_to_arkumu(self, org_iri: str) -> str | None:
        """
        Transform organization-specific IRI to Arkumu model IRI.

        Examples:
        - http://arkumu.org/data/det/types/organisationseinheit -> http://arkumu.org/types/organisationseinheit
        - http://arkumu.org/data/det/properties/property-cardinality -> http://arkumu.org/properties/property-cardinality
        """
        if not org_iri or not org_iri.startswith(self.base_arkumu_url):
            return None

        match = self.org_pattern.search(org_iri)
        if not match:
            return None

        org_code, resource_type = match.groups()

        # Replace /data/{org_code}/ with /
        arkumu_iri = self.org_pattern.sub(f"/{resource_type}/", org_iri)

        return self.org_pattern.sub(f"/{resource_type}/", org_iri)

    def extract_organization_code_from_iri(self, org_iri: str) -> str | None:
        """Extract organization code from IRI."""
        match = self.org_pattern.search(org_iri)
        return match.group(1) if match else None

    def get_organization_iris_from_resources(
        self, organization_codes: list[str]
    ) -> dict[str, set[str]]:
        """
        Get all organization-specific IRIs from the resources database.
        Look for resources that could be mapped to Arkumu model.

        Returns:
            Dict mapping org_code to set of IRIs
        """
        from arkumu.metadata.models.resource import Resource, ResourceType
        from arkumu.users.models import Organization

        org_iris = {}

        for org_code in organization_codes:
            try:
                organization = Organization.objects.get(code=org_code)

                # Get all Class and Property resources for this organization
                # These are the types that should be mapped to Arkumu model
                resources = Resource.objects.filter(
                    organization=organization,
                    resource_type__in=[ResourceType.CLASS, ResourceType.PROPERTY],
                    uri__isnull=False  # Must have a URI to map
                ).exclude(
                    uri=""  # Exclude empty URIs
                ).values_list("uri", flat=True)

                org_iris[org_code] = set(resources)
                logger.info(
                    "Found %d mappable resources (classes/properties) for organization %s",
                    len(org_iris[org_code]),
                    org_code,
                )

            except Organization.DoesNotExist:
                logger.warning("Organization with code %s not found", org_code)
                org_iris[org_code] = set()

        return org_iris

    def create_harmonization_rules(
        self,
        organization_codes: list[str],
        created_by: User,
        mapping_type: str = "exact",
        priority: int = 0,
    ) -> HarmonizationExecution:
        """
        Create harmonization rules for bulk mapping organizations to Arkumu model.

        Args:
            organization_codes: List of organization codes to process
            created_by: User creating the mappings
            mapping_type: Type of semantic mapping ('exact', 'close', 'broad', 'narrow')
            priority: Priority for conflict resolution

        Returns:
            HarmonizationExecution instance tracking this bulk operation
        """

        # Create execution record
        execution = HarmonizationExecution.objects.create(
            created_by=created_by,
            status="running",
            execution_mode="manual",
        )

        try:
            with transaction.atomic():
                # Get organizations
                organizations = Organization.objects.filter(
                    code__in=organization_codes,
                )
                execution.organizations.set(organizations)

                # Get all IRIs for these organizations
                org_iris = self.get_organization_iris_from_resources(organization_codes)

                rules_created = 0
                rules_skipped = 0

                for org_code, iris in org_iris.items():
                    try:
                        organization = Organization.objects.get(code=org_code)
                    except Organization.DoesNotExist:
                        logger.warning(
                            "Organization with code %s not found", org_code
                        )
                        continue

                    for org_iri in iris:
                        arkumu_iri = self.transform_organization_iri_to_arkumu(org_iri)

                        if not arkumu_iri:
                            continue

                        # Extract label from IRI (last part after /)
                        label = (
                            org_iri.split("/")[-1]
                            .replace("-", " ")
                            .replace("_", " ")
                            .title()
                        )

                        # Create harmonization rule (or skip if it already exists)
                        rule, created = HarmonizationRule.objects.get_or_create(
                            source_organization=organization,
                            source_property_pattern=org_iri,  # Use exact IRI as pattern
                            catalog_property_uri=arkumu_iri,
                            defaults={
                                "catalog_property_label": label,
                                "mapping_type": mapping_type,
                                "priority": priority,
                                "is_active": True,
                                "created_by": created_by,
                                "notes": (
                                    f"Auto-generated bulk mapping from {org_code} "
                                    "to Arkumu model"
                                ),
                            },
                        )

                        if created:
                            rules_created += 1
                            execution.rules_applied.add(rule)
                        else:
                            rules_skipped += 1

                # Update execution status
                execution.status = "completed"
                execution.resources_processed = sum(
                    len(iris) for iris in org_iris.values()
                )
                execution.triples_created = rules_created
                execution.save()

                logger.info(
                    "Bulk mapping completed: %d rules created, %d rules skipped",
                    rules_created,
                    rules_skipped,
                )

        except Exception as e:
            execution.status = "failed"
            execution.errors = [{"error": str(e), "type": "bulk_mapping_error"}]
            execution.save()
            logger.exception("Bulk mapping failed")
            raise

        return execution

    def preview_bulk_mapping(
        self, organization_codes: list[str]
    ) -> dict[str, list[dict[str, str]]]:
        """
        Preview what mappings would be created without actually creating them.

        Returns:
            Dict mapping org_code to list of mapping previews
        """
        org_iris = self.get_organization_iris_from_resources(organization_codes)

        preview = {}

        for org_code, iris in org_iris.items():
            mappings = []

            for org_iri in iris:
                arkumu_iri = self.transform_organization_iri_to_arkumu(org_iri)

                if arkumu_iri:
                    label = (
                        org_iri.split("/")[-1]
                        .replace("-", " ")
                        .replace("_", " ")
                        .title()
                    )
                    resource_type = "Class" if "/types/" in org_iri else "Property"

                    mappings.append({
                        "source_iri": org_iri,
                        "target_iri": arkumu_iri,
                        "label": label,
                        "resource_type": resource_type,
                    })

            preview[org_code] = mappings

        return preview

    def get_existing_mappings_count(
        self, organization_codes: list[str]
    ) -> dict[str, int]:
        """Get count of existing harmonization rules for each organization."""
        counts = {}

        for org_code in organization_codes:
            try:
                organization = Organization.objects.get(code=org_code)
                count = HarmonizationRule.objects.filter(
                    source_organization=organization,
                    is_active=True,
                ).count()
                counts[org_code] = count
            except Organization.DoesNotExist:
                counts[org_code] = 0

        return counts

    def validate_organization_codes(
        self, organization_codes: list[str]
    ) -> tuple[list[str], list[str]]:
        """
        Validate organization codes and return valid/invalid lists.

        Returns:
            Tuple of (valid_codes, invalid_codes)
        """
        existing_codes = set(
            Organization.objects.filter(
                code__in=organization_codes,
            ).values_list("code", flat=True),
        )

        valid_codes = [
            code for code in organization_codes if code in existing_codes
        ]
        invalid_codes = [
            code for code in organization_codes if code not in existing_codes
        ]

        return valid_codes, invalid_codes
