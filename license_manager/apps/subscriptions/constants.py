# License status choices
ACTIVATED = 'activated'
ASSIGNED = 'assigned'
UNASSIGNED = 'unassigned'
REVOKED = 'revoked'
LICENSE_STATUS_CHOICES = (
    (ACTIVATED, 'Activated'),
    (ASSIGNED, 'Assigned'),
    (UNASSIGNED, 'Unassigned'),
    (REVOKED, 'Revoked'),
)
REVOCABLE_LICENSE_STATUSES = [ACTIVATED, ASSIGNED]


# Subscription/license renewals
class LicenseTypesToRenew:
    ASSIGNED_AND_ACTIVATED = 'assigned_and_activated'
    ACTIVATED = 'activated'
    NOTHING = 'nothing'

    CHOICES = (
        (ASSIGNED_AND_ACTIVATED, 'Assigned and activated'),
        (ACTIVATED, 'Activated'),
        (NOTHING, 'None'),
    )


class SubscriptionPlanShouldAutoApplyLicensesChoices:
    CHOICES = (
        (None, "----------"),
        (True, "Yes"),
        (False, "No")
    )


class SubscriptionPlanChangeReasonChoices:
    NONE = None
    NEW = "new"
    INCORRECT_USER_INPUT = "incorrect_user_input"
    DELAYED_PAYMENT = "delayed_payment"
    ORGANIZATION_REQUESTED_CHANGE = "organization_requested_change"
    OTHER = "other"

    CHOICES = (
        (NONE, "Select Reason"),
        (NEW, "New Subscription"),
        (INCORRECT_USER_INPUT, "Incorrect User Input"),
        (DELAYED_PAYMENT, "Delayed Payment"),
        (ORGANIZATION_REQUESTED_CHANGE, "Organization Request Change"),
        (OTHER, "Other"),
    )


class NotificationChoices:
    LIMITED_ALLOCATIONS_REMAINING = "limited_allocations_remaining"
    NO_ALLOCATIONS_REMAINING = "no_allocations_remaining"
    PERIODIC_INFORMATIONAL = "periodic_informational"

    CHOICES = (
        (LIMITED_ALLOCATIONS_REMAINING, "Limited Allocations Remaining"),
        (NO_ALLOCATIONS_REMAINING, "No Allocations Remaining"),
        (PERIODIC_INFORMATIONAL, "Periodic Informational"),
    )


# Segment events
class SegmentEvents:
    LICENSE_ACTIVATED = 'edx.server.license-manager.license-lifecycle.activated'
    LICENSE_ASSIGNED = 'edx.server.license-manager.license-lifecycle.assigned'
    LICENSE_CREATED = 'edx.server.license-manager.license-lifecycle.created'
    LICENSE_DELETED = 'edx.server.license-manager.license-lifecycle.deleted'
    LICENSE_EXPIRED = 'edx.server.license-manager.license-lifecycle.expired'
    LICENSE_RENEWED = 'edx.server.license-manager.license-lifecycle.renewed'
    LICENSE_REVOKED = 'edx.server.license-manager.license-lifecycle.revoked'
    LICENSE_NOT_ASSIGNED = 'edx.server.license-manager.license-lifecycle.not-assigned'
    LICENSE_ACTIVATED_180_DAYS_AGO = 'edx.server.license-manager.license.activated.180.days.ago'


# Template names used for emails
LICENSE_ACTIVATION_EMAIL_TEMPLATE = 'activation'
LICENSE_REMINDER_EMAIL_TEMPLATE = 'reminder'
ONBOARDING_EMAIL_TEMPLATE = 'onboarding'
REVOCATION_CAP_NOTIFICATION_EMAIL_TEMPLATE = 'revocation_cap'

# Role-based access control
SUBSCRIPTIONS_ADMIN_ROLE = 'enterprise_subscriptions_admin'
SUBSCRIPTIONS_LEARNER_ROLE = 'enterprise_subscriptions_learner'
# Role-based access control - Provisioning admins
PROVISIONING_SUBSCRIPTION_ADMIN_ROLE = 'provisioning_subscription_admin'
PROVISIONING_CUSTOMER_AGREEMENT_ADMIN_ROLE = 'provisioning_customer_agreement_admin'

SYSTEM_ENTERPRISE_ADMIN_ROLE = 'enterprise_admin'
SYSTEM_ENTERPRISE_LEARNER_ROLE = 'enterprise_learner'
SYSTEM_ENTERPRISE_OPERATOR_ROLE = 'enterprise_openedx_operator'
SYSTEM_ENTERPRISE_PROVISIONING_ADMIN_ROLE = 'enterprise_provisioning_admin'

SUBSCRIPTIONS_ADMIN_ACCESS_PERMISSION = 'subscriptions.has_admin_access'
SUBSCRIPTIONS_ADMIN_LEARNER_ACCESS_PERMISSION = 'subscriptions.has_learner_or_admin_access'

# Provisioning admins permissions
SUBSCRIPTIONS_PROVISIONING_ADMIN_ACCESS_PERMISSION = 'subscriptions.has_provisioning_admin_access'
SUBSCRIPTIONS_CUSTOMER_AGREEMENT_PROVISIONING_ADMIN_ACCESS_PERMISSION = \
    'agreements.has_provisioning_admin_access'

# Subsidy constants
PERCENTAGE_DISCOUNT_TYPE = 'percentage'
LICENSE_DISCOUNT_VALUE = 100  # Represents a 100% off value

# Salesforce constants
SALESFORCE_ID_LENGTH = 18  # The salesforce_opportunity_id must be exactly 18 characters

# User retirements constants
DAYS_TO_RETIRE = 90

# Subscription validation constants
MIN_NUM_LICENSES = 0
MAX_NUM_LICENSES = 1000000 # Set a reasonably high max to prevent us from crashing.

# Number of license uuids enrollments are expired for in each batch
LICENSE_EXPIRATION_BATCH_SIZE = 100

# Bulk operation constants
LICENSE_BULK_OPERATION_BATCH_SIZE = 100
PENDING_ACCOUNT_CREATION_BATCH_SIZE = 50
LICENSE_SOURCE_BULK_OPERATION_BATCH_SIZE = 100
TRACK_LICENSE_CHANGES_BATCH_SIZE = 25
ASSIGNMENT_EMAIL_BATCH_SIZE = 50
REMINDER_EMAIL_BATCH_SIZE = 50

# Num distinct catalog query validation batch size
VALIDATE_NUM_CATALOG_QUERIES_BATCH_SIZE = 100

# Feature Toggles

# Default sender alias for emails
DEFAULT_EMAIL_SENDER_ALIAS = 'edX Support Team'

# Error messages
BULK_ENROLL_TOO_MANY_ENROLLMENTS = 'Too many provided enrollments, please try a smaller request.'

# Deprecated Constants #
DEACTIVATED = 'deactivated'  # Deprecated for REVOKED

# License utilization emails
DAYS_BEFORE_INITIAL_UTILIZATION_EMAIL_SENT = 7

LICENSE_UTILIZATION_THRESHOLDS = [1, 0.75]
NOTIFICATION_CHOICE_AND_CAMPAIGN_BY_THRESHOLD = {
    1: (NotificationChoices.NO_ALLOCATIONS_REMAINING, 'NO_ALLOCATIONS_REMAINING_CAMPAIGN'),
    0.75: (NotificationChoices.LIMITED_ALLOCATIONS_REMAINING, 'LIMITED_ALLOCATIONS_REMAINING_CAMPAIGN')
}

ENTERPRISE_BRAZE_ALIAS_LABEL = 'Enterprise'  # Do Not change this, this is consistent with other uses across edX repos.
