from django.conf import settings
from django.core import mail

from license_manager.apps.subscriptions.constants import (
    LICENSE_ACTIVATION_EMAIL_SUBJECT
)


def send_activation_emails(email_template, email_recipient_list, subscription_expiration_date):
    """
    Send an email using a template, asynchronously, to a given list of users
    """
    with mail.get_connection() as connection:
        # Use the same email backend connection to send all messages
        connection.open()
        activation_emails = []
        # Construct each message to be sent and append onto the activation_emails list
        for email_address in email_recipient_list:
            email_message = _activation_message_from_template(
                email_template,
                email_address,
                subscription_expiration_date
            )
            activation_emails.append(email_message)
        # Send the messages and close the connection
        connection.send_messages(activation_emails)
        connection.close()


def _activation_message_from_template(email_template, email_recipient_address, subscription_expiration_date):
    """
    Creates an activation email to be sent to a learner

    Returns:
        EmailMessage: an individual message constructed from the information provided, not yet sent
    """
    # TODO: double-check that each of the template fields should be separated by two newlines
    email_message_skeleton = '{EMAIL_GREETING}\n\n{EMAIL_BODY}\n\n{EMAIL_CLOSING}'
    # Insert values into the email_template body placeholders
    email_body_formatted = email_template.body.format(USER_EMAIL=email_recipient_address,
                                                      EXPIRATION_DATE=subscription_expiration_date)
    # Insert values into the email_message_skeleton placeholders
    email_message = email_message_skeleton.format(EMAIL_GREETING=email_template.greeting,
                                                  EMAIL_BODY=email_body_formatted,
                                                  EMAIL_CLOSING=email_template.closing)
    return mail.EmailMessage(
        subject=LICENSE_ACTIVATION_EMAIL_SUBJECT,
        body=email_message,
        from_email=settings.SUBSCRIPTIONS_FROM_EMAIL,
        to=[email_recipient_address],
        bcc=[],

    )
