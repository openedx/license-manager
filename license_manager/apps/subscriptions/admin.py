from django.contrib import admin
from django.urls import reverse
from django.utils.safestring import mark_safe

from license_manager.apps.subscriptions.forms import (
    SubscriptionPlanForm,
    SubscriptionPlanRenewalForm,
)
from license_manager.apps.subscriptions.models import (
    License,
    SubscriptionPlan,
    SubscriptionPlanRenewal,
)


@admin.register(License)
class LicenseAdmin(admin.ModelAdmin):
    readonly_fields = ['activation_key']
    exclude = ['history']
    list_display = (
        'uuid',
        'get_subscription_plan_title',
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
        'uuid__startswith',
        'user_email',
        'subscription_plan__title',
        'subscription_plan__uuid__startswith',
        'subscription_plan__enterprise_customer_uuid__startswith',
        'subscription_plan__enterprise_catalog_uuid__startswith',
    )

    def get_subscription_plan_title(self, obj):
        return mark_safe('<a href="{}">{}</a>'.format(
            reverse('admin:subscriptions_subscriptionplan_change', args=(obj.subscription_plan.uuid,)),
            obj.subscription_plan.title,
        ))
    get_subscription_plan_title.short_description = 'Subscription Plan'


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
    list_display = (
        'title',
        'is_active',
        'start_date',
        'expiration_date',
        'enterprise_customer_uuid',
        'enterprise_catalog_uuid',
        'for_internal_use_only',
    )
    list_filter = (
        'is_active',
        'for_internal_use_only',
    )
    search_fields = (
        'uuid__startswith',
        'title',
        'enterprise_customer_uuid__startswith',
        'enterprise_catalog_uuid__startswith',
    )
    ordering = (
        'title',
        'start_date',
        'expiration_date',
    )
    sortable_by = (
        'title',
        'start_date',
        'expiration_date',
    )

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


@admin.register(SubscriptionPlanRenewal)
class SubscriptionPlanRenewalAdmin(admin.ModelAdmin):
    form = SubscriptionPlanRenewalForm
    list_display = (
        'get_subscription_plan_title',
        'effective_date',
        'renewed_expiration_date',
        'processed',
        'get_subscription_plan_uuid',
        'get_subscription_plan_enterprise_customer',
        'get_subscription_plan_enterprise_catalog',
    )
    ordering = (
        'subscription_plan__title',
        'effective_date',
    )
    list_filter = (
        'subscription_plan__title',
        'processed',
        'subscription_plan__enterprise_customer_uuid',
        'subscription_plan__enterprise_catalog_uuid',
    )
    search_fields = (
        'subscription_plan__title',
        'subscription_plan__uuid__startswith',
        'subscription_plan__enterprise_customer_uuid__startswith',
        'subscription_plan__enterprise_catalog_uuid__startswith',
    )

    def get_subscription_plan_title(self, obj):
        return obj.subscription_plan.title
    get_subscription_plan_title.short_description = 'Subscription Title'
    get_subscription_plan_title.admin_order_field = 'subscription_plan__title'

    def get_subscription_plan_uuid(self, obj):
        return obj.subscription_plan.uuid
    get_subscription_plan_uuid.short_description = 'Subscription UUID'
    get_subscription_plan_uuid.admin_order_field = 'subscription_plan__uuid'

    def get_subscription_plan_enterprise_customer(self, obj):
        return obj.subscription_plan.enterprise_customer_uuid
    get_subscription_plan_enterprise_customer.short_description = 'Enterprise Customer UUID'
    get_subscription_plan_enterprise_customer.admin_order_field = 'subscription_plan__enterprise_customer_uuid'

    def get_subscription_plan_enterprise_catalog(self, obj):
        return obj.subscription_plan.enterprise_catalog_uuid
    get_subscription_plan_enterprise_catalog.short_description = 'Enterprise Catalog UUID'
    get_subscription_plan_enterprise_catalog.admin_order_field = 'subscription_plan__enterprise_catalog_uuid'

    def has_change_permission(self, request, obj=None):
        """
        If the subscription renewal has already been created, it should not be editable.
        """
        if obj:
            return False
        return True
