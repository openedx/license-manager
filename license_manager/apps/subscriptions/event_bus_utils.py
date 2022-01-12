"""
Util classes and methods for producing license events to the event bus. Likely
temporary.
"""

import logging

from confluent_kafka import KafkaError, KafkaException, SerializingProducer
from confluent_kafka.admin import AdminClient, NewTopic
from confluent_kafka.error import ValueSerializationError
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.serialization import StringSerializer
from django.conf import settings
from openedx_events.enterprise.data import TrackingEvent
from openedx_events.avro_attrs_bridge import KafkaWrapper


logger = logging.getLogger(__name__)


# Eventually the following should be moved into a plugin, app, library, or something more reusable

class TrackingEventSerializer:
    """ Wrapper class used to ensure a single instance of the tracking event serializer.
     This avoids errors on startup."""
    TRACKING_EVENT_SERIALIZER = None

    @classmethod
    def get_serializer(cls):
        """
        Get or create a single instance of the TrackingEvent serializer to be used throughout the life of the app
        :return: AvroSerializer
        """
        if cls.TRACKING_EVENT_SERIALIZER is None:
            KAFKA_SCHEMA_REGISTRY_CONFIG = {
                'url': getattr(settings, 'SCHEMA_REGISTRY_URL', ''),
                'basic.auth.user.info': f"{getattr(settings,'SCHEMA_REGISTRY_API_KEY','')}"
                f":{getattr(settings,'SCHEMA_REGISTRY_API_SECRET','')}",
            }

            # create bridge for TrackingEvent
            bridge = KafkaWrapper(TrackingEvent)
            schema_registry_client = SchemaRegistryClient(KAFKA_SCHEMA_REGISTRY_CONFIG)
            cls.TRACKING_EVENT_SERIALIZER = AvroSerializer(schema_str=bridge.schema_str(),
                                                           schema_registry_client=schema_registry_client,
                                                           to_dict=bridge.to_dict)
            return cls.TRACKING_EVENT_SERIALIZER
        return cls.TRACKING_EVENT_SERIALIZER


class ProducerFactory:
    """ Factory class to create event producers.
    The factory pattern is used to ensure only one producer per event type, which is the confluent recommendation"""
    _type_to_producer = {}

    @classmethod
    def get_or_create_event_producer(cls, event_type, event_key_serializer, event_value_serializer):
        """
        Factory method to return the correct producer for the event type, or
        create a new producer if none exists
        :param event_type: name of event (same as segment events)
        :param event_key_serializer:  AvroSerializer instance for serializing event key
        :param event_value_serializer: AvroSerializer instance for serializing event value
        :return: SerializingProducer
        """
        existing_producer = cls._type_to_producer.get(event_type)
        if existing_producer is not None:
            return existing_producer
        producer_settings = {
            'bootstrap.servers': getattr(settings, 'KAFKA_BOOTSTRAP_SERVER', ''),
            'sasl.mechanism': 'PLAIN',
            'security.protocol': 'SASL_SSL',
            'sasl.username': getattr(settings, 'KAFKA_API_KEY', ''),
            'sasl.password': getattr(settings, 'KAFKA_API_SECRET', ''),
            'key.serializer': event_key_serializer,
            'value.serializer': event_value_serializer,
        }

        new_producer = SerializingProducer(producer_settings)
        cls._type_to_producer[event_type] = new_producer
        return new_producer


def create_topic_if_not_exists(topic_name):
    """
    Create a topic in the event bus
    :param topic_name: topic to create
    """
    KAFKA_ACCESS_CONF_BASE = {'bootstrap.servers': getattr(settings, 'KAFKA_BOOTSTRAP_SERVER', ''),
                              'sasl.mechanism': 'PLAIN',
                              'security.protocol': 'SASL_SSL',
                              'sasl.username': getattr(settings, 'KAFKA_API_KEY', ''),
                              'sasl.password': getattr(settings, 'KAFKA_API_SECRET', '')
                              }

    a = AdminClient(KAFKA_ACCESS_CONF_BASE)

    license_event_topic = NewTopic(topic_name,
                                   num_partitions=settings.KAFKA_PARTITIONS_PER_TOPIC,
                                   replication_factor=settings.KAFKA_REPLICATION_FACTOR_PER_TOPIC)
    # Call create_topics to asynchronously create topic.
    # Wait for each operation to finish.
    topic_futures = a.create_topics([license_event_topic])

    # TODO: (ARCHBOM-2004) programmatically update permissions so the calling app can write to the created topic

    # ideally we could check beforehand if the topic already exists instead of using exceptions as control flow
    # but that is not in the AdminClient API
    for topic, f in topic_futures.items():
        try:
            f.result()  # The result itself is None
            logger.info(f"Topic {topic} created")
        except KafkaException as ke:
            if ke.args[0].code() == KafkaError.TOPIC_ALREADY_EXISTS:
                logger.info(f"Topic {topic} already exists")
            else:
                raise


def send_event_to_message_bus(event_name, event_properties):
    """
    Create a TrackingEvent from event_properties and send it to the settings.LICENSE_TOPIC_NAME queue on
    the event bus
    :param event_name: same as segment event name
    :param event_properties: same as segment event properties
    """
    try:
        license_event_producer = ProducerFactory.get_or_create_event_producer(
            settings.LICENSE_TOPIC_NAME,
            StringSerializer('utf-8'),
            TrackingEventSerializer.get_serializer()
        )
        license_event_producer.produce(settings.LICENSE_TOPIC_NAME, key=str(event_name),
                                       value=TrackingEvent(**event_properties), on_delivery=verify_event)
        license_event_producer.poll()
    except ValueSerializationError as vse:
        logger.exception(vse)


def verify_event(err, evt):
    """ Simple callback method for debugging event production
    :param err: Error if event production failed
    :param evt: Event that was delivered
    """
    if err is not None:
        logger.warning(f"Event delivery failed: {err}")
    else:
        # Don't log msg.value() because it may contain userids and/or emails
        logger.debug(f"Event delivered to {evt.topic()}: key(bytes) - {evt.key()}; "
                     f"partition - {evt.partition()}")
