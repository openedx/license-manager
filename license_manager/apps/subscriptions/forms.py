"""
Forms to be used in the subscriptions django app.
"""
from datetime import datetime

from django import forms

from license_manager.apps.subscriptions.constants import MAX_NUM_LICENSES
from license_manager.apps.subscriptions.models import (
    SubscriptionPlan,
    SubscriptionPlanRenewal,
)


class SubscriptionPlanForm(forms.ModelForm):
    # Extra form field to specify the number of licenses to be associated with the subscription plan
    num_licenses = forms.IntegerField(label="Number of Licenses", required=False)

    # Using a HidenInput widget here allows us to hide the property
    # on the creation form while still displaying the property
    # as read-only on the SubscriptionPlan update form.
    num_revocations_remaining = forms.IntegerField(
        required=False,
        widget=forms.HiddenInput()
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['num_licenses'].initial = self.instance.num_licenses

    def is_valid(self):
        # Perform original validation and return if false
        if not super().is_valid():
            return False

        form_num_licenses = self.cleaned_data.get('num_licenses', 0)
        # Only internal use subscription plans to have more than the maximum number of licenses
        if form_num_licenses > MAX_NUM_LICENSES and not self.instance.for_internal_use_only:
            self.add_error(
                'num_licenses',
                f'Non-test subscriptions may not have more than {MAX_NUM_LICENSES} licenses',
            )
            return False

        # Ensure the number of licenses is not being decreased
        if form_num_licenses < self.instance.num_licenses:
            self.add_error('num_licenses', 'Number of Licenses cannot be decreased.')
            return False

        # Ensure the revoke max percentage is between 0 and 100
        if self.instance.revoke_max_percentage > 100:
            self.add_error('revoke_max_percentage', 'Must be a valid percentage (0-100).')
            return False

        return True

    class Meta:
        model = SubscriptionPlan
        fields = '__all__'


class SubscriptionPlanRenewalForm(forms.ModelForm):
    # Using a HidenInput widget here allows us to hide the property
    # on the creation form while still displaying the property
    # as read-only on the SubscriptionPlanRenewalForm update form.
    renewed_subscription_plan = forms.IntegerField(
        required=False,
        widget=forms.HiddenInput()
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def is_valid(self):
        # Perform original validation and return if false
        if not super().is_valid():
            return False

        # Subscription dates should follow this ordering:
        # subscription start date <= subscription expiration date <= subscription renewal effective date <=
        # subscription renewal expiration date
        form_effective_date = self.cleaned_data.get('effective_date')
        form_renewed_expiration_date = self.cleaned_data.get('renewed_expiration_date')

        if form_effective_date < datetime.today().date():
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

        return True

    class Meta:
        model = SubscriptionPlanRenewal
        fields = '__all__'
