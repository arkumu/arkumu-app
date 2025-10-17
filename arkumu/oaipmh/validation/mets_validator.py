"""Rosetta METS validation utilities."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from typing import Optional

from lxml import etree as ET
import xmlschema

from arkumu.oaipmh.constants import (
    DNX_NS,
    DNX_SCHEMA_PATH,
    METS_NS,
    METS_SCHEMA_PATH,
    REQUIRED_METS_NAMESPACE_MAP,
    XLINK_NS,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidationIssue:
    """Details about a single validation problem."""

    message: str
    location: Optional[str] = None


@dataclass(frozen=True)
class ValidationResult:
    """Container describing the outcome of a validation run."""

    is_valid: bool
    issues: tuple[ValidationIssue, ...] = ()


from arkumu.oaipmh.constants import XLINK_SCHEMA_PATH


@lru_cache(maxsize=1)
def _load_mets_schema(schema_path: str) -> Optional[xmlschema.XMLSchemaBase]:
    try:
        compiled = xmlschema.XMLSchema(
            schema_path,
            allow="local",
            locations={"http://www.w3.org/1999/xlink": str(XLINK_SCHEMA_PATH)},
        )
        logger.debug("Loaded METS schema from %s", schema_path)
        return compiled
    except FileNotFoundError:
        logger.error("METS schema not found at %s", schema_path)
    except xmlschema.XMLSchemaException as exc:
        logger.exception("Unable to load METS schema %s: %s", schema_path, exc)
    return None


@lru_cache(maxsize=1)
def _load_dnx_schema(schema_path: str) -> Optional[xmlschema.XMLSchemaBase]:
    try:
        compiled = xmlschema.XMLSchema11(schema_path, allow="local")
        logger.debug("Loaded DNX schema from %s", schema_path)
        return compiled
    except FileNotFoundError:
        logger.error("DNX schema not found at %s", schema_path)
    except xmlschema.XMLSchemaException as exc:
        logger.exception("Unable to load DNX schema %s: %s", schema_path, exc)
    return None


class RosettaMETSValidator:
    """Validate Rosetta METS payloads embedded in OAI-PMH responses."""

    def __init__(
        self,
        *,
        schema_path: str | None = None,
        dnx_schema_path: str | None = None,
        log: Optional[logging.Logger] = None,
    ) -> None:
        self.schema_path = schema_path or str(METS_SCHEMA_PATH)
        self.dnx_schema_path = dnx_schema_path or str(DNX_SCHEMA_PATH)
        self.logger = log or logger

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def validate_metadata_xml(self, metadata_xml: str, *, resource_uri: str | None = None) -> ValidationResult:
        """Parse and validate a `<metadata>` wrapper containing METS."""

        if not metadata_xml:
            return ValidationResult(False, (ValidationIssue("Empty metadata payload", None),))

        try:
            metadata_elem = ET.fromstring(metadata_xml.encode("utf-8"))
        except (TypeError, ET.XMLSyntaxError) as exc:
            self.logger.debug("Failed to parse metadata XML for %s: %s", resource_uri or "unknown", exc)
            return ValidationResult(False, (ValidationIssue("Invalid XML payload", None),))

        return self.validate_metadata_element(metadata_elem, resource_uri=resource_uri)

    def validate_metadata_element(
        self,
        metadata_elem: ET._Element,
        *,
        resource_uri: str | None = None,
    ) -> ValidationResult:
        """Validate an already-parsed metadata element that should contain METS."""

        mets_root = self._extract_mets_root(metadata_elem)
        if mets_root is None:
            return self._failure("No METS root element found", resource_uri)

        if not self._ensure_required_namespaces(mets_root, resource_uri):
            return self._failure("METS root missing required namespace declarations", resource_uri)

        if not self._validate_rosetta_schema(mets_root, resource_uri):
            return self._failure("Rosetta METS schema validation failed", resource_uri)

        if not self._validate_dnx_sections(mets_root, resource_uri):
            return self._failure("DNX schema validation failed", resource_uri)

        if not self._validate_semantic_rules(mets_root, resource_uri):
            return self._failure("Rosetta semantic validation failed", resource_uri)

        return ValidationResult(True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _failure(self, message: str, resource_uri: str | None) -> ValidationResult:
        if resource_uri:
            self.logger.debug("%s (%s)", message, resource_uri)
        else:
            self.logger.debug(message)
        return ValidationResult(False, (ValidationIssue(message, resource_uri),))

    def _extract_mets_root(self, metadata_elem: ET._Element) -> Optional[ET._Element]:
        node = metadata_elem

        if self._is_mets_element(node):
            return node

        for child in node:
            if self._is_mets_element(child):
                return child
        return None

    def _is_mets_element(self, element: ET._Element) -> bool:
        tag = element.tag
        if isinstance(tag, str):
            return tag == "mets" or tag.endswith("}mets")
        return False

    def _ensure_required_namespaces(self, mets_root: ET._Element, resource_uri: str | None) -> bool:
        nsmap = mets_root.nsmap or {}
        for prefix, uri in REQUIRED_METS_NAMESPACE_MAP.items():
            current = nsmap.get(prefix)
            if current != uri:
                human_prefix = prefix if prefix is not None else "default"
                self.logger.warning(
                    "Missing namespace declaration %s -> %s while validating %s",
                    human_prefix,
                    uri,
                    resource_uri or "unknown resource",
                )
                return False
        return True

    def _validate_rosetta_schema(self, mets_root: ET._Element, resource_uri: str | None) -> bool:
        schema = _load_mets_schema(self.schema_path)
        if schema is None:
            return False

        mets_bytes = ET.tostring(mets_root, encoding="utf-8")
        error_iter = schema.iter_errors(BytesIO(mets_bytes))
        first_error = next(error_iter, None)
        if first_error is not None:
            detail = first_error.reason or first_error.message
            if getattr(first_error, "path", None):
                detail = f"{detail} (path: {first_error.path})"
            self.logger.error(
                "Rosetta METS validation failed for %s: %s",
                resource_uri or "unknown resource",
                detail,
            )
            return False
        return True

    def _validate_dnx_sections(self, mets_root: ET._Element, resource_uri: str | None) -> bool:
        schema = _load_dnx_schema(self.dnx_schema_path)
        if schema is None:
            return False

        dnx_nodes = list(mets_root.findall(f".//{{{DNX_NS}}}dnx"))
        if not dnx_nodes:
            self.logger.warning(
                "No DNX sections found while validating METS for %s",
                resource_uri or "unknown resource",
            )
            return False

        for dnx_node in dnx_nodes:
            dnx_bytes = ET.tostring(dnx_node, encoding="utf-8")
            error_iter = schema.iter_errors(BytesIO(dnx_bytes))
            first_error = next(error_iter, None)
            if first_error is not None:
                detail = first_error.reason or first_error.message
                if getattr(first_error, "path", None):
                    detail = f"{detail} (path: {first_error.path})"
                self.logger.warning(
                    "DNX validation failed for %s: %s",
                    resource_uri or "unknown resource",
                    detail,
                )
                return False
        return True

    def _validate_semantic_rules(self, mets_root: ET._Element, resource_uri: str | None) -> bool:
        if mets_root.find(f'.//{{{METS_NS}}}FLocat') is None:
            self.logger.debug("Validation failed (no FLocat) for %s", resource_uri or "unknown resource")
            return False

        # Validate xlink:href on all FLocat elements
        for flocat in mets_root.findall(f'.//{{{METS_NS}}}FLocat'):
            href = flocat.get(f'{{{XLINK_NS}}}href')
            if not href or not href.strip():
                self.logger.warning(
                    "FLocat missing usable xlink:href for %s",
                    resource_uri or "unknown resource",
                )
                return False

        # Critical DNX fields must not be empty when present
        for dnx_node in mets_root.findall(f".//{{{DNX_NS}}}dnx"):
            if not self._dnx_section_has_text(
                dnx_node,
                section_id="generalRepCharacteristics",
                key_id="usageType",
            ):
                self.logger.warning(
                    "Empty usageType in generalRepCharacteristics for %s",
                    resource_uri or "unknown resource",
                )
                return False
            if not self._dnx_section_has_text(
                dnx_node,
                section_id="accessRightsPolicy",
                key_id="policyId",
            ):
                self.logger.warning(
                    "Empty policyId in accessRightsPolicy for %s",
                    resource_uri or "unknown resource",
                )
                return False
        return True

    def _dnx_section_has_text(self, dnx_node: ET._Element, *, section_id: str, key_id: str) -> bool:
        xpath = (
            f".//{{{DNX_NS}}}section[@id='{section_id}']//"
            f"{{{DNX_NS}}}key[@id='{key_id}']"
        )
        elements = dnx_node.findall(xpath)
        if not elements:
            return True  # Section/key not present, leave decision to schema
        return all(elem.text and elem.text.strip() for elem in elements)


# Shared singleton used by views and tests
rosetta_mets_validator = RosettaMETSValidator()
