# Import tasks to register them with Huey (only if available)
try:
    from . import tasks
except ImportError:
    # Huey might not be available in some environments
    pass