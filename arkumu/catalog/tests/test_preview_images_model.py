from django.utils import timezone

from arkumu.catalog.models import PreviewImages


def test_preview_images_last_download_uses_callable_default():
    field = PreviewImages._meta.get_field("last_download")

    assert field.default is timezone.now
    assert callable(field.default)
