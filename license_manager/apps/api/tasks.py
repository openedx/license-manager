import logging

from celery import shared_task
from celery_utils.logged_task import LoggedTask

from license_manager.apps.api_client.enterprise import EnterpriseApiClient
from license_manager.apps.subscriptions.emails import (
    send_activation_emails,
    send_revocation_cap_notification_email,
)
from license_manager.apps.subscriptions.models import License, SubscriptionPlan


logger = logging.getLogger(__name__)


@shared_task(base=LoggedTask)
def activation_task(custom_template_text, email_recipient_list, subscription_uuid):
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
    send_activation_emails(custom_template_text, pending_licenses, enterprise_slug)
    License.set_date_fields_to_now(pending_licenses, ['last_remind_date', 'assigned_date'])

    for email_recipient in email_recipient_list:
        enterprise_api_client.create_pending_enterprise_user(
            subscription_plan.enterprise_customer_uuid,
            email_recipient,
        )


@shared_task(base=LoggedTask)
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

    try:
        send_activation_emails(
            custom_template_text,
            pending_licenses,
            enterprise_slug,
            is_reminder=True
        )
    except Exception:  # pylint: disable=broad-except
        logger.error('License manager activation email sending received an exception.', exc_info=True)
        # Return without updating the last_remind_date for licenses
        return

    License.set_date_fields_to_now(pending_licenses, ['last_remind_date'])


@shared_task(base=LoggedTask)
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

    try:
        send_revocation_cap_notification_email(
            subscription_plan,
            enterprise_name,
        )
    except Exception:  # pylint: disable=broad-except
        logger.error('Revocation cap notification email sending received an exception.', exc_info=True)
