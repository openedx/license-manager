import uuid
from unittest import mock

import ddt
from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from license_manager.apps.subscriptions.tests.factories import (
    SubscriptionPlanFactory,
)


@ddt.ddt
class ValidateQueryMappingTaskTests(TestCase):
    """
    Tests for the validate_query_mapping_task
    """
    command_name = 'validate_num_catalog_queries'

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.sub_plan = SubscriptionPlanFactory()

    @ddt.unpack
    @ddt.data(
        {
            'num_queries_found': settings.NUM_SUBSCRIPTION_CUSTOMER_TYPES - 1,
            'is_valid': False,
        },
        {
            'num_queries_found': settings.NUM_SUBSCRIPTION_CUSTOMER_TYPES,
            'is_valid': True,
        },
    )
    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.validate_num_catalog_queries.EnterpriseCatalogApiClient'
    )
    def test_email_sent_for_invalid_num_queries(self, mock_api_client, num_queries_found, is_valid):
        """
        Tests that an email is sent to ECS in the case that an invalid number of distinct
        CatalogQuery IDs are found to be used for all subscription customers.

        Tests that no email is sent if the valid number of distinct CatalogQuery IDs are found.
        """
        log_level = 'INFO' if is_valid else 'ERROR'
        with self.assertLogs(level=log_level) as log:
            catalog_query_ids = []
            for _ in range(num_queries_found):
                catalog_query_ids.append(str(uuid.uuid4()))
            mock_response = {
                'count': num_queries_found,
                'catalog_query_ids': catalog_query_ids,
            }
            mock_api_client.return_value.get_distinct_catalog_queries.return_value = mock_response
            call_command(self.command_name)
            if is_valid:
                # Assert SUCCESS logged
                assert 'SUCCESS' in log.output[0]
            else:
                # Assert ERROR logged
                assert 'ERROR' in log.output[0]
