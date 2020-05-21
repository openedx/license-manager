from django.contrib import admin

from license_manager.apps.subscriptions.models import (
    License,
    SubscriptionPlan,
)


@admin.register(License)
class LicenseAdmin(admin.ModelAdmin):
    exclude = ['history']


@admin.register(SubscriptionPlan)
class SubscriptionPlan(admin.ModelAdmin):
    exclude = ['history']
