import pytest

from django.contrib.auth import get_user_model

from arkumu.storage.models.upload_tracking import AsyncUploadFile, AsyncUploadSession
from arkumu.storage.services.async_upload_manager import AsyncUploadManager


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(username='tester', password='secret')


@pytest.fixture
def manager(monkeypatch):
    mgr = AsyncUploadManager()

    def fake_validate(file_name, file_size, content_type, user_id=None):
        return {
            'valid': True,
            'errors': [],
            'warnings': [],
            'should_use_multipart': False,
        }

    def fake_presigned(**kwargs):
        file_name = kwargs.get('file_name')
        path_prefix = kwargs.get('path_prefix')
        key = f"{path_prefix}/{file_name}" if path_prefix else file_name
        return {
            'success': True,
            'url': 'https://example.com/upload',
            'key': key,
            'fields': {},
            'method': 'PUT',
            'type': 'single',
            'max_file_size': kwargs.get('max_file_size'),
        }

    def fake_bucket(org):
        return f"bucket-{org}" if org else None

    monkeypatch.setattr(mgr.upload_service, 'validate_upload_request', fake_validate)
    monkeypatch.setattr(mgr.upload_service, 'generate_presigned_upload_url', fake_presigned)
    monkeypatch.setattr(mgr.bucket_service, 'get_organization_bucket', fake_bucket)

    return mgr


@pytest.mark.django_db
def test_prepare_presigned_uploads_creates_session_and_files(manager, user):
    files = [
        {'name': 'doc.pdf', 'size': 1024, 'type': 'application/pdf'},
    ]

    result = manager.prepare_presigned_uploads(
        user=user,
        files=files,
        folder='data/fuk',
    )

    assert result.success is True
    assert result.uploads
    assert result.session.organization == 'fuk'
    assert result.session.status == 'presigned_generated'
    assert AsyncUploadSession.objects.count() == 1
    assert AsyncUploadFile.objects.count() == 1

    upload_file = AsyncUploadFile.objects.first()
    assert upload_file.presigned_url == 'https://example.com/upload'
    assert upload_file.s3_key.endswith('doc.pdf')


@pytest.mark.django_db
def test_prepare_presigned_uploads_raises_for_invalid_session(manager, user):
    with pytest.raises(ValueError):
        manager.prepare_presigned_uploads(
            user=user,
            files=[{'name': 'doc.pdf', 'size': 1, 'type': 'application/pdf'}],
            folder='data/fuk',
            session_id='00000000-0000-0000-0000-000000000000',
        )


@pytest.mark.django_db
def test_prepare_presigned_uploads_appends_to_existing_session(manager, user):
    session = AsyncUploadSession.objects.create(user=user, total_files=1, organization='fuk', base_folder='data')

    files = [
        {'name': 'img.png', 'size': 2048, 'type': 'image/png', 'relativePath': 'images/img.png'},
    ]

    result = manager.prepare_presigned_uploads(
        user=user,
        files=files,
        folder='data/fuk',
        session_id=str(session.id),
    )

    session.refresh_from_db()
    assert str(result.session.id) == str(session.id)
    assert session.total_files == 1
    assert AsyncUploadFile.objects.filter(session=session).count() == 1
