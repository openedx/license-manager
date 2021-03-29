from django.conf import settings
from django.core import mail
from django.template.loader import get_template

from license_manager.apps.subscriptions.constants import (
    LICENSE_ACTIVATION_EMAIL_SUBJECT,
    LICENSE_ACTIVATION_EMAIL_TEMPLATE,
    LICENSE_BULK_OPERATION_BATCH_SIZE,
    LICENSE_REMINDER_EMAIL_SUBJECT,
    LICENSE_REMINDER_EMAIL_TEMPLATE,
    REVOCATION_CAP_NOTIFICATION_EMAIL_SUBJECT,
    REVOCATION_CAP_NOTIFICATION_EMAIL_TEMPLATE,
)
from license_manager.apps.subscriptions.utils import (
    chunks,
    get_license_activation_link,
)


def send_revocation_cap_notification_email(subscription_plan, enterprise_name, enterprise_sender_alias):
    """
    Sends an email to inform ECS that a subscription plan for a customer has reached its
    revocation cap, and that action may be necessary to help the customer add more licenses.
    """
    context = {
        'template_name': REVOCATION_CAP_NOTIFICATION_EMAIL_TEMPLATE,
        'subject': REVOCATION_CAP_NOTIFICATION_EMAIL_SUBJECT.format(subscription_plan.title),
        'SUBSCRIPTION_TITLE': subscription_plan.title,
        'ENTERPRISE_NAME': enterprise_name,
        'NUM_REVOCATIONS_APPLIED': subscription_plan.num_revocations_applied,
        'RECIPIENT_EMAIL': settings.CUSTOMER_SUCCESS_EMAIL_ADDRESS,
        'HIDE_EMAIL_FOOTER_MARKETING': True,
    }
    email = _message_from_context_and_template(context, enterprise_sender_alias)
    email.send()


def send_activation_emails(
    custom_template_text,
    pending_licenses,
    enterprise_slug,
    enterprise_name,
    enterprise_sender_alias,
    is_reminder=False
):
    """
    Sends an email to a learner to prompt them to activate their subscription license

    Args:
        custom_template_text (dict): Dictionary containing `greeting` and `closing` keys to be used for customizing
            the email template.
        pending_licenses (Iterable): Licenses that are currently assigned to a learner that haven't been activated yet
        subscription_plan (SubscriptionPlan): The subscription that the recipients are associated with or
            will be associated with.
        enterprise_slug (str): The slug associated with an enterprise to uniquely identify it
        enterprise_sender_alias (str): Sender alias of the enterprise customer
        is_reminder (bool): whether this is a reminder activation email being sent
    """
    context = {
        'template_name': LICENSE_REMINDER_EMAIL_TEMPLATE if is_reminder else LICENSE_ACTIVATION_EMAIL_TEMPLATE,
        'subject': (LICENSE_ACTIVATION_EMAIL_SUBJECT, LICENSE_REMINDER_EMAIL_SUBJECT)[is_reminder],
        'TEMPLATE_CLOSING': custom_template_text['closing'],
        'TEMPLATE_GREETING': custom_template_text['greeting'],
        'ENTERPRISE_NAME': enterprise_name,
    }
    email_activation_key_map = {}
    for pending_license in pending_licenses:
        email_activation_key_map.update({pending_license.user_email: str(pending_license.activation_key)})

    _send_email_with_activation(
        email_activation_key_map,
        context,
        enterprise_slug,
        enterprise_sender_alias,
    )


def _send_email_with_activation(email_activation_key_map, context, enterprise_slug, sender_alias):
    """
    Helper that sends emails with the given template with an activation link to the the given list of emails.

    Args:
        email_activation_key_map (dict): Dictionary containing the emails of each recipient and the activation key that
            is unique to the email. Recipient emails are the keys in the dictionary.
        context (dict): Dictionary of context variables for template rendering. Context takes an optional `REMINDER`
            key. If `REMINDER` is provided, a reminder message is added to the email.
        enterprise_slug (str): The slug associated with an enterprise to uniquely identify it.
        sender_alias (str): The alias to use in from email for sending the email.
    """
    # Construct each message to be sent and appended onto the email list
    email_recipient_list = email_activation_key_map.keys()
    emails = []
    for email_address in email_recipient_list:
        # Construct user specific context for each message
        context.update({
            'LICENSE_ACTIVATION_LINK': get_license_activation_link(
                enterprise_slug,
                email_activation_key_map.get(email_address)
            ),
            'RECIPIENT_EMAIL': email_address,
            'SOCIAL_MEDIA_FOOTER_URLS': settings.SOCIAL_MEDIA_FOOTER_URLS,
            'MOBILE_STORE_URLS': settings.MOBILE_STORE_URLS,
        })
        emails.append(_message_from_context_and_template(context, sender_alias))

    # Send out the emails in batches
    email_chunks = chunks(emails, LICENSE_BULK_OPERATION_BATCH_SIZE)
    for email_chunk in email_chunks:
        # Renew the email connection for each chunk of emails sent
        with mail.get_connection() as connection:
            connection.send_messages(email_chunk)


def _get_rendered_template_content(template_name, extension, context):
    """
    Returns the rendered content for a given template name and file extension
    """
    message_template = 'email/' + template_name + extension
    return get_template(message_template).render(context)


def _message_from_context_and_template(context, sender_alias):
    """
    Creates a message about the subscription_plan in the template specified by the context, with custom_template_text.

    Args:
        context (dict): Dictionary of context variables for template rendering.
        sender_alias (str): The alias to use in from email for sending the email.

    Returns:
        EmailMultiAlternative: an individual message constructed from the information provided, not yet sent
    """
    # Update context to be used for Django template rendering
    context.update({
        'UNSUBSCRIBE_LINK': settings.EMAIL_UNSUBSCRIBE_LINK,
    })

    # Render the message contents using Django templates
    template_name = context['template_name']
    txt_content = _get_rendered_template_content(template_name, '.txt', context)
    html_content = _get_rendered_template_content(template_name, '.html', context)

    # Display sender name in addition to the email address
    from_email_string = '"{sender_alias}" <{from_email}>'.format(
        sender_alias=sender_alias,
        from_email=settings.SUBSCRIPTIONS_FROM_EMAIL,
    )

    # Using both the mailto: and https:// methods for the List-Unsubscribe header
    list_unsubscribe_header = '<mailto:' + settings.SUBSCRIPTIONS_FROM_EMAIL + '?subject=unsubscribe>' + \
        ', <' + settings.EMAIL_UNSUBSCRIBE_LINK + '>'

    # Additional headers to attach to the message
    message_headers = {
        'List-Unsubscribe': list_unsubscribe_header
    }

    message = mail.EmailMultiAlternatives(
        subject=context['subject'],
        body=txt_content,
        from_email=from_email_string,
        to=[context['RECIPIENT_EMAIL']],
        bcc=[],
        headers=message_headers,
    )
    message.attach_alternative(html_content, 'text/html')
    return message
