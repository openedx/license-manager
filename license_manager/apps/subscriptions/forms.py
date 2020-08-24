"""
Forms to be used in the subscriptions django app.
"""
from django import forms

from license_manager.apps.subscriptions.constants import MAX_NUM_LICENSES
from license_manager.apps.subscriptions.models import SubscriptionPlan


class SubscriptionPlanForm(forms.ModelForm):
    # Extra form field to specify the number of licenses to be associated with the subscription plan
    num_licenses = forms.IntegerField(label="Number of Licenses", required=False)

    def __init__(self, *args, **kwargs):
        super(SubscriptionPlanForm, self).__init__(*args, **kwargs)
        self.fields['num_licenses'].initial = self.instance.num_licenses

    def is_valid(self):
        # Perform original validation and return if false
        if not super(SubscriptionPlanForm, self).is_valid():
            return False

        form_num_licenses = self.cleaned_data.get('num_licenses', 0)
        # Only internal use subscription plans to have more than the maximum number of licenses
        if form_num_licenses > MAX_NUM_LICENSES and not self.instance.for_internal_use_only:
            self.add_error(
                'num_licenses',
                'Non-test subscriptions may not have more than {} licenses'.format(MAX_NUM_LICENSES),
            )
            return False

        # Ensure the number of licenses is not being decreased
        if form_num_licenses < self.instance.num_licenses:
            self.add_error('num_licenses', 'Number of Licenses cannot be decreased.')
            return False

        return True

    class Meta:
        model = SubscriptionPlan
        fields = '__all__'
