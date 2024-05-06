import logging
from collections import defaultdict

from django.conf import settings
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

    def add_arguments(self, parser):
        parser.add_argument(
            '--catalog-id-reporting-threshold',
            action='store',
            dest='catalog_id_reporting_threshold',
            help=(
                'The number of catalog uuids associated with an unaccounted-for catalog query, '
                'below which number such catalog uuids will be printed in an error message. '
                'Defaults to 50.'
            ),
            type=int,
            default=50,
        )

    def handle(self, *args, **options):
        # Filter any subscriptions that have expired or are for internal use only.
        customer_subs = SubscriptionPlan.objects.filter(
            expiration_processed=False,
            for_internal_use_only=False,
            product__plan_type__internal_use_only=False,
        ).select_related(
            'product',
            'product__plan_type',
        )
        distinct_catalog_uuids = [
            str(uuid) for uuid in customer_subs.values_list('enterprise_catalog_uuid', flat=True).distinct()
        ]

        # Batch the catalog UUIDs and aggregate API response data into a set
        # keyed by catalog query id and valued by lists of catalogs that
        # use that key as their catalog query.
        catalog_uuids_by_catalog_query_id = defaultdict(list)
        for catalog_uuid_batch in chunks(distinct_catalog_uuids, constants.VALIDATE_NUM_CATALOG_QUERIES_BATCH_SIZE):
            response = EnterpriseCatalogApiClient().get_distinct_catalog_queries(catalog_uuid_batch)
            query_ids = response['catalog_uuids_by_catalog_query_id']
            for catalog_query_id, catalog_uuid in query_ids.items():
                if catalog_uuid not in settings.CUSTOM_CATALOG_PRODUCTS_ALLOW_LIST:
                    catalog_uuids_by_catalog_query_id[catalog_query_id] += catalog_uuid

        distinct_catalog_query_ids = catalog_uuids_by_catalog_query_id.keys()
        # Calculate the number of customer types using the distinct number of
        # non-internal-use-only Products-Plan Types found among customer subscriptions.
        # If the number of distinct catalog
        # query IDs doesn't match the number of customer types, log an error.
        num_distinct_external_use_plan_types = customer_subs.values_list(
            'product__plan_type__label',
            flat=True,
        ).distinct().count()

        summary = (
            f'{len(distinct_catalog_query_ids)} distinct Subscription Catalog Queries found, '
            f'{num_distinct_external_use_plan_types} expected based on the number of distinct subscription products.'
        )

        if len(distinct_catalog_query_ids) > num_distinct_external_use_plan_types:
            # We typically only see a handful of catalogs that relate
            # to some unaccounted-for catalog query, so we'll just log those,
            # instead of logging the potentially thousands of catalog uuids
            # that relate to accounted-for catalog queries.
            suspicious_catalog_query_ids = {
                catalog_query_id: catalog_list
                for catalog_query_id, catalog_list
                in catalog_uuids_by_catalog_query_id.items()
                if len(catalog_list) < options['catalog_id_reporting_threshold']
            }
            error_msg = (
                f'ERROR: {summary}\n'
                f'Suspicious CatalogQueries and their related catalog identifiers: {suspicious_catalog_query_ids}'
            )
            logger.error(error_msg)
            raise InvalidCatalogQueryMappingError
        else:
            logger.info('SUCCESS: {}'.format(summary))


class InvalidCatalogQueryMappingError(Exception):
    """
    Exception to indicate failure of the validate_num_catalog_queries management command.
    """
