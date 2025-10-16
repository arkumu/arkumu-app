"""
Tests for BaseCoordinatorMixin

This test suite validates the shared functionality provided by BaseCoordinatorMixin
including organization management, session key generation, and state management.
"""

import pytest
from unittest.mock import Mock, patch
from django.test import RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.middleware.csrf import CsrfViewMiddleware

from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin
from arkumu.users.models import Organization


@pytest.fixture
def mock_request(db):
    """Create a mock request with session support."""
    factory = RequestFactory()
    request = factory.get('/')
    
    # Add session middleware
    middleware = SessionMiddleware(lambda x: None)
    middleware.process_request(request)
    request.session.save()
    
    # Add CSRF middleware
    csrf_middleware = CsrfViewMiddleware(lambda x: None)
    csrf_middleware.process_request(request)
    
    return request


@pytest.fixture
def coordinator():
    """Create a BaseCoordinatorMixin instance for testing."""
    return BaseCoordinatorMixin()


@pytest.fixture
def test_organization(db):
    """Create a test organization."""
    return Organization.objects.create(
        code='TEST_ORG',
        name='Test Organization'
    )


@pytest.fixture
def coordinator_with_custom_type():
    """Create a BaseCoordinatorMixin with custom type for testing."""
    coordinator = BaseCoordinatorMixin()
    # No SESSION_PREFIX since it's removed in the new architecture
    return coordinator


class TestSessionKeyGeneration:
    """Test session key generation with various configurations."""
    
    def test_session_key_with_org(self, coordinator):
        """Test session key generation with organization ID."""
        key = coordinator.get_session_key('workspace_columns', 'test_org')
        assert key == 'workspace_columns_test_org'
    
    def test_session_key_no_org(self, coordinator):
        """Test session key generation without organization ID."""
        key = coordinator.get_session_key('current_organization')
        assert key == 'current_organization'
    
    def test_session_key_without_prefix(self, coordinator):
        """Test shared session key generation."""
        key = coordinator._get_shared_session_key('current_organization')
        assert key == 'current_organization'
    
    def test_session_key_consistency(self, coordinator_with_custom_type):
        """Test session key generation consistency across coordinators."""
        key = coordinator_with_custom_type.get_session_key('workspace_columns', 'test_org')
        assert key == 'workspace_columns_test_org'
    
    def test_session_key_empty_org_id(self, coordinator):
        """Test session key generation with empty organization ID."""
        key = coordinator.get_session_key('workspace_columns', '')
        assert key == 'workspace_columns'
    
    def test_session_key_none_org_id(self, coordinator):
        """Test session key generation with None organization ID."""
        key = coordinator.get_session_key('workspace_columns', None)
        assert key == 'workspace_columns'


@pytest.mark.django_db
class TestOrganizationManagement:
    """Test organization state management functionality."""
    
    def test_set_organization_by_id(self, mock_request, coordinator, test_organization):
        """Test setting organization by numeric ID."""
        org_data = coordinator.set_current_organization(mock_request, str(test_organization.id))
        
        assert org_data is not None
        assert org_data['id'] == test_organization.id
        assert org_data['code'] == test_organization.code
        assert org_data['name'] == test_organization.name
    
    def test_set_organization_by_code(self, mock_request, coordinator, test_organization):
        """Test setting organization by code."""
        org_data = coordinator.set_current_organization(mock_request, test_organization.code)
        
        assert org_data is not None
        assert org_data['id'] == test_organization.id
        assert org_data['code'] == test_organization.code
        assert org_data['name'] == test_organization.name
    
    def test_set_organization_nonexistent(self, mock_request, coordinator):
        """Test setting nonexistent organization."""
        org_data = coordinator.set_current_organization(mock_request, 'NONEXISTENT')
        assert org_data is None
    
    def test_set_organization_invalid_id(self, mock_request, coordinator):
        """Test setting organization with invalid ID."""
        org_data = coordinator.set_current_organization(mock_request, '99999')
        assert org_data is None
    
    def test_get_organization_when_set(self, mock_request, coordinator, test_organization):
        """Test getting organization when one is set."""
        coordinator.set_current_organization(mock_request, test_organization.code)
        
        org_data = coordinator.get_current_organization(mock_request)
        assert org_data is not None
        assert org_data['code'] == test_organization.code
    
    def test_get_organization_when_none_set(self, mock_request, coordinator):
        """Test getting organization when none is set."""
        org_data = coordinator.get_current_organization(mock_request)
        assert org_data is None
    
    def test_clear_organization(self, mock_request, coordinator, test_organization):
        """Test clearing organization from session."""
        # Set organization first
        coordinator.set_current_organization(mock_request, test_organization.code)
        assert coordinator.get_current_organization(mock_request) is not None
        
        # Clear organization
        coordinator.clear_current_organization(mock_request)
        assert coordinator.get_current_organization(mock_request) is None
    
    def test_organization_session_key_consistency(self, mock_request, coordinator_with_custom_type, test_organization):
        """Test that organization is stored with correct shared session key."""
        coordinator_with_custom_type.set_current_organization(mock_request, test_organization.code)
        
        # Check that the session key follows the shared pattern (not prefixed)
        expected_key = 'current_organization'  # Shared key, no prefix
        assert expected_key in mock_request.session
        assert mock_request.session[expected_key]['code'] == test_organization.code


@pytest.mark.django_db
class TestOrganizationContext:
    """Test organization context preparation for templates."""
    
    def test_organization_context_with_org(self, mock_request, coordinator, test_organization):
        """Test organization context when organization is set."""
        coordinator.set_current_organization(mock_request, test_organization.code)
        
        context = coordinator.get_organization_context(mock_request)
        
        assert context['organization_id'] == test_organization.code
        assert context['organization_code'] == test_organization.code
        assert context['organization_name'] == test_organization.name
        assert context['organization_numeric_id'] == test_organization.id
        assert context['has_organization'] is True
    
    def test_organization_context_without_org(self, mock_request, coordinator):
        """Test organization context when no organization is set."""
        context = coordinator.get_organization_context(mock_request)
        
        assert context['organization_id'] is None
        assert context['organization_code'] is None
        assert context['organization_name'] is None
        assert context['organization_numeric_id'] is None
        assert context['has_organization'] is False


@pytest.mark.django_db
class TestTemplateContext:
    """Test base template context generation."""
    
    def test_base_template_context_no_additional(self, mock_request, coordinator, test_organization):
        """Test base template context without additional context."""
        coordinator.set_current_organization(mock_request, test_organization.code)
        
        context = coordinator.get_base_template_context(mock_request)
        
        assert 'organization_id' in context
        assert 'csrf_token' in context
        assert context['organization_id'] == test_organization.code
    
    def test_base_template_context_with_additional(self, mock_request, coordinator, test_organization):
        """Test base template context with additional context."""
        coordinator.set_current_organization(mock_request, test_organization.code)
        
        additional = {'custom_key': 'custom_value', 'another_key': 123}
        context = coordinator.get_base_template_context(mock_request, additional)
        
        assert 'organization_id' in context
        assert 'csrf_token' in context
        assert 'custom_key' in context
        assert 'another_key' in context
        assert context['custom_key'] == 'custom_value'
        assert context['another_key'] == 123


@pytest.mark.django_db
class TestOrganizationValidation:
    """Test organization validation functionality."""
    
    def test_validate_organization_when_present(self, mock_request, coordinator, test_organization):
        """Test organization validation when organization is set."""
        coordinator.set_current_organization(mock_request, test_organization.code)
        
        is_valid, error_message, org_data = coordinator.validate_organization_required(mock_request)
        
        assert is_valid is True
        assert error_message is None
        assert org_data is not None
        assert org_data['code'] == test_organization.code
    
    def test_validate_organization_when_missing(self, mock_request, coordinator):
        """Test organization validation when no organization is set."""
        is_valid, error_message, org_data = coordinator.validate_organization_required(mock_request)
        
        assert is_valid is False
        assert error_message == "No organization selected"
        assert org_data is None


@pytest.mark.django_db
class TestOrganizationChangeHandling:
    """Test organization change workflow."""
    
    def test_handle_organization_change(self, mock_request, coordinator, test_organization):
        """Test basic organization change handling."""
        new_org_data, old_org_data = coordinator.handle_organization_change(mock_request, test_organization.code)
        
        assert new_org_data is not None
        assert new_org_data['code'] == test_organization.code
        assert old_org_data is None  # No previous organization
        
        # Verify organization was actually set
        current_org = coordinator.get_current_organization(mock_request)
        assert current_org['code'] == test_organization.code
    
    def test_handle_organization_change_with_mixin(self, mock_request, coordinator, test_organization):
        """Test organization change handling when OrganizationMixin is available."""
        # Mock the method as if OrganizationMixin is available
        mock_set_last = Mock()
        coordinator.set_last_selected_organization = mock_set_last
        
        coordinator.handle_organization_change(mock_request, test_organization.code)
        
        # Verify the mixin method was called
        mock_set_last.assert_called_once_with(mock_request, test_organization.code)

    def test_clear_state_uses_all_identifier_variants(self, mock_request, test_organization):
        """Ensure organization cleanup runs for both numeric ID and organization code."""

        class RecordingCoordinator(BaseCoordinatorMixin):
            def __init__(self):
                self.cleared = []

            def clear_organization_specific_state(self, request, organization_id):
                self.cleared.append(organization_id)
                super().clear_organization_specific_state(request, organization_id)

        coordinator = RecordingCoordinator()
        coordinator.set_current_organization(mock_request, test_organization.code)

        another_org = Organization.objects.create(
            name="Another Org",
            code="another-org",
        )

        coordinator.set_current_organization(mock_request, another_org.code)

        assert test_organization.id in coordinator.cleared
        assert str(test_organization.id) in coordinator.cleared
        assert test_organization.code in coordinator.cleared


@pytest.mark.django_db
class TestStateManagement:
    """Test general state management functionality."""
    
    def test_clear_organization_specific_state_base(self, mock_request, coordinator):
        """Test base implementation of clearing organization-specific state."""
        # Base implementation should not raise errors
        coordinator.clear_organization_specific_state(mock_request, 'test_org')
        # No assertions needed - just verify it doesn't crash
    
    def test_get_coordinator_debug_info(self, mock_request, coordinator_with_custom_type, test_organization):
        """Test debug information generation."""
        # Set up some state
        coordinator_with_custom_type.set_current_organization(mock_request, test_organization.code)
        mock_request.session['some_data'] = 'test_value'
        mock_request.session['other_data'] = 'other_value'
        
        debug_info = coordinator_with_custom_type.get_coordinator_debug_info(mock_request)
        
        assert debug_info['coordinator_type'] == 'BaseCoordinatorMixin'
        assert debug_info['session_prefix'] is None  # No prefix in single source of truth
        assert debug_info['current_organization'] is not None
        assert debug_info['current_organization']['code'] == test_organization.code
        assert 'coordinator_sessions' in debug_info
        assert len(debug_info['coordinator_sessions']) >= 1  # At least the organization
        assert debug_info['total_session_keys'] > 0
        assert debug_info['coordinator_session_count'] >= 1


@pytest.mark.django_db
class TestSessionSharing:
    """Test that coordinator instances share session state correctly."""
    
    def test_coordinators_share_organization_state(self, mock_request, test_organization):
        """Test that coordinators share the same organization state."""
        coordinator1 = BaseCoordinatorMixin()
        coordinator2 = BaseCoordinatorMixin()
        
        # Set organization in one coordinator
        coordinator1.set_current_organization(mock_request, test_organization.code)
        
        # Both coordinators should see the same organization state
        org1 = coordinator1.get_current_organization(mock_request)
        org2 = coordinator2.get_current_organization(mock_request)
        
        assert org1 is not None
        assert org2 is not None
        assert org1['code'] == test_organization.code
        assert org2['code'] == test_organization.code
        
        # Clear using coordinator1 - this clears the shared organization
        coordinator1.clear_current_organization(mock_request)
        
        # Both coordinators should have no organization (shared state)
        assert coordinator1.get_current_organization(mock_request) is None
        assert coordinator2.get_current_organization(mock_request) is None
    
    def test_session_key_generation_consistency(self, mock_request):
        """Test that session keys are consistent across coordinators."""
        coordinator1 = BaseCoordinatorMixin()
        coordinator2 = BaseCoordinatorMixin()
        
        key1 = coordinator1.get_session_key('workspace_columns', 123)
        key2 = coordinator2.get_session_key('workspace_columns', 123)
        
        # Keys should be identical (single source of truth)
        assert key1 == key2
        assert key1 == 'workspace_columns_123'
        assert key2 == 'workspace_columns_123'


@pytest.mark.django_db
class TestErrorHandling:
    """Test error handling and edge cases."""
    
    def test_set_organization_with_none(self, mock_request, coordinator):
        """Test setting organization with None value."""
        org_data = coordinator.set_current_organization(mock_request, None)
        assert org_data is None
    
    def test_set_organization_with_empty_string(self, mock_request, coordinator):
        """Test setting organization with empty string."""
        org_data = coordinator.set_current_organization(mock_request, '')
        assert org_data is None
    
    def test_session_operations_with_invalid_session(self, coordinator):
        """Test operations with request that has no session."""
        factory = RequestFactory()
        request = factory.get('/')
        # No session middleware added
        
        # Should not crash, but will likely return None or default values
        try:
            org_data = coordinator.get_current_organization(request)
            # Depending on implementation, might be None or raise AttributeError
        except AttributeError:
            # This is acceptable for requests without sessions
            pass
    
    def test_get_organization_context_resilience(self, mock_request, coordinator):
        """Test that organization context is resilient to missing data."""
        # Clear any existing organization
        coordinator.clear_current_organization(mock_request)
        
        context = coordinator.get_organization_context(mock_request)
        
        # Should return valid context even with no organization
        assert isinstance(context, dict)
        assert 'organization_id' in context
        assert 'has_organization' in context
        assert context['has_organization'] is False


@pytest.mark.django_db
class TestIntegrationScenarios:
    """Integration tests simulating real usage scenarios."""
    
    def test_full_organization_workflow(self, mock_request, coordinator, test_organization):
        """Test complete organization management workflow."""
        # 1. Start with no organization
        assert coordinator.get_current_organization(mock_request) is None
        
        # 2. Set organization
        org_data = coordinator.set_current_organization(mock_request, test_organization.code)
        assert org_data is not None
        
        # 3. Verify organization is set
        current_org = coordinator.get_current_organization(mock_request)
        assert current_org['code'] == test_organization.code
        
        # 4. Get template context
        context = coordinator.get_base_template_context(mock_request)
        assert context['organization_id'] == test_organization.code
        
        # 5. Validate organization
        is_valid, error, org = coordinator.validate_organization_required(mock_request)
        assert is_valid is True
        assert error is None
        
        # 6. Handle organization change
        new_org_data, old_org_data = coordinator.handle_organization_change(mock_request, test_organization.id)
        assert new_org_data['id'] == test_organization.id
        assert old_org_data['id'] == test_organization.id  # Same organization, so old and new are the same
        
        # 7. Clear organization
        coordinator.clear_current_organization(mock_request)
        assert coordinator.get_current_organization(mock_request) is None
    
    def test_coordinator_inheritance_simulation(self, mock_request, test_organization):
        """Test how subclasses would use the base coordinator."""
        
        class MockCSVMappingCoordinator(BaseCoordinatorMixin):
            def get_workspace_columns(self, request, org_id):
                key = self.get_session_key('workspace_columns', org_id)
                return request.session.get(key, [])
            
            def set_workspace_columns(self, request, org_id, columns):
                key = self.get_session_key('workspace_columns', org_id)
                request.session[key] = columns
                request.session.modified = True
        
        class MockIngestCoordinator(BaseCoordinatorMixin):
            def get_selected_files(self, request, org_id):
                key = self.get_session_key('selected_files', org_id)
                return request.session.get(key, [])
            
            def set_selected_files(self, request, org_id, files):
                key = self.get_session_key('selected_files', org_id)
                request.session[key] = files
                request.session.modified = True
        
        csv_coord = MockCSVMappingCoordinator()
        ingest_coord = MockIngestCoordinator()
        
        # Both coordinators share organization state
        csv_coord.set_current_organization(mock_request, test_organization.code)
        
        # Both should have organization set (shared state)
        assert csv_coord.get_current_organization(mock_request) is not None
        assert ingest_coord.get_current_organization(mock_request) is not None
        
        # Each coordinator can store their own data using different base keys
        csv_coord.set_workspace_columns(mock_request, test_organization.code, ['col1', 'col2'])
        ingest_coord.set_selected_files(mock_request, test_organization.code, ['file1.csv', 'file2.csv'])
        
        # Data should be accessible from their respective coordinators
        assert csv_coord.get_workspace_columns(mock_request, test_organization.code) == ['col1', 'col2']
        assert ingest_coord.get_selected_files(mock_request, test_organization.code) == ['file1.csv', 'file2.csv']
        
        # Check that different coordinators can access each other's data (shared session)
        csv_key = csv_coord.get_session_key('workspace_columns', test_organization.code)
        ingest_key = ingest_coord.get_session_key('selected_files', test_organization.code)
        
        assert csv_key == 'workspace_columns_TEST_ORG'
        assert ingest_key == 'selected_files_TEST_ORG'
        
        # Both coordinators should have no session prefix
        csv_debug = csv_coord.get_coordinator_debug_info(mock_request)
        ingest_debug = ingest_coord.get_coordinator_debug_info(mock_request)
        
        assert csv_debug['session_prefix'] is None
        assert ingest_debug['session_prefix'] is None
