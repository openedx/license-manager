from uuid import uuid4

from django.db import models
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords

from license_manager.apps.subscriptions import models as subs_models


class SubsidyRequest(TimeStampedModel):
    uuid = models.UUIDField(
        primary_key=True,
        default=uuid4,
        editable=False,
        unique=True,
    )
    lms_user_id = models.IntegerField()
    customer_agreement = models.ForeignKey(
        subs_models.CustomerAgreement,
        on_delete=models.CASCADE,
    )
    customer_uuid = models.UUIDField()  # For analytics

    @classmethod
    def create(cls, lms_user_id, customer_agreement, course_id=None):
        """
        This really belongs in an ``api.py`` module.
        """
        kwargs = {
            'lms_user_id': lms_user_id,
            'customer_agreement': customer_agreement,
            'customer_uuid': customer_agreement.enterprise_customer_uuid,
        }
        if course_id:
            kwargs['course_id'] = course_id

        if customer_agreement.primary_subsidy_type == 'SUBSCRIPTION':
            return LicenseRequest.objects.create(**kwargs)
        elif customer_agreement.primary_subsidy_type == 'COUPON':
            # will balk if course_id is falsey.
            return CouponCodeRequest.objects.create(**kwargs)

    def is_approvable(self):
        raise NotImplementedError

    def approve(self, *args, **kwargs):
        raise NotImplementedError

    def deny(self, admin_lms_user_id, reason):
        """ really belongs in ``api.py`` module."""
        return SubsidyRequestDenial.objects.create(
            admin_lms_user_id,
            request=self,
            reason=reason,
        )

    class Meta:
        abstract = True


class LicenseRequest(SubsidyRequest):
    course_id = models.CharField(null=True, max_length=128)
    history = HistoricalRecords()

    def is_approvable(self):
        """
        Check related agreement subscription plan(s) for available licenses.
        This should act as a "convenience" method and actually call an ``api.py`` function
        """

    def approve(self, admin_lms_user_id, assigned_license):
        return LicenseRequestApproval.objects.create(
            responding_lms_user_id=admin_lms_user_id,
            request=self,
            assigned_license=assigned_license,
        )


class CouponCodeRequest(SubsidyRequest):
    course_id = models.CharField(null=False, max_length=128)
    history = HistoricalRecords()

    def is_approvable(self):
        """
        Check enterprise for /offers in ecommerce.
        This should act as a "convenience" method and actually call an ``api.py`` function
        """

    def approve(self, admin_lms_user_id, offer_id, coupon_code):
        return CouponCodeRequestApproval.objects.create(
            responding_lms_user_id=admin_lms_user_id,
            request=self,
            offer_id=offer_id,
            coupon_code=coupon_code,
        )


class SubsidyRequestResponse(TimeStampedModel):
    uuid = models.UUIDField(
        primary_key=True,
        default=uuid4,
        editable=False,
        unique=True,
    )
    responding_lms_user_id = models.IntegerField()

    class Meta:
        abstract = True



class LicenseRequestDenial(SubsidyRequestResponse):
    reason = models.TextField(null=False)
    request = models.OneToOneField(
        LicenseRequest,
        on_delete=models.CASCADE,
    )


    history = HistoricalRecords()


class CouponCodeRequestDenial(SubsidyRequestResponse):
    reason = models.TextField(null=False)
    request = models.OneToOneField(
        CouponCodeRequest,
        on_delete=models.CASCADE,
    )

    history = HistoricalRecords()


class LicenseRequestApproval(SubsidyRequestResponse):
    assigned_license = models.OneToOneField(
        subs_models.License,
        related_name='request_approval',
        on_delete=models.CASCADE,
    )
    request = models.OneToOneField(
        LicenseRequest,
        on_delete=models.CASCADE,
    )

    history = HistoricalRecords()


class CouponCodeRequestApproval(SubsidyRequestResponse):
    offer_id = models.IntegerField()  # store the offer ID.
    coupon_code = models.CharField(null=False, blank=False, max_length=128)
    request = models.OneToOneField(
        CouponCodeRequest,
        on_delete=models.CASCADE,
    )

    history = HistoricalRecords()
