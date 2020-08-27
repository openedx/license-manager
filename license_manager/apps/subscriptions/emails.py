from django.conf import settings
from django.core import mail
from django.template.loader import get_template

from license_manager.apps.subscriptions.constants import (
    LICENSE_ACTIVATION_EMAIL_SUBJECT,
    LICENSE_ACTIVATION_EMAIL_TEMPLATE,
    LICENSE_REMINDER_EMAIL_SUBJECT,
)


def send_activation_emails(
    custom_template_text,
    pending_licenses,
    subscription_plan,
    enterprise_slug,
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
        is_reminder (bool): whether this is a reminder activation email being sent
    """
    context = {
        'template_name': LICENSE_ACTIVATION_EMAIL_TEMPLATE,
        'subject': (LICENSE_ACTIVATION_EMAIL_SUBJECT, LICENSE_REMINDER_EMAIL_SUBJECT)[is_reminder],
        'REMINDER': is_reminder,
    }
    email_activation_key_map = {}
    for pending_license in pending_licenses:
        email_activation_key_map.update({pending_license.user_email: str(pending_license.activation_key)})

    _send_email_with_activation(
        custom_template_text,
        email_activation_key_map,
        subscription_plan.expiration_date,
        context,
        enterprise_slug
    )


def _send_email_with_activation(
    custom_template_text,
    email_activation_key_map,
    subscription_expiration_date,
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
        subscription_expiration_date (datetime): When the subscription expires
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
            'LEARNER_PORTAL_LINK': _learner_portal_link(enterprise_slug),
            'LICENSE_ACTIVATION_LINK': _generate_license_activation_link(
                enterprise_slug,
                email_activation_key_map.get(email_address)
            ),
            'USER_EMAIL': email_address,
            'SOCIAL_MEDIA_FOOTER_URLS': settings.SOCIAL_MEDIA_FOOTER_URLS,
            'MOBILE_STORE_URLS': settings.MOBILE_STORE_URLS,
        })
        emails.append(_message_from_context_and_template(
            context,
            custom_template_text,
            subscription_expiration_date,
        ))

    # Use a single connection to send all messages
    with mail.get_connection() as connection:
        connection.send_messages(emails)


def _generate_license_activation_link(enterprise_slug, activation_key):
    """
    Returns the activation link displayed in the activation email sent to a learner
    """
    return '/'.join((
        _learner_portal_link(enterprise_slug),
        'licenses',
        activation_key,
        'activate'
    ))


def _learner_portal_link(enterprise_slug):
    """
    Returns the link to the learner portal, given an enterprise slug.
    Does not contain a trailing slash.
    """
    return settings.ENTERPRISE_LEARNER_PORTAL_BASE_URL + '/' + enterprise_slug


def _get_rendered_template_content(template_name, extension, context):
    """
    Returns the rendered content for a given template name and file extension
    """
    message_template = 'email/' + template_name + extension
    return get_template(message_template).render(context)


def _message_from_context_and_template(context, custom_template_text, subscription_expiration_date):
    """
    Creates a message about the subscription_plan in the template specified by the context, with custom_template_text.

    Args:
        context (dict): Dictionary of context variables for template rendering.
        custom_template_text (dict): Dictionary containing `greeting` and `closing` keys to be used for customizing
            the email template.
        subscription_expiration_date (datetime): When the subscription expires

    Returns:
        EmailMultiAlternative: an individual message constructed from the information provided, not yet sent
    """
    # Update context to be used for Django template rendering
    context.update({
        'EXPIRATION_DATE': subscription_expiration_date,
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
