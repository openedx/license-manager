"""
Util classes and methods for producing license events to the event bus. Likely
temporary.
"""

import logging

from confluent_kafka import KafkaError, KafkaException, SerializingProducer
from confluent_kafka.admin import AdminClient, NewTopic
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from django.conf import settings
from openedx_events.event_bus.avro.serializer import AvroSignalSerializer
from openedx_events.enterprise.signals import SUBSCRIPTION_LICENSE_MODIFIED


logger = logging.getLogger(__name__)

# TODO (EventBus):
#   1. (ARCHBOM-2004) remove this file from the omit list in coverage.py and add tests when finalized
#   2. Move ProducerFactory, serializer creation, topic creation, to a reusable plugin accessible by other apps


class SubscriptionLicenseEventSerializer:
    """ Wrapper class used to ensure a single instance of the event serializer.

    This avoids errors on startup.
    """
    SERIALIZER = None

    @classmethod
    def get_serializer(cls):
        """
        Get or create a single instance of the SUBSCRIPTION_LICENSE_MODIFIED signal serializer

        :return: AvroSerializer
        """
        if cls.SERIALIZER is None:
            KAFKA_SCHEMA_REGISTRY_CONFIG = {
                'url': getattr(settings, 'SCHEMA_REGISTRY_URL', ''),
                'basic.auth.user.info': f"{getattr(settings,'SCHEMA_REGISTRY_API_KEY','')}"
                f":{getattr(settings,'SCHEMA_REGISTRY_API_SECRET','')}",
            }
            signal_serializer = AvroSignalSerializer(SUBSCRIPTION_LICENSE_MODIFIED)

            def inner_to_dict(event_data, ctx=None):  # pylint: disable=unused-argument
                return signal_serializer.to_dict(event_data)
            schema_registry_client = SchemaRegistryClient(KAFKA_SCHEMA_REGISTRY_CONFIG)
            cls.SERIALIZER = AvroSerializer(schema_str=signal_serializer.schema_string(),
                                            schema_registry_client=schema_registry_client,
                                            to_dict=inner_to_dict)
            return cls.SERIALIZER
        return cls.SERIALIZER


class ProducerFactory:
    """ Factory class to create event producers.

    The factory pattern is used to ensure only one producer per event type, which is the confluent recommendation"""
    _type_to_producer = {}

    @classmethod
    def get_or_create_event_producer(cls, event_type, event_key_serializer, event_value_serializer):
        """
        Factory method to create (if needed) and return the correct producer for the event type

        :param event_type: name of event (same as segment events)
        :param event_key_serializer:  AvroSerializer instance for serializing event key
        :param event_value_serializer: AvroSerializer instance for serializing event value
        :return: SerializingProducer
        """
        existing_producer = cls._type_to_producer.get(event_type)
        if existing_producer is not None:
            return existing_producer

        producer_settings = {
            'bootstrap.servers': getattr(settings, 'KAFKA_BOOTSTRAP_SERVER', None),
            'key.serializer': event_key_serializer,
            'value.serializer': event_value_serializer,
        }

        if getattr(settings, 'KAFKA_API_KEY', None) and getattr(settings, 'KAFKA_API_SECRET', None):
            producer_settings.update({
                'sasl.mechanism': 'PLAIN',
                'security.protocol': 'SASL_SSL',
                'sasl.username': getattr(settings, 'KAFKA_API_KEY', ''),
                'sasl.password': getattr(settings, 'KAFKA_API_SECRET', ''),
            })

        new_producer = SerializingProducer(producer_settings)
        cls._type_to_producer[event_type] = new_producer
        return new_producer


def create_topic_if_not_exists(topic_name):
    """
    Create a topic in the event bus

    :param topic_name: topic to create
    """
    KAFKA_ACCESS_CONF_BASE = {'bootstrap.servers': getattr(settings, 'KAFKA_BOOTSTRAP_SERVER', None)}

    if getattr(settings, 'KAFKA_API_KEY', None) and getattr(settings, 'KAFKA_API_SECRET', None):
        KAFKA_ACCESS_CONF_BASE.update({
            'sasl.mechanism': 'PLAIN',
            'security.protocol': 'SASL_SSL',
            'sasl.username': getattr(settings, 'KAFKA_API_KEY', ''),
            'sasl.password': getattr(settings, 'KAFKA_API_SECRET', '')
        })

    admin_client = AdminClient(KAFKA_ACCESS_CONF_BASE)

    license_event_topic = NewTopic(topic_name,
                                   num_partitions=settings.KAFKA_PARTITIONS_PER_TOPIC,
                                   replication_factor=settings.KAFKA_REPLICATION_FACTOR_PER_TOPIC)
    # Call create_topics to asynchronously create topic.
    # Wait for each operation to finish.
    topic_futures = admin_client.create_topics([license_event_topic])

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
