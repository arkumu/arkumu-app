"""
Bulk Arkumu Mapping Views

Views for creating bulk mappings from organization-specific ontologies to the Arkumu model.
"""

from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.generic import FormView, TemplateView, View
from django.urls import reverse_lazy
from django import forms
from django.http import HttpResponse
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator

from arkumu.users.mixins import GeneralLoginRequiredMixin
from arkumu.users.models import Organization
from arkumu.metadata.services.bulk_arkumu_mapping_service import BulkArkumuMappingService
from arkumu.metadata.models.harmonization import HarmonizationExecution


class BulkArkumuMappingForm(forms.Form):
    """Form for bulk Arkumu mapping configuration."""
    
    organizations = forms.ModelMultipleChoiceField(
        queryset=Organization.objects.filter(is_active=True),
        widget=forms.CheckboxSelectMultiple,
        help_text="Select one or more organizations to map to the Arkumu model"
    )
    
    mapping_type = forms.ChoiceField(
        choices=[
            ('exact', 'Exact Match'),
            ('close', 'Close Match'),
            ('broad', 'Broader Match'),
            ('narrow', 'Narrower Match')
        ],
        initial='exact',
        widget=forms.HiddenInput(),  # Hide this field
        help_text="Type of semantic mapping between organization ontology and Arkumu model"
    )
    
    priority = forms.IntegerField(
        initial=1,
        min_value=0,
        max_value=100,
        widget=forms.HiddenInput(),  # Hide this field
        help_text="Priority for conflict resolution (higher values win)"
    )
    
    preview_only = forms.BooleanField(
        required=False,
        initial=False,
        help_text="Only preview mappings without creating them"
    )


class BulkArkumuMappingView(GeneralLoginRequiredMixin, FormView):
    """Main view for bulk Arkumu mapping with HTMX support."""
    
    template_name = 'metadata/bulk_arkumu_mapping/main.html'
    form_class = BulkArkumuMappingForm
    success_url = reverse_lazy('metadata:bulk_arkumu_mapping')
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service = BulkArkumuMappingService()
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get recent executions for display
        context['recent_executions'] = HarmonizationExecution.objects.filter(
            execution_mode='manual',
            created_by=self.request.user
        ).order_by('-created_at')[:10]
        
        # Get organization statistics with mapping counts
        organizations = Organization.objects.filter(is_active=True)
        context['organization_stats'] = {}
        
        for org in organizations:
            # Get preview data for this single organization to show counts
            try:
                preview_data = self.service.preview_bulk_mapping([org.code])
                org_data = preview_data.get(org.code, {})
                
                context['organization_stats'][org.code] = {
                    'name': org.name,
                    'total_count': org_data.get('total_count', 0),
                    'class_count': org_data.get('class_count', 0),
                    'property_count': org_data.get('property_count', 0),
                    'has_mappable_resources': org_data.get('total_count', 0) > 0
                }
            except Exception:
                # Fallback if there's an error getting preview data
                context['organization_stats'][org.code] = {
                    'name': org.name,
                    'total_count': 0,
                    'class_count': 0,
                    'property_count': 0,
                    'has_mappable_resources': False
                }
        
        return context
    
    def post(self, request, *args, **kwargs):
        """Handle both HTMX preview requests and regular form submission."""
        form = self.get_form()
        
        # Handle HTMX preview request
        if request.headers.get('HX-Request') and 'preview' in request.POST:
            return self._handle_htmx_preview(form)
        
        # Handle regular form submission
        if form.is_valid():
            return self.form_valid(form)
        else:
            return self.form_invalid(form)
    
    def _handle_htmx_preview(self, form):
        """Handle HTMX preview request and return HTML fragment."""
        if not form.is_valid():
            return HttpResponse(
                '<div class="alert alert-danger">Please correct form errors and try again.</div>'
            )
        
        organizations = form.cleaned_data['organizations']
        organization_codes = [org.code for org in organizations]
        
        # Validate organization codes
        valid_codes, invalid_codes = self.service.validate_organization_codes(organization_codes)
        
        if invalid_codes:
            return HttpResponse(
                f'<div class="alert alert-danger">Invalid organization codes: {", ".join(invalid_codes)}</div>'
            )
        
        if not valid_codes:
            return HttpResponse(
                '<div class="alert alert-warning">No valid organizations selected.</div>'
            )
        
        try:
            # Generate preview
            preview = self.service.preview_bulk_mapping(valid_codes)
            
            # Cache the preview data for fast sorting
            for org_code, org_data in preview.items():
                session_key = f'bulk_mapping_preview_{org_code}'
                self.request.session[session_key] = org_data.get('mappings', [])
            
            # Get sort states for each organization
            sort_states = {}
            for org_code in preview.keys():
                sort_session_key = f'bulk_mapping_sort_{org_code}'
                sort_states[org_code] = self.request.session.get(sort_session_key, {'sort': None, 'order': 'asc'})
            
            context = {
                'preview': preview,
                'total_new_mappings': sum(data['total_count'] for data in preview.values()),
                'sort_states': sort_states
            }
            
            return render(self.request, 'metadata/bulk_arkumu_mapping/preview_fragment.html', context)
            
        except Exception as e:
            return HttpResponse(
                f'<div class="alert alert-danger">Error generating preview: {str(e)}</div>'
            )

    def form_valid(self, form):
        """Handle regular form submission."""
        organizations = form.cleaned_data['organizations']
        organization_codes = [org.code for org in organizations]
        mapping_type = form.cleaned_data['mapping_type']
        priority = form.cleaned_data['priority']
        preview_only = form.cleaned_data['preview_only']
        
        # Validate organization codes
        valid_codes, invalid_codes = self.service.validate_organization_codes(organization_codes)
        
        if invalid_codes:
            messages.error(
                self.request,
                f"Invalid organization codes: {', '.join(invalid_codes)}"
            )
            return self.form_invalid(form)
        
        if preview_only:
            # Generate preview and redirect to preview page
            preview = self.service.preview_bulk_mapping(valid_codes)
            
            # Store preview in session for display
            self.request.session['bulk_mapping_preview'] = {
                'organization_codes': valid_codes,
                'mapping_type': mapping_type,
                'priority': priority,
                'preview': preview
            }
            
            messages.info(
                self.request, 
                f"Preview generated for {len(valid_codes)} organizations"
            )
            
            return redirect('metadata:bulk_arkumu_mapping_preview')
        
        else:
            # Create actual mappings
            try:
                execution = self.service.create_harmonization_rules(
                    organization_codes=valid_codes,
                    created_by=self.request.user,
                    mapping_type=mapping_type,
                    priority=priority
                )
                
                if execution.status == 'completed':
                    messages.success(
                        self.request,
                        f"Successfully created {execution.triples_created} mappings "
                        f"for {len(valid_codes)} organizations"
                    )
                else:
                    messages.error(
                        self.request,
                        f"Bulk mapping failed with status: {execution.status}"
                    )
                
                return redirect('metadata:bulk_arkumu_mapping_execution', pk=execution.pk)
                
            except Exception as e:
                messages.error(
                    self.request,
                    f"Error creating bulk mappings: {str(e)}"
                )
                return self.form_invalid(form)
        
        return super().form_valid(form)


class BulkArkumuMappingPreviewView(GeneralLoginRequiredMixin, TemplateView):
    """View for previewing bulk mappings before creation."""
    
    template_name = 'metadata/bulk_arkumu_mapping/preview.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get preview data from session
        preview_data = self.request.session.get('bulk_mapping_preview')
        
        if not preview_data:
            messages.warning(self.request, "No preview data found. Please generate a preview first.")
            return context
        
        context['preview_data'] = preview_data
        
        # Calculate statistics
        total_mappings = sum(len(mappings) for mappings in preview_data['preview'].values())
        context['total_mappings'] = total_mappings
        
        # Group mappings by type (Class vs Property)
        context['mapping_stats'] = {}
        for org_code, mappings in preview_data['preview'].items():
            classes = [m for m in mappings if m['resource_type'] == 'Class']
            properties = [m for m in mappings if m['resource_type'] == 'Property']
            
            context['mapping_stats'][org_code] = {
                'total': len(mappings),
                'classes': len(classes),
                'properties': len(properties)
            }
        
        return context
    
    def post(self, request, *args, **kwargs):
        """Handle confirmation of preview mappings."""
        preview_data = request.session.get('bulk_mapping_preview')
        
        if not preview_data:
            messages.error(request, "No preview data found.")
            return redirect('metadata:bulk_arkumu_mapping')
        
        service = BulkArkumuMappingService()
        
        try:
            execution = service.create_harmonization_rules(
                organization_codes=preview_data['organization_codes'],
                created_by=request.user,
                mapping_type=preview_data['mapping_type'],
                priority=preview_data['priority']
            )
            
            # Clear preview data
            if 'bulk_mapping_preview' in request.session:
                del request.session['bulk_mapping_preview']
            
            if execution.status == 'completed':
                messages.success(
                    request,
                    f"Successfully created {execution.triples_created} mappings"
                )
            else:
                messages.error(
                    request,
                    f"Bulk mapping failed with status: {execution.status}"
                )
            
            return redirect('metadata:bulk_arkumu_mapping_execution', pk=execution.pk)
            
        except Exception as e:
            messages.error(request, f"Error creating mappings: {str(e)}")
            return redirect('metadata:bulk_arkumu_mapping')


class BulkArkumuMappingExecutionDetailView(GeneralLoginRequiredMixin, TemplateView):
    """View for displaying execution details."""
    
    template_name = 'metadata/bulk_arkumu_mapping/execution_detail.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        execution_id = kwargs.get('pk')
        try:
            execution = HarmonizationExecution.objects.get(pk=execution_id)
            context['execution'] = execution
            
            # Get associated organizations
            context['organizations'] = execution.organizations.all()
            
            # Get applied rules
            context['rules'] = execution.rules_applied.all()[:100]  # Limit for performance
            context['total_rules'] = execution.rules_applied.count()
            
            # Calculate duration if needed
            if execution.completed_at and execution.started_at and not execution.duration_seconds:
                execution.calculate_duration()
            
        except HarmonizationExecution.DoesNotExist:
            messages.error(self.request, "Execution not found.")
            context['execution'] = None
        
        return context


@method_decorator(require_http_methods(["GET"]), name='dispatch')
class BulkArkumuMappingSortView(GeneralLoginRequiredMixin, View):
    """HTMX view for sorting mappings in the preview table."""
    
    def get(self, request, *args, **kwargs):
        """Handle HTMX sorting request with URL parameters."""
        org_code = request.GET.get('org_code')
        sort_by = request.GET.get('sort')
        order = request.GET.get('order', 'asc')
        
        if not org_code or not sort_by:
            return HttpResponse('<tr><td colspan="4">Invalid sort request</td></tr>')
        
        try:
            # Get cached preview data from session
            session_key = f'bulk_mapping_preview_{org_code}'
            cached_mappings = request.session.get(session_key)
            
            if not cached_mappings:
                # Fallback: regenerate if not cached
                service = BulkArkumuMappingService()
                preview = service.preview_bulk_mapping([org_code])
                org_data = preview.get(org_code, {})
                cached_mappings = org_data.get('mappings', [])
                # Cache for future sorts
                request.session[session_key] = cached_mappings
            
            # Sort the cached mappings
            reverse_sort = (order == 'desc')
            
            if sort_by == 'type':
                sorted_mappings = sorted(cached_mappings, key=lambda x: (x.get('resource_type', ''), x.get('label', '')), reverse=reverse_sort)
            elif sort_by == 'source':
                sorted_mappings = sorted(cached_mappings, key=lambda x: x.get('source_iri', ''), reverse=reverse_sort)
            elif sort_by == 'target':
                sorted_mappings = sorted(cached_mappings, key=lambda x: x.get('target_iri', ''), reverse=reverse_sort)
            elif sort_by == 'label':
                sorted_mappings = sorted(cached_mappings, key=lambda x: x.get('label', ''), reverse=reverse_sort)
            else:
                sorted_mappings = cached_mappings
            
            # Store current sort state in session for template
            sort_session_key = f'bulk_mapping_sort_{org_code}'
            request.session[sort_session_key] = {'sort': sort_by, 'order': order}
            
            context = {
                'mappings': sorted_mappings,
                'current_sort': {'sort': sort_by, 'order': order},
                'org_code': org_code
            }
            return render(
                request, 
                'metadata/bulk_arkumu_mapping/sorted_mappings_fragment.html', 
                context
            )
            
        except Exception as e:
            return HttpResponse(f'<tr><td colspan="4">Error sorting: {str(e)}</td></tr>')


@method_decorator(require_http_methods(["POST"]), name='dispatch')
class BulkArkumuMappingRemoveView(GeneralLoginRequiredMixin, View):
    """HTMX view for removing mappings for a specific organization."""
    
    def post(self, request, *args, **kwargs):
        """Handle HTMX remove request for organization mappings."""
        org_code = request.GET.get('org_code')
        
        if not org_code:
            return HttpResponse('<div class="alert alert-danger">Invalid remove request</div>')
        
        try:
            service = BulkArkumuMappingService()
            
            # Remove the organization from cached preview data
            session_key = f'bulk_mapping_preview_{org_code}'
            if session_key in request.session:
                del request.session[session_key]
            
            # Remove sort state for this organization
            sort_session_key = f'bulk_mapping_sort_{org_code}'
            if sort_session_key in request.session:
                del request.session[sort_session_key]
            
            # Get all cached preview organization codes and remove the specified one
            session_keys = [key for key in request.session.keys() if key.startswith('bulk_mapping_preview_')]
            remaining_codes = []
            
            for key in session_keys:
                cached_org_code = key.replace('bulk_mapping_preview_', '')
                if cached_org_code != org_code:
                    remaining_codes.append(cached_org_code)
            
            if not remaining_codes:
                return HttpResponse('<div class="alert alert-info">No organizations selected.</div>')
            
            # Regenerate preview without the removed organization
            preview = service.preview_bulk_mapping(remaining_codes)
            
            # Cache the preview data for remaining organizations
            for remaining_org_code, org_data in preview.items():
                session_key = f'bulk_mapping_preview_{remaining_org_code}'
                request.session[session_key] = org_data.get('mappings', [])
            
            # Get sort states for remaining organizations
            sort_states = {}
            for remaining_org_code in preview.keys():
                sort_session_key = f'bulk_mapping_sort_{remaining_org_code}'
                sort_states[remaining_org_code] = request.session.get(sort_session_key, {'sort': None, 'order': 'asc'})
            
            context = {
                'preview': preview,
                'total_new_mappings': sum(data['total_count'] for data in preview.values()),
                'sort_states': sort_states
            }
            
            return render(
                request, 
                'metadata/bulk_arkumu_mapping/preview_fragment.html', 
                context
            )
            
        except Exception as e:
            return HttpResponse(f'<div class="alert alert-danger">Error removing mappings: {str(e)}</div>')


@method_decorator(require_http_methods(["DELETE"]), name='dispatch')
class BulkArkumuMappingDeleteView(GeneralLoginRequiredMixin, View):
    """HTMX view for deleting existing harmonization mappings."""
    
    def delete(self, request, *args, **kwargs):
        """Handle HTMX delete request for harmonization execution."""
        execution_id = kwargs.get('pk')
        
        if not execution_id:
            return HttpResponse('<tr><td colspan="6" class="text-danger">Invalid delete request</td></tr>')
        
        try:
            # Get the harmonization execution
            execution = HarmonizationExecution.objects.get(pk=execution_id)
            
            # Check if user has permission to delete (created by them)
            if execution.created_by != request.user:
                return HttpResponse('<tr><td colspan="6" class="text-danger">You can only delete your own mappings</td></tr>')
            
            # Delete all harmonization rules created by this execution
            deleted_rules_count = execution.rules_applied.count()
            execution.rules_applied.all().delete()
            
            # Delete the execution record itself
            execution.delete()
            
            # Return empty content to remove the table row
            return HttpResponse('')
            
        except HarmonizationExecution.DoesNotExist:
            return HttpResponse('<tr><td colspan="6" class="text-danger">Execution not found</td></tr>')
        except Exception as e:
            return HttpResponse(f'<tr><td colspan="6" class="text-danger">Error deleting mappings: {str(e)}</td></tr>')