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
class ProjectDigitalObjectLicense:
    uri: Optional[str] = None
    label_de: Optional[str] = None
    label_en: Optional[str] = None
    rights_statement: Optional[str] = None
    identifier: Optional[str] = None


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
    license: Optional[ProjectDigitalObjectLicense] = None
    uuid: Optional[str] = None
    genesis_type: Optional[str] = None
    media_type: Optional[str] = None
    significant_properties_de: Optional[str] = None
    significant_properties_en: Optional[str] = None
    originalsprache: Optional[str] = None
    sprachfassung: Optional[str] = None
    untertitelsprache: Optional[str] = None
    tonformat: Optional[str] = None
    tonmischfassung: Optional[str] = None
    equalizer: Optional[str] = None
    resource_id: Optional[str] = None
    source: Optional[str] = None
    source_event_ids: List[str] = field(default_factory=list)
    source_event_uris: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.license and isinstance(self.license, dict):
            self.license = ProjectDigitalObjectLicense(**self.license)


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
    is_copyright_holder: bool = False
    is_neighbouring_rights_holder: bool = False


@dataclass
class ProjectEvent:
    id: Optional[str] = None
    owning_project_uris: List[str] = field(default_factory=list)
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
    name_de: Optional[str] = None
    name_en: Optional[str] = None
    type_label_de: Optional[str] = None
    type_label_en: Optional[str] = None
    type_synonyms_de: List[str] = field(default_factory=list)
    type_synonyms_en: List[str] = field(default_factory=list)
    type_wikidata_id: Optional[str] = None
    type_gnd_id: Optional[str] = None
    type_aat_id: Optional[str] = None
    type_lido_id: Optional[str] = None
    type_uri: Optional[str] = None
    start_estimated: Optional[bool] = None
    end_estimated: Optional[bool] = None
    tonart: Optional[str] = None
    stimmung_in_hertz: Optional[str] = None
    actors: List[ProjectEventActor] = field(default_factory=list)
    is_reference_only: bool = False


@dataclass
class ProjectPropertyBundle:
    dauer_hms: Optional[str] = None
    dauer_freitext: Optional[str] = None
    tonarten: List[str] = field(default_factory=list)
    produktionsformat: Optional[str] = None
    instrumentierung: Optional[str] = None
    aspect_ratio: Optional[str] = None
    stimmung_hz: Optional[str] = None
    sprachen: List[str] = field(default_factory=list)
    abspielgeschwindigkeit: Optional[str] = None
    equalizer: List[str] = field(default_factory=list)
    bandbreite: Optional[str] = None
    tonaufnahme: Optional[str] = None
    werkverzeichnis: Optional[str] = None
    musikgattungen: List[str] = field(default_factory=list)
    tonformate: List[str] = field(default_factory=list)
    bildfrequenz: Optional[str] = None
    filmentwicklung: Optional[str] = None
    tonmischfassungen: List[str] = field(default_factory=list)
    fernsehnorm: Optional[str] = None
    spurausrichtung: Optional[str] = None
    ton_kanaele: Optional[str] = None
    audio_aufnahmetechnik: Optional[str] = None


@dataclass
class ProjectStatusSignatures:
    signatur: Optional[str] = None
    signatur_beim_einlieferer: Optional[str] = None
    werkverzeichnis_nummer: Optional[str] = None


@dataclass
class ProjectAuthorityLinks:
    wikidata_ids: List[str] = field(default_factory=list)
    gnd_ids: List[str] = field(default_factory=list)
    weitere_normdaten: List[str] = field(default_factory=list)
    externe_webseiten: List[str] = field(default_factory=list)


@dataclass
class ProjectSubmitterInfo:
    hochschule: Optional[str] = None
    hochschule_uri: Optional[str] = None
    organisationseinheiten: List[str] = field(default_factory=list)
    erstellungsdatum: Optional[str] = None
    letzte_modifikation: Optional[str] = None


@dataclass
class ProjectLicenseInfo:
    bestehende_vertraege: List[str] = field(default_factory=list)
    neuer_lizenzvertrag: Optional[str] = None
    angegebene_nutzungsrechte: Optional[str] = None
    sonderregelungen: List[str] = field(default_factory=list)
    weitere_rechtsdokumente: List[str] = field(default_factory=list)
    dateiabfrage_dokument: Optional[str] = None


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
    rights_status: Optional[str] = None
    reference_events: List[ProjectEvent] = field(default_factory=list)
    event_sources: Dict[str, List[str]] = field(default_factory=dict)
    filtered_event_ids: List[str] = field(default_factory=list)
    digital_object_sources: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    filtered_digital_object_ids: List[str] = field(default_factory=list)
    reference_project_uris: List[str] = field(default_factory=list)
    ownership_filtered: bool = False
    reference_only: bool = False
    harvestable: bool = True
    properties: ProjectPropertyBundle = field(default_factory=ProjectPropertyBundle)
    status: ProjectStatusSignatures = field(default_factory=ProjectStatusSignatures)
    authority: ProjectAuthorityLinks = field(default_factory=ProjectAuthorityLinks)
    submitter: ProjectSubmitterInfo = field(default_factory=ProjectSubmitterInfo)
    licenses: ProjectLicenseInfo = field(default_factory=ProjectLicenseInfo)

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

        def _build_events(items: Optional[List[Dict[str, Any]]]) -> List[ProjectEvent]:
            if not items:
                return []
            return [
                ProjectEvent(
                    **{
                        **item,
                        "owning_project_uris": list(item.get("owning_project_uris", [])),
                        "actors": _build_list(item.get("actors"), ProjectEventActor),
                    }
                )
                for item in items
            ]

        def _build_digital_objects(items: Optional[List[Dict[str, Any]]]) -> List[ProjectDigitalObject]:
            if not items:
                return []
            materialized: List[ProjectDigitalObject] = []
            for item in items:
                normalized = {
                    **item,
                    "source_event_ids": list(item.get("source_event_ids", [])),
                    "source_event_uris": list(item.get("source_event_uris", [])),
                }
                materialized.append(ProjectDigitalObject(**normalized))
            return materialized

        record = cls(
            subject_id=payload["subject_id"],
            uri=payload["uri"],
            title=payload.get("title"),
            subtitle=payload.get("subtitle"),
            description=payload.get("description"),
            image=payload.get("image"),
            institution=institution,
            categories=_build_list(payload.get("categories"), ProjectCategory),
            events=_build_events(payload.get("events")),
            actors=_build_list(payload.get("actors"), ProjectActor),
            alternative_titles=_build_list(payload.get("alternative_titles"), ProjectAlternateTitle),
            catchphrases=_build_list(payload.get("catchphrases"), ProjectCatchphrase),
            project_type=ProjectType(**payload["project_type"]) if payload.get("project_type") else None,
            digital_objects=_build_digital_objects(payload.get("digital_objects")),
            year_range=payload.get("year_range"),
            institution_codes=payload.get("institution_codes", []),
            category_slugs=payload.get("category_slugs", []),
            rights_status=payload.get("rights_status"),
            reference_events=_build_events(payload.get("reference_events")),
            event_sources={key: list(value) for key, value in (payload.get("event_sources") or {}).items()},
            filtered_event_ids=list(payload.get("filtered_event_ids", [])),
            digital_object_sources={
                key: {
                    **value,
                    "event_ids": list(value.get("event_ids", [])),
                    "event_uris": list(value.get("event_uris", [])),
                    "filtered_event_ids": list(value.get("filtered_event_ids", [])),
                }
                for key, value in (payload.get("digital_object_sources") or {}).items()
            },
            filtered_digital_object_ids=list(payload.get("filtered_digital_object_ids", [])),
            reference_project_uris=list(payload.get("reference_project_uris", [])),
            ownership_filtered=bool(payload.get("ownership_filtered", False)),
            reference_only=bool(payload.get("reference_only", False)),
            harvestable=bool(payload.get("harvestable", True)),
            properties=ProjectPropertyBundle(**(payload.get("properties") or {})),
            status=ProjectStatusSignatures(**(payload.get("status") or {})),
            authority=ProjectAuthorityLinks(**(payload.get("authority") or {})),
            submitter=ProjectSubmitterInfo(**(payload.get("submitter") or {})),
            licenses=ProjectLicenseInfo(**(payload.get("licenses") or {})),
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
