from license_manager.apps.subscriptions import constants


# Constants for subscriptions API tests
SUBSCRIPTION_RENEWAL_DAYS_OFFSET = 500
PROVISIONING_ADMINS_GROUP = "provisioning_admins_group"

ADMIN_ROLES = {
    'system_role': constants.SYSTEM_ENTERPRISE_ADMIN_ROLE,
    'subscriptions_role': constants.SUBSCRIPTIONS_ADMIN_ROLE,
}
LEARNER_ROLES = {
    'system_role': constants.SYSTEM_ENTERPRISE_LEARNER_ROLE,
    'subscriptions_role': constants.SUBSCRIPTIONS_LEARNER_ROLE,
}
