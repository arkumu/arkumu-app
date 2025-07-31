"""
Bulk Arkumu Mapping Views

Views for creating bulk mappings from organization-specific ontologies to the Arkumu model.
"""

from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.generic import FormView, TemplateView
from django.urls import reverse_lazy
from django import forms
from django.http import HttpResponse

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
        
        # Get organization statistics
        organizations = Organization.objects.filter(is_active=True)
        context['organization_stats'] = {}
        
        for org in organizations:
            context['organization_stats'][org.code] = {
                'name': org.name,
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
            
            context = {
                'preview': preview,
                'total_new_mappings': sum(len(mappings) for mappings in preview.values())
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