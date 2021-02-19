import logging

from celery import shared_task
from celery_utils.logged_task import LoggedTask
from django.conf import settings

from license_manager.apps.api_client.enterprise_catalog import (
    EnterpriseCatalogApiClient,
)
from license_manager.apps.subscriptions.emails import (
    send_invalid_num_distinct_catalog_queries_email,
)
from license_manager.apps.subscriptions.models import SubscriptionPlan


logger = logging.getLogger(__name__)


@shared_task(base=LoggedTask)
def validate_query_mapping_task():
    """
    Task to validate the number of catalog queries used across
    Enterprise Catalogs assigned to customer SubscriptionPlans.
    """
    all_subs = SubscriptionPlan.objects.filter(for_internal_use_only=False)
    # Uses set comprehension to remove any duplicate EnterpriseCatalog UUIDs
    # See https://python-reference.readthedocs.io/en/latest/docs/comprehensions/set_comprehension.html
    all_catalog_uuids = list({str(sub.enterprise_catalog_uuid) for sub in all_subs})
    response = EnterpriseCatalogApiClient().get_distinct_catalog_queries(all_catalog_uuids)
    summary = '{} distinct catalog queries found: {}'.format(
        response['count'],
        response['catalog_query_ids'],
    )
    if response['count'] != settings.NUM_SUBSCRIPTION_CUSTOMER_TYPES:
        error_msg = 'ERROR: Unexpected number of Subscription Catalog Queries found. {}'.format(summary)
        logger.error(error_msg)
        send_invalid_num_distinct_catalog_queries_email(error_msg)
    else:
        logger.info('SUCCESS: {}'.format(summary))
