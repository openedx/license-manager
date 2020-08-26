# License status choices
ACTIVATED = 'activated'
ASSIGNED = 'assigned'
UNASSIGNED = 'unassigned'
DEACTIVATED = 'deactivated'
LICENSE_STATUS_CHOICES = (
    (ACTIVATED, 'Activated'),
    (ASSIGNED, 'Assigned'),
    (UNASSIGNED, 'Unassigned'),
    (DEACTIVATED, 'Deactivated'),
)

# Subject lines used for emails
LICENSE_ACTIVATION_EMAIL_SUBJECT = 'edX License Activation'
LICENSE_REMINDER_EMAIL_SUBJECT = 'Your edX License is pending'

# Template names used for emails
LICENSE_ACTIVATION_EMAIL_TEMPLATE = 'activation'

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
MAX_NUM_LICENSES = 1000

# SQL bulk operation constants
LICENSE_BULK_OPERATION_BATCH_SIZE = 100
