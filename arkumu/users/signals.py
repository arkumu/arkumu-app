"""
Signal handlers for user authentication tracking.

Handles:
- Authentication event logging (login, logout, failed login)
- User account creation/deletion logging
"""
import logging
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.contrib.auth import get_user_model

logger = logging.getLogger("arkumu.security")
User = get_user_model()


def get_client_ip(request):
    """Extract client IP address from request."""
    if request is None:
        return "unknown"
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR", "unknown")
    return ip


@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    """Log successful user login events."""
    try:
        ip_address = get_client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "unknown")[:200] if request else "unknown"

        # Detect login method
        login_method = "unknown"
        if request and hasattr(request, "META"):
            if any(key.startswith("HTTP_") and "shib" in key.lower() for key in request.META.keys()):
                login_method = "shibboleth"
                # Update Shibboleth login timestamp if field exists
                if hasattr(user, "last_shibboleth_login"):
                    user.last_shibboleth_login = timezone.now()
                    user.save(update_fields=["last_shibboleth_login"])
            else:
                login_method = "regular"

        logger.info(
            f"LOGIN_SUCCESS: user={user.username} ip={ip_address} method={login_method} "
            f"user_agent={user_agent}"
        )

    except Exception as e:
        # Don't let login tracking errors break the login process
        logger.error(f"Error tracking login for user {user.username}: {str(e)}")


@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    """Log user logout events."""
    ip_address = get_client_ip(request)
    username = user.username if user else "anonymous"
    logger.info(f"LOGOUT: user={username} ip={ip_address}")


@receiver(user_login_failed)
def log_login_failed(sender, credentials, request, **kwargs):
    """Log failed login attempts."""
    ip_address = get_client_ip(request)
    username = credentials.get("username", "unknown")
    user_agent = request.META.get("HTTP_USER_AGENT", "unknown")[:200] if request else "unknown"
    logger.warning(
        f"LOGIN_FAILED: attempted_user={username} ip={ip_address} user_agent={user_agent}"
    )


@receiver(post_save, sender=User)
def log_user_changes(sender, instance, created, **kwargs):
    """Log user account creation."""
    if created:
        logger.info(f"USER_CREATED: username={instance.username} email={instance.email}")


@receiver(post_delete, sender=User)
def log_user_deletion(sender, instance, **kwargs):
    """Log user account deletion."""
    logger.warning(f"USER_DELETED: username={instance.username} email={instance.email}")


# Import Organization for delete logging
from .models import Organization


@receiver(post_delete, sender=Organization)
def log_organization_deletion(sender, instance, **kwargs):
    """Log organization deletion."""
    logger.warning(f"ORGANIZATION_DELETED: name={instance.name} code={instance.code}")