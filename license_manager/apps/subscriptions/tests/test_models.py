import uuid
from unittest import mock

import ddt
import freezegun
from django.test import TestCase
from requests.exceptions import HTTPError

from license_manager.apps.subscriptions.constants import REVOKED, UNASSIGNED
from license_manager.apps.subscriptions.exceptions import (
    CustomerAgreementException,
)
from license_manager.apps.subscriptions.models import License
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    LicenseFactory,
    SubscriptionPlanFactory,
    SubscriptionPlanRenewalFactory,
)
from license_manager.apps.subscriptions.utils import localized_datetime, localized_utcnow


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

    def test_prior_renewals(self):
        renewed_subscription_plan_1 = SubscriptionPlanFactory.create()
        renewed_subscription_plan_2 = SubscriptionPlanFactory.create()
        renewal_1 = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=self.subscription_plan,
            renewed_subscription_plan=renewed_subscription_plan_1
        )
        renewal_2 = SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=renewed_subscription_plan_1,
            renewed_subscription_plan=renewed_subscription_plan_2
        )
        self.assertEqual(renewed_subscription_plan_2.prior_renewals, [renewal_1, renewal_2])

    @ddt.data(True, False)
    def test_is_locked_for_renewal_processing(self, is_locked_for_renewal_processing):
        today = localized_utcnow()
        with freezegun.freeze_time(today):
            renewed_subscription_plan = SubscriptionPlanFactory.create(expiration_date=today)
            renewal_kwargs = {'prior_subscription_plan': renewed_subscription_plan}
            if is_locked_for_renewal_processing:
                renewal_kwargs.update({'effective_date': renewed_subscription_plan.expiration_date})
            SubscriptionPlanRenewalFactory.create(**renewal_kwargs)
            self.assertEqual(renewed_subscription_plan.is_locked_for_renewal_processing, is_locked_for_renewal_processing)


class LicenseModelTests(TestCase):
    """
    Tests for the License model.
    """
    CREATE_HISTORY_TYPE = '+'
    UPDATE_HISTORY_TYPE = '~'

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        NOW = localized_datetime(2021, 7, 1)

        cls.user_email = 'bob@example.com'
        cls.enterprise_customer_uuid = uuid.uuid4()
        cls.customer_agreement = CustomerAgreementFactory.create(
            enterprise_customer_uuid=cls.enterprise_customer_uuid,
        )

        cls.subscription_plan = SubscriptionPlanFactory()

        cls.active_current_plan = SubscriptionPlanFactory.create(
            customer_agreement=cls.customer_agreement,
            is_active=True,
            start_date=localized_datetime(2021, 1, 1),
            expiration_date=localized_datetime(2021, 12, 31),
        )
        cls.active_current_license = LicenseFactory.create(
            user_email=cls.user_email,
            subscription_plan=cls.active_current_plan,
        )

        cls.inactive_current_plan = SubscriptionPlanFactory.create(
            customer_agreement=cls.customer_agreement,
            is_active=False,
            start_date=localized_datetime(2021, 1, 1),
            expiration_date=localized_datetime(2021, 12, 31),
        )
        cls.inactive_current_license = LicenseFactory.create(
            user_email=cls.user_email,
            subscription_plan=cls.inactive_current_plan,
        )

        cls.non_current_active_plan = SubscriptionPlanFactory.create(
            customer_agreement=cls.customer_agreement,
            is_active=True,
            start_date=localized_datetime(2022, 1, 1),
            expiration_date=localized_datetime(2022, 12, 31),
        )
        cls.non_current_active_license = LicenseFactory.create(
            user_email=cls.user_email,
            subscription_plan=cls.non_current_active_plan,
        )

        cls.non_current_inactive_plan = SubscriptionPlanFactory.create(
            customer_agreement=cls.customer_agreement,
            is_active=False,
            start_date=localized_datetime(2022, 1, 1),
            expiration_date=localized_datetime(2022, 12, 31),
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

    @mock.patch('license_manager.apps.subscriptions.models.dispatch_license_create_events')
    def test_bulk_create(self, mock_post_save_event):
        """
        Test that bulk_create creates and saves objects, and creates an associated
        historical record for the creation, and calls the create track_event.
        """
        licenses = [License(subscription_plan=self.subscription_plan) for _ in range(3)]

        License.bulk_create(licenses)

        for user_license in licenses:
            user_license.refresh_from_db()
            assert UNASSIGNED == user_license.status
            license_history = user_license.history.all()
            assert 1 == len(license_history)
            assert self.CREATE_HISTORY_TYPE == user_license.history.earliest().history_type

        # Assert we made the right # of tracking calls total.
        assert len(licenses) == mock_post_save_event.call_count

    @mock.patch('license_manager.apps.subscriptions.models.dispatch_license_create_events')
    def test_bulk_update(self, mock_post_save_event):
        """
        Test that bulk_update saves objects, and creates an associated
        historical record for the update action
        """
        licenses = [License(subscription_plan=self.subscription_plan) for _ in range(3)]

        License.bulk_create(licenses)

        for user_license in licenses:
            user_license.status = REVOKED

        License.bulk_update(licenses, ['status'])

        # Assert we made the right # of tracking calls total.
        assert 2 * len(licenses) == mock_post_save_event.call_count

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


class CustomerAgreementTests(TestCase):
    """
    Test for the CustomerAgreement model.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.customer_agreement = CustomerAgreementFactory()
        cls.subscription_plan_a = SubscriptionPlanFactory(
            expiration_date=localized_datetime(2020, 1, 1),
            customer_agreement=cls.customer_agreement,
        )
        cls.subscription_plan_b = SubscriptionPlanFactory(
            expiration_date=localized_datetime(2021, 1, 1),
            customer_agreement=cls.customer_agreement
        )

    def test_net_days_until_expiration(self):
        today = localized_datetime(2020, 1, 1)
        with freezegun.freeze_time(today):
            expected_days = (self.subscription_plan_b.expiration_date - today).days
            assert self.customer_agreement.net_days_until_expiration == expected_days

    @mock.patch('license_manager.apps.subscriptions.models.EnterpriseApiClient', autospec=True)
    def test_save_with_slug(self, mock_client):
        self.customer_agreement.save()

        self.assertFalse(mock_client.called)

    @mock.patch('license_manager.apps.subscriptions.models.EnterpriseApiClient', autospec=True)
    def test_save_without_slug(self, mock_client):
        agreement = CustomerAgreementFactory()
        agreement.enterprise_customer_slug = None
        client = mock_client.return_value
        client.get_enterprise_customer_data.return_value = {
            'slug': 'new-slug',
        }

        agreement.save()

        self.assertTrue(mock_client.called)
        client.get_enterprise_customer_data.assert_called_once_with(
            agreement.enterprise_customer_uuid
        )
        self.assertEqual('new-slug', agreement.enterprise_customer_slug)

    @mock.patch('license_manager.apps.subscriptions.models.EnterpriseApiClient', autospec=True)
    def test_save_without_slug_http_error(self, mock_client):
        agreement = CustomerAgreementFactory()
        agreement.enterprise_customer_slug = None
        client = mock_client.return_value
        client.get_enterprise_customer_data.side_effect = HTTPError('some error')

        with self.assertRaisesRegex(CustomerAgreementException, 'some error'):
            agreement.save()

        self.assertTrue(mock_client.called)
        client.get_enterprise_customer_data.assert_called_once_with(
            agreement.enterprise_customer_uuid
        )
        self.assertIsNone(agreement.enterprise_customer_slug)
