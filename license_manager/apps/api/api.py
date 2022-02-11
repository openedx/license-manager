
import logging
from uuid import uuid4

from celery import chain

from license_manager.apps.api import tasks
from license_manager.apps.api.utils import get_custom_text
from license_manager.apps.subscriptions import event_utils
from license_manager.apps.subscriptions.constants import (
    ACTIVATED,
    ASSIGNED,
    PENDING_ACCOUNT_CREATION_BATCH_SIZE,
    SegmentEvents,
)
from license_manager.apps.subscriptions.models import License
from license_manager.apps.subscriptions.utils import chunks, localized_utcnow


logger = logging.getLogger(__name__)


def link_and_notify_assigned_emails(request_data, subscription_plan, user_emails):
    """
    Helper to create async chains of the pending learners and activation emails tasks with each batch of users
    The task signatures are immutable, hence the `si()` - we don't want the result of the
    link_learners_to_enterprise_task passed to the "child" send_assignment_email_task.

    If disable_onboarding_notifications is set to true on the CustomerAgreement,
    Braze aliases will be created but no activation email will be sent:
    """

    customer_agreement = subscription_plan.customer_agreement
    disable_onboarding_notifications = customer_agreement.disable_onboarding_notifications

    for pending_learner_batch in chunks(user_emails, PENDING_ACCOUNT_CREATION_BATCH_SIZE):
        tasks_chain = chain(
            tasks.link_learners_to_enterprise_task.si(
                pending_learner_batch,
                subscription_plan.enterprise_customer_uuid,
            ),
            tasks.create_braze_aliases_task.si(
                pending_learner_batch
            )
        )

        if not disable_onboarding_notifications:
            tasks_chain.link(
                tasks.send_assignment_email_task.si(
                    get_custom_text(request_data),
                    pending_learner_batch,
                    str(subscription_plan.uuid),
                )
            )

        tasks_chain.apply_async()


def assign_new_licenses(subscription_plan, user_emails):
    """
    Assign licenses for the given user_emails (that have not already been revoked).

    Returns a QuerySet of licenses that are assigned.
    """
    licenses = subscription_plan.unassigned_licenses[:len(user_emails)]
    now = localized_utcnow()
    for unassigned_license, email in zip(licenses, user_emails):
        # Assign each email to a license and mark the license as assigned
        unassigned_license.user_email = email
        unassigned_license.status = ASSIGNED
        unassigned_license.activation_key = str(uuid4())
        unassigned_license.assigned_date = now
        unassigned_license.last_remind_date = now

    License.bulk_update(
        licenses,
        ['user_email', 'status', 'activation_key', 'assigned_date', 'last_remind_date'],
        batch_size=10,
    )

    license_uuid_strs = [str(_license.uuid) for _license in licenses]
    tasks.track_license_changes_task.delay(
        license_uuid_strs,
        SegmentEvents.LICENSE_ASSIGNED,
    )
    return licenses


def execute_post_revocation_tasks(revoked_license, original_status):
    """
    Executes a set of tasks after a license has been revoked.

    Tasks:
        - Revoke enrollments if the License has an original status of ACTIVATED.
        - Send email notification to ECS if the Subscription Plan has reached its revocation cap.
    """

    # We should only need to revoke enrollments if the License has an original
    # status of ACTIVATED, pending users shouldn't have any enrollments.
    if original_status == ACTIVATED:
        tasks.revoke_course_enrollments_for_user_task.delay(
            user_id=revoked_license.lms_user_id,
            enterprise_id=str(revoked_license.subscription_plan.enterprise_customer_uuid),
        )

    if not revoked_license.subscription_plan.has_revocations_remaining:
        # Send email notification to ECS that the Subscription Plan has reached its revocation cap
        tasks.send_revocation_cap_notification_email_task.delay(
            subscription_uuid=revoked_license.subscription_plan.uuid,
        )

    logger.info('License {} has been revoked'.format(revoked_license.uuid))


def auto_apply_new_license(subscription_plan, user_email, lms_user_id):
    """
    Auto-apply licenses for the given user_email and lms_user_id.

    Returns the auto-applied (activated) license.
    """
    now = localized_utcnow()

    auto_applied_license = subscription_plan.unassigned_licenses.first()
    if not auto_applied_license:
        return None

    auto_applied_license.user_email = user_email
    auto_applied_license.lms_user_id = lms_user_id
    auto_applied_license.status = ACTIVATED
    auto_applied_license.activation_key = str(uuid4())
    auto_applied_license.activation_date = now
    auto_applied_license.assigned_date = now
    auto_applied_license.last_remind_date = now
    auto_applied_license.auto_applied = True

    auto_applied_license.save()
    event_utils.track_license_changes([auto_applied_license], SegmentEvents.LICENSE_ACTIVATED)
    event_utils.identify_braze_alias(lms_user_id, user_email)
    tasks.send_utilization_threshold_reached_email_task.delay(subscription_plan.uuid)

    return auto_applied_license
