"""
Forms to be used in the subscriptions django app.
"""
from __future__ import absolute_import, unicode_literals

from django import forms

from license_manager.apps.subscriptions.models import License, SubscriptionPlan


class SubscriptionPlanForm(forms.ModelForm):
    # Extra form field to specify the number of licenses to be associated with the subscription plan
    num_licenses = forms.IntegerField(label="Number of Licenses", required=False)

    def __init__(self, *args, **kwargs):
        super(SubscriptionPlanForm, self).__init__(*args, **kwargs)
        self.fields['num_licenses'].initial = self.instance.calc_num_licenses

    def save(self, commit=True):
        subscription_uuid = super(SubscriptionPlanForm, self).save(commit=commit)
        # Create licenses to be associated with the subscription plan
        num_new_licenses = self.cleaned_data.get('num_licenses', 0) - self.instance.calc_num_licenses
        new_licenses = [License(subscription_plan=subscription_uuid) for _ in range(num_new_licenses)]
        License.objects.bulk_create(new_licenses)
        return subscription_uuid

    def is_valid(self):
        # Perform original validation and return if false
        if not super(SubscriptionPlanForm, self).is_valid():
            return False
        # Ensure the number of licenses is not being decreased
        if self.cleaned_data.get('num_licenses', 0) < self.instance.calc_num_licenses:
            self.add_error('num_licenses', 'Number of Licenses cannot be decreased.')
            return False
        return True

    class Meta:
        model = SubscriptionPlan
        fields = '__all__'
