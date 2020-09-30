"""
Python APIs exposed by the Subscriptions app to other in-process apps.
"""
from ..api.tasks import revoke_course_enrollments_for_user_task
from .constants import ACTIVATED
from .exceptions import LicenseRevocationError


def revoke_license(lic):
    """
    Arguments:
        lic (License): The License to be revoked
    """
    # Number of revocations remaining can become negative if revoke max percentage is decreased
    if lic.subscription_plan.num_revocations_remaining > 0:
        if lic.status == ACTIVATED:
            # We should only need to revoke enrollments if the License has an original
            # status of ACTIVATED, pending users shouldn't have any enrollments.
            revoke_course_enrollments_for_user_task.delay(
                user_id=lic.lms_user_id,
                enterprise_id=str(lic.subscription_plan.enterprise_customer_uuid),
            )

        # Revoke the license
        lic.revoke()
    else:
        raise LicenseRevocationError(lic.uuid)
