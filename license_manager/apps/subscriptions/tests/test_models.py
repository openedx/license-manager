from unittest import mock

import ddt
from django.test import TestCase

from license_manager.apps.subscriptions.constants import REVOKED, UNASSIGNED
from license_manager.apps.subscriptions.models import License, SubscriptionPlan
from license_manager.apps.subscriptions.tests.factories import (
    SubscriptionPlanFactory,
)


@ddt.ddt
class SubscriptionsModelTests(TestCase):
    """
    Tests for models in the subscriptions app.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.subscription_plan = SubscriptionPlanFactory()

    @mock.patch('license_manager.apps.subscriptions.models.EnterpriseCatalogApiClient', return_value=mock.MagicMock())
    @ddt.data(True, False)
    def test_contains_content(self, contains_content, mock_enterprise_catalog_client):
        # Mock the value from the enterprise catalog client
        mock_enterprise_catalog_client().contains_content_items.return_value = contains_content
        content_ids = ['test-key', 'another-key']
        assert self.subscription_plan.contains_content(content_ids) == contains_content
        mock_enterprise_catalog_client().contains_content_items.assert_called_with(
            self.subscription_plan.enterprise_catalog_uuid,
            content_ids,
        )


class LicenseModelTests(TestCase):
    """
    Tests for the License model.
    """
    CREATE_HISTORY_TYPE = '+'
    UPDATE_HISTORY_TYPE = '~'

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.subscription_plan = SubscriptionPlanFactory()

    @classmethod
    def tearDownClass(cls):  # pylint: disable=unused-argument
        """
        Removes all test instances of License that have been created.
        """
        License.objects.all().delete()

    def test_bulk_create(self):
        """
        Test that bulk_create creates and saves objects, and creates an associated
        historical record for the creation.
        """
        licenses = [License(subscription_plan=self.subscription_plan) for _ in range(3)]

        License.bulk_create(licenses)

        for user_license in licenses:
            user_license.refresh_from_db()
            assert UNASSIGNED == user_license.status
            license_history = user_license.history.all()
            assert 1 == len(license_history)
            assert self.CREATE_HISTORY_TYPE == user_license.history.earliest().history_type

    def test_bulk_update(self):
        """
        Test that bulk_update saves objects, and creates an associated
        historical record for the update action
        """
        licenses = [License(subscription_plan=self.subscription_plan) for _ in range(3)]

        License.bulk_create(licenses)

        for user_license in licenses:
            user_license.status = REVOKED

        License.bulk_update(licenses, ['status'])

        for user_license in licenses:
            user_license.refresh_from_db()
            assert REVOKED == user_license.status
            license_history = user_license.history.all()
            assert 2 == len(license_history)
            assert self.CREATE_HISTORY_TYPE == user_license.history.earliest().history_type
            assert self.UPDATE_HISTORY_TYPE == user_license.history.first().history_type
