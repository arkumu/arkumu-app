from django.http import HttpResponseNotFound, HttpResponse
from django.views.generic import View
from django.contrib.auth.mixins import LoginRequiredMixin

from arkumu.catalog.models import PreviewImages


class ImagesView(LoginRequiredMixin, View):
    """Serve preview images with browser caching."""

    # Cache for 24 hours (browser won't hit DB again)
    CACHE_MAX_AGE = 86400

    def get(self, request, *args, **kwargs):
        query = request.GET.get('query', '').strip()

        # First: lightweight query for cache validation (no blob)
        meta = PreviewImages.objects.filter(path=query).values(
            'id', 'etag', 'content_type', 'content_length'
        ).first()

        if not meta:
            return HttpResponseNotFound("Image not found")

        etag = meta['etag']

        # Check If-None-Match header (browser cache validation)
        if etag and request.META.get('HTTP_IF_NONE_MATCH') == etag:
            return HttpResponse(status=304)  # Not Modified

        # Cache miss: fetch the blob
        img = PreviewImages.objects.filter(pk=meta['id']).values_list('img', flat=True).first()

        response = HttpResponse(img, content_type=meta['content_type'])
        response['Content-Length'] = meta['content_length']
        response['Cache-Control'] = f'private, max-age={self.CACHE_MAX_AGE}'
        if etag:
            response['ETag'] = etag
        return response


