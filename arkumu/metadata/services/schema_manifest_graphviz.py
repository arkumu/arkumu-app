from __future__ import annotations

import html
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import graphviz


@dataclass(frozen=True)
class SchemaManifestGraphStats:
    dataset_label: str
    dataset_canonical_uri: Optional[str]
    property_count: int
    canonical_count: int
    missing_canonical_count: int
    fk_edge_count: int


@dataclass(frozen=True)
class SchemaManifestGraphResult:
    svg: str
    stats: SchemaManifestGraphStats


@dataclass(frozen=True)
class SchemaManifestComparisonStats:
    canonical_classes: int
    canonical_properties: int
    organization_datasets: int
    organization_properties: int
    mapped_properties: int
    unmapped_properties: int


@dataclass(frozen=True)
class SchemaManifestComparisonResult:
    svg: str
    stats: SchemaManifestComparisonStats


class SchemaManifestGraphBuilder:
    """Render schema_manifest entries as Graphviz diagrams."""

    def __init__(
        self,
        dataset_name: str,
        dataset_manifest: Dict[str, Any],
        *,
        organization_code: Optional[str] = None,
    ) -> None:
        if not dataset_manifest:
            raise ValueError("Dataset manifest data is required to build a graph.")

        self.dataset_name = dataset_name
        self.dataset = dataset_manifest
        self.organization_code = organization_code or "global"

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    def build_graph(self) -> Tuple[graphviz.Digraph, SchemaManifestGraphStats]:
        entity_type = self.dataset.get("entity_type") or {}
        dataset_label = (
            entity_type.get("name")
            or self.dataset.get("label")
            or self.dataset.get("name")
            or self.dataset_name
        )
        dataset_canonical = entity_type.get("canonical_uri")

        dot = graphviz.Digraph(
            name=f"canonical_manifest_{self.organization_code}_{self.dataset_name}",
            graph_attr={
                "rankdir": "LR",
                "bgcolor": "transparent",
                "splines": "spline",
                "nodesep": "0.6",
                "ranksep": "1.1",
            },
            node_attr={
                "shape": "box",
                "style": "rounded,filled",
                "fontname": "Inter,Arial",
                "fontsize": "11",
                "color": "#1f2937",
            },
            edge_attr={
                "fontname": "Inter,Arial",
                "fontsize": "10",
                "color": "#4b5563",
                "arrowsize": "0.8",
            },
        )

        dataset_node_id = self._safe_id(f"dataset_{self.dataset_name}")
        dot.node(
            dataset_node_id,
            self._dataset_label(dataset_label, dataset_canonical),
            shape="record",
            fillcolor="#e0e7ff",
        )

        properties: Dict[str, Dict[str, Any]] = self.dataset.get("properties") or {}
        column_meta: Dict[str, Dict[str, Any]] = self.dataset.get("column_metadata") or {}
        fk_map = self._build_fk_map(self.dataset.get("fk_relationships") or [])

        canonical_nodes: Dict[str, str] = {}
        created_canonical_nodes: set[str] = set()
        target_nodes: Dict[str, str] = {}
        created_target_nodes: set[str] = set()

        canonical_count = 0
        missing_canonical = 0
        fk_edge_count = 0

        for idx, (slug, prop_data) in enumerate(
            sorted(properties.items(), key=lambda item: item[0].lower())
        ):
            prop_node_id = self._safe_id(f"prop_{idx}_{slug}")
            meta = column_meta.get(slug, {})
            fk_entries = fk_map.get(slug) or []

            dot.node(
                prop_node_id,
                self._property_label(prop_data, meta, slug, fk_entries),
                fillcolor=self._property_color(meta, prop_data),
            )
            dot.edge(dataset_node_id, prop_node_id)

            canonical_uri = prop_data.get("canonical_uri")
            if canonical_uri:
                canonical_count += 1
                canonical_node_id = canonical_nodes.setdefault(
                    canonical_uri,
                    self._safe_id(f"canonical_{len(canonical_nodes)}"),
                )
                if canonical_node_id not in created_canonical_nodes:
                    dot.node(
                        canonical_node_id,
                        self._canonical_label(canonical_uri),
                        shape="ellipse",
                        fillcolor="#dcfce7",
                    )
                    created_canonical_nodes.add(canonical_node_id)
                dot.edge(
                    prop_node_id,
                    canonical_node_id,
                    style="dashed",
                    color="#16a34a",
                    label="canonical",
                )
            else:
                missing_canonical += 1

            for rel in fk_entries:
                fk_edge_count += 1
                target_key = f"{rel.get('target_dataset') or 'Target'}::{rel.get('target_column') or ''}"
                target_node_id = target_nodes.setdefault(
                    target_key,
                    self._safe_id(f"target_{len(target_nodes)}"),
                )
                if target_node_id not in created_target_nodes:
                    dot.node(
                        target_node_id,
                        self._target_label(rel),
                        shape="folder",
                        fillcolor="#fef9c3",
                    )
                    created_target_nodes.add(target_node_id)
                dot.edge(
                    prop_node_id,
                    target_node_id,
                    style="dotted",
                    label=self._fk_label(rel),
                    color="#b45309",
                )

        stats = SchemaManifestGraphStats(
            dataset_label=dataset_label,
            dataset_canonical_uri=dataset_canonical,
            property_count=len(properties),
            canonical_count=canonical_count,
            missing_canonical_count=missing_canonical,
            fk_edge_count=fk_edge_count,
        )
        return dot, stats

    def render_svg(self) -> SchemaManifestGraphResult:
        dot, stats = self.build_graph()
        svg = dot.pipe(format="svg").decode("utf-8")
        if svg.startswith("<?xml"):
            svg = svg.split("\n", 1)[1]
        return SchemaManifestGraphResult(svg=svg, stats=stats)

    # ------------------------------------------------------------------
    # Label helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _build_fk_map(fk_entries: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        mapping: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for entry in fk_entries:
            source = entry.get("source_column")
            if not source:
                continue
            mapping[source].append(entry)
        return mapping

    @staticmethod
    def _dataset_label(label: str, canonical_uri: Optional[str]) -> str:
        safe_label = html.escape(label)
        canonical = html.escape(canonical_uri or "No canonical class linked")
        return (
            f"""<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="1">"""
            f"""<TR><TD ALIGN="LEFT"><B>{safe_label}</B></TD></TR>"""
            f"""<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="10" COLOR="#4338ca">{canonical}</FONT></TD></TR>"""
            f"""</TABLE>>"""
        )

    @staticmethod
    def _property_color(meta: Dict[str, Any], prop_data: Dict[str, Any]) -> str:
        if not prop_data.get("canonical_uri"):
            return "#fee2e2"
        column_type = (meta.get("column_type") or "").lower()
        if (
            meta.get("has_fk")
            or meta.get("is_fk")
            or column_type.endswith("foreign_key")
            or column_type.endswith("multi_value_foreign_key")
        ):
            return "#e0f2fe"
        if meta.get("is_anchor"):
            return "#d1fae5"
        return "#f8fafc"

    @staticmethod
    def _property_label(
        prop_data: Dict[str, Any],
        meta: Dict[str, Any],
        slug: str,
        fk_entries: List[Dict[str, Any]],
    ) -> str:
        local_name = prop_data.get("name") or slug
        uri = prop_data.get("uri") or "—"
        canonical_uri = prop_data.get("canonical_uri") or "—"
        badges: List[str] = []
        if meta.get("is_anchor"):
            badges.append("anchor")
        if meta.get("is_required"):
            badges.append("required")
        if meta.get("is_multi_value"):
            badges.append("multi")
        if meta.get("is_external_ontology") or meta.get("external_ontologies"):
            badges.append("ontology")
        if fk_entries or meta.get("has_fk") or meta.get("is_fk"):
            badges.append("fk")
        if canonical_uri == "—":
            badges.append("missing canonical")

        badge_html = ""
        if badges:
            badge_html = (
                "<TR><TD COLSPAN=\"2\" ALIGN=\"LEFT\">"
                + " ".join(
                    f'<FONT POINT-SIZE="9" COLOR="#6b7280">[{html.escape(b)}]</FONT>'
                    for b in badges
                )
                + "</TD></TR>"
            )

        fk_html = ""
        if fk_entries:
            targets = [
                f"{entry.get('target_dataset') or '?'} → {entry.get('target_column') or '?'}"
                for entry in fk_entries[:3]
            ]
            if len(fk_entries) > 3:
                targets.append("…")
            fk_html = (
                "<TR><TD COLSPAN=\"2\" ALIGN=\"LEFT\">"
                f'<FONT POINT-SIZE="9" COLOR="#92400e">FK {html.escape(", ".join(targets))}</FONT>'
                "</TD></TR>"
            )

        slug_safe = html.escape(slug)
        name_safe = html.escape(local_name)
        uri_safe = html.escape(uri)
        canonical_safe = html.escape(canonical_uri)
        canonical_short = canonical_uri.rsplit("/", 1)[-1] if canonical_uri != "—" else "—"
        canonical_short_safe = html.escape(canonical_short)

        return (
            f"""<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="1">"""
            f"""<TR><TD ALIGN="LEFT"><B>{name_safe}</B></TD>"""
            f"""<TD ALIGN="RIGHT"><FONT POINT-SIZE="9" COLOR="#6b7280">{slug_safe}</FONT></TD></TR>"""
            f"""{badge_html}"""
            f"""<TR><TD COLSPAN="2" ALIGN="LEFT"><FONT POINT-SIZE="9" COLOR="#6b7280">{uri_safe}</FONT></TD></TR>"""
            f"""<TR><TD COLSPAN="2" ALIGN="LEFT"><FONT POINT-SIZE="10" COLOR="#15803d">{canonical_short_safe}</FONT></TD></TR>"""
            f"""<TR><TD COLSPAN="2" ALIGN="LEFT"><FONT POINT-SIZE="9" COLOR="#4b5563">{canonical_safe}</FONT></TD></TR>"""
            f"""{fk_html}"""
            f"""</TABLE>>"""
        )

    @staticmethod
    def _canonical_label(canonical_uri: str) -> str:
        short = canonical_uri.rsplit("/", 1)[-1]
        short_safe = html.escape(short)
        canonical_safe = html.escape(canonical_uri)
        return (
            f"""<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="1">"""
            f"""<TR><TD ALIGN="LEFT"><B>{short_safe}</B></TD></TR>"""
            f"""<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="9" COLOR="#4b5563">{canonical_safe}</FONT></TD></TR>"""
            f"""</TABLE>>"""
        )

    @staticmethod
    def _target_label(rel: Dict[str, Any]) -> str:
        dataset = rel.get("target_dataset") or "Target dataset"
        column = rel.get("target_column") or "ID"
        canonical = rel.get("target_canonical_property")
        dataset_safe = html.escape(dataset)
        column_safe = html.escape(column)
        canonical_safe = html.escape(canonical) if canonical else "—"
        return (
            f"""<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="1">"""
            f"""<TR><TD ALIGN="LEFT"><B>{dataset_safe}</B></TD></TR>"""
            f"""<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="10">{column_safe}</FONT></TD></TR>"""
            f"""<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="9" COLOR="#4b5563">{canonical_safe}</FONT></TD></TR>"""
            f"""</TABLE>>"""
        )

    @staticmethod
    def _fk_label(rel: Dict[str, Any]) -> str:
        if rel.get("relationship_type"):
            return rel["relationship_type"]
        if rel.get("source_property"):
            return rel["source_property"]
        return rel.get("source_column") or "FK"

    @staticmethod
    def _safe_id(value: str) -> str:
        slug = re.sub(r"[^0-9a-zA-Z_]+", "_", value)
        if slug and slug[0].isdigit():
            slug = f"id_{slug}"
        return slug or "node"


class SchemaManifestComparisonGraphBuilder:
    """Render an organization manifest against Arkumu canonical targets."""

    def __init__(
        self,
        manifest: Dict[str, Dict[str, Any]],
        *,
        organization_code: Optional[str] = None,
    ) -> None:
        if not manifest:
            raise ValueError("Schema manifest is required to build comparison graph.")
        self.manifest = manifest
        self.organization_code = organization_code or "org"

    def render_svg(self) -> SchemaManifestComparisonResult:
        canonical_classes: Dict[str, Dict[str, Any]] = {}
        canonical_properties: Dict[str, Dict[str, Any]] = {}
        org_datasets: List[Dict[str, Any]] = []

        total_properties = 0
        mapped_properties = 0

        for dataset_name, dataset in sorted(self.manifest.items(), key=lambda item: item[0].lower()):
            entity_type = dataset.get("entity_type") or {}
            canonical_class_uri = entity_type.get("canonical_uri")
            dataset_label = (
                dataset.get("label")
                or entity_type.get("name")
                or dataset.get("name")
                or dataset_name
            )
            dataset_id = self._safe_id(f"org_dataset_{dataset_name}")
            dataset_entry = {
                "id": dataset_id,
                "name": dataset_name,
                "label": dataset_label,
                "canonical_uri": canonical_class_uri,
                "properties": [],
                "column_metadata": dataset.get("column_metadata") or {},
            }
            org_datasets.append(dataset_entry)

            if canonical_class_uri:
                canonical_classes.setdefault(
                    canonical_class_uri,
                    {
                        "label": entity_type.get("canonical_label") or entity_type.get("name") or canonical_class_uri.rsplit("/", 1)[-1],
                        "datasets": set(),
                        "id": self._safe_id(f"canonical_class_{canonical_class_uri}"),
                    },
                )["datasets"].add(dataset_name)

            properties = dataset.get("properties") or {}
            for slug, prop in sorted(properties.items(), key=lambda item: item[0].lower()):
                total_properties += 1
                prop_id = self._safe_id(f"org_prop_{dataset_name}_{slug}")
                canonical_uri = prop.get("canonical_uri")
                if canonical_uri:
                    mapped_properties += 1
                    prop_entry = canonical_properties.setdefault(
                        canonical_uri,
                        {
                            "label": prop.get("canonical_label") or canonical_uri.rsplit("/", 1)[-1],
                            "uri": canonical_uri,
                            "classes": set(),
                            "id": self._safe_id(f"canonical_prop_{canonical_uri}"),
                        },
                    )
                    if canonical_class_uri:
                        prop_entry["classes"].add(canonical_class_uri)
                dataset_entry["properties"].append(
                    {
                        "id": prop_id,
                        "slug": slug,
                        "data": prop,
                        "metadata": dataset_entry["column_metadata"].get(slug, {}),
                        "canonical_uri": canonical_uri,
                    }
                )

        dot = graphviz.Digraph(
            name=f"canonical_vs_org_{self.organization_code}",
            graph_attr={
                "rankdir": "LR",
                "splines": "spline",
                "bgcolor": "transparent",
                "nodesep": "0.8",
                "ranksep": "1.2",
            },
            node_attr={
                "shape": "box",
                "style": "rounded,filled",
                "fontname": "Inter,Arial",
                "fontsize": "11",
                "color": "#1f2937",
            },
            edge_attr={
                "fontname": "Inter,Arial",
                "fontsize": "10",
                "color": "#4b5563",
                "arrowsize": "0.8",
            },
        )

        with dot.subgraph(name="cluster_org") as org_cluster:
            org_cluster.attr(
                label=f"{self.organization_code.upper()} schema manifest",
                style="rounded",
                color="#bfdbfe",
            )
            for dataset in org_datasets:
                org_cluster.node(
                    dataset["id"],
                    SchemaManifestGraphBuilder._dataset_label(dataset["label"], dataset["canonical_uri"]),
                    shape="record",
                    fillcolor="#dbeafe",
                )
                for prop in dataset["properties"]:
                    label = SchemaManifestGraphBuilder._property_label(
                        prop["data"],
                        prop["metadata"],
                        prop["slug"],
                        [],
                    )
                    fill = SchemaManifestGraphBuilder._property_color(prop["metadata"], prop["data"])
                    org_cluster.node(prop["id"], label, fillcolor=fill)
                    org_cluster.edge(dataset["id"], prop["id"], color="#3b82f6")

        with dot.subgraph(name="cluster_canonical") as canonical_cluster:
            canonical_cluster.attr(
                label="Arkumu canonical schema",
                style="rounded",
                color="#bbf7d0",
            )
            for class_uri, info in canonical_classes.items():
                canonical_cluster.node(
                    info["id"],
                    self._canonical_class_label(info["label"], class_uri),
                    shape="folder",
                    fillcolor="#bbf7d0",
                )
            for canonical_uri, info in canonical_properties.items():
                canonical_cluster.node(
                    info["id"],
                    SchemaManifestGraphBuilder._canonical_label(canonical_uri),
                    shape="ellipse",
                    fillcolor="#dcfce7",
                )

        for dataset in org_datasets:
            if not dataset["canonical_uri"]:
                continue
            class_info = canonical_classes.get(dataset["canonical_uri"])
            if not class_info:
                continue
            dot.edge(
                dataset["id"],
                class_info["id"],
                color="#6d28d9",
                penwidth="1.2",
                label="class",
            )

        for dataset in org_datasets:
            for prop in dataset["properties"]:
                canonical_uri = prop["canonical_uri"]
                if not canonical_uri:
                    continue
                canonical_info = canonical_properties.get(canonical_uri)
                if not canonical_info:
                    continue
                dot.edge(
                    prop["id"],
                    canonical_info["id"],
                    color="#16a34a",
                    penwidth="1.4",
                    label="canonical",
                )

        for canonical_uri, info in canonical_properties.items():
            classes: Set[str] = info["classes"]
            for class_uri in classes:
                class_info = canonical_classes.get(class_uri)
                if not class_info:
                    continue
                dot.edge(
                    info["id"],
                    class_info["id"],
                    color="#94a3b8",
                    style="dashed",
                )

        stats = SchemaManifestComparisonStats(
            canonical_classes=len(canonical_classes),
            canonical_properties=len(canonical_properties),
            organization_datasets=len(org_datasets),
            organization_properties=total_properties,
            mapped_properties=mapped_properties,
            unmapped_properties=max(total_properties - mapped_properties, 0),
        )
        svg = dot.pipe(format="svg").decode("utf-8")
        if svg.startswith("<?xml"):
            svg = svg.split("\n", 1)[1]
        return SchemaManifestComparisonResult(svg=svg, stats=stats)

    @staticmethod
    def _sanitise_text(value: Optional[str], fallback: str) -> str:
        if not value:
            return fallback
        return value

    @staticmethod
    def _canonical_class_label(label: str, uri: str) -> str:
        safe_label = html.escape(label)
        safe_uri = html.escape(uri)
        return (
            f"""<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="1">"""
            f"""<TR><TD ALIGN="LEFT"><B>{safe_label}</B></TD></TR>"""
            f"""<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="9" COLOR="#475569">{safe_uri}</FONT></TD></TR>"""
            f"""</TABLE>>"""
        )

    @staticmethod
    def _safe_id(value: str) -> str:
        slug = re.sub(r"[^0-9a-zA-Z_]+", "_", value)
        if slug and slug[0].isdigit():
            slug = f"id_{slug}"
        return slug or "node"
