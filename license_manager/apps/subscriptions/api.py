"""
Python APIs exposed by the Subscriptions app to other in-process apps.
"""
from ..api.tasks import revoke_course_enrollments_for_user_task
from .constants import ACTIVATED, ASSIGNED
from .exceptions import LicenseRevocationError


def revoke_license(user_license):
    """
    Revoke a License.

    Arguments:
        user_license (License): The License to be revoked
    """
    # Number of revocations remaining can become negative if revoke max percentage is decreased
    revoke_limit_reached = user_license.subscription_plan.num_revocations_remaining <= 0
    # Revocation of ASSIGNED licenses is not limited
    revoke_limit_reached &= user_license.status == ACTIVATED
    # Only allow revocation for ASSIGNED and ACTIVATED licenses
    if user_license.status not in [ACTIVATED, ASSIGNED] or revoke_limit_reached:
        raise LicenseRevocationError(user_license.uuid)

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

    # Revoke the license
    user_license.revoke()
    # Create new license to add to the unassigned license pool
    user_license.subscription_plan.increase_num_licenses(1)
