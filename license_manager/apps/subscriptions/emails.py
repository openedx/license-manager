from django.conf import settings
from django.core import mail
from django.template.loader import get_template

from license_manager.apps.subscriptions.constants import (
    LICENSE_ACTIVATION_EMAIL_SUBJECT,
    LICENSE_ACTIVATION_EMAIL_TEMPLATE,
    LICENSE_REMINDER_EMAIL_SUBJECT,
)


def send_activation_emails(custom_template_text, email_recipient_list, subscription_plan):
    """
    Sends an activation email updated with the custom template text to the given recipients.

    Args:
        custom_template_text (dict): Dictionary containing `greeting` and `closing` keys to be used for customizing
            the email template.
        email_recipient_list (list of str): List of recipients to send the emails to.
        subscription_plan (SubscriptionPlan): The subscription that the recipients are associated with or
            will be associated with.
    """
    context = {
        'template_name': LICENSE_ACTIVATION_EMAIL_TEMPLATE,
        'subject': LICENSE_ACTIVATION_EMAIL_SUBJECT,
    }
    _send_email_with_activation(
        custom_template_text,
        email_recipient_list,
        subscription_plan,
        context,
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
    _send_email_with_activation(
        custom_template_text,
        email_recipient_list,
        subscription_plan,
        context,
    )


def _send_email_with_activation(custom_template_text, email_recipient_list, subscription_plan, context):
    """
    Helper that sends emails with the given template with an activation link to the the given list of emails.

    Args:
        custom_template_text (dict): Dictionary containing `greeting` and `closing` keys to be used for customizing
            the email template.
        email_recipient_list (list of str): List of recipients to send the emails to.
        subscription_plan (SubscriptionPlan): The subscription that the recipients are associated with or
            will be associated with.
        context (dict): Dictionary of context variables for template rendering. Context takes an optional `REMINDER`
            key. If `REMINDER` is provided, a reminder message is added to the email.
    """
    # Construct each message to be sent and appended onto the email list
    emails = []
    for email_address in email_recipient_list:
        # Construct user specific context for each message
        context.update({
            'LICENSE_ACTIVATION_LINK': _generate_license_activation_link(),
            'USER_EMAIL': email_address,
        })
        emails.append(_message_from_context_and_template(
            context,
            custom_template_text,
            subscription_plan,
        ))

    # Use a single connection to send all messages
    with mail.get_connection() as connection:
        connection.open()
        connection.send_messages(emails)
        connection.close()


def _generate_license_activation_link():  # TODO: implement 'How users will activate licenses' (ENT-2748)
    return 'https://www.edx.org/'


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
