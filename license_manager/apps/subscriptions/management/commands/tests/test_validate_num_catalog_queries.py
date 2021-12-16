import uuid
from unittest import mock

import ddt
from django.core.management import call_command
from django.test import TestCase

from license_manager.apps.subscriptions.management.commands.validate_num_catalog_queries import (
    InvalidCatalogQueryMappingError,
)
from license_manager.apps.subscriptions.tests.factories import (
    ProductFactory,
    SubscriptionPlanFactory,
)


@ddt.ddt
class ValidateQueryMappingTaskTests(TestCase):
    """
    Tests for the validate_query_mapping_task
    """
    command_name = 'validate_num_catalog_queries'

    @ddt.data(
        False,
        True,
    )
    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.validate_num_catalog_queries.EnterpriseCatalogApiClient'
    )
    def test_email_sent_for_invalid_num_queries(self, is_valid, mock_api_client):
        """
        Tests that an email is sent to ECS in the case that an invalid number of distinct
        CatalogQuery IDs are found to be used for all subscription customers.

        Tests that no email is sent if the valid number of distinct CatalogQuery IDs are found.
        """
        # Arbitrary number of subscriptions ("correct" number)
        num_subs = 3

        for i in range(num_subs):
            SubscriptionPlanFactory(product=ProductFactory(netsuite_id=i))

        if is_valid:
            log_level = 'INFO'
            num_queries_found = num_subs
        else:
            log_level = 'ERROR'
            num_queries_found = num_subs - 1
        with self.assertLogs(level=log_level) as log:
            catalog_query_ids = {}
            for _ in range(num_queries_found):
                catalog_query_ids[str(uuid.uuid4())] = [str(uuid.uuid4())]
            mock_api_client.return_value.get_distinct_catalog_queries.return_value = {
                'num_distinct_query_ids': num_queries_found,
                'catalog_uuids_by_catalog_query_id': catalog_query_ids,
            }
            if is_valid:
                call_command(self.command_name)
                assert 'SUCCESS' in log.output[0]
            else:
                with self.assertRaises(InvalidCatalogQueryMappingError):
                    call_command(self.command_name)
                assert 'ERROR' in log.output[0]
