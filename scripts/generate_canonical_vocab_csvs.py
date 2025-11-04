"""
Generate controlled vocabulary CSVs with canonical Arkumu concept URIs.

The script reads the canonical mapping table from the sibling
``arkumu-metadata`` repository and enriches each controlled vocabulary CSV
with a new ``Canonical URI`` column. The original ``URI`` column is retained
so provenance back to the GitLab wiki remains available.

Usage (run from the arkumu-app repository root):

    uv run python scripts/generate_canonical_vocab_csvs.py

Optional arguments allow overriding the metadata repository location or the
output directory. See ``--help`` for details.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from urllib.parse import urlparse


DEFAULT_METADATA_DIRNAME = "arkumu-metadata"
MAPPING_FILENAME = "2025-09-24-Mapping-aller-Datenquellen.csv"
CONTROLLED_VOCAB_DIRNAME = "controlled_vocabularies"

# Mapping of controlled vocabulary filenames to the label used in the canonical
# mapping table (column "Label"). The mapping table provides the canonical base
# URI we append our slugs to.
VOCAB_LABELS: Dict[str, str] = {
    "Event_Types.csv": "Ereignistyp",
    "Project_Types.csv": "Projektart",
    "Project_Categories.csv": "Projektkategorie",
    "Roles.csv": "Rolle",
    "Equipment_Types.csv": "Equipmentart",
    "Information_Storage_Medium_Types.csv": "Informationstraegertyp",
    "Organisational_Units.csv": "Organisationseinheit",
}


class CanonicalMappingError(RuntimeError):
    """Raised when the canonical mapping table is missing required entries."""


def slugify_token(value: str) -> str:
    """
    Lightweight slugification compatible with arkumu.common.uri_utils.slugify_uri_part.
    """

    if not isinstance(value, str):
        value = str(value)

    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "Ä": "Ae",
        "Ö": "Oe",
        "Ü": "Ue",
        "ß": "ss",
        " ": "-",
        "_": "-",
        "/": "-",
        "\\": "-",
        "?": "",
        "#": "",
        "&": "and",
        "+": "plus",
        "(": "",
        ")": "",
        "[": "",
        "]": "",
        "{": "",
        "}": "",
        "'": "",
        '"': "",
        "`": "",
        ":": "-",
        ";": "-",
        ",": "-",
        ".": "-",
        "=": "",
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    value = value.lower()

    # Keep alphanumeric characters and hyphens only
    value = "".join(ch for ch in value if ch.isalnum() or ch == "-")

    # Collapse multiple hyphens
    while "--" in value:
        value = value.replace("--", "-")

    value = value.strip("-")

    return value or "n-a"


def sniff_dialect(sample: str, default_delimiter: str = ";") -> csv.Dialect:
    """
    Attempt to sniff a CSV dialect and fall back to the provided delimiter.
    """

    sniffer = csv.Sniffer()
    try:
        return sniffer.sniff(sample)
    except csv.Error:
        class FallbackDialect(csv.Dialect):
            delimiter = default_delimiter
            quotechar = '"'
            escapechar = None
            doublequote = True
            skipinitialspace = False
            lineterminator = "\n"
            quoting = csv.QUOTE_MINIMAL

        return FallbackDialect


def load_class_targets(mapping_path: Path) -> Dict[str, str]:
    """
    Load the canonical target URIs for class definitions from the mapping CSV.

    Returns a dictionary keyed by the mapping table's "Label" value and
    containing the canonical "Target" URI.
    """

    if not mapping_path.exists():
        raise CanonicalMappingError(f"Mapping file not found: {mapping_path}")

    with mapping_path.open("r", encoding="utf-8") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        dialect = sniff_dialect(sample, default_delimiter=",")
        reader = csv.DictReader(handle, dialect=dialect)
        class_targets: Dict[str, str] = {}
        for row in reader:
            if (row.get("Type") or "").strip().lower() != "class":
                continue
            label = (row.get("Label") or "").strip()
            target = (row.get("Target") or "").strip()
            if not label or not target:
                continue
            class_targets[label] = target.rstrip("/")

    return class_targets


def derive_slug(
    uri: str,
    *,
    fallback_tokens: Iterable[str],
) -> str:
    """
    Derive a stable slug for a vocabulary entry based on its existing URI.
    """

    slug_candidate: str | None = None
    if uri:
        parsed = urlparse(uri)
        if parsed.fragment:
            slug_candidate = parsed.fragment
        elif parsed.path:
            slug_candidate = parsed.path.rstrip("/").split("/")[-1]

    if slug_candidate:
        slug = slugify_token(slug_candidate)
        if slug:
            return slug

    for token in fallback_tokens:
        if not token:
            continue
        slug = slugify_token(str(token))
        if slug:
            return slug

    return "unidentified-entry"


def enrich_vocabulary_file(
    vocab_path: Path,
    base_uri: str,
    output_path: Path,
) -> Tuple[int, List[str]]:
    """
    Read a controlled vocabulary CSV, compute canonical URIs, and write a new file.

    Returns the number of processed rows and any warnings encountered.
    """

    warnings: List[str] = []
    with vocab_path.open("r", encoding="utf-8") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        dialect = sniff_dialect(sample, default_delimiter=";")
        reader = csv.DictReader(handle, dialect=dialect)
        if not reader.fieldnames:
            raise RuntimeError(f"No header found in {vocab_path}")

        fieldnames = list(reader.fieldnames)
        if "Canonical URI" not in fieldnames:
            try:
                uri_index = fieldnames.index("URI")
                fieldnames.insert(uri_index + 1, "Canonical URI")
            except ValueError:
                fieldnames.append("Canonical URI")

        rows = list(reader)

    used_slugs: defaultdict[str, set[str]] = defaultdict(set)
    total_rows = 0

    for row in rows:
        original_uri = (row.get("URI") or "").strip()
        slug = derive_slug(
            original_uri,
            fallback_tokens=(
                row.get("ID"),
                f"{vocab_path.stem}-{row.get('ID')}",
                row.get("English Name"),
                row.get("German Name"),
            ),
        )

        if slug in used_slugs[base_uri]:
            fallback_slug = derive_slug(
                "",
                fallback_tokens=(
                    f"{slug}-{row.get('ID')}",
                    f"{slug}-{total_rows}",
                ),
            )
            warnings.append(
                f"Duplicate slug '{slug}' in {vocab_path.name}; using fallback '{fallback_slug}'."
            )
            slug = fallback_slug

        used_slugs[base_uri].add(slug)
        canonical_uri = f"{base_uri}/{slug}"
        row["Canonical URI"] = canonical_uri
        total_rows += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            delimiter=dialect.delimiter,
            quotechar='"',
            doublequote=True,
            lineterminator="\n",
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    return total_rows, warnings


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata-root",
        type=Path,
        default=None,
        help="Path to the arkumu-metadata repository (defaults to sibling directory).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for generated CSVs (defaults to metadata controlled_vocabularies).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting existing output files.",
    )
    return parser


def resolve_paths(args: argparse.Namespace) -> Tuple[Path, Path, Path]:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent

    metadata_root = (
        args.metadata_root
        if args.metadata_root
        else repo_root.parent / DEFAULT_METADATA_DIRNAME
    )

    mapping_path = metadata_root / MAPPING_FILENAME
    vocab_dir = metadata_root / CONTROLLED_VOCAB_DIRNAME

    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = vocab_dir

    return mapping_path, vocab_dir, output_dir


def main(argv: List[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    mapping_path, vocab_dir, output_dir = resolve_paths(args)

    class_targets = load_class_targets(mapping_path)

    missing_labels = [label for label in VOCAB_LABELS.values() if label not in class_targets]
    if missing_labels:
        raise CanonicalMappingError(
            "Missing canonical targets for labels: " + ", ".join(sorted(missing_labels))
        )

    summaries: List[str] = []
    for filename, label in sorted(VOCAB_LABELS.items()):
        input_path = vocab_dir / filename
        if not input_path.exists():
            summaries.append(f"- {filename}: skipped (file not found)")
            continue

        base_uri = class_targets[label]
        output_path = output_dir / f"{Path(filename).stem}_canonical.csv"
        if output_path.exists() and not args.overwrite:
            summaries.append(f"- {filename}: skipped (output exists; use --overwrite)")
            continue

        row_count, warnings = enrich_vocabulary_file(input_path, base_uri, output_path)
        summary_line = f"- {filename}: wrote {row_count} rows to {output_path.name}"
        if warnings:
            summary_line += f" (warnings: {len(warnings)})"
        summaries.append(summary_line)
        for warning in warnings:
            summaries.append(f"  • {warning}")

    print("Controlled vocabulary export complete:")
    for line in summaries:
        print(line)

    return 0


if __name__ == "__main__":
    sys.exit(main())
