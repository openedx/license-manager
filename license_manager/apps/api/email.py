import logging

from braze.exceptions import BrazeClientError
from license_manager.apps.api.tasks import LICENSE_DEBUG_PREFIX
from license_manager.apps.subscriptions.constants import ENTERPRISE_BRAZE_ALIAS_LABEL
from license_manager.apps.subscriptions.event_utils import get_license_tracking_properties
from license_manager.apps.subscriptions.utils import get_enterprise_sender_alias
from mailchimp_transactional.api_client import ApiClientError as MailChimpClientError
from django.conf import settings

from license_manager.apps.api_client.braze import BrazeApiClient
from license_manager.apps.api_client.mailchimp import MailchimpTransactionalApiClient


logger = logging.getLogger(__name__)


class EmailClient:
    def __init__(self) -> None:
        if settings.TRANSACTIONAL_MAIL_SERVICE == 'braze':
            self._braze_client = BrazeApiClient()
        elif settings.TRANSACTIONAL_MAIL_SERVICE == 'mailchimp':
            self._mailchimp_client = MailchimpTransactionalApiClient()
        else:
            raise ValueError("Please set TRANSACTIONAL_MAIL_SERVICE setting to either 'braze' or 'mailchimp'.")

    @staticmethod
    def _aliased_recipient_object_from_email(user_email):
        """
        Returns a dictionary with a braze recipient object, including
        a braze alias object.
        """
        return {
            'attributes': {'email': user_email},
            'user_alias': {
                'alias_label': ENTERPRISE_BRAZE_ALIAS_LABEL,
                'alias_name': user_email,
            },
        }

    def _send_braze_assignement_email(self, template_context, user_email, enterprise_name):
        recipient = self._aliased_recipient_object_from_email(user_email)
        braze_campaign_id = settings.BRAZE_ASSIGNMENT_EMAIL_CAMPAIGN
        try:
            self._braze_client.send_campaign_message(
                braze_campaign_id,
                recipients=[recipient],
                trigger_properties=template_context,
            )
            logger.info(
                f'{LICENSE_DEBUG_PREFIX} Sent license assignment email '
                f'braze campaign {braze_campaign_id} to {recipient}'
            )
        except BrazeClientError as exc:
            message = (
                'License manager activation email sending received an ' f'exception for enterprise: {enterprise_name}.'
            )
            logger.exception(message)
            raise exc

    def _send_mailchimp_assignement_email(self, merge_vars, user_email, enterprise_name):
        template_slug = settings.MAILCHIMP_ASSIGNMENT_EMAIL_TEMPLATE_SLUG
        try:
            self._mailchimp_client.send_message(
                template_slug,
                merge_vars,
                [{'email': user_email}],
                subject=settings.MAILCHIMP_ASSIGNMENT_EMAIL_SUBJECT,
                recipient_metadata=[
                    {
                        'rcpt': user_email,
                        'values': {'email': user_email},
                    }
                ],
            )
            logger.info(
                f'{LICENSE_DEBUG_PREFIX} Sent license assignment email '
                f'mailchimp template {template_slug} to {user_email}'
            )
        except MailChimpClientError as exc:
            message = (
                'License manager activation email sending received an ' f'exception for enterprise: {enterprise_name}.'
            )
            logger.exception(message)
            raise exc

    def send_assignment_email(self, pending_licenses, enterprise_customer, custom_template_text):
        enterprise_slug = enterprise_customer.get('slug')
        enterprise_name = enterprise_customer.get('name')
        enterprise_sender_alias = get_enterprise_sender_alias(enterprise_customer)
        enterprise_contact_email = enterprise_customer.get('contact_email')
        pending_license_by_email = {}
        # We need to send these emails individually, because each email's text must be
        # generated for every single user/activation_key
        for pending_license in pending_licenses:
            user_email = pending_license.user_email
            pending_license_by_email[user_email] = pending_license
            license_activation_key = str(pending_license.activation_key)
            if settings.TRANSACTIONAL_MAIL_SERVICE == 'braze':
                template_context = {
                    'TEMPLATE_GREETING': custom_template_text['greeting'],
                    'TEMPLATE_CLOSING': custom_template_text['closing'],
                    'license_activation_key': license_activation_key,
                    'enterprise_customer_slug': enterprise_slug,
                    'enterprise_customer_name': enterprise_name,
                    'enterprise_sender_alias': enterprise_sender_alias,
                    'enterprise_contact_email': enterprise_contact_email,
                }
                self._send_braze_assignement_email(template_context, user_email, enterprise_name)
            elif settings.TRANSACTIONAL_MAIL_SERVICE == 'mailchimp':
                template_context = [
                    {'name': 'TEMPLATE_GREETING', 'content': custom_template_text['greeting']},
                    {'name': 'TEMPLATE_CLOSING', 'content': custom_template_text['closing']},
                    {'name': 'license_activation_key', 'content': license_activation_key},
                    {'name': 'enterprise_customer_slug', 'content': enterprise_slug},
                    {'name': 'enterprise_customer_name', 'content': enterprise_name},
                    {'name': 'enterprise_sender_alias', 'content': enterprise_sender_alias},
                    {'name': 'enterprise_contact_email', 'content': enterprise_contact_email},
                ]
                self._send_mailchimp_assignement_email(
                    [{'rcpt': user_email, 'vars': template_context}], user_email, enterprise_name
                )
        return pending_license_by_email

    def _send_braze_reminder_email(self, recipients, user_emails):
        try:
            self._braze_client.create_braze_alias(
                user_emails,
                ENTERPRISE_BRAZE_ALIAS_LABEL,
            )
            self._braze_client.send_campaign_message(
                settings.BRAZE_REMIND_EMAIL_CAMPAIGN,
                recipients=recipients,
            )
            logger.info(
                f'{LICENSE_DEBUG_PREFIX} Sent license reminder emails '
                f'braze campaign {settings.BRAZE_REMIND_EMAIL_CAMPAIGN} to {user_emails}'
            )
        except BrazeClientError as exc:
            message = (
                'Error hitting Braze API. '
                f'reminder email to {settings.BRAZE_REMIND_EMAIL_CAMPAIGN} for license failed.'
            )
            logger.exception(message)
            raise exc

    def _send_mailchimp_reminder_email(self, merge_vars, user_emails, recipient_metadata):
        template_slug = settings.MAILCHIMP_REMINDER_EMAIL_TEMPLATE_SLUG
        try:
            self._mailchimp_client.send_message(
                template_slug,
                merge_vars,
                user_emails,
                subject=settings.MAILCHIMP_ASSIGNMENT_EMAIL_SUBJECT,
                recipient_metadata=recipient_metadata,
            )
            logger.info(
                f'{LICENSE_DEBUG_PREFIX} Sent license assignment email '
                f'mailchimp template {template_slug} to {user_emails}'
            )
        except MailChimpClientError as exc:
            message = (
                'Error hitting Mailchimp API. '
                f'reminder email to {settings.MAILCHIMP_REMINDER_EMAIL_TEMPLATE_SLUG} for license failed.'
            )
            logger.exception(message)
            raise exc

    def send_reminder_email(self, pending_licenses, enterprise_customer, custom_template_text):
        enterprise_slug = enterprise_customer.get('slug')
        enterprise_name = enterprise_customer.get('name')
        enterprise_sender_alias = get_enterprise_sender_alias(enterprise_customer)
        enterprise_contact_email = enterprise_customer.get('contact_email')
        pending_license_by_email = {}
        user_emails = []
        messages = []
        recipient_metadata = []
        for pending_license in pending_licenses:
            user_email = pending_license.user_email
            pending_license_by_email[user_email] = pending_license
            license_activation_key = str(pending_license.activation_key)
            if settings.TRANSACTIONAL_MAIL_SERVICE == 'braze':
                user_emails.append(user_email)
                trigger_properties = {
                    'TEMPLATE_GREETING': custom_template_text['greeting'],
                    'TEMPLATE_CLOSING': custom_template_text['closing'],
                    'license_activation_key': license_activation_key,
                    'enterprise_customer_slug': enterprise_slug,
                    'enterprise_customer_name': enterprise_name,
                    'enterprise_sender_alias': enterprise_sender_alias,
                    'enterprise_contact_email': enterprise_contact_email,
                }
                recipient = self._aliased_recipient_object_from_email(user_email)
                recipient['attributes'].update(get_license_tracking_properties(pending_license))
                recipient['trigger_properties'] = trigger_properties
                messages.append(recipient)
            elif settings.TRANSACTIONAL_MAIL_SERVICE == 'mailchimp':
                user_emails.append({'email': user_email})
                template_context = [
                    {'name': 'TEMPLATE_GREETING', 'content': custom_template_text['greeting']},
                    {'name': 'TEMPLATE_CLOSING', 'content': custom_template_text['closing']},
                    {'name': 'license_activation_key', 'content': license_activation_key},
                    {'name': 'enterprise_customer_slug', 'content': enterprise_slug},
                    {'name': 'enterprise_customer_name', 'content': enterprise_name},
                    {'name': 'enterprise_sender_alias', 'content': enterprise_sender_alias},
                    {'name': 'enterprise_contact_email', 'content': enterprise_contact_email},
                ]
                messages.append({'rcpt': user_email, 'vars': template_context})
                recipient_metadata.append(
                    {
                        'rcpt': user_email,
                        'values': {'email': user_email}.update(get_license_tracking_properties(pending_license)),
                    }
                )
        if settings.TRANSACTIONAL_MAIL_SERVICE == 'braze':
            self._send_braze_reminder_email(messages, user_emails)
        elif settings.TRANSACTIONAL_MAIL_SERVICE == 'mailchimp':
            self._send_mailchimp_reminder_email(messages, user_emails, recipient_metadata)
        return pending_license_by_email
