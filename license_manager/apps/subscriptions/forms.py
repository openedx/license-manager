# -*- coding: utf-8 -*-
"""
Forms to be used in the subscriptions django app.
"""
from __future__ import absolute_import, unicode_literals

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext

from license_manager.apps.subscriptions.models import License, SubscriptionPlan


class SubscriptionPlanForm(forms.ModelForm):
    num_licenses = forms.IntegerField(label="Number of Licenses", required=False)

    def __init__(self, *args, **kwargs):
        super(SubscriptionPlanForm, self).__init__(*args, **kwargs)
        self.calc_num_licenses = 0
        if hasattr(self, 'instance'):
            self.calc_num_licenses = self.instance.calc_num_licenses
        self.fields['num_licenses'].initial = self.calc_num_licenses

    def save(self, commit=True):
        num_licenses = self.cleaned_data.get('num_licenses', None)
        if num_licenses < self.calc_num_licenses:
            raise ValidationError(
                gettext('Invalid value: %(value)s'),
                code='cannot decrease num_licenses',
                params={'value': num_licenses}
            )
        else:
            num_new_licenses = num_licenses - self.calc_num_licenses
        subscription_uuid = super(SubscriptionPlanForm, self).save(commit=commit)
        for _ in range(num_new_licenses):
            lic = License(subscription_plan=subscription_uuid)
            lic.save()
        return subscription_uuid

    class Meta:
        model = SubscriptionPlan
        fields = '__all__'
