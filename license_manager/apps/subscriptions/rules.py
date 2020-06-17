"""
Rules needed to restrict access to the license management service.
"""
import crum
import rules
from edx_rbac.utils import (
    get_decoded_jwt,
    request_user_has_implicit_access_via_jwt,
    user_has_access_via_database,
)

from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.models import (
    SubscriptionsRoleAssignment,
)


@rules.predicate
def has_implicit_access_to_subscriptions_admin(user, subscription_plan):  # pylint: disable=unused-argument
    """
    Check that if request user has implicit access to the given SubscriptionPlan for the
    `SUBSCRIPTIONS_ADMIN_ROLE` feature role.

    Returns:
        boolean: whether the request user has access.
    """
    if not subscription_plan:
        return False

    return request_user_has_implicit_access_via_jwt(
        get_decoded_jwt(crum.get_current_request()),
        constants.SUBSCRIPTIONS_ADMIN_ROLE,
        str(subscription_plan.enterprise_customer_uuid),
    )


@rules.predicate
def has_explicit_access_to_subscriptions_admin(user, subscription_plan):
    """
    Check that if request user has explicit access to `SUBSCRIPTIONS_ADMIN_ROLE` feature role.
    Returns:
        boolean: whether the request user has access.
    """
    if not subscription_plan:
        return False

    return user_has_access_via_database(
        user,
        constants.SUBSCRIPTIONS_ADMIN_ROLE,
        SubscriptionsRoleAssignment,
        str(subscription_plan.enterprise_customer_uuid),
    )


rules.add_perm(
    constants.SUBSCRIPTIONS_ADMIN_ACCESS_PERMISSION,
    has_implicit_access_to_subscriptions_admin | has_explicit_access_to_subscriptions_admin
)
