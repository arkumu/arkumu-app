# Development settings with production AWS config but verbose logging
from .production import *  # noqa: F403

# Override only what's needed for development visibility
DEBUG = env.bool("DJANGO_DEBUG", default=False)

# Add dev server to allowed hosts
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["arkumu.uni-koeln.de"]) + [
    "dev.arkumu.uni-koeln.de",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
]

# Ensure Huey tasks run asynchronously even if DEBUG is toggled later.
HUEY["immediate"] = False
HUEY["consumer"]["workers"] = env.int("HUEY_DEV_WORKERS", default=2)

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
        "arkumu.security": {
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

# Allow TLS-terminating proxies in remote dev, but stay HTTP-only locally by default
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=False)

# Dev server runs over HTTP, so allow non-secure cookies unless explicitly overridden
SESSION_COOKIE_SECURE = env.bool("DJANGO_SESSION_COOKIE_SECURE", default=True)
CSRF_COOKIE_SECURE = env.bool("DJANGO_CSRF_COOKIE_SECURE", default=True)
CSRF_USE_SESSIONS = env.bool("DJANGO_CSRF_USE_SESSIONS", default=True)

if not SESSION_COOKIE_SECURE:
    SESSION_COOKIE_NAME = env("DJANGO_SESSION_COOKIE_NAME", default="sessionid")

if not CSRF_COOKIE_SECURE:
    CSRF_COOKIE_NAME = env("DJANGO_CSRF_COOKIE_NAME", default="csrftoken")

# Keep S3 but without the deprecated buckets
USE_MINIO = False

# Disable collectfasta integration locally; Whitenoise handles static files
INSTALLED_APPS = [app for app in INSTALLED_APPS if app != "collectfasta"]
COLLECTFASTA_STRATEGY = None


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
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
MEDIA_URL = "/media/"
STATIC_URL = "/static/"

# Allow Whitenoise to serve files collected in DEBUG=False
WHITENOISE_USE_FINDERS = False

# Option 2: Keep S3 but override bucket name (if you have a dev bucket)
# DJANGO_AWS_STORAGE_BUCKET_NAME = env("DJANGO_AWS_STORAGE_BUCKET_NAME", default="arkumu-dev")

# S3 settings are inherited from production
# Current bucket: my_pony (needs to exist on your S3 server)

# File upload settings for development
# Increase from Django's default of 100 to handle larger batch uploads
DATA_UPLOAD_MAX_NUMBER_FILES = 10000  # Allow up to 10000 files
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB - keep files in memory below this
DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024 * 1024  # 100GB total request size
