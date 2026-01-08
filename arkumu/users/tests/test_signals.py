"""
Tests for user authentication and security audit signals.
"""
import pytest
from unittest.mock import Mock
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed

from arkumu.users.models import User, Organization
from arkumu.users.tests.factories import UserFactory, OrganizationFactory


@pytest.mark.django_db
class TestAuthenticationLogging:
    """Tests for authentication event logging."""

    def test_login_success_logs_event(self, caplog):
        """Test that successful login is logged with user info."""
        user = UserFactory()
        request = Mock()
        request.META = {
            "HTTP_USER_AGENT": "Mozilla/5.0 Test Browser",
            "REMOTE_ADDR": "192.168.1.100",
        }

        with caplog.at_level("INFO", logger="arkumu.security"):
            user_logged_in.send(sender=User, request=request, user=user)

        assert "LOGIN_SUCCESS" in caplog.text
        assert user.username in caplog.text
        assert "192.168.1.100" in caplog.text
        assert "regular" in caplog.text

    def test_login_success_detects_shibboleth(self, caplog):
        """Test that Shibboleth login method is detected."""
        user = UserFactory()
        request = Mock()
        request.META = {
            "HTTP_USER_AGENT": "Mozilla/5.0",
            "REMOTE_ADDR": "10.0.0.1",
            "HTTP_SHIB_IDENTITY_PROVIDER": "https://idp.example.com",
        }

        with caplog.at_level("INFO", logger="arkumu.security"):
            user_logged_in.send(sender=User, request=request, user=user)

        assert "LOGIN_SUCCESS" in caplog.text
        assert "method=shibboleth" in caplog.text

    def test_login_success_with_forwarded_ip(self, caplog):
        """Test that X-Forwarded-For IP is extracted correctly."""
        user = UserFactory()
        request = Mock()
        request.META = {
            "HTTP_USER_AGENT": "Mozilla/5.0",
            "HTTP_X_FORWARDED_FOR": "203.0.113.50, 70.41.3.18",
            "REMOTE_ADDR": "127.0.0.1",
        }

        with caplog.at_level("INFO", logger="arkumu.security"):
            user_logged_in.send(sender=User, request=request, user=user)

        assert "ip=203.0.113.50" in caplog.text

    def test_logout_logs_event(self, caplog):
        """Test that logout is logged."""
        user = UserFactory()
        request = Mock()
        request.META = {"REMOTE_ADDR": "192.168.1.100"}

        with caplog.at_level("INFO", logger="arkumu.security"):
            user_logged_out.send(sender=User, request=request, user=user)

        assert "LOGOUT" in caplog.text
        assert user.username in caplog.text
        assert "192.168.1.100" in caplog.text

    def test_logout_handles_anonymous_user(self, caplog):
        """Test that logout handles None user gracefully."""
        request = Mock()
        request.META = {"REMOTE_ADDR": "192.168.1.100"}

        with caplog.at_level("INFO", logger="arkumu.security"):
            user_logged_out.send(sender=User, request=request, user=None)

        assert "LOGOUT" in caplog.text
        assert "anonymous" in caplog.text

    def test_login_failed_logs_warning(self, caplog):
        """Test that failed login attempts are logged as warnings."""
        request = Mock()
        request.META = {
            "HTTP_USER_AGENT": "Mozilla/5.0 Attacker",
            "REMOTE_ADDR": "10.20.30.40",
        }
        credentials = {"username": "hacker_attempt"}

        with caplog.at_level("WARNING", logger="arkumu.security"):
            user_login_failed.send(
                sender=User, credentials=credentials, request=request
            )

        assert "LOGIN_FAILED" in caplog.text
        assert "hacker_attempt" in caplog.text
        assert "10.20.30.40" in caplog.text


@pytest.mark.django_db
class TestUserModelLogging:
    """Tests for user model change logging."""

    def test_user_creation_logs_event(self, caplog):
        """Test that user creation is logged."""
        with caplog.at_level("INFO", logger="arkumu.security"):
            user = UserFactory(username="newuser", email="new@example.com")

        assert "USER_CREATED" in caplog.text
        assert "newuser" in caplog.text
        assert "new@example.com" in caplog.text

    def test_user_deletion_logs_warning(self, caplog):
        """Test that user deletion is logged as warning."""
        user = UserFactory(username="deleteme", email="delete@example.com")

        with caplog.at_level("WARNING", logger="arkumu.security"):
            user.delete()

        assert "USER_DELETED" in caplog.text
        assert "deleteme" in caplog.text
        assert "delete@example.com" in caplog.text


@pytest.mark.django_db
class TestOrganizationLogging:
    """Tests for organization model change logging."""

    def test_organization_deletion_logs_warning(self, caplog):
        """Test that organization deletion is logged as warning."""
        org = OrganizationFactory(name="Test Org to Delete", code="delete-me-org")

        with caplog.at_level("WARNING", logger="arkumu.security"):
            org.delete()

        assert "ORGANIZATION_DELETED" in caplog.text
        assert "Test Org to Delete" in caplog.text
        assert "delete-me-org" in caplog.text
