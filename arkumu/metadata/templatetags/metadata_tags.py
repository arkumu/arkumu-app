from django import template
from django.core.cache import cache

register = template.Library()

@register.filter
def get_col_header(index, col_headers):
    """Get the column header at the given index."""
    try:
        if col_headers and index < len(col_headers):
            return col_headers[index]
        return f"column_{index}"
    except:
        return f"column_{index}"

@register.filter
def get_row_id(index, row_ids):
    """Get the row ID at the given index."""
    try:
        if row_ids and index < len(row_ids):
            return row_ids[index]
        return f"row_{index}"
    except:
        return f"row_{index}"

@register.simple_tag(takes_context=True)
def get_dataset_columns(context, dataset_name):
    """Get columns for a specific dataset from cache."""
    try:
        # Get organization_id from context (should be available in request)
        request = context.get('request')
        if request and hasattr(request, 'user') and hasattr(request.user, 'organization_id'):
            organization_id = request.user.organization_id
        else:
            # Fallback - try to get from context
            organization_id = context.get('organization_id', 'default')
        
        # Get loaded datasets from cache (it's a list, not a dict)
        loaded_datasets_cache_key = f"loaded_datasets_{organization_id}"
        loaded_datasets = cache.get(loaded_datasets_cache_key, [])
        
        # Find the dataset by name
        for dataset in loaded_datasets:
            if dataset.get('name') == dataset_name:
                columns = dataset.get('columns', [])
                
                # Convert to list of dicts if needed
                column_list = []
                for col in columns:
                    if isinstance(col, dict):
                        column_list.append(col)
                    else:
                        # Handle string column names
                        column_list.append({
                            'name': str(col),
                            'type': None,
                            'sample_values': []
                        })
                return column_list
        return []
    except Exception as e:
        return []

@register.filter
def join_ontology_types(external_ontologies):
    """Join external ontology types with comma separation."""
    try:
        if not external_ontologies:
            return ""
        
        # Handle both list of objects and list of dicts
        types = []
        for ontology in external_ontologies:
            if hasattr(ontology, 'ontology_type'):
                types.append(ontology.ontology_type)
            elif isinstance(ontology, dict) and 'ontology_type' in ontology:
                types.append(ontology['ontology_type'])
        
        return ', '.join(types) if types else ""
    except Exception:
        return ""


@register.filter
def get_item(mapping, key):
    """Safely retrieve a value from a mapping by key inside templates."""
    if isinstance(mapping, dict):
        return mapping.get(key, "")
    try:
        return getattr(mapping, key, "")
    except Exception:
        return ""
