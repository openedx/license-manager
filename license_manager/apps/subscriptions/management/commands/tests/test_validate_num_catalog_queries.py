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
        SubscriptionPlanFactory.create_batch(num_subs)
        if is_valid:
            log_level = 'INFO'
            num_queries_found = num_subs
        else:
            log_level = 'ERROR'
            num_queries_found = num_subs - 1
        with self.assertLogs(level=log_level) as log:
            catalog_query_ids = [str(uuid.uuid4()) for _ in range(num_queries_found)]
            mock_api_client.return_value.get_distinct_catalog_queries.return_value = {
                'count': num_queries_found,
                'catalog_query_ids': catalog_query_ids,
            }
            call_command(self.command_name)
            if is_valid:
                assert 'SUCCESS' in log.output[0]
            else:
                assert 'ERROR' in log.output[0]
