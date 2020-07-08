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
    LICENSE_STATUS_CHOICES,
    SALESFORCE_ID_LENGTH,
    UNASSIGNED,
)


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

    purchase_date = models.DateField()

    start_date = models.DateField()

    expiration_date = models.DateField()

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
        Gets the total number of licenses associated with the subscription.

        Returns:
            int: The count of how many licenses are associated with the subscription plan.
        """
        return self.licenses.count()

    @property
    def num_allocated_licenses(self):
        """
        Gets the number of allocated licenses associated with the subscription. A license is
        defined as allocated if it has either been activated by a user, or assigned to a user.

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
        License.objects.bulk_create(new_licenses)

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
            "for SubscriptionPlan '{title}' with UUID '{subscription_plan_uuid}'>".format(
                uuid=self.uuid,
                title=self.subscription_plan.title,
                subscription_plan_uuid=self.subscription_plan.uuid,
            )
        )


class SubscriptionsFeatureRole(UserRole):
    """
    User role definitions specific to subscriptions.
     .. no_pii:
    """

    def __str__(self):
        """
        Return human-readable string representation.
        """
        return "SubscriptionsFeatureRole(name={name})".format(name=self.name)

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
