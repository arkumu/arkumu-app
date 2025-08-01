# Development settings with production AWS config but verbose logging
from .production import *  # noqa: F403

# Override only what's needed for development visibility
DEBUG = True

# Add dev server to allowed hosts
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["arkumu.uni-koeln.de"]) + [
    "dev.arkumu.uni-koeln.de",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
]

# LOGGING
# ------------------------------------------------------------------------------
# Override production's restrictive logging with verbose logging for development
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s",
        },
        "simple": {
            "format": "%(levelname)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.db.backends": {
            "level": "WARNING",
            "handlers": ["console"],
            "propagate": False,
        },
        "arkumu": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "boto3": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "botocore": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "urllib3": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "storages": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.server": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# Email backend for development
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Add dev CSRF trusted origin
CSRF_TRUSTED_ORIGINS = ["https://dev.arkumu.uni-koeln.de"]

# Use the X-Forwarded-Host header from nginx
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Enable SSL redirect for dev server (exposed to internet)
SECURE_SSL_REDIRECT = True

# Keep S3 but without the deprecated buckets
USE_MINIO = False


# Storage settings for development
# Option 1: Use local storage
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {
            "location": str(APPS_DIR / "media"),
        },
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
MEDIA_URL = "/media/"
STATIC_URL = "/static/"

# Option 2: Keep S3 but override bucket name (if you have a dev bucket)
# DJANGO_AWS_STORAGE_BUCKET_NAME = env("DJANGO_AWS_STORAGE_BUCKET_NAME", default="arkumu-dev")

# S3 settings are inherited from production
# Current bucket: my_pony (needs to exist on your S3 server)

# File upload settings for development
# Increase from Django's default of 100 to handle larger batch uploads
DATA_UPLOAD_MAX_NUMBER_FILES = 10000  # Allow up to 10000 files
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB - keep files in memory below this
DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024 * 1024  # 100GB total request size