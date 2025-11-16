"""
With these settings, tests run faster.
"""

from .base import *  # noqa: F403
from .base import TEMPLATES
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="QWQOCFYVxnPKiAmtS7cVkp4uRUAWNZUTfuVZ2AvXniZ7RlPzZPEJgyOwZcm5oSpd",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#test-runner
TEST_RUNNER = "django.test.runner.DiscoverRunner"

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# DEBUGGING FOR TEMPLATES
# ------------------------------------------------------------------------------
TEMPLATES[0]["OPTIONS"]["debug"] = True  # type: ignore[index]

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = "http://media.testserver"
# DATABASE CONFIGURATION FOR TESTS
# ------------------------------------------------------------------------------
# Override the DATABASE_URL-based configuration from base.py
# Use separate test database to avoid contaminating development data
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "test_arkumu",
        "USER": "debug", 
        "PASSWORD": "debug",
        "HOST": "postgres",
        "PORT": "5432",
        "OPTIONS": {"options": "-c search_path=digikunst,public"},
        "ATOMIC_REQUESTS": True,
    }
}

# Your stuff...
# ------------------------------------------------------------------------------

# Huey Configuration for Tests
# ------------------------------------------------------------------------------
HUEY = {
    'huey_class': 'huey.MemoryHuey',  # Use in-memory Huey for tests
    'name': 'arkumu-test',
    'results': True,
    'store_none': False,
    'immediate': True,  # Run tasks synchronously in tests
    'utc': True,
    'blocking': True,
    'connection': {
        'host': 'localhost',
    }
}
