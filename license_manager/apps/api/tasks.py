from celery import shared_task
from celery_utils.logged_task import LoggedTask

from license_manager.apps.subscriptions.emails import (
    send_activation_emails,
    send_reminder_emails,
)
from license_manager.apps.subscriptions.models import SubscriptionPlan


@shared_task(base=LoggedTask)
def send_activation_email_task(custom_template_text, email_activation_key_map, subscription_uuid, enterprise_slug):
    """
    Sends license activation email(s) asynchronously

    Arguments:
        custom_template_text (dict): Dictionary containing `greeting` and `closing` keys to be used for customizing
            the email template.
        email_activation_key_map (dict): Dictionary containing the emails of each recipient and the activation key that
            is unique to the email. Recipient emails are the keys in the dictionary
        subscription_uuid (str): UUID (string representation) of the subscription that the recipients are associated
            with or will be associated with.
        enterprise_slug (str): The slug associated with an enterprise to uniquely identify it
    """
    subscription_plan = SubscriptionPlan.objects.get(uuid=subscription_uuid)
    send_activation_emails(custom_template_text, email_activation_key_map, subscription_plan, enterprise_slug)


@shared_task(base=LoggedTask)
def send_reminder_email_task(custom_template_text, email_recipient_list, subscription_uuid):
    """
    Sends license activation reminder email(s) asynchronously

    Arguments:
        custom_template_text (dict): Dictionary containing `greeting` and `closing` keys to be used for customizing
            the email template.
        email_recipient_list (list of str): List of recipients to send the emails to.
        subscription_uuid (str): UUID (string representation) of the subscription that the recipients are associated
            with or will be associated with.
    """
    subscription_plan = SubscriptionPlan.objects.get(uuid=subscription_uuid)
    send_reminder_emails(custom_template_text, email_recipient_list, subscription_plan)
