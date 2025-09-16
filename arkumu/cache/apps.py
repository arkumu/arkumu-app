from django.apps import AppConfig


class CacheConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'arkumu.cache'
    verbose_name = 'Centralized Cache Service'
