"""
Python APIs exposed by the Subscriptions app to other in-process apps.
"""
from ..api.tasks import revoke_course_enrollments_for_user_task
from .constants import ACTIVATED
from .exceptions import LicenseRevocationError


def revoke_license(user_license):
    """
    Arguments:
        user_license (License): The License to be revoked
    """
    # Number of revocations remaining can become negative if revoke max percentage is decreased
    if user_license.subscription_plan.num_revocations_remaining > 0:
        if user_license.status == ACTIVATED:
            # We should only need to revoke enrollments if the License has an original
            # status of ACTIVATED, pending users shouldn't have any enrollments.
            revoke_course_enrollments_for_user_task.delay(
                user_id=user_license.lms_user_id,
                enterprise_id=str(user_license.subscription_plan.enterprise_customer_uuid),
            )
            # License revocation only counts against the plan limit when status is ACTIVATED
            user_license.subscription_plan.num_revocations_applied += 1
            user_license.subscription_plan.save()

        # Revoke the license
        user_license.revoke()

        # Create new license to add to the unassigned license pool
        user_license.subscription_plan.increase_num_licenses(1)
    else:
        raise LicenseRevocationError(user_license.uuid)
