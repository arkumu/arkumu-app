# Catalog App Harmonization Integration Plan

## Overview
This document outlines the plan to integrate the harmonization services into the catalog app for unified resource browsing across organizations.

## Current State
- **Harmonization Services**: ✅ Complete
  - `BulkArkumuMappingService`: Maps organization URIs to Arkumu model
  - `CatalogNavigationService`: Queries using harmonization mappings
- **Catalog App**: Existing views need updating to use harmonization

## Integration Goals
1. Replace direct Resource queries with CatalogNavigationService
2. Enable unified browsing across all organizations
3. Maintain performance with optimized queries
4. Support filtering by resource type and organization

## Implementation Steps

### Phase 1: Update Catalog Views (Priority: High)

#### 1.1 Update `CatalogListView` 
**File**: `arkumu/catalog/views_optimized.py`
```python
# Current: Direct Resource queries
# Target: Use CatalogNavigationService.get_all_projects()
```
- Replace direct Resource.objects queries
- Use service methods for type-aware filtering
- Implement proper pagination with prefetched data

#### 1.2 Update `ResourceDetailView`
**File**: `arkumu/catalog/views_optimized.py`
```python
# Current: Basic resource fetch
# Target: Use CatalogNavigationService.get_project_with_full_graph()
```
- Replace with service method for full graph retrieval
- Display related resources hierarchically
- Show harmonized relationships

#### 1.3 Create `CatalogOverviewView`
**New File**: `arkumu/catalog/views_optimized.py`
- Use `get_resource_counts_by_type()` for dashboard
- Show counts per resource type
- Enable drill-down navigation

### Phase 2: Update Templates (Priority: High)

#### 2.1 Catalog List Template
**File**: `arkumu/catalog/templates/catalog/resource_list.html`
- Update to handle prefetched relationships
- Display labels from `label_triples`
- Show related resources inline

#### 2.2 Resource Detail Template  
**File**: `arkumu/catalog/templates/catalog/resource_detail.html`
- Render full resource graph
- Display harmonized properties
- Show relationship hierarchy

#### 2.3 Navigation Components
**File**: `arkumu/catalog/templates/catalog/components/`
- Resource type filter using harmonized counts
- Organization filter
- Search integration

### Phase 3: Search Integration (Priority: Medium)

#### 3.1 Update Search Functionality
**File**: `arkumu/catalog/views_optimized.py`
```python
# Use CatalogNavigationService.search_resources()
```
- Replace existing search with harmonized search
- Support type filtering in search
- Maintain faceted search capabilities

#### 3.2 Search Templates
- Update search results display
- Show resource types clearly
- Highlight matched terms

### Phase 4: URL Routing (Priority: Low)

#### 4.1 Update URL Patterns
**File**: `arkumu/catalog/urls.py`
- Add routes for type-specific views
- Support organization filtering in URLs
- Maintain backward compatibility

### Phase 5: Performance Optimization (Priority: Medium)

#### 5.1 Caching Strategy
- Cache harmonization mappings
- Cache resource counts
- Implement query result caching

#### 5.2 Query Monitoring
- Add query logging
- Monitor prefetch effectiveness
- Optimize based on usage patterns

## Technical Implementation Details

### Service Integration Pattern
```python
# In view
from arkumu.metadata.services.catalog_navigation_service import CatalogNavigationService

class CatalogListView(ListView):
    def get_queryset(self):
        service = CatalogNavigationService(self.request.user)
        return service.get_all_projects(
            include_events=True,
            include_participants=True
        )
```

### Template Usage Pattern
```django
{% for project in projects %}
    <h3>{{ project.uri }}</h3>
    {% for triple in project.label_triples %}
        <p>{{ triple.object.value }}</p>
    {% endfor %}
    {% if project.event_triples %}
        <h4>Events:</h4>
        {% for triple in project.event_triples %}
            <li>{{ triple.object.uri }}</li>
        {% endfor %}
    {% endif %}
{% endfor %}
```

### Migration Strategy
1. Run in parallel initially (feature flag)
2. A/B test performance
3. Gradual rollout by organization
4. Full migration after validation

## Testing Requirements

### Unit Tests
- Test each updated view with harmonized data
- Verify query optimization (assertNumQueries)
- Test access control with different user types

### Integration Tests  
- End-to-end catalog browsing
- Cross-organization resource discovery
- Search functionality with harmonization

### Performance Tests
- Measure query counts before/after
- Load test with large datasets
- Profile memory usage

## Rollout Plan

### Week 1-2: Development
- Update views and templates
- Implement core functionality
- Write tests

### Week 3: Testing & Optimization
- Performance testing
- Query optimization
- Bug fixes

### Week 4: Deployment
- Feature flag deployment
- Gradual rollout
- Monitor performance

## Success Metrics

1. **Query Reduction**: 50% fewer database queries
2. **Load Time**: <2s for catalog pages
3. **Cross-Org Discovery**: Users find 3x more relevant resources
4. **User Satisfaction**: Positive feedback on unified browsing

## Dependencies

- Harmonization rules must be created for all organizations
- Existing catalog data remains unchanged
- User permissions properly configured

## Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Performance degradation | High | Feature flag rollback |
| Missing harmonization rules | Medium | Fallback to direct queries |
| Complex query debugging | Low | Comprehensive logging |

## Next Steps

1. Review plan with team
2. Create feature branch
3. Start with Phase 1 implementation
4. Set up monitoring dashboards