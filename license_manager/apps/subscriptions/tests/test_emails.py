from unittest import mock
from uuid import uuid4

from django.core import mail
from django.test import TestCase

from license_manager.apps.subscriptions import constants, emails
from license_manager.apps.subscriptions.tests.factories import (
    SubscriptionPlanFactory,
)
from license_manager.apps.subscriptions.tests.utils import make_test_email_data


LICENSE_ACTIVATION_EMAIL_SUBJECT = 'Start your edX Subscription'
LICENSE_REMINDER_EMAIL_SUBJECT = 'Your edX License is pending'
ONBOARDING_EMAIL_SUBJECT = 'Welcome to edX Subscriptions!'
REVOCATION_CAP_NOTIFICATION_EMAIL_SUBJECT = 'REVOCATION CAP REACHED: {}'


class EmailTests(TestCase):
    def setUp(self):
        super().setUp()
        test_email_data = make_test_email_data()
        self.user_email = 'emailtest@example.com'
        self.subscription = SubscriptionPlanFactory.create()
        self.subscription_plan = test_email_data['subscription_plan']
        self.licenses = test_email_data['licenses']
        self.custom_template_text = test_email_data['custom_template_text']
        self.enterprise_uuid = uuid4()
        self.enterprise_slug = 'mock-enterprise'
        self.email_recipient_list = test_email_data['email_recipient_list']
        self.enterprise_name = 'Mock Enterprise'
        self.enterprise_sender_alias = 'Mock Enterprise Alias'
        self.reply_to_email = 'edx@example.com'
        self.subscription_plan_type = self.subscription.plan_type.id

    def test_send_activation_emails(self):
        """
        Tests that activation emails are correctly sent.
        """
        emails.send_activation_emails(
            self.custom_template_text,
            [license for license in self.licenses if license.status == constants.ASSIGNED],
            self.enterprise_slug,
            self.enterprise_name,
            self.enterprise_sender_alias,
            self.reply_to_email,
            self.subscription_plan_type,
        )
        self.assertEqual(
            len(mail.outbox),
            len(self.email_recipient_list)
        )
        # Verify the contents of the first message
        message = mail.outbox[0]
        self.assertEqual(message.subject, LICENSE_ACTIVATION_EMAIL_SUBJECT)
        self.assertTrue('Activate' in message.body)

    def test_send_reminder_email(self):
        """
        Tests that reminder emails are correctly sent.
        """
        lic = self.licenses[0]
        emails.send_activation_emails(
            self.custom_template_text,
            [lic],
            self.enterprise_slug,
            self.enterprise_name,
            self.enterprise_sender_alias,
            self.reply_to_email,
            self.subscription_plan_type,
            is_reminder=True,
        )
        self.assertEqual(len(mail.outbox), 1)
        # Verify the contents of the first message
        message = mail.outbox[0]
        self.assertEqual(message.subject, LICENSE_REMINDER_EMAIL_SUBJECT)
        self.assertFalse('Activate' in message.body)

    @mock.patch('license_manager.apps.subscriptions.emails.EnterpriseApiClient')
    def test_onboarding_email(self, mock_enterprise_api_client):
        """
        Tests that onboarding emails are correctly sent.
        """
        emails.send_onboarding_email(self.enterprise_uuid, self.user_email, self.subscription_plan_type)
        mock_enterprise_api_client.return_value.get_enterprise_customer_data.assert_called_with(self.enterprise_uuid)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, ONBOARDING_EMAIL_SUBJECT)
