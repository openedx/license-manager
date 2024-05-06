import uuid
from unittest import mock

import ddt
from django.core.management import call_command
from django.test import TestCase

from license_manager.apps.subscriptions.management.commands.validate_num_catalog_queries import (
    InvalidCatalogQueryMappingError,
)
from license_manager.apps.subscriptions.tests.factories import (
    PlanTypeFactory,
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
    def test_error_logged_for_invalid_num_queries(self, is_valid, mock_api_client):
        """
        Tests that an error is logged in the case that an invalid number of distinct
        CatalogQuery IDs are found to be used for all subscription customers.

        Tests that no email is sent if the valid number of distinct CatalogQuery IDs are found.
        """
        # Number of distinct subscription types ("correct" number)
        num_subs = 3

        for i in range(num_subs):
            plan_type = PlanTypeFactory(internal_use_only=False, label=f'PlanType{i}')
            SubscriptionPlanFactory(
                product=ProductFactory(
                    netsuite_id=i,
                    plan_type=plan_type,
                ),
            )

        if is_valid:
            log_level = 'INFO'
            num_queries_found = num_subs
        else:
            log_level = 'ERROR'
            num_queries_found = num_subs + 1
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

    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.validate_num_catalog_queries.EnterpriseCatalogApiClient'
    )
    def test_allow_list_is_respected(self, mock_api_client):
        """
        Tests that our configurable allow list of customized subscription catalogs
        is respected by this command.
        """
        # Number of distinct subscription types ("correct" number)
        num_subs = 2
        allowed_custom_catalog_uuid = str(uuid.uuid4())
        allow_list = [allowed_custom_catalog_uuid]

        for i in range(num_subs):
            plan_type = PlanTypeFactory(internal_use_only=False, label=f'PlanType{i}')
            SubscriptionPlanFactory(
                product=ProductFactory(
                    netsuite_id=i,
                    plan_type=plan_type,
                ),
            )

        with self.assertLogs(level='INFO') as log, \
             self.settings(CUSTOM_CATALOG_PRODUCTS_ALLOW_LIST=allow_list):
            catalog_query_ids = {}
            for index in range(num_subs):
                catalog_query_ids[index] = [str(uuid.uuid4())]

            # add one allowed *custom* catalog uuid to the response payload
            catalog_query_ids[42] = allowed_custom_catalog_uuid

            mock_api_client.return_value.get_distinct_catalog_queries.return_value = {
                'num_distinct_query_ids': len(catalog_query_ids),
                'catalog_uuids_by_catalog_query_id': catalog_query_ids,
            }
            call_command(self.command_name)
            assert 'SUCCESS' in log.output[0]
