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
        subscription_plan_1_details = {
            'uuid': subscription_plan_1.uuid,
            'title': subscription_plan_1.title,
            'enterprise_customer_uuid': subscription_plan_1.enterprise_customer_uuid,
            'enterprise_customer_name': subscription_plan_1.customer_agreement.enterprise_customer_name,
            'num_allocated_licenses': subscription_plan_1.num_allocated_licenses,
            'num_licenses': subscription_plan_1.num_licenses,
            'highest_utilization_threshold_reached': subscription_plan_1.highest_utilization_threshold_reached
        }
        subscription_plan_2_details = {
            'uuid': subscription_plan_2.uuid,
            'title': subscription_plan_2.title,
            'enterprise_customer_uuid': subscription_plan_2.enterprise_customer_uuid,
            'enterprise_customer_name': subscription_plan_2.customer_agreement.enterprise_customer_name,
            'num_allocated_licenses': subscription_plan_2.num_allocated_licenses,
            'num_licenses': subscription_plan_2.num_licenses,
            'highest_utilization_threshold_reached': subscription_plan_2.highest_utilization_threshold_reached
        }

        cls.customer_agreement = customer_agreement
        cls.subscription_plan_1 = subscription_plan_1
        cls.subscription_plan_2 = subscription_plan_2
        cls.subscription_plan_1_details = subscription_plan_1_details
        cls.subscription_plan_2_details = subscription_plan_2_details

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

    @mock.patch('license_manager.apps.subscriptions.management.commands.send_license_utilization_emails.send_weekly_utilization_email_task')
    @mock.patch('license_manager.apps.subscriptions.management.commands.send_license_utilization_emails.send_utilization_threshold_reached_email_task')
    @mock.patch('license_manager.apps.subscriptions.management.commands.send_license_utilization_emails.EnterpriseApiClient')
    def test_send_emails_success(
        self,
        mock_enterprise_client,
        mock_send_utilization_threshold_reached_email_task,
        mock_send_weekly_utilization_email_task
    ):
        """
        Tests that a call is made to get the enterprise admin users, then send_weekly_utilization_email_task and send_utilization_threshold_reached_email_task
        are called.
        """
        mock_get_enterprise_admin_users = mock_enterprise_client.return_value.get_enterprise_admin_users
        mock_get_enterprise_admin_users.return_value = []
        self.subscription_plan_1.should_auto_apply_licenses = True
        self.subscription_plan_1.save()

        call_command(self.command_name)

        mock_get_enterprise_admin_users.assert_called_with(self.customer_agreement.enterprise_customer_uuid)
        mock_send_utilization_threshold_reached_email_task.delay.assert_called_with(self.subscription_plan_1_details, [])
        mock_send_weekly_utilization_email_task.delay.assert_called_with(self.subscription_plan_1_details, [])

    @mock.patch('license_manager.apps.subscriptions.management.commands.send_license_utilization_emails.send_weekly_utilization_email_task')
    @mock.patch('license_manager.apps.subscriptions.management.commands.send_license_utilization_emails.send_utilization_threshold_reached_email_task')
    @mock.patch('license_manager.apps.subscriptions.management.commands.send_license_utilization_emails.EnterpriseApiClient')
    def test_send_emails_enterprise_api_failure(
        self,
        mock_enterprise_client,
        mock_send_utilization_threshold_reached_email_task,
        mock_send_weekly_utilization_email_task
    ):
        """
        Tests that an error retrieving admins for one enterprise customer does not stop the command.
        """

        mock_get_enterprise_admin_users = mock_enterprise_client.return_value.get_enterprise_admin_users
        mock_get_enterprise_admin_users.side_effect = [Exception("oops"), []]

        self.subscription_plan_1.should_auto_apply_licenses = True
        self.subscription_plan_2.should_auto_apply_licenses = True
        self.subscription_plan_1.save()
        self.subscription_plan_2.save()

        call_command(self.command_name)

        assert mock_get_enterprise_admin_users.call_count == 2
        assert mock_send_utilization_threshold_reached_email_task.delay.call_count == 1
        assert mock_send_weekly_utilization_email_task.delay.call_count == 1
        mock_send_utilization_threshold_reached_email_task.delay.assert_called_with(self.subscription_plan_2_details, [])
        mock_send_weekly_utilization_email_task.delay.assert_called_with(self.subscription_plan_2_details, [])

    @mock.patch('license_manager.apps.subscriptions.management.commands.send_license_utilization_emails.send_weekly_utilization_email_task')
    @mock.patch('license_manager.apps.subscriptions.management.commands.send_license_utilization_emails.send_utilization_threshold_reached_email_task')
    @mock.patch('license_manager.apps.subscriptions.management.commands.send_license_utilization_emails.EnterpriseApiClient')
    def test_send_emails_admin_users_already_retrieved(
        self,
        mock_enterprise_client,
        mock_send_utilization_threshold_reached_email_task,
        mock_send_weekly_utilization_email_task
    ):
        """
        Tests that duplicate calls to retrieve admins for the same enterprise are not made.
        """

        mock_get_enterprise_admin_users = mock_enterprise_client.return_value.get_enterprise_admin_users
        mock_get_enterprise_admin_users.return_value = []

        self.subscription_plan_1.should_auto_apply_licenses = True
        self.subscription_plan_2.should_auto_apply_licenses = True
        self.subscription_plan_1.save()
        self.subscription_plan_2.save()

        call_command(self.command_name)

        assert mock_get_enterprise_admin_users.call_count == 1
