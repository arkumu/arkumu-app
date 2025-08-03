"""
Signal handlers for user authentication tracking.
"""
import logging
from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


@receiver(user_logged_in)
def track_user_login(sender, request, user, **kwargs):
    """
    Track user login events and update login timestamps.
    
    This signal is fired whenever a user successfully logs in, including:
    - Regular Django authentication
    - Shibboleth authentication (when properly configured)
    - Admin login
    """
    try:
        # Update the user's last_login field (Django handles this automatically)
        # But we can log additional information here
        
        # Determine login method based on request
        login_method = 'unknown'
        user_agent = request.META.get('HTTP_USER_AGENT', 'Unknown')
        ip_address = get_client_ip(request)
        
        # Check if this is a Shibboleth login based on request attributes
        if hasattr(request, 'META') and any(key.startswith('HTTP_') and 'shib' in key.lower() 
                                           for key in request.META.keys()):
            login_method = 'shibboleth'
            # Update Shibboleth login timestamp
            user.last_shibboleth_login = timezone.now()
            user.save(update_fields=['last_shibboleth_login'])
        else:
            login_method = 'regular'
        
        # Log the login event
        logger.info(
            f"User login tracked: {user.username} via {login_method} "
            f"from {ip_address} using {user_agent[:100]}"
        )
        
    except Exception as e:
        # Don't let login tracking errors break the login process
        logger.error(f"Error tracking login for user {user.username}: {str(e)}")


def get_client_ip(request):
    """Extract client IP address from request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


@receiver(post_save, sender=User)
def log_user_changes(sender, instance, created, **kwargs):
    """
    Log important user account changes.
    """
    if created:
        logger.info(f"New user account created: {instance.username} ({instance.email})")
    else:
        # Log significant changes (this runs after save, so we can't compare with original)
        # For more detailed change tracking, consider using django-simple-history
        if instance.is_active:
            logger.debug(f"User account updated: {instance.username}")