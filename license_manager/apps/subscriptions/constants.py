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


# Subject lines used for emails for testing
LICENSE_ACTIVATION_EMAIL_SUBJECT = 'Start your edX Subscription'
LICENSE_REMINDER_EMAIL_SUBJECT = 'Your edX License is pending'
ONBOARDING_EMAIL_SUBJECT = 'Welcome to edX Subscriptions!'
REVOCATION_CAP_NOTIFICATION_EMAIL_SUBJECT = 'REVOCATION CAP REACHED: {}'

# Template names used for emails
LICENSE_ACTIVATION_EMAIL_TEMPLATE = 'activation'
LICENSE_REMINDER_EMAIL_TEMPLATE = 'reminder'
ONBOARDING_EMAIL_TEMPLATE = 'onboarding'
REVOCATION_CAP_NOTIFICATION_EMAIL_TEMPLATE = 'revocation_cap'

# Role-based access control
SUBSCRIPTIONS_ADMIN_ROLE = 'enterprise_subscriptions_admin'
SUBSCRIPTIONS_LEARNER_ROLE = 'enterprise_subscriptions_learner'

SYSTEM_ENTERPRISE_ADMIN_ROLE = 'enterprise_admin'
SYSTEM_ENTERPRISE_LEARNER_ROLE = 'enterprise_learner'
SYSTEM_ENTERPRISE_OPERATOR_ROLE = 'enterprise_openedx_operator'

SUBSCRIPTIONS_ADMIN_ACCESS_PERMISSION = 'subscriptions.has_admin_access'
SUBSCRIPTIONS_ADMIN_LEARNER_ACCESS_PERMISSION = 'subscriptions.has_learner_or_admin_access'

# Subsidy constants
PERCENTAGE_DISCOUNT_TYPE = 'percentage'
LICENSE_DISCOUNT_VALUE = 100  # Represents a 100% off value

# Salesforce constants
SALESFORCE_ID_LENGTH = 18  # The salesforce_opportunity_id must be exactly 18 characters

# User retirements constants
DAYS_TO_RETIRE = 90

# Subscription validation constants
MIN_NUM_LICENSES = 0
MAX_NUM_LICENSES = 5000

# Number of license uuids enrollments are expired for in each batch
LICENSE_EXPIRATION_BATCH_SIZE = 200

# Bulk operation constants
LICENSE_BULK_OPERATION_BATCH_SIZE = 100
PENDING_ACCOUNT_CREATION_BATCH_SIZE = 100

# Num distinct catalog query validation batch size
VALIDATE_NUM_CATALOG_QUERIES_BATCH_SIZE = 100

# Feature Toggles
EXPOSE_LICENSE_ACTIVATION_KEY_OVER_API = 'expose_license_activation_key_over_api'

# Default sender alias for emails
DEFAULT_EMAIL_SENDER_ALIAS = 'edX Support Team'


# Deprecated Constants #
DEACTIVATED = 'deactivated'  # Deprecated for REVOKED
