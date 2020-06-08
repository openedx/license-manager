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

    # Construct context to be used for Django template rendering
    context = {
        'TEMPLATE_GREETING': custom_template_text['greeting'],
        'EXPIRATION_DATE': subscription_expiration_date,
        'TEMPLATE_CLOSING': custom_template_text['closing'],
    }

    # Construct each message to be sent and append onto the activation_emails list
    activation_emails = []
    for email_address in email_recipient_list:
        # Update user specific context for each message
        context.update({
            'LICENSE_ACTIVATION_LINK': _generate_license_activation_link(),
            'USER_EMAIL': email_address,
        })
        activation_emails.append(_message_from_context_and_template(context, LICENSE_ACTIVATION_EMAIL_TEMPLATE))

    # Use a single connection to send all messages
    with mail.get_connection() as connection:
        connection.open()
        connection.send_messages(activation_emails)
        connection.close()


def _generate_license_activation_link():  # TODO: implement 'How users will activate licenses' (ENT-2748)
    return 'edx.org'


def _message_from_context_and_template(context, template_name):
    """
    Creates an activation email to be sent to a learner

    Returns:
        EmailMultiAlternative: an individual message constructed from the information provided, not yet sent
    """
    # Render the message contents using Django templates
    txt_template = 'email/' + template_name + '.txt'
    html_template = 'email/' + template_name + '.html'
    template = get_template(txt_template)
    txt_content = template.render(context)
    template = get_template(html_template)
    html_content = template.render(context)

    message = mail.EmailMultiAlternatives(
        subject=LICENSE_ACTIVATION_EMAIL_SUBJECT,
        body=txt_content,
        from_email=settings.SUBSCRIPTIONS_FROM_EMAIL,
        to=[context['USER_EMAIL']],
        bcc=[],
    )
    message.attach_alternative(html_content, 'text/html')
    return message
