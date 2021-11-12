import logging

from braze.client import BrazeClient
from django.conf import settings


logger = logging.getLogger(__name__)


class BrazeApiClient(BrazeClient):
    def __init__(self):

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
