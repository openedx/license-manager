from datetime import timedelta
from unittest import mock
from unittest.mock import call

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.models import LicenseEvent
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    LicenseFactory,
    SubscriptionPlanFactory,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


@pytest.mark.django_db
class TriggerLicenseEventTests(TestCase):

    def setUp(self):
        super().setUpTestData()

        self.command_name = 'trigger_event_for_licenses'

        now = localized_utcnow()

        enterprise_customer_uuids = settings.CUSTOMERS_WITH_CUSTOM_LICENSE_EVENTS

        customer_agreement = CustomerAgreementFactory(enterprise_customer_uuid=enterprise_customer_uuids[0])
        subscription_plan_1 = SubscriptionPlanFactory(customer_agreement=customer_agreement)
        subscription_plan_2 = SubscriptionPlanFactory(customer_agreement=customer_agreement)

        self.unassigned_license = LicenseFactory.create(
            status=constants.UNASSIGNED,
            subscription_plan=subscription_plan_1
        )
        self.assigned_license = LicenseFactory.create(
            status=constants.ASSIGNED,
            subscription_plan=subscription_plan_1
        )
        self.activated_license_1 = LicenseFactory(
            lms_user_id=100,
            status=constants.ACTIVATED,
            subscription_plan=subscription_plan_2,
            activation_date=(now - timedelta(days=190)),
        )
        self.activated_license_2 = LicenseFactory(
            lms_user_id=200,
            status=constants.ACTIVATED,
            subscription_plan=subscription_plan_2,
            activation_date=(now - timedelta(days=100)),
        )
        self.activated_license_3 = LicenseFactory(
            lms_user_id=300,
            status=constants.ACTIVATED,
            subscription_plan=subscription_plan_1,
            activation_date=(now - timedelta(days=185)),
        )

        self.customer_agreement = customer_agreement
        self.subscription_plan_1 = subscription_plan_1
        self.subscription_plan_2 = subscription_plan_2

    @mock.patch('license_manager.apps.subscriptions.management.commands.trigger_event_for_licenses.track_event')
    def test_dry_run(self, mock_track_event):
        """
        Tests that no events were triggered in dry run.
        """
        call_command(self.command_name, '--dry-run')
        assert mock_track_event.call_count == 0

    @mock.patch('license_manager.apps.subscriptions.management.commands.trigger_event_for_licenses.track_event')
    def test_trigger_events(self, mock_track_event):
        """
        Tests that correct segment events were triggered.
        """
        call_command(self.command_name)
        assert mock_track_event.call_count == 2
        expected_calls = [
            call(
                self.activated_license_1.lms_user_id,
                'edx.server.license-manager.license.activated.180.days.ago',
                {'user_email': self.activated_license_1.user_email}
            ),
            call(
                self.activated_license_3.lms_user_id,
                'edx.server.license-manager.license.activated.180.days.ago',
                {'user_email': self.activated_license_3.user_email}
            ),
        ]
        mock_track_event.assert_has_calls(expected_calls, any_order=True)
        sent_events = LicenseEvent.objects.all()
        assert sent_events.count() == 2
        license_uuids = []
        for sent_event in sent_events:
            assert sent_event.event_name == 'edx.server.license-manager.license.activated.180.days.ago'
            assert sent_event.license.status == constants.ACTIVATED
            license_uuids.append(sent_event.license.uuid)

        assert sorted(license_uuids) == sorted([self.activated_license_1.uuid, self.activated_license_3.uuid])

        mock_track_event.reset_mock()
        # call the command again to ensure that the same events are not triggered again
        call_command(self.command_name)
        assert mock_track_event.call_count == 0
