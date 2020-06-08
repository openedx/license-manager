from django.contrib import admin

from license_manager.apps.subscriptions.forms import SubscriptionPlanForm
from license_manager.apps.subscriptions.models import License, SubscriptionPlan


@admin.register(License)
class LicenseAdmin(admin.ModelAdmin):
    exclude = ['history']


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    form = SubscriptionPlanForm
    # This is not to be confused with readonly_fields of the BaseModelAdmin class
    read_only_fields = (
        'title',
        'purchase_date',
        'start_date',
        'expiration_date',
        'enterprise_customer_uuid',
        'enterprise_catalog_uuid',
    )
    writable_fields = (
        'num_licenses',
        'is_active',
    )
    fields = read_only_fields + writable_fields

    def get_readonly_fields(self, request, obj=None):
        """
        If subscription already exists, make all fields but num_licenses and is_active read-only
        """
        if obj:
            return self.read_only_fields
        return ()
