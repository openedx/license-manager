from uuid import uuid4

import mock
from django.conf import settings
from django.core import mail
from django.test import TestCase

from license_manager.apps.subscriptions import constants, emails
from license_manager.apps.subscriptions.tests.utils import make_test_email_data


class EmailTests(TestCase):
    def setUp(self):
        super().setUp()
        test_email_data = make_test_email_data()
        self.subscription_plan = test_email_data['subscription_plan']
        self.licenses = test_email_data['licenses']
        self.custom_template_text = test_email_data['custom_template_text']
        self.enterprise_slug = 'mock-enterprise'
        self.email_recipient_list = test_email_data['email_recipient_list']

    def test_send_activation_emails(self):
        """
        Tests that activation emails are correctly sent.
        """
        emails.send_activation_emails(
            self.custom_template_text,
            [license for license in self.licenses if license.status == constants.ASSIGNED],
            self.subscription_plan,
            self.enterprise_slug
        )
        self.assertEqual(
            len(mail.outbox),
            len(self.email_recipient_list)
        )
        # Verify the contents of the first message
        message = mail.outbox[0]
        self.assertEqual(message.subject, constants.LICENSE_ACTIVATION_EMAIL_SUBJECT)
        self.assertFalse('Reminder' in message.body)

    def test_send_reminder_email(self):
        """
        Tests that reminder emails are correctly sent.
        """
        lic = self.licenses[0]
        emails.send_activation_emails(
            self.custom_template_text,
            [lic],
            lic.subscription_plan,
            self.enterprise_slug,
            True
        )
        self.assertEqual(len(mail.outbox), 1)
        # Verify the contents of the first message
        message = mail.outbox[0]
        self.assertEqual(message.subject, constants.LICENSE_REMINDER_EMAIL_SUBJECT)
        # Verify that 'Reminder' does show up for the reminder case
        self.assertTrue('Reminder' in message.body)
