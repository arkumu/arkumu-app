# ruff: noqa: E501
from .base import *  # noqa: F403
import copy

from .base import INSTALLED_APPS
from .base import LOGGING as BASE_LOGGING
from .base import MIDDLEWARE
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = True
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="DgH5HbQISk2a3BaFBQ7JBujqiZL3oZQhUfsaD6I1AV9jm5SxAuzcwCsPgqLNC9Ra",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#allowed-hosts
ALLOWED_HOSTS = ["localhost", "0.0.0.0", "127.0.0.1", "dev.arkumu.uni-koeln.de"]  # noqa: S104

CSRF_TRUSTED_ORIGINS = [
    "https://dev.arkumu.uni-koeln.de",
]

# CACHES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#caches
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://redis:6379/1"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            # Mimicing memcache behavior.
            # http://niwinz.github.io/django-redis/latest/#_memcached_exceptions_behavior
            "IGNORE_EXCEPTIONS": True,
        },
    }
}

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend",
)

# django-debug-toolbar
# ------------------------------------------------------------------------------
# https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#prerequisites
# INSTALLED_APPS += ["debug_toolbar"]
# https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#middleware
# MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]
# https://django-debug-toolbar.readthedocs.io/en/latest/configuration.html#debug-toolbar-config
DEBUG_TOOLBAR_CONFIG = {
    "DISABLE_PANELS": [
        "debug_toolbar.panels.redirects.RedirectsPanel",
        # Disable profiling panel due to an issue with Python 3.12:
        # https://github.com/jazzband/django-debug-toolbar/issues/1875
        "debug_toolbar.panels.profiling.ProfilingPanel",
    ],
    "SHOW_TEMPLATE_CONTEXT": True,
}
# https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#internal-ips
INTERNAL_IPS = ["127.0.0.1", "10.0.2.2"]
if env("USE_DOCKER") == "yes":
    import socket

    hostname, _, ips = socket.gethostbyname_ex(socket.gethostname())
    INTERNAL_IPS += [".".join(ip.split(".")[:-1] + ["1"]) for ip in ips]

# Logging: default to DEBUG locally but allow overrides via env
LOG_LEVEL = env("ARKUMU_LOG_LEVEL", default="DEBUG").upper()
LOGGING["root"]["level"] = LOG_LEVEL
LOGGING.setdefault("loggers", {})
LOGGING["loggers"].setdefault(
    "arkumu",
    {"handlers": LOGGING["root"]["handlers"], "propagate": False},
)
LOGGING["loggers"]["arkumu"]["level"] = LOG_LEVEL

# django-extensions
# ------------------------------------------------------------------------------
# https://django-extensions.readthedocs.io/en/latest/installation_instructions.html#configuration
INSTALLED_APPS += ["django_extensions"]

# Your stuff...
# ------------------------------------------------------------------------------

# Storage configuration for local development
# Use filesystem storage for both static and media files
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# File upload settings for development
# Support large video files and batch uploads
DATA_UPLOAD_MAX_NUMBER_FILES = 10000  # Allow up to 10000 files
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB - keep files in memory below this
DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024 * 1024  # 100GB total request size

# Cache settings for development
# ------------------------------------------------------------------------------
WARM_CACHE_ON_STARTUP = False
WARM_CROSS_INSTITUTIONAL_CACHE_ON_STARTUP = False
OAI_SKIP_CACHE_WARMUP = True

# Logging overrides for local development
# ------------------------------------------------------------------------------
LOGGING = copy.deepcopy(BASE_LOGGING)
root_log_level = env("DJANGO_ROOT_LOG_LEVEL", default="INFO").upper()
LOGGING["root"]["level"] = root_log_level
LOGGING.setdefault("loggers", {})
LOGGING["loggers"]["arkumu.projects.services.snapshot_service"] = {
    "handlers": ["console"],
    "level": env("ARKUMU_PROJECTS_LOG_LEVEL", default=root_log_level).upper(),
    "propagate": False,
}
