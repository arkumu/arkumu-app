# ruff: noqa
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include
from django.urls import path
from django.views import defaults as default_views
from django.views.generic import TemplateView, RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.authtoken.views import obtain_auth_token
from django.conf.urls.i18n import i18n_patterns

# Import staticfiles_urlpatterns
from django.contrib.staticfiles.urls import staticfiles_urlpatterns

from arkumu.pages.views import ImpressumView
urlpatterns = [
    # ============================================================================
    # BACKEND APPLICATION URLS (with navbar)
    # ============================================================================
    path("", TemplateView.as_view(template_name="pages/home.html"), name="home"),
    path(
        "about/",
        TemplateView.as_view(template_name="pages/about.html"),
        name="about",
    ),
    path("impressum/", ImpressumView.as_view(), name="impressum"),
    
    # ============================================================================
    # DESIGN SHOWCASE URLS (moved to catalog app)
    # ============================================================================
    # These URLs have been moved to arkumu.catalog.urls
    
    # ============================================================================
    # ADMIN & USER MANAGEMENT
    # ============================================================================
    # Django Admin, use {% url 'admin:index' %}
    path(settings.ADMIN_URL, admin.site.urls),
    # User management
    path("users/", include("arkumu.users.urls", namespace="users")),
    path("accounts/", include("allauth.urls")),
    # Override signup to redirect to login
    path("accounts/signup/", RedirectView.as_view(url="/accounts/login/", permanent=True)),
    
    # ============================================================================
    # APPLICATION MODULES
    # ============================================================================
    # Your stuff: custom urls includes go here
    path('metadata/', include(('arkumu.metadata.urls', 'metadata'), namespace='metadata')),
    path('storage/', include('arkumu.storage.urls', namespace='storage')),
    path('importer/', include('arkumu.importer.urls', namespace='importer')),
    path('catalog/', include('arkumu.catalog.urls', namespace='catalog')),
    # OAI-PMH provider (minimal)
    path('oai/', include('arkumu.oaipmh.urls', namespace='oai')),
    # SSE URLs removed - migrated to HTMX polling
    
    # ============================================================================
    # MEDIA & INTERNATIONALIZATION
    # ============================================================================
    # Media files
    *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),    
    # i18n
    path('i18n/', include('django.conf.urls.i18n')),
]

# API URLS
urlpatterns += [
    # API base url
    path("api/", include("config.api_router")),
    # DRF auth token
    path("api/auth-token/", obtain_auth_token),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        path(
            "400/",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        path(
            "403/",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        path(
            "404/",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        path("500/", default_views.server_error),
    ]

    # Add static files serving for development
    urlpatterns += staticfiles_urlpatterns()
    
    # Optionally, if you also serve from STATIC_ROOT in debug (less common for dev)
    # urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

    if "debug_toolbar" in settings.INSTALLED_APPS:
        pass
#        import debug_toolbar
#
#        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
