from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Tuple

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from arkumu.metadata.canonical import canonical_uri
from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.models.resources.entity import EntityResource
from arkumu.users.models import Organization


PROJECT_DATASET = "Projekt"
EVENT_DATASET = "Ereignis"
ACTOR_DATASET = "Akteurin"
DIGITAL_DATASET = "Digitales Objekt"


class Command(BaseCommand):
    help = "Seed demo data to exercise the project overview workspace UI."

    def add_arguments(self, parser):
        parser.add_argument(
            "--organization",
            default="fuk",
            help="Organisation-Code für die Demo-Daten (Standard: fuk)",
        )
        parser.add_argument(
            "--projects",
            type=int,
            default=3,
            help="Anzahl der zu erzeugenden Projekte (Standard: 3)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        org_code: str = options["organization"]
        project_amount: int = max(1, options["projects"])

        organization, _ = Organization.objects.get_or_create(
            code=org_code,
            defaults={"name": org_code.upper()},
        )

        dataset_resources = self._ensure_dataset_resources(organization)
        predicate_resources = self._ensure_predicate_resources(organization)

        created_projects = []
        for index in range(project_amount):
            project = self._create_project(
                organization=organization,
                dataset_resources=dataset_resources,
                predicates=predicate_resources,
                index=index,
            )
            created_projects.append(project)

        self.stdout.write(
            self.style.SUCCESS(
                f"{len(created_projects)} Projekte für Organisation '{organization.code}' erstellt."
            )
        )

    # ------------------------------------------------------------------ #
    # Dataset scaffolding
    # ------------------------------------------------------------------ #
    def _ensure_dataset_resources(
        self,
        organization: Organization,
    ) -> dict[str, Resource]:
        datasets = {}
        for dataset_name in (PROJECT_DATASET, EVENT_DATASET, ACTOR_DATASET, DIGITAL_DATASET):
            uri = f"http://arkumu.org/data/{slugify(organization.code)}/datasets/{slugify(dataset_name)}"
            resource, _ = Resource.objects.get_or_create(
                uri=uri,
                defaults={
                    "resource_type": ResourceType.IRI,
                    "name": dataset_name,
                    "organization": organization,
                },
            )
            datasets[dataset_name] = resource
        return datasets

    def _ensure_predicate_resources(
        self,
        organization: Organization,
    ) -> dict[str, Resource]:
        predicate_map = {}
        predicate_uris = {
            "project_event": canonical_uri("event"),
            "event_actor": canonical_uri("actor_in_event"),
            "digital_object": canonical_uri("digital_object"),
            "event_name": "http://arkumu.org/data/properties/ereignisname",
            "event_start": "http://arkumu.org/data/properties/ereignisbeginn",
            "event_end": "http://arkumu.org/data/properties/ereignisende",
        }
        for key, uri in predicate_uris.items():
            resource, _ = Resource.objects.get_or_create(
                uri=uri,
                defaults={
                    "resource_type": ResourceType.PROPERTY,
                    "name": key.replace("_", " ").title(),
                    "organization": organization,
                    "canonical_uri": uri,
                },
            )
            predicate_map[key] = resource
        return predicate_map

    # ------------------------------------------------------------------ #
    # Entity creation helpers
    # ------------------------------------------------------------------ #
    def _create_project(
        self,
        *,
        organization: Organization,
        dataset_resources: dict[str, Resource],
        predicates: dict[str, Resource],
        index: int,
    ) -> Resource:
        project_entity, _ = EntityResource.create_by_organization_and_dataset_name(
            organization=organization,
            dataset_name=PROJECT_DATASET,
        )
        project = project_entity._resource
        project.name = f"Workspace-Demo Projekt {index + 1}"
        project.public_access_level = PublicAccessLevel.RESTRICTED
        project.is_public_approved = False
        project.organization = organization
        project.save()

        event_resource = self._create_event(
            organization=organization,
            dataset_resources=dataset_resources,
            predicates=predicates,
            project=project,
            index=index,
        )
        self._create_actor(organization, event_resource, predicates, index)
        self._create_digital_object(
            organization=organization,
            dataset_resources=dataset_resources,
            predicates=predicates,
            project=project,
            index=index,
        )

        return project

    def _create_event(
        self,
        *,
        organization: Organization,
        dataset_resources: dict[str, Resource],
        predicates: dict[str, Resource],
        project: Resource,
        index: int,
    ) -> Resource:
        event_entity, _ = EntityResource.create_by_organization_and_dataset_name(
            organization=organization,
            dataset_name=EVENT_DATASET,
        )
        event = event_entity._resource
        event.name = f"Demo-Ereignis {index + 1}"
        event.organization = organization
        event.save()

        Triple.objects.get_or_create(
            subject=project,
            predicate=predicates["project_event"],
            object=event,
            defaults={"source": organization, "is_derived": False},
        )

        self._attach_literal(
            subject=event,
            predicate=predicates["event_name"],
            value=f"Showcase {index + 1}",
        )

        today = date.today()
        start_date = today - timedelta(days=random.randint(30, 180))
        end_date = start_date + timedelta(days=random.randint(1, 30))

        self._attach_literal(
            subject=event,
            predicate=predicates["event_start"],
            value=start_date.isoformat(),
        )
        self._attach_literal(
            subject=event,
            predicate=predicates["event_end"],
            value=end_date.isoformat(),
        )

        return event

    def _create_actor(
        self,
        organization: Organization,
        event: Resource,
        predicates: dict[str, Resource],
        index: int,
    ) -> None:
        actor_entity, _ = EntityResource.create_by_organization_and_dataset_name(
            organization=organization,
            dataset_name=ACTOR_DATASET,
        )
        actor = actor_entity._resource
        actor.name = f"Person {index + 1}"
        actor.organization = organization
        actor.save()

        Triple.objects.get_or_create(
            subject=event,
            predicate=predicates["event_actor"],
            object=actor,
            defaults={"source": organization, "is_derived": False},
        )

    def _create_digital_object(
        self,
        *,
        organization: Organization,
        dataset_resources: dict[str, Resource],
        predicates: dict[str, Resource],
        project: Resource,
        index: int,
    ) -> None:
        digital_entity, _ = EntityResource.create_by_organization_and_dataset_name(
            organization=organization,
            dataset_name=DIGITAL_DATASET,
        )
        digital = digital_entity._resource
        digital.name = f"Digitales Objekt {index + 1}"
        digital.organization = organization
        digital.save()

        Triple.objects.get_or_create(
            subject=project,
            predicate=predicates["digital_object"],
            object=digital,
            defaults={"source": organization, "is_derived": False},
        )

    def _attach_literal(self, subject: Resource, predicate: Resource, value: str) -> None:
        literal, _ = Resource.objects.get_or_create(
            resource_type=ResourceType.LITERAL,
            value=value,
        )
        Triple.objects.get_or_create(
            subject=subject,
            predicate=predicate,
            object=literal,
            defaults={"is_derived": False},
        )
