from datetime import timedelta
from unittest import mock

import freezegun
import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from license_manager.apps.subscriptions.api import RenewalProcessingError
from license_manager.apps.subscriptions.constants import (
    PROCESS_SUBSCRIPTION_RENEWAL_AUTO_RENEWED,
)
from license_manager.apps.subscriptions.models import (
    License,
    SubscriptionPlan,
    SubscriptionPlanRenewal,
)
from license_manager.apps.subscriptions.tests.factories import (
    SubscriptionPlanFactory,
    SubscriptionPlanRenewalFactory,
    UserFactory,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


@pytest.mark.django_db
class ProcessRenewalsCommandTests(TestCase):
    command_name = 'process_renewals'
    now = localized_utcnow()

    def tearDown(self):
        """
        Deletes all renewals, licenses, and subscription after each test method is run.
        """
        super().tearDown()
        License.objects.all().delete()
        SubscriptionPlan.objects.all().delete()
        SubscriptionPlanRenewal.objects.all().delete()

    def create_subscription_with_renewal(self, effective_date, processed=False):
        prior_subscription_plan = SubscriptionPlanFactory.create(
            start_date=self.now - timedelta(days=7),
            expiration_date=self.now,
        )

        renewed_subscription_plan = SubscriptionPlanFactory.create(
            start_date=self.now,
            expiration_date=self.now + timedelta(days=7),
        )

        SubscriptionPlanRenewalFactory.create(
            prior_subscription_plan=prior_subscription_plan,
            renewed_subscription_plan=renewed_subscription_plan,
            effective_date=effective_date,
            processed=processed
        )

        return (prior_subscription_plan)

    @mock.patch('license_manager.apps.subscriptions.management.commands.process_renewals.renew_subscription')
    def test_no_upcoming_renewals(self, mock_renew_subscription):
        """
        Verify that only unprocessed renewals within their processing window are processed
        """
        with self.assertLogs(level='INFO') as log, freezegun.freeze_time(self.now):
            # renewal far in the future
            self.create_subscription_with_renewal(
                self.now + timedelta(hours=settings.SUBSCRIPTION_PLAN_RENEWAL_LOCK_PERIOD_HOURS) + timedelta(seconds=1))

            # renewal in the past
            self.create_subscription_with_renewal(self.now - timedelta(seconds=1))

            # renewal that has already been processed
            self.create_subscription_with_renewal(self.now + timedelta(seconds=1), processed=True)

            call_command(self.command_name)
            assert mock_renew_subscription.call_count == 0
            assert 'Processing 0 renewals for subscriptions with uuids: []' in log.output[0]
            assert 'Processed 0 renewals for subscriptions with uuids: []' in log.output[1]

    @mock.patch('license_manager.apps.subscriptions.management.commands.process_renewals.renew_subscription')
    def test_upcoming_renewals(self, mock_renew_subscription):
        """
        Verify that unprocessed renewals within their processing window are processed
        """
        subscription_plan_1 = self.create_subscription_with_renewal(
            self.now + timedelta(hours=settings.SUBSCRIPTION_PLAN_RENEWAL_LOCK_PERIOD_HOURS))

        subscription_plan_2 = self.create_subscription_with_renewal(self.now + timedelta(seconds=1))

        with self.assertLogs(level='INFO') as log, freezegun.freeze_time(self.now):
            call_command(self.command_name)
            assert mock_renew_subscription.call_count == 2
            assert "Processing 2 renewals for subscriptions with uuids: ['{}', '{}']".format(
                subscription_plan_1.uuid, subscription_plan_2.uuid) in log.output[0]
            assert "Processed 2 renewals for subscriptions with uuids: ['{}', '{}']".format(
                subscription_plan_1.uuid, subscription_plan_2.uuid) in log.output[1]

    @mock.patch('license_manager.apps.subscriptions.management.commands.process_renewals.renew_subscription')
    def test_renew_subscription_exception(self, mock_renew_subscription):
        """
        Verify that an exception when processing a renewal will not stop other renewals from being processed
        """
        mock_renew_subscription.side_effect = [RenewalProcessingError, None]

        subscription_plan_1 = self.create_subscription_with_renewal(
            self.now + timedelta(hours=settings.SUBSCRIPTION_PLAN_RENEWAL_LOCK_PERIOD_HOURS))

        subscription_plan_2 = self.create_subscription_with_renewal(self.now + timedelta(seconds=1))

        with self.assertLogs(level='INFO') as log, freezegun.freeze_time(self.now):
            call_command(self.command_name)
            assert mock_renew_subscription.call_count == 2
            assert "Processing 2 renewals for subscriptions with uuids: ['{}', '{}']".format(
                subscription_plan_1.uuid, subscription_plan_2.uuid) in log.output[0]
            assert "Could not automatically process renewal with id: {}".format(subscription_plan_1.renewal.id) in log.output[1]
            assert "Processed 1 renewals for subscriptions with uuids: ['{}']".format(subscription_plan_2.uuid) in log.output[2]

    @mock.patch('license_manager.apps.subscriptions.management.commands.process_renewals.renew_subscription')
    @mock.patch('license_manager.apps.subscriptions.management.commands.process_renewals.track_event')
    def test_track_subscription_renewal(self, mock_track_event, mock_renew_subscription):
        """
        Verify that a segment event is sent if the license_manager_worker user exists and a subscription is renewed
        """
        subscription_plan_1 = self.create_subscription_with_renewal(
            self.now + timedelta(hours=settings.SUBSCRIPTION_PLAN_RENEWAL_LOCK_PERIOD_HOURS))

        worker = UserFactory.create(username='license_manager_worker')

        with freezegun.freeze_time(self.now):
            call_command(self.command_name)
            assert mock_renew_subscription.call_count == 1
            assert mock_track_event.call_count == 1
            mock_track_event.assert_called_with(worker.id, PROCESS_SUBSCRIPTION_RENEWAL_AUTO_RENEWED, {
                'user_id': worker.id,
                'prior_subscription_plan_id': str(subscription_plan_1.uuid),
                'renewed_subscription_plan_id': str(subscription_plan_1.renewal.renewed_subscription_plan.uuid)
            })
