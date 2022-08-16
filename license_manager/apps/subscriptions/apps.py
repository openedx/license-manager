"""
Defines the Django app config for subscriptions.
"""
import logging

import analytics
from django.apps import AppConfig
from django.conf import settings


logger = logging.getLogger(__name__)


class SubscriptionsConfig(AppConfig):
    """
    The app config for subscriptions.
    """
    name = 'license_manager.apps.subscriptions'
    default = False

    def ready(self):
        if getattr(settings, 'SEGMENT_KEY', None):
            logger.debug("Found segment key, setting up")
            analytics.write_key = settings.SEGMENT_KEY
