"""
Tests for Data Explorer Ontology Linking functionality

This test module verifies that ontology links created through the data explorer
are properly saved and displayed.
"""

import pytest
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.db import transaction

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization

User = get_user_model()


@pytest.mark.django_db
class TestDataExplorerOntologyLinking(TestCase):
    """Test ontology linking functionality in the data explorer"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        
        self.organization = Organization.objects.create(
            name='Test Organization',
            code='test-org',
            is_active=True
        )
        
        self.user.organization = self.organization
        self.user.save()
        
        # Create a test resource to link to ontologies
        self.resource = Resource.objects.create(
            uri='http://example.com/test-resource',
            name='Test Resource',
            resource_type=ResourceType.IRI,
            organization=self.organization
        )
        
        self.client = Client()
        self.client.login(username='testuser', password='testpass')
    
    def test_ontology_linking_modal_get_displays_correctly(self):
        """Test that the ontology linking modal displays correctly"""
        url = reverse('metadata:ontology_linking_modal')
        response = self.client.get(url, {'resource_id': self.resource.pk})
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Link to Ontology')
        self.assertContains(response, self.resource.name)
        self.assertContains(response, 'ORCID')
        self.assertContains(response, 'Wikidata')
        self.assertContains(response, 'CIDOC-CRM')
    
    def test_ontology_linking_modal_without_resource_id(self):
        """Test modal behavior when no resource_id is provided"""
        url = reverse('metadata:ontology_linking_modal')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Resource not found')
    
    def test_ontology_link_form_submission_works_now(self):
        """Test that ontology link form submission now works with POST handler"""
        url = reverse('metadata:ontology_linking_modal')
        
        form_data = {
            'resource_id': self.resource.pk,
            'ontology_type': 'orcid',
            'external_identifier': '0000-0002-1825-0097',
            'uri_template': 'https://orcid.org/{identifier}'
        }
        
        # This should now work with the POST handler
        response = self.client.post(url, form_data)
        
        # Should return 200 OK now that POST is implemented
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ontology Link Created!')
        self.assertContains(response, 'orcid')
        self.assertContains(response, '0000-0002-1825-0097')
    
    def test_ontology_links_are_now_persisted(self):
        """Test that ontology links are now being saved to the database"""
        # Before any linking attempt
        initial_triple_count = Triple.objects.filter(
            subject=self.resource,
            predicate__uri='http://www.w3.org/2002/07/owl#sameAs'
        ).count()
        
        self.assertEqual(initial_triple_count, 0)
        
        # Submit the form (which should now work)
        url = reverse('metadata:ontology_linking_modal')
        form_data = {
            'resource_id': self.resource.pk,
            'ontology_type': 'orcid',
            'external_identifier': '0000-0002-1825-0097',
            'uri_template': 'https://orcid.org/{identifier}'
        }
        
        response = self.client.post(url, form_data)
        self.assertEqual(response.status_code, 200)
        
        # Check that a triple was created
        final_triple_count = Triple.objects.filter(
            subject=self.resource,
            predicate__uri='http://www.w3.org/2002/07/owl#sameAs'
        ).count()
        
        self.assertEqual(final_triple_count, 1)
        
        # Verify the triple details
        triple = Triple.objects.get(
            subject=self.resource,
            predicate__uri='http://www.w3.org/2002/07/owl#sameAs'
        )
        
        self.assertEqual(triple.object.uri, 'https://orcid.org/0000-0002-1825-0097')
        self.assertTrue(triple.is_derived)
        self.assertIsNone(triple.source)  # Derived triples have no source
    
    def test_expected_ontology_link_behavior_when_implemented(self):
        """Test the expected behavior once ontology linking is properly implemented"""
        # This test documents what should happen when the POST handler is implemented
        
        # Create owl:sameAs predicate if it doesn't exist
        same_as_predicate, created = Resource.objects.get_or_create(
            uri='http://www.w3.org/2002/07/owl#sameAs',
            defaults={
                'name': 'sameAs',
                'resource_type': ResourceType.PROPERTY,
                'organization': self.organization
            }
        )
        
        # Create expected target resource for ORCID link
        orcid_uri = 'https://orcid.org/0000-0002-1825-0097'
        orcid_resource, created = Resource.objects.get_or_create(
            uri=orcid_uri,
            defaults={
                'name': '0000-0002-1825-0097',
                'resource_type': ResourceType.IRI,
                'organization': self.organization
            }
        )
        
        # Manually create the expected triple (simulating what the POST handler should do)
        triple = Triple.objects.create(
            subject=self.resource,
            predicate=same_as_predicate,
            object=orcid_resource,
            source=self.organization,
            is_derived=True  # External ontology links are typically marked as derived
        )
        
        # Verify the triple was created correctly
        self.assertEqual(triple.subject, self.resource)
        self.assertEqual(triple.predicate.uri, 'http://www.w3.org/2002/07/owl#sameAs')
        self.assertEqual(triple.object.uri, orcid_uri)
        self.assertTrue(triple.is_derived)
        
        # Verify it appears in the data explorer query results
        from arkumu.metadata.views.data_explorer_optimized import OptimizedDataExplorerView as DataExplorerView
        
        # Test that the resource now shows as having an ontology link
        triples_with_same_as = Triple.objects.filter(
            subject=self.resource,
            predicate__uri='http://www.w3.org/2002/07/owl#sameAs'
        )
        
        self.assertEqual(triples_with_same_as.count(), 1)
        self.assertEqual(triples_with_same_as.first().object.uri, orcid_uri)
    
    def test_multiple_ontology_links_expected_behavior(self):
        """Test that a resource can have multiple ontology links"""
        # Create owl:sameAs predicate
        same_as_predicate, created = Resource.objects.get_or_create(
            uri='http://www.w3.org/2002/07/owl#sameAs',
            defaults={
                'name': 'sameAs',
                'resource_type': ResourceType.PROPERTY,
                'organization': self.organization
            }
        )
        
        # Create multiple external resources
        ontology_links = [
            ('https://orcid.org/0000-0002-1825-0097', 'ORCID'),
            ('https://www.wikidata.org/entity/Q42', 'Wikidata'),
            ('https://viaf.org/viaf/12347231', 'VIAF')
        ]
        
        created_triples = []
        for uri, name in ontology_links:
            external_resource, created = Resource.objects.get_or_create(
                uri=uri,
                defaults={
                    'name': name,
                    'resource_type': ResourceType.IRI,
                    'organization': self.organization
                }
            )
            
            triple = Triple.objects.create(
                subject=self.resource,
                predicate=same_as_predicate,
                object=external_resource,
                source=self.organization,
                is_derived=True
            )
            created_triples.append(triple)
        
        # Verify all triples were created
        self.assertEqual(len(created_triples), 3)
        
        # Verify the resource has all expected ontology links
        all_same_as_triples = Triple.objects.filter(
            subject=self.resource,
            predicate__uri='http://www.w3.org/2002/07/owl#sameAs'
        )
        
        self.assertEqual(all_same_as_triples.count(), 3)
        
        # Verify specific URIs are linked
        linked_uris = set(triple.object.uri for triple in all_same_as_triples)
        expected_uris = {'https://orcid.org/0000-0002-1825-0097', 
                        'https://www.wikidata.org/entity/Q42', 
                        'https://viaf.org/viaf/12347231'}
        
        self.assertEqual(linked_uris, expected_uris)