from datetime import datetime, timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from faker import Factory as FakerFactory
from freezegun import freeze_time

from license_manager.apps.subscriptions.constants import (
    ACTIVATED,
    ASSIGNED,
    DAYS_TO_RETIRE,
    REVOKED,
    UNASSIGNED,
)
from license_manager.apps.subscriptions.models import (
    License,
    SubscriptionLicenseSource,
)
from license_manager.apps.subscriptions.tests.factories import (
    LicenseFactory,
    SubscriptionLicenseSourceFactory,
    SubscriptionPlanFactory,
)
from license_manager.apps.subscriptions.tests.utils import (
    assert_date_fields_correct,
    assert_historical_pii_cleared,
    assert_license_fields_cleared,
    assert_pii_cleared,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


faker = FakerFactory.create()


class RetireOldLicensesCommandTests(TestCase):
    command_name = 'retire_old_licenses'

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        subscription_plan = SubscriptionPlanFactory()
        day_before_retirement_deadline = localized_utcnow() - timedelta(DAYS_TO_RETIRE + 1)
        cls.expired_subscription_plan = SubscriptionPlanFactory(expiration_date=day_before_retirement_deadline)

        # Set up a bunch of licenses that should not be retired
        LicenseFactory.create_batch(
            3,
            status=ACTIVATED,
            subscription_plan=subscription_plan,
            revoked_date=None,
        )
        LicenseFactory.create_batch(
            4,
            status=REVOKED,
            subscription_plan=subscription_plan,
            revoked_date=localized_utcnow(),
        )
        LicenseFactory.create_batch(
            5,
            status=REVOKED,
            subscription_plan=subscription_plan,
            revoked_date=localized_utcnow(),
        )
        LicenseFactory.create_batch(
            5,
            status=REVOKED,
            subscription_plan=subscription_plan,
            revoked_date=day_before_retirement_deadline,
            user_email=None,  # The user_email is None to represent already retired licenses
        )
        LicenseFactory.create_batch(
            2,
            status=ASSIGNED,
            subscription_plan=subscription_plan,
            assigned_date=localized_utcnow(),
            revoked_date=None,
        )

        # Set up licenses that should be retired as either there subscription plan has been expired for long enough
        # for retirement, or they were assigned/revoked a day before the current date to retire.
        cls.num_revoked_licenses_to_retire = 6
        cls.revoked_licenses_ready_for_retirement = LicenseFactory.create_batch(
            cls.num_revoked_licenses_to_retire,
            status=REVOKED,
            subscription_plan=subscription_plan,
            revoked_date=day_before_retirement_deadline,
        )
        for revoked_license in cls.revoked_licenses_ready_for_retirement:
            revoked_license.lms_user_id = faker.random_int()
            revoked_license.user_email = faker.email()
            revoked_license.save()
            SubscriptionLicenseSourceFactory.create(license=revoked_license)

        cls.num_assigned_licenses_to_retire = 7
        cls.assigned_licenses_ready_for_retirement = LicenseFactory.create_batch(
            cls.num_assigned_licenses_to_retire,
            status=ASSIGNED,
            subscription_plan=subscription_plan,
            assigned_date=day_before_retirement_deadline,
        )
        for assigned_license in cls.assigned_licenses_ready_for_retirement:
            assigned_license.lms_user_id = faker.random_int()
            assigned_license.user_email = faker.email()
            assigned_license.save()
            SubscriptionLicenseSourceFactory.create(license=assigned_license)

        # Create licenses of different statuses that should be retired from association with an old expired subscription
        LicenseFactory.create(
            status=ACTIVATED,
            subscription_plan=cls.expired_subscription_plan,
            lms_user_id=faker.random_int(),
            user_email=faker.email(),
        )
        LicenseFactory.create(
            status=ASSIGNED,
            subscription_plan=cls.expired_subscription_plan,
            lms_user_id=faker.random_int(),
            user_email=faker.email(),
        )
        LicenseFactory.create(
            status=REVOKED,
            lms_user_id=faker.random_int(),
            user_email=faker.email(),
            subscription_plan=cls.expired_subscription_plan,
        )

    def tearDown(self):
        """
        Deletes all licenses after each test method is run.
        """
        super().tearDown()

        License.objects.all().delete()

    @mock.patch('license_manager.apps.subscriptions.event_utils.track_event')  # Mock silences log outputs
    def test_retire_old_licenses(self, _):
        """
        Verify that the command retires the correct licenses appropriately and logs messages about the retirement.
        """
        with freeze_time(localized_utcnow()), self.assertLogs(level='INFO') as log:
            call_command(self.command_name, '--batch-size=2')

            # Verify all expired licenses that were ready for retirement have been retired correctly
            expired_licenses = self.expired_subscription_plan.licenses.all()
            assert_date_fields_correct(expired_licenses, ['revoked_date'], True)
            for expired_license in expired_licenses:
                expired_license.refresh_from_db()
                assert_pii_cleared(expired_license)
                assert expired_license.status == REVOKED
                assert_historical_pii_cleared(expired_license)

            message = 'Retired {} expired licenses with uuids: {}'.format(
                expired_licenses.count(),
                sorted([expired_license.uuid for expired_license in expired_licenses]),
            )
            assert message in ' '.join(log.output)

            # Verify all revoked licenses that were ready for retirement have been retired correctly
            for revoked_license in self.revoked_licenses_ready_for_retirement:
                revoked_license.refresh_from_db()
                assert_pii_cleared(revoked_license)
                assert_historical_pii_cleared(revoked_license)
                with self.assertRaises(SubscriptionLicenseSource.DoesNotExist):
                    revoked_license.source

            message = 'Retired {} revoked licenses with uuids: {}'.format(
                self.num_revoked_licenses_to_retire,
                sorted([revoked_license.uuid for revoked_license in self.revoked_licenses_ready_for_retirement]),
            )
            assert message in ' '.join(log.output)

            # Verify all assigned licenses that were ready for retirement have been retired correctly
            for assigned_license in self.assigned_licenses_ready_for_retirement:
                assigned_license.refresh_from_db()
                assert_license_fields_cleared(assigned_license)
                assert_pii_cleared(assigned_license)
                assert_historical_pii_cleared(assigned_license)
                assert assigned_license.activation_key is None
                assert assigned_license.status == UNASSIGNED

            message = 'Retired {} assigned licenses that exceeded their inactivation duration with uuids: {}'.format(
                self.num_assigned_licenses_to_retire,
                sorted([assigned_license.uuid for assigned_license in self.assigned_licenses_ready_for_retirement]),
            )
            assert message in ' '.join(log.output)
