from django.contrib import admin

from license_manager.apps.subsidy_request import models


class BaseRequestAdmin:
    read_only_fields = ('uuid', 'customer_uuid')
    fields = (
        'lms_user_id',
        'customer_agreement',
        'course_id',
    )


@admin.register(models.LicenseRequest)
class LicenseRequestAdmin(BaseRequestAdmin, admin.ModelAdmin):
    """
    """

@admin.register(models.CouponCodeRequest)
class CouponCodeRequestAdmin(BaseRequestAdmin, admin.ModelAdmin):
    """
    """
