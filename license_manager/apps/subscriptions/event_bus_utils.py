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


logger = logging.getLogger(__name__)

# TODO EVENT BUS:
#  1. Move the TrackingEvent class to openedx_events and use the Attr<->Avro bridge as a serializer
#  2. Remove the TrackingEventSerializer once (1) is complete
#  3. (ARCHBOM-2004) remove this file from the omit list in coverage.py and add tests when finalized


class TrackingEvent:
    """
    License events to be put on event bus
    """

    def __init__(self, *args, **kwargs):
        self.license_uuid = kwargs['license_uuid']
        self.license_activation_key = kwargs['license_activation_key']
        self.previous_license_uuid = kwargs['previous_license_uuid']
        self.assigned_date = kwargs['assigned_date']
        self.activation_date = kwargs['activation_date']
        self.assigned_lms_user_id = kwargs['assigned_lms_user_id']
        self.expiration_processed = kwargs['expiration_processed']
        self.auto_applied = kwargs['auto_applied']
        self.enterprise_customer_uuid = kwargs.get('enterprise_customer_uuid', None)
        self.enterprise_customer_slug = kwargs.get('enterprise_customer_slug', None)
        self.enterprise_customer_name = kwargs.get('enterprise_customer_name', None)
        self.customer_agreement_uuid = kwargs.get('customer_agreement_uuid', None)

    # Some paths will set assigned_lms_user_id to '' if empty, so need to allow strings in the schema
    TRACKING_EVENT_AVRO_SCHEMA = """
        {
            "namespace": "license_manager.apps.subscriptions",
            "name": "TrackingEvent",
            "type": "record",
            "fields": [
                {"name": "license_uuid", "type": "string"},
                {"name": "license_activation_key", "type": "string"},
                {"name": "previous_license_uuid", "type": "string"},
                {"name": "assigned_date", "type": "string"},
                {"name": "assigned_lms_user_id", "type": ["int", "string", "null"], "default": "null"},
                {"name": "expiration_processed", "type": "boolean"},
                {"name": "auto_applied", "type": "boolean", "default": "false"},
                {"name": "enterprise_customer_uuid", "type": ["string", "null"], "default": "null"},
                {"name": "customer_agreement_uuid", "type": ["string", "null"], "default": "null"},
                {"name": "enterprise_customer_slug", "type": ["string", "null"], "default": "null"},
                {"name": "enterprise_customer_name", "type": ["string", "null"], "default": "null"}
            ]
        }

    """

    @staticmethod
    def from_dict(dict_instance, ctx):  # pylint: disable=unused-argument
        return TrackingEvent(**dict_instance)

    @staticmethod
    def to_dict(obj, ctx):  # pylint: disable=unused-argument
        return {
            'enterprise_customer_uuid': obj.enterprise_customer_uuid,
            'customer_agreement_uuid': obj.customer_agreement_uuid,
            'enterprise_customer_slug': obj.enterprise_customer_slug,
            'enterprise_customer_name': obj.enterprise_customer_name,
            "license_uuid": obj.license_uuid,
            "license_activation_key": obj.license_activation_key,
            "previous_license_uuid": obj.previous_license_uuid,
            "assigned_date": obj.assigned_date,
            "activation_date": obj.activation_date,
            "assigned_lms_user_id": obj.assigned_lms_user_id,
            "expiration_processed": obj.expiration_processed,
            "auto_applied": (obj.auto_applied or False),
        }


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
            schema_registry_client = SchemaRegistryClient(KAFKA_SCHEMA_REGISTRY_CONFIG)
            cls.TRACKING_EVENT_SERIALIZER = AvroSerializer(schema_str=TrackingEvent.TRACKING_EVENT_AVRO_SCHEMA,
                                                           schema_registry_client=schema_registry_client,
                                                           to_dict=TrackingEvent.to_dict)
            return cls.TRACKING_EVENT_SERIALIZER
        return cls.TRACKING_EVENT_SERIALIZER

# TODO EVENT BUS: Move ProducerFactory, topic creation, and simple event sending
#  to a reusable plugin accessible by other apps


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
        logger.info(f"Event delivered to {evt.topic()}: key(bytes) - {evt.key()}; "
                    f"partition - {evt.partition()}")
