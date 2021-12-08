import math
from datetime import timedelta
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import TestCase

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
    SubscriptionPlanRenewalFactory,
)
from license_manager.apps.subscriptions.utils import (
    localized_datetime,
    localized_utcnow,
)


@pytest.mark.django_db
class ExpireSubscriptionsCommandTests(TestCase):
    command_name = 'expire_subscriptions'
    today = localized_utcnow()

    def _create_expired_plan_with_licenses(
        self,
        unassigned_licenses_count=1,
        assigned_licenses_count=2,
        activated_licenses_count=3,
        revoked_licenses_count=4,
        start_date=today - timedelta(days=7),
        expiration_date=today,
        expiration_processed=False
    ):
        """
        Creates a plan with licenses. The plan is expired by default.
        """
        expired_plan = SubscriptionPlanFactory.create(
            start_date=start_date,
            expiration_date=expiration_date,
            expiration_processed=expiration_processed
        )

        LicenseFactory.create_batch(unassigned_licenses_count, status=UNASSIGNED, subscription_plan=expired_plan)
        LicenseFactory.create_batch(assigned_licenses_count, status=ASSIGNED, subscription_plan=expired_plan)
        LicenseFactory.create_batch(activated_licenses_count, status=ACTIVATED, subscription_plan=expired_plan)
        LicenseFactory.create_batch(revoked_licenses_count, status=REVOKED, subscription_plan=expired_plan)

        return expired_plan

    def _get_allocated_license_uuids(self, subscription_plan):
        return [str(license.uuid) for license in subscription_plan.licenses.filter(status__in=[ASSIGNED, ACTIVATED])]

    def tearDown(self):
        """
        Deletes all licenses and subscriptions after each test method is run.
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

    @mock.patch('license_manager.apps.subscriptions.event_utils.track_event')
    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.expire_subscriptions.license_expiration_task'
    )
    def test_1_subscription_expiring_today(self, mock_license_expiration_task, mock_track_event):
        """
        When there is a subscription expiring verify only the assigned and activated licenses are sent to edx-enterprise
        """
        expired_subscription = self._create_expired_plan_with_licenses()

        call_command(self.command_name)

        expired_license_uuids = self._get_allocated_license_uuids(expired_subscription)
        mock_license_expiration_task.assert_called_with(
            expired_license_uuids,
            ignore_enrollments_modified_after=None
        )
        expired_subscription.refresh_from_db()
        self.assertTrue(expired_subscription.expiration_processed)

    @mock.patch('license_manager.apps.subscriptions.event_utils.track_event')
    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.expire_subscriptions.license_expiration_task'
    )
    def test_1_subscription_expiring_outside_date_range(self, mock_license_expiration_task, mock_track_event):
        """
        Verifies that only expired subscriptions within the expired range
        have their license uuids sent to edx-enterprise
        """
        # A recently expired subscription that should be processed
        expired_subscription = self._create_expired_plan_with_licenses()

        # An expired subscription that expired about a month ago
        self._create_expired_plan_with_licenses(
            start_date=self.today - timedelta(days=60),
            expiration_date=self.today - timedelta(days=30)
        )

        expired_license_uuids = self._get_allocated_license_uuids(expired_subscription)
        call_command(self.command_name)
        mock_license_expiration_task.assert_called_with(
            expired_license_uuids,
            ignore_enrollments_modified_after=None
        )
        expired_subscription.refresh_from_db()
        self.assertTrue(expired_subscription.expiration_processed)

    @mock.patch('license_manager.apps.subscriptions.event_utils.track_event')
    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.expire_subscriptions.license_expiration_task'
    )
    def test_subscriptions_expiring_within_range(self, mock_license_expiration_task, mock_track_event):
        """
        Verifies that all expired and unprocessed subscriptions within the expired range have their license uuids sent to edx-enterprise.
        """

        expired_subscription_1 = self._create_expired_plan_with_licenses(
            start_date=localized_datetime(2013, 1, 1),
            expiration_date=localized_datetime(2014, 1, 1),
        )

        expired_subscription_2 = self._create_expired_plan_with_licenses(
            start_date=localized_datetime(2015, 1, 1),
            expiration_date=localized_datetime(2016, 1, 1),
        )

        self._create_expired_plan_with_licenses(
            start_date=localized_datetime(2015, 1, 1),
            expiration_date=localized_datetime(2016, 1, 1),
            expiration_processed=True
        )

        call_command(
            self.command_name,
            "--expired-after=2013-1-01T00:00:00",
            "--expired-before=2016-1-01T00:00:00"
        )

        expired_license_uuids_1 = self._get_allocated_license_uuids(expired_subscription_1)
        expired_license_uuids_2 = self._get_allocated_license_uuids(expired_subscription_2)
        mock_license_expiration_task.assert_any_call(
            expired_license_uuids_1,
            ignore_enrollments_modified_after='2014-01-01T00:00:00+00:00'
        )
        mock_license_expiration_task.assert_any_call(
            expired_license_uuids_2,
            ignore_enrollments_modified_after='2016-01-01T00:00:00+00:00'
        )
        assert mock_license_expiration_task.call_count == 2

        expired_subscription_1.refresh_from_db()
        expired_subscription_2.refresh_from_db()
        self.assertTrue(expired_subscription_1.expiration_processed)
        self.assertTrue(expired_subscription_2.expiration_processed)

    @mock.patch('license_manager.apps.subscriptions.event_utils.track_event')
    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.expire_subscriptions.license_expiration_task'
    )
    def test_subscriptions_expiring_within_range_forced(self, mock_license_expiration_task, mock_track_event):
        """
        Verifies that all expired subscriptions within the expired range, including previously processed ones,
        have their license uuids sent to edx-enterprise if the force flag is passed.
        """

        expired_subscription_1 = self._create_expired_plan_with_licenses(
            start_date=localized_datetime(2013, 1, 1),
            expiration_date=localized_datetime(2014, 1, 1),
            expiration_processed=True
        )

        expired_subscription_2 = self._create_expired_plan_with_licenses(
            start_date=localized_datetime(2015, 1, 1),
            expiration_date=localized_datetime(2016, 1, 1),
            expiration_processed=True
        )

        call_command(
            self.command_name,
            "--expired-after=2013-1-01T00:00:00",
            "--expired-before=2016-1-01T00:00:00",
            "--force"
        )

        expired_license_uuids_1 = self._get_allocated_license_uuids(expired_subscription_1)
        expired_license_uuids_2 = self._get_allocated_license_uuids(expired_subscription_2)
        mock_license_expiration_task.assert_any_call(
            expired_license_uuids_1,
            ignore_enrollments_modified_after='2014-01-01T00:00:00+00:00'
        )
        mock_license_expiration_task.assert_any_call(
            expired_license_uuids_2,
            ignore_enrollments_modified_after='2016-01-01T00:00:00+00:00'
        )
        assert mock_license_expiration_task.call_count == 2

        expired_subscription_1.refresh_from_db()
        expired_subscription_2.refresh_from_db()
        self.assertTrue(expired_subscription_1.expiration_processed)
        self.assertTrue(expired_subscription_2.expiration_processed)

    @mock.patch('license_manager.apps.subscriptions.event_utils.track_event')
    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.expire_subscriptions.license_expiration_task'
    )
    def test_subscriptions_expiring_with_uuids(self, mock_license_expiration_task, mock_track_event):
        """
        Verifies that expired subscriptions with the given uuids, including previously processed ones,
        have their license uuids sent to edx-enterprise.
        """

        expired_subscription_1 = self._create_expired_plan_with_licenses(
            start_date=localized_datetime(2013, 1, 1),
            expiration_date=localized_datetime(2014, 1, 1),
            expiration_processed=True
        )

        expired_subscription_2 = self._create_expired_plan_with_licenses(
            start_date=localized_datetime(2015, 1, 1),
            expiration_date=localized_datetime(2016, 1, 1),
            expiration_processed=False
        )

        call_command(
            self.command_name,
            "--subscription-uuids={}".format(
                ','.join([str(expired_subscription_1.uuid)])
            ),
        )

        args_1 = mock_license_expiration_task.call_args_list[0][0][0]
        assert args_1 == self._get_allocated_license_uuids(expired_subscription_1)
        assert mock_license_expiration_task.call_args_list[0][1][
            'ignore_enrollments_modified_after'
        ] == '2014-01-01T00:00:00+00:00'
        assert mock_license_expiration_task.call_count == 1

        expired_subscription_1.refresh_from_db()
        expired_subscription_2.refresh_from_db()

        self.assertTrue(expired_subscription_1.expiration_processed)
        self.assertFalse(expired_subscription_2.expiration_processed)

    @mock.patch('license_manager.apps.subscriptions.event_utils.track_event')
    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.expire_subscriptions.license_expiration_task'
    )
    def test_expiring_10k_licenses_batched(self, mock_license_expiration_task, mock_track_event):
        """
        Verifies that all expired subscriptions within the expired range have their license uuids sent to edx-enterprise
        """
        # A recently expired subscription that should be processed
        expired_subscription_plan_1 = self._create_expired_plan_with_licenses(
            activated_licenses_count=500
        )
        expired_subscription_plan_2 = self._create_expired_plan_with_licenses(
            activated_licenses_count=500
        )
        allocated_license_count = len(self._get_allocated_license_uuids(expired_subscription_plan_1))

        call_command(self.command_name)
        expected_call_count = math.ceil(allocated_license_count / LICENSE_EXPIRATION_BATCH_SIZE) * 2
        assert expected_call_count == mock_license_expiration_task.call_count

    @mock.patch('license_manager.apps.subscriptions.event_utils.track_event')
    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.expire_subscriptions.license_expiration_task'
    )
    def test_license_expiration_error(self, mock_license_expiration_task, mock_track_event):
        """
        Verifies that expiration_processed is not set to True and license expiration events are not tracked
        if an error occured during license_expiration_task
        """
        mock_license_expiration_task.side_effect = Exception('something terrible went wrong')

        expired_subscription = self._create_expired_plan_with_licenses()

        call_command(self.command_name)
        assert mock_track_event.call_count == 0

        expired_subscription.refresh_from_db()
        assert expired_subscription.expiration_processed is False

    @mock.patch('license_manager.apps.subscriptions.event_utils.track_event')
    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.expire_subscriptions.license_expiration_task'
    )
    def test_license_expiration_tracked(self, _, mock_track_event):
        """
        Verifies that license expiration events are tracked
        """
        expired_subscription = self._create_expired_plan_with_licenses()
        call_command(self.command_name)
        assert mock_track_event.call_count == expired_subscription.licenses.count()

    @mock.patch('license_manager.apps.subscriptions.event_utils.track_event')
    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.expire_subscriptions.license_expiration_task'
    )
    def test_subscription_with_renewal_not_processed(self, mock_license_expiration_task, mock_track_event):
        """
        Verifies that a subscription plan's expiration will not be processed if it has a renewal.
        """

        expired_subscription = self._create_expired_plan_with_licenses()
        SubscriptionPlanRenewalFactory(prior_subscription_plan=expired_subscription)
        call_command(self.command_name)

        expired_subscription.refresh_from_db()
        mock_license_expiration_task.assert_not_called()
        assert expired_subscription.expiration_processed is False

    @mock.patch('license_manager.apps.subscriptions.event_utils.track_event')
    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.expire_subscriptions.license_expiration_task'
    )
    def test_prior_plans_in_renewal_chain_processed(self, mock_license_expiration_task, mock_track_event):
        """
        Verifies that previous subscriptions in a chain of renewals will also be processed when the last plan expires.
        """

        expired_subscription_plan_1 = self._create_expired_plan_with_licenses(
            start_date=localized_datetime(2014, 1, 1),
            expiration_date=localized_datetime(2015, 1, 1)
        )
        expired_subscription_plan_2 = self._create_expired_plan_with_licenses(
            start_date=localized_datetime(2015, 1, 1),
            expiration_date=localized_datetime(2016, 1, 1)
        )
        expired_subscription_plan_3 = self._create_expired_plan_with_licenses()

        SubscriptionPlanRenewalFactory(
            prior_subscription_plan=expired_subscription_plan_1,
            renewed_subscription_plan=expired_subscription_plan_2
        )

        SubscriptionPlanRenewalFactory(
            prior_subscription_plan=expired_subscription_plan_2,
            renewed_subscription_plan=expired_subscription_plan_3
        )

        call_command(self.command_name)

        args_1 = mock_license_expiration_task.call_args_list[0][0][0]
        args_2 = mock_license_expiration_task.call_args_list[1][0][0]
        args_3 = mock_license_expiration_task.call_args_list[2][0][0]
        assert args_1 == self._get_allocated_license_uuids(expired_subscription_plan_3)
        assert args_2 == self._get_allocated_license_uuids(expired_subscription_plan_1)
        assert args_3 == self._get_allocated_license_uuids(expired_subscription_plan_2)
        assert mock_license_expiration_task.call_count == 3
