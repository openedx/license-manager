from math import ceil, inf
from operator import itemgetter
from uuid import uuid4

from django.core.validators import MinLengthValidator
from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import gettext as _
from edx_rbac.models import UserRole, UserRoleAssignment
from edx_rbac.utils import ALL_ACCESS_CONTEXT
from model_utils.models import TimeStampedModel
from simple_history.models import HistoricalRecords
from simple_history.utils import (
    bulk_create_with_history,
    bulk_update_with_history,
)

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
    LicenseTypesToRenew,
)
from license_manager.apps.subscriptions.exceptions import LicenseUnrevokeError
from license_manager.apps.subscriptions.utils import (
    days_until,
    get_license_activation_link,
    localized_utcnow,
)


class CustomerAgreement(TimeStampedModel):
    """
    Stores information related to an agreement for a specific customer
    Allows for linking of an enterprise customer with all of their subscription plans

    .. no_pii: This model has no PII
    """

    uuid = models.UUIDField(
        primary_key=True,
        default=uuid4,
        editable=False,
        unique=True,
    )

    enterprise_customer_uuid = models.UUIDField(
        null=False,
        blank=False,
        unique=True,
    )

    enterprise_customer_slug = models.CharField(
        max_length=128,
        blank=False,
        null=False,
        unique=True,
    )

    default_enterprise_catalog_uuid = models.UUIDField(
        blank=True,
        null=True,
        help_text=_(
            "The default enterprise catalog UUID must be from a catalog associated with the above Enterprise Customer "
            "UUID."
        )
    )

    disable_expiration_notifications = models.BooleanField(
        default=False,
        help_text=_(
            "Used in MFEs to disable subscription expiration notifications"
        )
    )

    history = HistoricalRecords()

    @property
    def ordered_subscription_plan_expirations(self):
        subscription_plan_expiration_data = [
            {
                'uuid': subscription.uuid,
                'days_until_expiration': subscription.days_until_expiration,
                'days_until_expiration_including_renewals': subscription.days_until_expiration_including_renewals,
                'is_active': subscription.is_active,
            }
            for subscription in self.subscriptions.all()
        ]

        ordered_subscription_plan_data = sorted(
            subscription_plan_expiration_data,
            key=itemgetter('is_active', 'days_until_expiration_including_renewals'),
            reverse=True,
        )

        return ordered_subscription_plan_data

    class Meta:
        verbose_name = _("Customer Agreement")
        verbose_name_plural = _("Customer Agreements")

    def __str__(self):
        """
        Return human-readable string representation.
        """
        return (
            "<CustomerAgreement: '{slug}'>".format(
                slug=self.enterprise_customer_slug,
            )
        )


class PlanType(models.Model):
    """
    Stores top-level information related to available enterprise Subscription plan types.

    .. no_pii: This model has no PII
    """
    label = models.CharField(
        max_length=128,
        blank=False,
        null=False,
    )
    description = models.CharField(
        max_length=255,
        blank=False,
        null=False,
    )
    is_paid_subscription = models.BooleanField(
        default=True,
        help_text=_(
            "Marking this indicates that the plan is a paid subscription."
        )
    )
    ns_id_required = models.BooleanField(
        default=True,
        help_text=_(
            "Marking this indicates the NetSuite ID is required."
        )
    )
    sf_id_required = models.BooleanField(
        default=True,
        help_text=_(
            "Marking this indicates the Salesforce ID is required."
        )
    )
    internal_use_only = models.BooleanField(
        default=False,
        help_text=_(
            "Marking this indicates this subscription is only used internally by edX employees."
        )
    )

    def __str__(self):
        return self.label


class PlanEmailTemplates(models.Model):
    """
    Stores email templates associated with each enterprise Subscription plan type.
    .. no_pii: This model has no PII
    """
    plaintext_template = models.TextField(
        blank=False,
    )
    html_template = models.TextField(
        blank=False,
    )
    subject_line = models.CharField(
        max_length=100,
        blank=False,
        null=False,
    )
    plan_type = models.ForeignKey(
        PlanType,
        related_name='subscriptions',
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    template_type = models.TextField(
        blank=False,
        null=False,
    )


class SubscriptionPlan(TimeStampedModel):
    """
    Stores top-level information related to an enterprise Subscriptions purchase.

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

    expiration_processed = models.BooleanField(
        default=False
    )

    @property
    def days_until_expiration(self):
        """
        Returns the number of days remaining until a subscription expires.

        Note: expiration_date is a required field so checking for None isn't needed.
        """
        return days_until(self.expiration_date)

    enterprise_catalog_uuid = models.UUIDField(
        blank=True,
        null=False,
        help_text=_(
            "If you do not explicitly set an Enterprise Catalog UUID, it will be set from the Subscription's Customer "
            "Agreement `default_enterprise_catalog_uuid`."
        )
    )

    customer_agreement = models.ForeignKey(
        CustomerAgreement,
        related_name='subscriptions',
        on_delete=models.CASCADE,
        null=False,
        blank=False,
    )

    is_active = models.BooleanField(
        default=False
    )

    is_revocation_cap_enabled = models.BooleanField(
        default=False,
        help_text=(
            "Determines whether there is a maximum cap on the number of license revocations for this SubscriptionPlan. "
            "Defaults to False."
        )
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
    def has_revocations_remaining(self):
        """
        Returns true if there are any revocations remaining for this SubscriptionPlan, false otherwise.
        """
        if not self.is_revocation_cap_enabled:
            return True
        return self.num_revocations_remaining > 0

    @property
    def num_revocations_remaining(self):
        """
        When the revocation cap is enabled for this plan,
        returns the number of revocations that can still be made against this plan.

        When the revocation cap is not enabled for this plan, positive infinity is returned.
        """
        if not self.is_revocation_cap_enabled:
            return inf

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

    plan_type = models.ForeignKey(
        PlanType,
        on_delete=models.DO_NOTHING,
        null=False,
        blank=False
    )

    @property
    def enterprise_customer_uuid(self):
        """
        A link to the customer on the subscription's customer agreement.

        Returns:
            UUID
        """
        return self.customer_agreement.enterprise_customer_uuid

    @property
    def unassigned_licenses(self):
        """
        Gets all of the unassigned licenses associated with the subscription.

        Returns:
            Queryset
        """
        return self.licenses.filter(status=UNASSIGNED)

    @property
    def activated_licenses(self):
        """
        Returns all activated licenses for this subscription plan.
        """
        return self.licenses.filter(status=ACTIVATED)

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

    @property
    def future_renewals(self):
        """
        Returns all of the future renewals associated with a subscription.

        The collected renewals are "future" renewals in that it does not return the renewal that might have created
        this subscription or any renewals before that.
        """
        renewals = []
        current_renewal = self.get_renewal()

        # Traverse forwards through the renewals that are associated with this plan
        while current_renewal:
            renewals.append(current_renewal)
            try:
                current_renewal = current_renewal.renewed_subscription_plan.get_renewal()
            except AttributeError:
                current_renewal = None

        return renewals

    @property
    def days_until_expiration_including_renewals(self):
        """
        Returns the number of days remaining until a subscription expires, accounting for its future renewals.
        """
        renewal_expiration_dates = [renewal.renewed_expiration_date for renewal in self.future_renewals]
        try:
            return days_until(max(renewal_expiration_dates))
        except ValueError:
            # A value error indicates that there were no renewals
            return self.days_until_expiration

    def get_renewal(self):
        """
        Helper to safely return the renewal associated with the subscription, or None if one does not exist.
        """
        try:
            return self.renewal  # pylint: disable=no-member
        except SubscriptionPlanRenewal.DoesNotExist:
            return None

    def increase_num_licenses(self, num_new_licenses):
        """
        Method to increase the number of licenses associated with an instance of SubscriptionPlan by num_new_licenses.
        """
        new_licenses = [License(subscription_plan=self) for _ in range(num_new_licenses)]
        License.bulk_create(new_licenses)

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
            ('title', 'customer_agreement'),
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


class SubscriptionPlanRenewal(TimeStampedModel):
    """
    Stores information related to a purchase that schedules the renewal of a SubscriptionPlan.
    A subscription renewal may be for more, the same, or fewer licenses than the original Subscription.
    A renewal can be scheduled to become effective on any day on or after the original Subscription expires.
    .. no_pii: This model has no PII
    """
    prior_subscription_plan = models.OneToOneField(
        SubscriptionPlan,
        on_delete=models.CASCADE,
        null=False,
        related_name='renewal',
        unique=True,
    )

    renewed_subscription_plan = models.OneToOneField(
        SubscriptionPlan,
        on_delete=models.CASCADE,
        null=True,
        related_name='origin_renewal',
    )

    salesforce_opportunity_id = models.CharField(
        max_length=SALESFORCE_ID_LENGTH,
        validators=[MinLengthValidator(SALESFORCE_ID_LENGTH)],
        blank=False,
        null=False,
        help_text=_(
            "Locate the appropriate Salesforce Opportunity record and copy the Opportunity ID field (18 characters)."
            " Note that this is not the same Salesforce Opportunity ID associated with the linked subscription."
        )
    )

    number_of_licenses = models.PositiveIntegerField(
        blank=False,
        null=False,
        help_text=_("Number of licenses to renew the linked subscription for."),
    )

    effective_date = models.DateField(
        blank=False,
        null=False,
        help_text=_("The date that the subscription renewal will take place on."),
    )

    renewed_expiration_date = models.DateField(
        blank=False,
        null=False,
        help_text=_("The date that the renewed subscription should expire on."),
    )

    # Mainly used as an easy way to confirm that a renewal has been processed successfully
    processed = models.BooleanField(
        default=False,
        help_text=_("Whether the renewal has been processed and gone into effect for the linked subscription."),
    )

    processed_datetime = models.DateTimeField(
        blank=True,
        null=True,
        help_text=_("The time at which the renewal was processed."),
    )

    renewed_plan_title = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        help_text=_("The title of the future plan."),
    )

    license_types_to_copy = models.CharField(
        max_length=32,
        blank=False,
        null=False,
        choices=LicenseTypesToRenew.CHOICES,
        default=LicenseTypesToRenew.ASSIGNED_AND_ACTIVATED,
        help_text=(
            "Which types of licenses are copied from the original plan to the future plan. "
            "'None' means the future plan will be created with only unassigned licenses."
        ),
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Subscription Plan Renewal")
        verbose_name_plural = _("Subscription Plan Renewals")

    def get_renewed_plan_title(self):
        if self.renewed_plan_title:
            return self.renewed_plan_title
        return '{prior_title} - Renewal {activation_year}'.format(
            prior_title=self.prior_subscription_plan.title,
            activation_year=self.effective_date.year,
        )

    def __str__(self):
        """
        Return human-readable string representation.
        """
        return (
            "<SubscriptionPlanRenewal with id '{id}'"
            " for subscription with title '{title}' and UUID '{uuid}'"
            " effective on '{effective_date}'>".format(
                id=self.id,
                title=self.prior_subscription_plan.title,
                uuid=self.prior_subscription_plan.uuid,
                effective_date=self.effective_date,
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
            "\nTransferred for renwal: The license's subscription plan was renewed into a new plan,"
            " and the license transferred to a new, active license in the renewed plan."
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

    renewed_to = models.OneToOneField(
        'License',  # Passed as a string because we're in the License class definition here.
        related_name='_renewed_from',
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
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

    @cached_property
    def activation_link(self):
        """
        Returns the activation link displayed in the activation email sent to a learner.
        """
        return get_license_activation_link(
            self.subscription_plan.customer_agreement.enterprise_customer_slug,
            self.activation_key,
        )

    @property
    def renewed_from(self):
        """
        Helper to get any existing licenses this license was renewed from.
        """
        # pylint: disable=no-member
        try:
            return self._renewed_from
        except License._renewed_from.RelatedObjectDoesNotExist:
            return None

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

    def unrevoke(self):
        """
        Moves a revoked license's status back to ASSIGNED and
        sets its revoked_date to null.
        """
        if self.status != REVOKED:
            raise LicenseUnrevokeError(self.uuid, 'status does not equal REVOKED')

        now = localized_utcnow()
        self.status = ASSIGNED
        self.lms_user_id = None
        self.revoked_date = None
        self.activation_date = None
        self.assigned_date = now
        self.last_remind_date = now
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
        License.bulk_update(licenses, date_field_names)

    @classmethod
    def bulk_create(cls, license_objects, batch_size=LICENSE_BULK_OPERATION_BATCH_SIZE):
        """
        django-simple-history functions by saving history using a post_save signal every time that
        an object with history is saved. However, for certain bulk operations, such as bulk_create, bulk_update,
        and queryset updates, signals are not sent, and the history is not saved automatically.
        However, django-simple-history provides utility functions to work around this.

        https://django-simple-history.readthedocs.io/en/2.12.0/common_issues.html#bulk-creating-and-queryset-updating
        """
        bulk_create_with_history(license_objects, cls, batch_size=batch_size)

    @classmethod
    def bulk_update(cls, license_objects, field_names, batch_size=LICENSE_BULK_OPERATION_BATCH_SIZE):
        """
        django-simple-history functions by saving history using a post_save signal every time that
        an object with history is saved. However, for certain bulk operations, such as bulk_create, bulk_update,
        and queryset updates, signals are not sent, and the history is not saved automatically.
        However, django-simple-history provides utility functions to work around this.

        https://django-simple-history.readthedocs.io/en/2.12.0/common_issues.html#bulk-creating-and-queryset-updating
        """
        bulk_update_with_history(license_objects, cls, field_names, batch_size=batch_size)

    @classmethod
    def by_user_email(cls, user_email):
        """
        Returns all licenses asssociated with the given user email.
        """
        return cls.objects.filter(
            user_email=user_email,
        ).select_related(
            'subscription_plan',
            'subscription_plan__customer_agreement',
        )

    @classmethod
    def for_email_and_customer(
        cls,
        user_email,
        enterprise_customer_uuid,
        active_plans_only=False,
        current_plans_only=False,
    ):
        """
        Returns all licenses asssociated with the given user email that are associated
        with a particular customer's SubscrptionPlans.  The optional ``active_plans_only``
        and ``current_plans_only`` allow the caller to filter for licenses whose plans
        are marked ``active`` or that are current (the current time is within the plan's
        start/end range), respectively.
        """
        queryset = cls.by_user_email(user_email)
        kwargs = {
            'subscription_plan__customer_agreement__enterprise_customer_uuid': enterprise_customer_uuid,
        }
        if active_plans_only:
            kwargs['subscription_plan__is_active'] = True
        if current_plans_only:
            today = localized_utcnow().date()
            kwargs['subscription_plan__start_date__lte'] = today
            kwargs['subscription_plan__expiration_date__gte'] = today

        return queryset.filter(**kwargs)


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
