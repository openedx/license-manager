import datetime
from math import ceil
from uuid import uuid4

from django.core.validators import MinLengthValidator
from django.db import models
from django.utils.translation import gettext as _
from edx_rbac.models import UserRole, UserRoleAssignment
from edx_rbac.utils import ALL_ACCESS_CONTEXT
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords

from license_manager.apps.api_client.enterprise_catalog import (
    EnterpriseCatalogApiClient,
)
from license_manager.apps.subscriptions.constants import (
    ACTIVATED,
    ASSIGNED,
    LICENSE_BULK_OPERATION_BATCH_SIZE,
    LICENSE_STATUS_CHOICES,
    REVOKED,
    SALESFORCE_ID_LENGTH,
    UNASSIGNED,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


class SubscriptionPlan(TimeStampedModel):
    """
    Stores top-level information related to a Subscriptions purchase.

    We allow enterprise_customer_uuid and enterprise_catalog_uuid to be NULL to support the
    potential future use of subscriptions for non-enterprise customers.

    .. no_pii: This model has no PII
    """
    title = models.CharField(
        max_length=128,
        blank=False,
        null=False,
    )

    uuid = models.UUIDField(
        primary_key=True,
        default=uuid4,
        editable=False
    )

    start_date = models.DateField()

    expiration_date = models.DateField()

    @property
    def days_until_expiration(self):
        """
        Returns the number of days remaining until a subscription expires.

        Note: expiration_date is a required field so checking for None isn't needed.
        """
        today = datetime.date.today()
        diff = self.expiration_date - today
        return diff.days

    enterprise_customer_uuid = models.UUIDField(
        blank=True,
        null=True,
        db_index=True,
    )

    enterprise_catalog_uuid = models.UUIDField(
        blank=True,
        null=True,
    )

    is_active = models.BooleanField(
        default=False
    )

    revoke_max_percentage = models.PositiveSmallIntegerField(
        blank=True,
        default=5,
        help_text=(
            "Percentage of Licenses that can be revoked for this SubscriptionPlan."
        ),
    )

    num_revocations_applied = models.PositiveIntegerField(
        blank=True,
        default=0,
        verbose_name="Number of Revocations Applied",
        help_text="Number of revocations applied to Licenses for this SubscriptionPlan.",
    )

    @property
    def num_revocations_remaining(self):
        """
        Gets the number of revocations that can still be made against this SubscriptionPlan.

        Note: This value is rounded up.
        """
        num_revocations_allowed = ceil(self.num_licenses * (self.revoke_max_percentage / 100))
        return num_revocations_allowed - self.num_revocations_applied
    num_revocations_remaining.fget.short_description = "Number of Revocations Remaining"

    salesforce_opportunity_id = models.CharField(
        max_length=SALESFORCE_ID_LENGTH,
        validators=[MinLengthValidator(SALESFORCE_ID_LENGTH)],
        blank=False,
        null=False,
        help_text=_(
            "Locate the appropriate Salesforce Opportunity record and copy the Opportunity ID field (18 characters)."
        )
    )

    netsuite_product_id = models.IntegerField(
        help_text=_(
            "Locate the Sales Order record in NetSuite and copy the Product ID field (numeric)."
        )
    )

    for_internal_use_only = models.BooleanField(
        default=False,
        help_text=_(
            "Whether this SubscriptionPlan is only for internal use (e.g. a test Subscription record)."
        )
    )

    @property
    def unassigned_licenses(self):
        """
        Gets all of the unassigned licenses associated with the subscription.

        Returns:
            Queryset
        """
        return self.licenses.filter(status=UNASSIGNED)

    @property
    def num_licenses(self):
        """
        Gets the number of licenses associated with the subscription excluding revoked licenses.

        We exclude revoked licenses from this "total" license count as a new, unassigned license is created
        whenever a license is revoked. Excluding revoked licenses thus makes sure that the total count of
        licenses remains the same when one is revoked (and the revoked one no longer factors into the
        allocated) count.

        Returns:
            int
        """
        return self.licenses.exclude(status=REVOKED).count()

    @property
    def num_allocated_licenses(self):
        """
        Gets the number of allocated licenses associated with the subscription. A license is defined as allocated if it
        has either been activated by a user, or assigned to a user. We exclude revoked licenses from our definition
        of allocated as we in practice allow allocating more licenses to make up for the revoked one. This is done
        by the creation of a new, unassigned license whenever a license is revoked.

        Returns:
        int: The count of how many licenses that are associated with the subscription plan are
            already allocated.
        """
        return self.licenses.filter(status__in=(ACTIVATED, ASSIGNED)).count()

    def increase_num_licenses(self, num_new_licenses):
        """
        Method to increase the number of licenses associated with an instance of SubscriptionPlan by num_new_licenses.
        """
        new_licenses = [License(subscription_plan=self) for _ in range(num_new_licenses)]
        License.objects.bulk_create(new_licenses, batch_size=LICENSE_BULK_OPERATION_BATCH_SIZE)

    def contains_content(self, content_ids):
        """
        Checks whether the subscription contains the given content by checking against its linked enterprise catalog.

        If a subscription "contains" a particular piece of content, that means a license for this plan can be used to
        access that content.

        Arguments:
            content_ids (list of str): List of content ids to check whether the subscription contains.

        Returns:
            bool: Whether the given content_ids are part of the subscription.
        """
        enterprise_catalog_client = EnterpriseCatalogApiClient()
        content_in_catalog = enterprise_catalog_client.contains_content_items(
            self.enterprise_catalog_uuid,
            content_ids,
        )
        return content_in_catalog

    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Subscription Plan")
        verbose_name_plural = _("Subscription Plans")
        app_label = 'subscriptions'
        unique_together = (
            ('title', 'enterprise_customer_uuid'),
        )

    def __str__(self):
        """
        Return human-readable string representation.
        """
        return (
            "<SubscriptionPlan with Title '{title}' "
            "for EnterpriseCustomer '{enterprise_customer_uuid}'"
            "{internal_use}>".format(
                title=self.title,
                enterprise_customer_uuid=self.enterprise_customer_uuid,
                internal_use=' (for internal use only)' if self.for_internal_use_only else '',
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
            "\nRevoked: A license which has been created but is no longer active (intentionally revoked or"
            " has expired). A license in this state may or may not have a learner assigned."
        )
    )

    assigned_date = models.DateTimeField(
        blank=True,
        null=True,
    )

    activation_date = models.DateTimeField(
        blank=True,
        null=True,
    )

    activation_key = models.UUIDField(
        default=None,
        blank=True,
        editable=False,
        null=True
    )

    last_remind_date = models.DateTimeField(
        blank=True,
        null=True,
    )

    revoked_date = models.DateTimeField(
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
            "for SubscriptionPlan '{title}' with UUID '{subscription_plan_uuid}'>".format(
                uuid=self.uuid,
                title=self.subscription_plan.title,
                subscription_plan_uuid=self.subscription_plan.uuid,
            )
        )

    def clear_pii(self):
        """
        Helper function to remove pii (user_email & lms_user_id) from the license.

        Note that this does NOT save the license. If you want the changes to persist you need to either explicitly save
        the license after calling this, or use something like bulk_update which saves each object as part of its updates
        """
        self.user_email = None
        self.lms_user_id = None

    def clear_historical_pii(self):
        """
        Helper function to remove pii (user_email & lms_user_id) from the license's historical records.
        """
        self.history.update(user_email=None, lms_user_id=None)  # pylint: disable=no-member

    def reset_to_unassigned(self):
        """
        Resets a license to unassigned and clears the previously set fields on it that no longer apply.

        Note that this does NOT save the license. If you want the changes to persist you need to either explicitly save
        the license after calling this, or use something like bulk_update which saves each object as part of its updates
        """
        self.status = UNASSIGNED
        self.user_email = None
        self.lms_user_id = None
        self.last_remind_date = None
        self.activation_date = None
        self.activation_key = None
        self.assigned_date = None
        self.revoked_date = None

    def revoke(self):
        """
        Performs all field updates required to revoke a License
        """
        self.status = REVOKED
        self.revoked_date = localized_utcnow()
        self.save()

    @staticmethod
    def set_date_fields_to_now(licenses, date_field_names):
        """
        Helper function to bulk set the field given by `date_field_name` on a group of licenses to now.

        Args:
            licenses (iterable): The licenses to set the field to now on.
            date_field_name (list of str): The names of the date field to set to now.
        """
        for subscription_license in licenses:
            for field_name in date_field_names:
                setattr(subscription_license, field_name, localized_utcnow())
        License.objects.bulk_update(licenses, date_field_names, batch_size=LICENSE_BULK_OPERATION_BATCH_SIZE)


class SubscriptionsFeatureRole(UserRole):
    """
    User role definitions specific to subscriptions.
     .. no_pii:
    """

    def __str__(self):
        """
        Return human-readable string representation.
        """
        return f"SubscriptionsFeatureRole(name={self.name})"

    def __repr__(self):
        """
        Return uniquely identifying string representation.
        """
        return self.__str__()


class SubscriptionsRoleAssignment(UserRoleAssignment):
    """
    Model to map users to a SubscriptionsFeatureRole.
     .. no_pii:
    """

    role_class = SubscriptionsFeatureRole
    enterprise_customer_uuid = models.UUIDField(blank=True, null=True, verbose_name='Enterprise Customer UUID')

    def get_context(self):
        """
        Return the enterprise customer id or `*` if the user has access to all resources.
        """
        if self.enterprise_customer_uuid:
            return str(self.enterprise_customer_uuid)
        return ALL_ACCESS_CONTEXT

    @classmethod
    def user_assignments_for_role_name(cls, user, role_name):
        """
        Returns assignments for a given user and role name.
        """
        return cls.objects.filter(user__id=user.id, role__name=role_name)

    def __str__(self):
        """
        Return human-readable string representation.
        """
        return "SubscriptionsRoleAssignment(name={name}, user={user})".format(
            name=self.role.name,  # pylint: disable=no-member
            user=self.user.id,
        )

    def __repr__(self):
        """
        Return uniquely identifying string representation.
        """
        return self.__str__()
