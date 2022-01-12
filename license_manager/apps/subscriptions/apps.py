import logging

import analytics
from django.apps import AppConfig
from django.conf import settings

from .event_bus_utils import create_topic_if_not_exists


logger = logging.getLogger(__name__)


class SubscriptionsConfig(AppConfig):
    name = 'license_manager.apps.subscriptions'
    default = False

    def ready(self):
        if getattr(settings, 'SEGMENT_KEY', None):
            logger.debug("Found segment key, setting up")
            analytics.write_key = settings.SEGMENT_KEY

        # TODO: (ARCHBOM-2004) remove pragma and add tests when finalizing
        if getattr(settings, 'KAFKA_ENABLED', False):  # pragma: no cover
            try:
                create_topic_if_not_exists(settings.LICENSE_TOPIC_NAME)
            except Exception as e:
                logger.error(f"Error creating topic {settings.LICENSE_TOPIC_NAME}: {e}")
