import pytest
from rest_framework.test import APIRequestFactory, force_authenticate
from unittest.mock import patch

from arkumu.storage.models.upload_tracking import AsyncUploadSession
from arkumu.storage.services.async_upload_manager import PresignedUploadBatchResult
from arkumu.rest.views.upload_viewsets import UploadViewSet


@pytest.mark.django_db
@patch('arkumu.rest.views.upload_viewsets.AsyncUploadManager')
def test_batch_presigned_urls_uses_async_manager(mock_manager_class, django_user_model):
    user = django_user_model.objects.create_user(username='rest-user', password='pass')
    factory = APIRequestFactory()

    session = AsyncUploadSession.objects.create(user=user, total_files=1, organization='fuk', base_folder='data')
    batch_result = PresignedUploadBatchResult(
        session=session,
        uploads=[{'filename': 'doc.pdf'}],
        errors=[],
        created_files=[],
    )

    mock_manager = mock_manager_class.return_value
    mock_manager.prepare_presigned_uploads.return_value = batch_result

    payload = {
        'files': [{'name': 'doc.pdf', 'size': 100, 'type': 'application/pdf'}],
        'folder': 'data/fuk',
    }

    request = factory.post('/upload/batch-presigned-urls/', payload, format='json')
    force_authenticate(request, user=user)
    view = UploadViewSet.as_view({'post': 'batch_presigned_urls'})
    response = view(request)

    assert response.status_code == 200
    assert response.data['uploads'] == [{'filename': 'doc.pdf'}]
    assert response.data['session_id'] == str(session.id)
    mock_manager.prepare_presigned_uploads.assert_called_once()
