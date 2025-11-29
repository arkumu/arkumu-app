import hashlib

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
        img = PreviewImages.objects.filter(path=query).first()

        if not img:
            return HttpResponseNotFound("Image not found")

        # Generate ETag from content hash
        etag = hashlib.md5(img.img).hexdigest()

        # Check If-None-Match header (browser cache validation)
        if request.META.get('HTTP_IF_NONE_MATCH') == etag:
            return HttpResponse(status=304)  # Not Modified

        response = HttpResponse(img.img, content_type=img.content_type)
        response['Content-Length'] = img.content_length
        response['Cache-Control'] = f'private, max-age={self.CACHE_MAX_AGE}'
        response['ETag'] = etag
        return response


