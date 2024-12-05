"""
Forms to be used in the subscriptions django app.
"""
import logging

from dal import autocomplete
from django import forms
from django.conf import settings
from django.utils.translation import gettext as _
from durationwidget.widgets import TimeDurationWidget
from requests.exceptions import HTTPError
from rest_framework import status

from license_manager.apps.api_client.enterprise import EnterpriseApiClient
from license_manager.apps.api_client.enterprise_catalog import (
    EnterpriseCatalogApiClient,
)
from license_manager.apps.subscriptions.constants import (
    MAX_NUM_LICENSES,
    MIN_NUM_LICENSES,
    SubscriptionPlanChangeReasonChoices,
    SubscriptionPlanShouldAutoApplyLicensesChoices,
)
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    LicenseTransferJob,
    Product,
    SubscriptionPlan,
    SubscriptionPlanRenewal,
)
from license_manager.apps.subscriptions.utils import (
    localized_utcnow,
    verify_sf_opportunity_product_line_item,
)


logger = logging.getLogger(__name__)


class SubscriptionPlanForm(forms.ModelForm):
    """
    Form used for the SubscriptionPlan admin class.
    """

    should_auto_apply_licenses = forms.ChoiceField(
        choices=SubscriptionPlanShouldAutoApplyLicensesChoices.CHOICES,
        required=False,
        label="Should auto apply licenses",
        help_text=(
            """
            Whether licenses from this Subscription Plan should be auto applied.
            It it possible and acceptable for more than one plan in a single
            customer agreement to have this field enabled.
            """
        )
    )

    # Extra form field to specify the number of licenses to be associated with the subscription plan
    num_licenses = forms.IntegerField(
        label="Number of Licenses",
        required=True,
        min_value=MIN_NUM_LICENSES,
    )

    # Using a HiddenInput widget here allows us to hide the property
    # on the creation form while still displaying the property
    # as read-only on the SubscriptionPlan update form.
    num_revocations_remaining = forms.IntegerField(
        required=False,
        widget=forms.HiddenInput()
    )

    # Extra form field to set reason for changing a subscription plan, data saved in simple history record
    change_reason = forms.ChoiceField(
        choices=SubscriptionPlanChangeReasonChoices.CHOICES,
        required=True,
        label="Reason for change",
    )

    # Override the salesforce_opportunity_line_item help text to be more specific to the subscription plan
    salesforce_opportunity_line_item = forms.CharField(
        help_text=(
            """18 character value that starts with '00k' --
            Locate the appropriate Salesforce Opportunity Line Item record and copy it here."""
        )
    )

    def _validate_enterprise_catalog_uuid(self):
        """
        Verifies that the enterprise customer has a catalog with the given enterprise_catalog_uuid.
        """

        try:
            catalog = EnterpriseCatalogApiClient().get_enterprise_catalog(self.instance.enterprise_catalog_uuid)
            catalog_enterprise_customer_uuid = catalog['enterprise_customer']
            if str(self.instance.enterprise_customer_uuid) != catalog_enterprise_customer_uuid:
                self.add_error(
                    'enterprise_catalog_uuid',
                    'A catalog with the given UUID does not exist for this enterprise customer.',
                )
                return False
            return True
        except HTTPError as ex:
            if ex.response.status_code == status.HTTP_404_NOT_FOUND:
                self.add_error(
                    'enterprise_catalog_uuid',
                    'A catalog with the given UUID does not exist for this enterprise customer.',
                )
            else:
                self.add_error(
                    'enterprise_catalog_uuid',
                    f'Could not verify the given UUID: {ex}. Please try again.',
                )
            return False

    def _log_validation_error(self, message):
        """
        Helper to help us log error messages about validation gone awry.
        """
        logger.error(f'Form Validation failed for {self.instance}: {message}')

    def is_valid(self):
        # Perform original validation and return if false
        if not super().is_valid():
            self._log_validation_error('base validation failed')
            return False

        logger.info(f'More validation of {self.cleaned_data} for plan {self.instance}')
        # Ensure that we are getting an enterprise catalog uuid from the field itself or the linked customer agreement
        # when the subscription is first created.
        if 'customer_agreement' in self.changed_data:
            form_customer_agreement = self.cleaned_data.get('customer_agreement')
            form_enterprise_catalog_uuid = self.cleaned_data.get('enterprise_catalog_uuid')
            if not form_customer_agreement.default_enterprise_catalog_uuid and not form_enterprise_catalog_uuid:
                self._log_validation_error('bad catalog uuid')
                self.add_error(
                    'enterprise_catalog_uuid',
                    'The subscription must have an enterprise catalog uuid from itself or its customer agreement',
                )
                return False

        form_num_licenses = self.cleaned_data.get('num_licenses', 0)
        # Only internal use subscription plans to have more than the maximum number of licenses
        if form_num_licenses > MAX_NUM_LICENSES and not self.instance.for_internal_use_only:
            self._log_validation_error('exceeded max licenses')
            self.add_error(
                'num_licenses',
                f'Non-test subscriptions may not have more than {MAX_NUM_LICENSES} licenses',
            )
            return False

        # Ensure the revoke max percentage is between 0 and 100
        if self.instance.is_revocation_cap_enabled and self.instance.revoke_max_percentage > 100:
            self._log_validation_error('bad max revoke settings')
            self.add_error('revoke_max_percentage', 'Must be a valid percentage (0-100).')
            return False

        product = self.cleaned_data.get('product')

        if not product:
            self._log_validation_error('no product specified')
            self.add_error(
                'product',
                'You must specify a product.',
            )
            return False

        if (
                product.plan_type.sf_id_required
                and self.cleaned_data.get('salesforce_opportunity_line_item') is None
                or not verify_sf_opportunity_product_line_item(self.cleaned_data.get(
                'salesforce_opportunity_line_item'))
        ):
            self._log_validation_error('no SF ID')
            self.add_error(
                'salesforce_opportunity_line_item',
                'You must specify Salesforce ID for selected product. It must start with \'00k\'.',
            )
            return False

        if settings.VALIDATE_FORM_EXTERNAL_FIELDS and self.instance.enterprise_catalog_uuid and \
                not self._validate_enterprise_catalog_uuid():
            self._log_validation_error('bad catalog uuid validation')
            return False

        return True

    class Meta:
        model = SubscriptionPlan
        fields = '__all__'


class SubscriptionPlanRenewalForm(forms.ModelForm):
    """
    Form for the renewal Django admin class.
    """
    # Using a HiddenInput widget here allows us to hide the property
    # on the creation form while still displaying the property
    # as read-only on the SubscriptionPlanRenewalForm update form.
    renewed_subscription_plan = forms.IntegerField(
        required=False,
        widget=forms.HiddenInput()
    )

    salesforce_opportunity_id = forms.CharField(
        help_text=(
            "Locate the appropriate Salesforce Opportunity record and copy the Opportunity ID field "
            "(18 characters and begin with '00k')."
            " Note that this is not the same Salesforce Opportunity ID associated with the linked subscription."
        )
    )

    def is_valid(self):
        # Perform original validation and return if false
        if not super().is_valid():
            return False

        # Subscription dates should follow this ordering:
        # subscription start date <= subscription expiration date <= subscription renewal effective date <=
        # subscription renewal expiration date
        form_effective_date = self.cleaned_data.get('effective_date')
        form_renewed_expiration_date = self.cleaned_data.get('renewed_expiration_date')
        form_future_salesforce_opportunity_line_item = self.cleaned_data.get('salesforce_opportunity_id')

        if form_effective_date < localized_utcnow():
            self.add_error(
                'effective_date',
                'A subscription renewal can not be scheduled to become effective in the past.',
            )
            return False

        if form_renewed_expiration_date < form_effective_date:
            self.add_error(
                'renewed_expiration_date',
                'A subscription renewal can not expire before it becomes effective.',
            )
            return False

        subscription = self.instance.prior_subscription_plan
        if form_effective_date < subscription.expiration_date:
            self.add_error(
                'effective_date',
                'A subscription renewal can not take effect before a subscription expires.',
            )
            return False

        if form_future_salesforce_opportunity_line_item is None or \
                not verify_sf_opportunity_product_line_item(form_future_salesforce_opportunity_line_item):
            self.add_error(
                'salesforce_opportunity_id',
                'You must specify Salesforce ID for the renewed product. It must start with \'00k\'.',
            )
            return False

        return True

    class Meta:
        model = SubscriptionPlanRenewal
        fields = '__all__'


class CustomerAgreementAdminForm(forms.ModelForm):
    """
    Helps convert the unuseful database value, stored in microseconds,
    of ``license_duration_before_purge`` to a useful value, and vica versa.
    """

    # Hide this field when creating a new CustomerAgreement
    subscription_for_auto_applied_licenses = forms.ChoiceField(
        required=False,
        widget=forms.HiddenInput()
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if 'instance' in kwargs:
            instance = kwargs['instance']
            if instance:
                self.populate_subscription_for_auto_applied_licenses_choices(instance)

    def populate_subscription_for_auto_applied_licenses_choices(self, instance):
        """
        Populates the choice field used to choose which plan
        is used for auto-applied licenses in a Customer Agreement.
        """
        now = localized_utcnow()
        active_plans = SubscriptionPlan.objects.filter(
            customer_agreement=instance,
            is_active=True,
            start_date__lte=now,
            expiration_date__gte=now
        )
        current_plan = instance.auto_applicable_subscription
        empty_choice = ('', '------')
        choices = [empty_choice] + [(plan.uuid, plan.title) for plan in active_plans]
        choice_field = forms.ChoiceField(
            choices=choices,
            required=False,
            initial=empty_choice if not current_plan else (current_plan.uuid, current_plan.title),
            help_text=(
                """
                The subscription plan from which licenses will be auto-applied, if any.
                If you do not manually modify this field, it will be automatically set, chosen as the
                most recently started plan that is active, current, and has 'should_auto_apply_licenses'
                set to true. Manually selecting/modifying the plan for this field will have two effects:
                It will automatically enable the \"Should auto apply licenses\" field on the selected plan,
                and it will automatically *disable* that field on all other plans
                associated with this customer agreement.
                """
            ),
        )
        self.fields['subscription_for_auto_applied_licenses'] = choice_field

    def _validate_enterprise_customer_uuid(self):
        """
        Verifies that a customer with the given enterprise_customer_uuid exists
        """
        enterprise_customer_uuid = self.instance.enterprise_customer_uuid
        try:
            customer_data = EnterpriseApiClient().get_enterprise_customer_data(
                enterprise_customer_uuid
            )
            self.instance.enterprise_customer_slug = customer_data.get('slug')
            self.instance.enterprise_customer_name = customer_data.get('name')
            return True
        except HTTPError as ex:
            logger.exception(f'Could not validate enterprise_customer_uuid {enterprise_customer_uuid}.')
            if ex.response.status_code == status.HTTP_404_NOT_FOUND:
                self.add_error(
                    'enterprise_customer_uuid',
                    f'An enterprise customer with uuid: {enterprise_customer_uuid} does not exist.',
                )
            else:
                self.add_error(
                    'enterprise_customer_uuid',
                    f'Could not verify the given UUID: {ex}. Please try again.',
                )

            return False

    def _validate_default_enterprise_catalog_uuid(self):
        """
        Verifies that the enterprise customer has a catalog with the given default_enterprise_catalog_uuid.
        """
        default_enterprise_catalog_uuid = self.instance.default_enterprise_catalog_uuid

        if not default_enterprise_catalog_uuid:
            return True

        try:
            catalog = EnterpriseCatalogApiClient().get_enterprise_catalog(default_enterprise_catalog_uuid)
            catalog_enterprise_customer_uuid = catalog['enterprise_customer']
            if str(self.instance.enterprise_customer_uuid) != catalog_enterprise_customer_uuid:
                self.add_error(
                    'default_enterprise_catalog_uuid',
                    'A catalog with the given UUID does not exist for this enterprise customer.',
                )
                return False
            return True
        except HTTPError as ex:
            logger.exception(f'Could not validate default_enterprise_catalog_uuid {default_enterprise_catalog_uuid}.')
            if ex.response.status_code == status.HTTP_404_NOT_FOUND:
                self.add_error(
                    'default_enterprise_catalog_uuid',
                    'A catalog with the given UUID does not exist for this enterprise customer.',
                )
            else:
                self.add_error(
                    'default_enterprise_catalog_uuid',
                    f'Could not verify the given UUID: {ex}. Please try again.',
                )
            return False

    def is_valid(self):
        # Perform original validation and return if false
        if not super().is_valid():
            return False

        if settings.VALIDATE_FORM_EXTERNAL_FIELDS:
            if not all([
                self._validate_enterprise_customer_uuid(),
                self._validate_default_enterprise_catalog_uuid()
            ]):
                return False

        return True

    class Meta:
        model = CustomerAgreement
        fields = '__all__'

    license_duration_before_purge = forms.DurationField(
        widget=TimeDurationWidget(
            show_days=True,
            show_hours=False,
            show_minutes=False,
            show_seconds=False,
        ),
        help_text=_(
            "The number of days after which unclaimed, revoked, or expired (due to plan expiration) licenses "
            "associated with this customer agreement will have user data retired "
            "and the license status reset to UNASSIGNED."
        ),
    )


class ProductForm(forms.ModelForm):
    """
    Form for the Product Django admin class.
    """
    class Meta:
        model = Product
        fields = '__all__'

    def is_valid(self):
        # Perform original validation and return if false
        if not super().is_valid():
            return False

        if self.instance.plan_type.ns_id_required and not self.instance.netsuite_id:
            self.add_error(
                'netsuite_id',
                'You must specify Netsuite ID for selected plan type.',
            )
            return False

        return True


class LicenseTransferJobAdminForm(forms.ModelForm):
    class Meta:
        model = LicenseTransferJob
        fields = [
            'customer_agreement',
            'old_subscription_plan',
            'new_subscription_plan',
            'notes',
            'is_dry_run',
            'transfer_all',
            'delimiter',
            'license_uuids_raw',
            'completed_at',
            'processed_results',
        ]
        # Use django-autocomplete-light to filter the available
        # subscription_plan choices to only those related to
        # the selected customer agreement.  Works for both
        # records that don't yet exist (on transfer job creation)
        # and for modification of existing transfer job records.
        # See urls_admin.py for the view that does this filtering,
        # and see static/filtered_subscription_admin.js for
        # the jQuery code that clears subscription plan selections
        # when the selected customer agreement is changed.
        widgets = {
            'old_subscription_plan': autocomplete.ModelSelect2(
                url='filtered_subscription_plan_admin',
                # forward the customer_agreement field's value
                # into our custom autocomplete field in urls_admin.py
                forward=['customer_agreement'],
            ),
            'new_subscription_plan': autocomplete.ModelSelect2(
                url='filtered_subscription_plan_admin',
                # forward the customer_agreement field's value
                # into our custom autocomplete field in urls_admin.py
                forward=['customer_agreement'],
            ),
        }

    class Media:
        js = (
            'filtered_subscription_admin.js',
        )
