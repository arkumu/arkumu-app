from __future__ import annotations

from pathlib import Path

from django.http import Http404
from django.views.generic import TemplateView
from markdown import markdown


class ImpressumView(TemplateView):
    template_name = "pages/impressum.html"

    def get_context_data(self, **kwargs):  # type: ignore[override]
        context = super().get_context_data(**kwargs)
        context["impressum_html"] = self._load_impressum_html()
        return context

    def _load_impressum_html(self) -> str:
        impressum_path = Path(__file__).resolve().parent / "content" / "impressum.md"
        try:
            raw_text = impressum_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise Http404("Impressum content is temporarily unavailable.") from exc

        return markdown(
            raw_text,
            extensions=[
                "markdown.extensions.extra",
                "markdown.extensions.sane_lists",
                "markdown.extensions.nl2br",
            ],
            output_format="html5",
        )
