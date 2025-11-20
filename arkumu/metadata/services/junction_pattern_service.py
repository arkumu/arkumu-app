from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from arkumu.metadata.derivations.kreuz_config import (
    DerivationPattern,
    DerivedTripleRecipe,
    iter_applicable_patterns,
    normalize_dataset_key,
)


@dataclass(frozen=True)
class PatternSource:
    """Metadata describing where a derivation pattern came from."""

    origin: str  # e.g. "manifest" / "static"
    dataset: Optional[str]
    name: str


class JunctionPatternService:
    """Provide derivation patterns sourced from mapping manifests and static config."""

    def __init__(
        self,
        *,
        mapping_config: Optional[Mapping[str, object]] = None,
        organization_code: Optional[str] = None,
        include_static_patterns: bool = True,
    ) -> None:
        self.mapping_config = mapping_config or {}
        self.organization_code = organization_code.lower() if organization_code else None
        self.include_static_patterns = include_static_patterns
        self._manifest_patterns = self._load_manifest_patterns()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    def iter_patterns(
        self,
        *,
        dataset_name: Optional[str],
        canonical_predicates: Iterable[str],
    ) -> Sequence[DerivationPattern]:
        """Yield derivation patterns applicable to the provided junction context."""

        normalized_dataset = normalize_dataset_key(dataset_name)
        predicate_set = {p for p in canonical_predicates if p}

        manifest_patterns = self._manifest_patterns.get(normalized_dataset, [])
        matched_manifest_patterns = [
            pattern for pattern in manifest_patterns if set(pattern.required_properties).issubset(predicate_set)
        ]

        if not self.include_static_patterns:
            return matched_manifest_patterns

        static_patterns = iter_applicable_patterns(
            self.organization_code or "",
            dataset_name,
            predicate_set,
        )

        if not matched_manifest_patterns:
            return static_patterns

        existing_names = {pattern.name for pattern in matched_manifest_patterns}
        merged: List[DerivationPattern] = list(matched_manifest_patterns)
        merged.extend(pattern for pattern in static_patterns if pattern.name not in existing_names)
        return merged

    def describe_patterns(self) -> List[PatternSource]:
        """Return human-readable metadata for all manifest-sourced patterns."""

        result: List[PatternSource] = []
        for dataset_key, patterns in self._manifest_patterns.items():
            for pattern in patterns:
                result.append(
                    PatternSource(
                        origin="manifest",
                        dataset=dataset_key,
                        name=pattern.name,
                    )
                )
        return result

    def get_manifest_patterns(self, dataset_name: Optional[str]) -> List[DerivationPattern]:
        normalized = normalize_dataset_key(dataset_name)
        return list(self._manifest_patterns.get(normalized, []))

    # ------------------------------------------------------------------
    # Manifest helpers
    # ------------------------------------------------------------------
    def _load_manifest_patterns(self) -> Dict[Optional[str], List[DerivationPattern]]:
        manifest_patterns: Dict[Optional[str], List[DerivationPattern]] = {}
        raw_patterns = self.mapping_config.get("junction_patterns")
        if not isinstance(raw_patterns, Mapping):
            return manifest_patterns

        for dataset_key, dataset_patterns in raw_patterns.items():
            normalized = normalize_dataset_key(dataset_key)
            parsed_patterns: List[DerivationPattern] = []

            if isinstance(dataset_patterns, Mapping):
                dataset_patterns = dataset_patterns.get("patterns", [])

            if not isinstance(dataset_patterns, Iterable):
                continue

            for entry in dataset_patterns:
                pattern = self._parse_manifest_pattern(entry)
                if pattern:
                    parsed_patterns.append(pattern)

            if parsed_patterns:
                manifest_patterns.setdefault(normalized, []).extend(parsed_patterns)
        return manifest_patterns

    def _parse_manifest_pattern(self, entry: object) -> Optional[DerivationPattern]:
        if not isinstance(entry, Mapping):
            return None
        name = entry.get("name") or entry.get("id")
        required = entry.get("required_properties") or entry.get("requires")
        recipes = entry.get("recipes")
        if not name or not isinstance(required, Iterable) or not isinstance(recipes, Iterable):
            return None

        required_tuple = tuple({prop for prop in required if isinstance(prop, str) and prop})
        parsed_recipes: List[DerivedTripleRecipe] = []
        for recipe in recipes:
            parsed = self._parse_recipe(recipe)
            if parsed:
                parsed_recipes.append(parsed)

        if not required_tuple or not parsed_recipes:
            return None

        description = entry.get("description") or ""
        return DerivationPattern(
            name=str(name),
            required_properties=required_tuple,
            recipes=tuple(parsed_recipes),
            description=description,
        )

    def _parse_recipe(self, recipe: object) -> Optional[DerivedTripleRecipe]:
        if not isinstance(recipe, Mapping):
            return None
        subject = recipe.get("subject_property")
        object_prop = recipe.get("object_property")
        predicate = recipe.get("predicate_uri")
        if not all(isinstance(value, str) and value for value in (subject, object_prop, predicate)):
            return None
        return DerivedTripleRecipe(
            subject_property=subject,
            object_property=object_prop,
            predicate_uri=predicate,
            description=recipe.get("description", ""),
        )
