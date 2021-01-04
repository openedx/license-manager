"""
Tests for the license-manager API celery tasks
"""
from smtplib import SMTPException
from unittest import mock

from django.test import TestCase

from license_manager.apps.api import tasks
from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.tests.utils import (
    assert_date_fields_correct,
    make_test_email_data,
)


class LicenseManagerCeleryTaskTests(TestCase):
    def setUp(self):
        super().setUp()
        test_email_data = make_test_email_data()
        self.subscription_plan = test_email_data['subscription_plan']
        self.custom_template_text = test_email_data['custom_template_text']
        self.email_recipient_list = test_email_data['email_recipient_list']
        self.assigned_licenses = self.subscription_plan.licenses.filter(status=constants.ASSIGNED).order_by('uuid')
        self.enterprise_slug = 'mock-enterprise'
        self.enterprise_name = 'Mock Enterprise'

    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.send_activation_emails')
    def test_activation_task(self, mock_send_emails, mock_enterprise_client):
        """
        Assert activation_task is called with the correct arguments
        """
        mock_enterprise_client().get_enterprise_slug.return_value = self.enterprise_slug
        mock_enterprise_client().get_enterprise_name.return_value = self.enterprise_name
        tasks.activation_task(
            self.custom_template_text,
            self.email_recipient_list,
            str(self.subscription_plan.uuid)
        )

        send_email_args, _ = mock_send_emails.call_args
        self._verify_mock_send_email_arguments(send_email_args)
        mock_enterprise_client().get_enterprise_slug.assert_called_with(
            self.subscription_plan.enterprise_customer_uuid
        )

        # Verify a call is made to create a pending enterprise user for each user_email specified
        for recipient in self.email_recipient_list:
            mock_enterprise_client().create_pending_enterprise_user.assert_any_call(
                self.subscription_plan.enterprise_customer_uuid,
                recipient,
            )

        # Verify the 'last_remind_date' and 'assigned_date' of all licenses have been updated
        assert_date_fields_correct(send_email_args[1], ['last_remind_date', 'assigned_date'], True)

    @mock.patch('license_manager.apps.api.tasks.send_activation_emails')
    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    def test_send_reminder_email_task(self, mock_enterprise_client, mock_send_emails):
        """
        Assert send_reminder_email_task is called with the correct arguments
        """
        mock_enterprise_client().get_enterprise_slug.return_value = self.enterprise_slug
        mock_enterprise_client().get_enterprise_name.return_value = self.enterprise_name
        tasks.send_reminder_email_task(
            self.custom_template_text,
            self.email_recipient_list,
            str(self.subscription_plan.uuid)
        )

        send_email_args, _ = mock_send_emails.call_args
        self._verify_mock_send_email_arguments(send_email_args)
        mock_enterprise_client().get_enterprise_slug.assert_called_with(
            self.subscription_plan.enterprise_customer_uuid
        )
        # Verify the 'last_remind_date' of all licenses have been updated
        assert_date_fields_correct(send_email_args[1], ['last_remind_date'], True)

    @mock.patch('license_manager.apps.api.tasks.send_activation_emails', side_effect=SMTPException)
    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    def test_send_reminder_email_failure_no_remind_date_update(self, mock_enterprise_client, mock_send_emails):
        """
        Tests that when sending the remind email fails, last_remind_date is not updated
        """
        mock_enterprise_client().get_enterprise_slug.return_value = self.enterprise_slug
        mock_enterprise_client().get_enterprise_name.return_value = self.enterprise_name
        with mock_send_emails:
            tasks.send_reminder_email_task(
                self.custom_template_text,
                self.email_recipient_list,
                str(self.subscription_plan.uuid)
            )
            send_email_args, _ = mock_send_emails.call_args
            assert_date_fields_correct(send_email_args[1], ['last_remind_date'], False)

    def _verify_mock_send_email_arguments(self, send_email_args):
        """
        Verifies that the arguments passed into send_activation_emails is correct
        """
        (
            actual_template_text,
            actual_licenses,
            actual_enterprise_slug,
            actual_enterprise_name,
        ) = send_email_args[:5]

        assert list(self.assigned_licenses) == list(actual_licenses)
        assert self.custom_template_text == actual_template_text
        assert self.enterprise_slug == actual_enterprise_slug
        assert self.enterprise_name == actual_enterprise_name
