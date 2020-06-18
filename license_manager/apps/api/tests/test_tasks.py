"""
Tests for the license-manager API celery tasks
"""
from unittest import mock

from django.test import TestCase

from license_manager.apps.api import tasks
from license_manager.apps.subscriptions.tests.utils import make_test_email_data


class LicenseManagerCeleryTaskTests(TestCase):
    def setUp(self):
        super().setUp()
        test_email_data = make_test_email_data()
        self.subscription_plan = test_email_data['subscription_plan']
        self.custom_template_text = test_email_data['custom_template_text']
        self.email_recipient_list = test_email_data['email_recipient_list']

    @mock.patch('license_manager.apps.api.tasks.send_activation_emails')
    def test_send_activation_email_task(self, mock_send_emails):
        """
        Assert send_activation_email_task is called with the correct arguments
        """
        tasks.send_activation_email_task(
            self.custom_template_text,
            self.email_recipient_list,
            str(self.subscription_plan.uuid)
        )
        mock_send_emails.assert_called_with(
            self.custom_template_text,
            self.email_recipient_list,
            self.subscription_plan
        )

    @mock.patch('license_manager.apps.api.tasks.send_reminder_emails')
    def test_send_reminder_email_task(self, mock_send_emails):
        """
        Assert send_reminder_email_task is called with the correct arguments
        """
        tasks.send_reminder_email_task(
            self.custom_template_text,
            self.email_recipient_list,
            str(self.subscription_plan.uuid)
        )
        mock_send_emails.assert_called_with(
            self.custom_template_text,
            self.email_recipient_list,
            self.subscription_plan
        )
