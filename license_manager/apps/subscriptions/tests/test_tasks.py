from unittest import mock

import ddt
from django.conf import settings
from django.test import TestCase, override_settings

from license_manager.apps.subscriptions.tasks import validate_query_mapping_task


@ddt.ddt
class ValidateQueryMappingTaskTests(TestCase):
    """
    Tests for the validate_query_mapping_task
    """
    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
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
    @mock.patch('license_manager.apps.subscriptions.tasks.send_invalid_num_distinct_catalog_queries_email')
    @mock.patch('license_manager.apps.subscriptions.tasks.EnterpriseCatalogApiClient')
    def test_email_sent_for_invalid_num_queries(self, mock_api_client, mock_email_fn, num_queries_found, is_valid):
        """
        Tests that an email is sent to ECS in the case that an invalid number of distinct
        CatalogQuery IDs are found to be used for all subscription customers.

        Tests that no email is sent if the valid number of distinct CatalogQuery IDs are found.
        """
        mock_response = {
            'count': num_queries_found,
            'catalog_query_ids': [],
        }
        mock_api_client.return_value.get_distinct_catalog_queries.return_value = mock_response
        validate_query_mapping_task.delay()
        if is_valid:
            mock_email_fn.assert_not_called()
        else:
            mock_email_fn.assert_called()
