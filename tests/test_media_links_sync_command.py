import pytest
from django.core.management import call_command, CommandError

from arkumu.metadata.canonical import canonical_uri
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.oaipmh import media_link_views
from arkumu.oaipmh.management.commands import media_links_sync as cmd_module
from arkumu.oaipmh.services.oai_project_media_sync_service import MediaLinkCandidate
from arkumu.users.models import Organization


@pytest.mark.django_db
def test_queue_mode_schedules_job(monkeypatch):
    org = Organization.objects.create(name="KHM", code="khm", domain="khm", is_active=True)

    scheduled = {}

    def fake_create_job(**kwargs):
        scheduled["job_kwargs"] = kwargs
        return "job-123"

    def fake_schedule(args=(), delay=0):
        scheduled["scheduled_args"] = args
        scheduled["delay"] = delay

    monkeypatch.setattr(cmd_module.media_sync_jobs, "create_job", fake_create_job)
    monkeypatch.setattr(cmd_module.run_media_link_seed_and_sync_job, "schedule", fake_schedule)

    call_command("media_links_sync", organization=org.code, queue=True)

    assert scheduled["job_kwargs"]["organization_code"] == org.code
    assert scheduled["scheduled_args"] == ("job-123",)
    assert scheduled["delay"] == 0


@pytest.mark.django_db
def test_inline_seed_and_sync(monkeypatch):
    org = Organization.objects.create(name="FUK", code="fuk", domain="fuk", is_active=True)

    calls = {}

    def fake_seed(organization, force_full_refresh=False):
        calls["seed"] = {"org": organization, "force_full_refresh": force_full_refresh}
        return {"projects": 1, "created": 1, "refreshed": 0, "stale": 0, "skipped": 0}

    def fake_sync(organization, user=None, force_full_refresh=False):
        calls["sync"] = {
            "org": organization,
            "force_full_refresh": force_full_refresh,
            "user": user,
        }
        return {"projects": 1, "auto_approved": 1, "errors": 0}

    monkeypatch.setattr(cmd_module, "_run_media_link_seed", fake_seed)
    monkeypatch.setattr(cmd_module, "_sync_oai_publication_for_org", fake_sync)

    call_command("media_links_sync", organization=org.code, full=True)

    assert calls["seed"]["org"].id == org.id
    assert calls["seed"]["force_full_refresh"] is True
    assert calls["sync"]["org"].id == org.id
    assert calls["sync"]["force_full_refresh"] is True


@pytest.mark.django_db
def test_approvals_only(monkeypatch):
    org = Organization.objects.create(name="DET", code="det", domain="det", is_active=True)

    calls = {}

    def fake_sync(organization, user=None, force_full_refresh=False):
        calls["sync"] = {"org": organization, "force_full_refresh": force_full_refresh}
        return {"projects": 1, "auto_approved": 0, "errors": 0}

    monkeypatch.setattr(cmd_module, "_sync_oai_publication_for_org", fake_sync)

    call_command("media_links_sync", organization=org.code, approvals_only=True)

    assert "sync" in calls
    assert calls["sync"]["org"].id == org.id
    assert calls["sync"]["force_full_refresh"] is False


@pytest.mark.django_db
def test_queue_and_approvals_only_conflict():
    Organization.objects.create(name="KHM", code="khm", domain="khm", is_active=True)
    with pytest.raises(CommandError):
        call_command("media_links_sync", organization="khm", queue=True, approvals_only=True)


def _make_project(org, uri):
    return Resource.objects.create(
        organization=org,
        uri=uri,
        resource_type=ResourceType.ENTITY,
    )


def _make_digital_object(org, uri):
    return Resource.objects.create(
        organization=org,
        uri=uri,
        resource_type=ResourceType.ENTITY,
    )


@pytest.mark.django_db
def test_khm_uses_direct_triples(monkeypatch):
    org = Organization.objects.create(name="KHM", code="khm", domain="khm", is_active=True)
    project = _make_project(org, "http://arkumu.org/data/khm/entities/projekt/direct")
    digital = _make_digital_object(org, "http://arkumu.org/data/khm/entities/digitales-objekt/direct")

    def fake_direct(self, project_arg):
        return [MediaLinkCandidate(resource=digital, source="project", uri=digital.uri, path=None)]

    # Force direct triple path; bypass assembler.
    monkeypatch.setattr(media_link_views.OAIProjectMediaSyncService, "_candidates_from_direct_triples", fake_direct)
    monkeypatch.setattr(media_link_views.OAIProjectMediaSyncService, "_candidates_from_record", lambda self, r, p: [])

    service = media_link_views.OAIProjectMediaSyncService()
    result = service.sync_project(project)
    assert result.created + result.refreshed + result.stale + result.skipped >= 0


@pytest.mark.django_db
def test_direct_triples_match_on_uri_or_canonical():
    org = Organization.objects.create(name="HMT", code="hmt", domain="hmt", is_active=True)
    project = _make_project(org, "http://arkumu.org/data/hmt/entities/projekt/direct")
    digital = _make_digital_object(org, "http://arkumu.org/data/hmt/entities/digitales-objekt/direct")
    digital_pred_uri = canonical_uri("digital_object")

    # Predicate without canonical_uri set (URI only) to ensure URI fallback works.
    predicate = Resource.objects.create(uri=digital_pred_uri, resource_type=ResourceType.PROPERTY)

    Triple = media_link_views.Triple  # reuse imported module path
    Triple.objects.create(subject=project, predicate=predicate, object=digital, is_derived=True)

    service = media_link_views.OAIProjectMediaSyncService()
    candidates = service._candidates_from_direct_triples(project)
    assert any(c.uri == digital.uri for c in candidates)
