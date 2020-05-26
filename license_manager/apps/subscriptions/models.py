from uuid import uuid4

from django.db import models
from django.utils.translation import gettext as _
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords

from license_manager.apps.subscriptions.constants import (
    LICENSE_STATUS_CHOICES,
    UNASSIGNED,
)


class SubscriptionPlan(TimeStampedModel):
    """
    Stores top-level information related to a Subscriptions purchase.

    We allow enterprise_customer_uuid and enterprise_catalog_uuid to be NULL to support the
    potential future use of subscriptions for non-enterprise customers.

    .. no_pii: This model has no PII
    """
    uuid = models.UUIDField(
        primary_key=True,
        default=uuid4,
        editable=False
    )

    purchase_date = models.DateField(
        blank=True,
        null=True,
    )

    start_date = models.DateField(
        blank=True,
        null=True,
    )

    expiration_date = models.DateField(
        blank=True,
        null=True,
    )

    enterprise_customer_uuid = models.UUIDField(
        blank=True,
        null=True,
        db_index=True,
    )

    enterprise_catalog_uuid = models.UUIDField(
        blank=True,
        null=True,
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

    .. pii: Stores email address and user id (from the lms) for a user. The email could potentially
    be for a customer who is not yet an edx user. Note: We are currently working on the plan of how
    to retire this pii, but are proceeding for the moment as we have no user data in stage or
    production. Marking as `local_api` for now as that is likely the retirement solution we will
    take.
    .. pii_types: id,email_address
    .. pii_retirement: local_api
    """
    uuid = models.UUIDField(
        primary_key=True,
        default=uuid4,
        editable=False
    )

    status = models.CharField(
        max_length=25,
        blank=False,
        null=False,
        choices=LICENSE_STATUS_CHOICES,
        default=UNASSIGNED,
        help_text=_(
            "The status fields has the following options and definitions:"
            "\nActive: A license which has been created, assigned to a learner, and the learner has activated the"
            " license. The license also must not have expired."
            "\nAssigned: A license which has been created and assigned to a learner, but which has not yet been"
            " activated by that learner."
            "\nUnassigned: A license which has been created but does not have a learner assigned to it."
            "\nDeactivated: A license which has been created but is no longer active (intentionally made inactive or"
            " has expired). A license in this state may or may not have a learner assigned."
        )
    )

    activation_date = models.DateTimeField(
        blank=True,
        null=True,
    )

    last_remind_date = models.DateTimeField(
        blank=True,
        null=True,
    )

    user_email = models.EmailField(
        blank=True,
        null=True,
    )

    lms_user_id = models.IntegerField(
        blank=True,
        null=True,
    )

    subscription_plan = models.ForeignKey(
        SubscriptionPlan,
        related_name='licenses',
        on_delete=models.CASCADE,
    )

    history = HistoricalRecords()

    class Meta:
        unique_together = (
            ('subscription_plan', 'user_email'),
            ('subscription_plan', 'lms_user_id'),
        )

    def __str__(self):
        """
        Return human-readable string representation.
        """
        return (
            "<License with UUID '{uuid}' "
            "for SubscriptionPlan'{subscription_plan_uuid}'>".format(
                uuid=self.uuid,
                subscription_plan_uuid=self.subscription_plan.uuid,
            )
        )
