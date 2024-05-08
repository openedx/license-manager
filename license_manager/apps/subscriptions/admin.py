from datetime import datetime

from django.conf import settings
from django.contrib import admin, messages
from django.db import transaction
from django.urls import reverse
from django.utils.safestring import mark_safe
from djangoql.admin import DjangoQLSearchMixin
from pytz import UTC
from simple_history.admin import SimpleHistoryAdmin

from license_manager.apps.subscriptions.api import (
    UnprocessableSubscriptionPlanFreezeError,
    delete_unused_licenses_post_freeze,
    renew_subscription,
    sync_agreement_with_enterprise_customer,
    toggle_auto_apply_licenses,
)
from license_manager.apps.subscriptions.exceptions import CustomerAgreementError
from license_manager.apps.subscriptions.forms import (
    CustomerAgreementAdminForm,
    LicenseTransferJobAdminForm,
    ProductForm,
    SubscriptionPlanForm,
    SubscriptionPlanRenewalForm,
)
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    License,
    LicenseTransferJob,
    Notification,
    PlanType,
    Product,
    SubscriptionPlan,
    SubscriptionPlanRenewal,
)
from license_manager.apps.subscriptions.tasks import (
    PROVISION_LICENSES_BATCH_SIZE,
    provision_licenses_task,
)


def get_related_object_link(admin_viewname, object_pk, object_str):
    return mark_safe('<a href="{href}">{object_string}</a><br/>'.format(
        href=reverse(admin_viewname, args=(object_pk,)),
        object_string=object_str,
    ))


@admin.register(License)
class LicenseAdmin(DjangoQLSearchMixin, admin.ModelAdmin):
    readonly_fields = [
        'activation_key',
        'get_renewed_to',
        'get_renewed_from',
        'auto_applied',
        'source_id',
        'source_type',
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
        'subscription_plan__customer_agreement__enterprise_customer_uuid__startswith',
        'subscription_plan__customer_agreement__enterprise_customer_slug__startswith'
    )

    actions = ['revert_licenses_to_snapshot_time']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'subscription_plan',
            'source'
        )

    @admin.display(description='Source ID')
    def source_id(self, instance):
        """Return source id of license if a source exists"""
        try:
            return instance.source.source_id
        except License.source.RelatedObjectDoesNotExist:  # pylint: disable=no-member
            return ''

    @admin.display(description='Source Type')
    def source_type(self, instance):
        """Return source type of license if a source exists"""
        try:
            return instance.source.source_type.slug
        except License.source.RelatedObjectDoesNotExist:  # pylint: disable=no-member
            return ''

    @admin.display(
        description='Subscription Plan'
    )
    def get_subscription_plan_title(self, obj):
        return get_related_object_link(
            'admin:subscriptions_subscriptionplan_change',
            obj.subscription_plan.uuid,
            obj.subscription_plan.title,
        )

    @admin.display(
        description='License renewed to'
    )
    def get_renewed_to(self, obj):
        """
        Returns License renewed to
        """
        if not obj.renewed_to:
            return ''
        return get_related_object_link(
            'admin:subscriptions_license_change',
            obj.renewed_to.uuid,
            obj.renewed_to.uuid,
        )

    @admin.display(
        description='License renewed from'
    )
    def get_renewed_from(self, obj):
        """
        Returns License renewed from
        """
        if not obj.renewed_from:
            return ''
        return get_related_object_link(
            'admin:subscriptions_license_change',
            obj.renewed_from.uuid,
            obj.renewed_from.uuid,
        )

    def _parse_snapshot_timestamp(self):
        """
        Parses settings.LICENSE_REVERT_SNAPSHOT_TIMESTAMP into a UTC-localized datetime object.
        """
        snapshot_datetime = datetime.strptime(
            settings.LICENSE_REVERT_SNAPSHOT_TIMESTAMP,
            '%Y-%m-%d %H:%M:%S',
        )
        # pylint: disable=no-value-for-parameter
        return UTC.localize(snapshot_datetime)

    @admin.action(
        description='Revert licenses to snapshot'
    )
    def revert_licenses_to_snapshot_time(self, request, queryset):
        """
        Sets a license back to whatever it was at some timestamp defined in config.
        """
        try:
            with transaction.atomic():
                snapshot_datetime = self._parse_snapshot_timestamp()
                for _license in queryset:
                    # https://github.com/jazzband/django-simple-history/issues/617
                    snapshot_record = _license.history.as_of(snapshot_datetime)
                    _license = snapshot_record
                    _license._state.adding = False  # pylint: disable=protected-access
                    _license.save(force_update=True)
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully reset licenses to snapshot time {}'.format(snapshot_datetime),
                )
        except Exception as exc:  # pylint: disable=broad-except
            messages.add_message(request, messages.ERROR, exc)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(DjangoQLSearchMixin, SimpleHistoryAdmin):
    form = SubscriptionPlanForm

    # Do not include these fields on the create page.
    fields_skip_create = [
        'desired_num_licenses',
    ]
    # This is not to be confused with readonly_fields of the BaseModelAdmin class.
    # This is only used for field display sorting purposes (they should appear lower on the page).
    read_only_fields = [
        'num_revocations_remaining',
        'num_licenses',
        'expiration_processed',
        'customer_agreement',
        'last_freeze_timestamp',
        'salesforce_opportunity_id',
    ]
    # Writable fields appear higher on the page.
    writable_fields = [
        'title',
        'desired_num_licenses',
        'start_date',
        'expiration_date',
        'enterprise_catalog_uuid',
        'salesforce_opportunity_line_item',
        'product',
        'revoke_max_percentage',
        'is_revocation_cap_enabled',
        'is_active',
        'for_internal_use_only',
        'change_reason',
        'can_freeze_unused_licenses',
        'should_auto_apply_licenses',
    ]
    # There are some fields we want to force first/last in the form for cognitive ease.
    fields_displayed_first = [
        'title',
        'is_active',
        'num_licenses',
        'desired_num_licenses',
        'for_internal_use_only',
    ]
    fields_displayed_last = [
        'is_revocation_cap_enabled',
        'revoke_max_percentage',
        'can_freeze_unused_licenses',
        'change_reason',
    ]

    def get_fields(self, request, obj=None):
        """
        Construct a list of fields, ordered based on first/last/read_only/writable hints above, and filtered depending
        on create vs. edit.
        """
        # Construct the "middle" list of fields, favoring writable fields first.
        fields_displayed_middle = [
            # Note that dict is guaranteed to preserve insertion order as of Python 3.7
            # https://docs.python.org/3.6/whatsnew/3.6.html#new-dict-implementation
            field for field in dict.fromkeys(self.writable_fields + self.read_only_fields)
            if field not in self.fields_displayed_first + self.fields_displayed_last
        ]

        # Construct preliminary list of all fields to show.
        fields = self.fields_displayed_first + fields_displayed_middle + self.fields_displayed_last

        # For the create page (where obj does not exist), remove any fields not wanted.
        if obj is None:
            for skip_field in self.fields_skip_create:
                fields.remove(skip_field)

        return fields

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

    autocomplete_fields = ['customer_agreement']

    actions = [
        'process_unused_licenses_post_freeze',
        'create_actual_licenses_action',
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'customer_agreement',
        )

    def get_readonly_fields(self, request, obj=None):
        """
        Only allow a few certain fields to be writable if a subscription already exists
        """
        if obj:
            return self.read_only_fields
        return ()

    @admin.display(
        description='Customer Agreement'
    )
    def get_customer_agreement_link(self, obj):
        """
        Returns a link to the customer agreement for this plan.
        """
        if obj.customer_agreement:
            return get_related_object_link(
                'admin:subscriptions_customeragreement_change',
                obj.customer_agreement.uuid,
                obj.customer_agreement.enterprise_customer_slug,
            )
        return ''

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """
        Injects a CustomerAgreement queryset as a real FK in the form.
        """
        if db_field.name == 'customer_agreement':
            kwargs['queryset'] = CustomerAgreement.objects.filter().order_by('enterprise_customer_slug')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.action(
        description='Freeze selected Subscription Plans (deletes unused licenses)'
    )
    def process_unused_licenses_post_freeze(self, request, queryset):
        """
        Used as an action; this function deletes unused licenses after a plan is frozen.
        """
        try:
            with transaction.atomic():
                for subscription_plan in queryset:
                    delete_unused_licenses_post_freeze(subscription_plan)
                messages.add_message(request, messages.SUCCESS, 'Successfully froze selected Subscription Plans.')
        except UnprocessableSubscriptionPlanFreezeError as exc:
            messages.add_message(request, messages.ERROR, exc)

    @admin.action(
        description='Create actual licenses to match desired number'
    )
    def create_actual_licenses_action(self, request, queryset):
        """
        Django action to make the actual number of License records associated with this
        plan match the *desired* number of licenses for the plan.
        """
        for subscription_plan in queryset:
            self._create_actual_licenses(subscription_plan)

        messages.add_message(
            request, messages.SUCCESS, 'Successfully created license records for selected Subscription Plans.',
        )

    def _create_actual_licenses(self, obj):
        """
        Provision any additional licenses if necessary, assuming that the plan
        has not been "frozen"
        """
        if obj.desired_num_licenses and not obj.last_freeze_timestamp:
            license_count_gap = obj.desired_num_licenses - obj.num_licenses
            if license_count_gap > 0:
                if license_count_gap <= PROVISION_LICENSES_BATCH_SIZE:
                    # We can handle just one batch synchronously.
                    SubscriptionPlan.increase_num_licenses(obj, license_count_gap)
                else:
                    # Multiple batches of licenses will need to be created, so provision them asynchronously.
                    provision_licenses_task.delay(subscription_plan_uuid=obj.uuid)

    def save_model(self, request, obj, form, change):
        # Record change reason for simple history
        obj._change_reason = form.cleaned_data.get('change_reason')  # pylint: disable=protected-access

        # If a uuid is not specified on the subscription itself, use the default one for the CustomerAgreement
        customer_agreement_catalog = obj.customer_agreement.default_enterprise_catalog_uuid
        obj.enterprise_catalog_uuid = (obj.enterprise_catalog_uuid or customer_agreement_catalog)

        # If we're creating the model instance, determine the desired number of licenses
        # from the form and store that in the model. This will lead to the eventual creation of those licenses.
        if not change:
            obj.desired_num_licenses = form.cleaned_data.get('num_licenses', 0)

        super().save_model(request, obj, form, change)

        # Finally, if we're creating the model instance, go ahead and create the related license records.
        if not change:
            self._create_actual_licenses(obj)


@admin.register(CustomerAgreement)
class CustomerAgreementAdmin(admin.ModelAdmin):
    form = CustomerAgreementAdminForm

    read_only_fields = (
        'enterprise_customer_uuid',
        'enterprise_customer_slug',
        'enterprise_customer_name',
        'get_subscription_plan_links',
    )
    writable_fields = (
        'default_enterprise_catalog_uuid',
        'disable_expiration_notifications',
        'license_duration_before_purge',
        'disable_onboarding_notifications'
    )
    custom_fields = ('subscription_for_auto_applied_licenses',)

    fields = read_only_fields + writable_fields + custom_fields
    list_display = (
        'uuid',
        'enterprise_customer_uuid',
        'enterprise_customer_slug',
        'enterprise_customer_name',
        'get_subscription_plan_links',
        'disable_expiration_notifications'
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
        'enterprise_customer_slug__istartswith',
        'enterprise_customer_name__istartswith',
    )
    actions = ['sync_agreement_with_enterprise_customer']

    @admin.action(
        description='Sync enterprise customer fields for selected records'
    )
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

    def save_model(self, request, obj, form, change):
        """
        Saves the CustomerAgreement instance.

        Adds a Django error message a ``CustomerAgreementError`` occurred.
        Notably, this happens when the slug field was
        not present and could not be fetched from the enterprise API.
        """
        try:
            if 'subscription_for_auto_applied_licenses' in form.changed_data:
                customer_agreement_uuid = request.resolver_match.kwargs.get('object_id')
                subscription_for_auto_applied_licenses = form.cleaned_data['subscription_for_auto_applied_licenses']
                toggle_auto_apply_licenses(customer_agreement_uuid, subscription_for_auto_applied_licenses)

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
        return (
            'enterprise_customer_slug',
            'license_duration_before_purge',
            'get_subscription_plan_links',
        )

    @admin.display(
        description='Subscription Plans'
    )
    def get_subscription_plan_links(self, obj):
        """
        Gets links to all active subscription plans for this customer agreement.
        """
        links = []
        for subscription_plan in obj.subscriptions.all():
            if subscription_plan.is_active:
                links.append(
                    get_related_object_link(
                        'admin:subscriptions_subscriptionplan_change',
                        subscription_plan.uuid,
                        '{}: {}'.format(subscription_plan.title, subscription_plan.uuid),
                    )
                )
        return mark_safe(' '.join(links))


@admin.register(SubscriptionPlanRenewal)
class SubscriptionPlanRenewalAdmin(DjangoQLSearchMixin, admin.ModelAdmin):
    form = SubscriptionPlanRenewalForm
    readonly_fields = ['renewed_subscription_plan', 'processed', 'processed_datetime']
    raw_id_fields = ['prior_subscription_plan']
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
    search_fields = (
        'prior_subscription_plan__title',
        'prior_subscription_plan__uuid__startswith',
        'prior_subscription_plan__customer_agreement__enterprise_customer_uuid__startswith',
        'prior_subscription_plan__enterprise_catalog_uuid__startswith',
    )
    actions = ['process_renewal']

    @admin.action(
        description='Process selected renewal records'
    )
    def process_renewal(self, request, queryset):
        """
        Process selected renewal records
        """
        for renewal in queryset:
            renew_subscription(renewal)

    @admin.display(
        description='Subscription Title',
        ordering='prior_subscription_plan__title',
    )
    def get_prior_subscription_plan_title(self, obj):
        """
        Returns Subscription Title
        """
        return obj.prior_subscription_plan.title

    @admin.display(
        description='Subscription UUID',
        ordering='prior_subscription_plan__uuid',
    )
    def get_prior_subscription_plan_uuid(self, obj):
        """
        Returns Subscription UUID
        """
        return obj.prior_subscription_plan.uuid

    @admin.display(
        description='Enterprise Customer UUID',
        ordering='prior_subscription_plan__enterprise_customer_uuid',
    )
    def get_prior_subscription_plan_enterprise_customer(self, obj):
        """
        Returns Enterprise Customer UUID
        """
        return obj.prior_subscription_plan.enterprise_customer_uuid

    @admin.display(
        description='Enterprise Catalog UUID',
        ordering='prior_subscription_plan__enterprise_catalog_uuid',
    )
    def get_prior_subscription_plan_enterprise_catalog(self, obj):
        """
        Returns Enterprise Catalog UUID
        """
        return obj.prior_subscription_plan.enterprise_catalog_uuid

    @admin.display(
        description='Renewed Subscription Plan'
    )
    def get_renewed_plan_link(self, obj):
        """
        Returns a link to the renewed subscription plan.
        """
        if obj.renewed_subscription_plan:
            return get_related_object_link(
                'admin:subscriptions_subscriptionplan_change',
                obj.renewed_subscription_plan.uuid,
                '{}: {}'.format(obj.renewed_subscription_plan.title, obj.renewed_subscription_plan.uuid),
            )
        return ''

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


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductForm

    exclude = ['history']
    fields = (
        'name',
        'description',
        'netsuite_id',
        'plan_type',
        'salesforce_product_id',
    )
    list_display = fields
    readonly_fields = ['netsuite_id']
    ordering = (
        'plan_type',
        'name',
        'salesforce_product_id',
        'netsuite_id',
    )
    sortable_by = (
        'name',
        'salesforce_product_id',
        'netsuite_id',
        'plan_type',
    )
    list_filter = (
        'plan_type',
    )
    search_fields = (
        'name',
        'netsuite_id',
        'salesforce_product_id',
    )


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        'enterprise_customer_uuid',
        'enterprise_customer_user_uuid',
        'subscripton_plan_id',
        'notification_type',
        'last_sent',
    )

    list_filter = (
        'notification_type',
    )

    search_fields = (
        'subscripton_plan__uuid__startswith',
    )

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(LicenseTransferJob)
class LicenseTransferJobAdmin(admin.ModelAdmin):
    form = LicenseTransferJobAdminForm

    list_display = (
        'id',
        'customer_agreement',
        'old_subscription_plan',
        'new_subscription_plan',
        'completed_at',
        'is_dry_run',
    )

    list_filter = (
        'is_dry_run',
    )

    autocomplete_fields = ['customer_agreement']

    search_fields = (
        'customer_agreement__enterprise_customer_uuid__startswith',
        'customer_agreement__enterprise_customer_slug__istartswith',
        'customer_agreement__enterprise_customer_name__istartswith',
        'old_subscription_plan',
        'new_subscription_plan',
    )

    sortable_by = (
        'id',
        'completed_at',
        'is_dry_run',
        'customer_agreement',
    )

    actions = ['process_transfer_jobs']

    def get_readonly_fields(self, request, obj=None):
        """
        Makes all fields except ``notes`` read-only
        when ``completed_at`` is not null.
        """
        if obj and obj.completed_at:
            return list(
                # pylint: disable=no-member
                set(self.form.base_fields) - {'notes'}
            )
        else:
            return [
                'completed_at',
                'processed_results',
            ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'customer_agreement',
            'old_subscription_plan',
            'new_subscription_plan',
        )

    @admin.action(description="Process selected license transfer jobs")
    def process_transfer_jobs(self, request, queryset):
        for transfer_job in queryset:
            transfer_job.process()
