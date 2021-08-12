import analytics

from django.apps import AppConfig
from django.conf import settings

import logging


logger = logging.getLogger(__name__)


class SubscriptionsConfig(AppConfig):
    name = 'license_manager.apps.subscriptions'
    default = False

    def ready(self):
        if settings.SEGMENT_KEY:
            logger.debug("Found segment key, setting up")
            analytics.write_key = settings.SEGMENT_KEY

