import logging
import threading

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class OaipmhConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'arkumu.oaipmh'

    def ready(self):
        # Import signals for security audit logging
        from . import signals  # noqa: F401

        # Preload caches in a thread to work around ASGI async context restriction
        # Use a blocking join to ensure cache is ready before first request
        thread = threading.Thread(target=self._warm_caches, daemon=True)
        thread.start()
        thread.join(timeout=30)  # Wait up to 30s for warmup

    def _warm_caches(self):
        """Preload KHM DCP caches, modules, and warm lxml at startup."""
        try:
            from arkumu.oaipmh.oai_project import _load_dcp_folder_cache
            from arkumu.oaipmh.services.dcp_index import _load_dcp_files_cache

            # Import modules that have lazy imports to avoid first-request latency
            from arkumu.oaipmh.services import dcp_index  # noqa: F401
            from arkumu.projects.services.snapshot_service import ProjectSnapshotService  # noqa: F401
            from arkumu.catalog.services.project_views import ProjectURIs  # noqa: F401

            _load_dcp_folder_cache()
            _load_dcp_files_cache()

            # Warm lxml namespace/QName handling (first use is slow)
            self._warm_lxml()

            logger.info("OaipmhConfig: caches and modules preloaded")
        except Exception as e:
            logger.warning("OaipmhConfig: failed to preload caches: %s", e)

    def _warm_lxml(self):
        """Warm lxml's namespace handling to avoid first-request latency."""
        try:
            from lxml import etree as ET
            from arkumu.oaipmh.views.metadata import (
                METS_NS, METS_NSMAP, DC_NS, DNX_NS,
                _register_rosetta_namespaces,
            )

            _register_rosetta_namespaces()

            # Create dummy METS structure to warm lxml internals
            root = ET.Element(ET.QName(METS_NS, "mets"), nsmap=METS_NSMAP)
            ET.SubElement(root, ET.QName(METS_NS, "dmdSec"), {"ID": "warmup"})
            ET.SubElement(root, ET.QName(DC_NS, "record"))
            ET.SubElement(root, ET.QName(DNX_NS, "dnx"))
            _ = ET.tostring(root, encoding="unicode")

            # Warm ORM query compilation for OAI models
            self._warm_orm()
        except Exception as e:
            logger.debug("OaipmhConfig: lxml warmup failed: %s", e)

    def _warm_orm(self):
        """Warm Django ORM query compilation for OAI-related models."""
        try:
            from arkumu.oaipmh.models import OAIProjectPublication
            # Execute a simple query to compile the ORM internals
            OAIProjectPublication.objects.filter(is_approved=True).exists()
        except Exception as e:
            logger.debug("OaipmhConfig: ORM warmup failed: %s", e)
