from django.contrib import admin

from license_manager.apps.subscriptions.forms import SubscriptionPlanForm
from license_manager.apps.subscriptions.models import License, SubscriptionPlan


@admin.register(License)
class LicenseAdmin(admin.ModelAdmin):
    readonly_fields = ['activation_key']
    exclude = ['history']
    list_display = (
        'uuid',
        'status',
        'assigned_date',
        'activation_date',
        'user_email',
    )
    ordering = (
        'assigned_date',
        'status',
        'user_email',
    )
    sortable_by = (
        'assigned_date',
        'status',
        'user_email',
    )
    list_filter = (
        'status',
    )
    search_fields = (
        'user_email',
        'subscription_plan__title',
        'subscription_plan__uuid',
        'subscription_plan__enterprise_customer_uuid',
    )


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    form = SubscriptionPlanForm
    # This is not to be confused with readonly_fields of the BaseModelAdmin class
    read_only_fields = (
        'title',
        'start_date',
        'expiration_date',
        'enterprise_customer_uuid',
        'enterprise_catalog_uuid',
        'salesforce_opportunity_id',
        'netsuite_product_id',
        'num_revocations_remaining',
    )
    writable_fields = (
        'revoke_max_percentage',
        'num_licenses',
        'is_active',
        'for_internal_use_only',
    )
    fields = read_only_fields + writable_fields

    def save_model(self, request, obj, form, change):
        # Create licenses to be associated with the subscription plan after creating the subscription plan
        num_new_licenses = form.cleaned_data.get('num_licenses', 0) - obj.num_licenses
        super().save_model(request, obj, form, change)
        SubscriptionPlan.increase_num_licenses(obj, num_new_licenses)

    def get_readonly_fields(self, request, obj=None):
        """
        If subscription already exists, make all fields but num_licenses and is_active read-only
        """
        if obj:
            return self.read_only_fields
        return ()
