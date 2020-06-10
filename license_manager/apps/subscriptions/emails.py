from django.conf import settings
from django.core import mail
from django.template.loader import get_template

from license_manager.apps.subscriptions.constants import (
    LICENSE_ACTIVATION_EMAIL_SUBJECT,
    LICENSE_ACTIVATION_EMAIL_TEMPLATE,
)


def send_activation_emails(custom_template_text, email_recipient_list, subscription_expiration_date):
    """
    Send a license activation email to a given set of users
    """
    # Construct each message to be sent and append onto the activation_emails list
    activation_emails = []
    for email_address in email_recipient_list:
        # Construct user specific context for each message
        context = {
            'LICENSE_ACTIVATION_LINK': _generate_license_activation_link(),
            'USER_EMAIL': email_address,
        }
        activation_emails.append(_message_from_context_and_template(
            context,
            LICENSE_ACTIVATION_EMAIL_TEMPLATE,
            custom_template_text,
            subscription_expiration_date
        ))

    # Use a single connection to send all messages
    with mail.get_connection() as connection:
        connection.open()
        connection.send_messages(activation_emails)
        connection.close()


def _generate_license_activation_link():  # TODO: implement 'How users will activate licenses' (ENT-2748)
    return 'https://www.edx.org/'


def _get_rendered_template_content(template_name, extension, context):
    """
    Returns the rendered content for a given template name and file extension
    """
    message_template = 'email/' + template_name + extension
    return get_template(message_template).render(context)


def _message_from_context_and_template(context, template_name, custom_template_text, expiration_date):
    """
    Creates an activation email to be sent to a learner

    Returns:
        EmailMultiAlternative: an individual message constructed from the information provided, not yet sent
    """
    # Update context to be used for Django template rendering
    context.update({
        'EXPIRATION_DATE': expiration_date,
        'TEMPLATE_CLOSING': custom_template_text['closing'],
        'TEMPLATE_GREETING': custom_template_text['greeting'],
        'UNSUBSCRIBE_LINK': settings.EMAIL_UNSUBSCRIBE_LINK,
    })

    # Render the message contents using Django templates
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
        subject=LICENSE_ACTIVATION_EMAIL_SUBJECT,
        body=txt_content,
        from_email=from_email_string,
        to=[context['USER_EMAIL']],
        bcc=[],
        headers=message_headers
    )
    message.attach_alternative(html_content, 'text/html')
    return message
