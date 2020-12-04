from django.contrib import admin
from django.urls import reverse
from django.utils.safestring import mark_safe

from license_manager.apps.subscriptions.forms import (
    SubscriptionPlanForm,
    SubscriptionPlanRenewalForm,
)
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
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
        'subscription_plan__customer_agreement__enterprise_customer_uuid__startswith',
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
        'customer_agreement',
        'enterprise_catalog_uuid',
        'salesforce_opportunity_id',
        'netsuite_product_id',
        'num_revocations_remaining',
        'num_licenses',
    )
    writable_fields = (
        'revoke_max_percentage',
        'is_active',
        'for_internal_use_only',
    )
    fields = read_only_fields + writable_fields
    list_display = (
        'title',
        'uuid',
        'is_active',
        'start_date',
        'expiration_date',
        'get_customer_agreement_link',
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
        'customer_agreement__enterprise_customer_uuid__startswith',
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
        # If a uuid is not specified on the subscription itself, use the default one for the CustomerAgreement
        customer_agreement_catalog = obj.customer_agreement.default_enterprise_catalog_uuid
        obj.enterprise_catalog_uuid = (obj.enterprise_catalog_uuid or customer_agreement_catalog)

        # Create licenses to be associated with the subscription plan after creating the subscription plan
        num_new_licenses = form.cleaned_data.get('num_licenses', 0) - obj.num_licenses
        super().save_model(request, obj, form, change)
        SubscriptionPlan.increase_num_licenses(obj, num_new_licenses)

    def get_readonly_fields(self, request, obj=None):
        """
        Only allow a few certain fields to be writable if a subscription already exists
        """
        if obj:
            return self.read_only_fields
        return ()

    def get_customer_agreement_link(self, obj):
        if obj.customer_agreement:
            return mark_safe('<a href="{}">{}</a></br>'.format(
                reverse('admin:subscriptions_customeragreement_change', args=(obj.customer_agreement.uuid,)),
                obj.customer_agreement.uuid,
            ))
        return ''
    get_customer_agreement_link.short_description = 'Customer Agreement'


@admin.register(CustomerAgreement)
class CustomerAgreementAdmin(admin.ModelAdmin):
    read_only_fields = (
        'enterprise_customer_uuid',
    )
    writable_fields = (
        'enterprise_customer_slug',
        'default_enterprise_catalog_uuid',
    )
    fields = read_only_fields + writable_fields
    list_display = (
        'uuid',
        'enterprise_customer_uuid',
        'enterprise_customer_slug',
        'get_subscription_plan_links',
    )
    sortable_by = (
        'uuid',
        'enterprise_customer_uuid',
        'enterprise_customer_slug',
    )
    search_fields = (
        'uuid__startswith',
        'enterprise_customer_uuid__startswith',
        'enterprise_customer_slug__startswith',
    )

    def get_readonly_fields(self, request, obj=None):
        """
        If the Customer Agreement already exists, make all fields but enterprise_customer_slug
        and default_enterprise_catalog_uuid read-only
        """
        if obj:
            return self.read_only_fields
        return ()

    def get_subscription_plan_links(self, obj):
        links = ''
        for subscription_plan in obj.subscriptions.all():
            if subscription_plan.is_active:
                links = links + '<a href="{}">{}: {}</a></br>'.format(
                    reverse('admin:subscriptions_subscriptionplan_change', args=(subscription_plan.uuid,)),
                    subscription_plan.title,
                    subscription_plan.uuid,
                )
        return mark_safe(links)
    get_subscription_plan_links.short_description = 'Subscription Plans'


@admin.register(SubscriptionPlanRenewal)
class SubscriptionPlanRenewalAdmin(admin.ModelAdmin):
    form = SubscriptionPlanRenewalForm
    readonly_fields = ['renewed_subscription_plan']
    list_display = (
        'get_prior_subscription_plan_title',
        'effective_date',
        'renewed_expiration_date',
        'processed',
        'get_prior_subscription_plan_uuid',
        'get_prior_subscription_plan_enterprise_customer',
        'get_prior_subscription_plan_enterprise_catalog',
        'get_renewed_plan_link'
    )
    ordering = (
        'prior_subscription_plan__title',
        'effective_date',
    )
    list_filter = (
        'prior_subscription_plan__title',
        'processed',
        'prior_subscription_plan__customer_agreement__enterprise_customer_uuid',
        'prior_subscription_plan__enterprise_catalog_uuid',
    )
    search_fields = (
        'prior_subscription_plan__title',
        'prior_subscription_plan__uuid__startswith',
        'prior_subscription_plan__customer_agreement__enterprise_customer_uuid__startswith',
        'prior_subscription_plan__enterprise_catalog_uuid__startswith',
    )

    def get_prior_subscription_plan_title(self, obj):
        return obj.prior_subscription_plan.title
    get_prior_subscription_plan_title.short_description = 'Subscription Title'
    get_prior_subscription_plan_title.admin_order_field = 'prior_subscription_plan__title'

    def get_prior_subscription_plan_uuid(self, obj):
        return obj.prior_subscription_plan.uuid
    get_prior_subscription_plan_uuid.short_description = 'Subscription UUID'
    get_prior_subscription_plan_uuid.admin_order_field = 'prior_subscription_plan__uuid'

    def get_prior_subscription_plan_enterprise_customer(self, obj):
        return obj.prior_subscription_plan.enterprise_customer_uuid
    get_prior_subscription_plan_enterprise_customer.short_description = 'Enterprise Customer UUID'
    get_prior_subscription_plan_enterprise_customer.admin_order_field = \
        'prior_subscription_plan__enterprise_customer_uuid'

    def get_prior_subscription_plan_enterprise_catalog(self, obj):
        return obj.prior_subscription_plan.enterprise_catalog_uuid
    get_prior_subscription_plan_enterprise_catalog.short_description = 'Enterprise Catalog UUID'
    get_prior_subscription_plan_enterprise_catalog.admin_order_field = \
        'prior_subscription_plan__enterprise_catalog_uuid'

    def get_renewed_plan_link(self, obj):
        if obj.renewed_subscription_plan:
            return mark_safe('<a href="{}">{}: {}</a></br>'.format(
                reverse('admin:subscriptions_subscriptionplan_change', args=(obj.renewed_subscription_plan.uuid,)),
                obj.renewed_subscription_plan.title,
                obj.renewed_subscription_plan.uuid,
            ))
        return ''
    get_renewed_plan_link.short_description = 'Renewed Subscription Plan'

    def has_change_permission(self, request, obj=None):
        """
        If the subscription renewal has already been created, it should not be editable.
        """
        if obj:
            return False
        return True
