import logging

import mailchimp_transactional as MailchimpTransactional
from django.conf import settings


logger = logging.getLogger(__name__)


class MailchimpTransactionalApiClient(MailchimpTransactional.Client):
    def __init__(self):
        required_settings = ['MAILCHIMP_API_KEY', 'MAILCHIMP_FROM_EMAIL', 'MAILCHIMP_FROM_NAME']

        for setting in required_settings:
            if not getattr(settings, setting, None):
                msg = f'Missing {setting} in settings required for Mailchimp API Client.'
                logger.error(msg)
                raise ValueError(msg)

        super().__init__(
            api_key=settings.MAILCHIMP_API_KEY,
        )

    @staticmethod
    def get_merge_vars(content):
        return [{'name': key, 'content': value} for key, value in content.items()]

    @staticmethod
    def _get_recipients_dict(recipients):
        return [{'email': recipient for recipient in recipients}]

    def send_message(self, template_slug, merge_vars, user_emails, subject, recipient_metadata=None):
        """Send message via mailchimp transactional api.
        Docs: https://mailchimp.com/developer/transactional/api/messages/send-using-message-template/

        Args:
            template_slug (str): Template name in Mailchimp
            merge_vars (list[dict[str, str]]): per-recipient merge variables.
            user_emails (list[str]): List of user emails
            subject (str): Email subject
            recipient_metadata (List[dict[str, dict]]): List of per-user metadata

        Returns:
            response object from mailchimp
        """
        response = self.messages.send_template(
            template_name=template_slug,
            message={
                'from_email': settings.MAILCHIMP_FROM_EMAIL,
                'from name': settings.MAILCHIMP_FROM_NAME,
                'subject': subject,
                'preserve_recipients': getattr(settings, 'MAILCHIMP_PRESERVE_RECIPIENTS', False),
                'to': user_emails,
                'merge_vars': merge_vars,
                'merge_language': getattr(settings, 'MAILCHIMP_MERGE_LANGUAGE', 'handlebars'),
                'recipient_metadata': recipient_metadata or [],
            },
        )
        return response
