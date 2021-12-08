import logging

import analytics
from confluent_kafka import KafkaError, KafkaException
from confluent_kafka.admin import AdminClient, NewTopic
from django.apps import AppConfig
from django.conf import settings


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
            KAFKA_ACCESS_CONF_BASE = {'bootstrap.servers': getattr(settings, 'KAFKA_BOOTSTRAP_SERVER', ''),
                                      'sasl.mechanism': 'PLAIN',
                                      'security.protocol': 'SASL_SSL',
                                      'sasl.username': getattr(settings, 'KAFKA_API_KEY', ''),
                                      'sasl.password': getattr(settings, 'KAFKA_API_SECRET', '')
                                      }

            a = AdminClient(KAFKA_ACCESS_CONF_BASE)

            license_event_topic = NewTopic(settings.LICENSE_TOPIC_NAME,
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
