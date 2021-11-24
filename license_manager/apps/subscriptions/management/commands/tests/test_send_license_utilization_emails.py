from unittest import mock

import pytest
from django.core.management import call_command
from django.test import TestCase

from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    SubscriptionPlan,
)
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    SubscriptionPlanFactory,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


@pytest.mark.django_db
class SendLicenseUtilizationEmailsTests(TestCase):
    command_name = 'send_license_utilization_emails'
    now = localized_utcnow()

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        customer_agreement = CustomerAgreementFactory()
        subscription_plan_1 = SubscriptionPlanFactory(customer_agreement=customer_agreement)
        subscription_plan_2 = SubscriptionPlanFactory(customer_agreement=customer_agreement)
        cls.customer_agreement = customer_agreement
        cls.subscription_plan_1 = subscription_plan_1
        cls.subscription_plan_2 = subscription_plan_2

    def tearDown(self):
        """
        Deletes all renewals, licenses, and subscription after each test method is run.
        """
        super().tearDown()
        CustomerAgreement.objects.all().delete()
        SubscriptionPlan.objects.all().delete()

    def test_send_emails_no_auto_apply_subscriptions(self):
        """
        Tests that the rest of the command is skipped if there are no subscriptions with auto-applied licenses.
        """
        with self.assertLogs(level='INFO') as log:
            call_command(self.command_name)
            assert 'No subscriptions with auto-applied licenses found, skipping license-utilization emails.' in log.output[0]

    @mock.patch('license_manager.apps.subscriptions.management.commands.send_license_utilization_emails.send_initial_utilization_email_task')
    def test_send_emails_success(
        self,
        mock_send_initial_utilization_email_task
    ):
        """
        Tests that send_initial_utilization_email_task is called.
        """
        self.subscription_plan_1.should_auto_apply_licenses = True
        self.subscription_plan_1.save()

        call_command(self.command_name)
        mock_send_initial_utilization_email_task.delay.assert_called_once_with(self.subscription_plan_1.uuid)
