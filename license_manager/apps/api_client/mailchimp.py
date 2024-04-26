import logging

import mailchimp_transactional as MailchimpTransactional
from django.conf import settings
from mailchimp_transactional.api_client import \
    ApiClientError as MailChimpClientError


logger = logging.getLogger(__name__)


class MailchimpTransactionalApiClient(MailchimpTransactional.Client):
    def __init__(self, logger_prefix):
        self.logger_prefix = logger_prefix
        required_settings = ['MAILCHIMP_API_KEY', 'MAILCHIMP_FROM_EMAIL', 'MAILCHIMP_FROM_NAME']

        for setting in required_settings:
            if not getattr(settings, setting, None):
                msg = f'Missing {setting} in settings required for Mailchimp API Client.'
                logger.error(msg)
                raise ValueError(msg)

        super().__init__(
            api_key=settings.MAILCHIMP_API_KEY,
        )

    def send_message(
        self,
        template_slug,
        merge_vars,
        user_emails,
        subject,
        recipient_metadata=None,
        global_merge_vars=None
    ):
        """
        Send message via mailchimp transactional api.
        Docs: https://mailchimp.com/developer/transactional/api/messages/send-using-message-template/

        Args:
            template_slug (str): Template name in Mailchimp
            merge_vars (list[dict[str, str]]): per-recipient merge variables.
            user_emails (list[str]): List of user emails
            subject (str): Email subject
            recipient_metadata (List[dict[str, dict]]): List of per-user metadata
            global_merge_vars (list[dict[str, any]]): List of global merge vars

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
                'global_merge_vars': global_merge_vars or [],
            },
        )
        return response

    def send_single_email(self, context, user_email, subject, template_slug, err_message):
        """
        Helper function to send a single email via mailchimp.
        Args:
            context (dict[str, any]): template context
            user_email (str): user email
            subject (str): email subject
            template_slug (str): template name from mailchimp
            err_message (str): message to log on failure
        """
        try:
            self.send_message(
                template_slug,
                [{'rcpt': user_email, 'vars': context}],
                [{'email': user_email}],
                subject=subject,
                recipient_metadata=[
                    {
                        'rcpt': user_email,
                        'values': {'email': user_email},
                    }
                ],
            )
            logger.info(f'{self.logger_prefix} Sent email for mailchimp template {template_slug} to {user_email}')
        except MailChimpClientError as exc:
            logger.exception(err_message)
            raise exc

    def send_emails(
        self,
        template_name,
        merge_vars,
        to_users,
        subject,
        success_msg,
        err_msg,
        recipient_metadata=None,
        global_merge_vars=None,
    ):
        """Helper to send emails to multiple users via mailchimp
        Docs: https://mailchimp.com/developer/transactional/api/messages/send-using-message-template/

        Args:
            template_name (str): Mailchimp template name
            merge_vars (list[dict[str, str]]): per-recipient merge variables.
            to_users (list[dict[str, str]]): List of user email objects
            subject (str): email subject
            success_msg (str): message to log on success
            err_msg (str): message to log on failure
            recipient_metadata (list[dict[str, any]]): per-recipient additional metadata
            global_merge_vars (list[dict[str, str]]): global merge variables.
        """
        try:
            self.send_message(
                template_name,
                merge_vars,
                to_users,
                subject=subject,
                recipient_metadata=recipient_metadata or [],
                global_merge_vars=global_merge_vars or [],
            )
            logger.info(success_msg)
        except MailChimpClientError as ex:
            logger.exception(err_msg)
            raise ex
