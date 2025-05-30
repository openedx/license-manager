"""
Models for the subscriptions app.
"""
from datetime import datetime, timedelta
from logging import getLogger
from math import ceil, inf
from uuid import uuid4

from django.conf import settings
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import (
    MaxValueValidator,
    MinLengthValidator,
    MinValueValidator,
)
from django.db import models, transaction
from django.db.models import Q
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.forms import ValidationError
from django.utils import timezone
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
    LICENSE_UTILIZATION_THRESHOLDS,
    REVOKED,
    SALESFORCE_ID_LENGTH,
    UNASSIGNED,
    LicenseTypesToRenew,
    NotificationChoices,
    SegmentEvents,
)
from license_manager.apps.subscriptions.event_utils import (
    get_license_tracking_properties,
    track_event,
    track_license_changes,
)
from license_manager.apps.subscriptions.sanitize import sanitize_html
from license_manager.apps.subscriptions.utils import (
    days_until,
    get_license_activation_link,
    hours_until,
    localized_utcnow,
    provision_licenses,
)

from .exceptions import (
    LicenseActivationMissingError,
    LicenseToActivateIsRevokedError,
)
from .utils import chunks


logger = getLogger(__name__)

CONTAINS_CONTENT_CACHE_TIMEOUT = 60 * 60

_CACHE_MISS = object()


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
        blank=True,
        null=True,
        unique=True,
    )

    enterprise_customer_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        unique=False,
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
            "Used to disable subscription expiration notifications, and the expiration date in the "
            "subsidy summary box in the enterprise learner portal MFE. If the subscription is expired, the subsidy "
            "summary box will not display the subscription status with the expired messaging."
        )
    )

    disable_onboarding_notifications = models.BooleanField(
        default=False,
        help_text=_(
            "Used to disable onboarding notifications, i.e. license assignment and post-activation emails."
        )
    )

    # In MySQL, the value of this field is stored as a bigint of microseconds
    # https://docs.djangoproject.com/en/2.2/ref/models/fields/#django.db.models.DurationField
    # We use a DurationField because it makes subtracting from a datetime using an F()
    # expression simpler in the ``retire_old_licenses`` management command.
    license_duration_before_purge = models.DurationField(
        default=timedelta(days=settings.DEFAULT_DAYS_BEFORE_LICENSE_PURGE),
        help_text=_(
            "The number of days after which unclaimed, revoked, or expired (due to plan expiration) licenses "
            "associated with this customer agreement will have user data retired "
            "and the license status reset to UNASSIGNED."
        ),
    )

    has_custom_license_expiration_messaging = models.BooleanField(
        default=False,
        help_text=_(
            "Indicates if the customer has a unique license expiration experience, instead of the standard one."
        )
    )

    modal_header_text = models.CharField(
        max_length=512,
        blank=True,
        null=True,
        help_text=_(
            "The bold text that will appear as the header in the expiration modal."
        )
    )

    expired_subscription_modal_messaging = models.TextField(
        blank=True,
        null=True,
        help_text=_(
            "The content of a modal that will appear to learners upon subscription expiration. This text can be used "
            "for custom guidance per customer."
        )
    )

    button_label_in_modal = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text=_(
            "The text that will appear as on the button in the expiration modal"
        )
    )

    url_for_button_in_modal = models.CharField(
        max_length=512,
        blank=True,
        null=True,
        help_text=_(
            "The URL that should underly the sole button in the expiration modal"
        )
    )

    enable_auto_applied_subscriptions_with_universal_link = models.BooleanField(
        default=False,
        help_text=_(
            "By default, auto-applied subscriptions are only granted when learners join their enterprise via SSO, "
            "checking this box will enable subscription licenses to be applied when a learner joins the enterprise via "
            "Universal link as well"
        )
    )

    enable_auto_scaling_of_current_plan = models.BooleanField(
        default=False,
        db_index=True,
        help_text=_(
            "Enables the most current, active plan for this customer "
            "to automatically have licenses added to it when the count of allocated "
            "licenses hits some threshold. The number of licenses is allowed to "
            "scale up to a hard limit, specified by `auto_scaling_max_licenses`."
        ),
    )
    auto_scaling_max_licenses = models.IntegerField(
        null=True,
        blank=True,
        help_text=_(
            "The maximum number of licenses a plan for this customer "
            "is allowed to automatically scale to. Consider setting this to a "
            "factor of 3 or 4 of the desired number of licenses for the current plan. "
            "For example, if the plan in question has 10,000 desired licenses, set "
            "the value of this field to 40,000."
        ),
    )
    auto_scaling_threshold_percentage = models.IntegerField(
        null=True,
        blank=True,
        validators=[
            MaxValueValidator(100),
            MinValueValidator(1),
        ],
        help_text=_(
            "Percentage of allocated (i.e. activated or assigned) licenses in the current plan "
            "above which auto-scaling will be executed."
        ),
    )
    auto_scaling_increment_percentage = models.IntegerField(
        null=True,
        blank=True,
        validators=[
            MaxValueValidator(100),
            MinValueValidator(1),
        ],
        help_text=_(
            "Percentage of total licenses in the current plan that will be created "
            "when auto-scaling will be executed. For instance, if the number of licenses "
            "in the plan is 50,000, and we set this field to 10 percent, an auto-scale execution "
            "would result in adding 5,000 licenses to the plan."
        ),
    )

    history = HistoricalRecords()

    @property
    def net_days_until_expiration(self):
        """
        Returns the max number of days until expiration
        of _any_ plan in this agreement.
        """
        net_days = 0
        for plan in self.subscriptions.all().prefetch_related('renewal'):
            net_days = max(net_days, plan.days_until_expiration_including_renewals)
        return net_days

    @property
    def available_subscription_catalogs(self):
        """
        Returns all the enterprise catalogs associated with the subscription plans
        in this customer agreement.
        """
        default_catalog_uuid = self.default_enterprise_catalog_uuid
        available_catalog_uuids = set()
        for plan in self.subscriptions.filter(is_active=True).prefetch_related('renewal'):
            if plan.days_until_expiration_including_renewals > 0:
                available_catalog_uuids.add(
                    str(plan.enterprise_catalog_uuid)
                    if plan.enterprise_catalog_uuid
                    else str(default_catalog_uuid)
                )
        return list(available_catalog_uuids)

    @property
    def auto_applicable_subscription(self):
        """
        Get which subscription on CustomerAgreement is auto-applicable.
        """
        now = localized_utcnow()
        plan = self.subscriptions.filter(
            should_auto_apply_licenses=True,
            is_active=True,
            start_date__lte=now,
            expiration_date__gte=now
        ).order_by('-start_date').first()

        return plan

    @property
    def custom_subscription_expiration_messaging(self):
        """
        Returns the custom subscription expiration messaging associated with this customer agreement.
        """
        try:
            return self._custom_subscription_expiration_messaging
        except CustomSubscriptionExpirationMessaging.DoesNotExist:
            return None

    class Meta:
        verbose_name = _("Customer Agreement")
        verbose_name_plural = _("Customer Agreements")

    def clean(self):
        """
        Custom clean method to validate fields based on the 'Has Custom License Expiration Messaging' flag.
        """
        errors = {}

        # Sanitize the expired_subscription_modal_messaging field
        if self.expired_subscription_modal_messaging:
            self.expired_subscription_modal_messaging = sanitize_html(self.expired_subscription_modal_messaging)

        error_message = "This field cannot be blank if 'Has Custom License Expiration Messaging' is checked."
        # Validate fields when custom messaging is enabled
        if self.has_custom_license_expiration_messaging:
            required_fields = {
                "modal_header_text": error_message,
                "expired_subscription_modal_messaging": error_message,
                "button_label_in_modal": error_message,
                "url_for_button_in_modal": error_message,
            }

            # Check if any required fields are missing
            for field, error_message in required_fields.items():
                if not getattr(self, field):
                    errors[field] = error_message

        # Ensure all fields are blank if custom messaging is disabled
        if not self.has_custom_license_expiration_messaging:
            fields_to_check = [
                "modal_header_text",
                "expired_subscription_modal_messaging",
                "button_label_in_modal",
                "url_for_button_in_modal",
            ]
            if any(getattr(self, field) for field in fields_to_check):
                error_msg = "This field must be blank if 'Has Custom License Expiration Messaging' is unchecked."
                errors = {field: error_msg for field in fields_to_check}

        # Validate that url_for_button_in_modal is a complete URL
        if self.url_for_button_in_modal and not self.url_for_button_in_modal.startswith(("http://", "https://")):
            errors["url_for_button_in_modal"] = (
                "The URL must start with 'http://' or 'https://'. Please provide a valid URL."
            )

        # Raise ValidationError if there are any errors
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        """
        Return human-readable string representation.
        """
        return (
            "<CustomerAgreement: '{}'>".format(
                self.enterprise_customer_slug or self.enterprise_customer_name
            )
        )


class CustomSubscriptionExpirationMessaging(models.Model):
    """
    Custom subscription expiration messaging

    .. no_pii: This model has no PII
    """

    customer_agreement = models.OneToOneField(
        CustomerAgreement,
        on_delete=models.CASCADE,
        related_name='_custom_subscription_expiration_messaging',
        unique=True,
    )

    has_custom_license_expiration_messaging = models.BooleanField(
        default=False,
        help_text=_(
            "Indicates if the customer has a unique license expiration experience, instead of the standard one."
        )
    )

    modal_header_text = models.CharField(
        max_length=512,
        blank=True,
        null=True,
        help_text=_(
            "The bold text that will appear as the header in the expiration modal."
        )
    )

    expired_subscription_modal_messaging = models.TextField(
        blank=True,
        null=True,
        help_text=_(
            "The content of a modal that will appear to learners upon subscription expiration. This text can be used "
            "for custom guidance per customer."
        )
    )

    button_label_in_modal = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text=_(
            "The text that will appear as on the button in the expiration modal"
        )
    )

    url_for_button_in_modal = models.CharField(
        max_length=512,
        blank=True,
        null=True,
        help_text=_(
            "The URL that should underly the sole button in the expiration modal"
        )
    )

    history = HistoricalRecords()


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


class Product(models.Model):
    """
    Defines the specific Product that was sold to the customer to allow
    them access to a SubscriptionPlan.

    .. no_pii: This model has no PII
    """
    name = models.CharField(
        max_length=128,
        blank=False,
        null=False,
    )
    description = models.CharField(
        max_length=255,
        blank=False,
        null=False,
    )
    salesforce_product_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )
    netsuite_id = models.IntegerField(
        blank=True,
        null=True,
        help_text=_(
            "(Deprecated) The Product ID field (numeric) of what was sold to the customer."
        ),
    )
    plan_type = models.ForeignKey(
        PlanType,
        related_name='netsuite_products',
        on_delete=models.DO_NOTHING,
        null=False,
        blank=False,
    )
    history = HistoricalRecords()

    class Meta:
        constraints = [models.UniqueConstraint(fields=("netsuite_id",), name="unique_netsuite_id")]

    def __str__(self):
        return self.name


class Notification(TimeStampedModel):
    """
    Stores information regarding when notifications were sent out to users.

    .. no_pii: This model has no PII
    """

    enterprise_customer_uuid = models.UUIDField(
        blank=False,
        null=False,
        verbose_name='Enterprise Customer UUID'
    )

    enterprise_customer_user_uuid = models.UUIDField(
        blank=False,
        null=False,
        verbose_name='Enterprise Customer User UUID'
    )

    subscripton_plan = models.ForeignKey(
        'SubscriptionPlan',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    notification_type = models.CharField(
        max_length=32,
        blank=False,
        null=False,
        choices=NotificationChoices.CHOICES,
        help_text=("Which type of notification was sent to the user."),
    )
    last_sent = models.DateTimeField(
        help_text="Date of the last time a notifcation was sent.",
        default=localized_utcnow
    )
    history = HistoricalRecords()


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

    start_date = models.DateTimeField()

    expiration_date = models.DateTimeField()

    expiration_processed = models.BooleanField(
        default=False
    )

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

    salesforce_opportunity_id = models.CharField(
        max_length=SALESFORCE_ID_LENGTH,
        validators=[MinLengthValidator(SALESFORCE_ID_LENGTH)],
        blank=True,
        null=True,
        help_text=_(
            "Deprecated -- 18 character value, derived from Salesforce Opportunity record."
        )
    )

    salesforce_opportunity_line_item = models.CharField(
        max_length=SALESFORCE_ID_LENGTH,
        validators=[MinLengthValidator(SALESFORCE_ID_LENGTH)],
        blank=True,
        null=True,
        help_text=_(
            "18 character value -- Locate the appropriate Salesforce Opportunity Line Item record and copy it here."
        )
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
    )

    for_internal_use_only = models.BooleanField(
        default=False,
        help_text=_(
            "Whether this SubscriptionPlan is only for internal use (e.g. a test Subscription record)."
        )
    )

    can_freeze_unused_licenses = models.BooleanField(
        default=False,
        help_text=_(
            "Whether this Subscription Plan supports freezing licenses, where unused licenses"
            " (not including previously revoked licenses) are deleted."
        )
    )

    last_freeze_timestamp = models.DateTimeField(
        blank=True,
        null=True,
        help_text=_("The time at which the Subscription Plan was last frozen."),
    )

    should_auto_apply_licenses = models.BooleanField(
        blank=True,
        null=True,
        help_text=_(
            "Whether licenses from this Subscription Plan should be auto applied."
        )
    )

    desired_num_licenses = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name="Desired Number of Licenses",
        help_text=(
            "Total number of licenses that should exist for this SubscriptionPlan. "
            "The total license count (provisioned asynchronously) will reach the desired amount eventually. "
            "Empty (NULL) means no attempts will be made to asynchronously provision licenses."
        ),
    )

    @classmethod
    def get_current_plan(cls, enterprise_uuid):
        """
        Class method to retrieve the most recently created plan with an active start date.
        """
        return cls.objects.filter(
            is_active=True,
            customer_agreement__enterprise_customer_uuid=enterprise_uuid,
            start_date__lte=localized_utcnow(),
            expiration_date__gte=localized_utcnow()
        ).order_by('-created').first()

    @property
    def days_until_expiration(self):
        """
        Returns the number of days remaining until a subscription expires.

        Note: expiration_date is a required field so checking for None isn't needed.
        """
        return days_until(self.expiration_date)

    @property
    def is_current(self):
        """
        Returns a boolean indicating whether start_date <= now <= expiration_date.
        """
        return self.start_date <= timezone.now() <= self.expiration_date

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

    @property
    def enterprise_customer_uuid(self):
        """
        A link to the customer on the subscription's customer agreement.

        Returns:
            UUID
        """
        return self.customer_agreement.enterprise_customer_uuid

    @property
    def enterprise_customer_slug(self):
        """
        A link to the customer slug of this plan's customer agreement

        Returns:
            str
        """
        return self.customer_agreement.enterprise_customer_slug

    @property
    def unassigned_licenses(self):
        """
        Gets all of the unassigned licenses associated with the subscription.

        Returns:
            Queryset
        """
        return self.licenses.filter(status=UNASSIGNED)

    @property
    def assigned_licenses(self):
        """
        Gets all of the assigned licenses associated with the subscription.

        Returns:
            Queryset
        """
        return self.licenses.filter(status=ASSIGNED)

    @property
    def activated_licenses(self):
        """
        Returns all activated licenses for this subscription plan.
        """
        return self.licenses.filter(status=ACTIVATED)

    @property
    def revoked_licenses(self):
        """
        Returns all revoked licenses for this subscription plan.
        """
        return self.licenses.filter(status=REVOKED)

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
    def prior_renewals(self):
        """
        Returns all of the prior renewals associated with a subscription ordered from oldest to most recent
        """
        prior_renewals = []
        origin_renewal = self.get_origin_renewal()

        while origin_renewal:
            prior_renewals.append(origin_renewal)
            origin_renewal = origin_renewal.prior_subscription_plan.get_origin_renewal()

        return prior_renewals[::-1]

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

    @property
    def is_locked_for_renewal_processing(self):
        """
        If there is an existing renewal tied to the plan (obj), returns whether it is within
        the renewal processing window.

        If there is no existing renewal, returns False.
        """
        subscription_plan_renewal = self.get_renewal()
        if not subscription_plan_renewal:
            return False

        hours_until_effective_date = hours_until(subscription_plan_renewal.effective_date)
        # The renewal's effective_date has already passed
        if hours_until_effective_date < 0:
            return False

        is_plan_locked_for_renewal = hours_until_effective_date < settings.SUBSCRIPTION_PLAN_RENEWAL_LOCK_PERIOD_HOURS
        return is_plan_locked_for_renewal

    @property
    def highest_utilization_threshold_reached(self):
        """
        Returns the highest license utilization threshold that has been reached.

        If no thresholds have been reached, return None.
        """

        num_licenses = self.num_licenses

        if num_licenses == 0:
            return None

        thresholds = LICENSE_UTILIZATION_THRESHOLDS
        current_utilization = self.num_allocated_licenses / num_licenses

        for threshold in thresholds:
            if current_utilization >= threshold:
                return threshold

    @cached_property
    def auto_apply_licenses_turned_on_at(self):
        """
        Returns the time of when auto-apply licenses was last turned on.
        """

        if not self.should_auto_apply_licenses:
            return None

        result = None

        # pylint: disable=no-member
        for history in self.history.iterator():
            if history.should_auto_apply_licenses:
                result = history.history_date
            else:
                break

        return result

    def auto_applied_licenses_count_since(self, since=None):
        """
        Returns the number of licenses auto applied since a given time.
        """
        if since is None:
            since = self.auto_apply_licenses_turned_on_at

        return self.licenses.filter(
            auto_applied=True,
            activation_date__gte=since
        ).count()

    def license_count_by_status(self):
        """
        Returns a dictionary keyed by each license status
        and valued by a count of the licenses with that status
        in this plan.
        """
        count_by_status = {status_choice[0]: 0 for status_choice in LICENSE_STATUS_CHOICES}

        queryset = self.licenses.all().values('status').annotate(
            count=models.Count('status'),
        ).order_by('status')

        for item in queryset:
            count_by_status[item['status']] = item['count']

        return count_by_status

    def get_renewal(self):
        """
        Helper to safely return the renewal associated with the subscription, or None if one does not exist.
        """
        try:
            return self.renewal  # pylint: disable=no-member
        except SubscriptionPlanRenewal.DoesNotExist:
            return None

    def get_origin_renewal(self):
        """
        Helper to safely return the origin renewal associated with the subscription, or None if one does not exist.
        """
        try:
            return self.origin_renewal  # pylint: disable=no-member
        except SubscriptionPlanRenewal.DoesNotExist:
            return None

    def increase_num_licenses(self, num_new_licenses):
        """
        Method to increase the number of licenses associated with an instance of SubscriptionPlan by num_new_licenses.
        """
        new_licenses = [License(subscription_plan=self) for _ in range(num_new_licenses)]
        License.bulk_create(new_licenses)

    def provision_licenses(self):
        """
        For a given subscription plan, try to provision it synchronously or asynchronously.
        """
        provision_licenses(self)

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
        cache_key = self.get_contains_content_cache_key(content_ids)
        cached_value = cache.get(cache_key, _CACHE_MISS)
        if cached_value is not _CACHE_MISS:
            return cached_value

        enterprise_catalog_client = EnterpriseCatalogApiClient()
        content_in_catalog = enterprise_catalog_client.contains_content_items(
            self.enterprise_catalog_uuid,
            content_ids,
        )
        cache.set(cache_key, content_in_catalog, timeout=CONTAINS_CONTENT_CACHE_TIMEOUT)
        return content_in_catalog

    def get_contains_content_cache_key(self, content_ids):
        return f'plan_contains_content:{self.uuid}:{content_ids}'

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
            "<SubscriptionPlan title='{title}' "
            "for customer '{enterprise_customer_uuid}', slug={slug} "
            "{internal_use}>".format(
                title=self.title,
                enterprise_customer_uuid=self.enterprise_customer_uuid,
                slug=self.enterprise_customer_slug,
                internal_use='(for internal use only)' if self.for_internal_use_only else '',
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
        verbose_name=_("Salesforce Opportunity Line Item"),
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

    effective_date = models.DateTimeField(
        blank=False,
        null=False,
        help_text=_("The date that the subscription renewal will take place on."),
    )

    renewed_expiration_date = models.DateTimeField(
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

    disable_auto_apply_licenses = models.BooleanField(
        default=False,
        help_text=_(
            "Whether auto-applied licenses should be disabled for the future plan. "
            "If the original plan was not auto applying licenses, modifying this field will have no effect."
        )
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

    class Meta:
        indexes = [
            models.Index(fields=["subscription_plan", "status"], name="subscription_plan_status_idx"),
        ]

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
        db_index=True,
    )

    lms_user_id = models.IntegerField(
        blank=True,
        null=True,
        db_index=True,
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

    # None and False are functionally equivalent. Not adding False as default
    # value simplified deploying, as the License table is quite large.
    auto_applied = models.BooleanField(
        blank=True,
        null=True,
        help_text="Whether or not License was auto-applied.",
    )

    history = HistoricalRecords()

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

    def clean(self):
        """
        Override to perform additional validations.
        """
        super().clean()

        if self.status in [ASSIGNED, ACTIVATED]:
            has_existing_license = License.objects.filter(
                user_email=self.user_email,
                status__in=[ASSIGNED, ACTIVATED],
                subscription_plan=self.subscription_plan,
            ).exclude(uuid=self.uuid).exists()

            if has_existing_license:
                raise ValidationError(
                    f'User with email {self.user_email} already has an assigned or activated license.'
                )

    def save(self, *args, **kwargs):
        """
        Override to ensure that full_clean()/clean() is always called.
        """
        self.full_clean()
        super().save(*args, **kwargs)

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

    def clear_historical_pii(self):
        """
        Helper function to remove pii (user_email & lms_user_id) from the license's historical records.
        """
        self.history.update(user_email=None)  # pylint: disable=no-member

    def reset_to_unassigned(self):
        """
        Resets a license to unassigned and clears the previously set fields on it that no longer apply.

        Note that this does NOT save the license. If you want the changes to persist you need to either explicitly save
        the license after calling this, or use something like bulk_update which saves each object as part of its updates
        """
        logger.info(f'Reseting license {self.uuid} to unassigned.')
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
        event_properties = get_license_tracking_properties(self)
        track_event(self.lms_user_id,
                    SegmentEvents.LICENSE_REVOKED,
                    event_properties)

    def delete_source(self):
        """
        Deletes any related ``SubscriptionLicenseSource`` record.
        """
        try:
            self.source.delete()  # pylint: disable=no-member
        except SubscriptionLicenseSource.DoesNotExist:
            logger.warning('Could not find related license source to delete for license %s', self.uuid)

    def activate(self, lms_user_id):
        """
        Update this license to activated and set the lms_user_id.
        """
        self.status = ACTIVATED
        self.activation_date = localized_utcnow()
        self.lms_user_id = lms_user_id
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

        # Since bulk_create does not call post_save, handle tracking events manually:
        track_license_changes(license_objects, SegmentEvents.LICENSE_CREATED)

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
    def by_user_email_or_lms_user_id(cls, user_email, lms_user_id=None):
        """
        Returns all licenses asssociated with the given user email or lms_user_id.
        """
        if lms_user_id is not None:
            qs = cls.objects.filter(
                Q(user_email=user_email) | Q(lms_user_id=lms_user_id)
            )
        else:
            qs = cls.objects.filter(Q(user_email=user_email))

        return qs.select_related(
            'subscription_plan',
            'subscription_plan__customer_agreement',
        )

    @classmethod
    def for_user_and_customer(
        cls,
        user_email,
        lms_user_id,
        enterprise_customer_uuid,
        active_plans_only=False,
        current_plans_only=False,
    ):
        """
        Returns all licenses asssociated with the given user email or lms_user_id that are associated
        with a particular customer's SubscrptionPlan. The optional ``active_plans_only``
        and ``current_plans_only`` allow the caller to filter for licenses whose plans
        are marked ``active`` or that are current (the current time is within the plan's
        start/end range), respectively.
        """
        queryset = cls.by_user_email_or_lms_user_id(user_email, lms_user_id)
        kwargs = {
            'subscription_plan__customer_agreement__enterprise_customer_uuid': enterprise_customer_uuid,
        }
        if active_plans_only:
            kwargs['subscription_plan__is_active'] = True
        if current_plans_only:
            now = localized_utcnow()
            kwargs['subscription_plan__start_date__lte'] = now
            kwargs['subscription_plan__expiration_date__gte'] = now

        return queryset.filter(**kwargs)

    @classmethod
    def get_licenses_exceeding_purge_duration(cls, date_field_to_compare, batch_size=1000, **kwargs):
        """
        Returns all licenses with non-null ``user_email`` values
        that have exceeded the purge duration specified by the related
        plan's ``CustomerAgreement.license_duration_before_purge`` value.

        The ``date_field_to_compare`` argument is compared to this value to determine
        if the duration has been exceeded.  It can be the name of any valid
        field for a queryset that filters on ``License`` or a related
        ``SubscriptionPlan`` or ``CustomerAgreement`` - for example:

          'activation_date'
          'revoked_date'
          'subscription_plan__expiration_date'
          'subscription_plan__start_date'
        """
        duration_before_purge_field = 'subscription_plan__customer_agreement__license_duration_before_purge'
        date_field = date_field_to_compare + '__lt'
        date_field_is_null = date_field_to_compare + '__isnull'

        kwargs.update({
            'user_email__isnull': False,
            date_field_is_null: False,
            date_field: localized_utcnow() - models.F(duration_before_purge_field),
        })

        # ordered by primary key for stable pagination, which we'll rely on
        # below to generate batches of result sets.
        base_queryset = License.objects.filter(**kwargs).select_related(
            'subscription_plan',
            'subscription_plan__customer_agreement',
        ).order_by('pk')

        queryset = base_queryset[:batch_size]
        offset = 0
        while queryset.exists():
            yield queryset
            # queryset.last() doesn't work here because we've already sliced it above.
            # We have to loop through (by list-ing) it in order to grab the last one.
            offset = list(queryset)[-1].pk
            queryset = base_queryset.filter(pk__gt=offset)[:batch_size]

    @classmethod
    def get_licenses_by_email(cls, user_email):
        """
        Helper to get all unrevoked licenses for a given user_email.
        Note that these may span across multiple plans - the caller
        may want to filter by subscription plan.
        """
        today = localized_utcnow()
        kwargs = {
            'user_email': user_email,
            'subscription_plan__is_active': True,
            'subscription_plan__start_date__lte': today,
            'subscription_plan__expiration_date__gte': today,
        }
        return License.objects.filter(**kwargs)

    @classmethod
    def get_license_by_email_and_activation_key(cls, user_email, activation_key):
        """
        Helper to get a licenses in any current, active plan by activation_key and user_email.
        """
        user_license = cls.get_licenses_by_email(user_email).filter(
            activation_key=activation_key,
        ).first()

        if not user_license:
            msg = f'No current license exists for the email {user_email} with activation key {activation_key}'
            raise LicenseActivationMissingError(
                license_uuid=None,
                failure_reason=msg,
            )
        return user_license

    @classmethod
    def license_for_activation(cls, user_email, activation_key):
        """
        Helper to get a license for activating, given an activation_key and user email.

        If more than one assigned or activated license is found,
        this method will clean up the duplicates by setting
        the earlier (by assignment date) license record to unassigned.
        """
        license_with_activation_key = cls.get_license_by_email_and_activation_key(
            user_email, activation_key
        )
        if license_with_activation_key.status == REVOKED:
            raise LicenseToActivateIsRevokedError(license_with_activation_key.uuid)

        licenses_for_user_in_plan = list(
            cls.get_licenses_by_email(user_email).filter(
                subscription_plan=license_with_activation_key.subscription_plan,
            ).exclude(status=REVOKED)
        )
        if len(licenses_for_user_in_plan) > 1:
            logger.info(f'Cleaning up duplicate licenses during activation: {licenses_for_user_in_plan}')
            return cls._clean_up_duplicate_licenses(licenses_for_user_in_plan)
        return licenses_for_user_in_plan[0]

    @classmethod
    def _clean_up_duplicate_licenses(cls, duplicate_licenses):
        """
        Helper to deal with cases where more than one activated or assigned license
        exists for a given user_email in a plan.
        If any of these are activated, sets the remainder to unassigned and returns the activated
        license.
        Otherwise, picks the most recently assigned license as the "good" one, sets the remainding
        assigned licenses to unassigned, and returns the good one.
        """
        activated_license = next((
            _license for _license in duplicate_licenses
            if _license.status == ACTIVATED
        ), None)

        if activated_license:
            for _license in duplicate_licenses:
                if _license != activated_license:
                    _license.reset_to_unassigned()
                    _license.save()
            return activated_license

        # Now there should be only assigned licenses to deal with.
        # Sort them by newest assigned_date, leave the newest one untouched,
        # and unassign the remainder.
        sorted_licenses = sorted(
            duplicate_licenses,
            key=lambda lic: lic.assigned_date or datetime.min,
            reverse=True,
        )
        for duplicate in sorted_licenses[1:]:
            duplicate.reset_to_unassigned()
            duplicate.save()

        return sorted_licenses[0]


class LicenseTransferJob(TimeStampedModel):
    """
    A record to help run a job that "physically" transfers
    a batch of licenses' SubscriptionPlan FKs from one plan
    to another plan.

    .. no_pii: This model has no PII
    """
    CHUNK_SIZE = 100

    customer_agreement = models.ForeignKey(
        CustomerAgreement,
        related_name='license_transfer_jobs',
        on_delete=models.CASCADE,
        null=False,
        blank=False,
    )
    old_subscription_plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.CASCADE,
        null=False,
        blank=False,
        related_name='license_transfer_jobs_old',
        help_text=_("SubscriptionPlan from which licenses will be transferred."),
    )
    new_subscription_plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.CASCADE,
        null=False,
        blank=False,
        related_name='license_transfer_jobs_new',
        help_text=_("SubscriptionPlan to which licenses will be transferred."),
    )
    completed_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text=_("The time at which the job was successfully processed."),
    )
    notes = models.TextField(
        null=True,
        blank=True,
        help_text=_("Optionally, say something about why the licenses are being transferred."),
    )
    is_dry_run = models.BooleanField(
        default=False,
        help_text=_(
            "If true, will report which licenses will be transferred in processed_results, "
            "without actually transferring them."
        ),
    )
    delimiter = models.CharField(
        max_length=8,
        choices=(
            ('newline', _('Newline character')),
            ('comma', _('Comma character')),
            ('pipe', _('Pipe character')),
        ),
        null=False,
        default='newline',
    )
    transfer_all = models.BooleanField(
        default=False,
        help_text=_("Set to true to transfer ALL licenses from old to new plan, regardless of status."),
    )
    license_uuids_raw = models.TextField(
        null=True,
        blank=True,
        help_text=_("Delimitted (with newlines by default) list of license_uuids to transfer"),
    )
    processed_results = models.JSONField(
        null=True,
        blank=True,
        encoder=DjangoJSONEncoder,
        help_text=_("Raw results of what licenses were changed, either in dry-run form, or actual form."),
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = _("License Transfer Job")
        verbose_name_plural = _("License Transfer Jobs")

    def __str__(self):
        return f'{self.id}'

    @property
    def delimiter_char(self):
        return {
            'newline': '\n',
            'comma': ',',
            'pipe': '|',
        }.get(self.delimiter, '\n')

    def clean(self):
        """
        Validates that old and new subscription plans share the same customer agreement.
        """
        super().clean()
        if self.old_subscription_plan.customer_agreement != self.new_subscription_plan.customer_agreement:
            raise ValidationError(
                'LicenseTransferJob: Old and new subscription plans must have same customer_agreement.'
            )
        if not self.transfer_all and not self.license_uuids_raw:
            raise ValidationError(
                'LicenseTransferJob: Must specify either transfer_all or license_uuids_raw.'
            )

    def get_customer_agreement(self):
        try:
            return self.customer_agreement
        except CustomerAgreement.DoesNotExist:
            return None

    def get_license_uuids(self):
        return [
            raw_license_uuid.strip() for raw_license_uuid in
            self.license_uuids_raw.split(self.delimiter_char)
        ]

    def get_licenses_to_transfer(self):
        """
        Yields successive chunked querysets of License records to transfer.
        The licenses are from self.old_subscription_plan and will
        only be in the (activated, assigned) statuses, unless ``transfer_all``
        is True, in which case **all** licenses will be included.
        """
        if self.transfer_all:
            yield License.objects.filter(subscription_plan=self.old_subscription_plan)
        else:
            for license_uuid_chunk in chunks(self.get_license_uuids(), self.CHUNK_SIZE):
                yield License.objects.filter(
                    subscription_plan=self.old_subscription_plan,
                    status__in=[ACTIVATED, ASSIGNED],
                    uuid__in=license_uuid_chunk,
                )

    def process(self):
        """
        Processes this job, moving activated and assigned licenses
        from the job's old subscription plan to the new subscription plan.
        Is ``self.is_dry_run``, the licenses are not actually moved, but we
        report via ``self.processed_results`` which licenses would have
        been moved during this processing.
        """
        if self.completed_at:
            logger.info(f'{self} was already processed on {self.completed_at}')
            return

        processed_license_uuids = []
        with transaction.atomic():
            for license_queryset in self.get_licenses_to_transfer():
                licenses = list(license_queryset)

                if not self.is_dry_run:
                    for _license in licenses:
                        _license.subscription_plan = self.new_subscription_plan
                    License.bulk_update(licenses, ['subscription_plan'])

                processed_license_uuids.extend([str(_lic.uuid) for _lic in licenses])

        time_completed_at = localized_utcnow()
        if not self.is_dry_run:
            self.completed_at = time_completed_at

        if not self.processed_results:
            self.processed_results = []
        self.processed_results.append(
            {
                'is_dry_run': self.is_dry_run,
                'modified_licenses': processed_license_uuids,
                'completed_at': time_completed_at,
            }
        )
        self.save()


class SubscriptionLicenseSourceType(TimeStampedModel):
    """
    Subscription License Source Type

    .. no_pii: This model has no PII
    """

    AMT = 'AMT'

    name = models.CharField(max_length=64)
    slug = models.SlugField(max_length=30, unique=True)

    @classmethod
    def get_source_type(cls, source_slug):
        """
        Retrieve the source type based on the slug.
        """
        try:
            return cls.objects.get(slug=source_slug)
        except SubscriptionLicenseSourceType.DoesNotExist:
            return None

    def __str__(self):
        """
        String representation of source type.
        """
        return "SubscriptionLicenseSourceType: Name: {name}, Slug: {slug}".format(name=self.name, slug=self.slug)


class SubscriptionLicenseSource(TimeStampedModel):
    """
    Subscription License Source

    .. no_pii: This model has no PII
    """

    license = models.OneToOneField(
        License,
        related_name='source',
        on_delete=models.CASCADE,
    )
    source_id = models.CharField(
        max_length=SALESFORCE_ID_LENGTH,
        validators=[MinLengthValidator(SALESFORCE_ID_LENGTH)],
        help_text=_("18 character value -- Salesforce Opportunity ID")
    )
    source_type = models.ForeignKey(SubscriptionLicenseSourceType, on_delete=models.CASCADE)

    history = HistoricalRecords()

    def save(self, *args, **kwargs):
        """
        Override to ensure that model.clean is always called.
        """
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        """
        String representation of source.
        """
        return "SubscriptionLicenseSource: LicenseID: {license}, SourceID: {source}, SourceType: {source_type}".format(
            license=self.license.uuid,
            source=self.source_id,
            source_type=self.source_type.slug,
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


class LicenseEvent(TimeStampedModel):
    """
    Track events triggered for a license.

    .. no_pii:
    """
    license = models.ForeignKey(
        License,
        related_name='events',
        on_delete=models.DO_NOTHING,
        null=False,
        blank=False,
    )

    event_name = models.CharField(
        max_length=255,
        blank=False,
        null=False,
    )

    class Meta:
        verbose_name = _("License Triggered Event")
        verbose_name_plural = _("License Triggered Events")

    def __str__(self):
        return f'{self.license.uuid}'


@receiver(post_delete, sender=License)
def dispatch_license_delete_event(sender, **kwargs):  # pylint: disable=unused-argument
    license_obj = kwargs['instance']
    event_properties = get_license_tracking_properties(license_obj)
    track_event(license_obj.lms_user_id,
                SegmentEvents.LICENSE_DELETED,
                event_properties)


@receiver(post_save, sender=License)
def dispatch_license_create_events(sender, **kwargs):  # pylint: disable=unused-argument
    """ Post creation hook to handle tracking license lifecycle events
    that could have been created in a variety of states. """
    license_obj = kwargs['instance']
    is_new_license = kwargs.get('created', False)

    if not is_new_license:
        # Update events are handled by more explicit tracking events around the codebase
        # to map them more easily with the events we want to track.
        return

    event_properties = get_license_tracking_properties(license_obj)
    # We always send a creation event.
    track_event(license_obj.lms_user_id,
                SegmentEvents.LICENSE_CREATED,
                event_properties)

    # If the license has extra statuses on creation that would normally fire events,
    # then programmatically fire events for those also
    if license_obj.status == ASSIGNED:
        track_event(license_obj.lms_user_id,
                    SegmentEvents.LICENSE_ASSIGNED,
                    event_properties)
    if license_obj.status == ACTIVATED:
        track_event(license_obj.lms_user_id,
                    SegmentEvents.LICENSE_ACTIVATED,
                    event_properties)


@receiver(post_save, sender=SubscriptionPlan)
def dispatch_license_expiration_event(sender, **kwargs):  # pylint: disable=unused-argument
    """
    Post save hook to handle tracking license lifecycle events:
    Sends an expiration event for all linked licenses when a top level subscription plan is marked as
    expired and individual license WASN'T renewed.
    """
    # if we updated the expiration_processed field and it's true now:
    subscription_plan_obj = kwargs['instance']
    update_fields = kwargs.get('update_fields', None)

    if subscription_plan_obj and update_fields and 'expiration_processed' in update_fields:
        expired_licenses = [lcs for lcs in subscription_plan_obj.licenses.all() if not lcs.renewed_to]
        track_license_changes(expired_licenses, SegmentEvents.LICENSE_EXPIRED)
