from uuid import uuid4
from logging import getLogger

from django.conf import settings
from django.db import models
from django.utils.translation import gettext as _
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords


LOGGER = getLogger(__name__)


class SubscriptionPlan(TimeStampedModel):
    """
    Stores top-level information related to a Subscriptions purchase.

    .. no_pii:
    """
    uuid = models.UUIDField(
        primary_key=True,
        default=uuid4,
        editable=False
    )

    purchase_date = models.DateField(
        blank=False,
        null=False,
    )

    expiration_date = models.DateField(
        blank=False,
        null=False,
    )

    enterprise_customer_uuid = models.UUIDField(
        blank=True,
        null=False,
        db_index=True,
    )

    enterprise_catalog_uuid = models.UUIDField(
        blank=True,
        null=False,
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Subscription Plan")
        verbose_name_plural = _("Subscription Plans")
        app_label = 'subscriptions'

    def __str__(self):
        """
        Return human-readable string representation.
        """
        return (
            "<SubscriptionPlan with UUID '{uuid}' "
            "for EnterpriseCustomer '{enterprise_customer_uuid}'>".format(
                uuid=self.uuid,
                enterprise_customer_uuid=self.enterprise_customer_uuid
            )
        )


class License(TimeStampedModel):
    """
    Stores information related to an individual subscriptions license.

    .. no_pii:
    """
    uuid = models.UUIDField(
        primary_key=True,
        default=uuid4,
        editable=False
    )

    ACTIVATED = 'activated'
    ASSIGNED = 'assigned'
    EMAIL_PENDING = 'email_pending'
    UNASSIGNED = 'unassigned'
    LICENSE_STATUS_CHOICES = (
        (ACTIVATED, 'Activated'),
        (ASSIGNED, 'Assigned'),
        (EMAIL_PENDING, 'Assignment Email Pending'),
        (UNASSIGNED, 'Unassigned'),
    )

    status = models.CharField(
        max_length=25,
        blank=False,
        null=False,
        choices=LICENSE_STATUS_CHOICES,
        default=UNASSIGNED,
    )

    start_date = models.DateField(
        blank=False,
        null=False,
    )

    activation_date = models.DateTimeField(
        blank=True,
        null=False,
    )

    last_remind_date = models.DateTimeField(
        blank=True,
        null=False,
    )

    user_email = models.EmailField(
        blank=False,
        null=False,
    )

    lms_user_id = models.IntegerField(
        blank=True,
        null=True,
    )

    subscription_plan_uuid = models.ForeignKey('subscriptions.SubscriptionPlan', on_delete=models.CASCADE)

    history = HistoricalRecords()
