import hashlib
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
        paths = self._dedupe_dicts(self._get_download_paths(force))
        self._download(paths)

    def _dedupe_dicts(self, dicts):
        seen = set()
        result = []
        for d in dicts:
            sig = tuple(sorted(d.items()))
            if sig not in seen:
                seen.add(sig)
                result.append(d)
        return result

    def _get_download_paths(self, force=False):
        preview_objs_other = [triple.object for triple in Triple.objects.filter(predicate__in=self.preview_pred).exclude(source__code='khm')]
        preview_objs_khm = [triple.object for triple in Triple.objects.filter(predicate__in=self.preview_pred, source__code='khm')]
        paths = [*self._digital_objs_path(preview_objs_other), *self._digital_objs_path_khm(preview_objs_khm)]
        if not force:
            paths = self._remove_already_downloaded(paths)

        return paths

    def _remove_already_downloaded(self, paths):
        existing = set(PreviewImages.objects.values_list('bucket', 'path'))
        return [p for p in paths if (p['bucket'], clean_path(p['orig_path'])) not in existing]

    def _digital_objs_path(self, digital_objs):
        return  [{'bucket': path.source.code, 'path': f"data{clean_path(path.object.value)}", 'orig_path': path.object.value}
                       for path in Triple.objects.filter(subject__in=digital_objs, predicate__in=self.path_pred)]

    def _digital_objs_path_khm(self, digital_objs):
        short_paths = [path.object.value for path in Triple.objects.filter(subject__in=digital_objs, predicate__uri='http://arkumu.org/data/khm/properties/dateiname-arkumu-web')]
        long_paths = [path.object.value for path in Triple.objects.filter(subject__in=digital_objs, predicate__in=self.path_pred)]

        return [{'bucket': 'khm', 'path': f"data/{path}", 'orig_path': long_paths[i]} for i, path in enumerate(short_paths)]

    def _download(self, paths):
        download_count = 0
        for path in paths:
            content_type = self.storage.get_file_content_type(path['bucket'], path['path'])
            if content_type['success'] and content_type['content_type'].startswith('image/'):
                img = self.storage.get_file_content(path['bucket'], path['path'])
                if img['success']:
                    # Pre-compute ETag for efficient cache validation
                    etag = hashlib.md5(img['content']).hexdigest()
                    # Normalize path to match ProjectIndex.image format
                    normalized_path = clean_path(path['orig_path'])
                    PreviewImages.objects.update_or_create(
                        bucket=path['bucket'],
                        path=normalized_path,
                        defaults={
                            'img': img['content'],
                            'content_length': img['metadata']['content_length'],
                            'content_type': img['metadata']['content_type'],
                            'etag': etag,
                            'last_download': timezone.now(),
                        }
                    )
                    download_count += 1
        logger.info(f"Downloaded {download_count}/{len(paths)} previews.")
