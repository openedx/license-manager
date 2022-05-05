import logging

from confluent_kafka.error import ValueSerializationError
from confluent_kafka.serialization import StringSerializer
from django.conf import settings
from django.dispatch import receiver
from openedx_events.enterprise.signals import SUBSCRIPTION_LICENSE_MODIFIED

from license_manager.apps.subscriptions.event_bus_utils import (
    ProducerFactory,
    SubscriptionLicenseEventSerializer,
)


logger = logging.getLogger(__name__)


@receiver(SUBSCRIPTION_LICENSE_MODIFIED)
def send_event_to_message_bus(**kwargs):
    """
    Forward a SUBSCRIPTION_LICENSE_MODIFIED event to the settings.LICENSE_TOPIC_NAME queue on the event bus

    :param kwargs: event data sent by signal
    """
    try:
        license_event_producer = ProducerFactory.get_or_create_event_producer(
            settings.LICENSE_TOPIC_NAME,
            StringSerializer('utf-8'),
            SubscriptionLicenseEventSerializer.get_serializer()
        )
        license_event_data = {"license": kwargs['license']}

        license_event_producer.produce(settings.LICENSE_TOPIC_NAME, key=kwargs['signal'].event_type,
                                       value=license_event_data, on_delivery=verify_event)
        license_event_producer.poll()
    except ValueSerializationError as vse:
        logger.exception(vse)


def verify_event(err, evt):
    """
    Simple callback method for debugging event production

    :param err: Error if event production failed
    :param evt: Event that was delivered
    """
    if err is not None:
        logger.warning(f"Event delivery failed: {err}")
    else:
        # Don't log msg.value() because it may contain userids and/or emails
        logger.info(f"Event delivered to {evt.topic()}: key(bytes) - {evt.key()}; "
                    f"partition - {evt.partition()}")
