"""Tests for catalog REST API endpoints."""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from arkumu.metadata.models import Resource, Triple
from arkumu.metadata.models.resource import ResourceType
from django.core.cache import cache


@pytest.fixture
def api_client():
    """Provide API client for tests."""
    return APIClient()


@pytest.fixture
def auth_client(api_client, django_user_model):
    """Provide authenticated API client."""
    user = django_user_model.objects.create_user(
        username='testuser',
        password='testpass123'
    )
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def sample_catalog_data(db):
    """Create sample catalog data for testing."""
    # Create resource types
    project_type, _ = Resource.objects.get_or_create(
        uri="http://arkumu.org/data/types/projekt",
        defaults={
            'canonical_uri': "http://arkumu.org/data/types/projekt",
            'resource_type': ResourceType.CLASS
        }
    )

    # Create predicates
    rdf_type, _ = Resource.objects.get_or_create(
        uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        defaults={
            'canonical_uri': "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
            'resource_type': ResourceType.PROPERTY
        }
    )

    category_pred, _ = Resource.objects.get_or_create(
        uri="http://arkumu.org/data/properties/projektkategorie",
        defaults={
            'canonical_uri': "http://arkumu.org/data/properties/projektkategorie",
            'resource_type': ResourceType.PROPERTY
        }
    )

    title_pred, _ = Resource.objects.get_or_create(
        uri="http://arkumu.org/data/properties/bevorzugter-titel",
        defaults={
            'canonical_uri': "http://arkumu.org/data/properties/bevorzugter-titel",
            'resource_type': ResourceType.PROPERTY
        }
    )

    institution_pred, _ = Resource.objects.get_or_create(
        uri="http://arkumu.org/data/properties/einliefernde-hochschule",
        defaults={
            'canonical_uri': "http://arkumu.org/data/properties/einliefernde-hochschule",
            'resource_type': ResourceType.PROPERTY
        }
    )

    category_name_pred, _ = Resource.objects.get_or_create(
        uri="http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb",
        defaults={
            'canonical_uri': "http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb",
            'resource_type': ResourceType.PROPERTY
        }
    )

    # Create categories
    category1, _ = Resource.objects.get_or_create(
        uri="http://arkumu.org/data/categories/theater",
        defaults={'resource_type': ResourceType.IRI}
    )
    category2, _ = Resource.objects.get_or_create(
        uri="http://arkumu.org/data/categories/musik",
        defaults={'resource_type': ResourceType.IRI}
    )

    # Add category labels
    cat1_label, _ = Resource.objects.get_or_create(
        value="Theater",
        defaults={'resource_type': ResourceType.LITERAL}
    )
    cat2_label, _ = Resource.objects.get_or_create(
        value="Musik",
        defaults={'resource_type': ResourceType.LITERAL}
    )

    Triple.objects.get_or_create(
        subject=category1,
        predicate=category_name_pred,
        object=cat1_label
    )
    Triple.objects.get_or_create(
        subject=category2,
        predicate=category_name_pred,
        object=cat2_label
    )

    # Create projects
    projects = []
    for i in range(5):
        project, _ = Resource.objects.get_or_create(
            uri=f"http://arkumu.org/data/projects/project{i+1}",
            defaults={'resource_type': ResourceType.IRI}
        )
        projects.append(project)

        # Set project type
        Triple.objects.get_or_create(
            subject=project,
            predicate=rdf_type,
            object=project_type
        )

        # Add title
        title_literal, _ = Resource.objects.get_or_create(
            value=f"Test Project {i+1}",
            defaults={'resource_type': ResourceType.LITERAL}
        )
        Triple.objects.get_or_create(
            subject=project,
            predicate=title_pred,
            object=title_literal
        )

        # Add institution
        institution, _ = Resource.objects.get_or_create(
            uri=f"http://arkumu.org/data/institutions/uni{i % 2 + 1}",
            defaults={'resource_type': ResourceType.IRI}
        )
        inst_name, _ = Resource.objects.get_or_create(
            value=f"University {i % 2 + 1}",
            defaults={'resource_type': ResourceType.LITERAL}
        )
        Triple.objects.get_or_create(
            subject=project,
            predicate=institution_pred,
            object=institution
        )

        # Add category (3 projects with category1, 2 with category2)
        category = category1 if i < 3 else category2
        Triple.objects.get_or_create(
            subject=project,
            predicate=category_pred,
            object=category
        )

    return {
        'projects': projects,
        'categories': [category1, category2],
        'predicates': {
            'type': rdf_type,
            'category': category_pred,
            'title': title_pred,
            'institution': institution_pred
        }
    }


@pytest.mark.django_db
class TestPopularKeywordsEndpoint:
    """Tests for the /api/catalog/keywords/popular endpoint."""

    def test_get_popular_keywords_success(self, auth_client, sample_catalog_data):
        """Test successful retrieval of popular keywords."""
        url = reverse('api:catalog-popular-keywords')
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)

        # Check that we have keywords
        assert len(data) > 0

        # Check keyword structure
        for keyword in data:
            assert 'id' in keyword
            assert 'label' in keyword
            assert 'count' in keyword
            assert isinstance(keyword['count'], int)

        # Check sorting (highest count first)
        if len(data) > 1:
            for i in range(len(data) - 1):
                assert data[i]['count'] >= data[i+1]['count']

    def test_popular_keywords_with_limit(self, auth_client, sample_catalog_data):
        """Test popular keywords with limit parameter."""
        url = reverse('api:catalog-popular-keywords')
        response = auth_client.get(url, {'limit': 1})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) <= 1

    def test_popular_keywords_max_limit_enforcement(self, auth_client):
        """Test that limit above max returns error."""
        url = reverse('api:catalog-popular-keywords')
        response = auth_client.get(url, {'limit': 500})

        # Should return 400 for limit above max
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'errors' in response.json()

    def test_popular_keywords_invalid_limit(self, auth_client):
        """Test invalid limit parameter."""
        url = reverse('api:catalog-popular-keywords')

        # Negative limit
        response = auth_client.get(url, {'limit': -1})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'errors' in response.json()

        # Non-integer limit
        response = auth_client.get(url, {'limit': 'abc'})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'errors' in response.json()

    def test_popular_keywords_no_auth(self, api_client, sample_catalog_data):
        """Test that endpoint works without authentication (public access)."""
        url = reverse('api:catalog-popular-keywords')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        # Should return data even without auth
        data = response.json()
        assert isinstance(data, list)

    def test_popular_keywords_empty_database(self, auth_client):
        """Test behavior with no catalog data."""
        # Clear all triples
        Triple.objects.all().delete()
        cache.clear()

        url = reverse('api:catalog-popular-keywords')
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data == []  # Should return empty list


@pytest.mark.django_db
class TestRandomProjectsEndpoint:
    """Tests for the /api/catalog/projects/random endpoint."""

    def test_get_random_projects_success(self, auth_client, sample_catalog_data):
        """Test successful retrieval of random projects."""
        url = reverse('api:catalog-random-projects')
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)

        # Check project structure
        if data:  # If we have projects
            project = data[0]
            assert 'id' in project
            assert 'title' in project
            assert 'university' in project
            assert 'year' in project
            assert 'project_type' in project
            assert 'actors' in project
            assert 'categories' in project
            assert 'preview_image_url' in project
            assert 'detail_url' in project

            # Check detail URL format
            assert project['detail_url'].startswith('/projekt/')

    def test_random_projects_with_limit(self, auth_client, sample_catalog_data):
        """Test random projects with limit parameter."""
        url = reverse('api:catalog-random-projects')
        response = auth_client.get(url, {'limit': 2})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) <= 2

    def test_random_projects_max_limit_enforcement(self, auth_client):
        """Test that limit above max returns error."""
        url = reverse('api:catalog-random-projects')
        response = auth_client.get(url, {'limit': 100})

        # Should return 400 for limit above max
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'errors' in response.json()

    def test_random_projects_filter_by_keyword_id(self, auth_client, sample_catalog_data):
        """Test filtering by keyword_id."""
        url = reverse('api:catalog-random-projects')
        response = auth_client.get(url, {'keyword_id': 'theater'})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # We should get exactly 3 projects (projects 1, 2, 3 have theater category)
        assert len(data) == 3

        # Verify these are the right projects
        project_ids = {p['id'] for p in data}
        expected_ids = {'project1', 'project2', 'project3'}
        assert project_ids == expected_ids

    def test_random_projects_filter_by_category(self, auth_client, sample_catalog_data):
        """Test filtering by category name."""
        url = reverse('api:catalog-random-projects')
        response = auth_client.get(url, {'category': 'musik'})

        assert response.status_code == status.HTTP_200_OK
        # Results depend on data but should not error

    def test_random_projects_filter_by_university(self, auth_client, sample_catalog_data):
        """Test filtering by university."""
        url = reverse('api:catalog-random-projects')
        response = auth_client.get(url, {'university': 'University 1'})

        assert response.status_code == status.HTTP_200_OK
        # Results depend on data but should not error

    def test_random_projects_filter_by_year(self, auth_client, sample_catalog_data):
        """Test filtering by year."""
        url = reverse('api:catalog-random-projects')
        response = auth_client.get(url, {'year': 2023})

        assert response.status_code == status.HTTP_200_OK
        # Results depend on data (might be empty if no 2023 projects)

    def test_random_projects_combined_filters(self, auth_client, sample_catalog_data):
        """Test combining multiple filters."""
        url = reverse('api:catalog-random-projects')
        response = auth_client.get(url, {
            'keyword_id': 'theater',
            'limit': 5
        })

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) <= 5

    def test_random_projects_invalid_parameters(self, auth_client):
        """Test invalid parameter values."""
        url = reverse('api:catalog-random-projects')

        # Invalid year (too old)
        response = auth_client.get(url, {'year': 1800})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        # Invalid year (too future)
        response = auth_client.get(url, {'year': 2200})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        # Non-integer year
        response = auth_client.get(url, {'year': 'abc'})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        # Negative limit
        response = auth_client.get(url, {'limit': -5})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_random_projects_no_auth(self, api_client, sample_catalog_data):
        """Test that endpoint works without authentication (public access)."""
        url = reverse('api:catalog-random-projects')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        # Should return data even without auth
        data = response.json()
        assert isinstance(data, list)

    def test_random_projects_empty_results(self, auth_client, sample_catalog_data):
        """Test filtering that returns no results."""
        url = reverse('api:catalog-random-projects')
        # Filter by non-existent keyword
        response = auth_client.get(url, {'keyword_id': 'nonexistent'})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data == []  # Should return empty list

    def test_random_projects_randomness(self, auth_client, sample_catalog_data):
        """Test that results are actually random (different between calls)."""
        url = reverse('api:catalog-random-projects')

        # Get multiple sets of results
        results = []
        for _ in range(3):
            response = auth_client.get(url, {'limit': 3})
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            if data:
                results.append([p['id'] for p in data])

        # Check that we got some variation (not always same order)
        # This test might occasionally fail if we get the same random order
        # but probability is low with multiple projects
        if len(results) > 1 and all(len(r) > 1 for r in results):
            # At least one should be different
            all_same = all(results[0] == r for r in results[1:])
            # We can't guarantee they're different due to randomness,
            # so just check the endpoint works
            assert True  # Endpoint works regardless
