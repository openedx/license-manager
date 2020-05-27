from django.contrib import admin

from license_manager.apps.subscriptions.forms import SubscriptionPlanForm
from license_manager.apps.subscriptions.models import License, SubscriptionPlan


@admin.register(License)
class LicenseAdmin(admin.ModelAdmin):
    exclude = ['history']


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    form = SubscriptionPlanForm

    fieldsets = (
        (None, {
            'fields': ('purchase_date',
                       'start_date',
                       'expiration_date',
                       'enterprise_customer_uuid',
                       'enterprise_catalog_uuid',
                       'num_licenses',
                       ),
        }),
    )
