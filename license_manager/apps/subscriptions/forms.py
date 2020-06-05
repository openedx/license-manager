"""
Forms to be used in the subscriptions django app.
"""
import datetime as dt

from django import forms

from license_manager.apps.subscriptions.models import SubscriptionPlan


class SubscriptionPlanForm(forms.ModelForm):
    # Extra form field to specify the number of licenses to be associated with the subscription plan
    num_licenses = forms.IntegerField(label="Number of Licenses", required=False, max_value=1000)

    def __init__(self, *args, **kwargs):
        super(SubscriptionPlanForm, self).__init__(*args, **kwargs)
        self.fields['num_licenses'].initial = self.instance.num_licenses

    def save(self, commit=True):
        subscription_uuid = super(SubscriptionPlanForm, self).save(commit=commit)
        # Create licenses to be associated with the subscription plan
        num_new_licenses = self.cleaned_data.get('num_licenses', 0) - self.instance.num_licenses
        SubscriptionPlan.increase_num_licenses(self.instance, num_new_licenses)
        return subscription_uuid

    def is_valid(self):
        # Perform original validation and return if false
        if not super(SubscriptionPlanForm, self).is_valid():
            return False

        # Ensure the number of licenses is not being decreased
        if self.cleaned_data.get('num_licenses', 0) < self.instance.num_licenses:
            self.add_error('num_licenses', 'Number of Licenses cannot be decreased.')
            return False

        # Ensure the expiration date is at least one year after start date if has been submitted
        expiration_date = self.cleaned_data.get('expiration_date')
        start_date = self.cleaned_data.get('start_date')
        if expiration_date and start_date:
            if expiration_date < start_date + dt.timedelta(days=365):
                self.add_error('expiration_date', 'Expiration Date must be at least a year after the Start Date.')
                return False

        return True

    class Meta:
        model = SubscriptionPlan
        fields = '__all__'
