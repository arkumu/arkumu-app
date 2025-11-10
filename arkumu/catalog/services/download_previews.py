import logging

from django.utils import timezone

from arkumu.catalog.models import PreviewImages
from arkumu.metadata.models import Resource, Triple
from arkumu.storage.services.base_storage_service import BaseStorageService

logger = logging.getLogger(__name__)

def clean_path(path):
    return path.replace('\\', '/').replace(' ', '_')


class DownloadPreviews:
    preview_pred = Resource.objects.filter(canonical_uri='http://arkumu.org/data/properties/vorschaubild')
    path_pred = Resource.objects.filter(canonical_uri='http://arkumu.org/data/properties/dateipfad')

    storage = BaseStorageService()

    def download_previews(self, force=False):
        paths = self._get_download_paths(force)
        self._download(paths)

    def _get_download_paths(self, force=False):
        preview_objs = [triple.object for triple in Triple.objects.filter(predicate__in=self.preview_pred)]
        paths = self._digital_objs_path(preview_objs)
        if not force:
            paths = self._remove_already_downloaded(paths)

        return paths

    def _remove_already_downloaded(self, paths):
        existing = set(PreviewImages.objects.values_list('bucket', 'path'))
        return [p for p in paths if (p['bucket'], p['path']) not in existing]

    def _digital_objs_path(self, digital_objs):
        return  [{'bucket': path.source.code, 'path': f"data{clean_path(path.object.value)}"}
                       for path in Triple.objects.filter(subject__in=digital_objs, predicate__in=self.path_pred)]

    def _download(self, paths):
        download_count = 0
        for path in paths:
            img = self.storage.get_file_content(path['bucket'], path['path'])
            if img['success']:
                PreviewImages.objects.update_or_create(
                    bucket=path['bucket'],
                    path=path['path'],
                    img=img['content'],
                    content_length=img['metadata']['content_length'],
                    content_type=img['metadata']['content_type'],
                    defaults={'last_download': timezone.now()}
                )
                download_count += 1
        logger.info(f"Downloaded {download_count}/{len(paths)} previews.")
