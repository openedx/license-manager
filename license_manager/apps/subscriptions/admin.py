from django.contrib import admin, messages
from django.db import transaction
from django.urls import reverse
from django.utils.safestring import mark_safe
from simple_history.admin import SimpleHistoryAdmin

from license_manager.apps.subscriptions.api import (
    UnprocessableSubscriptionPlanExpirationError,
    UnprocessableSubscriptionPlanFreezeError,
    delete_unused_licenses_post_freeze,
    renew_subscription,
    sync_agreement_with_enterprise_customer,
)
from license_manager.apps.subscriptions.exceptions import CustomerAgreementError
from license_manager.apps.subscriptions.forms import (
    CustomerAgreementAdminForm,
    SubscriptionPlanForm,
    SubscriptionPlanRenewalForm,
)
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    License,
    PlanType,
    SubscriptionPlan,
    SubscriptionPlanRenewal,
)


def _related_object_link(admin_viewname, object_pk, object_str):
    return mark_safe('<a href="{href}">{object_string}</a><br/>'.format(
        href=reverse(admin_viewname, args=(object_pk,)),
        object_string=object_str,
    ))


@admin.register(License)
class LicenseAdmin(admin.ModelAdmin):
    readonly_fields = [
        'activation_key',
        'get_renewed_to',
        'get_renewed_from',
    ]
    exclude = ['history', 'renewed_to']
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
        return _related_object_link(
            'admin:subscriptions_subscriptionplan_change',
            obj.subscription_plan.uuid,
            obj.subscription_plan.title,
        )
    get_subscription_plan_title.short_description = 'Subscription Plan'

    def get_renewed_to(self, obj):
        if not obj.renewed_to:
            return ''
        return _related_object_link(
            'admin:subscriptions_license_change',
            obj.renewed_to.uuid,
            obj.renewed_to.uuid,
        )
    get_renewed_to.short_description = 'License renewed to'

    def get_renewed_from(self, obj):
        if not obj.renewed_from:
            return ''
        return _related_object_link(
            'admin:subscriptions_license_change',
            obj.renewed_from.uuid,
            obj.renewed_from.uuid,
        )
    get_renewed_from.short_description = 'License renewed from'


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(SimpleHistoryAdmin):
    form = SubscriptionPlanForm
    # This is not to be confused with readonly_fields of the BaseModelAdmin class
    read_only_fields = (
        'num_revocations_remaining',
        'num_licenses',
        'expiration_processed',
        'customer_agreement',
        'last_freeze_timestamp',
    )
    writable_fields = (
        'title',
        'start_date',
        'expiration_date',
        'enterprise_catalog_uuid',
        'salesforce_opportunity_id',
        'netsuite_product_id',
        'plan_type',
        'revoke_max_percentage',
        'is_revocation_cap_enabled',
        'is_active',
        'for_internal_use_only',
        'change_reason',
        'can_freeze_unused_licenses',
    )
    fields = writable_fields + read_only_fields
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
        'can_freeze_unused_licenses',
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
    actions = ['process_unused_licenses_post_freeze']

    def save_model(self, request, obj, form, change):
        # Record change reason for simple history
        obj._change_reason = form.cleaned_data.get('change_reason')  # pylint: disable=protected-access

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
            return _related_object_link(
                'admin:subscriptions_customeragreement_change',
                obj.customer_agreement.uuid,
                obj.customer_agreement.enterprise_customer_slug,
            )
        return ''
    get_customer_agreement_link.short_description = 'Customer Agreement'

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'customer_agreement':
            kwargs['queryset'] = CustomerAgreement.objects.filter().order_by('enterprise_customer_slug')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def process_unused_licenses_post_freeze(self, request, queryset):
        try:
            with transaction.atomic():
                for subscription_plan in queryset:
                    delete_unused_licenses_post_freeze(subscription_plan)
                messages.add_message(request, messages.SUCCESS, 'Successfully froze selected Subscription Plans.')
        except UnprocessableSubscriptionPlanFreezeError as exc:
            messages.add_message(request, messages.ERROR, exc)
    process_unused_licenses_post_freeze.short_description = (
        'Freeze selected Subscription Plans (deletes unused licenses)'
    )


@admin.register(CustomerAgreement)
class CustomerAgreementAdmin(admin.ModelAdmin):
    form = CustomerAgreementAdminForm

    read_only_fields = (
        'enterprise_customer_uuid',
        'enterprise_customer_slug',
        'enterprise_customer_name',
    )
    writable_fields = (
        'default_enterprise_catalog_uuid',
        'disable_expiration_notifications',
        'license_duration_before_purge',
    )
    fields = read_only_fields + writable_fields
    list_display = (
        'uuid',
        'enterprise_customer_uuid',
        'enterprise_customer_slug',
        'enterprise_customer_name',
        'get_subscription_plan_links',
        'disable_expiration_notifications',
    )
    sortable_by = (
        'uuid',
        'enterprise_customer_uuid',
        'enterprise_customer_slug',
        'enterprise_customer_name',
    )
    search_fields = (
        'uuid__startswith',
        'enterprise_customer_uuid__startswith',
        'enterprise_customer_slug__startswith',
        'enterprise_customer_name__startswith',
    )
    actions = ['sync_agreement_with_enterprise_customer']

    def sync_agreement_with_enterprise_customer(self, request, queryset):
        """
        Django action handler to sync any updates made to the enterprise customer
        name and slug with any selected CustomerAgreement records.

        This provides a self-service way to address any mismatches between slug or name
        in the agreement and the EnterpriseCustomer in the LMS.
        """
        try:
            with transaction.atomic():
                for customer_agreement in queryset:
                    sync_agreement_with_enterprise_customer(customer_agreement)
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully synced enterprise customer fields with selected Customer Agreements'
                )
        except CustomerAgreementError as exc:
            messages.add_message(request, messages.ERROR, exc)
    sync_agreement_with_enterprise_customer.short_description = 'Sync enterprise customer fields for selected records'

    def save_model(self, request, obj, form, change):
        """
        Saves the CustomerAgreement instance.

        Adds a Django error message a ``CustomerAgreementError`` occurred.
        Notably, this happens when the slug field was
        not present and could not be fetched from the enterprise API.
        """
        try:
            super().save_model(request, obj, form, change)
        except CustomerAgreementError as exc:
            messages.error(request, exc)

    def get_readonly_fields(self, request, obj=None):
        """
        If creating a new CustomerAgreement, all fields but ``enterprise_customer_slug``
        and ``license_duration_before_purge`` should be writable.
        Note that we fetch the slug from the enterprise API before saving (if it's
        not already set).
        """
        if obj:
            return self.read_only_fields
        return ('enterprise_customer_slug', 'license_duration_before_purge')

    def get_subscription_plan_links(self, obj):
        links = []
        for subscription_plan in obj.subscriptions.all():
            if subscription_plan.is_active:
                links.append(
                    _related_object_link(
                        'admin:subscriptions_subscriptionplan_change',
                        subscription_plan.uuid,
                        '{}: {}'.format(subscription_plan.title, subscription_plan.uuid),
                    )
                )
        return mark_safe(' '.join(links))
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
    actions = ['process_renewal']

    def process_renewal(self, request, queryset):
        for renewal in queryset:
            renew_subscription(renewal)
    process_renewal.short_description = 'Process selected renewal records'

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
            return _related_object_link(
                'admin:subscriptions_subscriptionplan_change',
                obj.renewed_subscription_plan.uuid,
                '{}: {}'.format(obj.renewed_subscription_plan.title, obj.renewed_subscription_plan.uuid),
            )
        return ''
    get_renewed_plan_link.short_description = 'Renewed Subscription Plan'

    def has_change_permission(self, request, obj=None):
        """
        If the subscription renewal has already been processed, it should not be editable.
        """
        if obj and obj.processed:
            return False
        return True


@admin.register(PlanType)
class PlanTypeAdmin(admin.ModelAdmin):
    exclude = ['history']
    list_display = (
        'label',
        'description',
    )
    ordering = (
        'label',
        'description',
        'is_paid_subscription',
        'ns_id_required',
        'sf_id_required',
        'internal_use_only',
    )
    sortable_by = (
        'label',
        'description',
        'is_paid_subscription',
        'ns_id_required',
        'sf_id_required',
        'internal_use_only',
    )
    list_filter = (
        'label',
        'description'
    )
    search_fields = (
        'label',
        'description',
        'is_paid_subscription',
        'ns_id_required',
        'sf_id_required',
        'internal_use_only',
    )
    fields = (
        'label',
        'description',
        'is_paid_subscription',
        'ns_id_required',
        'sf_id_required',
        'internal_use_only',
    )
