"""
Harmonization Views

Simple, functional views for harmonization service - no fancy features, just what's needed to use the service.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, UpdateView, DetailView, FormView
from django.contrib import messages
from django.urls import reverse_lazy, reverse
from django.db.models import Count, Q
from django.utils import timezone
from django import forms

from arkumu.users.models import Organization 
from arkumu.metadata.models.harmonization import (
    HarmonizationRule, 
    HarmonizationExecution, 
    HarmonizationConflict
)
from arkumu.metadata.services.harmonization.harmonization_service import HarmonizationService


class HarmonizationStartForm(forms.Form):
    """Basic form to start harmonization"""
    organization = forms.ModelChoiceField(
        queryset=Organization.objects.filter(is_active=True),
        empty_label="Select organization..."
    )
    cleanup_existing = forms.BooleanField(
        initial=True,
        required=False,
        help_text="Remove existing alignments first"
    )


class HarmonizationRuleForm(forms.ModelForm):
    """Simple rule creation form"""
    class Meta:
        model = HarmonizationRule
        fields = [
            'source_organization', 
            'source_property_pattern', 
            'catalog_property_label', 
            'mapping_type', 
            'priority'
        ]
        widgets = {
            'source_organization': forms.Select(attrs={'class': 'form-control'}),
            'source_property_pattern': forms.TextInput(attrs={'class': 'form-control'}),
            'catalog_property_label': forms.TextInput(attrs={'class': 'form-control'}),
            'mapping_type': forms.Select(attrs={'class': 'form-control'}),
            'priority': forms.NumberInput(attrs={'class': 'form-control'}),
        }


class HarmonizationListView(LoginRequiredMixin, ListView):
    """Simple list showing organizations and their harmonization status"""
    template_name = 'metadata/harmonization/list.html'
    context_object_name = 'organizations'
    
    def get_queryset(self):
        # Return organizations user has access to (for now, all active organizations)
        return Organization.objects.filter(is_active=True).prefetch_related(
            'harmonization_rules',
            'harmonization_executions'
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Add harmonization stats for each organization
        organizations_with_stats = []
        for org in context['organizations']:
            # Get last execution
            last_execution = org.harmonization_executions.order_by('-started_at').first()
            
            # Get pending conflicts count
            pending_conflicts = HarmonizationConflict.objects.filter(
                execution__organizations=org,
                resolution='pending'
            ).count()
            
            org_data = {
                'organization': org,
                'rules_count': org.harmonization_rules.filter(is_active=True).count(),
                'last_execution': last_execution,
                'pending_conflicts': pending_conflicts
            }
            organizations_with_stats.append(org_data)
        
        context['organizations_with_stats'] = organizations_with_stats
        return context


class HarmonizationStartView(LoginRequiredMixin, FormView):
    """Simple form to start harmonization for an organization"""
    template_name = 'metadata/harmonization/start.html'
    form_class = HarmonizationStartForm
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['organizations'] = Organization.objects.filter(is_active=True)
        return context
    
    def form_valid(self, form):
        try:
            service = HarmonizationService()
            execution = service.harmonize_organization(
                organization=form.cleaned_data['organization'],
                user=self.request.user,
                cleanup_existing=form.cleaned_data['cleanup_existing']
            )
            messages.success(
                self.request, 
                f"Harmonization started for {form.cleaned_data['organization'].name}"
            )
            return redirect('metadata:harmonization_execution_detail', pk=execution.pk)
        except Exception as e:
            messages.error(self.request, f"Failed to start harmonization: {str(e)}")
            return self.form_invalid(form)


class HarmonizationExecutionDetailView(LoginRequiredMixin, DetailView):
    """Show execution results - status, stats, conflicts (if any)"""
    model = HarmonizationExecution
    template_name = 'metadata/harmonization/execution_detail.html'
    context_object_name = 'execution'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        execution = self.get_object()
        
        # Add conflicts for this execution
        context['conflicts'] = execution.conflicts.select_related('selected_rule').all()
        
        return context


class HarmonizationRuleListView(LoginRequiredMixin, ListView):
    """List rules with basic filtering by organization"""
    model = HarmonizationRule
    template_name = 'metadata/harmonization/rules/list.html'
    context_object_name = 'rules'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = HarmonizationRule.objects.select_related(
            'source_organization', 
            'validated_by'
        ).order_by('-priority', 'catalog_property_label')
        
        # Filter by organization if provided
        org_id = self.request.GET.get('organization')
        if org_id:
            try:
                queryset = queryset.filter(source_organization_id=org_id)
            except ValueError:
                pass  # Invalid UUID, ignore
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['organizations'] = Organization.objects.filter(is_active=True)
        context['selected_org'] = self.request.GET.get('organization')
        return context


class HarmonizationRuleCreateView(LoginRequiredMixin, CreateView):
    """Create rule with simple form"""
    model = HarmonizationRule
    form_class = HarmonizationRuleForm
    template_name = 'metadata/harmonization/rules/create.html'
    success_url = reverse_lazy('metadata:harmonization_rules')
    
    def form_valid(self, form):
        try:
            service = HarmonizationService()
            rule = service.create_harmonization_rule(
                source_organization=form.cleaned_data['source_organization'],
                source_property_pattern=form.cleaned_data['source_property_pattern'],
                catalog_property_name=form.cleaned_data['catalog_property_label'],
                mapping_type=form.cleaned_data['mapping_type'],
                priority=form.cleaned_data['priority'],
                user=self.request.user
            )
            messages.success(self.request, f"Harmonization rule created: {rule}")
            return redirect('metadata:harmonization_rules')
        except Exception as e:
            messages.error(self.request, f"Failed to create rule: {str(e)}")
            return self.form_invalid(form)


class HarmonizationRuleUpdateView(LoginRequiredMixin, UpdateView):
    """Edit existing rule"""
    model = HarmonizationRule
    template_name = 'metadata/harmonization/rules/update.html'
    fields = [
        'source_property_pattern', 
        'catalog_property_label', 
        'mapping_type', 
        'priority', 
        'is_active'
    ]
    success_url = reverse_lazy('metadata:harmonization_rules')
    
    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Rule updated: {self.object}")
        return response


class HarmonizationConflictListView(LoginRequiredMixin, ListView):
    """List conflicts with simple resolve buttons"""
    model = HarmonizationConflict
    template_name = 'metadata/harmonization/conflicts/list.html'
    context_object_name = 'conflicts'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = HarmonizationConflict.objects.select_related(
            'execution',
            'selected_rule',
            'resolved_by'
        ).prefetch_related(
            'conflicting_rules',
            'execution__organizations'
        ).order_by('-created_at')
        
        # Filter by resolution status
        resolution = self.request.GET.get('resolution')
        if resolution:
            queryset = queryset.filter(resolution=resolution)
        
        # Filter by execution
        execution_id = self.request.GET.get('execution')
        if execution_id:
            try:
                queryset = queryset.filter(execution_id=execution_id)
            except ValueError:
                pass  # Invalid UUID, ignore
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['resolution_choices'] = HarmonizationConflict.RESOLUTION_CHOICES
        context['selected_resolution'] = self.request.GET.get('resolution')
        context['selected_execution'] = self.request.GET.get('execution')
        return context