from django.contrib import admin

from license_manager.apps.subscriptions.forms import SubscriptionPlanForm
from license_manager.apps.subscriptions.models import License, SubscriptionPlan


@admin.register(License)
class LicenseAdmin(admin.ModelAdmin):
    exclude = ['history']


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    form = SubscriptionPlanForm
    fields = ('purchase_date',
              'start_date',
              'expiration_date',
              'enterprise_customer_uuid',
              'enterprise_catalog_uuid',
              'num_licenses',
              'is_active',
              )

    # If subscription already exists, make all fields but num_licenses read-only
    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ['purchase_date',
                    'start_date',
                    'expiration_date',
                    'enterprise_customer_uuid',
                    'enterprise_catalog_uuid']
        return []
