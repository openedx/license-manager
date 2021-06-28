from django.conf import settings
from django.core import mail
from django.db.models.query_utils import Q
from django.template.loader import get_template

from license_manager.apps.api_client.enterprise import EnterpriseApiClient
from license_manager.apps.subscriptions.constants import (
    LICENSE_BULK_OPERATION_BATCH_SIZE,
    LICENSE_ACTIVATION_EMAIL_TEMPLATE,
    LICENSE_REMINDER_EMAIL_TEMPLATE,
    ONBOARDING_EMAIL_TEMPLATE,
    REVOCATION_CAP_NOTIFICATION_EMAIL_TEMPLATE,
)
from license_manager.apps.subscriptions.models import PlanEmailTemplates, SubscriptionPlan
from license_manager.apps.subscriptions.utils import (
    chunks,
    get_enterprise_reply_to_email,
    get_enterprise_sender_alias,
    get_learner_portal_url,
    get_license_activation_link,
)


def send_revocation_cap_notification_email(subscription_plan, enterprise_name, enterprise_sender_alias, reply_to_email):
    """
    Sends an email to inform ECS that a subscription plan for a customer has reached its
    revocation cap, and that action may be necessary to help the customer add more licenses.
    """
    context = {
        'template_name': REVOCATION_CAP_NOTIFICATION_EMAIL_TEMPLATE,
        'SUBSCRIPTION_TITLE': subscription_plan.title,
        'ENTERPRISE_NAME': enterprise_name,
        'NUM_REVOCATIONS_APPLIED': subscription_plan.num_revocations_applied,
        'RECIPIENT_EMAIL': settings.CUSTOMER_SUCCESS_EMAIL_ADDRESS,
        'HIDE_EMAIL_FOOTER_MARKETING': True,
        'SUBSCRIPTION_PLAN_ID': subscription_plan.uuid,
    }
    email = _message_from_context_and_template(context, enterprise_sender_alias, reply_to_email)
    email.send()


def send_onboarding_email(enterprise_customer_uuid, user_email, subscription_plan_id):
    """
    Sends onboarding email to learner. Intended for use following license activation.

    Arguments:
        enterprise_customer_uuid (UUID): unique identifier of the EnterpriseCustomer
            that is linked to the SubscriptionPlan associated with the activated license
        user_email (str): email of the learner whose license has just been activated
        subscription_plan_id: unique identifier to uuid of specific plan type 
    """
    enterprise_customer = EnterpriseApiClient().get_enterprise_customer_data(enterprise_customer_uuid)
    enterprise_name = enterprise_customer.get('name')
    enterprise_slug = enterprise_customer.get('slug')
    enterprise_sender_alias = get_enterprise_sender_alias(enterprise_customer)
    reply_to_email = get_enterprise_reply_to_email(enterprise_customer)

    context = {
        'template_name': ONBOARDING_EMAIL_TEMPLATE,
        'SUBSCRIPTION_PLAN_ID': subscription_plan_id,
        'ENTERPRISE_NAME': enterprise_name,
        'ENTERPRISE_SLUG': enterprise_slug,
        'HELP_CENTER_URL': settings.SUPPORT_SITE_URL,
        'LEARNER_PORTAL_LINK': get_learner_portal_url(enterprise_slug),
        'MOBILE_STORE_URLS': settings.MOBILE_STORE_URLS,
        'RECIPIENT_EMAIL': user_email,
        'SOCIAL_MEDIA_FOOTER_URLS': settings.SOCIAL_MEDIA_FOOTER_URLS,
    }
    email = _message_from_context_and_template(context, enterprise_sender_alias, reply_to_email)
    email.send()


def send_activation_emails(
    custom_template_text,
    pending_licenses,
    enterprise_slug,
    enterprise_name,
    enterprise_sender_alias,
    reply_to_email,
    subscription_uuid,
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
        reply_to_email (str): Reply to email of the enterprise customer
        subscription_uuid (int): unique identifier of enterprise subscription
        is_reminder (bool): whether this is a reminder activation email being sent
    """
    context = {
        'template_name': LICENSE_REMINDER_EMAIL_TEMPLATE if is_reminder else LICENSE_ACTIVATION_EMAIL_TEMPLATE,
        'SUBSCRIPTION_PLAN_ID': subscription_uuid,
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
        reply_to_email,
    )


def _send_email_with_activation(email_activation_key_map, context, enterprise_slug, sender_alias, reply_to_email):
    """
    Helper that sends emails with the given template with an activation link to the the given list of emails.

    Args:
        email_activation_key_map (dict): Dictionary containing the emails of each recipient and the activation key that
            is unique to the email. Recipient emails are the keys in the dictionary.
        context (dict): Dictionary of context variables for template rendering. Context takes an optional `REMINDER`
            key. If `REMINDER` is provided, a reminder message is added to the email.
        enterprise_slug (str): The slug associated with an enterprise to uniquely identify it.
        sender_alias (str): The alias to use in from email for sending the email.
        reply_to_email (str): Reply to email of the enterprise customer
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
        emails.append(_message_from_context_and_template(context, sender_alias, reply_to_email))

    # Send out the emails in batches
    email_chunks = chunks(emails, LICENSE_BULK_OPERATION_BATCH_SIZE)
    for email_chunk in email_chunks:
        # Renew the email connection for each chunk of emails sent
        with mail.get_connection() as connection:
            connection.send_messages(email_chunk)


def _get_rendered_template_content(template_name, context):
    """
    Returns the rendered content from the Plan Email Templates model 
    """
    sub_plan_id = context['SUBSCRIPTION_PLAN_ID'] 
    print(sub_plan_id)
    sub = SubscriptionPlan.objects.filter(uuid=sub_plan_id)
    print(sub)
    plan_type_id = sub.plan_type_id
    plan_email_template = PlanEmailTemplates.objects.filter(
        template_type__exact=template_name, plan_type__exact=plan_type_id)
    print(plan_email_template)
    plaintext_template = plan_email_template.render_plaintext_template
    html_template = plan_email_template.render_html_template

    return plaintext_template, html_template


def _message_from_context_and_template(context, sender_alias, reply_to_email):
    """
    Creates a message about the subscription_plan in the template specified by the context, with custom_template_text.

    Args:
        context (dict): Dictionary of context variables for template rendering.
        sender_alias (str): The alias to use in from email for sending the email.
        reply_to_email (str): Reply to email of the enterprise customer

    Returns:
        EmailMultiAlternative: an individual message constructed from the information provided, not yet sent
    """
    # Update context to be used for Django template rendering
    context.update({
        'UNSUBSCRIBE_LINK': settings.EMAIL_UNSUBSCRIBE_LINK,
    })

    # Render the message contents using Django templates
    template_name = context['template_name']
    txt_content, html_content = _get_rendered_template_content(template_name, context)

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
        'List-Unsubscribe': list_unsubscribe_header,
    }
    if reply_to_email:
        message_headers['Reply-To'] = reply_to_email

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
