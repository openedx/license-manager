"""
Python APIs exposed by the Subscriptions app to other in-process apps.
"""
from ..api.tasks import (
    revoke_course_enrollments_for_user_task,
    send_revocation_cap_notification_email_task,
)
from .constants import ACTIVATED, ASSIGNED
from .exceptions import LicenseRevocationError
from .utils import localized_utcnow


def revoke_license(user_license):
    """
    Revoke a License.

    Arguments:
        user_license (License): The License to be revoked
    """
    # Number of revocations remaining can become negative if revoke max percentage is decreased
    revoke_limit_reached = user_license.subscription_plan.num_revocations_remaining <= 0
    # Revocation of ASSIGNED licenses is not limited
    if revoke_limit_reached and user_license.status == ACTIVATED:
        raise LicenseRevocationError(
            user_license.uuid,
            "License revocation limit has been reached."
        )
    # Only allow revocation for ASSIGNED and ACTIVATED licenses
    if user_license.status not in [ACTIVATED, ASSIGNED]:
        raise LicenseRevocationError(
            user_license.uuid,
            "License with status of {license_status} cannot be revoked.".format(
                license_status=user_license.status
            )
        )

    if user_license.status == ACTIVATED:
        # We should only need to revoke enrollments if the License has an original
        # status of ACTIVATED, pending users shouldn't have any enrollments.
        revoke_course_enrollments_for_user_task.delay(
            user_id=user_license.lms_user_id,
            enterprise_id=str(user_license.subscription_plan.enterprise_customer_uuid),
        )
        # Revocation only counts against the limit for ACTIVATED licenses
        user_license.subscription_plan.num_revocations_applied += 1
        user_license.subscription_plan.save()

    if user_license.subscription_plan.num_revocations_remaining <= 0:
        # Send email notification to ECS that the Subscription Plan has reached its revocation cap
        send_revocation_cap_notification_email_task.delay(
            subscription_uuid=user_license.subscription_plan.uuid,
        )

    # Revoke the license
    user_license.revoke()
    # Create new license to add to the unassigned license pool
    user_license.subscription_plan.increase_num_licenses(1)


def activate_license_for_user_id(user_license, user_id):
    if user_license.status != constants.ASSIGNED:
        return False

    user_license.activate(user_id)
    user_license.save()
    return True
