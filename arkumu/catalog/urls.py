from django.urls import path
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required

app_name = 'catalog'

urlpatterns = [
    # Design showcase pages with local catalog templates - login required
    path('design/', login_required(TemplateView.as_view(template_name="catalog/design.html")), name='design'),
    path('components/', login_required(TemplateView.as_view(template_name="catalog/components.html")), name='components'),
    path('documentation/', login_required(TemplateView.as_view(template_name="catalog/documentation.html")), name='documentation'),
    path('projekt/', login_required(TemplateView.as_view(template_name="catalog/projekt.html")), name='projekt'),
]