import pytest
from django.core.management import call_command, CommandError

from arkumu.oaipmh.management.commands import media_links_sync as cmd_module
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
