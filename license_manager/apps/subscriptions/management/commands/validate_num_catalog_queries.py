import logging

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

    def handle(self, *args, **options):
        all_catalog_uuids = [str(uuid) for uuid in SubscriptionPlan.objects.filter(
            expiration_processed=False,
            for_internal_use_only=False,
        ).distinct().values_list('enterprise_catalog_uuid', flat=True)]

        result = set()
        for catalog_uuid_batch in chunks(all_catalog_uuids, constants.VALIDATE_NUM_CATALOG_QUERIES_BATCH_SIZE):
            response = EnterpriseCatalogApiClient().get_distinct_catalog_queries(catalog_uuid_batch)
            # import pdb; pdb.set_trace()
            for id in response['catalog_query_ids']:
                result.add(id)
        result = list(result)

        summary = '{} distinct catalog queries found: {}'.format(
            len(result),
            result,
        )
        if len(result) != settings.NUM_SUBSCRIPTION_CUSTOMER_TYPES:
            error_msg = 'ERROR: Unexpected number of Subscription Catalog Queries found. {}'.format(summary)
            logger.error(error_msg)
        else:
            logger.info('SUCCESS: {}'.format(summary))
