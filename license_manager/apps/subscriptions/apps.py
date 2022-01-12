import logging

import analytics
from django.apps import AppConfig
from django.conf import settings

from .event_bus_utils import create_topic_if_not_exists
from edx_toggles.toggles import SettingToggle


logger = logging.getLogger(__name__)


# .. toggle_name: KAFKA_ENABLED
# .. toggle_implementation: SettingToggle
# .. toggle_default: False
# .. toggle_description: Enable producing events to the Kafka event bus
# .. toggle_creation_date: 2021-01-12
# .. toggle_tickets: https://openedx.atlassian.net/browse/ARCHBOM-1991
KAFKA_ENABLED = SettingToggle("KAFKA_ENABLED", default=False)


class SubscriptionsConfig(AppConfig):
    name = 'license_manager.apps.subscriptions'
    default = False

    def ready(self):
        if getattr(settings, 'SEGMENT_KEY', None):
            logger.debug("Found segment key, setting up")
            analytics.write_key = settings.SEGMENT_KEY

        # TODO: (ARCHBOM-2004) remove pragma and add tests when finalizing
        if KAFKA_ENABLED:  # pragma: no cover
            try:
                create_topic_if_not_exists(settings.LICENSE_TOPIC_NAME)
            except Exception as e:
                logger.error(f"Error creating topic: {e}")
