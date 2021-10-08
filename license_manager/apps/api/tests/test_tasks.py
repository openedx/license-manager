"""
Tests for the license-manager API celery tasks
"""
from smtplib import SMTPException
from unittest import mock
from uuid import uuid4

import pytest
from django.test import TestCase
from freezegun import freeze_time

from license_manager.apps.api import tasks
from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.exceptions import LicenseRevocationError
from license_manager.apps.subscriptions.models import License, SubscriptionPlan
from license_manager.apps.subscriptions.tests.factories import (
    LicenseFactory,
    SubscriptionPlanFactory,
)
from license_manager.apps.subscriptions.tests.utils import (
    assert_date_fields_correct,
    make_test_email_data,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


class EmailTaskTests(TestCase):
    """
    Tests for activation_email_task and send_onboarding_email_task
    """
    def setUp(self):
        super().setUp()
        test_email_data = make_test_email_data()
        self.user_email = 'test_email@example.com'
        self.subscription_plan = test_email_data['subscription_plan']
        self.custom_template_text = test_email_data['custom_template_text']
        self.email_recipient_list = test_email_data['email_recipient_list']
        self.assigned_licenses = self.subscription_plan.licenses.filter(status=constants.ASSIGNED).order_by('uuid')
        self.enterprise_uuid = uuid4()
        self.enterprise_slug = 'mock-enterprise'
        self.enterprise_name = 'Mock Enterprise'
        self.enterprise_sender_alias = 'Mock Enterprise Alias'
        self.reply_to_email = 'edx@example.com'
        self.subscription_plan_type = self.subscription_plan.plan_type.id

    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.send_activation_emails')
    def test_activation_task(self, mock_send_emails, mock_enterprise_client):
        """
        Assert activation_task is called with the correct arguments
        """
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'reply_to': self.reply_to_email,
        }

        tasks.activation_email_task(
            self.custom_template_text,
            self.email_recipient_list,
            self.subscription_plan.uuid,
        )

        send_email_args, _ = mock_send_emails.call_args
        self._verify_mock_send_email_arguments(send_email_args)
        mock_enterprise_client().get_enterprise_customer_data.assert_called_with(
            self.subscription_plan.enterprise_customer_uuid
        )

    @mock.patch('license_manager.apps.api.tasks.logger', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.send_activation_emails', side_effect=SMTPException)
    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    def test_activation_task_send_email_failure_logged(self, mock_enterprise_client, mock_send_emails, mock_logger):
        """
        Tests that when sending the activate email fails, an error gets logged
        """
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'reply_to': self.reply_to_email,
        }

        with mock_send_emails:
            tasks.activation_email_task(
                self.custom_template_text,
                self.email_recipient_list,
                self.subscription_plan.uuid
            )

        mock_logger.error.assert_called_once()

    @mock.patch('license_manager.apps.api.tasks.send_activation_emails')
    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    def test_send_reminder_email_task(self, mock_enterprise_client, mock_send_emails):
        """
        Assert send_reminder_email_task is called with the correct arguments
        """
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'reply_to': self.reply_to_email,
        }
        with freeze_time(localized_utcnow()):
            tasks.send_reminder_email_task(
                self.custom_template_text,
                self.email_recipient_list,
                self.subscription_plan.uuid
            )

            send_email_args, _ = mock_send_emails.call_args
            self._verify_mock_send_email_arguments(send_email_args)
            mock_enterprise_client().get_enterprise_customer_data.assert_called_with(
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
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'reply_to': self.reply_to_email,
        }
        with mock_send_emails:
            tasks.send_reminder_email_task(
                self.custom_template_text,
                self.email_recipient_list,
                self.subscription_plan.uuid
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
            actual_enterprise_sender_alias,
            actual_enterprise_reply_to_email,
            actual_subscription_plan_type,
        ) = send_email_args[:7]

        assert list(self.assigned_licenses) == list(actual_licenses)
        assert self.custom_template_text == actual_template_text
        assert self.enterprise_slug == actual_enterprise_slug
        assert self.enterprise_name == actual_enterprise_name
        assert self.enterprise_sender_alias == actual_enterprise_sender_alias
        assert self.reply_to_email == actual_enterprise_reply_to_email
        assert self.subscription_plan_type == actual_subscription_plan_type

    @mock.patch('license_manager.apps.api.tasks.send_onboarding_email', return_value=mock.MagicMock())
    def test_onboarding_email_task(self, mock_send_onboarding_email):
        """
        Tests that the onboarding email task sends the email
        """
        tasks.send_onboarding_email_task(self.enterprise_uuid, self.user_email, self.subscription_plan_type)
        mock_send_onboarding_email.assert_called_with(
            self.enterprise_uuid,
            self.user_email,
            self.subscription_plan_type,
        )


class RevokeAllLicensesTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        subscription_plan = SubscriptionPlanFactory()
        unassigned_license = LicenseFactory.create(status=constants.UNASSIGNED, subscription_plan=subscription_plan)
        assigned_license = LicenseFactory.create(status=constants.ASSIGNED, subscription_plan=subscription_plan)
        activated_license = LicenseFactory.create(status=constants.ACTIVATED, subscription_plan=subscription_plan)

        cls.subscription_plan = subscription_plan
        cls.unassigned_license = unassigned_license
        cls.assigned_license = assigned_license
        cls.activated_license = activated_license

    def tearDown(self):
        """
        Deletes all licenses, and subscription after each test method is run.
        """
        super().tearDown()
        License.objects.all().delete()
        SubscriptionPlan.objects.all().delete()

    @mock.patch('license_manager.apps.subscriptions.api.execute_post_revocation_tasks')
    @mock.patch('license_manager.apps.subscriptions.api.revoke_license')
    def test_revoke_all_licenses_task(self, mock_revoke_license, mock_execute_post_revocation_tasks):
        """
        Verify that revoke_license and execute_post_revocation_tasks is called for each revocable license
        """
        tasks.revoke_all_licenses_task(self.subscription_plan.uuid)
        assert mock_revoke_license.call_args_list == [
            mock.call(self.assigned_license), mock.call(self.activated_license)]
        assert mock_execute_post_revocation_tasks.call_count == 2

    @mock.patch('license_manager.apps.subscriptions.api.execute_post_revocation_tasks')
    @mock.patch('license_manager.apps.subscriptions.api.revoke_license')
    def test_revoke_all_licenses_task_error(self, mock_revoke_license, mock_execute_post_revocation_tasks):
        """
        Verify that revoke_license handles any errors
        """
        mock_revoke_license.side_effect = [
            LicenseRevocationError(self.assigned_license.uuid, 'something terrible went wrong'),
            None
        ]

        with self.assertLogs(level='INFO') as log, pytest.raises(LicenseRevocationError):
            tasks.revoke_all_licenses_task(self.subscription_plan.uuid)

        assert mock_revoke_license.call_args_list == [
            mock.call(self.assigned_license)]

        assert 'Could not revoke license with uuid {} during revoke_all_licenses_task'.format(
            self.assigned_license.uuid) in log.output[0]

        assert mock_execute_post_revocation_tasks.call_count == 0
