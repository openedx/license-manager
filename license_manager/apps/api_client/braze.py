import logging

from braze.client import BrazeClient
from braze.exceptions import BrazeClientError
from django.conf import settings

from license_manager.apps.subscriptions.constants import (
    ENTERPRISE_BRAZE_ALIAS_LABEL,
)


logger = logging.getLogger(__name__)


class BrazeApiClient(BrazeClient):
    def __init__(self, logger_prefix=''):
        self.logger_prefix = logger_prefix
        required_settings = ['BRAZE_API_KEY', 'BRAZE_API_URL', 'BRAZE_APP_ID']

        for setting in required_settings:
            if not getattr(settings, setting, None):
                msg = f'Missing {setting} in settings required for Braze API Client.'
                logger.error(msg)
                raise ValueError(msg)

        super().__init__(
            api_key=settings.BRAZE_API_KEY,
            api_url=settings.BRAZE_API_URL,
            app_id=settings.BRAZE_APP_ID
        )

    @staticmethod
    def aliased_recipient_object_from_email(user_email):
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

    def send_single_email(
        self, template_context, user_email, braze_campaign_id, err_message, create_alias=False
    ):
        recipient = self.aliased_recipient_object_from_email(user_email)
        try:
            if create_alias:
                self.create_braze_alias(
                    [user_email],
                    ENTERPRISE_BRAZE_ALIAS_LABEL,
                )
            self.send_campaign_message(
                braze_campaign_id,
                recipients=[recipient],
                trigger_properties=template_context,
            )
            logger.info(f'{self.logger_prefix} Sent email for braze campaign {braze_campaign_id} to {recipient}')
        except BrazeClientError as exc:
            logger.exception(err_message)
            raise exc

    def send_emails(
        self, campaign_id, recipients, success_msg, err_msg, trigger_properties=None, user_emails=None
    ):
        try:
            if user_emails:
                self.create_braze_alias(
                    user_emails,
                    ENTERPRISE_BRAZE_ALIAS_LABEL,
                )
            self.send_campaign_message(
                campaign_id, recipients=recipients, trigger_properties=trigger_properties
            )
            logger.info(success_msg)
        except BrazeClientError as ex:
            logger.exception(err_msg)
            raise ex
