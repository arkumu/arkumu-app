"""
Tests for RuleMatcher and mapping rules functionality
"""

import pytest
from django.contrib.auth import get_user_model
from arkumu.users.models import Organization
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.harmonization import HarmonizationRule, HarmonizationExecution
from arkumu.metadata.services.harmonization.mapping_rules import RuleMatcher, RuleMatchResult

User = get_user_model()


@pytest.fixture
def test_organization():
    """Create a test organization."""
    return Organization.objects.create(
        name="Test Organization",
        code="test_org",
        domain="test.org"
    )


@pytest.fixture
def test_user():
    """Create a test user."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com"
    )


@pytest.fixture
def test_resources(test_organization):
    """Create test resources with various name patterns."""
    resources = []
    
    property_data = [
        ("artwork_title", "artwork_title"),
        ("painting_title", "painting_title"), 
        ("artist_name", "artist_name"),
        ("creator_info", "creator_info"),
        ("date_created", "date_created"),
        ("description", "description")
    ]
    
    for uri_suffix, name in property_data:
        resource = Resource.objects.create(
            uri=f"http://test.org/{uri_suffix}",
            name=name,
            resource_type=ResourceType.PROPERTY,
            source=test_organization
        )
        resources.append(resource)
    
    return resources


@pytest.fixture
def test_rules(test_organization, test_user):
    """Create test harmonization rules with different patterns."""
    rules = []
    
    # Exact match rule
    rule1 = HarmonizationRule.objects.create(
        source_organization=test_organization,
        source_property_pattern="artist_name",
        catalog_property_uri="http://arkumu.org/data/catalog/catalog/properties/creator",
        catalog_property_label="creator",
        mapping_type="exact",
        priority=10,
        created_by=test_user
    )
    rules.append(rule1)
    
    # Regex pattern rule
    rule2 = HarmonizationRule.objects.create(
        source_organization=test_organization,
        source_property_pattern=".*title.*",
        catalog_property_uri="http://arkumu.org/data/catalog/catalog/properties/title",
        catalog_property_label="title",
        mapping_type="exact",
        priority=5,
        created_by=test_user
    )
    rules.append(rule2)
    
    # Another regex pattern with higher priority
    rule3 = HarmonizationRule.objects.create(
        source_organization=test_organization,
        source_property_pattern="artwork_.*",
        catalog_property_uri="http://arkumu.org/data/catalog/catalog/properties/artwork_property",
        catalog_property_label="artwork_property",
        mapping_type="close",
        priority=15,
        created_by=test_user
    )
    rules.append(rule3)
    
    return rules


@pytest.mark.django_db
class TestRuleMatchResult:
    """Test cases for RuleMatchResult."""
    
    def test_no_conflicts_with_single_rule(self, test_resources, test_rules):
        """Test RuleMatchResult with single matching rule."""
        resource = test_resources[0]  # artwork_title
        matching_rules = [test_rules[1]]  # .*title.* rule
        
        result = RuleMatchResult(resource, matching_rules)
        
        assert not result.has_conflicts
        assert result.selected_rule == matching_rules[0]
    
    def test_conflicts_with_multiple_rules(self, test_resources, test_rules):
        """Test RuleMatchResult with multiple matching rules."""
        resource = test_resources[0]  # artwork_title  
        matching_rules = [test_rules[1], test_rules[2]]  # Both .*title.* and artwork_.* match
        
        result = RuleMatchResult(resource, matching_rules)
        
        assert result.has_conflicts
        assert result.selected_rule is None  # Not auto-selected
    
    def test_resolve_by_priority(self, test_resources, test_rules):
        """Test conflict resolution by priority."""
        resource = test_resources[0]  # artwork_title
        matching_rules = [test_rules[1], test_rules[2]]  # Priority 5 and 15
        
        result = RuleMatchResult(resource, matching_rules)
        resolved_rule = result.resolve_by_priority()
        
        assert resolved_rule == test_rules[2]  # Higher priority (15)
        assert result.selected_rule == test_rules[2]


@pytest.mark.django_db  
class TestRuleMatcher:
    """Test cases for RuleMatcher."""
    
    def test_initialization(self):
        """Test RuleMatcher initialization."""
        matcher = RuleMatcher()
        
        assert matcher._rule_cache == {}
        assert matcher._pattern_cache == {}
    
    def test_find_matching_rules_exact_match(self, test_resources, test_rules):
        """Test finding rules with exact pattern match."""
        matcher = RuleMatcher()
        resource = test_resources[2]  # artist_name
        
        result = matcher.find_matching_rules(resource)
        
        assert len(result.matching_rules) == 1
        assert result.matching_rules[0] == test_rules[0]  # artist_name rule
        assert not result.has_conflicts
    
    def test_find_matching_rules_regex_match(self, test_resources, test_rules):
        """Test finding rules with regex pattern match."""
        matcher = RuleMatcher()
        resource = test_resources[1]  # painting_title
        
        result = matcher.find_matching_rules(resource)
        
        assert len(result.matching_rules) == 1
        assert result.matching_rules[0] == test_rules[1]  # .*title.* rule
        assert not result.has_conflicts
    
    def test_find_matching_rules_multiple_matches(self, test_resources, test_rules):
        """Test finding multiple matching rules (conflict)."""
        matcher = RuleMatcher()
        resource = test_resources[0]  # artwork_title (matches both .*title.* and artwork_.*)
        
        result = matcher.find_matching_rules(resource)
        
        assert len(result.matching_rules) == 2
        assert result.has_conflicts
        assert test_rules[1] in result.matching_rules  # .*title.*
        assert test_rules[2] in result.matching_rules  # artwork_.*
    
    def test_find_matching_rules_no_matches(self, test_resources, test_rules):
        """Test finding no matching rules."""
        matcher = RuleMatcher()
        resource = test_resources[5]  # description (no matching rules)
        
        result = matcher.find_matching_rules(resource)
        
        assert len(result.matching_rules) == 0
        assert not result.has_conflicts
        assert result.selected_rule is None
    
    def test_find_matching_rules_no_source(self):
        """Test matching rules for resource without source organization."""
        matcher = RuleMatcher()
        
        resource = Resource.objects.create(
            uri="http://example.org/test",
            name="test",
            resource_type=ResourceType.PROPERTY,
            source=None
        )
        
        result = matcher.find_matching_rules(resource)
        
        assert len(result.matching_rules) == 0
    
    def test_find_matching_rules_bulk(self, test_resources, test_rules):
        """Test bulk rule matching."""
        matcher = RuleMatcher()
        
        results = matcher.find_matching_rules_bulk(test_resources)
        
        assert len(results) == len(test_resources)
        
        # Check specific results
        artwork_title_result = results[test_resources[0]]  # artwork_title
        assert artwork_title_result.has_conflicts  # Matches multiple rules
        
        artist_name_result = results[test_resources[2]]  # artist_name  
        assert not artist_name_result.has_conflicts  # Matches one rule
        assert len(artist_name_result.matching_rules) == 1
    
    def test_resolve_conflicts_by_priority(self, test_resources, test_rules):
        """Test conflict resolution by priority."""
        matcher = RuleMatcher()
        
        # Get results with conflicts
        results = matcher.find_matching_rules_bulk(test_resources)
        match_results = list(results.values())
        
        resolved_results = matcher.resolve_conflicts_by_priority(match_results)
        
        # Check that conflicts were resolved
        for result in resolved_results:
            if result.has_conflicts:
                assert result.selected_rule is not None
    
    def test_get_conflicting_results(self, test_resources, test_rules):
        """Test filtering for conflicting results."""
        matcher = RuleMatcher()
        
        results = matcher.find_matching_rules_bulk(test_resources)
        match_results = list(results.values())
        
        conflicting_results = matcher.get_conflicting_results(match_results)
        
        # Should have at least one conflict (artwork_title matches multiple rules)
        assert len(conflicting_results) > 0
        
        for result in conflicting_results:
            assert result.has_conflicts
    
    def test_pattern_matches_string_exact(self):
        """Test pattern matching with exact strings."""
        matcher = RuleMatcher()
        
        assert matcher._pattern_matches_string("test", "test") is True
        assert matcher._pattern_matches_string("test", "TEST") is True  # Case insensitive
        assert matcher._pattern_matches_string("test", "other") is False
    
    def test_pattern_matches_string_regex(self):
        """Test pattern matching with regex patterns."""
        matcher = RuleMatcher()
        
        assert matcher._pattern_matches_string(".*title.*", "artwork_title") is True
        assert matcher._pattern_matches_string(".*title.*", "painting_title") is True
        assert matcher._pattern_matches_string(".*title.*", "artist_name") is False
        
        assert matcher._pattern_matches_string("^art.*", "artwork") is True
        assert matcher._pattern_matches_string("^art.*", "smart") is False
    
    def test_validate_rule_pattern_valid_regex(self):
        """Test validation of valid regex patterns."""
        matcher = RuleMatcher()
        
        is_valid, message = matcher.validate_rule_pattern(".*title.*")
        assert is_valid is True
        assert message == ""
        
        is_valid, message = matcher.validate_rule_pattern("^artwork_.*$")
        assert is_valid is True
        assert message == ""
    
    def test_validate_rule_pattern_invalid_regex(self):
        """Test validation of invalid regex patterns."""
        matcher = RuleMatcher()
        
        is_valid, message = matcher.validate_rule_pattern("[unclosed_bracket")
        assert is_valid is True  # Still valid as exact match
        assert "regex error" in message.lower()
    
    def test_validate_rule_pattern_empty(self):
        """Test validation of empty patterns."""
        matcher = RuleMatcher()
        
        is_valid, message = matcher.validate_rule_pattern("")
        assert is_valid is False
        assert "cannot be empty" in message
        
        is_valid, message = matcher.validate_rule_pattern("   ")
        assert is_valid is False
        assert "cannot be empty" in message
    
    def test_test_rule_against_resources(self, test_resources, test_rules):
        """Test testing a rule against resources."""
        matcher = RuleMatcher()
        rule = test_rules[1]  # .*title.* rule
        
        matching_resources = matcher.test_rule_against_resources(rule, test_resources)
        
        # Should match artwork_title and painting_title
        assert len(matching_resources) == 2
        
        resource_names = [r.name for r in matching_resources]
        assert "artwork_title" in resource_names
        assert "painting_title" in resource_names
    
    def test_clear_cache(self):
        """Test cache clearing."""
        matcher = RuleMatcher()
        
        # Populate caches
        matcher._rule_cache[1] = ["test"]
        matcher._pattern_cache["test"] = ("exact", "test")
        
        matcher.clear_cache()
        
        assert matcher._rule_cache == {}
        assert matcher._pattern_cache == {}