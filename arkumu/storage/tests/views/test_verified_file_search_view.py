from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.storage.models import S3FileObject
from arkumu.users.models import Organization


class VerifiedFileSearchViewTests(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(code="demo", name="Demo Organization")
        self.user = get_user_model().objects.create_user(
            username="demo-user",
            email="demo@example.com",
            password="safe-password",
        )
        self.user.organization = self.organization
        self.user.save(update_fields=["organization"])

        self.resource = Resource.objects.create(
            uri="http://example.org/resource/digital-object-1",
            name="Digitales Objekt 1",
            organization=self.organization,
            resource_type=ResourceType.IRI,
        )

        S3FileObject.objects.create(
            file_name="vorschaubild.jpg",
            s3_key="media/vorschaubild.jpg",
            organization=self.organization.code.lower(),
            status="verified",
            related_resource=self.resource,
        )

        # Non-matching rows that should not appear in search results
        other_org = Organization.objects.create(code="other", name="Other Org")
        other_resource = Resource.objects.create(
            uri="http://example.org/resource/other",
            name="Anderes Objekt",
            organization=other_org,
            resource_type=ResourceType.IRI,
        )
        S3FileObject.objects.create(
            file_name="andere-datei.jpg",
            s3_key="media/andere-datei.jpg",
            organization=other_org.code.lower(),
            status="verified",
            related_resource=other_resource,
        )
        S3FileObject.objects.create(
            file_name="unverified.jpg",
            s3_key="media/unverified.jpg",
            organization=self.organization.code.lower(),
            status="completed",
            related_resource=self.resource,
        )

    def test_returns_verified_files_for_user_organization(self) -> None:
        self.client.force_login(self.user)
        url = reverse("storage:verified_file_search")
        response = self.client.get(
            url,
            {
                "q": "vor",
                "input_id": "id_vorschaubild_uri",
                "selected": "",
                "organization": self.organization.code,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "vorschaubild.jpg")
        self.assertNotContains(response, "andere-datei.jpg")
        self.assertNotContains(response, "unverified.jpg")

    def test_returns_error_when_user_has_no_organization(self) -> None:
        user_without_org = get_user_model().objects.create_user(
            username="no-org",
            email="noorg@example.com",
            password="password123",
        )
        self.client.force_login(user_without_org)
        url = reverse("storage:verified_file_search")
        response = self.client.get(
            url,
            {
                "q": "vor",
                "input_id": "id_vorschaubild_uri",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Keine Organisation")
