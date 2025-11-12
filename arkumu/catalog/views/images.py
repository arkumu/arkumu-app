from django.http import HttpResponseNotFound, HttpResponse
from django.utils.html import format_html
from django.views.generic import View
from django.contrib.auth.mixins import LoginRequiredMixin

from arkumu.catalog.models import PreviewImages

import base64


class ImagesView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        query = request.GET.get('query', '').strip()
        img = PreviewImages.objects.filter(path=query).first()

        if not img:
            return HttpResponseNotFound("Image not found")

        # Gib das reine Bild zurück mit korrektem Content-Type
        return HttpResponse(img.img, content_type=img.content_type)


