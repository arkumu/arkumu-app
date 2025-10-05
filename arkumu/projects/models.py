"""Dataclasses representing cached project snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ProjectAlternateTitle:
    value: str
    uri: Optional[str] = None


@dataclass
class ProjectCatchphrase:
    label: str
    uri: Optional[str] = None


@dataclass
class ProjectDigitalObject:
    path: str
    uri: Optional[str] = None
    storage_key: Optional[str] = None
    file_name: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    checksum: Optional[str] = None
    checksum_algorithm: Optional[str] = None
    checksum_provenance: Optional[str] = None
    access_url: Optional[str] = None
    storage_status: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class ProjectInstitution:
    label: Optional[str]
    uri: Optional[str] = None
    code: Optional[str] = None


@dataclass
class ProjectCategory:
    label: Optional[str]
    uri: Optional[str] = None
    slug: Optional[str] = None


@dataclass
class ProjectType:
    label: Optional[str]
    uri: Optional[str] = None


@dataclass
class ProjectActor:
    name: Optional[str]
    roles: List[str] = field(default_factory=list)
    uri: Optional[str] = None


@dataclass
class ProjectEventActor:
    name: Optional[str]
    roles: List[str] = field(default_factory=list)


@dataclass
class ProjectEvent:
    id: Optional[str] = None
    uri: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    location_id: Optional[str] = None
    country: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    type: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    actors: List[ProjectEventActor] = field(default_factory=list)


@dataclass
class ProjectRecord:
    subject_id: str
    uri: str
    title: Optional[str] = None
    subtitle: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None
    institution: Optional[ProjectInstitution] = None
    categories: List[ProjectCategory] = field(default_factory=list)
    events: List[ProjectEvent] = field(default_factory=list)
    actors: List[ProjectActor] = field(default_factory=list)
    alternative_titles: List[ProjectAlternateTitle] = field(default_factory=list)
    catchphrases: List[ProjectCatchphrase] = field(default_factory=list)
    project_type: Optional[ProjectType] = None
    digital_objects: List[ProjectDigitalObject] = field(default_factory=list)
    year_range: Optional[str] = None
    institution_codes: List[str] = field(default_factory=list)
    category_slugs: List[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return self.uri.rstrip('/').split('/')[-1]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ProjectRecord":
        institution_payload = payload.get("institution")
        institution = (
            ProjectInstitution(**institution_payload)
            if institution_payload
            else None
        )

        def _build_list(items: Optional[List[Dict[str, Any]]], factory):
            if not items:
                return []
            return [factory(**item) for item in items]

        record = cls(
            subject_id=payload["subject_id"],
            uri=payload["uri"],
            title=payload.get("title"),
            subtitle=payload.get("subtitle"),
            description=payload.get("description"),
            image=payload.get("image"),
            institution=institution,
            categories=_build_list(payload.get("categories"), ProjectCategory),
            events=_build_list(payload.get("events"), ProjectEvent),
            actors=_build_list(payload.get("actors"), ProjectActor),
            alternative_titles=_build_list(payload.get("alternative_titles"), ProjectAlternateTitle),
            catchphrases=_build_list(payload.get("catchphrases"), ProjectCatchphrase),
            project_type=ProjectType(**payload["project_type"]) if payload.get("project_type") else None,
            digital_objects=_build_list(payload.get("digital_objects"), ProjectDigitalObject),
            year_range=payload.get("year_range"),
            institution_codes=payload.get("institution_codes", []),
            category_slugs=payload.get("category_slugs", []),
        )
        return record

    def to_card_dict(self) -> Dict[str, Any]:
        def _object_display_path(obj: ProjectDigitalObject) -> Optional[str]:
            return obj.access_url or obj.path or obj.storage_key

        card: Dict[str, Any] = {
            "uri": self.uri,
            "title": self.title or "",
            "subtitle": self.subtitle or "",
            "image": self.image or "images/main/card_1.png",
            "institution": (self.institution.label if self.institution and self.institution.label else ""),
            "categories": [cat.label for cat in self.categories if cat.label],
            "year_range": self.year_range or "",
            "digital_objects": [
                path for path in (_object_display_path(obj) for obj in self.digital_objects)
                if path
            ],
        }

        if self.digital_objects and not self.image:
            fallback_path = _object_display_path(self.digital_objects[0])
            if fallback_path:
                card["image"] = fallback_path

        for idx, actor in enumerate(self.actors[:4]):
            if actor.name:
                card[f"contributor{idx + 1}_name"] = actor.name
            if actor.roles:
                card[f"contributor{idx + 1}_role"] = ", ".join(sorted(set(actor.roles)))
        if len(self.actors) > 4:
            card["additional_contributors"] = f"{len(self.actors) - 4} weitere"

        categories = card["categories"]
        for idx, category in enumerate(categories[:4]):
            card[f"category{idx + 1}"] = category
        if len(categories) > 4:
            card["additional_categories"] = f"{len(categories) - 4} weitere"

        return card

    def matches_query(self, query: str) -> bool:
        if not query:
            return True

        haystack = " ".join(
            filter(
                None,
                [
                    self.title,
                    self.subtitle,
                    self.institution.label if self.institution else None,
                    " ".join(cat.label for cat in self.categories if cat.label),
                ],
            )
        ).lower()
        return query.lower() in haystack


@dataclass
class ProjectSnapshot:
    projects: List[ProjectRecord]
    counts: Dict[str, int] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "projects": [project.to_dict() for project in self.projects],
            "counts": self.counts,
            "generated_at": self.generated_at.isoformat(),
        }

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "ProjectSnapshot":
        projects = [ProjectRecord.from_dict(item) for item in payload.get("projects", [])]
        generated_at_raw = payload.get("generated_at")
        generated_at = (
            datetime.fromisoformat(generated_at_raw)
            if isinstance(generated_at_raw, str)
            else datetime.utcnow()
        )
        return cls(
            projects=projects,
            counts=payload.get("counts", {}),
            generated_at=generated_at,
        )
