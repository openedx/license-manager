import logging

from celery import shared_task
from celery_utils.logged_task import LoggedTask

from license_manager.apps.api_client.enterprise import EnterpriseApiClient
from license_manager.apps.subscriptions.constants import (
    PENDING_ACCOUNT_CREATION_BATCH_SIZE,
)
from license_manager.apps.subscriptions.emails import (
    send_activation_emails,
    send_revocation_cap_notification_email,
)
from license_manager.apps.subscriptions.models import License, SubscriptionPlan
from license_manager.apps.subscriptions.utils import chunks


logger = logging.getLogger(__name__)

# Soft time out of 15 minutes, max time out of 16 minutes
SOFT_TIME_LIMIT = 900
MAX_TIME_LIMIT = 960


@shared_task(base=LoggedTask, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def activation_email_task(custom_template_text, email_recipient_list, subscription_uuid):
    """
    Sends license activation email(s) asynchronously, and creates pending enterprise users to link the email recipients
    to the subscription's enterprise.

    Arguments:
        custom_template_text (dict): Dictionary containing `greeting` and `closing` keys to be used for customizing
            the email template.
        email_recipient_list (list of str): List of recipients to send the emails to.
        subscription_uuid (str): UUID (string representation) of the subscription that the recipients are associated
            with or will be associated with.
    """
    subscription_plan = SubscriptionPlan.objects.get(uuid=subscription_uuid)
    pending_licenses = subscription_plan.licenses.filter(user_email__in=email_recipient_list).order_by('uuid')
    enterprise_api_client = EnterpriseApiClient()
    enterprise_slug = enterprise_api_client.get_enterprise_slug(subscription_plan.enterprise_customer_uuid)
    enterprise_name = enterprise_api_client.get_enterprise_name(subscription_plan.enterprise_customer_uuid)
    enterprise_sender_alias = enterprise_api_client.get_enterprise_sender_alias(
        subscription_plan.enterprise_customer_uuid
    )

    try:
        send_activation_emails(
            custom_template_text, pending_licenses, enterprise_slug, enterprise_name, enterprise_sender_alias
        )
    except Exception:  # pylint: disable=broad-except
        msg = 'License manager activation email sending received an exception for enterprise: {}.'.format(
            enterprise_name
        )
        logger.error(msg, exc_info=True)
        return


@shared_task(base=LoggedTask, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def link_learners_to_enterprise_task(learner_emails, enterprise_customer_uuid):
    """
    Links learners to an enterprise asynchronously.

    Arguments:
        learner_emails (list): list email addresses to link to the given enterprise.
        enterprise_customer_uuid (str): UUID (string representation) of the enterprise to link learns to.
    """
    enterprise_api_client = EnterpriseApiClient()

    for user_email_batch in chunks(learner_emails, PENDING_ACCOUNT_CREATION_BATCH_SIZE):
        enterprise_api_client.create_pending_enterprise_users(
            enterprise_customer_uuid,
            user_email_batch,
        )


@shared_task(base=LoggedTask, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def send_reminder_email_task(custom_template_text, email_recipient_list, subscription_uuid):
    """
    Sends license activation reminder email(s) asynchronously.

    Arguments:
        custom_template_text (dict): Dictionary containing `greeting` and `closing` keys to be used for customizing
            the email template.
        email_recipient_list (list of str): List of recipients to send the emails to.
        subscription_uuid (str): UUID (string representation) of the subscription that the recipients are associated
            with or will be associated with.
    """
    subscription_plan = SubscriptionPlan.objects.get(uuid=subscription_uuid)
    pending_licenses = subscription_plan.licenses.filter(user_email__in=email_recipient_list).order_by('uuid')
    enterprise_api_client = EnterpriseApiClient()
    enterprise_slug = enterprise_api_client.get_enterprise_slug(subscription_plan.enterprise_customer_uuid)
    enterprise_name = enterprise_api_client.get_enterprise_name(subscription_plan.enterprise_customer_uuid)
    enterprise_sender_alias = enterprise_api_client.get_enterprise_sender_alias(
        subscription_plan.enterprise_customer_uuid
    )

    try:
        send_activation_emails(
            custom_template_text,
            pending_licenses,
            enterprise_slug,
            enterprise_name,
            enterprise_sender_alias,
            is_reminder=True
        )
    except Exception:  # pylint: disable=broad-except
        msg = 'License manager reminder email sending received an exception for enterprise: {}.'.format(
            enterprise_name
        )
        logger.error(msg, exc_info=True)
        # Return without updating the last_remind_date for licenses
        return

    License.set_date_fields_to_now(pending_licenses, ['last_remind_date'])


@shared_task(base=LoggedTask, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def revoke_course_enrollments_for_user_task(user_id, enterprise_id):
    """
    Sends revoking the user's enterprise licensed course enrollments asynchronously

    Arguments:
        user_id (str): The ID of the user who had an enterprise license revoked
        enterprise_id (str): The ID of the enterprise to revoke course enrollments for
    """
    try:
        enterprise_api_client = EnterpriseApiClient()
        enterprise_api_client.revoke_course_enrollments_for_user(user_id=user_id, enterprise_id=enterprise_id)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(
            "Revocation of course enrollments FAILED for user [{user_id}], enterprise [{enterprise_id}]: {exc}".format(
                user_id=user_id,
                enterprise_id=enterprise_id,
                exc=exc,
            )
        )


@shared_task(base=LoggedTask, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def license_expiration_task(license_uuids):
    """
    Sends terminating the licensed course enrollments for the submitted license_uuids asynchronously

    Arguments:
        license_uuids (list of str): The UUIDs of the expired licenses
    """
    try:
        enterprise_api_client = EnterpriseApiClient()
        enterprise_api_client.bulk_licensed_enrollments_expiration(expired_license_uuids=license_uuids)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(
            "Expiration of course enrollments FAILED for licenses [{license_uuids}]: {exc}".format(
                license_uuids=license_uuids,
                exc=exc,
            )
        )


@shared_task(base=LoggedTask)
def send_revocation_cap_notification_email_task(subscription_uuid):
    """
    Sends revocation cap email notification to ECS asynchronously.

    Arguments:
        subscription_uuid (str): UUID (string representation) of the subscription that has reached its recovation cap.
    """
    subscription_plan = SubscriptionPlan.objects.get(uuid=subscription_uuid)
    enterprise_api_client = EnterpriseApiClient()
    enterprise_name = enterprise_api_client.get_enterprise_name(subscription_plan.enterprise_customer_uuid)
    enterprise_sender_alias = enterprise_api_client.get_enterprise_sender_alias(
        subscription_plan.enterprise_customer_uuid
    )

    try:
        send_revocation_cap_notification_email(
            subscription_plan,
            enterprise_name,
            enterprise_sender_alias,
        )
    except Exception:  # pylint: disable=broad-except
        logger.error('Revocation cap notification email sending received an exception.', exc_info=True)
