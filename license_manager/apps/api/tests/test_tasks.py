"""
Tests for the license-manager API celery tasks
"""
from unittest import mock

from django.test import TestCase
from pytest import mark

from license_manager.apps.api import tasks
from license_manager.apps.subscriptions.tests.factories import (
    SubscriptionPlanFactory,
)


@mark.django_db
class LicenseManagerCeleryTaskTests(TestCase):
    def setUp(self):
        super().setUp()
        self.subscription_plan = SubscriptionPlanFactory()
        self.custom_template_text = {
            'greeting': 'Hello',
            'closing': 'Goodbye',
        }
        self.email_recipient_list = [
            'boatymcboatface@mit.edu',
            'saul.goodman@bettercallsaul.com',
            't.soprano@badabing.net',
        ]

    @mock.patch('license_manager.apps.api.tasks.SubscriptionPlan.objects.get')
    @mock.patch('license_manager.apps.api.tasks.send_activation_emails')
    def test_send_activation_email_task(self, mock_send_emails, mock_get_subscription):
        """
        Assert send_activation_email_task is called with the correct arguments
        """
        mock_get_subscription.side_effect = [self.subscription_plan]
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

    @mock.patch('license_manager.apps.api.tasks.SubscriptionPlan.objects.get')
    @mock.patch('license_manager.apps.api.tasks.send_reminder_emails')
    def test_send_reminder_email_task(self, mock_send_emails, mock_get_subscription):
        """
        Assert send_reminder_email_task is called with the correct arguments
        """
        mock_get_subscription.side_effect = [self.subscription_plan]
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
