import math
from datetime import datetime, timedelta
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import TestCase
from rest_framework import status

from license_manager.apps.subscriptions.constants import (
    ACTIVATED,
    ASSIGNED,
    LICENSE_EXPIRATION_BATCH_SIZE,
    REVOKED,
    UNASSIGNED,
)
from license_manager.apps.subscriptions.models import License, SubscriptionPlan
from license_manager.apps.subscriptions.tests.factories import (
    LicenseFactory,
    SubscriptionPlanFactory,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


@pytest.mark.django_db
class ExpireSubscriptionsCommandTests(TestCase):
    command_name = 'expire_subscriptions'
    today = localized_utcnow()

    def tearDown(self):
        """
        Deletes all licenses and subscription after each test method is run.
        """
        super().tearDown()
        License.objects.all().delete()
        SubscriptionPlan.objects.all().delete()

    def test_no_subscriptions_expiring_today(self):
        with self.assertLogs(level='INFO') as log:
            """
            Verify that the command returns when there are no subscriptions expiring
            """
            call_command(self.command_name)
            assert 'No subscriptions have expired between' in log.output[0]
            assert len(log.output) == 1

    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.expire_subscriptions.license_expiration_task'
    )
    def test_1_subscription_expiring_today(self, mock_license_expiration_task):
        """
        When there is a subscription expiring verify only the assigned and activated licenses are sent to edx-enterprise
        """
        expired_subscription = SubscriptionPlanFactory.create(
            start_date=self.today - timedelta(days=7),
            expiration_date=self.today,
        )

        # Create licenses with a variety of statuses
        LicenseFactory.create_batch(3, subscription_plan=expired_subscription)
        LicenseFactory.create_batch(2, status=ASSIGNED, subscription_plan=expired_subscription)
        LicenseFactory.create(status=ACTIVATED, subscription_plan=expired_subscription)
        LicenseFactory.create(status=REVOKED, subscription_plan=expired_subscription)

        call_command(self.command_name)
        expired_license_uuids = [str(license.uuid) for license in expired_subscription.licenses.filter(
            status__in=[ASSIGNED, ACTIVATED]
        )]
        mock_license_expiration_task.assert_called_with(expired_license_uuids)

    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.expire_subscriptions.license_expiration_task'
    )
    def test_1_subscription_expiring_outside_date_range(self, mock_license_expiration_task):
        """
        Verifies that only expired subscriptions within the expired range
        have their license uuids sent to edx-enterprise
        """
        # A recently expired subscription that should be processed
        expired_subscription = SubscriptionPlanFactory.create(
            start_date=self.today - timedelta(days=7),
            expiration_date=self.today,
        )

        # An expired subscription that expired about a month ago
        older_expired_subscription = SubscriptionPlanFactory.create(
            start_date=self.today - timedelta(days=60),
            expiration_date=self.today - timedelta(days=30),
        )

        # Create an activated license on each subscription
        license_to_expire_enrollments = LicenseFactory.create(status=ACTIVATED, subscription_plan=expired_subscription)
        LicenseFactory.create(status=ACTIVATED, subscription_plan=older_expired_subscription)

        call_command(self.command_name)
        mock_license_expiration_task.assert_called_with([str(license_to_expire_enrollments.uuid)])

    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.expire_subscriptions.license_expiration_task'
    )
    def test_2_subscriptions_expiring_within_range(self, mock_license_expiration_task):
        """
        Verifies that all expired subscriptions within the expired range have their license uuids sent to edx-enterprise
        """
        expired_subscription_1 = SubscriptionPlanFactory.create(
            start_date=datetime.strptime('2013-1-01 00:00:00', DATE_FORMAT),
            expiration_date=datetime.strptime('2014-1-01 00:00:00', DATE_FORMAT),
        )

        expired_subscription_2 = SubscriptionPlanFactory.create(
            start_date=datetime.strptime('2015-1-01 00:00:00', DATE_FORMAT),
            expiration_date=datetime.strptime('2016-1-01 00:00:00', DATE_FORMAT),
        )

        # Create an activated license on each subscription
        expired_license_1 = LicenseFactory.create(status=ACTIVATED, subscription_plan=expired_subscription_1)
        expired_license_2 = LicenseFactory.create(status=ACTIVATED, subscription_plan=expired_subscription_2)

        call_command(
            self.command_name,
            "--expired-after=2013-1-01 00:00:00",
            "--expired-before=2016-1-01 00:00:00"
        )
        actual_args = mock_license_expiration_task.call_args_list[0][0][0]
        assert sorted(actual_args) == sorted([str(expired_license_1.uuid), str(expired_license_2.uuid)])

    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.expire_subscriptions.license_expiration_task'
    )
    def test_expiring_10k_licenses_batched(self, mock_license_expiration_task):
        """
        Verifies that all expired subscriptions within the expired range have their license uuids sent to edx-enterprise
        """
        # A recently expired subscription that should be processed
        expired_subscription_1 = SubscriptionPlanFactory.create(
            start_date=self.today - timedelta(days=7),
            expiration_date=self.today,
        )
        expired_subscription_2 = SubscriptionPlanFactory.create(
            start_date=self.today - timedelta(days=7),
            expiration_date=self.today,
        )

        LicenseFactory.create_batch(500, status=ACTIVATED, subscription_plan=expired_subscription_1)
        LicenseFactory.create_batch(500, status=ACTIVATED, subscription_plan=expired_subscription_2)

        call_command(self.command_name)
        expected_call_count = math.ceil(1000 / LICENSE_EXPIRATION_BATCH_SIZE)
        assert expected_call_count == mock_license_expiration_task.call_count
