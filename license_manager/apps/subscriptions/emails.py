import logging

from django.conf import settings
from django.core import mail
from django.template.loader import get_template

from license_manager.apps.api.utils import localized_utcnow
from license_manager.apps.subscriptions.constants import (
    ASSIGNED,
    LICENSE_ACTIVATION_EMAIL_SUBJECT,
    LICENSE_ACTIVATION_EMAIL_TEMPLATE,
    LICENSE_REMINDER_EMAIL_SUBJECT,
)
from license_manager.apps.subscriptions.models import License


logger = logging.getLogger(__name__)


def send_activation_emails(custom_template_text, email_activation_key_map, subscription_plan, enterprise_slug):
    """
    Sends an activation email updated with the custom template text to the given recipients.

    Args:
        custom_template_text (dict): Dictionary containing `greeting` and `closing` keys to be used for customizing
            the email template.
        email_activation_key_map (dict): Dictionary containing the emails of each recipient and the activation key that
            is unique to the email. Recipient emails are the keys in the dictionary
        subscription_plan (SubscriptionPlan): The subscription that the recipients are associated with or
            will be associated with.
        enterprise_slug (str): The slug associated with an enterprise to uniquely identify it
    """
    context = {
        'template_name': LICENSE_ACTIVATION_EMAIL_TEMPLATE,
        'subject': LICENSE_ACTIVATION_EMAIL_SUBJECT,
    }
    _send_email_with_activation(
        custom_template_text,
        email_activation_key_map,
        subscription_plan,
        context,
        enterprise_slug
    )


def send_reminder_emails(custom_template_text, email_recipient_list, subscription_plan):
    """
    Sends a reminder email updated with the custom template text to the given recipients.

    Args:
        custom_template_text (dict): Dictionary containing `greeting` and `closing` keys to be used for customizing
            the email template.
        email_recipient_list (list of str): List of recipients to send the emails to.
        subscription_plan (SubscriptionPlan): The subscription that the recipients are associated with or
            will be associated with.
    """
    context = {
        'template_name': LICENSE_ACTIVATION_EMAIL_TEMPLATE,
        'subject': LICENSE_REMINDER_EMAIL_SUBJECT,
        'REMINDER': True,
    }
    try:
        _send_email_with_activation(
            custom_template_text,
            email_recipient_list,
            subscription_plan,
            context,
        )
    except Exception:  # pylint: disable=broad-except
        logger.warning('License manager activation email sending received an exception.', exc_info=True)
        # Return without updating the last_remind_date for licenses
        return

    # Gather the licenses for each email that's been reminded
    pending_licenses = License.objects.filter(
        subscription_plan=subscription_plan,
        status=ASSIGNED,
        user_email__in=email_recipient_list
    )

    # Set last remind date to now for all pending licenses
    for pending_license in pending_licenses:
        pending_license.last_remind_date = localized_utcnow()
    License.objects.bulk_update(pending_licenses, ['last_remind_date'])


def _send_email_with_activation(
    custom_template_text,
    email_activation_key_map,
    subscription_plan,
    context,
    enterprise_slug
):
    """
    Helper that sends emails with the given template with an activation link to the the given list of emails.

    Args:
        custom_template_text (dict): Dictionary containing `greeting` and `closing` keys to be used for customizing
            the email template.
        email_activation_key_map (dict): Dictionary containing the emails of each recipient and the activation key that
            is unique to the email. Recipient emails are the keys in the dictionary
        subscription_plan (SubscriptionPlan): The subscription that the recipients are associated with or
            will be associated with.
        context (dict): Dictionary of context variables for template rendering. Context takes an optional `REMINDER`
            key. If `REMINDER` is provided, a reminder message is added to the email.
        enterprise_slug (str): The slug associated with an enterprise to uniquely identify it
    """
    # Construct each message to be sent and appended onto the email list
    email_recipient_list = email_activation_key_map.keys()
    emails = []
    for email_address in email_recipient_list:
        # Construct user specific context for each message
        context.update({
            'LICENSE_ACTIVATION_LINK': _generate_license_activation_link(
                enterprise_slug,
                email_activation_key_map.get(email_address)
            ),
            'USER_EMAIL': email_address,
        })
        emails.append(_message_from_context_and_template(
            context,
            custom_template_text,
            subscription_plan,
        ))

    # Use a single connection to send all messages
    with mail.get_connection() as connection:
        connection.send_messages(emails)


def _generate_license_activation_link(enterprise_slug, activation_key):
    """
    Returns the activation link displayed in the activation email sent to a learner
    """
    return settings.ENTERPRISE_LEARNER_PORTAL_BASE_URL + '/' + enterprise_slug + '/licenses/' +\
        activation_key + '/activate'


def _get_rendered_template_content(template_name, extension, context):
    """
    Returns the rendered content for a given template name and file extension
    """
    message_template = 'email/' + template_name + extension
    return get_template(message_template).render(context)


def _message_from_context_and_template(context, custom_template_text, subscription_plan):
    """
    Creates a message about the subscription_plan in the template specified by the context, with custom_template_text.

    Args:
        context (dict): Dictionary of context variables for template rendering.
        custom_template_text (dict): Dictionary containing `greeting` and `closing` keys to be used for customizing
            the email template.
        subscription_plan (SubscriptionPlan): The subscription that the recipients are associated with or
            will be associated with.

    Returns:
        EmailMultiAlternative: an individual message constructed from the information provided, not yet sent
    """
    # Update context to be used for Django template rendering
    context.update({
        'EXPIRATION_DATE': subscription_plan.expiration_date,
        'TEMPLATE_CLOSING': custom_template_text['closing'],
        'TEMPLATE_GREETING': custom_template_text['greeting'],
        'UNSUBSCRIBE_LINK': settings.EMAIL_UNSUBSCRIBE_LINK,
    })

    # Render the message contents using Django templates
    template_name = context['template_name']
    txt_content = _get_rendered_template_content(template_name, '.txt', context)
    html_content = _get_rendered_template_content(template_name, '.html', context)

    # Display sender name in addition to the email address
    from_email_string = '"edX Support Team" <' + settings.SUBSCRIPTIONS_FROM_EMAIL + '>'

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
        to=[context['USER_EMAIL']],
        bcc=[],
        headers=message_headers
    )
    message.attach_alternative(html_content, 'text/html')
    return message
