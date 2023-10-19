import uuid
from datetime import datetime, timedelta
from unittest import mock

import ddt
import freezegun
import pytest
from django.forms import ValidationError
from django.test import TestCase
from requests.exceptions import HTTPError

from license_manager.apps.subscriptions.constants import (
    ACTIVATED,
    ASSIGNED,
    REVOKED,
    UNASSIGNED,
    SegmentEvents,
)
from license_manager.apps.subscriptions.exceptions import CustomerAgreementError
from license_manager.apps.subscriptions.models import (
    License,
    LicenseTransferJob,
    Notification,
    SubscriptionLicenseSourceType,
)
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    LicenseFactory,
    SubscriptionLicenseSourceFactory,
    SubscriptionPlanFactory,
    SubscriptionPlanRenewalFactory,
)
from license_manager.apps.subscriptions.utils import (
    localized_datetime,
    localized_datetime_from_datetime,
    localized_utcnow,
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

    def test_auto_apply_licenses_turned_on_at(self):
        """
        Tests that auto_apply_licenses_turned_on_at returns the correct time.
        """
        subscription_plan = SubscriptionPlanFactory.create()
        subscription_plan.should_auto_apply_licenses = True
        subscription_plan.save()
        auto_apply_licenses_turned_on_at = subscription_plan.history.latest().history_date

        subscription_plan.is_active = True
        subscription_plan.save()
        latest_history_date = subscription_plan.history.latest().history_date

        self.assertEqual(subscription_plan.auto_apply_licenses_turned_on_at, auto_apply_licenses_turned_on_at)
        self.assertNotEqual(subscription_plan.auto_apply_licenses_turned_on_at, latest_history_date)

    def test_auto_applied_licenses_count_since(self):
        """
        Tests that the correct auto-applied license count is returned.
        """
        subscription_plan = SubscriptionPlanFactory.create(should_auto_apply_licenses=True)
        timestamp_1 = localized_utcnow()
        LicenseFactory.create_batch(1, subscription_plan=subscription_plan, auto_applied=True, activation_date=timestamp_1)
        LicenseFactory.create_batch(3, subscription_plan=subscription_plan, auto_applied=False, activation_date=timestamp_1)

        self.assertEqual(subscription_plan.auto_applied_licenses_count_since(), 1)
        timestamp_2 = timestamp_1 + timedelta(seconds=1)
        self.assertEqual(subscription_plan.auto_applied_licenses_count_since(timestamp_2), 0)
        LicenseFactory.create_batch(5, subscription_plan=subscription_plan, auto_applied=True, activation_date=timestamp_2)
        self.assertEqual(subscription_plan.auto_applied_licenses_count_since(timestamp_2), 5)


class NotificationTests(TestCase):
    """
    Test for the Notification Model.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.NOW = localized_datetime(2021, 7, 1)

        cls.enterprise_customer_uuid = uuid.uuid4()
        cls.enterprise_customer_user_uuid = uuid.uuid4()

    def test_notification_choices(self):
        """
        Verify we can create a Notification object with a valid notification type.
        """
        choices = [
            "Limited Allocations Remaining",
            "No Allocations Remaining",
            "Periodic Informational",
        ]
        for choice in choices:
            Notification.objects.create(
                enterprise_customer_uuid=self.enterprise_customer_uuid,
                enterprise_customer_user_uuid=self.enterprise_customer_user_uuid,
                last_sent=self.NOW,
                notification_type=choice
            )
        assert Notification.objects.count() == 3


@ddt.ddt
class LicenseModelTests(TestCase):
    """
    Tests for the License model.
    """
    CREATE_HISTORY_TYPE = '+'
    UPDATE_HISTORY_TYPE = '~'

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # technically this will be off on leap years, but we just need something later than now, so it's not a problem
        ONE_YEAR_FROM_NOW = localized_datetime_from_datetime(datetime.now() + timedelta(days=365))
        TWO_YEARS_FROM_NOW = localized_datetime_from_datetime(datetime.now() + timedelta(days=730))

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
            expiration_date=ONE_YEAR_FROM_NOW,
        )
        cls.active_current_license = LicenseFactory.create(
            user_email=cls.user_email,
            subscription_plan=cls.active_current_plan,
        )

        cls.inactive_current_plan = SubscriptionPlanFactory.create(
            customer_agreement=cls.customer_agreement,
            is_active=False,
            start_date=localized_datetime(2021, 1, 1),
            expiration_date=ONE_YEAR_FROM_NOW,
        )
        cls.inactive_current_license = LicenseFactory.create(
            user_email=cls.user_email,
            subscription_plan=cls.inactive_current_plan,
        )

        cls.non_current_active_plan = SubscriptionPlanFactory.create(
            customer_agreement=cls.customer_agreement,
            is_active=True,
            start_date=ONE_YEAR_FROM_NOW,
            expiration_date=TWO_YEARS_FROM_NOW,
        )
        cls.non_current_active_license = LicenseFactory.create(
            user_email=cls.user_email,
            subscription_plan=cls.non_current_active_plan,
        )

        cls.non_current_inactive_plan = SubscriptionPlanFactory.create(
            customer_agreement=cls.customer_agreement,
            is_active=False,
            start_date=ONE_YEAR_FROM_NOW,
            expiration_date=TWO_YEARS_FROM_NOW,
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
        super().tearDownClass()
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

    @mock.patch('license_manager.apps.subscriptions.models.track_license_changes')
    def test_bulk_create(self, mock_track_license_changes):
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

        mock_track_license_changes.assert_called_with(
            licenses,
            SegmentEvents.LICENSE_CREATED
        )

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

    def test_for_user_and_customer_no_kwargs(self):
        expected_licenses = [
            self.active_current_license,
            self.inactive_current_license,
            self.non_current_active_license,
            self.non_current_inactive_license,
        ]

        actual_licenses = License.for_user_and_customer(
            user_email=self.user_email,
            lms_user_id=None,
            enterprise_customer_uuid=self.enterprise_customer_uuid,
        )

        self.assertCountEqual(actual_licenses, expected_licenses)

    def test_for_user_and_customer_active_only(self):
        expected_licenses = [
            self.active_current_license,
            self.non_current_active_license,
        ]

        actual_licenses = License.for_user_and_customer(
            user_email=self.user_email,
            lms_user_id=None,
            enterprise_customer_uuid=self.enterprise_customer_uuid,
            active_plans_only=True,
        )

        self.assertCountEqual(actual_licenses, expected_licenses)

    def test_for_user_and_customer_current_only(self):
        expected_licenses = [
            self.active_current_license,
            self.inactive_current_license,
        ]

        actual_licenses = License.for_user_and_customer(
            user_email=self.user_email,
            lms_user_id=None,
            enterprise_customer_uuid=self.enterprise_customer_uuid,
            current_plans_only=True,
        )

        self.assertCountEqual(actual_licenses, expected_licenses)

    def test_for_user_and_customer_active_and_current_only(self):
        expected_licenses = [
            self.active_current_license,
        ]

        actual_licenses = License.for_user_and_customer(
            user_email=self.user_email,
            lms_user_id=None,
            enterprise_customer_uuid=self.enterprise_customer_uuid,
            active_plans_only=True,
            current_plans_only=True,
        )

        self.assertCountEqual(actual_licenses, expected_licenses)

    @ddt.data(ASSIGNED, ACTIVATED)
    def test_save(self, new_status):
        """
        Test that validation for duplicate assigned/activated licenses occurs on save.
        """
        LicenseFactory.create(
            user_email=self.user_email,
            subscription_plan=self.active_current_plan,
            status=ASSIGNED
        )

        unassigned_license = LicenseFactory.create(
            user_email=self.user_email,
            subscription_plan=self.active_current_plan,
            status=UNASSIGNED
        )

        with self.assertRaises(ValidationError):
            unassigned_license.status = new_status
            unassigned_license.save()


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


@ddt.ddt
class SubscriptionLicenseSourceModelTests(TestCase):
    """
    Tests for the `SubscriptionLicenseSource` model.
    """

    def setUp(self):
        super().setUp()

        self.user_email = 'bob@example.com'
        self.enterprise_customer_uuid = uuid.uuid4()
        self.customer_agreement = CustomerAgreementFactory.create(
            enterprise_customer_uuid=self.enterprise_customer_uuid,
        )

        self.active_current_plan = SubscriptionPlanFactory.create(
            customer_agreement=self.customer_agreement,
            is_active=True,
            start_date=localized_datetime(2021, 1, 1),
            expiration_date=localized_datetime_from_datetime(datetime.now() + timedelta(days=365)),
        )

        self.active_current_license = LicenseFactory.create(
            user_email=self.user_email,
            subscription_plan=self.active_current_plan,
        )

    def test_license_source_creation(self):
        """
        Tests license souce model object creation.
        """
        license_source = SubscriptionLicenseSourceFactory(
            license=self.active_current_license,
            source_id='000000000000000000',
            source_type=SubscriptionLicenseSourceType.get_source_type(SubscriptionLicenseSourceType.AMT)
        )
        str_repr = 'SubscriptionLicenseSource: LicenseID: {license_uuid}, SourceID: {source_id}, SourceType: AMT'
        assert str(license_source) == str_repr.format(
            license_uuid=self.active_current_license.uuid,
            source_id='000000000000000000',
        )

    def test_license_source_creation_with_invalid_souce_id(self):
        """
        Verify that SubscriptionLicenseSource model raises exception if source id format is wrong.
        """
        with pytest.raises(ValidationError) as raised_exception:
            SubscriptionLicenseSourceFactory(
                license=self.active_current_license,
                source_id='000000000',
                source_type=SubscriptionLicenseSourceType.get_source_type(SubscriptionLicenseSourceType.AMT)
            )

        exception_message = ['Ensure this value has at least 18 characters (it has 9).']
        assert raised_exception.value.args[0]['source_id'][0].messages == exception_message


@ddt.ddt
class LicenseTransferJobTests(TestCase):
    """
    Tests for the `LicenseTransferJob` model.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.enterprise_customer_uuid = uuid.uuid4()
        cls.customer_agreement = CustomerAgreementFactory.create(
            enterprise_customer_uuid=cls.enterprise_customer_uuid,
        )

        cls.old_plan = SubscriptionPlanFactory.create(
            customer_agreement=cls.customer_agreement,
            is_active=True,
            start_date=localized_datetime(2021, 1, 1),
            expiration_date=localized_datetime_from_datetime(datetime.now() + timedelta(days=365)),
        )
        cls.new_plan = SubscriptionPlanFactory.create(
            customer_agreement=cls.customer_agreement,
            is_active=True,
            start_date=localized_datetime(2021, 1, 1),
            expiration_date=localized_datetime_from_datetime(datetime.now() + timedelta(days=365)),
        )

    def tearDown(self):
        super().tearDown()
        License.objects.all().delete()

    def _create_transfer_job(self, license_uuids_raw, **kwargs):
        return LicenseTransferJob.objects.create(
            customer_agreement=self.customer_agreement,
            old_subscription_plan=self.old_plan,
            new_subscription_plan=self.new_plan,
            license_uuids_raw=license_uuids_raw,
            **kwargs,
        )

    def test_get_licenses_to_transfer(self):
        """
        Tests that we only operate on activated or assigned licenses from the old plan
        of a transfer job.
        """
        old_assigned_licenses = LicenseFactory.create_batch(
            3, subscription_plan=self.old_plan, assigned_date=localized_utcnow(), status=ASSIGNED,
        )
        old_activated_licenses = LicenseFactory.create_batch(
            3, subscription_plan=self.old_plan, assigned_date=localized_utcnow(), status=ACTIVATED,
        )
        # old unassigned licenses
        LicenseFactory.create_batch(
            3, subscription_plan=self.old_plan,
        )
        # new_licenses
        LicenseFactory.create_batch(
            3, subscription_plan=self.new_plan, assigned_date=localized_utcnow(), status=ACTIVATED,
        )

        job = self._create_transfer_job(
            license_uuids_raw='\n'.join([str(_license.uuid) for _license in self.old_plan.licenses.all()]),
        )

        expected_licenses = {
            _license.uuid: _license
            for _license in old_assigned_licenses + old_activated_licenses
        }
        actual_licenses = {
            _license.uuid: _license
            for license_batch in job.get_licenses_to_transfer()
            for _license in license_batch
        }
        self.assertEqual(expected_licenses, actual_licenses)

    def test_transfer_dry_run_processing(self):
        """
        Tests that a dry-run process doesn't actually modify the
        otherwise impacted licenses.
        """
        old_activated_licenses = LicenseFactory.create_batch(
            3, subscription_plan=self.old_plan, assigned_date=localized_utcnow(), status=ACTIVATED,
        )

        job = self._create_transfer_job(
            license_uuids_raw='\n'.join([str(_license.uuid) for _license in old_activated_licenses]),
            is_dry_run=True,
        )
        job.process()

        for _license in old_activated_licenses:
            _license.refresh_from_db()
            self.assertEqual(_license.subscription_plan, self.old_plan)

        self.assertCountEqual(
            job.processed_results[0]['modified_licenses'],
            [str(_license.uuid) for _license in old_activated_licenses]
        )
        self.assertTrue(job.processed_results[0]['is_dry_run'])
        self.assertAlmostEqual(
            job.processed_results[0]['completed_at'],
            localized_utcnow(),
            delta=timedelta(seconds=2),
        )
        self.assertIsNone(job.completed_at)

    def test_transfer_idempotent_processing(self):
        """
        Tests that the `process()` method is idempotent.
        """
        old_activated_licenses = LicenseFactory.create_batch(
            3, subscription_plan=self.old_plan, assigned_date=localized_utcnow(), status=ACTIVATED,
        )

        job = self._create_transfer_job(
            license_uuids_raw='\n'.join([str(_license.uuid) for _license in old_activated_licenses]),
            is_dry_run=False,
        )
        job.process()

        for _license in old_activated_licenses:
            _license.refresh_from_db()
            self.assertEqual(_license.subscription_plan, self.new_plan)

        self.assertCountEqual(
            job.processed_results[0]['modified_licenses'],
            [str(_license.uuid) for _license in old_activated_licenses]
        )
        self.assertFalse(job.processed_results[0]['is_dry_run'])
        original_completed_at = job.completed_at
        self.assertAlmostEqual(
            original_completed_at,
            localized_utcnow(),
            delta=timedelta(seconds=2),
        )

        # now process the same job again, nothing should change
        job.process()
        for _license in old_activated_licenses:
            _license.refresh_from_db()
            self.assertEqual(_license.subscription_plan, self.new_plan)
        self.assertEqual(len(job.processed_results), 1)
        self.assertEqual(job.completed_at, original_completed_at)

    def test_transfer_reversable_processing(self):
        """
        Tests that we can transfer licenses one way, then create a second
        job to transfer them in the reverse direction.
        """
        old_activated_licenses = LicenseFactory.create_batch(
            3, subscription_plan=self.old_plan, assigned_date=localized_utcnow(), status=ACTIVATED,
        )

        raw_license_uuids = '\n'.join([str(_license.uuid) for _license in old_activated_licenses])
        job = self._create_transfer_job(
            license_uuids_raw=raw_license_uuids,
            is_dry_run=False,
        )
        job.process()

        for _license in old_activated_licenses:
            _license.refresh_from_db()
            self.assertEqual(_license.subscription_plan, self.new_plan)

        reverse_job = LicenseTransferJob.objects.create(
            customer_agreement=self.customer_agreement,
            old_subscription_plan=self.new_plan,
            new_subscription_plan=self.old_plan,
            license_uuids_raw=raw_license_uuids,
            is_dry_run=False,
        )

        reverse_job.process()

        for _license in old_activated_licenses:
            _license.refresh_from_db()
            self.assertEqual(_license.subscription_plan, self.old_plan)
