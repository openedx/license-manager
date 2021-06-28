import uuid
from datetime import date
from unittest import mock

import ddt
from django.test import TestCase

from license_manager.apps.subscriptions.constants import REVOKED, UNASSIGNED
from license_manager.apps.subscriptions.models import License, SubscriptionPlan
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    LicenseFactory,
    SubscriptionPlanFactory,
)
from license_manager.apps.subscriptions.utils import (
    localized_datetime_from_date,
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

        NOW = localized_datetime_from_date(date(2021, 7, 1))

        cls.user_email = 'bob@example.com'
        cls.enterprise_customer_uuid = uuid.uuid4()
        cls.customer_agreement = CustomerAgreementFactory.create(
            enterprise_customer_uuid=cls.enterprise_customer_uuid,
        )

        cls.subscription_plan = SubscriptionPlanFactory()

        cls.active_current_plan = SubscriptionPlanFactory.create(
            customer_agreement=cls.customer_agreement,
            is_active=True,
            start_date=date(2021, 1, 1),
            expiration_date=date(2021, 12, 31),
        )
        cls.active_current_license = LicenseFactory.create(
            user_email=cls.user_email,
            subscription_plan=cls.active_current_plan,
        )

        cls.inactive_current_plan = SubscriptionPlanFactory.create(
            customer_agreement=cls.customer_agreement,
            is_active=False,
            start_date=date(2021, 1, 1),
            expiration_date=date(2021, 12, 31),
        )
        cls.inactive_current_license = LicenseFactory.create(
            user_email=cls.user_email,
            subscription_plan=cls.inactive_current_plan,
        )

        cls.non_current_active_plan = SubscriptionPlanFactory.create(
            customer_agreement=cls.customer_agreement,
            is_active=True,
            start_date=date(2022, 1, 1),
            expiration_date=date(2022, 12, 31),
        )
        cls.non_current_active_license = LicenseFactory.create(
            user_email=cls.user_email,
            subscription_plan=cls.non_current_active_plan,
        )

        cls.non_current_inactive_plan = SubscriptionPlanFactory.create(
            customer_agreement=cls.customer_agreement,
            is_active=False,
            start_date=date(2022, 1, 1),
            expiration_date=date(2022, 12, 31),
        )
        cls.non_current_inactive_license = LicenseFactory.create(
            user_email=cls.user_email,
            subscription_plan=cls.non_current_inactive_plan,
        )

    @classmethod
    def tearDownClass(cls):  # pylint: disable=unused-argument
        """
        Removes all test instances of License that have been created.
        """
        License.objects.all().delete()

    def test_license_renewed_to_and_from(self):
        """
        Tests that links between renewed licenses are sane.
        """
        original = LicenseFactory.create()
        future = LicenseFactory.create()

        original.renewed_to = future
        original.save()
        future.save()

        self.assertEqual(future.renewed_from, original)

        another_one = LicenseFactory.create()
        self.assertIsNone(another_one.renewed_to)
        self.assertIsNone(another_one.renewed_from)

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

    def test_for_email_and_customer_no_kwargs(self):
        expected_licenses = [
            self.active_current_license,
            self.inactive_current_license,
            self.non_current_active_license,
            self.non_current_inactive_license,
        ]

        actual_licenses = License.for_email_and_customer(
            self.user_email,
            self.enterprise_customer_uuid,
        )

        self.assertCountEqual(actual_licenses, expected_licenses)

    def test_for_email_and_customer_active_only(self):
        expected_licenses = [
            self.active_current_license,
            self.non_current_active_license,
        ]

        actual_licenses = License.for_email_and_customer(
            self.user_email,
            self.enterprise_customer_uuid,
            active_plans_only=True,
        )

        self.assertCountEqual(actual_licenses, expected_licenses)

    def test_for_email_and_customer_current_only(self):
        expected_licenses = [
            self.active_current_license,
            self.inactive_current_license,
        ]

        actual_licenses = License.for_email_and_customer(
            self.user_email,
            self.enterprise_customer_uuid,
            current_plans_only=True,
        )

        self.assertCountEqual(actual_licenses, expected_licenses)

    def test_for_email_and_customer_active_and_current_only(self):
        expected_licenses = [
            self.active_current_license,
        ]

        actual_licenses = License.for_email_and_customer(
            self.user_email,
            self.enterprise_customer_uuid,
            active_plans_only=True,
            current_plans_only=True,
        )

        self.assertCountEqual(actual_licenses, expected_licenses)
