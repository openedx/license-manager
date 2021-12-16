import logging
from collections import defaultdict

from django.core.management.base import BaseCommand

from license_manager.apps.api_client.enterprise_catalog import (
    EnterpriseCatalogApiClient,
)
from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.models import SubscriptionPlan
from license_manager.apps.subscriptions.utils import chunks


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Verify that the correct number of distinct Catalog Queries used by Enterprise Catalogs for '
        'all SubscriptionPlans in the license-manager service exist in the enterprise-catalog service.'
    )

    def handle(self, *args, **options):
        # Filter any subscriptions that have expired or are FIUO
        customer_subs = SubscriptionPlan.objects.filter(
            expiration_processed=False,
            for_internal_use_only=False,
        ).select_related('product')
        distinct_catalog_uuids = [
            str(uuid) for uuid in customer_subs.values_list('enterprise_catalog_uuid', flat=True).distinct()
        ]

        # Batch the catalog UUIDs and aggregate API response data in a set
        catalog_uuids_by_catalog_query_id = defaultdict(list)
        for catalog_uuid_batch in chunks(distinct_catalog_uuids, constants.VALIDATE_NUM_CATALOG_QUERIES_BATCH_SIZE):
            response = EnterpriseCatalogApiClient().get_distinct_catalog_queries(catalog_uuid_batch)
            query_ids = response['catalog_uuids_by_catalog_query_id']
            for key in query_ids.keys():
                catalog_uuids_by_catalog_query_id[key] += query_ids[key]
        distinct_catalog_query_ids = catalog_uuids_by_catalog_query_id.keys()

        # Calculate the number of customer types using the distinct number of Netsuite
        # product IDs found among customer subscriptions. If the number of distinct catalog
        # query IDs doesn't match the number of customer types, log an error.
        num_customer_types = customer_subs.values_list('product__netsuite_id', flat=True).distinct().count()
        summary = '{} distinct Subscription Catalog Queries found, {} expected.'.format(
            len(distinct_catalog_query_ids),
            num_customer_types,
        )

        if len(distinct_catalog_query_ids) != num_customer_types:
            error_msg = 'ERROR: {}\nCatalogQuery to CustomerCatalog(s) mapping: {}'.format(
                summary,
                dict(catalog_uuids_by_catalog_query_id),
            )
            logger.error(error_msg)
            raise InvalidCatalogQueryMappingError
        else:
            logger.info('SUCCESS: {}'.format(summary))


class InvalidCatalogQueryMappingError(Exception):
    """
    Exception to indicate failure of the validate_num_catalog_queries management command.
    """
